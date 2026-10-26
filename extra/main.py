# ── Standard library ─────────────────────────────────────────────────
import asyncio
import hashlib
import json
import logging
import os
import threading
import time
os.environ["HF_HUB_DISABLE_XET"] = "1"
import re
import socket
import subprocess
import tempfile
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

# ── Third-party ───────────────────────────────────────────────────────
from dotenv import load_dotenv

load_dotenv()

import httpx
import torch
import whisper
import uvicorn

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel

from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_ollama import ChatOllama
from langchain_classic.chains import create_history_aware_retriever, create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_classic.prompts import ChatPromptTemplate, MessagesPlaceholder

from qdrant_client import QdrantClient
from langchain_qdrant import QdrantVectorStore, FastEmbedSparse

from FlagEmbedding import BGEM3FlagModel
from langchain_core.embeddings import Embeddings

# ── Local modules ─────────────────────────────────────────────────────
from db_memory import load_memory, save_memory_summary
from router import route_query
from reminder_service import (
    parse_iso_datetime,
    get_now_tz,
    normalize_event_name,
    create_reminder,
    get_upcoming_reminders,
    cancel_reminder,
    get_notifications,
    mark_notification_read,
    snooze_reminder,
    get_user_preference,
    save_user_preference,
    connect_google_oauth,
    disconnect_google_oauth,
    ensure_indexes,
)
from google_calendar import get_auth_url, create_calendar_event
from admin.admin_vectordb import router as admin_vectordb_router

BASE_DIR = Path(__file__).resolve().parent

# Hierarchical ingestion is persisted in MongoDB/Qdrant.
# Do not load legacy child/grandchild JSON stores at import time.

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ── Force IPv4 ────────────────────────────────────────────────────────
_orig_getaddrinfo = socket.getaddrinfo
def _patched_getaddrinfo(*args, **kwargs):
    return [r for r in _orig_getaddrinfo(*args, **kwargs) if r[0] == socket.AF_INET]
socket.getaddrinfo = _patched_getaddrinfo

# ── Constants ─────────────────────────────────────────────────────────
ACADEMIC_EVENT_TYPES = {
    "exam", "assignment", "fee", "project_submission",
    "registration", "placement", "workshop", "seminar", "event",
}

SUPPORTED_LANGUAGES = {"en", "ta", "hi", "te", "kn", "ml"}
LANGUAGE_ALIASES = {
    "english": "en", "eng": "en",
    "tamil": "ta", "tam": "ta",
    "hindi": "hi", "hin": "hi",
    "telugu": "te", "tel": "te",
    "kannada": "kn", "kan": "kn",
    "malayalam": "ml", "mal": "ml",
}

HISTORY_WINDOW = 6  # aligned with db_memory load limit
RAG_TIMEOUT = 500
REMINDER_LLM_TIMEOUT = 500
TONE_TIMEOUT = 500

# FIX: previously each stage had its own generous (500s) timeout but nothing
# capped the *sum* — a request could legitimately hang for many minutes
# before failing. This is a soft aggregate budget checked between stages;
# once exceeded, we bail out early with the same "taking longer than
# expected" message rather than letting the next 500s-timeout stage start.
REQUEST_TOTAL_BUDGET_MS = int(os.getenv("REQUEST_TOTAL_BUDGET_MS", "90000"))

# Remote reranker service (see app.py on the GPU box)
RERANKER_URL = os.getenv("RERANKER_URL", "http://localhost:8003")
RERANKER_TIMEOUT = float(os.getenv("RERANKER_TIMEOUT", "30"))



# FIX: postMessage('*') in the Google OAuth callback page let ANY page that
# ends up with a reference to that popup receive the connection-success
# signal. Restrict to the actual frontend origin.
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "")
if not FRONTEND_ORIGIN:
    logger.warning(
        "[startup] FRONTEND_ORIGIN is not set — Google OAuth callback will "
        "fall back to a same-origin postMessage target, which may not match "
        "your actual frontend. Set FRONTEND_ORIGIN in the env."
    )

# FIX: no cap previously existed on /api/transcribe uploads — a large file
# could be read entirely into memory with no limit (trivial DoS vector).
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))  # 25 MB

# ── App setup ─────────────────────────────────────────────────────────
os.environ["PATH"] += os.pathsep + str(Path(__file__).resolve().parent / "ffmpeg_bin")
os.environ["ANONYMIZED_TELEMETRY"] = "False"

app = FastAPI()

# NOTE: allow_origins=["*"] combined with allow_credentials=True is invalid
# per the CORS spec — browsers (via Starlette) will reflect the request's
# Origin header back, which effectively allows credentialed requests from
# ANY origin. This app authenticates via userId in the request body, not
# cookies, so credentials aren't needed here. If you later add cookie-based
# auth, allow_origins must become an explicit allow-list instead of "*".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── MongoDB ───────────────────────────────────────────────────────────
mongo_client = AsyncIOMotorClient("mongodb://localhost:27017")
db = mongo_client["chatbot_db"]
messages_collection = db["messages"]
chats_collection = db["chats"]

# ── Models / globals ──────────────────────────────────────────────────

rag_chain = None
hybrid_store = None
retriever = None
history_aware_retriever = None
question_answer_chain = None
query_rewrite_chain = None
reranker_http_client: httpx.AsyncClient | None = None

llm = ChatOllama(
    model="qwen3:8b-q4_K_M",
    base_url="http://localhost:11435",
    temperature=0,
    extra_body={"think": False},
    timeout=550,
)

whisper_model = whisper.load_model("small")
_whisper_executor = ThreadPoolExecutor(max_workers=1)
# FIX: ffmpeg subprocess + wave/numpy silence check were both run
# synchronously inside an `async def` handler, blocking the whole event
# loop (and therefore every other in-flight request) for however long
# ffmpeg/analysis took. Route them through this executor too.
_blocking_io_executor = ThreadPoolExecutor(max_workers=2)

device = "cuda" if torch.cuda.is_available() else "cpu"



# ── Helpers ───────────────────────────────────────────────────────────
async def handle_meta_query(query: str):
    q = query.lower()
    if any(x in q for x in ["language", "speak", "talk", "understand"]):
        return (
            "🌍 I can communicate in multiple languages, including "
            "English, Tamil, Hindi, Telugu, Kannada, and Malayalam. 😊\n\n"
            "Feel free to ask your questions in the language you're most comfortable with. "
            "Whether you need information about academics, fees, hostel facilities, clubs, "
            "contacts, or university procedures, I'm here to help!"
        )
    if any(x in q for x in ["what can you do", "help", "capabilities"]):
        return (
            "🤖 I'm your VIT Assistant, here to support you with university-related information and guidance.\n\n"
            "I can help you with:\n"
            "📚 Academic regulations, policies, and procedures\n"
            "💰 Fees, admissions, scholarships, and deadlines\n"
            "🏠 Hostel information, facilities, and rules\n"
            "🎭 Clubs, events, and student activities\n"
            "👨‍🏫 Faculty, counsellor, and department contact details\n"
            "🏢 Campus services and administrative processes\n"
            "⏰ Setting reminders for important academic events and deadlines\n\n"
            "You can ask questions naturally, and I'll do my best to provide accurate and helpful information. 😊"
        )
    if any(x in q for x in ["who are you", "what are you", "about you"]):
        return (
            "👋 I'm the VIT Assistant, a virtual assistant designed to help students with "
            "university-related information and support.\n\n"
            "My goal is to make it easier for you to find information about academics, "
            "campus services, fees, hostel facilities, student activities, and much more. "
            "I'm here to guide you, answer your questions, and help you stay informed throughout your journey at VIT. 😊"
        )
    if any(x in q for x in ["what questions can i ask", "what can i ask", "domains"]):
        return (
            "💡 You can ask me questions about many VIT-related topics, including:\n\n"
            "📚 Academics and regulations\n"
            "💰 Fees, admissions, and scholarships\n"
            "🏠 Hostel and campus facilities\n"
            "🎭 Clubs, events, and student activities\n"
            "👨‍🏫 Faculty and counsellor information\n"
            "🏢 University procedures and services\n"
            "⏰ Reminders for exams, assignments, and important dates\n\n"
            "If you're unsure whether I can help with something, just ask—I'll try my best to guide you! 😊"
        )
    return (
        "😊 I'm your VIT Assistant, here to help with university-related questions and student support.\n\n"
        "You can ask me about academics, fees, hostel facilities, campus services, clubs, contacts, admissions, and much more. "
        "I can also help you set reminders for important events and deadlines.\n\n"
        "If you have a question, feel free to ask—I'm here to assist you! 🌟"
    )


