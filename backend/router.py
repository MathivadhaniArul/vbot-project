import json
import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama

load_dotenv()

ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

_router_llm = ChatOllama(
    model="llama3:8b",
    base_url=ollama_url,
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
- For scheduling, setting reminders, or personal calendar event declarations (e.g., "I have my exam on...", "set a reminder for...", "my software project is on...") -> []
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
        data = json.loads(raw)
        if isinstance(data, list):
            return {"sources": data, "reason": "returned list"}
        if not isinstance(data, dict):
            return {"sources": ["qdrant"], "reason": "invalid JSON format"}
        return data
    except Exception as e:
        print(f"[router] fallback to qdrant: {e}")
        return {"sources": ["qdrant"], "reason": "fallback"}
