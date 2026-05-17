import uuid
import os
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

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.background import BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

# LangChain
from langchain.schema import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import ChatOllama
from langchain_community.vectorstores import Chroma
from langchain.memory import ConversationSummaryMemory
from db_memory import load_memory, save_memory_summary
from langchain.chains import create_history_aware_retriever
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import FlashrankRerank

import whisper
import edge_tts

load_dotenv()

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

# Add ffmpeg to PATH
os.environ["PATH"] += os.pathsep + str(Path(__file__).resolve().parent / "ffmpeg_bin")

app = FastAPI()


client = AsyncIOMotorClient("mongodb://localhost:27017")
db = client["chatbot_db"]
messages_collection = db["messages"]
chats_collection = db["chats"]



app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-User-Text", "X-Assistant-Text"],
)

retrieval_chain = None
rag_chain = None
memory = None
chat_memories = {}

llm = ChatOllama(model="llama3:8b", temperature=0.2)

whisper_model = whisper.load_model("base")
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

            else:
                combined = " ".join(contents)
            
                chunks.append({
                        "type": "section",
                        "source": url,
                        "heading": heading,
                        "content": combined
                    })

    return chunks




def hash_text(text: str):
    return hashlib.md5(text.encode()).hexdigest()



def clean_text(text):
    
    text = re.sub(r'\*\*', '', text)
    
    text = re.sub(r'^\s*#(?!#)\s*', '', text, flags=re.MULTILINE)

    return text.strip()


