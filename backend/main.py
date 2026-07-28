import uuid
import os
import socket
from dotenv import load_dotenv
from datetime import datetime, timedelta
# Force IPv4 to prevent IPv6 DNS resolution timeouts for Google Calendar APIs
orig_getaddrinfo = socket.getaddrinfo
def patched_getaddrinfo(*args, **kwargs):
    responses = orig_getaddrinfo(*args, **kwargs)
    return [r for r in responses if r[0] == socket.AF_INET]
socket.getaddrinfo = patched_getaddrinfo

# Load environment variables first so all imported modules can access them
load_dotenv()


import uvicorn
import re
import json
import shutil
import asyncio
import hashlib
import logging
import tempfile
import urllib.parse
import subprocess
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from router import route_query
from mongo_retriever import fetch_mongo_docs

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.background import BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient

# LangChain
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import ChatOllama
from langchain_community.vectorstores import Chroma
#from langchain.memory import ConversationSummaryMemory
from db_memory import load_memory, save_memory_summary
from langchain.chains import create_history_aware_retriever
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import FlashrankRerank

import whisper
import edge_tts
import torch

# ── Logging Configuration ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Quiet noisy libraries
logging.getLogger("chromadb").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

logger = logging.getLogger("main")

# Add ffmpeg to PATH
os.environ["PATH"] += os.pathsep + str(Path(__file__).resolve().parent / "ffmpeg_bin")

app = FastAPI()
os.environ["ANONYMIZED_TELEMETRY"] = "False"

mongo_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
if not os.path.exists("/.dockerenv") and ("mongodb:27017" in mongo_uri or "host.docker.internal" in mongo_uri):
    mongo_uri = "mongodb://localhost:27017"

client = AsyncIOMotorClient(mongo_uri)
db = client["chatbot_db"]
messages_collection = db["messages"]
chats_collection = db["chats"]



app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-User-Text", "X-Assistant-Text"],
)


retrieval_chain = None
rag_chain = None
question_answer_chain = None
memory = None
chat_memories = {}

ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
if not os.path.exists("/.dockerenv") and "host.docker.internal" in ollama_url:
    ollama_url = "http://localhost:11434"

llm = ChatOllama(model="llama3:8b", temperature=0.2, base_url=ollama_url)

whisper_model = whisper.load_model("small")
_whisper_executor = ThreadPoolExecutor(max_workers=1)

# embeddings = OllamaEmbeddings(
#     model="nomic-embed-text",
#      base_url="http://127.0.0.1:11434" 
#     )
embeddings = HuggingFaceEmbeddings(
    model_name="nomic-ai/nomic-embed-text-v1.5",
    model_kwargs={"trust_remote_code": True}
)


def structure_chunk(data):
    chunks = []


    for url, sections in data.items():
        for heading, contents in sections.items():


           
            if "frequently asked questions" in heading.lower():
                for item in contents:
                    chunks.append({
                        "type": "faq",
                        "source": url,
                        "heading": heading,
                        "content": item
                    })


            elif isinstance(contents, dict):
             
                for key, value in contents.items():
                    combined = f"{value}"
                    chunks.append({
                        "type": "section",
                        "source": url,
                        "heading": heading,
                        "subcontent": key,
                        "content": combined
                    })
                all = list(contents.keys())
                all.remove("BEWARE OF ILLEGAL/FAKE WEBSITES")
                chunks.append({
                    "type": "list",
                    "source": url,
                    "heading": f"{heading} list",
                    "subcontent": "all clubs/chapters",
                    "content": ", ".join(all)
                    })
                   
            elif isinstance(contents, list):
                length = len(contents)
                combined=""
                for i in range(0, length):
                    combined += f"{contents[i]}\n"
                chunks.append({
                        "type": "section",
                        "source": url,
                        "heading": heading,
                        "content": combined
                    })
               


    return chunks


def hash_text(text: str):
    return hashlib.md5(text.encode()).hexdigest()



def clean_text(text: str):
    text = re.sub(r'(\*\*|__)', '', text)
    return text.strip()


def sanitize_misleading_wording(text: str) -> str:
    import re
    text = re.sub(r'\bis scheduled for\b', 'takes place on', text, flags=re.IGNORECASE)
    text = re.sub(r'\bhas been scheduled for\b', 'takes place on', text, flags=re.IGNORECASE)
    text = re.sub(r'\bscheduled for\b', 'on', text, flags=re.IGNORECASE)
    text = re.sub(r'\bI have noted this down\b', 'I found the event details', text, flags=re.IGNORECASE)
    text = re.sub(r'\bI have noted it down\b', 'I found the event details', text, flags=re.IGNORECASE)
    text = re.sub(r'\bnoted down\b', 'found', text, flags=re.IGNORECASE)
    text = re.sub(r'\bnote this down\b', 'view this event', text, flags=re.IGNORECASE)
    text = re.sub(r'\breminder set\b', 'reminder option', text, flags=re.IGNORECASE)
    text = re.sub(r'\badded to calendar\b', 'can be added to your calendar', text, flags=re.IGNORECASE)
    text = re.sub(r'\badded to your calendar\b', 'can be added to your calendar', text, flags=re.IGNORECASE)
    text = re.sub(r'\byour reminder has been set\b', 'you can set your reminder below', text, flags=re.IGNORECASE)
    text = re.sub(r'\byour event is scheduled\b', 'your event takes place', text, flags=re.IGNORECASE)
    return text



