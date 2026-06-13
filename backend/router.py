import json
import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama

load_dotenv()

ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

_router_llm = ChatOllama(model="qwen3:8b-q4_K_M",base_url="http://localhost:11435", temperature=0,extra_body={"think": False} )

ROUTER_SYSTEM = """You are a routing agent for a VIT university chatbot.
Decide which data source(s) to query based on the user question.

Sources available:
- "qdrant"   : regulations, fees, clubs, academic policies (vector DB)
- "mongodb"  : contact details - counsellor, faculty, departments, committee (MongoDB)
- "reminder" : user mentions a personal event/exam/deadline WITH a specific date AND wants to be reminded

Return ONLY valid JSON, no other text:
{"sources": ["qdrant"], "reason": "one sentence"}

Rules:
- Pure reminder with date → ["reminder"]
- Academic rules, fees, clubs, hostel, procedures → ["qdrant"]
- Contact details → ["mongodb"]
- Mixed academic + reminder → ["qdrant", "reminder"]
- Mixed contact + reminder → ["mongodb", "reminder"]
- Mixed academic + contact → ["qdrant", "mongodb"]
- Mixed all three → ["qdrant", "mongodb", "reminder"]
- When unsure → ["qdrant"]

REMINDER EXAMPLES:
- "i have chemistry exam on 18th june, set a reminder" → ["reminder"]
- "when is the fee deadline and remind me on july 1" → ["qdrant", "reminder"]
- "who is my counsellor and remind me to meet them on friday" → ["mongodb", "reminder"]
- "how to get id card?" → ["qdrant"]
- "what are the exam rules?" → ["qdrant"]
"""

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
