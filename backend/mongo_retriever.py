import logging
import os
from typing import List

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import OperationFailure
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# point this at your second MongoDB
_client = AsyncIOMotorClient(
    os.getenv("MONGO2_URI", "mongodb://localhost:27017")
)
_db = _client[os.getenv("MONGO2_DB", "chatbot_db")]
_coll = _db[os.getenv("MONGO2_COLL", "contacts")]

# FIX: nothing in this file (or elsewhere) previously created a text index
# on `contacts`, so `$text: {"$search": ...}` would throw OperationFailure
# the first time this ran against a fresh collection. Doing it lazily on
# first call (guarded so we only try once) rather than assuming it exists.
_text_index_checked = False

# FIX: no cap on assembled content — a contact doc with a large free-text
# field would get dumped whole into the LLM context with no truncation.
_MAX_FIELD_CHARS = 500
_MAX_CONTENT_CHARS = 2000


async def _ensure_text_index():
    global _text_index_checked
    if _text_index_checked:
        return
    try:
        indexes = await _coll.index_information()
        has_text_index = any(
            any(t == "text" for _, t in spec.get("key", []))
            for spec in indexes.values()
        )
        if not has_text_index:
            logger.warning(
                f"[mongo_retriever] no text index found on '{_coll.name}' — "
                f"creating a wildcard text index now. For large collections, "
                f"create this manually/offline instead."
            )
            await _coll.create_index([("$**", "text")], name="idx_contacts_text")
    except Exception as e:
        logger.error(f"[mongo_retriever] failed to verify/create text index: {e}")
    finally:
        _text_index_checked = True


async def fetch_mongo_docs(query: str, k: int = 5) -> List[Document]:
    """
    Replace the filter below with your real query logic.
    Examples:
      - text search:  {"$text": {"$search": query}}
      - regex match:  {"name": {"$regex": query, "$options": "i"}}
      - Atlas vector: use $vectorSearch aggregation

    NOTE: as of this fix, this function is still not wired into router.py's
    VALID_SOURCES / server.py's chat() branches — it's a standalone utility
    ready to be plugged in as a retrieval source (e.g. for faculty/contact
    lookups), not currently reachable from the live chat pipeline.
    """
    await _ensure_text_index()

    try:
        cursor = _coll.find(
            {"$text": {"$search": query}},
            {"score": {"$meta": "textScore"}}
        ).sort(
            [("score", {"$meta": "textScore"})]
        ).limit(k)

        docs = []
        async for doc in cursor:
            parts = []
            for key, value in doc.items():
                if key == "_id" or key.startswith("_"):
                    continue
                value_str = str(value)
                if len(value_str) > _MAX_FIELD_CHARS:
                    value_str = value_str[:_MAX_FIELD_CHARS] + "…"
                parts.append(f"{key}: {value_str}")

            content = " | ".join(parts)
            if len(content) > _MAX_CONTENT_CHARS:
                content = content[:_MAX_CONTENT_CHARS] + "…"

            docs.append(Document(
                page_content=content,
                metadata={"source": "mongodb", "id": str(doc["_id"])}
            ))
        return docs

    except OperationFailure as e:
        # FIX: previously an unhandled OperationFailure (e.g. text index
        # genuinely still missing/broken) would propagate straight up
        # through whatever RAG chain called this, taking the request down.
        # Degrade gracefully like the reranker does elsewhere in this
        # codebase: log loudly, return no docs, let the caller carry on.
        logger.error(f"[mongo_retriever] Mongo text search failed: {e}")
        return []
    except Exception as e:
        logger.error(f"[mongo_retriever] unexpected error during fetch: {e}")
        return []