def split_markdown_with_subsections(md_text):
    md_text = clean_text(md_text)


    chunks = []


    current_h1 = ""
    current_h2 = ""
    current_h3 = ""
    current_content = []


    def save_chunk():
        content = "\n".join(line.strip() for line in current_content).strip()

        if content:
            chunks.append({
                "type": "section",
                "heading": current_h1,
                "subheading": current_h2,
                "subsubheading": current_h3,
                "content": content
            })


    for line in md_text.splitlines():


        h1 = re.match(r"^\s*#\s+(.*)", line)
        h2 = re.match(r"^\s*##\s+(.*)", line)
        h3 = re.match(r"^\s*###\s+(.*)", line)



        if h1:
            save_chunk()


            current_h1 = h1.group(1).strip()
            current_h2 = ""
            current_h3 = ""
            current_content = []


        elif h2:
            save_chunk()


            current_h2 = h2.group(1).strip()
            current_h3 = ""
            current_content = []


        elif h3:
            save_chunk()


            current_h3 = h3.group(1).strip()
            current_content = []


        else:
            current_content.append(line)


    save_chunk()


    return chunks


async def ensure_chat(chat_id: str, user_id: str, first_message: str):
    chat = await chats_collection.find_one({"_id": chat_id})

    if not chat:
        await chats_collection.insert_one({
            "_id": chat_id,
            "userId": user_id,  
            "title": first_message[:40],
            "memorySummary": "", 
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
        })
        





