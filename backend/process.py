# from docling_client import DoclingClient
# import pandas as pd


# client = DoclingClient(base_url="http://localhost:8004")
# print(client.health())
# data = client.convert("FFCS_Academic_Regulation_4_0_Final.pdf")

# # Markdown
# with open("FFCS.md", "w", encoding="utf-8") as f:
#     f.write(data["markdown"])

# # Tables
# for i, table_rows in enumerate(data["tables"]):
#     df = pd.DataFrame(table_rows)
#     print(f"--- Table {i} ---")
#     print(df.head())
#     df.to_csv(f"table_{i}.csv", index=False)

# # Chunks
# for chunk in data["chunks"]:
#     print(chunk["section_path"])
#     print(chunk["text"])
#     print("---")

# enriched_chunks = data["chunks"]  # already in the shape you wanted

import json
import re
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling.chunking import HybridChunker
from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
)
from docling_core.transforms.chunker.tokenizer.huggingface import (
    HuggingFaceTokenizer,
)
from docling_core.transforms.serializer.markdown import (
    MarkdownParams,
    MarkdownTableSerializer,
)
from transformers import AutoTokenizer

# ============================================================
# Configuration
# ============================================================

INPUT_FILE = "student_code_of_conduct.md"
OUTPUT_FILE = "student_code_of_conduct.json"

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# True embedding context length
MAX_TOKENS = 256

# Merge very small chunks
MIN_CHUNK_TOKENS = 40

# ============================================================
# Markdown Table Serializer
# ============================================================

class MDTableSerializerProvider(ChunkingSerializerProvider):

    def get_serializer(self, doc):
        return ChunkingDocSerializer(
            doc=doc,
            table_serializer=MarkdownTableSerializer(),
            params=MarkdownParams(compact_tables=True),
        )


# ============================================================
# Helpers
# ============================================================

def clean_heading(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = text.replace(" .", ".")
    text = text.rstrip(":")
    return text.strip()


def is_plausible_heading(text: str) -> bool:

    text = clean_heading(text)

    if not text:
        return False

    words = text.split()

    if len(words) > 20:
        return False

    if text.endswith((",", ";")):
        return False

    if text.endswith(".") and len(words) > 6:
        return False

    return True


def clean_text(text: str) -> str:

    text = text.replace("\u00A0", " ")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def token_count(text: str):

    return len(
        hf_tokenizer.encode(
            text,
            add_special_tokens=False,
        )
    )


def build_content(headings, body):
    """
    This is the text that will be embedded.
    """

    sections = []

    if headings:

        sections.append("Heading:")
        sections.append(headings[0])

        if len(headings) > 1:
            sections.append("")
            sections.append("Subheading:")
            sections.append(" > ".join(headings[1:]))

    sections.append("")
    sections.append("Content:")
    sections.append(body)

    return "\n".join(sections).strip()


# ============================================================
# Convert document
# ============================================================

print("Converting document...")

converter = DocumentConverter()
result = converter.convert(INPUT_FILE)

document = result.document

# ============================================================
# Tokenizer
# ============================================================

hf_tokenizer = AutoTokenizer.from_pretrained(
    EMBED_MODEL
)

tokenizer = HuggingFaceTokenizer(
    tokenizer=hf_tokenizer,
    max_tokens=MAX_TOKENS,
)

# ============================================================
# Chunker
# ============================================================

chunker = HybridChunker(
    tokenizer=tokenizer,
    merge_peers=True,
    serializer_provider=MDTableSerializerProvider(),
    repeat_table_header=True,
)

chunks = list(
    chunker.chunk(dl_doc=document)
)

print(f"Generated {len(chunks)} raw chunks")

# ============================================================
# Extract chunks
# ============================================================

raw_chunks = []

for chunk in chunks:

    headings = []

    for h in chunk.meta.headings or []:

        h = clean_heading(h)

        if is_plausible_heading(h):
            headings.append(h)

    # Remove duplicates while preserving order
    headings = list(dict.fromkeys(headings))

    body = clean_text(chunk.text)

    raw_chunks.append(
        {
            "headings": headings,
            "body": body,
        }
    )

# ============================================================
# Merge tiny chunks
# ============================================================

merged = []
buffer = None

for i, chunk in enumerate(raw_chunks):

    if buffer is not None:

        chunk = {
            "headings": buffer["headings"] or chunk["headings"],
            "body": buffer["body"] + "\n\n" + chunk["body"],
        }

        buffer = None

    if (
        token_count(chunk["body"]) < MIN_CHUNK_TOKENS
        and i != len(raw_chunks) - 1
    ):
        buffer = chunk
        continue

    merged.append(chunk)

if buffer is not None:

    if merged:
        merged[-1]["body"] += "\n\n" + buffer["body"]
    else:
        merged.append(buffer)

# ============================================================
# Build JSON
# ============================================================

source = Path(INPUT_FILE).name

output = []

for idx, chunk in enumerate(merged):

    content = build_content(
        chunk["headings"],
        chunk["body"],
    )

    metadata = {
        "source": source,
        "tokens": token_count(content),
        "characters": len(content),
    }

    if chunk["headings"]:
        metadata["heading"] = chunk["headings"][0]

    if len(chunk["headings"]) > 1:
        metadata["subheading"] = chunk["headings"][1]

    metadata["heading_path"] = chunk["headings"]

    output.append(
        {
            "id": f"{source}#chunk_{idx:04d}",
            "source": source,
            "content": content,
            "metadata": metadata,
        }
    )

# ============================================================
# Save
# ============================================================

with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8",
) as f:

    json.dump(
        output,
        f,
        indent=2,
        ensure_ascii=False,
    )

print(f"Saved {len(output)} chunks to {OUTPUT_FILE}")