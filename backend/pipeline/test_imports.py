"""Quick smoke test: verify all pipeline modules import cleanly."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

print("Testing imports...")

from pipeline.config import SCRAPE_TARGETS, get_targets_by_schedule
print(f"  config: OK — {len(SCRAPE_TARGETS)} targets total")
print(f"    frequent: {len(get_targets_by_schedule('frequent'))}")
print(f"    normal:   {len(get_targets_by_schedule('normal'))}")

from pipeline.cleaner import clean_text, normalize_url
print(f"  cleaner: OK")

from pipeline.change_detector import ChangeDetector, ChangeResult
detector = ChangeDetector()
print(f"  change_detector: OK — SQLite DB ready")

from pipeline.chunker import chunk_content
print(f"  chunker: OK")

from pipeline.fetcher import fetch_page
print(f"  fetcher: OK")

# Test change detection round-trip
report = detector.check("https://test.example.com", "Hello World test content")
print(f"  change_detector test: result={report.result.value}, hash={report.new_hash[:16]}...")

# Test chunking
docs = chunk_content(
    url="https://test.example.com",
    content="This is a test content block that should be chunked properly. " * 20,
    source="test",
    category="events",
    title="Test Page",
    content_hash="abc123",
)
print(f"  chunker test: {len(docs)} chunks generated")

from pipeline.runner import run_pipeline
print(f"  runner: OK")

from pipeline.scheduler import start_scheduler, stop_scheduler, get_scheduler_status
print(f"  scheduler: OK")

print("\n[OK] All pipeline modules import successfully!")