@app.on_event("startup")
def startup():
    global retrieval_chain, memory, rag_chain, question_answer_chain

    # print("Building RAG pipeline...")

    BASE_DIR = Path(__file__).resolve().parent
    REG_DIR = BASE_DIR / "reg_md"

    docsearch = Chroma(
    collection_name="vit-regulations",
    embedding_function=embeddings,
    persist_directory=str(BASE_DIR / "chroma")
    )
     
    data=[]
    
    
    if False:
        print("Indexing documents...")
        docs = []
        for path in REG_DIR.rglob("*.md"):
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
                

            chunks = split_markdown_with_subsections(text)
            
            for chunk in chunks:
                parts = [
                    chunk.get('heading') or "",
                    chunk.get('subheading') or "",
                    chunk.get('subsubheading') or "",
                    chunk.get('content') or ""
                    ]
                content = ". ".join([p for p in parts if p])
               
                docs.append(
                   Document(
            page_content=content.strip(),
            metadata={
                "id": hash_text(chunk.get("content"))or "",
                "heading": chunk.get("heading") or "",
                "subheading": chunk.get("subheading") or "",
                "subsubheading": chunk.get("subsubheading") or "",
                "type": chunk.get("type") or "",
                "source": str(path.relative_to(BASE_DIR)),
                "keywords": " ".join([
                    chunk.get("heading") or "",
                    chunk.get("subheading") or "",
                    chunk.get("subsubheading") or ""
                ]).lower()
            }
        )
    )
        
        JSON_FILES = [
    str(BASE_DIR / "scrape" / "vit_final_with_links.json"),
    str(BASE_DIR / "scrape" / "vit_all_data.json")
]
        def safe_meta(value):
            if value is None:
                return ""
            return str(value)

        all_chunks = []
        for file_path in JSON_FILES:
       
          print(f" Processing: {file_path}")
          with open(file_path, encoding="utf-8") as f:
            data = json.load(f)
            chunks = structure_chunk(data)
            all_chunks.extend(chunks)   # combine all chunks



        with open("vit_chunks.json", "w", encoding="cp1252") as f:
            json.dump(all_chunks, f, indent=2, ensure_ascii=False)
        
        for chunk in all_chunks:
            content = f"""
            Category: {chunk.get('heading','')}
            Name: {chunk.get('subcontent','')}
            Description: {chunk.get('content','')}
            """
            docs.append(
        Document(
            page_content=content.strip(),
            metadata={
    "id": safe_meta(hash_text(content)),
    "source": safe_meta(chunk.get("source")),
    "heading": safe_meta(chunk.get("heading")),
    "subheading": safe_meta(chunk.get("subcontent")),
    "type": safe_meta(chunk.get("type")),
    "keywords": (
        safe_meta(chunk.get("subcontent")) + " " +
        safe_meta(chunk.get("heading"))
    ).lower()
}
        )
    )
   
        print("Chunking complete!")

        # # Also index Riviera data
        # riviera_path = BASE_DIR / "scrape/riviera_data.json"
        # if riviera_path.exists():
        #     print("Indexing Riviera data...")
        #     with open(riviera_path, encoding="utf-8") as f:
        #         riviera_data = json.load(f)
        #     riviera_chunks = structure_chunk(riviera_data)
        #     for chunk in riviera_chunks:
        #         content = f"""
        #         Heading: {chunk['heading']}
        #         Content: {chunk['content']}
        #         """
        #         docs.append(
        #             Document(
        #                 page_content=content.strip(),
        #                 metadata={
        #                     "id": hash_text(content),
        #                     "source": chunk.get("source") or "riviera_website",
        #                     "heading": chunk.get("heading"),
        #                     "type": chunk.get("type", "section")
        #                 }
        #             )
        #         )
        #     print(f"Riviera chunks added: {len(riviera_chunks)}")
        # else:
        #     print("Warning: riviera_chunks.json not found, skipping.")
        print("Chunking complete!")
            
            
        
        
        
        if docs:   
            ids = [str(uuid.uuid4()) for _ in docs]
            docsearch.add_documents(docs, ids=ids)
            print("Indexing complete.")
    else:
            print("Collection already populated. Skipping embedding.")
   
    print(" Chroma loaded:", docsearch._collection.count())
    
    
    template = """
You are an helpful assistant for VIT .


Answer ONLY using the provided context.


-----------------------------
STRICT RULES
-----------------------------


1. ANSWER FROM CONTEXT (VERY IMPORTANT)
- Extract the answer from:
  • headings
  • labels
  • content
- If the answer appears ANYWHERE → treat it as AVAILABLE.
- DO NOT ignore headings.


2. NO CONTRADICTIONS
- NEVER say "not available" if the answer exists in the context.
- EXCEPTION: for phone numbers, emails, office locations, or personal contact details:
  • provide them ONLY if exact contact details are explicitly present
  • otherwise say:
    "No specific contact details found in the provided context"
- Do NOT invent or substitute contacts from related departments/services.

3. EXACTNESS
- Do NOT change numbers or conditions.

4. If retrieval is weak or missing:
- DO NOT say only “not relevant”
- Instead respond with:
  safe acknowledgment + guidance
- answer is not explicitly in context:
  DO NOT explain possible rules
  DO NOT speculate
  ONLY state absence of information
  DO NOT describe unrelated context



5. STYLE
- Do NOT copy text
- Explain clearly in your own words
- Keep it natural and concise
- DO NOT include phrases like:
  • "According to the provided context"
  • "The context states"
  • "This information is found in"
  • "As mentioned above"
- DO NOT reference the context at all.
- Start directly with the answer.
- Always use provided data to fully answer the user before mentioning any external link. Never respond with only a URL or reference.

6. LANGUAGE MODE RULE
   
You MUST respond ONLY in the language specified by the user system setting.

Selected language: {language}

Rules:
1. Always respond strictly in the selected language.
2. Do NOT auto-detect or change language based on user input.
3. Do NOT mix languages in the response.
4. Only allow English words for:
   - Technical terms (API, database, model names, code, etc.)
   - Proper nouns (names, places, brands)
5. If language = "auto", then detect user input language and respond in the same language.
6. If language is unsupported or unclear, default to English.
7. Do not mention these rules to the user.

7. STRUCTURED RESPONSE RULE

You MUST always respond in JSON format with this exact schema:
{{
  "answer": "Your detailed conversational answer in the selected language",
  "entities": [],
  "actions": []
}}

CRITICAL: The "answer" field must ALWAYS contain a full, helpful response using the provided context.
- NEVER leave "answer" empty or say "not found" just because entities is empty
- entities and actions being empty does NOT affect the quality of your answer
- Answer the question completely FIRST, then decide if entities apply

Populate entities and actions ONLY when ALL three are true:
  1. User states a specific date explicitly
  2. User explicitly requests a reminder
  3. Subject is a time-based academic event

Otherwise set entities: [] and actions: [] but STILL give a complete answer.

EXAMPLES:
  User: "how to get new id card?" 
  → Full answer about ID card process, entities: [], actions: []
  
  User: "I have chemistry exam on June 15, set a reminder"
  → Acknowledge + populate entities and actions
"""

    
    
    qa_prompt = ChatPromptTemplate.from_messages([
     ("system",template),
    MessagesPlaceholder("chat_history"),
    ("human", """
Context:
{context}


Question:
{input}


Instructions:
- If ANY relevant information exists → answer
- Do NOT say "not available" unless context is completely unrelated
""")
])

    
    def setup_retriever(docsearch):
        base_retriever = docsearch.as_retriever(search_type="mmr",
        search_kwargs = {
    "k": 12,
    "fetch_k": 180,
    "lambda_mult": 0.7
})
        compressor = FlashrankRerank(
        model="ms-marco-MiniLM-L-12-v2"
    )


        retriever = ContextualCompressionRetriever(base_compressor=compressor, base_retriever=base_retriever)
        return retriever


    retriever = setup_retriever(docsearch)
    contextualize_q_prompt = ChatPromptTemplate.from_messages([
    ("system",
     """
You are a query rewriting assistant for a retrieval system.


Your job is to convert the user's latest question into a COMPLETE and SPECIFIC query.




RULES:
- Use chat history to understand context
- Expand vague queries into full meaningful questions
- Replace words like:
  • "it", "this", "that", "other", "more"
  with the actual topic
- Always include key terms (like SAP, clubs, eligibility, etc.)


- DO NOT answer the question
- ONLY return the rewritten query

- If the user question is not in English:
  • First translate it to English.
  • Then rewrite it into a complete retrieval query.
  • Return only the final English retrieval query.


EXAMPLES:


Chat:
User: in which semester can we do SAP?
User: other dept?
→ Rewritten: SAP semester eligibility for all programs and departments


Chat:
User: tell me about ALPHA BIO CELL
User: tell more
→ Rewritten: detailed description of ALPHA BIO CELL club


Chat:
User: list technical clubs
User: what about others
→ Rewritten: list all technical clubs


"""),
    MessagesPlaceholder("chat_history"),
    ("human", "{input}")
])


    
    
    
    history_aware_retriever = create_history_aware_retriever(
    llm,
    retriever,
    contextualize_q_prompt
    ) 
     
    question_answer_chain = create_stuff_documents_chain(
    llm,
    qa_prompt
    )
    
    rag_chain = create_retrieval_chain(
    history_aware_retriever,
    question_answer_chain)
    
