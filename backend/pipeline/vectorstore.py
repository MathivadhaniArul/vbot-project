"""
VectorStore Manager — ChromaDB Incremental Upsert/Delete
==========================================================
Manages ChromaDB operations for the pipeline:

    - Delete old chunks for a URL before adding new ones
    - Add new chunks with deterministic IDs (idempotent)
    - Delete all chunks for a removed URL
    - Query collection stats

Uses the same ChromaDB collection as main.py ("vit-regulations").
Embeddings model matches the existing HuggingFace setup.
"""

import logging
from langchain.schema import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

from pipeline.config import CHROMA_DIR, COLLECTION_NAME

logger = logging.getLogger("pipeline.vectorstore")

# Singleton embeddings instance (heavy to load — share across calls)
_embeddings = None


def _get_embeddings() -> HuggingFaceEmbeddings:
    """Get or create the embeddings model (singleton)."""
    global _embeddings
    if _embeddings is None:
        logger.info("[VECTORSTORE] Loading embeddings model...")
        _embeddings = HuggingFaceEmbeddings(
            model_name="nomic-ai/nomic-embed-text-v1.5",
            model_kwargs={"trust_remote_code": True},
        )
        logger.info("[VECTORSTORE] Embeddings model loaded")
    return _embeddings


def _get_collection() -> Chroma:
    """Get the ChromaDB collection handle."""
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=_get_embeddings(),
        persist_directory=CHROMA_DIR,
    )


class VectorStoreManager:
    """
    Manages incremental updates to the ChromaDB vector store.

    The update strategy for a changed page is:
        1. Delete all old chunks associated with the URL
        2. Add new chunks with fresh embeddings

    This is a clean "replace" strategy because:
        - ChromaDB doesn't support in-place embedding updates
        - Content changes → different chunks → different embeddings
        - Only chunks from the changed page are affected
    """

    def __init__(self):
        self._collection = _get_collection()

    def upsert_documents(
        self,
        documents: list[Document],
        old_chunk_ids: list[str] | None = None,
    ) -> list[str]:
        """
        Replace old chunks with new ones for a page.

        Args:
            documents: New LangChain Document objects to add.
            old_chunk_ids: IDs of previous chunks to delete first.

        Returns:
            List of new chunk IDs that were added.
        """
        # Step 1: Delete old chunks if any
        if old_chunk_ids:
            self.delete_by_ids(old_chunk_ids)

        if not documents:
            return []

        # Step 2: Add new chunks
        new_ids = [doc.metadata.get("chunk_id", "") for doc in documents]
        new_ids = [cid for cid in new_ids if cid]  # filter empty

        if not new_ids or len(new_ids) != len(documents):
            # Fallback: generate IDs if metadata is missing
            import uuid
            new_ids = [str(uuid.uuid4()) for _ in documents]

        # Add in batches to avoid memory issues
        batch_size = 50
        for i in range(0, len(documents), batch_size):
            batch_docs = documents[i : i + batch_size]
            batch_ids = new_ids[i : i + batch_size]
            self._collection.add_documents(batch_docs, ids=batch_ids)

        logger.info(
            f"[VECTORSTORE] Added {len(documents)} chunks "
            f"(deleted {len(old_chunk_ids) if old_chunk_ids else 0} old)"
        )
        return new_ids

    def delete_by_ids(self, chunk_ids: list[str]):
        """
        Delete specific chunks by their IDs.

        Args:
            chunk_ids: List of ChromaDB document IDs to remove.
        """
        if not chunk_ids:
            return

        # ChromaDB delete in batches (max ~5000 per call)
        batch_size = 500
        for i in range(0, len(chunk_ids), batch_size):
            batch = chunk_ids[i : i + batch_size]
            try:
                self._collection._collection.delete(ids=batch)
            except Exception as e:
                logger.warning(f"[VECTORSTORE] Delete batch error: {e}")

        logger.info(f"[VECTORSTORE] Deleted {len(chunk_ids)} chunks")

    def delete_by_url(self, url: str):
        """
        Delete all chunks associated with a URL using metadata filter.

        Use this when a page is completely removed from the scrape targets.

        Args:
            url: The source URL whose chunks should be removed.
        """
        try:
            results = self._collection._collection.get(
                where={"url": url},
                include=[],
            )
            if results and results.get("ids"):
                ids_to_delete = results["ids"]
                self.delete_by_ids(ids_to_delete)
                logger.info(f"[VECTORSTORE] Deleted {len(ids_to_delete)} chunks for URL: {url}")
            else:
                logger.debug(f"[VECTORSTORE] No chunks found for URL: {url}")
        except Exception as e:
            logger.warning(f"[VECTORSTORE] Error deleting by URL {url}: {e}")

    def get_stats(self) -> dict:
        """
        Get collection statistics.

        Returns:
            Dict with total document count and sample metadata.
        """
        try:
            count = self._collection._collection.count()
            return {
                "total_documents": count,
                "collection_name": COLLECTION_NAME,
                "persist_directory": CHROMA_DIR,
            }
        except Exception as e:
            logger.error(f"[VECTORSTORE] Error getting stats: {e}")
            return {"total_documents": -1, "error": str(e)}
