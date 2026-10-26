"""
Auto-Updating Ingestion Pipeline
=================================
Scheduled scraping → change detection → incremental chunking → ChromaDB updates.

Modules:
    config           URL registry and constants
    fetcher          Hybrid page fetcher (requests + Playwright)
    cleaner          Content cleaning and normalization
    change_detector  SHA-256 hashing + SQLite metadata tracking
    chunker          Incremental document chunking
    vectorstore      ChromaDB upsert/delete operations
    scheduler        APScheduler job definitions
    runner           Pipeline orchestrator
"""

__version__ = "1.0.0"
