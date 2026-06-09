import json
from langchain_ollama import ChatOllama

_router_llm = ChatOllama(
    model="qwen3:0.6b",
    base_url="http://localhost:11435",
    temperature=0
)

ROUTER_SYSTEM = """You are a routing agent for a VIT university chatbot.
Decide which data source(s) to query based on the user question.

Sources available:
- "qdrant"  : regulations, fees, clubs, academic policies (vector DB)
- "mongodb" : contact details related to counsellor, faculty, departments , committee (MongoDB)

Return ONLY valid JSON, no other text:
{"sources": ["qdrant"], "reason": "one sentence"}

Rules:
- Academic rules, fees, clubs, hostel → ["qdrant"]
- contact details → ["mongodb"]
- Questions mixing both → ["qdrant", "mongodb"]
- When unsure → ["qdrant"]"""

async def route_query(query: str) -> dict:
    try:
        resp = await _router_llm.ainvoke([
            {"role": "system", "content": ROUTER_SYSTEM},
            {"role": "user",   "content": query}
        ])
        raw = resp.content.strip()
        # strip thinking tags if qwen outputs them
        if "</think>" in raw:
            raw = raw.split("</think>")[-1].strip()
        return json.loads(raw)
    except Exception as e:
        print(f"[router] fallback to qdrant: {e}")
        return {"sources": ["qdrant"], "reason": "fallback"}