def split_markdown_with_subsections(md_text):
    sections = []
    current_header = None
    current_content = []

    md_text = clean_text(md_text)

  
    for line in md_text.splitlines():
        if re.match(r"^\s*##\s+", line):
            if current_header:
                sections.append((current_header, "\n".join(current_content)))

            current_header = re.sub(r"^\s*##\s+", "", line).strip()
            current_content = []
        else:
            current_content.append(line)

    if current_header:
        sections.append((current_header, "\n".join(current_content)))

    
    final_chunks = []

    for heading, content in sections:
        parts = re.split(r"\n(?=\d+\s*\.\s*\d+\s*)", content)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            lines = part.split("\n", 1)
            subheading = lines[0].strip()
            subcontent = lines[1].strip() if len(lines) > 1 else ""

            final_chunks.append({
                "type": "section",
                "heading": heading,
                "subheading": subheading,
                "content": subcontent
            })
              
    return final_chunks

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
    global retrieval_chain, memory,rag_chain

    print("Building RAG pipeline...")

    BASE_DIR = Path(__file__).resolve().parent
    REG_DIR = BASE_DIR / "reg_md"

    docsearch = Chroma(
    collection_name="vit-regulations",
    embedding_function=embeddings,
    persist_directory="./chroma"
    )
     
    data=[]
    
    
    if docsearch._collection.count() == 0:
        print("Indexing documents...")
        docs = []
        for path in REG_DIR.rglob("*.md"):
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
                

            chunks = split_markdown_with_subsections(text)
            
            for chunk in chunks:
                content = f"""
                Heading: {chunk['heading']}
                Subsection: {chunk['subheading']}
                
                Content: {chunk['content']}
                """
                docs.append(
        Document(
            page_content=content.strip(),
            metadata={
                "id": hash_text(content),
                "heading": chunk["heading"],
                "subheading": chunk["subheading"],
                "type": chunk["type"],
                "source": str(path.relative_to(BASE_DIR))
            }
        )
    )
        with open("scrape/vit_final_with_links.json", encoding="utf-8") as f:
            data = json.load(f)
        chunks = structure_chunk(data)
        with open("vit_chunks.json", "w", encoding="cp1252") as f:
            json.dump(chunks, f, indent=2, ensure_ascii=False)
        
        for chunk in chunks:
            content = f"""
            Heading: {chunk['heading']}
            Content: {chunk['content']}
            """
            docs.append(
        Document(
            page_content=content.strip(),
            metadata={
                "id": hash_text(content),
                "source": chunk.get("source"),
                "heading": chunk.get("heading"),
                "type": chunk.get("type")
            }
        )
    )
        # Also index Riviera data
        riviera_path = BASE_DIR / "riviera_chunks.json"
        if riviera_path.exists():
            print("Indexing Riviera data...")
            with open(riviera_path, encoding="utf-8") as f:
                riviera_data = json.load(f)
            riviera_chunks = structure_chunk(riviera_data)
            for chunk in riviera_chunks:
                content = f"""
                Heading: {chunk['heading']}
                Content: {chunk['content']}
                """
                docs.append(
                    Document(
                        page_content=content.strip(),
                        metadata={
                            "id": hash_text(content),
                            "source": chunk.get("source") or "riviera_website",
                            "heading": chunk.get("heading"),
                            "type": chunk.get("type", "section")
                        }
                    )
                )
            print(f"Riviera chunks added: {len(riviera_chunks)}")
        else:
            print("Warning: riviera_chunks.json not found, skipping.")
        print("Chunking complete!")
            
            
        
        
        
        if docs:   
            ids = [str(uuid.uuid4()) for _ in docs]
            docsearch.add_documents(docs, ids=ids)
            print("Indexing complete.")
    else:
            print("Collection already populated. Skipping embedding.")
   
    print(" Chroma loaded:", docsearch._collection.count())
    
    
    template = """
You are an expert assistant for VIT Vellore, specializing in Academic Regulations and the Riviera 2026 Cultural Fest.

Answer ONLY using the provided context.

-----------------------------
STRICT RULES
-----------------------------

1. NO GUESSING
- Do NOT infer, assume, or add information.
- If the answer is not explicitly in the context, say:
  "This information is not mentioned in the provided documents."

2. EXACTNESS
- Do NOT change numbers, dates, inequalities, or conditions.
- Use them exactly as written in the context.

3. CONTEXT RELEVANCE
- Answer ONLY if the context is clearly relevant to the question.
- If the context is unrelated, say:
  "The retrieved context is not relevant to the question."

4. ACRONYMS
- If defined in the context → use that meaning.
- If NOT defined → say:
  "The acronym is not defined in the provided documents."

5. FOLLOW-UP QUESTIONS
- For words like "it", "this", "that":
  → refer ONLY to the most recent topic.
- If the context does not contain information about that topic → do NOT answer.
"""
    
    
    qa_prompt = ChatPromptTemplate.from_messages([
    ("system",template),
    MessagesPlaceholder("chat_history"),
    ("human", """
You must answer ONLY using the context below.

If the answer is not present, say:
"This information is not mentioned in the provided documents."

Context:
{context}

Question:
{input}
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
     "Given the chat history and the latest user question, "
     "rewrite the question to be standalone. "
     "Do NOT answer the question ,If the question is already standalone, return it unchanged."),
    MessagesPlaceholder("chat_history"),
    ("human", "{input}")])
    
    
    
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
    
    results = retriever.get_relevant_documents("want industrial visit form")

    for r in results:
        print("----")
        print(r.page_content)
        
    print(" RAG Ready!")

    # ── Start Auto-Update Pipeline Scheduler ─────────────────────────
    try:
        from pipeline.scheduler import start_scheduler
        start_scheduler()
        print(" Pipeline scheduler started!")
    except Exception as e:
        print(f"⚠️ Pipeline scheduler failed to start: {e}")
        print("  (The chatbot will still work, just without auto-updates)")


class ChatRequest(BaseModel):
    chatId: str
    userId: str
    text: str

class FeedbackRequest(BaseModel):
    feedback: str


@app.post("/api/chat")
async def chat(req: ChatRequest):

    await ensure_chat(req.chatId, req.userId, req.text)

   
    await messages_collection.insert_one({
        "chatId": req.chatId,
        "userId": req.userId,   
        "role": "user",
        "content": req.text
    })

    answer = "Unknown error"

    try:
        memory = await load_memory(req.chatId, req.userId)
        result = await rag_chain.ainvoke({
        "input": req.text,
        "chat_history": memory.chat_memory.messages
    })


        answer = result.get("answer", "No answer returned")

        #  update memory
        memory.chat_memory.add_user_message(req.text)
        memory.chat_memory.add_ai_message(answer)

        await save_memory_summary(req.chatId, req.userId, memory)

    except Exception as e:
        print("Chat error:", e)
        answer = f"Error: {str(e)}"

    # store assistant reply
    await messages_collection.insert_one({
    "chatId": req.chatId,
    "userId": req.userId,  
    "role": "assistant",
    "content": answer,
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
    return {"answer": answer}

@app.post("/api/voice")
async def voice_chat(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    chatId: str = Form(...),
    userId: str = Form(...)
):
    await ensure_chat(chatId, userId, "Voice Message")

    # Save uploaded audio to a temp file with proper extension
    # Browsers record as webm by default, Whisper/ffmpeg handles both
    suffix = ".webm"
    content_type = file.content_type or ""
    if "wav" in content_type:
        suffix = ".wav"
    elif "mp4" in content_type or "m4a" in content_type:
        suffix = ".m4a"
    elif "ogg" in content_type:
        suffix = ".ogg"

    temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=".")
    tts_audio_path = None
    try:
        contents = await file.read()
        temp_audio.write(contents)
        temp_audio.close()
        temp_audio_path = temp_audio.name
        print(f"Saved audio: {temp_audio_path} ({len(contents)} bytes)")

        # Convert to WAV first to ensure compatibility with Whisper
        wav_path = temp_audio_path.replace(suffix, ".wav")
        print(f"Converting {temp_audio_path} to {wav_path}...")
        
        conversion = subprocess.run([
            "ffmpeg",
            "-y",
            "-i",
            temp_audio_path,
            wav_path
        ], capture_output=True, text=True)
        
        if conversion.returncode != 0:
            print("FFmpeg conversion error:", conversion.stderr)
            # Fallback to original if conversion fails
            transcribe_path = temp_audio_path
        else:
            transcribe_path = wav_path

        # Run Whisper transcription in a separate thread to avoid blocking the event loop
        # Use language="en" to prevent auto-detection errors and fp16=False for CPU
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            _whisper_executor,
            lambda: whisper_model.transcribe(transcribe_path, language="en", fp16=False)
        )
        user_text = result["text"].strip()

        print(f"\n=== VOICE TRANSCRIPTION ===\nWhisper heard: '{user_text}'\n===========================")

        if not user_text:
            user_text = "(empty voice input)"

        # Add user message to DB
        await messages_collection.insert_one({
            "chatId": chatId,
            "userId": userId,
            "role": "user",
            "content": user_text
        })

        # Process via RAG
        memory = await load_memory(chatId, userId)
        rag_result = await rag_chain.ainvoke({
            "input": user_text,
            "chat_history": memory.chat_memory.messages
        })
        answer = rag_result.get("answer", "I couldn't process that.")

        print(f"\n=== VOICE RAG ANSWER ===\n{answer}\n========================")

        # Update memory
        memory.chat_memory.add_user_message(user_text)
        memory.chat_memory.add_ai_message(answer)
        await save_memory_summary(chatId, userId, memory)

        # Add assistant message to DB
        await messages_collection.insert_one({
            "chatId": chatId,
            "userId": userId,
            "role": "assistant",
            "content": answer,
            "createdAt": datetime.utcnow()
        })

        # Update timestamp
        await chats_collection.update_one(
            {"_id": chatId, "userId": userId},
            {"$set": {"updatedAt": datetime.utcnow()}}
        )

        # Convert text to speech
        tts_audio_path = tempfile.NamedTemporaryFile(
            delete=False, suffix=".mp3", dir="."
        ).name
        tts = edge_tts.Communicate(text=answer, voice="en-US-GuyNeural")
        await tts.save(tts_audio_path)

        # Encode text for headers
        headers = {
            "X-User-Text": urllib.parse.quote(user_text),
            "X-Assistant-Text": urllib.parse.quote(answer)
        }

        # Schedule cleanup AFTER the response is sent
        background_tasks.add_task(os.remove, tts_audio_path)

        return FileResponse(
            tts_audio_path,
            media_type="audio/mpeg",
            headers=headers
        )

    except Exception as e:
        print("Voice chat error:", e)
        # Clean up TTS file on error
        if tts_audio_path and os.path.exists(tts_audio_path):
            os.remove(tts_audio_path)
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Always clean up the input audio temp file
        if os.path.exists(temp_audio.name):
            # os.remove(temp_audio.name)
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
            "content": m["content"]
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
    """Gracefully stop the pipeline scheduler."""
    try:
        from pipeline.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass


@app.get("/")
async def root():
    return {"message": "Backend running"}