#     results = retriever.get_relevant_documents(
#     "what is the eligibility for sap",
#     k=50
# )

#     for r in results:
#         print("----")
#         print(r.page_content)
        
    print(" RAG Ready!")

    # ── Start Auto-Update Pipeline Scheduler ─────────────────────────
    try:
        from pipeline.scheduler import start_scheduler
        start_scheduler()
        print(" Pipeline scheduler started!")
    except Exception as e:
        print(f"⚠️ Pipeline scheduler failed to start: {e}")
        print("  (The chatbot will still work, just without auto-updates)")

    # ── Ensure MongoDB Indexes ────────────────────────────────────────
    try:
        from reminder_service import ensure_indexes
        loop = asyncio.get_event_loop()
        loop.create_task(ensure_indexes())
        print(" Database indexes scheduled.")
    except Exception as e:
        print(f"⚠️ Index creation skipped: {e}")

    # ── Start Reminder Scheduler ──────────────────────────────────────
    # Deliberately independent of the scrape pipeline above: reminder delivery
    # must keep working even when the scraping stack fails to start.
    try:
        from reminder_scheduler import start_reminder_scheduler, get_check_interval_seconds
        start_reminder_scheduler()
        print(f" Reminder scheduler started (every {get_check_interval_seconds()}s).")
    except Exception as e:
        logger.error(f"Reminder scheduler failed to start: {e}", exc_info=True)
        print(f"⚠️ Reminder scheduler failed to start: {e}")
        print("  (Reminders will NOT be delivered until this is fixed)")


def parse_llm_response(raw_text: str) -> dict:
    raw_text = raw_text.strip()
    
    # Clean up markdown code blocks first
    if "```" in raw_text:
        block_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_text, re.DOTALL)
        if block_match:
            raw_text = block_match.group(1).strip()
            
    # Try parsing direct JSON
    try:
        data = json.loads(raw_text)
        if isinstance(data, dict) and "answer" in data:
            return {
                "answer": data["answer"],
                "entities": data.get("entities", []),
                "actions": data.get("actions", [])
            }
    except Exception:
        pass

    # Try extracting JSON using regex search
    try:
        match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
            if isinstance(data, dict) and "answer" in data:
                return {
                    "answer": data["answer"],
                    "entities": data.get("entities", []),
                    "actions": data.get("actions", [])
                }
    except Exception:
        pass

    # Fallback to returning raw text as conversational answer
    return {
        "answer": raw_text,
        "entities": [],
        "actions": []
    }


class ChatRequest(BaseModel):
    chatId: str
    userId: str
    text: str
    language: str = "en"

class FeedbackRequest(BaseModel):
    feedback: str



