import logging
from langchain_classic.memory import ConversationSummaryBufferMemory
from langchain_ollama import ChatOllama
from database import chats_collection, messages_collection

logger = logging.getLogger(__name__)

llm = ChatOllama(
    model="qwen3:8b-q4_K_M",
    base_url="http://localhost:11435",
    temperature=0,
    extra_body={"think": False},
)


async def load_memory(chat_id: str, user_id: str) -> ConversationSummaryBufferMemory:
    """
    Load memory for a chat session.
    - Retrieves existing summary from chats_collection
    - Loads recent raw messages from messages_collection
    - If a summary exists, loads fewer raw messages to avoid double-counting
    """
    try:
        chat = await chats_collection.find_one({
            "_id": chat_id,
            "userId": user_id
        })
    except Exception as e:
        logger.error(f"Failed to load chat document [{chat_id}]: {e}")
        chat = None

    summary = chat.get("memorySummary", "") if chat else ""

    memory = ConversationSummaryBufferMemory(
        llm=llm,
        memory_key="chat_history",
        return_messages=True,
        max_token_limit=1024,  # raised from 512 — keeps recent turns as raw text longer
                               # before summarizing, preserving event names and dates
                               # that reminder extraction depends on
    )

    # Inject existing summary before loading raw messages
    # ConversationSummaryBufferMemory prepends this to context automatically
    memory.moving_summary_buffer = summary

    # If a summary already exists, we only need the most recent messages
    # that aren't captured in it yet. Loading 12 when a summary exists
    # causes double-counting — old turns appear both in the summary and
    # as raw messages.
    limit = 6 if summary else 12

    try:
        cursor = messages_collection.find(
            {"chatId": chat_id, "userId": user_id}
        ).sort("_id", -1).limit(limit)

        messages = await cursor.to_list(length=limit)
    except Exception as e:
        logger.error(f"Failed to load messages [{chat_id}]: {e}")
        messages = []

    # Messages are fetched newest-first, reverse to get chronological order
    for msg in reversed(messages):
        role = msg.get("role")
        content = msg.get("content", "")
        if not content:
            continue
        if role == "user":
            memory.chat_memory.add_user_message(content)
        elif role == "assistant":
            memory.chat_memory.add_ai_message(content)

    logger.info(
        f"Memory loaded [{chat_id}] — "
        f"summary={'yes' if summary else 'no'}, "
        f"raw_messages={len(messages)}"
    )

    return memory


async def save_memory_summary(chat_id: str, user_id: str, memory: ConversationSummaryBufferMemory) -> None:
    """
    Persist only the moving summary buffer back to the chat document.
    Raw messages are already persisted individually in messages_collection
    by main.py, so we only need to save the summarized portion here.
    """
    summary = memory.moving_summary_buffer or ""

    try:
        result = await chats_collection.update_one(
            {"_id": chat_id, "userId": user_id},
            {"$set": {"memorySummary": summary}}
        )
        if result.matched_count == 0:
            logger.warning(
                f"save_memory_summary: no chat document found for "
                f"chat_id={chat_id}, user_id={user_id}"
            )
        else:
            logger.info(
                f"Memory summary saved [{chat_id}] — "
                f"{len(summary)} chars"
            )
    except Exception as e:
        logger.error(f"Failed to save memory summary [{chat_id}]: {e}")