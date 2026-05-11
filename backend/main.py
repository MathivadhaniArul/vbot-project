import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
#import fitz 
from dotenv import load_dotenv
from pathlib import Path
import hashlib
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import FlashrankRerank
# LangChain

from langchain.schema import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_ollama import ChatOllama
from langchain_community.vectorstores import Chroma
from langchain.memory import ConversationSummaryMemory
from langchain.schema import Document
from db_memory import load_memory, save_memory_summary
from langchain.chains import create_history_aware_retriever
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain


load_dotenv()

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
)

retrieval_chain = None
rag_chain = None
memory = None
chat_memories = {}

llm = ChatOllama(model="llama3:8b", temperature=0.2)

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




def get_memory(chat_id: str):
    if chat_id not in chat_memories:
        chat_memories[chat_id] = ConversationSummaryMemory(
            llm=llm,
            memory_key="chat_history",
            return_messages=True,
            max_token_limit=512,
        )
    return chat_memories[chat_id]

def hash_text(text: str):
    return hashlib.md5(text.encode()).hexdigest()

import re



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
     
    import json
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
        with open(r"C:/Users/mathi/OneDrive/Desktop/shadcn-bot/ai-chatbot/backend/vit_chunks.json",  encoding="utf-8") as f:
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
        print("Chunking complete!")
            
            
        
        
        
        if docs:   
            ids = [str(uuid.uuid4()) for _ in docs]
            docsearch.add_documents(docs, ids=ids)
            print("Indexing complete.")
    else:
            print("Collection already populated. Skipping embedding.")
   
    print(" Chroma loaded:", docsearch._collection.count())
    
    
    template = """
You are an helpful assistant for VIT regulations.

Answer ONLY using the provided context.

-----------------------------
STRICT RULES
-----------------------------

1. NO GUESSING
- Do NOT infer, assume, or add information.
- If the answer is not explicitly in the context, say:
  "This information is not mentioned in the regulations."

2. EXACTNESS
- Do NOT change numbers, inequalities, or conditions.
- Use them exactly as written in the context.

3. CONTEXT RELEVANCE
- Answer ONLY if the context is clearly relevant to the question.
- If the context is unrelated, say:
  "The retrieved context is not relevant to the question."

4. ACRONYMS
- If defined in the context → use that meaning.
- If NOT defined → say:
  "The acronym is not defined in the provided regulations."

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
"This information is not mentioned in the regulations."

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
import asyncio

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

# @app.post("/api/ingest")
# async def ingest():

#     docsearch = Chroma(
#         collection_name="vit-regulations",
#         embedding_function=embeddings,
#         persist_directory="./chroma"
#     )

#     ingest_documents(docsearch)

#     return {"status": "ingestion complete"}

#From Swagger: http://localhost:8000/docs

@app.get("/")
async def root():
    return {"message": "Backend running"}