@app.post("/api/chat")
async def chat(req: ChatRequest):


    await ensure_chat(req.chatId, req.userId, req.text)


   
    await messages_collection.insert_one({
        "chatId": req.chatId,
        "userId": req.userId,  
        "role": "user",
        "content": req.text,
        "createdAt": datetime.utcnow()
    })


    answer = "Unknown error"
    
    raw_entities = []
    raw_actions = []
    conversational_answer = "Unknown error"  # ← add this
    entities = []                             # ← add this  
    actions = [] 


    try:
        
        
        memory = await load_memory(req.chatId, req.userId)
        # ── Step 1: route ────────────────────────────────────
        routing = await route_query(req.text)
        sources = routing.get("sources", ["qdrant"])
        print(f"[router] {sources} <- {routing.get('reason')}")

        from zoneinfo import ZoneInfo
        now_str = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S %Z")

        # ── Step 2: parallel fetch ────────────────────────────
        tasks = []
        if "mongodb" in sources:
            tasks.append(fetch_mongo_docs(req.text))

        mongo_docs = []
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            mongo_docs = results[0] if not isinstance(results[0], Exception) else []

        extra_context = ""
        if mongo_docs:
            parts = [f"[MONGODB]\n{d.page_content}" for d in mongo_docs]
            extra_context = "\n\n".join(parts)

        # ── Step 3: build invoke input & call ─────────────────
        if "qdrant" in sources or "mongodb" in sources:
            invoke_input = req.text
            if "reminder" in sources:
                invoke_input = f"[Current date: {now_str}]\n{invoke_input}"
            if "qdrant" not in sources and extra_context:
                invoke_input = f"CONTEXT ONLY FROM DB:\n{extra_context}\n\nQuestion: {invoke_input}"
                extra_context = ""

            result = await rag_chain.ainvoke({
                "input": invoke_input,
                "chat_history": memory.chat_memory.messages,
                "language": req.language,
            })
            answer = result.get("answer", "No answer returned")

            if extra_context and "qdrant" in sources:
                merged_input = f"Additional records from database:\n{extra_context}\n\nOriginal question: {req.text}"
                if "reminder" in sources:
                    merged_input = f"[Current date: {now_str}]\n{merged_input}"
                result2 = await rag_chain.ainvoke({
                    "input": merged_input,
                    "chat_history": memory.chat_memory.messages,
                    "language": req.language,
                })
                answer = result2.get("answer", answer)

        elif "reminder" in sources:
            # Pure reminder — bypass RAG entirely
            from reminder_policy import OFFICIAL_CATEGORIES, official_categories_summary
            reminder_result = await llm.ainvoke([
                {
                    "role": "system",
                    "content": f"""You are VBOT, the VIT college assistant. Current date and time: {now_str}

VBOT only sets reminders for official college events and announcements:
{official_categories_summary()}.
Personal to-dos (alarms, drinking water, calling someone, gym, chores, personal
study time) are NOT supported and must NOT produce an entity.

If the request is about an official college event or announcement, extract its
details. If it is a personal task, politely explain that you only handle official
college events and announcements, and return empty entities and actions.

Respond ONLY in this JSON format:
{{
  "answer": "A friendly confirmation, or a polite refusal for personal tasks",
  "entities": [
    {{
      "type": "{' | '.join(OFFICIAL_CATEGORIES)}",
      "name": "Name of the official event or announcement",
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
                {"role": "user", "content": req.text}
            ])
            answer = reminder_result.content.strip()
            if "</think>" in answer:
                answer = answer.split("</think>")[-1].strip()

        else:
            # fallback — should rarely hit
            result = await rag_chain.ainvoke({
                "input": req.text,
                "chat_history": memory.chat_memory.messages,
                "language": req.language,
            })
            answer = result.get("answer", "No answer returned")

        # ── Parse LLM response for entities/actions ───────────
        print("====== REMINDER PIPELINE DEBUGGING ======")
        print(f"RAW LLM RESPONSE:\n{answer}")

        parsed_data = parse_llm_response(answer)
        conversational_answer = parsed_data["answer"]
        raw_entities = parsed_data["entities"]
        raw_actions = parsed_data["actions"]

        print(f"PARSED ENTITIES (PRE-FILTER): {raw_entities}")
        print(f"PARSED ACTIONS (PRE-FILTER): {raw_actions}")
        # Deterministic Event Category & Date Validation
        from reminder_service import parse_iso_datetime, get_now_tz, normalize_event_name
        from reminder_policy import (
            classify_reminder_subject,
            is_reminder_request,
            rejection_message,
        )

        now = get_now_tz("Asia/Kolkata")
        entities = []
        actions = []
        rejected_personal = False

        for entity in raw_entities:
            try:
                # 1. Date Check: parse date and verify it is in the future
                dt_str = entity.get("date", "")
                if not dt_str:
                    print(f"Skipping entity: No date found. Entity: {entity}")
                    continue
                dt = parse_iso_datetime(dt_str)
                if dt <= now:
                    print(f"Skipping entity: Date {dt} is not in the future (now: {now}).")
                    # Historical/past event, skip
                    continue

                # 2. Official-source check: VBOT only reminds about official college
                #    events and announcements, never personal to-dos.
                classification = classify_reminder_subject(
                    entity.get("name", ""),
                    entity.get("type", ""),
                    entity.get("source_id"),
                )
                if not classification.allowed:
                    print(
                        f"Skipping entity: not official college information "
                        f"(reason={classification.reason}, matched={classification.matched!r}). Entity: {entity}"
                    )
                    rejected_personal = True
                    continue

                print(f"Entity passed all checks: {entity} (category={classification.category})")

                # Standardize both properties in clean ISO string format
                iso_date = dt.isoformat()
                entity["date"] = iso_date
                entity["event_name"] = entity.get("name", "")
                entity["event_date"] = iso_date
                entity["event_type"] = entity.get("type", "")
                entity["official_category"] = classification.category
                entity["official_source"] = classification.source
                entity["show_reminder"] = True

                # Keep both old and new properties to maintain compatibility
                entities.append(entity)

                # Keep matching set_reminder actions if any (using case-insensitive & space-insensitive matching)
                for action in raw_actions:
                    if action.get("type") == "set_reminder":
                        action_entity = normalize_event_name(action.get("entity", ""))
                        entity_name = normalize_event_name(entity.get("name", ""))
                        if action_entity == entity_name:
                            print(f"Matching action found: {action}")
                            actions.append(action)
                        else:
                            print(f"Action name mismatch: '{action_entity}' vs '{entity_name}'")

            except Exception as exc:
                print("Error validating entity:", exc)
                continue
        # Safeguard: if any entity is found, sanitize misleading language
        if entities:
            conversational_answer = sanitize_misleading_wording(conversational_answer)
        elif rejected_personal or (
            # No entity survived, but the user plainly asked for a reminder and the
            # subject is not official. Checked against the user's own words so the
            # refusal does not depend on the router or on the model bothering to
            # emit an entity — left unchecked, the model happily replies
            # "I've set your reminder!" for "remind me to drink water".
            is_reminder_request(req.text)
            and not classify_reminder_subject(req.text).allowed
        ):
            # Replace rather than append: a personal reminder request carries no
            # other informational content worth preserving, and any fabricated
            # confirmation in the model's answer must not survive.
            conversational_answer = rejection_message()


        #  update memory
        memory.chat_memory.add_user_message(req.text)
        memory.chat_memory.add_ai_message(conversational_answer)
       
       # memory.chat_memory.add_ai_message(answer)


        await save_memory_summary(req.chatId, req.userId, memory)


    except Exception as e:
        print("Chat error:", e)
        answer = f"Error: {str(e)}"
        conversational_answer = f"Error: {str(e)}"
        entities = []
        actions = []


    # store assistant reply
    await messages_collection.insert_one({
   "chatId": req.chatId,
        "userId": req.userId,  
        "role": "assistant",
        "content": conversational_answer,
        "entities": entities,
        "actions": actions,
        "createdAt": datetime.utcnow()    
})


    # update timestamp
    await chats_collection.update_one(
   {
            "_id": req.chatId,
            "userId": req.userId   
        },
        {
            "$set": {"updatedAt": datetime.utcnow()}
        }
    )

    print("\nUSER:", req.text)
    print("\nANSWER:", answer)
    return {
        "answer": conversational_answer,
        "entities": entities,
        "actions": actions,
        "debug_raw_entities": raw_entities
        }

@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...),language: str = Form("en")):
    temp_audio = None
    wav_path = None
    
    

    try:
        suffix = ".webm"
        content_type = file.content_type or ""

        if "wav" in content_type:
            suffix = ".wav"
        elif "mp4" in content_type or "m4a" in content_type:
            suffix = ".m4a"
        elif "ogg" in content_type:
            suffix = ".ogg"

        # ---------- SAVE FILE ----------
        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        temp_audio_path = temp_audio.name

        contents = await file.read()

        with open(temp_audio_path, "wb") as f:
            f.write(contents)

        print(f"Saved audio: {temp_audio_path} ({len(contents)} bytes)")

        # ---------- CONVERT TO WAV ----------
        import uuid

        wav_path = os.path.join(
            tempfile.gettempdir(),
            f"{uuid.uuid4()}.wav"
        )

        conversion = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                temp_audio_path,
                "-ac", "1",
                "-ar", "16000",
                "-sample_fmt", "s16",
                wav_path
            ],
            capture_output=True,
            text=True
        )

        if conversion.returncode != 0:
            print("FFmpeg failed:", conversion.stderr)
            return {"success": True, "text": ""}

        transcribe_path = wav_path

        # ---------- SILENCE DETECTION (NO EXTERNAL LIB) ----------
        import wave
        import numpy as np

        def is_silent(path):
            try:
                with wave.open(path, "rb") as wf:
                    frames = wf.readframes(wf.getnframes())
                    audio = np.frombuffer(frames, dtype=np.int16)

                    if len(audio) == 0:
                        return True

                    volume = np.abs(audio).mean()
                    return volume < 200  # tweak if needed
            except:
                return True

        # 🚨 skip silent audio BEFORE Whisper
        if is_silent(transcribe_path):
            print("Silent audio detected - skipping Whisper")
            return {"success": True, "text": ""}

        # ---------- WHISPER ----------
        loop = asyncio.get_running_loop()

        result = await loop.run_in_executor(
            _whisper_executor,
            lambda: whisper_model.transcribe(
                transcribe_path,
                language=language if language != "auto" else None,
                fp16=False,
                no_speech_threshold=0.6
            )
        )

        text = result["text"].strip().lower()

        # ---------- HALLUCINATION FILTER ----------
        bad_outputs = [
            "",
            "thank you",
            "thanks",
            "thank you for watching"
        ]

        if len(text) < 2 or text in bad_outputs:
            return {"success": True, "text": ""}

        print("\n=== TRANSCRIPTION ===\n", text, "\n=====================")

        return {
            "success": True,
            "text": text
        }

    except Exception as e:
        print("Transcription error:", e)
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        try:
            if temp_audio and os.path.exists(temp_audio.name):
                os.remove(temp_audio.name)

            if wav_path and os.path.exists(wav_path):
                os.remove(wav_path)
        except:
            pass
        
@app.get("/api/chats")
async def get_chats(userId: str):
    chats = await chats_collection.find(
        {"userId": userId}
    ).sort("updatedAt", -1).to_list(100)

    return chats


@app.get("/api/messages")
async def get_messages(chatId: str, userId: str):
    msgs = await messages_collection.find({
        "chatId": chatId,
        "userId": userId  
    }).to_list(100)

    return [
        {
            "id": str(m["_id"]),
            "role": m["role"],
            "content": m["content"],
            "entities": m.get("entities", []),
            "actions": m.get("actions", [])
        } for m in msgs
    ]



@app.post("/api/feedback")
async def submit_feedback(req: FeedbackRequest):
    print(" Feedback:", req.feedback)
    return {"status": "ok"}

@app.patch("/api/chats/{chat_id}")
async def rename_chat(chat_id: str, userId: str, data: dict):
    title = data.get("title")

    if not title:
        raise HTTPException(status_code=400, detail="Title required")

    result = await chats_collection.update_one(
        {
            "_id": chat_id,
            "userId": userId   # REQUIRED
        },
        {
            "$set": {"title": title}
        }
    )

    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Chat not found")

    return {"success": True}


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: str, userId: str):

    await asyncio.gather(
        chats_collection.delete_one({
            "_id": chat_id,
            "userId": userId  
        }),
        messages_collection.delete_many({
            "chatId": chat_id,
            "userId": userId
        })
    )

    return {"success": True}

@app.patch("/api/chats/{chat_id}/pin")
async def pin_chat(chat_id: str, userId: str):
    await chats_collection.update_one(
        {"_id": chat_id, "userId": userId},
        {"$set": {"pinned": True}}
    )
    return {"success": True}

@app.patch("/api/chats/{chat_id}/unpin")
async def unpin_chat(chat_id: str, userId: str):
    await chats_collection.update_one(
        {"_id": chat_id, "userId": userId},
        {"$set": {"pinned": False}}
    )
    return {"success": True}
# ── Pipeline API Endpoints ────────────────────────────────────────────

@app.post("/api/pipeline/trigger")
async def trigger_pipeline(schedule: str = "all"):
    """
    Manually trigger a scrape cycle.
    Query param 'schedule': 'frequent', 'normal', or 'all' (default).
    Runs in the background so the response returns immediately.
    """
    from pipeline.runner import run_frequent, run_normal, run_all

    async def _run():
        if schedule == "frequent":
            await run_frequent()
        elif schedule == "normal":
            await run_normal()
        else:
            await run_all()

    asyncio.create_task(_run())
    return {"status": "triggered", "schedule": schedule}


@app.get("/api/pipeline/status")
async def pipeline_status():
    """Get the last pipeline run stats and scheduler status."""
    from pipeline.runner import get_last_stats
    from pipeline.scheduler import get_scheduler_status

    return {
        "scheduler": get_scheduler_status(),
        "last_runs": get_last_stats(),
    }


@app.get("/api/pipeline/history")
async def pipeline_history(url: str | None = None):
    """Get scrape history. Optionally filter by URL."""
    from pipeline.change_detector import ChangeDetector
    detector = ChangeDetector()
    return {"history": detector.get_history(url)}


@app.on_event("shutdown")
def shutdown():
    """Gracefully stop the background schedulers."""
    try:
        from pipeline.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass
    try:
        from reminder_scheduler import stop_reminder_scheduler
        stop_reminder_scheduler()
    except Exception:
        pass


# ── Reminder API Endpoints ────────────────────────────────────────────
from reminder_service import (
    ReminderNotAllowedError,
    create_reminder,
    get_upcoming_reminders,
    get_reminder_history,
    cancel_reminder,
    get_notifications,
    get_unread_notification_count,
    mark_notification_read,
    snooze_reminder,
    get_user_preference,
    save_user_preference,
    connect_google_oauth,
    disconnect_google_oauth
)

class ReminderCreateRequest(BaseModel):
    userId: str
    eventName: str
    eventDate: str
    sourceType: str
    # Optional[...] is required under Pydantic v2: a `str` field with a None
    # default still rejects an explicit null, which is what the frontend sends.
    sourceId: str | None = None
    notificationType: str = "in_app"
    reminderOffset: str = "1d"
    chatId: str = ""

class SnoozeRequest(BaseModel):
    userId: str
    snoozeMinutes: int = 60

class PreferenceSaveRequest(BaseModel):
    userId: str
    notificationType: str
    email: str | None = None

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
            chat_id=req.chatId
        )
        is_duplicate = reminder.get("is_duplicate", False) if isinstance(reminder, dict) else False
        return {"success": True, "reminder": reminder, "is_duplicate": is_duplicate}
    except ReminderNotAllowedError as e:
        # 422: understood but refused by policy — the subject is not official
        # college information. The frontend renders `detail` verbatim.
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reminders/upcoming")
async def api_get_upcoming_reminders(userId: str):
    try:
        reminders = await get_upcoming_reminders(userId)
        return {"success": True, "reminders": reminders}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reminders/history")
async def api_get_reminder_history(userId: str):
    """Reminders that have expired, completed, failed or been cancelled."""
    try:
        reminders = await get_reminder_history(userId)
        return {"success": True, "reminders": reminders}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/reminders/scheduler-status")
async def api_reminder_scheduler_status():
    """Health check for the reminder scheduler — is the delivery loop alive?"""
    from reminder_scheduler import get_reminder_scheduler_status
    return {"success": True, **get_reminder_scheduler_status()}

@app.delete("/api/reminders/{id}")
async def api_cancel_reminder(id: str, userId: str):
    try:
        success = await cancel_reminder(id, userId)
        return {"success": success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/notifications")
async def api_get_notifications(userId: str):
    try:
        notifications = await get_notifications(userId)
        return {"success": True, "notifications": notifications}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/notifications/stream")
async def api_notifications_stream(userId: str):
    """
    Server-Sent Events stream pushing reminder notifications the instant they are
    created, so the panel updates without a refresh.

    The client keeps polling /api/notifications as a fallback, so a proxy that
    buffers or drops this stream costs latency only, never a lost notification.
    """
    from fastapi.responses import StreamingResponse
    from notification_hub import subscribe

    heartbeat_seconds = 25  # below the common 30s idle-proxy timeout

    async def event_source():
        async with subscribe(userId) as queue:
            unread = await get_unread_notification_count(userId)
            yield f"event: ready\ndata: {json.dumps({'unread': unread})}\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=heartbeat_seconds)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                except asyncio.CancelledError:
                    break
                yield f"event: notification\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx response buffering
        },
    )

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

@app.get("/api/user/preferences")
async def api_get_user_preferences(userId: str):
    try:
        pref = await get_user_preference(userId)
        if "_id" in pref:
            pref["_id"] = str(pref["_id"])
        if "created_at" in pref and isinstance(pref["created_at"], datetime):
            pref["created_at"] = pref["created_at"].isoformat()
        if "updated_at" in pref and isinstance(pref["updated_at"], datetime):
            pref["updated_at"] = pref["updated_at"].isoformat()
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

@app.get("/api/google/auth-url")
async def api_google_auth_url(userId: str):
    try:
        # Imported lazily so the optional Google Calendar dependencies never
        # block the app (and the reminder pipeline) from starting.
        from google_calendar import get_auth_url
        url = get_auth_url(userId)
        return {"success": bool(url), "url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/google/callback")
async def api_google_callback(code: str, state: str):
    try:
        user_id = state
        result = await connect_google_oauth(user_id, code)
        
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content="""
        <html>
            <head>
                <title>Google Calendar Connected</title>
                <script>
                    window.opener.postMessage({ type: 'GOOGLE_CALENDAR_CONNECTED', success: true }, '*');
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
        google_oauth = pref.get("google_oauth", {})
        connected = google_oauth.get("connected", False)
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
        if pref and "_id" in pref:
            pref["_id"] = str(pref["_id"])
        google_oauth = pref.get("google_oauth", {})
        if not google_oauth or not google_oauth.get("connected"):
            return {
                "success": False,
                "error": "Google Calendar not connected for this user",
                "preferences": pref
            }
        
        from datetime import datetime, timedelta
        from google_calendar import create_calendar_event
        now = datetime.utcnow()
        event_date = now + timedelta(hours=1)

        event_id, refreshed_tokens = create_calendar_event(
            user_id=userId,
            google_oauth=google_oauth,
            event_name="VBOT Integration Test Event",
            event_date_dt=event_date,
            timezone="Asia/Kolkata",
            reminder_offset_minutes=30
        )
        
        if refreshed_tokens:
            await db["user_preferences"].update_one(
                {"user_id": userId},
                {"$set": {"google_oauth": refreshed_tokens}}
            )
            
        if event_id:
            return {
                "success": True,
                "event_id": event_id,
                "message": "Test event successfully created in Google Calendar!",
                "refreshed_tokens_updated": bool(refreshed_tokens)
            }
        else:
            return {
                "success": False,
                "error": "Google Calendar event creation returned None. Check server logs."
            }
    except Exception as e:
        import traceback
        logger.error(f"Test event exception: {traceback.format_exc()}")
        return {"success": False, "error": str(e), "traceback": traceback.format_exc()}


@app.get("/")
async def root():
    return {"message": "Backend running"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
