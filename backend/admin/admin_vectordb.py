import asyncio
from collections import Counter
from fastapi import APIRouter, Body, HTTPException, Query
from qdrant_client import models
import main

router = APIRouter(prefix="/api/admin/vectordb", tags=["admin-vectordb"])


def _get_qdrant_client_and_collection():
    store = main.hybrid_store
    client = getattr(store, "client", None)
    collection_name = getattr(store, "collection_name", None)
    if client is None or collection_name is None:
        raise AttributeError(
            "main.hybrid_store does not expose .client/.collection_name — "
            "update this to match your store's API."
        )
    return client, collection_name


# =========================================================================
# Collection-level stats
# =========================================================================

@router.get("/stats")
async def vectordb_stats():
    """
    High-level health snapshot of the Qdrant collection: total points,
    vector config, index status, and a breakdown by level (grandchild/
    child/flat) and by source, so an admin can see at a glance what's
    actually stored without querying anything manually.
    """
    client, collection_name = _get_qdrant_client_and_collection()

    def _collect():
        info = client.get_collection(collection_name)

        level_counts = Counter()
        source_counts = Counter()
        ingested_by_counts = Counter()
        total_scanned = 0

        # scroll the whole collection in batches — payload-only, no vectors,
        # to keep this cheap even at tens of thousands of points
        next_offset = None
        while True:
            points, next_offset = client.scroll(
                collection_name=collection_name,
                limit=500,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                meta = payload.get("metadata", payload)  # handle either nesting
                level_counts[meta.get("level", "unknown")] += 1
                source_counts[meta.get("source", "unknown")] += 1
                ingested_by_counts[meta.get("ingested_by", "unknown")] += 1
                total_scanned += 1
            if next_offset is None:
                break

        return info, level_counts, source_counts, ingested_by_counts, total_scanned

    try:
        info, level_counts, source_counts, ingested_by_counts, total_scanned = (
            await asyncio.to_thread(_collect)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read collection stats: {e}")

    return {
        "success": True,
        "collection_name": collection_name,
        "points_count": info.points_count,
        "vectors_count": getattr(info, "vectors_count", None),
        "indexed_vectors_count": getattr(info, "indexed_vectors_count", None),
        "status": str(info.status),
        "total_scanned": total_scanned,
        "by_level": dict(level_counts),
        "top_sources": source_counts.most_common(20),
        "source_count": len(source_counts),
        "by_ingested_by": dict(ingested_by_counts),
    }


# =========================================================================
# Per-source breakdown
# =========================================================================

@router.get("/sources")
async def vectordb_sources(limit: int = Query(100, ge=1, le=1000)):
    """
    List every distinct source (parent_id/URL) currently in Qdrant, with
    grandchild/child counts each, cross-referenced against MongoDB to flag
    sources that have vectors but no parent doc (orphaned — usually means
    a purge or ingest failed halfway).
    """
    client, collection_name = _get_qdrant_client_and_collection()

    def _collect():
        per_source = {}
        next_offset = None
        while True:
            points, next_offset = client.scroll(
                collection_name=collection_name,
                limit=500,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                meta = payload.get("metadata", payload)
                source = meta.get("parent_id") or meta.get("source") or "unknown"
                level = meta.get("level", "unknown")
                entry = per_source.setdefault(source, {"grandchild": 0, "child": 0, "flat": 0, "other": 0})
                if level in entry:
                    entry[level] += 1
                else:
                    entry["other"] += 1
            if next_offset is None:
                break
        return per_source

    try:
        per_source = await asyncio.to_thread(_collect)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to enumerate sources: {e}")

    parent_ids = list(per_source.keys())
    existing_parents = set()
    if parent_ids:
        cursor = main.db["page_parents"].find(
            {"parent_id": {"$in": parent_ids}}, {"parent_id": 1}
        )
        existing_parents = {doc["parent_id"] async for doc in cursor}

    rows = [
        {
            "source": source,
            **counts,
            "total": sum(counts.values()),
            "has_parent_doc": source in existing_parents,
        }
        for source, counts in per_source.items()
    ]
    rows.sort(key=lambda r: r["total"], reverse=True)

    return {
        "success": True,
        "sources": rows[:limit],
        "total_sources": len(rows),
        "orphaned_sources": sum(1 for r in rows if not r["has_parent_doc"]),
    }


# =========================================================================
# Orphan detection — vectors with no parent doc, or parent docs with no
# vectors (both directions of drift)
# =========================================================================

@router.get("/orphans")
async def vectordb_orphans():
    """
    Two-directional consistency check between Qdrant and MongoDB:
      - vector_orphans: parent_ids present in Qdrant but missing from
        page_parents (e.g. Mongo write failed after Qdrant succeeded)
      - mongo_orphans: parent_ids present in page_parents but with zero
        vectors in Qdrant (e.g. purge deleted vectors but not the Mongo doc,
        or Qdrant delete failed after Mongo succeeded)
    """
    client, collection_name = _get_qdrant_client_and_collection()

    def _qdrant_parent_ids():
        ids = set()
        next_offset = None
        while True:
            points, next_offset = client.scroll(
                collection_name=collection_name,
                limit=500,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                meta = payload.get("metadata", payload)
                pid = meta.get("parent_id")
                if pid:
                    ids.add(pid)
            if next_offset is None:
                break
        return ids

    try:
        qdrant_parent_ids = await asyncio.to_thread(_qdrant_parent_ids)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to scan Qdrant: {e}")

    mongo_parent_ids = {
        doc["parent_id"]
        async for doc in main.db["page_parents"].find({}, {"parent_id": 1})
    }

    vector_orphans = sorted(qdrant_parent_ids - mongo_parent_ids)
    mongo_orphans = sorted(mongo_parent_ids - qdrant_parent_ids)

    return {
        "success": True,
        "vector_orphans": vector_orphans,   # has vectors, no parent doc
        "mongo_orphans": mongo_orphans,     # has parent doc, no vectors
        "vector_orphan_count": len(vector_orphans),
        "mongo_orphan_count": len(mongo_orphans),
        "in_sync_count": len(qdrant_parent_ids & mongo_parent_ids),
    }


@router.post("/orphans/repair")
async def vectordb_repair_orphans(payload: dict = Body(...)):
    """
    Cleans up one side of a detected inconsistency:
      - "vector": deletes Qdrant vectors for parent_ids with no Mongo doc
      - "mongo": deletes Mongo parent docs for parent_ids with no Qdrant vectors
    Pass the exact list returned by /orphans so nothing is guessed.
    """
    side = payload.get("side")
    parent_ids = payload.get("parent_ids", [])

    if side not in ("vector", "mongo"):
        raise HTTPException(status_code=400, detail="side must be 'vector' or 'mongo'")
    if not parent_ids:
        raise HTTPException(status_code=400, detail="parent_ids is required and must be non-empty")

    if side == "vector":
        client, collection_name = _get_qdrant_client_and_collection()

        def _delete_all():
            deleted = 0
            for pid in parent_ids:
                f = models.Filter(
                    must=[models.FieldCondition(key="metadata.parent_id", match=models.MatchValue(value=pid))]
                )
                count = client.count(collection_name=collection_name, count_filter=f, exact=True).count
                if count > 0:
                    client.delete(collection_name=collection_name, points_selector=models.FilterSelector(filter=f))
                    deleted += count
            return deleted

        try:
            deleted = await asyncio.to_thread(_delete_all)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Vector cleanup failed: {e}")

        main.logger.info(f"[vectordb-repair] deleted {deleted} orphaned vectors for {len(parent_ids)} parent_ids")
        return {"success": True, "side": "vector", "vectors_removed": deleted, "parent_ids_processed": len(parent_ids)}

    else:  # side == "mongo"
        result = await main.db["page_parents"].delete_many({"parent_id": {"$in": parent_ids}})
        main.logger.info(f"[vectordb-repair] deleted {result.deleted_count} orphaned parent docs")
        return {"success": True, "side": "mongo", "parents_removed": result.deleted_count}


# =========================================================================
# Point-level inspection & manual delete
# =========================================================================

@router.get("/points")
async def vectordb_points_by_source(
    source: str = Query(..., description="parent_id / source URL to inspect"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Every point (grandchild + child) currently stored for one source, for manual review."""
    client, collection_name = _get_qdrant_client_and_collection()

    f = models.Filter(
        must=[models.FieldCondition(key="metadata.parent_id", match=models.MatchValue(value=source))]
    )

    def _fetch():
        points, _ = client.scroll(
            collection_name=collection_name,
            scroll_filter=f,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return points

    try:
        points = await asyncio.to_thread(_fetch)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch points: {e}")

    rows = []
    for p in points:
        payload = p.payload or {}
        meta = payload.get("metadata", payload)
        rows.append({
            "point_id": str(p.id),
            "level": meta.get("level"),
            "heading": meta.get("heading"),
            "grandchild_id": meta.get("grandchild_id"),
            "child_id": meta.get("child_id"),
            "content_preview": (payload.get("page_content") or payload.get("content") or "")[:200],
        })

    return {"success": True, "source": source, "points": rows, "count": len(rows)}


@router.post("/points/delete")
async def vectordb_delete_points(payload: dict = Body(...)):
    """Delete specific points by Qdrant point ID — for surgical removal of a single bad chunk."""
    point_ids = payload.get("point_ids", [])
    if not point_ids:
        raise HTTPException(status_code=400, detail="point_ids is required and must be non-empty")

    client, collection_name = _get_qdrant_client_and_collection()

    def _delete():
        client.delete(
            collection_name=collection_name,
            points_selector=models.PointIdsList(points=point_ids),
        )

    try:
        await asyncio.to_thread(_delete)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete points: {e}")

    main.logger.info(f"[vectordb] manually deleted {len(point_ids)} point(s)")
    return {"success": True, "deleted": len(point_ids)}


# =========================================================================
# Duplicate detection — same heading+source appearing more than once
# (usually means re-ingestion happened without the pre-delete cleanup step)
# =========================================================================

@router.get("/duplicates")
async def vectordb_duplicates():
    """
    Flags child_ids that appear more than once in the collection — this
    should never happen if delete_stale_chunks() ran correctly before
    every re-ingest, so a non-empty result here usually means a purge/
    re-ingest raced or partially failed.
    """
    client, collection_name = _get_qdrant_client_and_collection()

    def _collect():
        child_id_counts = Counter()
        next_offset = None
        while True:
            points, next_offset = client.scroll(
                collection_name=collection_name,
                limit=500,
                offset=next_offset,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                payload = p.payload or {}
                meta = payload.get("metadata", payload)
                cid = meta.get("child_id")
                if cid:
                    child_id_counts[cid] += 1
            if next_offset is None:
                break
        return child_id_counts

    try:
        counts = await asyncio.to_thread(_collect)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to scan for duplicates: {e}")

    dup_candidates = {cid: n for cid, n in counts.items() if n > 1}

    return {
        "success": True,
        "note": "counts include grandchild+child sharing the same child_id; "
                "cross-check via /points?source=<parent_id> before deleting anything",
        "child_ids_with_multiple_points": dup_candidates,
        "count": len(dup_candidates),
    }