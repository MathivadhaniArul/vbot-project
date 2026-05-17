"""
Riviera Data Ingestion into ChromaDB
=====================================
Reads riviera_data.json, chunks the content, generates embeddings,
and stores them into the existing ChromaDB collection.

Uses content hashing to skip duplicates on re-runs.

Usage:
    python scrape/ingest_riviera.py
"""

import json
import hashlib
import sys
from pathlib import Path

from langchain.schema import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma


# === Configuration ===

# Chunk size: 500 chars
# Why: Riviera content is short, event-based. 500 chars captures a full event
# (name + description + venue) without mixing unrelated events.
# Too large (1000+) = retrieval pulls in irrelevant neighbor events.
# Too small (200) = loses context about what the event is.
CHUNK_SIZE = 500

# Overlap: 75 chars (15% of chunk_size)
# Why: Prevents information loss at boundaries. Events are discrete,
# so less overlap is needed vs. regulatory documents.
CHUNK_OVERLAP = 75

CHROMA_DIR = str(Path(__file__).resolve().parent.parent / "chroma")
COLLECTION_NAME = "vit-regulations"
DATA_FILE = str(Path(__file__).resolve().parent / "riviera_data.json")


def hash_text(text: str) -> str:
    """Generate MD5 hash for deduplication."""
    return hashlib.md5(text.encode()).hexdigest()


def load_riviera_data() -> list:
    """Load scraped data from JSON file."""
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def chunk_documents(data: list) -> list[Document]:
    """
    Split scraped content into chunks with metadata.
    Each chunk gets:
      - source: "riviera"
      - url: page URL
      - title: page title
      - category: event category or page type
      - id: content hash for deduplication
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    documents = []
    for page in data:
        content = page.get("content", "").strip()
        if not content or len(content) < 30:
            continue

        # Prepend title context so each chunk is self-contained
        titled_content = f"Riviera 2026 - {page['title']}\n\n{content}"

        chunks = splitter.split_text(titled_content)

        for chunk in chunks:
            doc = Document(
                page_content=chunk.strip(),
                metadata={
                    "id": hash_text(chunk),
                    "source": "riviera",
                    "url": page.get("url", ""),
                    "title": page.get("title", ""),
                    "category": page.get("category", "general"),
                    "type": "riviera_event",
                },
            )
            documents.append(doc)

    return documents


def ingest_into_chroma(documents: list[Document]):
    """
    Add documents to existing ChromaDB collection.
    Skips duplicates by checking content hashes against existing IDs.
    """
    print(f"[*] Loading embeddings model...")
    embeddings = HuggingFaceEmbeddings(
        model_name="nomic-ai/nomic-embed-text-v1.5",
        model_kwargs={"trust_remote_code": True},
    )

    print(f"[>] Connecting to ChromaDB at: {CHROMA_DIR}")
    docsearch = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=CHROMA_DIR,
    )

    existing_count = docsearch._collection.count()
    print(f"[*] Existing documents in collection: {existing_count}")

    if not documents:
        print("[WARN] No documents to ingest!")
        return

    # Get existing IDs to avoid duplicates
    try:
        existing_data = docsearch._collection.get(include=["metadatas"])
        existing_hashes = set()
        if existing_data and existing_data.get("metadatas"):
            for meta in existing_data["metadatas"]:
                if meta and meta.get("id"):
                    existing_hashes.add(meta["id"])
        print(f"[*] Found {len(existing_hashes)} existing content hashes")
    except Exception:
        existing_hashes = set()

    # Filter out duplicates
    new_docs = [
        doc for doc in documents
        if doc.metadata.get("id") not in existing_hashes
    ]

    if not new_docs:
        print("[OK] All documents already exist in ChromaDB. Nothing to add.")
        return

    print(f"[*] Adding {len(new_docs)} new documents (skipping {len(documents) - len(new_docs)} duplicates)...")

    # Add in batches of 50 to avoid memory issues
    batch_size = 50
    for i in range(0, len(new_docs), batch_size):
        batch = new_docs[i : i + batch_size]
        ids = [hash_text(doc.page_content + doc.metadata.get("url", "")) for doc in batch]
        docsearch.add_documents(batch, ids=ids)
        print(f"  [OK] Batch {i // batch_size + 1}: added {len(batch)} documents")

    final_count = docsearch._collection.count()
    print(f"\n[DONE] Ingestion complete!")
    print(f"[*] Collection now has {final_count} documents (was {existing_count})")
    print(f"[*] Added {final_count - existing_count} new documents")


def main():
    print("=" * 60)
    print("[*] Riviera Data Ingestion Pipeline")
    print("=" * 60)

    # Step 1: Load data
    print(f"\n[>] Loading data from: {DATA_FILE}")
    try:
        data = load_riviera_data()
    except FileNotFoundError:
        print(f"[FAIL] File not found: {DATA_FILE}")
        print("   Run 'python scrape/riviera.py' first to scrape the website.")
        sys.exit(1)

    print(f"   Loaded {len(data)} pages")

    # Step 2: Chunk documents
    print(f"\n[>] Chunking with size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}...")
    documents = chunk_documents(data)
    print(f"   Created {len(documents)} chunks")

    # Step 3: Ingest into ChromaDB
    print(f"\n[>] Ingesting into ChromaDB...")
    ingest_into_chroma(documents)

    print(f"\n{'=' * 60}")
    print("[DONE] Done! Restart your backend to pick up new data.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
