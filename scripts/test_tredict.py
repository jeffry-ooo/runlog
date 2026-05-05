#!/usr/bin/env python3
"""
test_tredict.py — diagnostic tool that tests every likely Tredict API
endpoint + auth combination and writes results to logs/tredict-diagnostic.json.
Always exits 0.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("requests not installed — run: pip install requests")
    sys.exit(0)

TOKEN = os.environ.get("TREDICT_API_KEY", "")
if not TOKEN:
    print("ERROR: TREDICT_API_KEY not set")
    sys.exit(0)

BASE = "https://www.tredict.com"

ENDPOINTS = [
    "/api/v2/activities",
    "/api/v2/activityList",
    "/api/oauth/v2/activities",
    "/api/oauth/v2/activityList",
    "/api/mcp/v2/activities",
    "/api/mcp/v2/activityList",
]

AUTH_STYLES = [
    ("Bearer", {"Authorization": f"Bearer {TOKEN}"}),
    ("Token",  {"Authorization": f"Token {TOKEN}"}),
    ("XApiKey", {"X-API-Key": TOKEN}),
]

results = []

for endpoint in ENDPOINTS:
    for auth_name, headers in AUTH_STYLES:
        url = BASE + endpoint
        try:
            r = requests.get(url, headers=headers, timeout=10)
            status = r.status_code
            preview = r.text[:200].replace("\n", " ").strip()
            success = status == 200
        except Exception as e:
            status = 0
            preview = str(e)[:200]
            success = False

        label = "✓" if success else "✗"
        print(f"  {label} [{status}] {auth_name:8s} {endpoint}")

        results.append({
            "endpoint": endpoint,
            "auth": auth_name,
            "status": status,
            "success": success,
            "response_preview": preview,
        })

successes = sum(1 for r in results if r["success"])
total = len(results)
summary = f"{successes}/{total} combinations succeeded"
print(f"\n{summary}")

log = {
    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "results": results,
    "summary": summary,
}

log_path = Path("logs/tredict-diagnostic.json")
log_path.parent.mkdir(parents=True, exist_ok=True)
log_path.write_text(json.dumps(log, indent=2))
print(f"Log written to {log_path}")
