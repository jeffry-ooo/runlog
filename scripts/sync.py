#!/usr/bin/env python3
"""
sync.py — fetches new running activities from Tredict via the Anthropic API
(claude-sonnet-4-6 + Tredict MCP server), writes data/activities.json.
"""

import json
import os
import re
from pathlib import Path

import anthropic

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TREDICT_API_KEY   = os.environ["TREDICT_API_KEY"]
DATA_PATH         = Path("data/activities.json")
GPX_DIR           = Path("public/gpx")

MCP_SERVER = {
    "type": "url",
    "url": "https://www.tredict.com/api/mcp/v2",
    "name": "tredict",
    "authorization_token": TREDICT_API_KEY,
}


# ── GPX export ───────────────────────────────────────────────────

def save_gpx(activity):
    """Write a GPX file for an activity if it has GPS track data."""
    lats = activity.get("track_lat", [])
    lngs = activity.get("track_lng", [])
    n = min(len(lats), len(lngs))
    if n < 3:
        return
    GPX_DIR.mkdir(parents=True, exist_ok=True)
    pts = "\n".join(
        '      <trkpt lat="{:.5f}" lon="{:.5f}"></trkpt>'.format(lats[i], lngs[i])
        for i in range(n)
    )
    gpx = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="jeffry.running" xmlns="http://www.topografix.com/GPX/1/1">\n'
        '  <metadata><time>{}</time></metadata>\n'
        '  <trk>\n    <trkseg>\n{}\n    </trkseg>\n  </trk>\n'
        '</gpx>'
    ).format(activity["date"], pts)
    out = GPX_DIR / "{}.gpx".format(activity["id"])
    out.write_text(gpx)
    print("    ✓ GPX saved ({} pts)".format(n))


# ── Load existing data ───────────────────────────────────────────

def load_existing():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text())
    return []


# ── Extract JSON array from Claude's text response ───────────────

def extract_json_array(text):
    """Pull the first [...] block out of a response string."""
    text = text.strip()
    if text.startswith("["):
        return json.loads(text)
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"No JSON array found in Claude response:\n{text[:400]}")


# ── Fetch new activities via Anthropic + Tredict MCP ────────────

def fetch_new_activities(known_ids):
    known_list = sorted(known_ids)
    prompt = (
        "Fetch all running activities from Tredict since 2026-04-01 using the activity-list tool.\n"
        "IMPORTANT: Only process activities where sportType == 'running'. "
        "Skip any misc, cycling, swimming, indoor_rowing, or other non-running activities entirely.\n"
        f"For each running activity whose id is NOT in this list: {known_list}\n"
        "call the activity tool to get full detail including time series.\n"
        "Return ONLY a valid JSON array with no preamble or explanation. Each object must have:\n"
        "  sportType, id, date, timezone, distance_m, heartrate_avg, heartrate_max, effort,\n"
        "  elevation_ascent, calories, temperature, hr_zones,\n"
        "  track_lat, track_lng, hr_series, distance_series, speed_series\n"
        "Use these mappings from the Tredict activity detail response:\n"
        "  sportType     ← sportType (must be 'running')\n"
        "  id            ← _id or id\n"
        "  date          ← date\n"
        "  timezone      ← timezone (default 'Europe/Brussels')\n"
        "  distance_m    ← summary.distance (rounded int)\n"
        "  heartrate_avg ← summary.heartrate\n"
        "  heartrate_max ← summary.heartrateMax\n"
        "  effort        ← summary.effort.heartrate (rounded int)\n"
        "  elevation_ascent ← summary.altitude.ascent (rounded int)\n"
        "  calories      ← summary.calories (rounded int)\n"
        "  temperature   ← weather.temperature or summary.temperature (rounded int)\n"
        "  hr_zones      ← summary.zonesDistribution.heartrate (array)\n"
        "  track_lat     ← seriesSampled.data.positionLat (array, null→omit)\n"
        "  track_lng     ← seriesSampled.data.positionLong (array, null→omit)\n"
        "  hr_series     ← seriesSampled.data.heartrate (array)\n"
        "  distance_series ← seriesSampled.data.distance (array)\n"
        "  speed_series  ← seriesSampled.data.speed (array, null values → 0)\n"
        "If there are no new activities, return an empty array: []"
    )

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    print("  Calling Anthropic API with Tredict MCP server...")

    response = client.beta.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=16000,
        messages=[{"role": "user", "content": prompt}],
        mcp_servers=[MCP_SERVER],
        betas=["mcp-client-2025-04-04"],
    )

    # Collect all text blocks (tool-use blocks are handled server-side)
    text_parts = [block.text for block in response.content if hasattr(block, "text")]
    full_text = "\n".join(text_parts).strip()

    if not full_text:
        raise ValueError("Claude returned no text content")

    return extract_json_array(full_text)


# ── Main ─────────────────────────────────────────────────────────

def main():
    print("Loading existing activities...")
    existing = load_existing()
    known_ids = {a["id"] for a in existing}
    print(f"  {len(existing)} existing, {len(known_ids)} known IDs")

    print("Fetching new activities via Anthropic + Tredict MCP...")
    try:
        new_activities = fetch_new_activities(known_ids)
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return

    if not new_activities:
        print("No new activities.")
        return

    # Safety filter: discard anything Claude returned that isn't running
    before = len(new_activities)
    new_activities = [a for a in new_activities if a.get("sportType", "running") == "running"]
    if len(new_activities) < before:
        print(f"  ⚠ Dropped {before - len(new_activities)} non-running activities")

    # Strip sportType — it's not part of the stored schema
    for a in new_activities:
        a.pop("sportType", None)

    if not new_activities:
        print("No new running activities after filtering.")
        return

    print(f"  {len(new_activities)} new activity/activities returned")
    for activity in new_activities:
        aid = activity.get("id", "?")
        dist = activity.get("distance_m", 0)
        date = activity.get("date", "?")[:10]
        print(f"  → {date} — {dist/1000:.1f}km  [{aid}]")
        save_gpx(activity)

    combined = new_activities + existing
    combined.sort(key=lambda a: a.get("date", ""), reverse=True)

    DATA_PATH.parent.mkdir(exist_ok=True)
    DATA_PATH.write_text(json.dumps(combined, indent=2))
    print(f"\nDone. {len(new_activities)} new activities added.")


if __name__ == "__main__":
    main()
