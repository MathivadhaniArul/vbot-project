"""
Incremental Chunker — Document Splitting with Rich Metadata
=============================================================
Splits page content into chunks suitable for embedding.

Key features:
    - Deterministic chunk IDs (enables idempotent upserts)
    - Rich metadata per chunk (source, URL, category, timestamp, hash)
    - Adaptive chunk sizes (smaller for events, larger for regulations)
    - Uses RecursiveCharacterTextSplitter from LangChain (already installed)
"""

import hashlib
import logging
from datetime import datetime, timezone

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter

from pipeline.config import (
    CHUNK_SIZE_EVENT,
    CHUNK_OVERLAP_EVENT,
    CHUNK_SIZE_ACADEMIC,
    CHUNK_OVERLAP_ACADEMIC,
)

logger = logging.getLogger("pipeline.chunker")

# Categories that use smaller (event-sized) chunks
EVENT_CATEGORIES = {
    "events", "announcements", "faq", "merch", "team",
    "adventure_sports", "art_drama", "cyber_engage", "dance",
    "informal", "music", "pre_riviera", "premium",
    "quiz_words_worth", "sports", "workshop", "general",
}


def _get_chunk_params(category: str) -> tuple[int, int]:
    """
    Select chunk size/overlap based on content category.

    Event-style pages (short, discrete items):  500 / 75
    Academic pages (long, contextual docs):    1000 / 150
    """
    if category in EVENT_CATEGORIES:
        return CHUNK_SIZE_EVENT, CHUNK_OVERLAP_EVENT
    return CHUNK_SIZE_ACADEMIC, CHUNK_OVERLAP_ACADEMIC


def _deterministic_chunk_id(url: str, chunk_index: int, content: str) -> str:
    """
    Generate a deterministic ID for a chunk.

    Combines URL + index + content hash to produce a unique, reproducible ID.
    This enables:
        - Idempotent upserts (same content → same ID)
        - Precise deletion when source content changes
    """
    raw = f"{url}::chunk_{chunk_index}::{hashlib.sha256(content.encode()).hexdigest()[:16]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def chunk_content(
    url: str,
    content: str,
    source: str,
    category: str,
    title: str = "",
    content_hash: str = "",
) -> list[Document]:
    """
    Split content into LangChain Documents with rich metadata.

    Args:
        url: Source page URL.
        content: Cleaned page content text.
        source: Data source label ("vit", "riviera").
        category: Content category for metadata.
        title: Page title for context prepending.
        content_hash: SHA-256 of the full page content.

    Returns:
        List of LangChain Document objects ready for ChromaDB.
    """
    if not content or len(content.strip()) < 30:
        logger.warning(f"[SKIP] Content too short for chunking: {url}")
        return []

    chunk_size, chunk_overlap = _get_chunk_params(category)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    # Prepend title context so each chunk is self-contained
    prefix = ""
    if title:
        if source == "riviera":
            prefix = f"Riviera 2026 - {title}\n\n"
        elif source == "vit":
            prefix = f"VIT - {title}\n\n"
        else:
            prefix = f"{title}\n\n"

    titled_content = prefix + content
    chunks = splitter.split_text(titled_content)

    now = datetime.now(timezone.utc).isoformat()
    documents = []

    for i, chunk_text in enumerate(chunks):
        chunk_text = chunk_text.strip()
        if not chunk_text:
            continue

        chunk_id = _deterministic_chunk_id(url, i, chunk_text)

        doc = Document(
            page_content=chunk_text,
            metadata={
                "chunk_id": chunk_id,
                "source": source,
                "url": url,
                "title": title,
                "category": category,
                "type": f"{source}_content",
                "content_hash": content_hash,
                "scraped_at": now,
                "chunk_index": i,
                "total_chunks": len(chunks),
            },
        )
        documents.append(doc)

    logger.info(
        f"[CHUNKED] {url} → {len(documents)} chunks "
        f"(size={chunk_size}, overlap={chunk_overlap})"
    )
    return documents
