import json
import re
import uuid
from collections import defaultdict, Counter
from urllib.parse import urlparse
import hashlib

from langchain_text_splitters import RecursiveCharacterTextSplitter

# ==========================================================
# Title resolution
# ==========================================================

def derive_title(url: str) -> str:
    path = urlparse(url).path.strip("/")
    if not path:
        return "Home"
    last_segment = path.split("/")[-1]
    words = re.split(r"[-_]+", last_segment)
    return " ".join(w.capitalize() for w in words if w)


def hash_text(text: str):
    return hashlib.md5(text.encode()).hexdigest()


def safe_meta(value):
    return "" if value is None else str(value)


# ==========================================================
# Content-quality filters
# ==========================================================

def is_placeholder(content: str) -> bool:
    return not re.search(r"[a-zA-Z0-9]{2,}", content)


_BREADCRUMB_SEGMENT_RE = re.compile(r"\(https?://\S+\)\s*$")
_BREADCRUMB_MAX_AVG_SEGMENT_CHARS = 30

def is_breadcrumb_chunk(content: str) -> bool:
    parts = [p.strip() for p in content.split("|") if p.strip()]
    if len(parts) < 2:
        return False
    link_like = sum(1 for p in parts if _BREADCRUMB_SEGMENT_RE.search(p))
    if link_like / len(parts) < 0.6:
        return False
    label_lengths = [
        len(_BREADCRUMB_SEGMENT_RE.sub("", p).strip())
        for p in parts
    ]
    avg_label_len = sum(label_lengths) / len(label_lengths)
    return avg_label_len <= _BREADCRUMB_MAX_AVG_SEGMENT_CHARS


def _looks_like_real_content_despite_breadcrumb_shape(content: str) -> bool:
    """Secondary check used ONLY by the restore-safety-net, for items the
    primary breadcrumb filter skipped. A real nav trail is a handful of
    short labels ("Home", "About", "Contact") — total label word count
    stays low even across several segments. Substantive content that
    merely happens to use "|" as a separator (e.g. a dated events listing)
    crosses this bar easily. This does NOT override is_breadcrumb_chunk
    as the primary filter — it only decides whether a page left with zero
    content after filtering should get its breadcrumb-skipped items back."""
    parts = [p.strip() for p in content.split("|") if p.strip()]
    labels = [_BREADCRUMB_SEGMENT_RE.sub("", p).strip() for p in parts]
    total_label_words = sum(len(l.split()) for l in labels)
    return total_label_words >= 20


_SMASHED_WORD_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])")

def repair_smashed_word_boundaries(text: str) -> str:
    return _SMASHED_WORD_BOUNDARY_RE.sub(r"\1 \2", text)


UI_BOILERPLATE_PHRASES = {
    "upcoming event past event",
    "read more",
    "view all",
    "click here",
    "know more",
    "coming soon",
    "no data found",
    "no results found",
}

def is_known_ui_boilerplate(content: str) -> bool:
    return content.strip().lower() in UI_BOILERPLATE_PHRASES


# ==========================================================
# Semantic-entity chunk builder — one dict/FAQ item = one entity.
# ==========================================================

def structure_chunk(data):
    chunks = []
    for url, sections in data.items():
        if not isinstance(sections, dict):
            continue

        title = derive_title(url)

        for heading, contents in sections.items():
            heading = safe_meta(heading)

            if "frequently asked questions" in heading.lower():
                for item in contents:
                    chunks.append({
                        "type": "faq", "source": url, "title": title,
                        "heading": heading, "content": safe_meta(item),
                    })

            elif isinstance(contents, dict):
                for key, value in contents.items():
                    chunks.append({
                        "type": "section", "source": url, "title": title,
                        "heading": heading, "subcontent": safe_meta(key),
                        "content": safe_meta(value),
                    })
                all_keys = list(contents.keys())
                chunks.append({
                    "type": "list", "source": url, "title": title,
                    "heading": f"{heading} list",
                    "subcontent": "all clubs/chapters",
                    "content": ", ".join(safe_meta(k) for k in all_keys),
                })

            elif isinstance(contents, list):
                combined = "".join(f"{safe_meta(c)}\n" for c in contents)
                chunks.append({
                    "type": "section", "source": url, "title": title,
                    "heading": heading, "content": combined,
                })

            elif isinstance(contents, str):
                chunks.append({
                    "type": "section", "source": url, "title": title,
                    "heading": heading, "content": contents,
                })

            else:
                print(
                    f"  WARNING: unhandled contents type {type(contents)} "
                    f"for {url} :: {heading!r} — skipping (not string/dict/list)"
                )
    return chunks


