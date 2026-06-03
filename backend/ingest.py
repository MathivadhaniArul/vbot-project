"""
Standalone ingestion script.
Run this ONCE to build the ChromaDB index from all JSON and markdown sources.
Usage: python ingest.py
"""
import uuid
import json
import hashlib
import re
from pathlib import Path
from langchain_core.documents import Document
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma

# ── Embeddings ──────────────────────────────────────────────────────────────
embeddings = HuggingFaceEmbeddings(
    model_name="nomic-ai/nomic-embed-text-v1.5",
    model_kwargs={"trust_remote_code": True}
)

BASE_DIR = Path(__file__).resolve().parent

# ── Helpers ──────────────────────────────────────────────────────────────────
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
                combined = " ".join(contents) if isinstance(contents, list) else str(contents)
                chunks.append({
                    "type": "section",
                    "source": url,
                    "heading": heading,
                    "content": combined
                })
    return chunks

# ── Clear existing chroma data ──────────────────────────────────────────────
print("Opening Chroma collection...")
docsearch = Chroma(
    collection_name="vit-regulations",
    embedding_function=embeddings,
    persist_directory=str(BASE_DIR / "chroma")
)

existing = docsearch._collection.count()
print(f"Existing embeddings: {existing}")

docs = []

# ── 1. Markdown regulations ──────────────────────────────────────────────────
REG_DIR = BASE_DIR / "reg_md"
if REG_DIR.exists():
    print("Indexing markdown regulations...")
    for path in REG_DIR.rglob("*.md"):
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        chunks = split_markdown_with_subsections(text)
        for chunk in chunks:
            content = f"Heading: {chunk['heading']}\nSubsection: {chunk['subheading']}\n\nContent: {chunk['content']}"
            docs.append(Document(
                page_content=content.strip(),
                metadata={
                    "id": hash_text(content),
                    "heading": chunk["heading"],
                    "subheading": chunk["subheading"],
                    "type": chunk["type"],
                    "source": str(path.relative_to(BASE_DIR))
                }
            ))
    print(f"  -> {len(docs)} regulation chunks")

# ── 2. JSON scraped data ──────────────────────────────────────────────────────
json_sources = [
    {"path": BASE_DIR / "scrape" / "vit_final_with_links.json", "source_name": "vit_website"},
    {"path": BASE_DIR / "riviera_chunks.json",                  "source_name": "riviera_website"},
]

before = len(docs)
for source in json_sources:
    path = source["path"]
    if path.exists():
        print(f"Indexing {source['source_name']} from {path.name}...")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        chunks = structure_chunk(data)
        for chunk in chunks:
            content = f"Heading: {chunk['heading']}\nContent: {chunk['content']}"
            docs.append(Document(
                page_content=content.strip(),
                metadata={
                    "id": hash_text(content),
                    "source": chunk.get("source") or source["source_name"],
                    "heading": chunk.get("heading"),
                    "type": chunk.get("type", "section")
                }
            ))
        print(f"  -> {len(docs) - before} chunks from {source['source_name']}")
        before = len(docs)
    else:
        print(f"  WARNING: {path} not found. Skipping.")

# ── Index into Chroma ─────────────────────────────────────────────────────────
if docs:
    print(f"\nAdding {len(docs)} total documents to ChromaDB...")
    ids = [str(uuid.uuid4()) for _ in docs]
    docsearch.add_documents(docs, ids=ids)
    print(f"Done! ChromaDB now has {docsearch._collection.count()} embeddings.")
else:
    print("No documents to index!")