class LocalBGEM3Embeddings(Embeddings):
    """Runs BGE-M3 in-process on local GPU/CPU — no HTTP hop."""

    def __init__(self, model_name="BAAI/bge-m3", use_fp16=True, device=None):
        self.model = BGEM3FlagModel(
            model_name,
            use_fp16=use_fp16,
            device=device or ("cuda" if torch.cuda.is_available() else "cpu"),
        )

    def embed_documents(self, texts):
        texts = [f"passage: {t}" for t in texts]
        out = self.model.encode(
            texts,
            batch_size=12,
            max_length=8192,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return out["dense_vecs"].tolist()

    def embed_query(self, text):
        out = self.model.encode(
            [f"query: {text}"],
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return out["dense_vecs"][0].tolist()


dense_embeddings = LocalBGEM3Embeddings(device=device)
sparse_embeddings = FastEmbedSparse(model_name="Qdrant/bm25")

# ── Per-request metrics ──────────────────────────────────────────────
import contextvars
current_metrics = contextvars.ContextVar("current_metrics", default=None)


def _dedupe_docs(docs: list[Document]) -> list[Document]:
    seen_hashes = set()
    deduped = []
    for doc in docs:
        normalized = " ".join(doc.page_content.split()).strip().lower()
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        if content_hash in seen_hashes:
            continue
        seen_hashes.add(content_hash)
        deduped.append(doc)
    return deduped


class BGEHTTPRerankRetriever(BaseRetriever):
    """Hybrid candidate retrieval + cross-encoder reranking.

    IMPORTANT: there is intentionally NO score threshold here.
    BGE-M3/BM25 provides the candidate pool and the cross-encoder
    determines ranking. Hard thresholds are avoided because reranker
    score scales are model-dependent and a valid supporting chunk can
    otherwise be discarded.
    """

    base_retriever: BaseRetriever
    top_n: int = 8
    max_docs: int = 8

    class Config:
        arbitrary_types_allowed = True

    def _filter(self, docs, scores):
        ranked = sorted(
            zip(scores, docs),
            key=lambda x: x[0],
            reverse=True,
        )
        if not ranked:
            return [], None
        kept = ranked[: self.max_docs]
        return [doc for _, doc in kept], ranked[0][0]

    async def _rerank_call(self, query: str, docs: list[Document]):
        if reranker_http_client is None:
            raise RuntimeError("reranker_http_client not initialized")
        resp = await reranker_http_client.post(
            f"{RERANKER_URL}/rerank",
            json={
                "query": query,
                "documents": [d.page_content for d in docs],
            },
        )
        resp.raise_for_status()
        return resp.json()["scores"]

    def _get_relevant_documents(
        self,
        query: str,
        *,
        run_manager: CallbackManagerForRetrieverRun = None,
    ):
        docs = _dedupe_docs(self.base_retriever.invoke(query))
        if not docs:
            return []

        try:
            resp = httpx.post(
                f"{RERANKER_URL}/rerank",
                json={
                    "query": query,
                    "documents": [d.page_content for d in docs],
                },
                timeout=RERANKER_TIMEOUT,
            )
            resp.raise_for_status()
            scores = resp.json()["scores"]
        except Exception as e:
            logger.error(
                f"[reranker] sync HTTP call failed; using hybrid order: {e}"
            )
            return docs[: self.top_n]

        if len(scores) != len(docs):
            logger.error(
                f"[reranker] score count {len(scores)} != doc count {len(docs)}"
            )
            return docs[: self.top_n]

        kept, _ = self._filter(docs, scores)
        return kept

    async def _aget_relevant_documents(self, query: str, *, run_manager=None):
        metrics = current_metrics.get()
        t0 = time.time()

        docs = await self.base_retriever.ainvoke(
            query,
            config={"callbacks": run_manager.get_child()} if run_manager else None,
        )
        docs = _dedupe_docs(docs)

        if metrics is not None:
            metrics["retrieval_ms"] = int((time.time() - t0) * 1000)
            metrics["docs_retrieved"] = len(docs)

        if not docs:
            return []

        t1 = time.time()
        try:
            scores = await self._rerank_call(query, docs)
        except Exception as e:
            logger.error(
                f"[reranker] HTTP call failed; using hybrid order: {e}"
            )
            if metrics is not None:
                metrics["reranker_fallback"] = True
                metrics["reranker_ms"] = int((time.time() - t1) * 1000)
            return docs[: self.top_n]

        reranker_ms = int((time.time() - t1) * 1000)
        if metrics is not None:
            metrics["reranker_ms"] = reranker_ms

        if len(scores) != len(docs):
            logger.error(
                f"[reranker] score count {len(scores)} != doc count {len(docs)}"
            )
            if metrics is not None:
                metrics["reranker_fallback"] = True
            return docs[: self.top_n]

        kept, top_score = self._filter(docs, scores)
        if metrics is not None:
            metrics["top_score"] = top_score
            metrics["docs_above_threshold"] = len(kept)  # legacy metric name
            metrics["retry_attempts"] = 0

        logger.info(
            f"[reranker] ranked {len(docs)} candidates -> {len(kept)} docs; "
            f"top_score={top_score}"
        )
        return kept


def clean_text(text: str) -> str:
    return re.sub(r"(\*\*|__)", "", text).strip()

def sanitize_misleading_wording(text: str) -> str:
    replacements = [
        (r"\bis scheduled for\b", "takes place on"),
        (r"\bhas been scheduled for\b", "takes place on"),
        (r"\bscheduled for\b", "on"),
        (r"\bI have noted this down\b", "I found the event details"),
        (r"\bI have noted it down\b", "I found the event details"),
        (r"\bnoted down\b", "found"),
        (r"\bnote this down\b", "view this event"),
        (r"\breminder set\b", "reminder option"),
        (r"\badded to calendar\b", "can be added to your calendar"),
        (r"\badded to your calendar\b", "can be added to your calendar"),
        (r"\byour reminder has been set\b", "you can set your reminder below"),
        (r"\byour event is scheduled\b", "your event takes place"),
    ]
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text

def strip_tool_call_tags(text: str) -> str:
    """Remove <tool_call>...</tool_call> wrapper tags without discarding
    content."""
    return text.replace("<tool_call>", "").replace("</tool_call>", "").strip()

def _normalize_llm_items(value, item_kind: str) -> list:
    """Keep entity/action parsing strict enough that validation never crashes.

    Qwen sometimes returns an object for `entities` (for example
    {"SAP": "Semester Abroad Program"}) instead of the required list.
    Such data is not a valid reminder entity, so it is ignored safely.
    """
    if not isinstance(value, list):
        logger.warning(
            "[llm-parse] ignoring malformed %s: expected list, got %s",
            item_kind,
            type(value).__name__,
        )
        return []
    return [item for item in value if isinstance(item, dict)]


def parse_llm_response(raw_text: str) -> dict:
    raw_text = (raw_text or "").strip()

    if "<think>" in raw_text:
        raw_text = re.sub(
            r"<think>.*?</think>", "",
            raw_text,
            flags=re.DOTALL,
        ).strip()
        if "<think>" in raw_text:
            raw_text = raw_text.split("<think>", 1)[0].strip()

    if "```" in raw_text:
        block_match = re.search(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            raw_text,
            re.DOTALL | re.IGNORECASE,
        )
        if block_match:
            raw_text = block_match.group(1).strip()

    candidates = [raw_text]
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end > start:
        candidates.append(raw_text[start:end + 1])

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except Exception:
            continue

        if not isinstance(data, dict) or "answer" not in data:
            continue

        answer = data.get("answer", "")
        if not isinstance(answer, str):
            answer = str(answer)

        return {
            "answer": answer,
            "entities": _normalize_llm_items(data.get("entities", []), "entities"),
            "actions": _normalize_llm_items(data.get("actions", []), "actions"),
        }

    return {"answer": raw_text, "entities": [], "actions": []}


async def ensure_chat(chat_id: str, user_id: str, first_message: str):
    # FIX: previously looked up by _id only, with no userId filter — unlike
    # every other chat-related endpoint here (rename_chat, delete_chat,
    # get_messages, etc.), which all filter by {_id, userId}. If a chat_id
    # were ever reused/guessed, a second user could silently attach messages
    # to another user's chat. Now scoped by both, and we explicitly detect
    # (and refuse) an id collision against a different owner instead of
    # silently proceeding.
    chat = await chats_collection.find_one({"_id": chat_id, "userId": user_id})
    if chat:
        return

    existing_any_owner = await chats_collection.find_one({"_id": chat_id})
    if existing_any_owner:
        logger.error(
            f"[ensure_chat] chat_id {chat_id!r} already exists under a "
            f"different userId — refusing to attach user {user_id!r} to it."
        )
        raise HTTPException(status_code=409, detail="Chat ID conflict")

    await chats_collection.insert_one({
        "_id": chat_id,
        "userId": user_id,
        "title": first_message[:40],
        "memorySummary": "",
        "createdAt": datetime.now(UTC),
        "updatedAt": datetime.now(UTC),
    })


def _budget_exceeded(request_t0: float) -> bool:
    return int((time.time() - request_t0) * 1000) > REQUEST_TOTAL_BUDGET_MS


async def _retrieve_with_rewrite(raw_query: str, chat_history: list):
    """
    Always rewrite/translate `raw_query` via `query_rewrite_chain` before
    handing it to the retriever — regardless of whether `chat_history` is
    empty. This guarantees BGE-M3/BM25/Qdrant/reranker only ever see the
    rewritten (English) retrieval query, on the first turn as well as
    follow-ups, instead of relying on `history_aware_retriever`'s
    chat_history-gated behavior (which skips the rewrite step entirely
    when there's no prior history).

    Returns (docs, rewritten_query) so callers can log/inspect what was
    actually sent to the retriever. Bundled into one function so the
    caller can wrap both steps in a single asyncio.wait_for and keep the
    existing per-stage timeout budget (RAG_TIMEOUT) covering the whole
    rewrite+retrieve stage, not each step separately.
    """
    rewritten = await query_rewrite_chain.ainvoke({
        "input": raw_query,
        "chat_history": chat_history,
    })
    if not isinstance(rewritten, str):
        rewritten = str(rewritten)
    rewritten = rewritten.strip()

    # Safety net: an empty/failed rewrite should never silently drop the
    # query — fall back to the raw text rather than searching for "".
    if not rewritten:
        rewritten = raw_query

    docs = await retriever.ainvoke(rewritten)
    return docs, rewritten


# ── Prompts ───────────────────────────────────────────────────────────
# ============================================================
# FINAL ANSWER PROMPT
# ============================================================

template = """
You are VIT Assistant, an empathetic and knowledgeable AI
chatbot designed to serve the VIT College community, including
students, staff, and parents.

Your primary mission is to provide accurate and relevant
information about VIT College, including:

- regulations
- academic programs
- fees
- hostel
- library resources
- departments
- faculty
- clubs
- placements
- procedures
- campus services
- academic policies
- deadlines
- contact information

You may also assist with reminders and general chatbot
capability questions.

Your responses must be:

- accurate
- grounded
- clear
- professional
- friendly
- conversational
- concise when possible

Do not sound robotic.

============================================================
GROUNDING RULE
============================================================

ONLY state facts directly supported by the provided Context.

If the Context does not contain information that answers the
question:

- say that the available information does not contain the
  answer
- do not guess
- do not use general world knowledge
- do not invent details
- do not fabricate URLs
- do not fabricate contact information

For example:

"I don't have specific information about that in the
available VIT information."

Do not attach a URL or contact detail to a claim unless that
exact URL/detail appears in the Context next to the fact it
supports.

============================================================
NO INFERENCE RULE
============================================================

Never infer facts that are not explicitly present in Context.

Do not infer:

- eligibility
- deadlines
- departments
- office responsibilities
- fees
- contact information
- procedures
- approval processes
- requirements

unless explicitly supported by Context.

============================================================
LIST FIDELITY RULE
============================================================

If a Context chunk explicitly presents itself as a complete
list for a category, treat that chunk as the authoritative
membership list.

When answering category-membership questions:

- use the list exactly as provided
- do not add items from unrelated Context chunks
- do not remove items
- do not infer membership from descriptions
- do not merge separate category lists
- never invent an item name

If two Context chunks disagree, prefer the chunk explicitly
identified as the complete/full list.

============================================================
FORMAT FIDELITY RULE
============================================================

Mirror the structure of the relevant Context whenever
possible.

If Context is a table:
- use a Markdown table

If Context is a numbered procedure:
- use numbered steps

If Context is a bullet list:
- use bullets

If Context is prose:
- use concise paragraphs

Preserve:

- row order
- column names
- numbering
- hierarchy

Do not convert tables into prose unless the user explicitly
asks for an explanation.

============================================================
QUOTATION FIDELITY RULE
============================================================

When the user asks for the exact wording of:

- a regulation
- a rule
- a policy
- a definition
- an eligibility criterion
- a grading scale

quote or closely reproduce the wording from Context.

Do not change:

- numerical values
- dates
- eligibility conditions
- official terminology

============================================================
CONTEXT PRIORITY
============================================================

When multiple Context chunks are available:

1. Prefer the chunk that directly answers the question.
2. Use additional chunks only when they support the same topic.
3. Do not combine unrelated chunks.
4. If Context conflicts, acknowledge the inconsistency instead
   of inventing a resolution.

============================================================
RESPONSE STRUCTURE
============================================================

When appropriate, organize the answer as:

1. Direct answer
2. Supporting explanation
3. Relevant table/list/procedure
4. Next steps

Only provide next steps when supported by Context.

============================================================
TONE
============================================================

Be:

- warm
- empathetic
- professional
- natural
- helpful

Communicate like a helpful senior student or staff member.

Avoid generic phrases such as:

"Based on my knowledge..."
"As an AI..."
"I apologize for the inconvenience..."

unless genuinely necessary.

Emojis may be used sparingly.

Accuracy is always more important than warmth.

============================================================
LANGUAGE
============================================================

Response language:

{language}

Rules:

1. Respond entirely in the selected language.

2. If language is "auto", use the detected language supplied
   by the application.

3. Do not switch languages merely because the retrieved Context
   is written in English.

4. The retrieved Context may be English while the answer is
   Tamil, Hindi, Telugu, Kannada, or Malayalam.

5. Do not unnecessarily translate proper nouns.

6. Preserve official names exactly as they appear in Context.

7. Technical terms such as API, database, model, Qdrant,
   JSON, etc. may remain in English.

8. Do not mention these language rules to the user.

============================================================
JSON OUTPUT
============================================================

Return ONLY valid JSON.

Exact schema:

{{
  "answer": "Answer in the selected language",
  "entities": [],
  "actions": []
}}

No text may appear outside the JSON object.

============================================================
ANSWER FIELD
============================================================

The answer field may contain Markdown.

Allowed:

- headings
- bullets
- numbered lists
- Markdown tables
- bold text

Do not use HTML.

Escape double quotes correctly so the result remains valid JSON.

============================================================
COMPLETENESS
============================================================

"Complete" means complete according to the available Context.

If Context fully supports the question:
- answer fully

If Context partially supports the question:
- give only the supported information
- explicitly state what information is missing

If Context does not support the question:
- clearly say that the available information does not contain
  the answer

Do not add facts simply to make the response sound complete.

============================================================
ENTITIES AND ACTIONS
============================================================

Populate entities and actions ONLY when all of these are true:

1. The user explicitly states a specific date.
2. The user explicitly requests a reminder.
3. The subject is a time-based academic event.

Otherwise:

"entities": []
"actions": []

Do not invent event details.

============================================================
EXAMPLES
============================================================

User:
"How do I get a new ID card?"

Return:

{{
  "answer": "Answer using only the available Context.",
  "entities": [],
  "actions": []
}}

User:
"I have chemistry exam on June 15, set a reminder."

Return an appropriate answer and populate entities/actions
only if the application has enough Context to do so.
"""


# ============================================================
# RETRIEVAL QUERY CONTEXTUALIZER
# ============================================================

contextualize_q_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
You are the retrieval-query rewriting component of a
multilingual RAG system.

Your ONLY job is to convert the user's latest message into the
best possible query for the vector database.

DO NOT answer the user.

Return ONLY the final English retrieval query.

============================================================
RULES
============================================================

1. Use chat history to understand context.

2. Resolve vague references such as:

   - it
   - this
   - that
   - they
   - them
   - other
   - others
   - more
   - same
   - previous
   - above

3. Expand the latest message into a complete retrieval query.

4. Preserve the user's actual intent.

5. Include important entities and terms such as:

   - SAP
   - clubs
   - departments
   - eligibility
   - hostel
   - fees
   - deadlines
   - courses
   - regulations

6. Do NOT invent facts.

7. Do NOT answer the question.

8. Do NOT provide explanations.

9. If the latest user message is not English, translate it
   into English before rewriting it.

10. Return ONE English retrieval query only.

============================================================
EXAMPLES
============================================================

Conversation:

User:
"in which semester can we do SAP?"

User:
"other dept?"

Output:

SAP semester eligibility for other departments


Conversation:

User:
"tell me about ALPHA BIO CELL"

User:
"tell more"

Output:

Detailed information about ALPHA BIO CELL club


Conversation:

User:
"list technical clubs"

User:
"what about others"

Output:

List of all technical clubs


Conversation:

User:
"விடுதி கட்டணம் எப்போது செலுத்த வேண்டும்?"

Output:

When is the hostel fee due?


Conversation:

User:
"hostel fee deadline kab hai?"

Output:

Hostel fee deadline


============================================================
IMPORTANT
============================================================

This is a RETRIEVAL query.

It is NOT the final response.

The final response language is handled separately by the
answer-generation component.
""",
        ),
        MessagesPlaceholder("chat_history"),
        (
            "human",
            "{input}",
        ),
    ]
)


async def _log_pipeline_metrics(
    req,
    sources,
    routing,
    router_ms,
    retrieval_ms=None,
    docs_retrieved=None,
    reranker_ms=None,
    reranker_fallback=False,
    generation_ms=None,
    rag_total_ms=None,
    reminder_llm_ms=None,
    total_ms=None,
    timed_out=False,
    error=None,
    docs_above_threshold=None,
    top_score=None,
    retry_attempts=0,
):
    """Best-effort metrics write — never let this break the actual chat response."""
    try:
        await db["pipeline_metrics"].insert_one({
            "chatId": req.chatId,
            "userId": req.userId,
            "query": req.text,
            "sources": sources,
            "router_reason": routing.get("reason"),
            "router_ms": router_ms,
            "retrieval_ms": retrieval_ms,
            "docs_retrieved": docs_retrieved,
            "docs_above_threshold": docs_above_threshold,
            "top_score": top_score,
            # FIX: how many times the reranker retry loop widened k because
            # nothing cleared threshold — lets you see on the dashboard how
            # often this is happening and whether retry_k_values needs tuning.
            "reranker_retry_attempts": retry_attempts,
            "reranker_ms": reranker_ms,
            "reranker_fallback": reranker_fallback,
            "generation_ms": generation_ms,
            "rag_total_ms": rag_total_ms,
            "reminder_llm_ms": reminder_llm_ms,
            "total_ms": total_ms,
            "timed_out": timed_out,
            "error": error,
            "createdAt": datetime.now(UTC),
        })
    except Exception as e:
        logger.warning(f"[metrics] failed to log pipeline metrics: {e}")


# ── Startup ───────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup():
    global rag_chain, hybrid_store, retriever, history_aware_retriever, question_answer_chain, query_rewrite_chain, reranker_http_client
    COLLECTION = "newest"

    logger.info("Building RAG pipeline...")

    reranker_http_client = httpx.AsyncClient(timeout=RERANKER_TIMEOUT)
    try:
        health = await reranker_http_client.get(f"{RERANKER_URL}/health", timeout=5)
        logger.info(f"[reranker] health check: {health.json()}")
    except Exception as e:
        logger.warning(f"[reranker] health check failed at startup (will retry per-request): {e}")

    client = QdrantClient(path=str(BASE_DIR / "qdrant"), timeout=100)
    await db["page_parents"].create_index("parent_id", unique=True)

    collection_info = client.get_collection(COLLECTION)
    logger.info(f"Collection already populated ({collection_info.points_count} points). Skipping embedding.")

    hybrid_store = QdrantVectorStore(
        client=client,
        collection_name=COLLECTION,
        embedding=dense_embeddings,
        sparse_embedding=sparse_embeddings,
        retrieval_mode="hybrid",
        vector_name="dense",
        sparse_vector_name="sparse",
    )

    hybrid_retriever = hybrid_store.as_retriever(search_kwargs={"k": 80})
    if not hasattr(hybrid_store, "client"):
        hybrid_store.client = client
    if not hasattr(hybrid_store, "collection_name"):
        hybrid_store.collection_name = COLLECTION

    # No hard reranker threshold. Hybrid retrieval supplies candidates;
    # the cross-encoder reranker orders them and top-N is passed to Qwen.
    retriever = BGEHTTPRerankRetriever(
        base_retriever=hybrid_retriever,
        top_n=8,
        max_docs=8,
    )

    qa_prompt = ChatPromptTemplate.from_messages([
        ("system", template),
        MessagesPlaceholder("chat_history"),
        ("human", "Context:\n{context}\n\nQuestion:\n{input}\n"),
    ])

    history_aware_retriever = create_history_aware_retriever(llm, retriever, contextualize_q_prompt)
    question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)
    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)

    # FIX: `create_history_aware_retriever` builds a RunnableBranch that
    # SKIPS the LLM rewrite/translate step entirely whenever chat_history
    # is empty (falsy) — it just calls `retriever(input)` directly in that
    # case. That means on a user's very first message (no history yet),
    # a non-English query like "SAP என்றால் என்ன?" was going straight
    # into BGE-M3/BM25/Qdrant/reranker untranslated, bypassing
    # `contextualize_q_prompt`'s "translate to English" instruction —
    # unlike every subsequent turn, which does get rewritten. This
    # standalone chain always runs the same prompt/LLM rewrite step
    # regardless of whether chat_history is empty, so retrieval_query is
    # consistently rewritten before it ever reaches the retriever.
    query_rewrite_chain = contextualize_q_prompt | llm | StrOutputParser()

    try:
        asyncio.create_task(ensure_indexes())
        logger.info("Database indexes scheduled.")
    except Exception as e:
        logger.warning(f"Index creation skipped: {e}")

    logger.info("RAG pipeline ready.")


# ── Shutdown ──────────────────────────────────────────────────────────
@app.on_event("shutdown")
async def shutdown():
    global reranker_http_client
    if reranker_http_client:
        await reranker_http_client.aclose()
    try:
        from pipeline.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass


# ── Pydantic models ───────────────────────────────────────────────────
# ── Deterministic script-based language detection ──────────────────────
# FIX: the router's language detection runs through an 8B LLM, which is
# unreliable for unambiguous cases and can drift over time. Native Indic
# scripts are trivially identifiable by Unicode code-point range, so we
# detect them deterministically here and let this take priority over
# whatever the router's LLM guessed. This is independent of router.py's
# own internal detection — belt-and-suspenders, since main.py should not
# have to trust every upstream component to get this right.
_SCRIPT_LANGUAGE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ta", re.compile(r"[\u0B80-\u0BFF]")),  # Tamil
    ("hi", re.compile(r"[\u0900-\u097F]")),  # Devanagari (Hindi)
    ("te", re.compile(r"[\u0C00-\u0C7F]")),  # Telugu
    ("kn", re.compile(r"[\u0C80-\u0CFF]")),  # Kannada
    ("ml", re.compile(r"[\u0D00-\u0D7F]")),  # Malayalam
]


def _detect_script_language(text: str) -> str | None:
    """
    Deterministically detect Tamil/Hindi/Telugu/Kannada/Malayalam from
    native script Unicode ranges. Returns None if the text contains no
    recognizable Indic script (e.g. plain English or romanized text),
    in which case the caller should fall back to the router's LLM-based
    `detected_language`.
    """
    if not text:
        return None
    for lang, pattern in _SCRIPT_LANGUAGE_PATTERNS:
        if pattern.search(text):
            return lang
    return None


class ChatRequest(BaseModel):
    chatId: str
    userId: str
    text: str
    language: str = "auto"

class ReminderCreateRequest(BaseModel):
    userId: str
    eventName: str
    eventDate: str
    sourceType: str
    # FIX: bare `str = None` works under Pydantic v1's implicit-optional
    # behavior but raises a schema error under Pydantic v2 — use Optional[]
    # explicitly.
    sourceId: Optional[str] = None
    notificationType: str = "in_app"
    reminderOffset: str = "1d"
    chatId: str = ""

class SnoozeRequest(BaseModel):
    userId: str
    snoozeMinutes: int = 60

class PreferenceSaveRequest(BaseModel):
    userId: str
    notificationType: str
    email: Optional[str] = None


# ── Fallback answer when no docs clear the reranker threshold ─────────
# FIX: this answer now bypasses BOTH generation (qa_prompt's {language}
# handling) and tone rewrite (see used_no_info_fallback below), so it needs
# its own per-language text instead of always coming out in English
# regardless of req.language. Covers the languages handle_meta_query()
# already advertises; anything else falls back to English.
_NO_INFO_ANSWER_TEXT_BY_LANGUAGE = {
    "en": (
        "I couldn't find specific information about that in what's "
        "available to me right now. You may want to reach out to the "
        "relevant department or check the official VIT resources directly "
        "for the most accurate answer. Is there anything else I can help "
        "with?"
    ),
    "ta": (
        "இது குறித்த குறிப்பிட்ட தகவலை என்னால் தற்போது கண்டறிய முடியவில்லை. "
        "சரியான தகவலுக்கு தொடர்புடைய துறையை அணுகவும் அல்லது VIT-இன் "
        "அதிகாரப்பூர்வ வளங்களைப் பார்க்கவும். வேறு எதிலாவது உதவ வேண்டுமா?"
    ),
    "hi": (
        "मुझे अभी इस बारे में विशिष्ट जानकारी नहीं मिल पाई। सही जानकारी के "
        "लिए कृपया संबंधित विभाग से संपर्क करें या VIT के आधिकारिक संसाधन "
        "देखें। क्या मैं किसी और चीज़ में मदद कर सकता हूँ?"
    ),
    "te": (
        "దీని గురించి నిర్దిష్ట సమాచారం నాకు ప్రస్తుతం అందుబాటులో లేదు. "
        "సరైన సమాచారం కోసం సంబంధిత విభాగాన్ని సంప్రదించండి లేదా VIT అధికారిక "
        "వనరులను చూడండి. మరేదైనా సహాయం కావాలా?"
    ),
    "kn": (
        "ಇದರ ಬಗ್ಗೆ ನಿರ್ದಿಷ್ಟ ಮಾಹಿತಿ ನನಗೆ ಸದ್ಯಕ್ಕೆ ಲಭ್ಯವಿಲ್ಲ. ಸರಿಯಾದ ಮಾಹಿತಿಗಾಗಿ "
        "ಸಂಬಂಧಿತ ವಿಭಾಗವನ್ನು ಸಂಪರ್ಕಿಸಿ ಅಥವಾ VIT ಅಧಿಕೃತ ಸಂಪನ್ಮೂಲಗಳನ್ನು ಪರಿಶೀಲಿಸಿ. "
        "ಬೇರೆ ಯಾವುದಾದರೂ ಸಹಾಯ ಬೇಕೇ?"
    ),
    "ml": (
        "ഇതിനെക്കുറിച്ചുള്ള നിർദ്ദിഷ്ട വിവരങ്ങൾ എനിക്ക് ഇപ്പോൾ കണ്ടെത്താൻ "
        "കഴിഞ്ഞില്ല. കൃത്യമായ വിവരങ്ങൾക്ക് ബന്ധപ്പെട്ട വകുപ്പിനെ സമീപിക്കുകയോ "
        "VIT-യുടെ ഔദ്യോഗിക വിഭവങ്ങൾ പരിശോധിക്കുകയോ ചെയ്യുക. മറ്റെന്തെങ്കിലും "
        "സഹായം വേണോ?"
    ),
}


def _no_info_answer_payload(language: str) -> dict:
    text = _NO_INFO_ANSWER_TEXT_BY_LANGUAGE.get(
        (language or "en").lower(), _NO_INFO_ANSWER_TEXT_BY_LANGUAGE["en"]
    )
    return {"answer": text, "entities": [], "actions": []}


# ── Chat endpoint ─────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(req: ChatRequest):
    request_t0 = time.time()

    sources, routing, router_ms = [], {}, None
    retrieval_ms = docs_retrieved = generation_ms = rag_total_ms = None
    reminder_llm_ms  = None
    reranker_ms = None
    reranker_fallback = False
    docs_above_threshold = None
    top_score = None
    retry_attempts = 0
   
    await ensure_chat(req.chatId, req.userId, req.text)

    await messages_collection.insert_one({
        "chatId": req.chatId,
        "userId": req.userId,
        "role": "user",
        "content": req.text,
        "createdAt": datetime.now(UTC)
    })

    conversational_answer = ""
    factual_answer = ""
    entities, actions = [], []
    raw_entities, raw_actions = [], []

    async def _timeout_response(stage_name: str, **metric_kwargs):
        total_ms = int((time.time() - request_t0) * 1000)
        await _log_pipeline_metrics(
            req, sources, routing, router_ms,
            retrieval_ms=retrieval_ms, docs_retrieved=docs_retrieved,
            reranker_ms=reranker_ms, reranker_fallback=reranker_fallback,
            generation_ms=generation_ms, rag_total_ms=rag_total_ms,
            reminder_llm_ms=reminder_llm_ms,
            docs_above_threshold=docs_above_threshold, top_score=top_score,
            retry_attempts=retry_attempts,
            total_ms=total_ms, timed_out=True,
            **metric_kwargs,
        )
        logger.error(f"[chat] {stage_name} timeout/budget-exceeded for query: {req.text!r}")
        return {"answer": "This is taking longer than expected — please try again.",
                "entities": [], "actions": []}

    try:
        memory = await load_memory(req.chatId, req.userId)

        def format_history(messages):
            return "\n".join(
                f"{m.type.upper()}: {m.content}"
                for m in messages[-HISTORY_WINDOW:]
            )

        chat_history = format_history(memory.chat_memory.messages)

        t_router0 = time.time()
        routing = await route_query(
    req.text,
    chat_history,
)
        router_ms = int((time.time() - t_router0) * 1000)
        sources = routing.get("sources") or ["qdrant"]

        # `original_question` is the untouched user input. It is never
        # translated or rewritten — it's what gets shown to the final
        # Qwen generation step, alongside `effective_language`. Any
        # query rewriting for retrieval purposes happens separately,
        # in a dedicated `retrieval_query` variable further down, and
        # never leaks into `original_question`.
        original_question = req.text

        router_detected_language = (
            routing.get("detected_language") or "en"
        ).strip().lower()

        # Deterministic script detection takes priority over the
        # router's LLM-based guess whenever the message contains a
        # recognizable Tamil/Hindi/Telugu/Kannada/Malayalam script —
        # that's a strictly more reliable signal than an 8B model.
        script_language = _detect_script_language(original_question)
        detected_language = script_language or router_detected_language

        requested_language = (req.language or "auto").strip().lower()
        requested_language = LANGUAGE_ALIASES.get(requested_language, requested_language)

        # The frontend historically sent `en` even when the user typed in
        # Tamil/Hindi/etc. Treat `en` as the legacy auto value unless the
        # frontend is later changed to send an explicit language preference.
        # This fixes romanized Hindi/Tamil too, because the router detects
        # those languages even when Unicode script detection returns None.
        if requested_language in ("", "auto", "en"):
            effective_language = detected_language
        elif requested_language in SUPPORTED_LANGUAGES:
            effective_language = requested_language
        else:
            logger.warning(
                "[language] unsupported requested language=%r; using detected=%s",
                req.language, detected_language,
            )
            effective_language = detected_language

        logger.info(
            "[router] %s <- %s | original: %r | lang: "
            "req=%s script=%s router=%s detected=%s effective=%s",
            sources,
            routing.get("reason"),
            original_question,
            req.language,
            script_language,
            router_detected_language,
            detected_language,
            effective_language,
        )
        if _budget_exceeded(request_t0):
            return await _timeout_response("post-router")

        now_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S %Z")

        if "clarify" in sources:
            conversational_answer = routing.get(
                "clarification_question",
                "😊 Could you please provide a little more detail so I can help you better?"
            )
            factual_answer = conversational_answer

        elif "meta" in sources:
            conversational_answer = await handle_meta_query(req.text)
            factual_answer = conversational_answer

        elif "greeting" in sources:
            conversational_answer = "👋 Hello! I'm the VIT Assistant. How can I help you today?"
            factual_answer = conversational_answer

        elif "irrelevant" in sources:
            conversational_answer = (
                "😊 That's outside what I can help with — I'm focused on VIT University topics "
                "like academics, fees, hostel info, clubs, and reminders. "
                "Is there anything university-related I can help you with instead?"
            )
            factual_answer = conversational_answer

        else:
            if "qdrant" in sources:
                # `retrieval_query` feeds ONLY the history-aware retriever /
                # plain retriever / reranker chain — it may be augmented
                # (e.g. with a current-date prefix for combined
                # qdrant+reminder queries) purely to help retrieval/query
                # rewriting. It must never be used for final generation;
                # `original_question` (untouched) is used there instead.
                retrieval_query = original_question
                if "reminder" in sources:
                    retrieval_query = f"[Current date: {now_str}]\n{retrieval_query}"

                recent_history = memory.chat_memory.messages[-HISTORY_WINDOW:]

                rag_metrics = {"retrieval_ms": None, "docs_retrieved": None,
                                "reranker_ms": None, "reranker_fallback": False,
                                "docs_above_threshold": None, "top_score": None,
                                "retry_attempts": 0}
                metrics_token = current_metrics.set(rag_metrics)

                t_retrieve0 = time.time()
                try:
                    docs, rewritten_retrieval_query = await asyncio.wait_for(
                        _retrieve_with_rewrite(retrieval_query, recent_history),
                        timeout=RAG_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    retrieval_ms = int((time.time() - t_retrieve0) * 1000)
                    reranker_ms = rag_metrics.get("reranker_ms")
                    reranker_fallback = rag_metrics.get("reranker_fallback", False)
                    retry_attempts = rag_metrics.get("retry_attempts", 0)
                    current_metrics.reset(metrics_token)
                    return await _timeout_response("retrieval")

                current_metrics.reset(metrics_token)
                retrieval_ms = int((time.time() - t_retrieve0) * 1000)
                docs_retrieved = len(docs)
                reranker_ms = rag_metrics.get("reranker_ms")
                reranker_fallback = rag_metrics.get("reranker_fallback", False)
                docs_above_threshold = rag_metrics.get("docs_above_threshold")
                top_score = rag_metrics.get("top_score")
                retry_attempts = rag_metrics.get("retry_attempts", 0)
                logger.info(
                    f"[rag] retrieval+rerank: {retrieval_ms}ms "
                    f"(reranker: {reranker_ms}ms, fallback={reranker_fallback}, "
                    f"retries={retry_attempts}), "
                    f"{docs_retrieved} docs post-rerank | "
                    f"retrieval_query={rewritten_retrieval_query!r}"
                )
                for doc in docs:
                    logger.info(f"RETRIEVED: {doc.page_content}")

                if _budget_exceeded(request_t0):
                    return await _timeout_response("post-retrieval")

                # If hybrid retrieval produced no candidates, do not ask Qwen
                # to invent an answer. The reranker is only a ranking stage;
                # it does not use a hard relevance threshold.
                if not docs:
                    raw_answer = json.dumps(_no_info_answer_payload(effective_language))
                    generation_ms = 0
                    rag_total_ms = retrieval_ms
                else:
                    t_gen0 = time.time()
                    try:
                        raw_answer = await asyncio.wait_for(
                            question_answer_chain.ainvoke({
                                "input": original_question,
                                "chat_history": recent_history,
                                "context": docs,
                                "language": effective_language,
                            }),
                            timeout=RAG_TIMEOUT,
                        )
                        logger.info("=" * 80)
                        logger.info("CONTEXT PASSED TO LLM")
                        logger.info("=" * 80)
                        for i, d in enumerate(docs):
                            logger.info(f"Context Doc {i+1}")
                            logger.info(d.page_content)
                    except asyncio.TimeoutError:
                        generation_ms = int((time.time() - t_gen0) * 1000)
                        rag_total_ms = retrieval_ms + generation_ms
                        return await _timeout_response(
                            "generation",
                            docs_retrieved=docs_retrieved, generation_ms=generation_ms,
                            rag_total_ms=rag_total_ms,
                        )

                    generation_ms = int((time.time() - t_gen0) * 1000)
                    rag_total_ms = retrieval_ms + generation_ms
                    logger.info(f"[rag] generation: {generation_ms}ms | total rag: {rag_total_ms}ms")

                if not isinstance(raw_answer, str):
                    raw_answer = str(raw_answer)

            elif "reminder" in sources:
                
                lang_instruction = (
                    f'Respond strictly in the language: "{effective_language}". '
                    f'If language is "auto", respond in the same language as '
                    f'the user\'s message. Only use English for technical '
                    f'terms and proper nouns (event/place/brand names).'
                )
                t_rem0 = time.time()
                try:
                    reminder_result = await asyncio.wait_for(llm.ainvoke([
                        {
                            "role": "system",
                            "content": f"""You are a helpful assistant. Current date and time: {now_str}

{lang_instruction}

The user wants to set a personal reminder. Extract the event details and respond ONLY in this JSON format:
{{
  "answer": "A friendly confirmation acknowledging their reminder",
  "entities": [
    {{
      "type": "exam | assignment | fee | project_submission | event",
      "name": "Name of the event",
      "date": "YYYY-MM-DDTHH:MM:SS+05:30",
      "confidence": 0.95,
      "timezone": "Asia/Kolkata"
    }}
  ],
  "actions": [
    {{
      "type": "set_reminder",
      "entity": "Name matching entity above"
    }}
  ]
}}"""
                        },
                        {"role": "user", "content": original_question}
                    ]), timeout=REMINDER_LLM_TIMEOUT)
                except asyncio.TimeoutError:
                    reminder_llm_ms = int((time.time() - t_rem0) * 1000)
                    return await _timeout_response("reminder_llm")

                reminder_llm_ms = int((time.time() - t_rem0) * 1000)
                raw_answer = strip_tool_call_tags(reminder_result.content.strip())

            else:
                # No reminder-date prefix applies on this path, so
                # retrieval_query and original_question are the same
                # string — but kept as distinct names for consistency
                # with the qdrant branch and to make the retrieval-vs-
                # generation split explicit and easy to preserve if this
                # branch ever needs its own query augmentation later.
                retrieval_query = original_question

                recent_history = memory.chat_memory.messages[-HISTORY_WINDOW:]

                rag_metrics = {"retrieval_ms": None, "docs_retrieved": None,
                                "reranker_ms": None, "reranker_fallback": False,
                                "docs_above_threshold": None, "top_score": None,
                                "retry_attempts": 0}
                metrics_token = current_metrics.set(rag_metrics)

                t_retrieve0 = time.time()
                try:
                    docs, rewritten_retrieval_query = await asyncio.wait_for(
                        _retrieve_with_rewrite(retrieval_query, recent_history),
                        timeout=RAG_TIMEOUT,
                    )
                finally:
                    current_metrics.reset(metrics_token)

                retrieval_ms = int((time.time() - t_retrieve0) * 1000)
                docs_retrieved = len(docs)
                reranker_ms = rag_metrics.get("reranker_ms")
                reranker_fallback = rag_metrics.get("reranker_fallback", False)
                docs_above_threshold = rag_metrics.get("docs_above_threshold")
                top_score = rag_metrics.get("top_score")
                retry_attempts = rag_metrics.get("retry_attempts", 0)
                logger.info(
                    f"[rag-fallback] retrieval: {retrieval_ms}ms, "
                    f"{docs_retrieved} docs | "
                    f"retrieval_query={rewritten_retrieval_query!r}"
                )

                if not docs:
                    raw_answer = json.dumps(_no_info_answer_payload(effective_language))
                    generation_ms = 0
                    rag_total_ms = retrieval_ms
                else:
                    t_gen0 = time.time()
                    raw_answer = await asyncio.wait_for(
                        question_answer_chain.ainvoke({
                            "input": original_question,
                            "chat_history": recent_history,
                            "context": docs,
                            "language": effective_language,
                        }),
                        timeout=RAG_TIMEOUT,
                    )
                    generation_ms = int((time.time() - t_gen0) * 1000)
                    rag_total_ms = retrieval_ms + generation_ms

                if not isinstance(raw_answer, str):
                    raw_answer = str(raw_answer)

            # ── Parse entities ──────────────────────────────────────────
            parsed_data = parse_llm_response(raw_answer)
            raw_entities = parsed_data["entities"]
            raw_actions = parsed_data["actions"]
            answer_text = parsed_data["answer"]

            logger.info(f"PARSED ENTITIES (PRE-FILTER): {raw_entities}")
            logger.info(f"PARSED ACTIONS  (PRE-FILTER): {raw_actions}")

            if _budget_exceeded(request_t0):
                return await _timeout_response("post-generation")

            conversational_answer = answer_text
            factual_answer = answer_text

            # ── Validate entities ────────────────────────────────────────
            now = get_now_tz("Asia/Kolkata")

            for entity in raw_entities:
                try:
                    dt_str = entity.get("date", "")
                    if not dt_str:
                        logger.info(f"Skipping entity — no date: {entity}")
                        continue

                    dt = parse_iso_datetime(dt_str)
                    if dt <= now:
                        logger.info(f"Skipping entity — past date {dt}: {entity}")
                        continue

                    category = entity.get("type", "").lower().strip()
                    if category not in ACADEMIC_EVENT_TYPES:
                        logger.info(f"Skipping entity — unknown category '{category}': {entity}")
                        continue

                    iso_date = dt.isoformat()
                    entity["date"] = iso_date
                    entity["event_name"] = entity.get("name", "")
                    entity["event_date"] = iso_date
                    entity["event_type"] = entity.get("type", "")
                    entity["show_reminder"] = True
                    entities.append(entity)

                    entity_name = normalize_event_name(entity.get("name", ""))
                    for action in raw_actions:
                        if action.get("type") != "set_reminder":
                            continue
                        action_entity = normalize_event_name(action.get("entity", ""))
                        if action_entity == entity_name:
                            logger.info(f"Matching action found: {action}")
                            actions.append(action)
                        else:
                            logger.info(f"Action name mismatch: '{action_entity}' vs '{entity_name}'")

                except Exception as exc:
                    logger.error(f"Error validating entity: {exc}")
                    continue

        
        conversational_answer = sanitize_misleading_wording(conversational_answer)

        memory.chat_memory.add_user_message(req.text)
        memory.chat_memory.add_ai_message(factual_answer)
        await save_memory_summary(req.chatId, req.userId, memory)

        await messages_collection.insert_one({
            "chatId": req.chatId,
            "userId": req.userId,
            "role": "assistant",
            "content": conversational_answer,
            "entities": entities,
            "actions": actions,
            "createdAt": datetime.now(UTC)
        })

        await chats_collection.update_one(
            {"_id": req.chatId, "userId": req.userId},
            {"$set": {"updatedAt": datetime.now(UTC)}}
        )

        total_ms = int((time.time() - request_t0) * 1000)
        await _log_pipeline_metrics(
            req, sources, routing, router_ms,
            retrieval_ms=retrieval_ms, docs_retrieved=docs_retrieved,
            reranker_ms=reranker_ms, reranker_fallback=reranker_fallback,
            generation_ms=generation_ms, rag_total_ms=rag_total_ms,
            reminder_llm_ms=reminder_llm_ms,
            docs_above_threshold=docs_above_threshold, top_score=top_score,
            retry_attempts=retry_attempts,
            total_ms=total_ms,
        )

        return {
            "answer": conversational_answer,
            "entities": entities,
            "actions": actions,
            "debug_raw_entities": raw_entities,
        }

    except asyncio.TimeoutError:
        return await _timeout_response("outer")

    except Exception as e:
        total_ms = int((time.time() - request_t0) * 1000)
        await _log_pipeline_metrics(
            req, sources, routing, router_ms,
            retrieval_ms=retrieval_ms, docs_retrieved=docs_retrieved,
            reranker_ms=reranker_ms, reranker_fallback=reranker_fallback,
            generation_ms=generation_ms, rag_total_ms=rag_total_ms,
            reminder_llm_ms=reminder_llm_ms,
            docs_above_threshold=docs_above_threshold, top_score=top_score,
            retry_attempts=retry_attempts,
            total_ms=total_ms, error=str(e),
        )
        logger.error(f"Chat error: {e}\n{traceback.format_exc()}")
        return {
            "answer": f"Error: {str(e)}",
            "entities": [],
            "actions": [],
        }


# ── Blocking helpers for transcription (run off the event loop) ───────
def _run_ffmpeg_convert(src_path: str, wav_path: str):
    return subprocess.run(
        ["ffmpeg", "-y", "-i", src_path, "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", wav_path],
        capture_output=True, text=True,
    )


def _is_silent(path: str) -> bool:
    import wave
    import numpy as np
    try:
        with wave.open(path, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            audio = np.frombuffer(frames, dtype=np.int16)
            return len(audio) == 0 or np.abs(audio).mean() < 200
    except Exception:
        return True


# ── Transcription endpoint ────────────────────────────────────────────
@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...), language: str = Form("en")):
    temp_audio_path = None
    wav_path = None

    try:
        content_type = file.content_type or ""
        if "wav" in content_type:
            suffix = ".wav"
        elif "mp4" in content_type or "m4a" in content_type:
            suffix = ".m4a"
        elif "ogg" in content_type:
            suffix = ".ogg"
        else:
            suffix = ".webm"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            temp_audio_path = tmp.name

        
        total_bytes = 0
        with open(temp_audio_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Audio file too large")
                f.write(chunk)
        logger.info(f"Saved audio: {temp_audio_path} ({total_bytes} bytes)")

        wav_path = os.path.join(tempfile.gettempdir(), f"{uuid.uuid4()}.wav")

        loop = asyncio.get_running_loop()

        
        conversion = await loop.run_in_executor(
            _blocking_io_executor, _run_ffmpeg_convert, temp_audio_path, wav_path
        )
        if conversion.returncode != 0:
            logger.error(f"FFmpeg failed: {conversion.stderr}")
            return {"success": True, "text": ""}

        
        silent = await loop.run_in_executor(_blocking_io_executor, _is_silent, wav_path)
        if silent:
            logger.info("Silent audio detected — skipping Whisper.")
            return {"success": True, "text": ""}

        result = await loop.run_in_executor(
            _whisper_executor,
            lambda: whisper_model.transcribe(
                wav_path,
                language=language if language != "auto" else None,
                fp16=False,
                no_speech_threshold=0.6,
            ),
        )

        text = result["text"].strip().lower()
        bad_outputs = {"", "thank you", "thanks", "thank you for watching"}
        if len(text) < 2 or text in bad_outputs:
            return {"success": True, "text": ""}

        logger.info(f"TRANSCRIPTION: {text}")
        return {"success": True, "text": text}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        for path in [temp_audio_path, wav_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass


# ── Chat management endpoints ─────────────────────────────────────────
@app.get("/api/chats")
async def get_chats(userId: str):
    chats = await chats_collection.find({"userId": userId}).sort("updatedAt", -1).to_list(100)
    return chats

@app.get("/api/messages")
async def get_messages(chatId: str, userId: str):
    msgs = await messages_collection.find({"chatId": chatId, "userId": userId}).to_list(100)
    return [
        {
            "id": str(m["_id"]),
            "role": m["role"],
            "content": m["content"],
            "entities": m.get("entities", []),
            "actions": m.get("actions", []),
        }
        for m in msgs
    ]

@app.patch("/api/chats/{chat_id}")
async def rename_chat(chat_id: str, userId: str, data: dict):
    title = data.get("title")
    if not title:
        raise HTTPException(status_code=400, detail="Title required")
    result = await chats_collection.update_one(
        {"_id": chat_id, "userId": userId},
        {"$set": {"title": title}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")
    return {"success": True}

@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str, userId: str):
    await asyncio.gather(
        chats_collection.delete_one({"_id": chat_id, "userId": userId}),
        messages_collection.delete_many({"chatId": chat_id, "userId": userId}),
    )
    return {"success": True}

@app.patch("/api/chats/{chat_id}/pin")
async def pin_chat(chat_id: str, userId: str):
    await chats_collection.update_one({"_id": chat_id, "userId": userId}, {"$set": {"pinned": True}})
    return {"success": True}

@app.patch("/api/chats/{chat_id}/unpin")
async def unpin_chat(chat_id: str, userId: str):
    await chats_collection.update_one({"_id": chat_id, "userId": userId}, {"$set": {"pinned": False}})
    return {"success": True}


# ── Reminder endpoints ────────────────────────────────────────────────
@app.post("/api/reminders")
async def api_create_reminder(req: ReminderCreateRequest):
    try:
        reminder = await create_reminder(
            user_id=req.userId,
            event_name=req.eventName,
            event_date_str=req.eventDate,
            source_type=req.sourceType,
            source_id=req.sourceId,
            notification_type=req.notificationType,
            reminder_offset=req.reminderOffset,
            chat_id=req.chatId,
        )
        is_duplicate = reminder.get("is_duplicate", False) if isinstance(reminder, dict) else False
        
        google_calendar_failed = reminder.get("google_calendar_failed", False) if isinstance(reminder, dict) else False
        return {
            "success": True,
            "reminder": reminder,
            "is_duplicate": is_duplicate,
            "google_calendar_failed": google_calendar_failed,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reminders/upcoming")
async def api_get_upcoming_reminders(userId: str):
    try:
        reminders = await get_upcoming_reminders(userId)
        return {"success": True, "reminders": reminders}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/reminders/{id}")
async def api_cancel_reminder(id: str, userId: str):
    try:
        success = await cancel_reminder(id, userId)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Notification endpoints ────────────────────────────────────────────
@app.get("/api/notifications")
async def api_get_notifications(userId: str):
    try:
        notifications = await get_notifications(userId)
        return {"success": True, "notifications": notifications}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/api/notifications/{id}/read")
async def api_mark_notification_read(id: str, userId: str):
    try:
        success = await mark_notification_read(id, userId)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/notifications/{id}/snooze")
async def api_snooze_reminder(id: str, req: SnoozeRequest):
    try:
        success = await snooze_reminder(id, req.userId, req.snoozeMinutes)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── User preference endpoints ─────────────────────────────────────────
@app.get("/api/user/preferences")
async def api_get_user_preferences(userId: str):
    try:
        pref = await get_user_preference(userId)
        if "_id" in pref:
            pref["_id"] = str(pref["_id"])
        for field in ("created_at", "updated_at"):
            if field in pref and isinstance(pref[field], datetime):
                pref[field] = pref[field].isoformat()
        return {"success": True, "preferences": pref}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/user/preferences")
async def api_save_user_preferences(req: PreferenceSaveRequest):
    try:
        pref = await save_user_preference(req.userId, req.notificationType, req.email)
        if "_id" in pref:
            pref["_id"] = str(pref["_id"])
        return {"success": True, "preferences": pref}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Google Calendar endpoints ─────────────────────────────────────────
@app.get("/api/google/auth-url")
async def api_google_auth_url(userId: str):
    try:
        url = get_auth_url(userId)
        return {"success": bool(url), "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/google/callback")
async def api_google_callback(code: str, state: str):
    try:
        await connect_google_oauth(state, code)
        
        target_origin = FRONTEND_ORIGIN or "*"
        return HTMLResponse(content=f"""
        <html>
            <head>
                <title>Google Calendar Connected</title>
                <script>
                    window.opener.postMessage({{ type: 'GOOGLE_CALENDAR_CONNECTED', success: true }}, {json.dumps(target_origin)});
                    window.close();
                </script>
            </head>
            <body style="font-family: sans-serif; text-align: center; padding: 50px;">
                <h2 style="color: #4f46e5;">Connection Successful!</h2>
                <p>Google Calendar has been connected. You can close this window now.</p>
            </body>
        </html>
        """)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/google/status")
async def api_google_status(userId: str):
    try:
        pref = await get_user_preference(userId)
        connected = pref.get("google_oauth", {}).get("connected", False)
        return {"success": True, "connected": connected}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/google/disconnect")
async def api_google_disconnect(userId: str):
    try:
        success = await disconnect_google_oauth(userId)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/google/test-event")
async def api_google_test_event(userId: str):
    try:
        pref = await get_user_preference(userId)
        if "_id" in pref:
            pref["_id"] = str(pref["_id"])

        google_oauth = pref.get("google_oauth", {})
        if not google_oauth or not google_oauth.get("connected"):
            return {"success": False, "error": "Google Calendar not connected for this user"}

        event_date = datetime.now(UTC) + timedelta(hours=1)
        event_id, refreshed_tokens = create_calendar_event(
            user_id=userId,
            google_oauth=google_oauth,
            event_name="VBOT Integration Test Event",
            event_date_dt=event_date,
            timezone="Asia/Kolkata",
            reminder_offset_minutes=30,
        )

        if refreshed_tokens:
            await db["user_preferences"].update_one(
                {"user_id": userId},
                {"$set": {"google_oauth": refreshed_tokens}},
            )

        if event_id:
            return {
                "success": True,
                "event_id": event_id,
                "message": "Test event successfully created in Google Calendar!",
                "refreshed_tokens_updated": bool(refreshed_tokens),
            }
        return {"success": False, "error": "Google Calendar event creation returned None. Check server logs."}

    except Exception as e:
        logger.error(f"Test event exception:\n{traceback.format_exc()}")
        return {"success": False, "error": str(e)}


# ── Health check ──────────────────────────────────────────────────────
@app.get("/")
async def home():
    return {"message": "Backend running"}


@app.get("/api/debug/threads")
async def debug_threads():
    """Live thread count — use this to catch zombie threads after timeouts."""
    return {
        "active_thread_count": threading.active_count(),
        "thread_names": [t.name for t in threading.enumerate()],
    }


@app.get("/api/admin/stats")
async def admin_stats():
    """High-level counters for the dashboard overview."""
    total_chats = await chats_collection.count_documents({})
    total_messages = await messages_collection.count_documents({})
    total_users = len(await chats_collection.distinct("userId"))

    try:
        upcoming_reminders = await db["reminders"].count_documents({"status": "pending"})
    except Exception as e:
        logger.warning(f"[admin_stats] failed to count reminders (check collection name): {e}")
        upcoming_reminders = None

    try:
        unread_notifications = await db["notifications"].count_documents({"read": False})
    except Exception as e:
        logger.warning(f"[admin_stats] failed to count notifications (check collection name): {e}")
        unread_notifications = None

    return {
        "success": True,
        "stats": {
            "total_chats": total_chats,
            "total_messages": total_messages,
            "total_users": total_users,
            "upcoming_reminders": upcoming_reminders,
            "unread_notifications": unread_notifications,
            "active_threads": threading.active_count(),
        },
    }

#, dependencies=[Depends(require_admin_key)]
@app.get("/api/admin/chats")
async def admin_list_chats(limit: int = 50, skip: int = 0):
    """All chats across all users, most recently updated first."""
    chats = await chats_collection.find({}).sort("updatedAt", -1).skip(skip).limit(limit).to_list(limit)
    for c in chats:
        c["_id"] = str(c["_id"])
        for field in ("createdAt", "updatedAt"):
            if isinstance(c.get(field), datetime):
                c[field] = c[field].isoformat()
    return {"success": True, "chats": chats}


@app.get("/api/admin/users")
async def admin_list_users():
    """Distinct users with chat counts and last-active time, for the user picker."""
    pipeline = [
        {"$group": {
            "_id": "$userId",
            "chatCount": {"$sum": 1},
            "lastActive": {"$max": "$updatedAt"},
        }},
        {"$sort": {"lastActive": -1}},
    ]
    users = await chats_collection.aggregate(pipeline).to_list(500)
    for u in users:
        if isinstance(u.get("lastActive"), datetime):
            u["lastActive"] = u["lastActive"].isoformat()
    return {"success": True, "users": users}


def _percentile(sorted_values: list, pct: float):
    """Simple percentile on an already-sorted list — fine for dashboard-scale windows."""
    if not sorted_values:
        return None
    idx = min(int(len(sorted_values) * pct), len(sorted_values) - 1)
    return sorted_values[idx]


async def _stage_stats(match: dict, field: str):
   
    cursor = db["pipeline_metrics"].find(
        {**match, field: {"$ne": None}}, {field: 1}
    ).sort("createdAt", -1).limit(2000)
    values = sorted([doc[field] async for doc in cursor])
    if not values:
        return {"avg": None, "p95": None, "max": None, "count": 0}
    return {
        "avg": round(sum(values) / len(values)),
        "p95": _percentile(values, 0.95),
        "max": values[-1],
        "count": len(values),
    }


@app.get("/api/admin/pipeline/summary")
async def admin_pipeline_summary(hours: int = 24):
    
    since = datetime.now(UTC) - timedelta(hours=hours)
    match = {"createdAt": {"$gte": since}}

    total_requests = await db["pipeline_metrics"].count_documents(match)
    timeouts = await db["pipeline_metrics"].count_documents({**match, "timed_out": True})
    errors = await db["pipeline_metrics"].count_documents({**match, "error": {"$ne": None}})
    reranker_fallbacks = await db["pipeline_metrics"].count_documents({**match, "reranker_fallback": True})

    router_dist_pipeline = [
        {"$match": match},
        {"$unwind": "$sources"},
        {"$group": {"_id": "$sources", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    router_distribution = await db["pipeline_metrics"].aggregate(router_dist_pipeline).to_list(20)

    stages = {}
    for field in ["router_ms", "retrieval_ms", "reranker_ms", "generation_ms", "rag_total_ms", "reminder_llm_ms", "total_ms"]:
        stages[field] = await _stage_stats(match, field)

    slowest = await db["pipeline_metrics"].find(
        {**match, "total_ms": {"$ne": None}}
    ).sort("total_ms", -1).limit(10).to_list(10)
    for s in slowest:
        s["_id"] = str(s["_id"])
        if isinstance(s.get("createdAt"), datetime):
            s["createdAt"] = s["createdAt"].isoformat()

    recent_failures = await db["pipeline_metrics"].find({
        **match,
        "$or": [{"timed_out": True}, {"error": {"$ne": None}}],
    }).sort("createdAt", -1).limit(20).to_list(20)
    for f in recent_failures:
        f["_id"] = str(f["_id"])
        if isinstance(f.get("createdAt"), datetime):
            f["createdAt"] = f["createdAt"].isoformat()

    return {
        "success": True,
        "window_hours": hours,
        "totals": {
            "requests": total_requests,
            "timeout_rate": round(timeouts / total_requests, 4) if total_requests else 0,
            "error_rate": round(errors / total_requests, 4) if total_requests else 0,
            "reranker_fallback_rate": round(reranker_fallbacks / total_requests, 4) if total_requests else 0,
        },
        "router_distribution": router_distribution,
        "stages": stages,
        "slowest_queries": slowest,
        "recent_failures": recent_failures,
    }


from admin.admin_scrape import router as admin_scrape_router
from admin.admin_ingest import router as admin_ingest_router

app.include_router(admin_scrape_router)
app.include_router(admin_ingest_router)
app.include_router(admin_vectordb_router)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)