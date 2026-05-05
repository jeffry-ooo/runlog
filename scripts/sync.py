#!/usr/bin/env python3
"""
sync.py — pulls running activities from Tredict REST API,
writes/updates data/activities.json, ready for Astro to build.
"""

import os
import json
import requests
from pathlib import Path
from datetime import datetime, timezone

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
TREDICT_API_KEY   = os.environ["TREDICT_API_KEY"]
DATA_PATH         = Path("data/activities.json")
GPX_DIR           = Path("public/gpx")

TREDICT_BASE = "https://www.tredict.com/api/oauth/v2"


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


# ── 1. Fetch activity list from Tredict ──────────────────────────

def fetch_activity_list(limit=20):
    """Pull recent activities from Tredict REST API and filter for running."""
    headers = {"Authorization": f"Bearer {TREDICT_API_KEY}"}
    resp = requests.get(
        f"{TREDICT_BASE}/activityList",
        headers=headers,
        params={"pageSize": limit}
    )
    resp.raise_for_status()
    all_activities = resp.json().get("activityList", [])
    activity_list = [a for a in all_activities if a.get("sportType") == "running"]
    print(f"  Found {len(activity_list)} running activities")
    return activity_list


def fetch_activity_detail(activity_id):
    """Fetch full detail including time series for one activity."""
    headers = {"Authorization": f"Bearer {TREDICT_API_KEY}"}
    resp = requests.get(
        f"{TREDICT_BASE}/activities/{activity_id}",
        headers=headers
    )
    resp.raise_for_status()
    return resp.json()


# ── 2. Parse Tredict response into our schema ────────────────────

def parse_activity(raw):
    """Convert Tredict activity JSON to our flat schema."""
    s = raw.get("summary", {})
    series = raw.get("seriesSampled", {}).get("data", {})
    weather = raw.get("weather", {})

    return {
        "id":               raw.get("_id") or raw.get("id"),
        "date":             raw.get("date"),
        "timezone":         raw.get("timezone", "Europe/Brussels"),
        "distance_m":       round(s.get("distance", 0)),
        "heartrate_avg":    s.get("heartrate"),
        "heartrate_max":    s.get("heartrateMax"),
        "effort":           round(s.get("effort", {}).get("heartrate", 0)),
        "elevation_ascent": round(s.get("altitude", {}).get("ascent", 0)),
        "calories":         round(s.get("calories", 0)),
        "temperature":      round(weather.get("temperature", s.get("temperature", 0))),
        "hr_zones":         raw.get("summary", {}).get("zonesDistribution", {}).get("heartrate", []),
        "track_lat":        series.get("positionLat", []),
        "track_lng":        series.get("positionLong", []),
        "hr_series":        series.get("heartrate", []),
        "distance_series":  series.get("distance", []),
        "speed_series":     [v if v else 0 for v in series.get("speed", [])],
    }


# ── 3. Load existing data ────────────────────────────────────────

def load_existing():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text())
    return []


# ── 4. Main ──────────────────────────────────────────────────────

def main():
    print("Fetching activity list from Tredict...")
    try:
        activity_list = fetch_activity_list(limit=20)
    except Exception as e:
        print(f"  ✗ Failed to fetch list: {e}")
        return

    existing = load_existing()
    existing_ids = {a["id"] for a in existing}
    new_activities = []

    for item in activity_list:
        aid = item.get("id")
        if not aid or aid in existing_ids:
            print(f"  — Skip (exists): {aid}")
            continue

        print(f"  → Fetching detail: {aid}")
        try:
            detail = fetch_activity_detail(aid)
            parsed = parse_activity(detail)
            new_activities.append(parsed)
            save_gpx(parsed)
            print(f"    ✓ {parsed['date'][:10]} — {parsed['distance_m']/1000:.1f}km")
        except Exception as e:
            print(f"    ✗ Failed: {e}")
            continue

    if not new_activities:
        print("No new activities.")
        return

    combined = new_activities + existing
    combined.sort(key=lambda a: a.get("date", ""), reverse=True)

    DATA_PATH.parent.mkdir(exist_ok=True)
    DATA_PATH.write_text(json.dumps(combined, indent=2))
    print(f"\nDone. {len(new_activities)} new activities added.")


if __name__ == "__main__":
    main()