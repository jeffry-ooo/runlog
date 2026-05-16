#!/usr/bin/env python3
"""
sync.py — fetches new running activities from the Tredict REST API,
writes data/activities/<id>.json, public/gpx/*.gpx, and logs/sync-latest.json.
Always exits 0.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

TOKEN        = os.environ.get("TREDICT_API_KEY", "")
BASE         = "https://www.tredict.com/api/oauth/v2"
ACTIVITY_DIR = Path("data/activities")
GPX_DIR      = Path("public/gpx")
LOG_PATH     = Path("logs/sync-latest.json")

# How long to wait for Tredict to compute effort before storing anyway (no HR data).
# If effort isn't ready within an hour of upload it almost certainly won't come
# (activity was recorded without a heart-rate monitor).
EFFORT_GRACE_HOURS = 1
# How long to keep re-checking a stored null-effort activity for an updated score
EFFORT_REFRESH_DAYS = 7


# ── Helpers ──────────────────────────────────────────────────────

def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def write_log(log):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, indent=2))


def load_existing():
    if not ACTIVITY_DIR.exists():
        return []
    return [json.loads(p.read_text()) for p in ACTIVITY_DIR.glob("*.json")]


def parse_date(date_str):
    if not date_str:
        return None
    try:
        s = (date_str or "").replace("Z", "+00:00")
        # Accept both full ISO and date-only strings
        if "T" not in s:
            s += "T00:00:00+00:00"
        return datetime.fromisoformat(s)
    except ValueError:
        return None


# ── API calls ─────────────────────────────────────────────────────

def check_connectivity():
    """Ping activityList endpoint with pageSize=1 to verify auth."""
    try:
        r = requests.get(
            BASE + "/activityList",
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
        BASE + "/activityList",
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
    """Fetch full activity detail via the HAL self link."""
    url = (item.get("_links") or {}).get("self", {}).get("href")
    if not url:
        aid = item.get("id") or item.get("_id")
        url = BASE + f"/activity/{aid}"
    r = requests.get(url, headers=auth(), timeout=30)
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
    now = datetime.now(timezone.utc)
    ts  = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    log = {
        "timestamp":           ts,
        "connectivity":        None,
        "total_on_tredict":    0,
        "skipped_non_running": 0,
        "already_known":       0,
        "pending_effort":      0,
        "new_activities":      [],
        "updated_activities":  [],
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
    existing    = load_existing()
    by_id       = {a["id"]: a for a in existing}

    # Re-check for effort only on activities stored with null effort that are
    # recent enough that Tredict might still compute the score.
    refresh_ids = {
        a["id"] for a in existing
        if a.get("effort") is None
        and parse_date(a.get("date")) is not None
        and (now - parse_date(a["date"])).days <= EFFORT_REFRESH_DAYS
    }

    # All other existing IDs are considered fully known (skip re-fetching).
    known_ids = set(by_id.keys()) - refresh_ids

    log["already_known"]  = len(known_ids)
    log["pending_effort"] = len(refresh_ids)
    print(
        f"  {len(existing)} existing activities locally "
        f"({len(known_ids)} known, {len(refresh_ids)} pending effort re-check)"
    )

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
    to_fetch    = []  # list of (item, is_refresh)
    non_running = 0
    no_id_skipped = 0
    for item in activity_list:
        if item.get("sportType") != "running":
            non_running += 1
            continue
        # Try top-level id fields first, then extract from the HAL self link URL.
        aid = item.get("id") or item.get("_id")
        if not aid:
            href = (item.get("_links") or {}).get("self", {}).get("href", "")
            aid = href.rstrip("/").split("/")[-1] or None
        if not aid:
            no_id_skipped += 1
            print(f"  ⚠ Running activity with no resolvable ID — skipping: {item}")
            continue
        if aid in known_ids:
            continue
        to_fetch.append((item, aid in refresh_ids))

    n_new     = sum(1 for _, is_ref in to_fetch if not is_ref)
    n_refresh = sum(1 for _, is_ref in to_fetch if is_ref)
    log["skipped_non_running"] = non_running
    log["skipped_no_id"]       = no_id_skipped
    print(
        f"  {non_running} non-running skipped, "
        f"{len(known_ids)} already known, "
        f"{n_new} new, {n_refresh} pending effort re-check"
        + (f", {no_id_skipped} skipped (no ID)" if no_id_skipped else "")
    )

    if not to_fetch:
        print("Nothing to fetch — all running activities already known.")
        log["status"] = "no_new_data"
        write_log(log)
        return

    # ── 5. Fetch details ──────────────────────────────────────────
    new_activities     = []
    updated_activities = []

    for item, is_refresh in to_fetch:
        aid = item.get("id") or item.get("_id")
        print(f"  Fetching {aid}...")
        try:
            detail   = fetch_activity_detail(item)
            activity = map_activity(detail)
            dist     = activity.get("distance_m", 0)
            date     = (activity.get("date") or "")[:10]

            if dist < 100:
                print(f"    ⚠ {date} — {dist}m too short, skipping (invalid/ghost run)")
                continue

            if activity.get("effort") is None:
                if is_refresh:
                    # Already stored — effort still not available, nothing to update.
                    print(f"    ⏳ {date} — {dist / 1000:.1f} km (effort still pending)")
                    continue

                # Truly new activity with no effort score yet.
                run_date  = parse_date(activity.get("date"))
                age_hours = (now - run_date).total_seconds() / 3600 if run_date else 999
                if age_hours < EFFORT_GRACE_HOURS:
                    print(
                        f"    ⏳ {date} — {dist / 1000:.1f} km "
                        f"(effort not ready, {age_hours:.0f}h old — will retry)"
                    )
                    continue
                # Older than grace period: Tredict won't compute effort (no HR data).
                # Store it anyway so it appears on the site.
                print(
                    f"    ✓ {date} — {dist / 1000:.1f} km "
                    f"(no effort after {age_hours:.0f}h, storing as-is)"
                )
            else:
                if is_refresh:
                    print(f"    ✓ {date} — {dist / 1000:.1f} km (effort now {activity['effort']} — updated)")
                else:
                    print(f"    ✓ {date} — {dist / 1000:.1f} km")

            if is_refresh:
                updated_activities.append(activity)
                log["updated_activities"].append(aid)
            else:
                new_activities.append(activity)
                log["new_activities"].append(aid)

            save_gpx(activity)

        except Exception as e:
            msg = f"{aid}: {e}"
            print(f"    ✗ {msg}")
            log["errors"].append(msg)

    # ── 6. Write per-activity JSON files ──────────────────────────
    if new_activities or updated_activities:
        ACTIVITY_DIR.mkdir(parents=True, exist_ok=True)
        for a in new_activities + updated_activities:
            (ACTIVITY_DIR / f"{a['id']}.json").write_text(json.dumps(a, indent=2))
        n = len(new_activities)
        u = len(updated_activities)
        parts = []
        if n:
            parts.append(f"{n} new {'activity' if n == 1 else 'activities'}")
        if u:
            parts.append(f"{u} updated")
        print(f"\nDone. {', '.join(parts)} written.")
        log["status"] = "synced"
    else:
        log["status"] = "pending_effort" if to_fetch else "no_new_data"

    if log["errors"]:
        log["status"] = "partial_error" if (new_activities or updated_activities) else "error"

    write_log(log)
    print(f"Log written → {LOG_PATH}")


if __name__ == "__main__":
    main()