# ==========================================================
# Load source files
# ==========================================================

JSON_FILES = ["merged_new_data_cleaned.json", "vit_final_with_links.json", "vit_all_data.json"]

# FIX: diagnostic-only check — if the same URL appears in more than one
# source file, both get processed as separate items below and merged into
# that URL's chunks. This isn't auto-resolved (no reliable way to know
# which file is authoritative for a given URL without knowing your
# ingestion order/intent), but it's surfaced loudly so silent
# duplication/conflict doesn't slip through unnoticed.
url_to_files = defaultdict(set)
for file_path in JSON_FILES:
    with open(file_path, encoding="utf-8") as f:
        for url in json.load(f):
            url_to_files[url].add(file_path)

overlapping = {u: fs for u, fs in url_to_files.items() if len(fs) > 1}
if overlapping:
    print(f"\n⚠️  {len(overlapping)} URLs appear in more than one source file — "
          f"content from both will be merged, which may duplicate or conflict:")
    for u, fs in list(overlapping.items())[:10]:
        print(f"   {u}  <- {fs}")
    if len(overlapping) > 10:
        print(f"   ... and {len(overlapping) - 10} more")
    print()

all_chunks = []
for file_path in JSON_FILES:
    print(f" Processing: {file_path}")
    with open(file_path, encoding="utf-8") as f:
        data = json.load(f)
        all_chunks.extend(structure_chunk(data))

# Repair smashed word boundaries from table-cell concatenation. Skip
# "list" type — comma-joined proper nouns where this regex could misfire
# on names with internal caps (e.g. "McDonald").
for item in all_chunks:
    if item["type"] != "list":
        item["content"] = repair_smashed_word_boundaries(item["content"])

with open("vit_chunks_new.json", "w", encoding="utf-8") as f:
    json.dump(all_chunks, f, indent=2, ensure_ascii=False)

print(f"Chunking complete! ({len(all_chunks)} semantic-entity chunks)")

# ==========================================================
# PARENT STORE (L1 — full page, for context lookup, NOT embedded)
# ==========================================================

parent_builder = defaultdict(list)
parent_titles = {}
for item in all_chunks:
    parent_builder[item["source"]].append(
        f"Heading:\n{item['heading']}\n\nContent:\n{item['content']}"
    )
    parent_titles[item["source"]] = item["title"]

parent_store = {
    source: {
        "parent_id": source,
        "source": source,
        "title": parent_titles[source],
        "content": "\n\n".join(texts),
    }
    for source, texts in parent_builder.items()
}
print(f"Parents: {len(parent_store)}")

# ==========================================================
# GRANDCHILD CHUNKS — one per semantic entity, title-aware embedding text.
# ==========================================================

splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)

LIST_CHUNK_WARN_CHARS = 2000


def _looks_like_name_list(content: str) -> bool:
    items = [p.strip() for p in content.split(",") if p.strip()]
    if len(items) < 3:
        return False
    capitalized = sum(1 for it in items if it[:1].isupper())
    short_enough = sum(1 for it in items if len(it.split()) <= 6)
    return (capitalized / len(items) >= 0.7) and (short_enough / len(items) >= 0.8)


def make_child_id(item):
    sub = item.get("subcontent", "")
    return f"{item['source']}::{item['heading']}::{sub}" if sub else f"{item['source']}::{item['heading']}"


