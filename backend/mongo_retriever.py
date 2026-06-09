from motor.motor_asyncio import AsyncIOMotorClient
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from typing import List
import os

# point this at your second MongoDB
_client = AsyncIOMotorClient(
    os.getenv("MONGO2_URI", "mongodb://localhost:27017")
)
_db   = _client[os.getenv("MONGO2_DB",  "chatbot_db")]
_coll = _db[os.getenv("MONGO2_COLL", "contacts")]

async def fetch_mongo_docs(query: str, k: int = 5) -> List[Document]:
    """
    Replace the filter below with your real query logic.
    Examples:
      - text search:  {"$text": {"$search": query}}
      - regex match:  {"name": {"$regex": query, "$options": "i"}}
      - Atlas vector: use $vectorSearch aggregation
    """
    cursor = _coll.find(
        {"$text": {"$search": query}},
        {"score": {"$meta": "textScore"}}
    ).sort(
        [("score", {"$meta": "textScore"})]
    ).limit(k)

    docs = []
    async for doc in cursor:
        content = " | ".join(
            f"{k}: {v}"
            for k, v in doc.items()
            if k != "_id" and not k.startswith("_")
        )
        docs.append(Document(
            page_content=content,
            metadata={"source": "mongodb", "id": str(doc["_id"])}
        ))
    return docs
