import os
import logging

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("lingua-bridge")

LLM_URL = os.getenv("VLLM_URL", "http://host.docker.internal:11435/v1/chat/completions")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen3:8b-q4_K_M")

app = FastAPI()

_cache: dict[tuple[str, str, str], str] = {}


async def translate(text: str, source_lang: str, target_lang: str) -> str:
    if source_lang == target_lang:
        return text

    key = (text, source_lang, target_lang)
    if key in _cache:
        return _cache[key]

    system_prompt = (
        f"You are a translation engine embedded in a chat between a college proctor and a parent. "
        f"Translate the user's message from {source_lang} to {target_lang}. "
        f"Preserve the original meaning, intent, and tone exactly - do not add, omit, soften, or exaggerate anything. "
        f"Use a respectful, formal register appropriate for addressing a parent or elder "
        f"(e.g. formal 'you' forms where the target language distinguishes them, such as 'நீங்கள்' not 'நீ' in Tamil, or 'आप' not 'तू/तुम' in Hindi). "
        f"The input may mix languages in a single sentence (e.g. English words inside a Tamil sentence) - "
        f"translate the full meaning naturally into {target_lang}, not word-by-word. "
        f"Keep proper nouns, names, dates, numbers, and amounts exactly as written. "
        f"If the message is a question, keep it phrased as a question. "
        f"If any part is unclear or ambiguous, translate your best interpretation rather than asking for clarification. "
        f"Reply with ONLY the translation - no quotes, no explanation, no preamble."
        
    )
   
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        "max_tokens": 512,
        "temperature": 0.2,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(LLM_URL, json=payload)
        resp.raise_for_status()
        data = resp.json()

    translated = data["choices"][0]["message"]["content"].strip()
    _cache[key] = translated
    return translated


class ConnectionManager:
    """Tracks the two chat roles (A and B) and their live WebSocket."""

    def __init__(self) -> None:
        self.connections: dict[str, WebSocket] = {}

    async def connect(self, role: str, ws: WebSocket) -> None:
        await ws.accept()
        self.connections[role] = ws

    def disconnect(self, role: str) -> None:
        self.connections.pop(role, None)

    async def send(self, role: str, message: dict) -> None:
        ws = self.connections.get(role)
        if ws is not None:
            await ws.send_json(message)


manager = ConnectionManager()


@app.websocket("/ws/{role}")
async def ws_endpoint(websocket: WebSocket, role: str):
    if role not in ("A", "B"):
        await websocket.close(code=4000)
        return

    other_role = "B" if role == "A" else "A"
    await manager.connect(role, websocket)
    log.info("role %s connected", role)

    try:
        while True:
            data = await websocket.receive_json()
            text = (data.get("text") or "").strip()
            source_lang = data.get("source_lang", "English")
            target_lang = data.get("target_lang", "English")
            if not text:
                continue

            # Echo the message back to the sender immediately, in their own language.
            await manager.send(role, {"type": "own", "text": text})

            try:
                translated = await translate(text, source_lang, target_lang)
                await manager.send(
                    other_role,
                    {"type": "incoming", "text": translated, "source_lang": source_lang},
                )
            except Exception as exc:  # noqa: BLE001
                log.exception("translation failed")
                await manager.send(
                    other_role,
                    {"type": "error", "detail": "Translation service unavailable."},
                )
                await manager.send(
                    role,
                    {"type": "error", "detail": f"Couldn't translate: {exc}"},
                )
    except WebSocketDisconnect:
        manager.disconnect(role)
        log.info("role %s disconnected", role)


# Serve the static frontend last, so it doesn't shadow the /ws routes.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