def make_embedding_text(title: str, heading: str, subcontent: str, item_type: str, content: str) -> str:
    if item_type == "list" and _looks_like_name_list(content):
        prefix = f"{title} — {heading}" if title and title.lower() != heading.lower() else heading
        return f"{prefix} — full list of names in this category: {content}"

    
    parts = [p for p in (title, heading, subcontent) if p]
    # de-dupe adjacent identical parts (e.g. title == heading)
    dedup_parts = []
    for p in parts:
        if not dedup_parts or dedup_parts[-1].lower() != p.lower():
            dedup_parts.append(p)
    prefix = " — ".join(dedup_parts)

    return f"{prefix}\n\n{content}"
    


def build_grandchild_entries(item: dict) -> list[dict]:
    """Single shared path for turning one semantic-entity item into one or
    more grandchild chunks. Every caller (main loop, restore-safety-net)
    goes through this, so splitting behavior can't diverge between them."""
    content = item["content"].strip()
    if not content:
        return []

    child_id = make_child_id(item)
    heading = item["heading"]
    title = item["title"]
    item_type = item["type"]
    
    

    if item_type == "list":
        if len(content) > LIST_CHUNK_WARN_CHARS:
            print(
                f"  WARNING: list-type chunk for {item['source']} :: "
                f"{heading!r} is {len(content)} chars — not split (would "
                f"break list fidelity), but this size is unusual. Review "
                f"whether this should genuinely be one retrievable unit."
            )
        return [{
            "grandchild_id": str(uuid.uuid4()),
            "child_id": child_id,
            "parent_id": item["source"],
            "source": item["source"],
            "title": title,
            "heading": heading,
            "subcontent": safe_meta(item.get("subcontent", "")),
            "type": item_type,
            "content": content,
            "embedding_text": make_embedding_text(title, heading, safe_meta(item.get("subcontent", "")), item_type, content),
        }]

    if len(content) <= 700:
        return [{
            "grandchild_id": str(uuid.uuid4()),
            "child_id": child_id,
            "parent_id": item["source"],
            "source": item["source"],
            "title": title,
            "heading": heading,
            "subcontent": safe_meta(item.get("subcontent", "")),
            "type": item_type,
            "content": content,
            "embedding_text": make_embedding_text(title, heading, safe_meta(item.get("subcontent", "")), item_type, content),
        }]

    entries = []
    for chunk in splitter.split_text(content):
        entries.append({
            "grandchild_id": str(uuid.uuid4()),
            "child_id": child_id,
            "parent_id": item["source"],
            "source": item["source"],
            "title": title,
            "heading": heading,
            "subcontent": safe_meta(item.get("subcontent", "")),
            "type": item_type,
            "content": chunk,
            "embedding_text":make_embedding_text(title, heading, safe_meta(item.get("subcontent", "")), item_type, content),
        })
    return entries


grandchild_chunks = []
skipped_placeholder = 0
skipped_breadcrumb = 0
# FIX: track WHICH items were breadcrumb-skipped (not just a count) so the
# restore-safety-net below can reconsider exactly those items — never
# placeholder-skipped items, which have no informational content to
# recover.
breadcrumb_skipped_items = defaultdict(list)

for item in all_chunks:
    content = item["content"].strip()
    if not content:
        continue

    if item["type"] != "list":
        if is_placeholder(content):
            skipped_placeholder += 1
            continue
        if is_breadcrumb_chunk(content):
            skipped_breadcrumb += 1
            breadcrumb_skipped_items[item["source"]].append(item)
            continue

    grandchild_chunks.extend(build_grandchild_entries(item))

print(
    f"Grandchildren (semantic-entity chunks): {len(grandchild_chunks)} "
    f"({skipped_placeholder} skipped as placeholder, "
    f"{skipped_breadcrumb} skipped as breadcrumb/nav noise)"
)

# ==========================================================
# UI-noise filter — explicit boilerplate allowlist only.
# ==========================================================

