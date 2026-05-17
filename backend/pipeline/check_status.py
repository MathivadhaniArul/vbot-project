"""Check pipeline status and history."""
import urllib.request
import json
import time

# Check status
r = urllib.request.urlopen("http://127.0.0.1:8000/api/pipeline/status")
status = json.loads(r.read())
print("=== PIPELINE STATUS ===")
print(json.dumps(status, indent=2))

# Check history
r = urllib.request.urlopen("http://127.0.0.1:8000/api/pipeline/history")
history = json.loads(r.read())
entries = history.get("history", [])
print(f"\n=== SCRAPE HISTORY ({len(entries)} entries) ===")
for h in entries[:10]:
    url = h.get("url", "?")[:70]
    status_val = h.get("status", "?")
    chunks = "?"
    if h.get("chunk_ids"):
        chunk_list = json.loads(h["chunk_ids"]) if isinstance(h["chunk_ids"], str) else h["chunk_ids"]
        chunks = len(chunk_list)
    print(f"  [{status_val:5s}] {url} ({chunks} chunks)")
