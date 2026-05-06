#!/usr/bin/env python3
"""
sync.py — fetches new running activities from the Tredict REST API,
writes data/activities.json, public/gpx/*.gpx, and logs/sync-latest.json.
Always exits 0.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

TOKEN     = os.environ.get("TREDICT_API_KEY", "")
BASE      = "https://www.tredict.com/api/v2"
DATA_PATH = Path("data/activities.json")
GPX_DIR   = Path("public/gpx")
LOG_PATH  = Path("logs/sync-latest.json")


# ── Helpers ──────────────────────────────────────────────────────

def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def write_log(log):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=2))


def load_existing():
    if DATA_PATH.exists():
        return json.loads(DATA_PATH.read_text())
    return []


# ── API calls ─────────────────────────────────────────────────────

def check_connectivity():
    """Ping activities endpoint with pageSize=1 to verify auth."""
    try:
        r = requests.get(
            BASE + "/activities",
            headers=auth(),
            params={"pageSize": 1},
            timeout=10,
        )
        return r.status_code == 200, r.status_code
    except Exception as e:
        return False, str(e)


def fetch_activity_list():
    """Return all activity stubs (up to 500)."""
    r = requests.get(
        BASE + "/activities",
        headers=auth(),
        params={"pageSize": 500},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    if isinstance(data, list):
        return data
    return data.get("_embedded", {}).get("activityList", [])


def fetch_activity_detail(item):
    """Fetch full activity detail by ID."""
    aid = item.get("id") or item.get("_id")
    r = requests.get(BASE + f"/activities/{aid}", headers=auth(), timeout=30)
    r.raise_for_status()
    return r.json()


# ── Data mapping ──────────────────────────────────────────────────

def _clean_series(arr):
    """Replace nulls with 0."""
    return [v if v is not None else 0 for v in arr] if arr else []


def _clean_coords(arr):
    """Drop nulls; return [] if all null."""
    if not arr:
        return []
    filtered = [v for v in arr if v is not None]
    return filtered if filtered else []


def map_activity(detail):
    s      = detail.get("summary", {})
    series = detail.get("seriesSampled", {}).get("data", {})
    effort = (s.get("effort") or {}).get("heartrate")
    alt    = (s.get("altitude") or {})
    zones  = (s.get("zonesDistribution") or {})
    wx     = detail.get("weather") or {}

    temp_raw = wx.get("temperature") or s.get("temperature")

    return {
        "id":               detail.get("_id") or detail.get("id"),
        "date":             detail.get("date"),
        "timezone":         detail.get("timezone", "Europe/Brussels"),
        "distance_m":       round(s.get("distance") or 0),
        "heartrate_avg":    s.get("heartrate"),
        "heartrate_max":    s.get("heartrateMax"),
        "effort":           round(effort) if effort is not None else None,
        "elevation_ascent": round(alt.get("ascent") or 0),
        "calories":         round(s.get("calories") or 0),
        "temperature":      round(temp_raw) if temp_raw is not None else None,
        "hr_zones":         zones.get("heartrate", []),
        "track_lat":        _clean_coords(series.get("positionLat")),
        "track_lng":        _clean_coords(series.get("positionLong")),
        "hr_series":        _clean_series(series.get("heartrate")),
        "distance_series":  _clean_series(series.get("distance")),
        "speed_series":     _clean_series(series.get("speed")),
    }


# ── GPX export ────────────────────────────────────────────────────

def save_gpx(activity):
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
        '<gpx version="1.1" creator="jeffry.running"'
        ' xmlns="http://www.topografix.com/GPX/1/1">\n'
        '  <metadata><time>{}</time></metadata>\n'
        '  <trk>\n    <trkseg>\n{}\n    </trkseg>\n  </trk>\n'
        '</gpx>'
    ).format(activity["date"], pts)
    (GPX_DIR / "{}.gpx".format(activity["id"])).write_text(gpx)
    print("      ✓ GPX saved ({} pts)".format(n))


# ── Main ──────────────────────────────────────────────────────────

def main():
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log = {
        "timestamp":           ts,
        "connectivity":        None,
        "total_on_tredict":    0,
        "skipped_non_running": 0,
        "already_known":       0,
        "new_activities":      [],
        "errors":              [],
        "status":              "ok",
    }

    if not TOKEN:
        msg = "TREDICT_API_KEY not set"
        print(f"ERROR: {msg}")
        log["status"] = "error"
        log["errors"].append(msg)
        write_log(log)
        return

    # ── 1. Connectivity check ─────────────────────────────────────
    print("Checking Tredict API connectivity...")
    ok, detail = check_connectivity()
    log["connectivity"] = {"ok": ok, "detail": str(detail)}
    if ok:
        print(f"  ✓ Connected (HTTP {detail})")
    else:
        msg = f"API unreachable: {detail}"
        print(f"  ✗ {msg}")
        log["status"] = "error"
        log["errors"].append(msg)
        write_log(log)
        return

    # ── 2. Load existing ──────────────────────────────────────────
    existing  = load_existing()
    known_ids = {a["id"] for a in existing}
    log["already_known"] = len(known_ids)
    print(f"  {len(existing)} existing activities locally")

    # ── 3. Fetch list ─────────────────────────────────────────────
    print("Fetching activity list...")
    try:
        activity_list = fetch_activity_list()
    except Exception as e:
        msg = f"Failed to fetch activity list: {e}"
        print(f"  ✗ {msg}")
        log["status"] = "error"
        log["errors"].append(msg)
        write_log(log)
        return

    log["total_on_tredict"] = len(activity_list)
    print(f"  {len(activity_list)} total activities on Tredict")

    # ── 4. Filter ─────────────────────────────────────────────────
    to_fetch   = []
    non_running = 0
    for item in activity_list:
        if item.get("sportType") != "running":
            non_running += 1
            continue
        aid = item.get("id") or item.get("_id")
        if not aid:
            continue
        if aid in known_ids:
            continue
        to_fetch.append(item)

    log["skipped_non_running"] = non_running
    print(f"  {non_running} non-running skipped, "
          f"{len(activity_list) - non_running - len(to_fetch) - len(known_ids & {i.get('id') or i.get('_id') for i in activity_list if i.get('sportType') == 'running'})} already known")
    print(f"  {len(to_fetch)} new running activities to sync")

    if not to_fetch:
        print("No new running activities.")
        log["status"] = "no_new_data"
        write_log(log)
        return

    # ── 5. Fetch details ──────────────────────────────────────────
    new_activities = []
    for item in to_fetch:
        aid = item.get("id") or item.get("_id")
        print(f"  Fetching {aid}...")
        try:
            detail   = fetch_activity_detail(item)
            activity = map_activity(detail)
            new_activities.append(activity)
            log["new_activities"].append(aid)
            dist = activity.get("distance_m", 0)
            date = (activity.get("date") or "")[:10]
            print(f"    ✓ {date} — {dist / 1000:.1f} km")
            save_gpx(activity)
        except Exception as e:
            msg = f"{aid}: {e}"
            print(f"    ✗ {msg}")
            log["errors"].append(msg)

    # ── 6. Write activities.json ───────────────────────────────────
    if new_activities:
        combined = new_activities + existing
        combined.sort(key=lambda a: a.get("date", ""), reverse=True)
        DATA_PATH.parent.mkdir(exist_ok=True)
        DATA_PATH.write_text(json.dumps(combined, indent=2))
        print(f"\nDone. {len(new_activities)} new activit"
              f"{'y' if len(new_activities) == 1 else 'ies'} added.")

    if log["errors"]:
        log["status"] = "partial_error" if new_activities else "error"

    write_log(log)
    print(f"Log written → {LOG_PATH}")


if __name__ == "__main__":
    main()