before = len(grandchild_chunks)
grandchild_chunks = [
    g for g in grandchild_chunks
    if not (g["type"] != "list" and is_known_ui_boilerplate(g["content"]))
]
skipped_ui_noise = before - len(grandchild_chunks)
print(f"Grandchildren after UI-noise filter: {len(grandchild_chunks)} ({skipped_ui_noise} removed)")

# ==========================================================
# FIX: restore-safety-net, narrowed. Previously restored EVERY source left
# with zero surviving chunks, regardless of why — which un-filtered
# genuinely nav-only pages (galleries, policies-core-values, etc.) right
# back to raw breadcrumb junk, undoing is_breadcrumb_chunk for exactly the
# cases it's supposed to catch.
#
# Now: only reconsiders items that were specifically breadcrumb-skipped
# (never placeholder-skipped — nothing to recover there), and only
# restores them when a secondary check finds evidence they're real
# content rather than an actual nav trail. A source that's genuinely
# nav-only stays empty, correctly, with no restoration.
# ==========================================================

surviving_sources = set(g["source"] for g in grandchild_chunks)
wiped_by_filtering = set(
    src for src in breadcrumb_skipped_items if src not in surviving_sources
)

restored_sources = []
left_empty_sources = []

if wiped_by_filtering:
    for src in sorted(wiped_by_filtering):
        candidates = [
            item for item in breadcrumb_skipped_items[src]
            if _looks_like_real_content_despite_breadcrumb_shape(item["content"])
        ]
        if candidates:
            for item in candidates:
                grandchild_chunks.extend(build_grandchild_entries(item))
            restored_sources.append((src, len(candidates)))
        else:
            left_empty_sources.append(src)

    if restored_sources:
        print(f"\n⚠️  Restored {len(restored_sources)} page(s) wrongly wiped by the "
              f"breadcrumb filter (secondary check found real content):")
        for src, n in restored_sources:
            print(f"   restored ({n} items): {src}")

    if left_empty_sources:
        print(f"\n{len(left_empty_sources)} page(s) confirmed genuinely nav-only — "
              f"left empty (correct, not a bug):")
        for src in left_empty_sources:
            print(f"   empty: {src}")
else:
    print("No pages were fully zeroed out by breadcrumb filtering.")

# ==========================================================
# Exact-duplicate dedup pass. "list"-type chunks exempt.
# ==========================================================

def _normalized_hash(text: str) -> str:
    normalized = " ".join(text.split()).strip().lower()
    return hash_text(normalized)


seen_hashes = {}
deduped_chunks = []
removed_dupes = []
for g in grandchild_chunks:
    if g["type"] == "list":
        deduped_chunks.append(g)
        continue
    key = _normalized_hash(g["content"])
    if key in seen_hashes:
        removed_dupes.append(g)
        continue
    seen_hashes[key] = g["grandchild_id"]
    deduped_chunks.append(g)

if removed_dupes:
    dupe_sources = Counter(g["source"] for g in removed_dupes)
    print(f"\nRemoved {len(removed_dupes)} exact-duplicate chunks "
          f"(kept first occurrence of each), spanning {len(dupe_sources)} sources.")
    print("  Top sources contributing duplicates:")
    for src, count in dupe_sources.most_common(10):
        print(f"    {count:4d}  {src}")
else:
    print("\nNo exact-duplicate chunks found.")

grandchild_chunks = deduped_chunks
print(f"Grandchildren after dedup: {len(grandchild_chunks)}")

# ==========================================================
# SAVE
# ==========================================================

with open("new_parent_store.json", "w", encoding="utf-8") as f:
    json.dump(parent_store, f, indent=2, ensure_ascii=False)

with open("new_grandchild_chunks.json", "w", encoding="utf-8") as f:
    json.dump(grandchild_chunks, f, indent=2, ensure_ascii=False)

print("Saved parent_store + grandchild_chunks (single-tier retrieval)")