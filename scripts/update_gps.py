#!/usr/bin/env python3
"""
update_gps.py — fetches GPS track data for activities missing it,
updates data/activities.json, and generates GPX files.
"""

import os
import json
import requests
from pathlib import Path

TREDICT_API_KEY = os.environ["TREDICT_API_KEY"]
DATA_PATH = Path("data/activities.json")
GPX_DIR = Path("public/gpx")


def fetch_activity(activity_id):
    headers = {"Authorization": f"Bearer {TREDICT_API_KEY}"}
    resp = requests.get(
        f"https://www.tredict.com/api/v2/activities/{activity_id}",
        headers=headers
    )
    resp.raise_for_status()
    return resp.json()


def save_gpx(activity_id, date, lats, lngs):
    GPX_DIR.mkdir(parents=True, exist_ok=True)
    n = len(lats)
    pts = "\n".join(
        '      <trkpt lat="{:.5f}" lon="{:.5f}"></trkpt>'.format(lats[i], lngs[i])
        for i in range(n)
    )
    gpx = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<gpx version="1.1" creator="jeffry.running" '
        'xmlns="http://www.topografix.com/GPX/1/1">\n'
        '  <metadata><time>{}</time></metadata>\n'
        '  <trk>\n    <trkseg>\n{}\n    </trkseg>\n  </trk>\n'
        '</gpx>'
    ).format(date, pts)
    out = GPX_DIR / f"{activity_id}.gpx"
    out.write_text(gpx)
    print(f"    ✓ GPX saved ({n} pts)")


def main():
    activities = json.loads(DATA_PATH.read_text())
    updated = 0

    for a in activities:
        if a.get("track_lat") and len(a["track_lat"]) > 2:
            print(f"  — Skip (has GPS): {a['id']} ({a['date'][:10]})")
            continue

        print(f"  → Fetching GPS: {a['id']} ({a['date'][:10]})")
        try:
            raw = fetch_activity(a["id"])
            series = raw.get("seriesSampled", {}).get("data", {})
            lats = series.get("positionLat", [])
            lngs = series.get("positionLong", [])

            # Filter pairs where both values are non-null
            pairs = [
                (lat, lng) for lat, lng in zip(lats, lngs)
                if lat is not None and lng is not None
            ]

            if len(pairs) < 3:
                print(f"    ✗ Too few GPS points ({len(pairs)}), skipping")
                continue

            clean_lats = [round(p[0], 5) for p in pairs]
            clean_lngs = [round(p[1], 5) for p in pairs]

            a["track_lat"] = clean_lats
            a["track_lng"] = clean_lngs

            save_gpx(a["id"], a["date"], clean_lats, clean_lngs)
            print(f"    ✓ {len(pairs)} GPS points added")
            updated += 1

        except Exception as e:
            print(f"    ✗ Failed: {e}")

    DATA_PATH.write_text(json.dumps(activities, indent=2))
    print(f"\nDone. {updated} activities updated.")


if __name__ == "__main__":
    main()
