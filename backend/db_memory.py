from langchain.memory import ConversationSummaryBufferMemory
# from langchain.schema import HumanMessage, AIMessage
from database import chats_collection, messages_collection
from langchain_ollama import ChatOllama

llm = ChatOllama(model="llama3", temperature=0.2)


from langchain.memory import ConversationSummaryBufferMemory
from database import chats_collection, messages_collection
from langchain_ollama import ChatOllama

llm = ChatOllama(model="llama3:8b", temperature=0.2)


async def load_memory(chat_id: str, user_id: str):
    
    # 🔹 1. Load summary from DB
    chat = await chats_collection.find_one({
        "_id": chat_id,
        "userId": user_id   # ✅ IMPORTANT
    })

    summary = chat.get("memorySummary", "") if chat else ""

    # 🔹 2. Create memory
    memory = ConversationSummaryBufferMemory(
        llm=llm,
        memory_key="chat_history",
        return_messages=True,
        max_token_limit=512,
    )

    # 🔹 3. Inject summary AFTER creation
    memory.moving_summary_buffer = summary

    # 🔹 4. Load ONLY recent messages (last 10–15)
    cursor = messages_collection.find(
        {"chatId": chat_id, "userId": user_id}
    ).sort("_id", -1).limit(12)

    messages = await cursor.to_list(length=12)

    # 🔹 5. Add messages in correct order
    for msg in reversed(messages):
        if msg["role"] == "user":
            memory.chat_memory.add_user_message(msg["content"])
        else:
            memory.chat_memory.add_ai_message(msg["content"])

    return memory

async def save_memory_summary(chat_id: str, user_id: str, memory):
    await chats_collection.update_one(
        {"_id": chat_id, "userId": user_id},  # ✅ important
        {
            "$set": {
                "memorySummary": memory.moving_summary_buffer
            }
        },
    )