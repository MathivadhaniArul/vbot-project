import uuid


def build_hierarchical_chunks(structured: dict, url: str, source: str | None = None):
    """
    structured: heading -> list[str]  (output of _extract_structured in admin_scrape.py)
    Returns (grandchildren: list[dict], children: list[dict], parent: dict)
    matching the grandchild/child/parent JSON schema:
      grandchild: {grandchild_id, child_id, parent_id, source, heading, content}
      child:      {child_id, parent_id, source, heading, content}
      parent:     {parent_id, source, content}
    """
    source = source or url
    parent_id = url

    children = []
    grandchildren = []
    parent_content_parts = []

    for heading, items in structured.items():
        child_id = f"{url}::{heading}"
        full_content = " ".join(i.strip() for i in items if i.strip()).strip()
        if not full_content:
            continue

        children.append({
            "child_id": child_id,
            "parent_id": parent_id,
            "source": source,
            "heading": heading,
            "content": full_content,
        })

        parent_content_parts.append(f"Heading:\n{heading}\n\nContent:\n{full_content}\n\n")

        for piece in _pack_into_pieces(items, max_chars=500):
            grandchildren.append({
                "grandchild_id": str(uuid.uuid4()),
                "child_id": child_id,
                "parent_id": parent_id,
                "source": source,
                "heading": heading,
                "content": piece,
            })

    parent = {
        "parent_id": parent_id,
        "source": source,
        "content": "\n" + "\n".join(parent_content_parts).strip() + "\n",
    }

    return grandchildren, children, parent


def _pack_into_pieces(items: list[str], max_chars: int = 500) -> list[str]:
    """
    Greedily packs heading items into ~max_chars pieces without splitting
    an item mid-sentence, unless a single item itself exceeds max_chars
    (then hard-wrap it). This produces multiple grandchild rows per child
    when a heading's content is long, mirroring headings like "SELECTION
    PROCEDURE" that span several grandchild entries under one child.
    """
    pieces, current, current_len = [], [], 0

    for raw in items:
        item = raw.strip()
        if not item:
            continue

        if len(item) > max_chars:
            if current:
                pieces.append(" ".join(current))
                current, current_len = [], 0
            for i in range(0, len(item), max_chars):
                pieces.append(item[i:i + max_chars])
            continue

        if current_len + len(item) + 1 > max_chars and current:
            pieces.append(" ".join(current))
            current, current_len = [], 0

        current.append(item)
        current_len += len(item) + 1

    if current:
        pieces.append(" ".join(current))

    return pieces or [""]