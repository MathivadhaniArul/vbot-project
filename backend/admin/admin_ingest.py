import asyncio
import traceback
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import models

import main
from admin.chunking import build_hierarchical_chunks


router = APIRouter(
    prefix="/api/admin/ingest",
    tags=["admin-ingest"],
)


# ============================================================================
# TIME HELPERS
# ============================================================================
#
# Store timestamps in UTC with timezone information.
#
# Example:
#   2026-08-18T10:48:00.123456+00:00
#
# The frontend can convert this to:
#   18 Aug, 04:18 pm
#
# for Asia/Kolkata.
# ============================================================================

DISPLAY_TIMEZONE = "Asia/Kolkata"


def utc_now() -> datetime:
    """
    Return the current timezone-aware UTC datetime.

    DO NOT use datetime.utcnow().
    datetime.utcnow() returns a naive datetime.
    """
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """
    Return current UTC time as an ISO-8601 string.
    """
    return utc_now().isoformat()


def serialize_datetime(value: Any) -> Any:
    """
    Convert datetime values to ISO strings before returning them
    through FastAPI.

    MongoDB datetime values are timezone-aware/UTC in normal operation.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)

        return value.isoformat()

    return value


# ============================================================================
# QDRANT HELPERS
# ============================================================================


def _get_qdrant_client_and_collection():
    """
    main.hybrid_store is expected to expose:
        .client
        .collection_name

    If your hybrid store uses different names, only this function
    needs to be changed.
    """

    store = main.hybrid_store

    if store is None:
        raise RuntimeError("main.hybrid_store is not initialized")

    client = getattr(store, "client", None)
    collection_name = getattr(store, "collection_name", None)

    if client is None or collection_name is None:
        raise AttributeError(
            "main.hybrid_store does not expose "
            ".client/.collection_name — "
            "update _get_qdrant_client_and_collection() "
            "to match your store's API."
        )

    return client, collection_name


def _parent_id_filter(parent_id: str) -> models.Filter:
    """
    Match all current grandchild vectors and legacy child vectors
    belonging to this parent.
    """

    return models.Filter(
        must=[
            models.FieldCondition(
                key="metadata.parent_id",
                match=models.MatchValue(value=parent_id),
            ),
            models.FieldCondition(
                key="metadata.level",
                match=models.MatchAny(
                    any=["grandchild", "child"]
                ),
            ),
        ]
    )


async def delete_stale_chunks(parent_id: str) -> int:
    """
    Delete all existing hierarchical vectors for a parent.

    This removes:
      - current grandchild vectors
      - legacy child vectors

    Returns the number of points removed.
    """

    client, collection_name = _get_qdrant_client_and_collection()

    delete_filter = _parent_id_filter(parent_id)

    def _count_then_delete():
        existing = client.count(
            collection_name=collection_name,
            count_filter=delete_filter,
            exact=True,
        ).count

        if existing > 0:
            client.delete(
                collection_name=collection_name,
                points_selector=models.FilterSelector(
                    filter=delete_filter
                ),
            )

        return existing

    try:
        return await asyncio.to_thread(_count_then_delete)

    except Exception as exc:
        main.logger.error(
            f"[cleanup] failed to delete stale chunks "
            f"for parent_id={parent_id}: {exc}\n"
            f"{traceback.format_exc()}"
        )
        raise


# ============================================================================
# CONFIRM INGEST
# ============================================================================


@router.post("/confirm")
async def admin_ingest_confirm(
    payload: dict = Body(...)
):
    """
    Supported payloads:

    Hierarchical:

    {
        "source": "...",
        "title": "...",
        "structured": {
            "Heading": [...]
        }
    }

    Flat:

    {
        "source": "...",
        "title": "...",
        "text": "...",
        "chunk_size": 800,
        "chunk_overlap": 120
    }
    """

    title = str(
        payload.get("title", "")
    ).strip()

    source = (
        str(payload.get("source", "")).strip()
        or str(payload.get("url", "")).strip()
        or title
    )

    structured = payload.get("structured")

    if not source:
        raise HTTPException(
            status_code=400,
            detail="source (or url) is required",
        )

    if main.hybrid_store is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Vector store not initialized yet — "
                "try again shortly."
            ),
        )

    if structured:
        return await _ingest_hierarchical(
            title=title,
            source=source,
            structured=structured,
        )

    text = str(
        payload.get("text", "")
    ).strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail=(
                "either 'structured' or 'text' is required"
            ),
        )

    chunk_size = int(
        payload.get("chunk_size", 800)
    )

    chunk_overlap = int(
        payload.get("chunk_overlap", 120)
    )

    if chunk_size <= 0:
        raise HTTPException(
            status_code=400,
            detail="chunk_size must be greater than 0",
        )

    if chunk_overlap < 0:
        raise HTTPException(
            status_code=400,
            detail="chunk_overlap cannot be negative",
        )

    if chunk_overlap >= chunk_size:
        raise HTTPException(
            status_code=400,
            detail="chunk_overlap must be smaller than chunk_size",
        )

    return await _ingest_flat_text(
        title=title,
        source=source,
        text=text,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


# ============================================================================
# HIERARCHICAL INGEST
# ============================================================================


async def _ingest_hierarchical(
    *,
    title: str,
    source: str,
    structured: dict,
):
    """
    Build hierarchical chunks.

    Qdrant:
        ONLY grandchild vectors

    MongoDB:
        ONE parent document
    """

    grandchildren, children, parent = (
        build_hierarchical_chunks(
            structured,
            source,
        )
    )

    if not grandchildren:
        raise HTTPException(
            status_code=400,
            detail=(
                "No chunks produced from "
                "structured content."
            ),
        )

    parent_id = parent["parent_id"]

    # ------------------------------------------------------------------------
    # Delete old vectors first
    # ------------------------------------------------------------------------

    try:
        deleted_count = await delete_stale_chunks(
            parent_id
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Failed to clear stale vectors: {exc}"
            ),
        )

    # ------------------------------------------------------------------------
    # IMPORTANT:
    # Use timezone-aware UTC.
    # ------------------------------------------------------------------------

    now = utc_now()
    now_iso = now.isoformat()

    # ------------------------------------------------------------------------
    # QDRANT DOCUMENTS
    # ------------------------------------------------------------------------

    docs = []

    for gc in grandchildren:
        docs.append(
            Document(
                page_content=gc["content"],
                metadata={
                    "level": "grandchild",
                    "grandchild_id": gc["grandchild_id"],
                    "child_id": gc["child_id"],
                    "parent_id": gc["parent_id"],
                    "source": gc["source"],
                    "heading": gc["heading"],
                    "title": title,

                    # UTC timezone-aware timestamp
                    "ingested_at": now_iso,

                    "ingested_by": "admin_dashboard",
                },
            )
        )

    # ------------------------------------------------------------------------
    # QDRANT UPSERT
    # ------------------------------------------------------------------------

    try:
        await asyncio.to_thread(
            main.hybrid_store.add_documents,
            docs,
        )

    except Exception as exc:
        main.logger.error(
            f"[ingest] Qdrant upsert failed: {exc}\n"
            f"{traceback.format_exc()}"
        )

        raise HTTPException(
            status_code=500,
            detail=f"Vector ingestion failed: {exc}",
        )

    # ------------------------------------------------------------------------
    # MONGODB PARENT
    # ------------------------------------------------------------------------

    try:
        await main.db["page_parents"].update_one(
            {
                "parent_id": parent_id
            },
            {
                "$set": {
                    **parent,

                    "title": title,

                    # Children are not persisted.
                    "child_count": 0,

                    "grandchild_count": len(
                        grandchildren
                    ),

                    # Timezone-aware UTC datetime.
                    "updatedAt": now,
                },

                "$setOnInsert": {
                    "createdAt": now,
                },
            },
            upsert=True,
        )

    except Exception as exc:
        main.logger.error(
            f"[ingest] Mongo parent upsert failed: "
            f"{exc}\n"
            f"{traceback.format_exc()}"
        )

        raise HTTPException(
            status_code=500,
            detail=f"Parent storage failed: {exc}",
        )

    # ------------------------------------------------------------------------
    # INGESTION HISTORY
    # ------------------------------------------------------------------------

    try:
        await main.db[
            "ingested_documents"
        ].insert_one(
            {
                "title": title,
                "source": source,
                "mode": "hierarchical",

                "grandchild_count": len(
                    grandchildren
                ),

                "child_count": 0,

                "stale_chunks_removed": deleted_count,

                "sample_chunk": (
                    grandchildren[0]["content"][:300]
                ),

                # Timezone-aware UTC.
                "createdAt": now,
            }
        )

    except Exception as exc:
        main.logger.error(
            f"[ingest] ingestion history storage failed: "
            f"{exc}\n"
            f"{traceback.format_exc()}"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"Ingestion history storage failed: "
                f"{exc}"
            ),
        )

    main.logger.info(
        f"[ingest] '{title}' ({source}): "
        f"removed {deleted_count} stale vectors, "
        f"added {len(grandchildren)} grandchild docs "
        f"-> Qdrant; child docs discarded; "
        f"1 parent doc -> Mongo"
    )

    return {
        "success": True,
        "mode": "hierarchical",

        "stale_chunks_removed": deleted_count,

        "grandchild_ingested": len(
            grandchildren
        ),

        "child_ingested": 0,

        "child_discarded": len(children),

        "parent_id": parent_id,

        "title": title,
        "source": source,

        # Explicit timestamp for the frontend.
        "createdAt": now_iso,

        # Helpful display value.
        "timezone": "UTC",

        "display_timezone": DISPLAY_TIMEZONE,
    }


# ============================================================================
# FLAT TEXT INGEST
# ============================================================================


async def _ingest_flat_text(
    *,
    title: str,
    source: str,
    text: str,
    chunk_size: int,
    chunk_overlap: int,
):
    """
    Legacy flat-text ingestion.

    Qdrant:
        grandchild/leaf vectors

    MongoDB:
        one parent document containing complete text
    """

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=[
            "\n## ",
            "\n\n",
            "\n",
            ". ",
            " ",
            "",
        ],
    )

    chunks = splitter.split_text(text)

    if not chunks:
        raise HTTPException(
            status_code=400,
            detail=(
                "Text produced no chunks "
                "after splitting."
            ),
        )

    parent_id = source

    # ------------------------------------------------------------------------
    # One consistent timestamp for this ingestion.
    # ------------------------------------------------------------------------

    now = utc_now()
    now_iso = now.isoformat()

    # ------------------------------------------------------------------------
    # Delete previous vectors
    # ------------------------------------------------------------------------

    try:
        deleted_count = await delete_stale_chunks(
            parent_id
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Failed to clear stale vectors: "
                f"{exc}"
            ),
        )

    # ------------------------------------------------------------------------
    # Build Qdrant documents
    # ------------------------------------------------------------------------

    docs = []

    for i, chunk in enumerate(chunks):
        docs.append(
            Document(
                page_content=chunk,
                metadata={
                    "level": "grandchild",

                    "grandchild_id": (
                        f"{parent_id}::gc::{i}"
                    ),

                    "child_id": (
                        f"{parent_id}::child::0"
                    ),

                    "parent_id": parent_id,

                    "source": source,

                    "heading": (
                        title or "Document"
                    ),

                    "title": title,

                    # UTC timezone-aware timestamp.
                    "ingested_at": now_iso,

                    "ingested_by": "admin_dashboard",

                    "chunk_index": i,
                },
            )
        )

    # ------------------------------------------------------------------------
    # QDRANT UPSERT
    # ------------------------------------------------------------------------

    try:
        await asyncio.to_thread(
            main.hybrid_store.add_documents,
            docs,
        )

    except Exception as exc:
        main.logger.error(
            f"[ingest] failed to add grandchild "
            f"documents: {exc}\n"
            f"{traceback.format_exc()}"
        )

        raise HTTPException(
            status_code=500,
            detail=f"Ingestion failed: {exc}",
        )

    # ------------------------------------------------------------------------
    # MONGODB
    # ------------------------------------------------------------------------

    try:
        await main.db[
            "page_parents"
        ].update_one(
            {
                "parent_id": parent_id
            },
            {
                "$set": {
                    "parent_id": parent_id,
                    "source": source,
                    "title": title,
                    "content": text,
                    "mode": "flat",

                    "child_count": 0,

                    "grandchild_count": len(
                        chunks
                    ),

                    # UTC-aware.
                    "updatedAt": now,
                },

                "$setOnInsert": {
                    "createdAt": now,
                },
            },
            upsert=True,
        )

        await main.db[
            "ingested_documents"
        ].insert_one(
            {
                "title": title,
                "source": source,
                "mode": "flat",

                "grandchild_count": len(
                    chunks
                ),

                "child_count": 0,

                "stale_chunks_removed": deleted_count,

                "sample_chunk": chunks[0][:300],

                # UTC-aware.
                "createdAt": now,
            }
        )

    except Exception as exc:
        main.logger.error(
            f"[ingest] Mongo parent storage failed: "
            f"{exc}\n"
            f"{traceback.format_exc()}"
        )

        raise HTTPException(
            status_code=500,
            detail=f"Parent storage failed: {exc}",
        )

    main.logger.info(
        f"[ingest] added {len(chunks)} "
        f"grandchild docs -> Qdrant; "
        f"1 parent doc -> Mongo; "
        f"removed {deleted_count} stale vectors"
    )

    return {
        "success": True,
        "mode": "flat",

        "stale_chunks_removed": deleted_count,

        "grandchild_ingested": len(chunks),

        "child_ingested": 0,

        "parent_id": parent_id,

        "title": title,
        "source": source,

        "createdAt": now_iso,

        "timezone": "UTC",

        "display_timezone": DISPLAY_TIMEZONE,
    }


# ============================================================================
# PURGE
# ============================================================================


@router.post("/purge")
async def admin_ingest_purge(
    payload: dict = Body(...)
):
    """
    Delete all vectors and parent data for a source.
    """

    parent_id = (
        str(
            payload.get("parent_id", "")
        ).strip()
        or str(
            payload.get("source", "")
        ).strip()
    )

    if not parent_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "parent_id (or source) is required"
            ),
        )

    if main.hybrid_store is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Vector store not initialized yet — "
                "try again shortly."
            ),
        )

    try:
        deleted_count = await delete_stale_chunks(
            parent_id
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete vectors: {exc}",
        )

    mongo_result = await main.db[
        "page_parents"
    ].delete_one(
        {
            "parent_id": parent_id
        }
    )

    main.logger.info(
        f"[purge] parent_id={parent_id}: "
        f"removed {deleted_count} vectors, "
        f"{mongo_result.deleted_count} parent doc(s)"
    )

    return {
        "success": True,
        "parent_id": parent_id,

        "vectors_removed": deleted_count,

        "parent_removed": bool(
            mongo_result.deleted_count
        ),
    }


# ============================================================================
# RETRIEVAL TEST
# ============================================================================


@router.post("/test")
async def admin_ingest_test(
    payload: dict = Body(...)
):
    """
    Run a query through the same retriever used
    by the chat pipeline.
    """

    query = str(
        payload.get("query", "")
    ).strip()

    include_parent = payload.get(
        "include_parent",
        True,
    )

    if not query:
        raise HTTPException(
            status_code=400,
            detail="query is required",
        )

    if main.retriever is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Retriever not initialized yet — "
                "try again shortly."
            ),
        )

    try:
        docs = await asyncio.to_thread(
            main.retriever.invoke,
            query,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Retrieval test failed: {exc}"
            ),
        )

    if not include_parent:
        return {
            "success": True,
            "query": query,
            "results": [
                {
                    "content": d.page_content[:500],
                    "metadata": d.metadata,
                }
                for d in docs
            ],
        }

    results = await _attach_parent_context(
        docs
    )

    return {
        "success": True,
        "query": query,
        "results": results,
    }


# ============================================================================
# PARENT CONTEXT
# ============================================================================


async def _attach_parent_context(
    docs: list,
    dedupe: bool = True,
) -> list[dict]:
    """
    Fetch parent content from MongoDB for retrieved
    grandchild documents.
    """

    parent_ids = list(
        {
            d.metadata.get("parent_id")
            for d in docs
            if d.metadata.get("parent_id")
        }
    )

    if not parent_ids:
        return [
            _result_without_parent(d)
            for d in docs
        ]

    cursor = main.db[
        "page_parents"
    ].find(
        {
            "parent_id": {
                "$in": parent_ids
            }
        }
    )

    parents_by_id = {
        p["parent_id"]: p
        async for p in cursor
    }

    results = []
    seen_parents = set()

    for d in docs:
        metadata = d.metadata

        parent_id = metadata.get(
            "parent_id"
        )

        parent = parents_by_id.get(
            parent_id
        )

        if (
            dedupe
            and parent_id in seen_parents
        ):
            results.append(
                _result_without_parent(d)
            )
            continue

        if parent_id:
            seen_parents.add(parent_id)

        results.append(
            {
                "level": metadata.get(
                    "level"
                ),

                "content": d.page_content,

                "heading": metadata.get(
                    "heading"
                ),

                "source": metadata.get(
                    "source"
                ),

                "grandchild_id": metadata.get(
                    "grandchild_id"
                ),

                "child_id": metadata.get(
                    "child_id"
                ),

                "parent_id": parent_id,

                "parent_content": (
                    parent.get("content")
                    if parent
                    else None
                ),
            }
        )

    return results


def _result_without_parent(
    d,
) -> dict:
    """
    Format a retrieval result without
    parent content.
    """

    metadata = d.metadata

    return {
        "level": metadata.get(
            "level"
        ),

        "content": d.page_content,

        "heading": metadata.get(
            "heading"
        ),

        "source": metadata.get(
            "source"
        ),

        "grandchild_id": metadata.get(
            "grandchild_id"
        ),

        "child_id": metadata.get(
            "child_id"
        ),

        "parent_id": metadata.get(
            "parent_id"
        ),

        "parent_content": None,
    }


# ============================================================================
# DOCUMENT HISTORY
# ============================================================================


@router.get("/documents")
async def admin_ingest_documents(
    limit: int = 50,
):
    """
    Return recently ingested documents.

    Timestamps are returned in ISO-8601 UTC.

    Example:

        createdAt:
        2026-08-18T10:48:00+00:00

    The frontend should display this in Asia/Kolkata.
    """

    if limit < 1:
        limit = 1

    if limit > 500:
        limit = 500

    docs = await main.db[
        "ingested_documents"
    ].find(
        {}
    ).sort(
        "createdAt",
        -1,
    ).limit(
        limit
    ).to_list(
        limit
    )

    response_documents = []

    for document in docs:
        document["_id"] = str(
            document["_id"]
        )

        created_at = document.get(
            "createdAt"
        )

        # --------------------------------------------------------------------
        # Normalize old naive Mongo timestamps.
        #
        # Older records may have been written using datetime.utcnow().
        # Treat those old values as UTC.
        # --------------------------------------------------------------------

        if isinstance(
            created_at,
            datetime,
        ):
            if created_at.tzinfo is None:
                created_at = created_at.replace(
                    tzinfo=timezone.utc
                )

            document[
                "createdAt"
            ] = created_at.isoformat()

            # Keep this explicit so the frontend knows
            # what timezone the canonical timestamp uses.
            document[
                "createdAtTimezone"
            ] = "UTC"

        else:
            document[
                "createdAtTimezone"
            ] = "UTC"

        response_documents.append(
            document
        )

    return {
        "success": True,

        "documents": response_documents,

        "timezone": "UTC",

        "display_timezone": DISPLAY_TIMEZONE,
    }