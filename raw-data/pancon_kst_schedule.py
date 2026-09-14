#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PANCON (Pan Continental Shipping / 범주해운) — Bangkok & Laem Chabang -> Ho Chi Minh
weekly service schedule fetcher/projector.

WHAT THIS SCRIPT DOES
----------------------
PANCON's public website (https://www.pancon.co.kr/intro/serviceRoute) publishes
the recurring weekly port-rotation for each of their services (day-of-week +
time, no specific calendar dates, no vessel names). The route that covers
Bangkok, Laem Chabang and Ho Chi Minh City is service code "KST" — "KOREA
SHIPPING THAILAND SERVICE".

This script:
  1. Calls the exact two JSON endpoints that page itself calls
     (POST /pan/getDataSvcRouteVer.pcl, POST /pan/getDataRouteSection.pcl)
     to pull the current KST rotation.
  2. Finds the BANGKOK -> HO CHI MINH and LAEM CHABANG -> HO CHI MINH legs
     inside that rotation (by walking the rotation order, not by hardcoding
     day names, so it keeps working if PANCON changes the timetable).
  3. Projects those weekly day/time patterns onto real calendar dates for
     whatever month(s)/year you ask for (default: this run's September and
     October) and prints/saves the result.

IMPORTANT — please read
------------------------
* PANCON does NOT expose a public, login-free tool that gives specific
  per-voyage sailing dates or vessel/voyage names. Their actual "Schedule"
  screen (https://www.pancon.co.kr/pcl/newpclnet/schedule) lives behind
  e-Service member login, and — separately — did not render usable content
  in an automated/headless browser when this script was built (it appears
  to depend on an old plugin/legacy front-end). This script therefore
  CANNOT and does NOT attempt to log in (we never handle passwords in
  automated tools), and it cannot give you vessel names, cut-off times, or
  a definitive per-container booking date.
* What it gives you instead is the WEEKLY RECURRING pattern PANCON itself
  publishes (e.g. "ex-Bangkok every Monday"), projected onto real dates.
  Treat the generated dates as a planning estimate, not a booking
  confirmation — always verify the exact sailing with PANCON or your
  forwarder before committing cargo.
* This script needs normal internet access to www.pancon.co.kr. If that
  request fails (offline, site down, endpoint changed), it automatically
  falls back to a rotation snapshot captured on 2026-09-09 and clearly
  labels the output as coming from that cached snapshot.

USAGE
-----
    python3 pancon_kst_schedule.py                       # this run's Sep+Oct, current year
    python3 pancon_kst_schedule.py --months 9 10 --year 2026
    python3 pancon_kst_schedule.py --csv out.csv          # also save a CSV
"""

import argparse
import csv
import datetime as dt
import json
import sys
from typing import Optional

try:
    import requests
except ImportError:
    sys.exit("This script needs the 'requests' package: pip install requests")

BASE_URL = "https://www.pancon.co.kr"
SERVICE_ROUTE_PAGE = f"{BASE_URL}/intro/serviceRoute"
VER_ENDPOINT = f"{BASE_URL}/pan/getDataSvcRouteVer.pcl"
SECTION_ENDPOINT = f"{BASE_URL}/pan/getDataRouteSection.pcl"

LINE_CD = "KST"  # KOREA SHIPPING THAILAND SERVICE (Incheon/Busan - HCMC - Laem Chabang - Bangkok)

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
WD_INDEX = {d: i for i, d in enumerate(WEEKDAYS)}

HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Origin": BASE_URL,
    "Referer": SERVICE_ROUTE_PAGE,
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
}

# ---------------------------------------------------------------------------
# Snapshot captured live from the PANCON site on 2026-09-09, used only if the
# live request below fails. Keeps the script useful even offline, and its
# structure exactly mirrors the real API response so the rest of the code
# doesn't need to know which source it came from.
# ---------------------------------------------------------------------------
OFFLINE_FALLBACK_ROTATION = [
    {"ROTATION_SEQ": 1, "PORT_NM": "INCHEON", "TMN_NM": "Inchon Sunkwang New Container Terminal", "ETA": "WED / 16:00", "ETD": "THU / 07:00"},
    {"ROTATION_SEQ": 2, "PORT_NM": "BUSAN", "TMN_NM": "Busan Port Terminal (BPT-SinSeonDae)", "ETA": "FRI / 22:00", "ETD": "SAT / 12:00"},
    {"ROTATION_SEQ": 3, "PORT_NM": "HOCHIMINH CITY", "TMN_NM": "CAT LAI TERMINAL", "ETA": "THU / 13:00", "ETD": "FRI / 02:00"},
    {"ROTATION_SEQ": 4, "PORT_NM": "LAEM CHABANG", "TMN_NM": "LCHB5 / PPL-2815", "ETA": "SAT / 22:00", "ETD": "SUN / 09:00"},
    {"ROTATION_SEQ": 5, "PORT_NM": "BANGKOK", "TMN_NM": "UNITHAI CY#2114, RTN #2333 (PPL0113)", "ETA": "SUN / 12:00", "ETD": "MON / 15:00"},
    {"ROTATION_SEQ": 6, "PORT_NM": "LAEM CHABANG", "TMN_NM": "LCHB5 / PPL-2815", "ETA": "MON / 19:00", "ETD": "TUE / 08:00"},
    {"ROTATION_SEQ": 7, "PORT_NM": "HOCHIMINH CITY", "TMN_NM": "CAT LAI TERMINAL", "ETA": "WED / 19:00", "ETD": "THU / 14:00"},
]


def fetch_live_rotation(line_cd: str = LINE_CD) -> list:
    """Reproduces exactly what the browser does on the Service Route page:
    1) resolve the current LINE_VER_SEQ for this service code, then
    2) pull the full port rotation for that version.
    Raises on any network/parse problem so the caller can fall back."""
    session = requests.Session()
    # Touch the real page first so cookies/session state look normal.
    session.get(SERVICE_ROUTE_PAGE, headers=HEADERS, timeout=15)

    ver_resp = session.post(VER_ENDPOINT, headers=HEADERS,
                             data=json.dumps({"I_AS_LINE_CD": line_cd}), timeout=15)
    ver_resp.raise_for_status()
    ver_rows = ver_resp.json()["rows"]
    if not ver_rows:
        raise RuntimeError(f"PANCON returned no version info for line code {line_cd!r}")
    line_ver_seq = ver_rows[0]["LINE_VER_SEQ"]

    sec_resp = session.post(
        SECTION_ENDPOINT, headers=HEADERS,
        data=json.dumps({"I_AS_LINE_CD": line_cd, "I_AS_LINE_VER_SEQ": line_ver_seq}),
        timeout=15,
    )
    sec_resp.raise_for_status()
    rotation = sec_resp.json()["SP_SVC_ROUTE_PORT_R"]
    rotation.sort(key=lambda r: r["ROTATION_SEQ"])
    return rotation


def get_rotation(line_cd: str = LINE_CD) -> tuple:
    """Returns (rotation_list, source_label)."""
    try:
        return fetch_live_rotation(line_cd), "live (pancon.co.kr, just now)"
    except Exception as exc:  # noqa: BLE001 - we deliberately want a broad, user-facing fallback
        print(f"[warning] Could not reach PANCON live schedule ({exc}); "
              f"using the 2026-09-09 cached snapshot instead.", file=sys.stderr)
        return OFFLINE_FALLBACK_ROTATION, "cached snapshot from 2026-09-09"


def parse_wd_time(value: str):
    """'MON / 15:00' -> (weekday_index 0=Mon..6=Sun, datetime.time)."""
    day_part, time_part = [p.strip() for p in value.split("/")]
    h, m = (int(x) for x in time_part.split(":"))
    return WD_INDEX[day_part.upper()], dt.time(hour=h, minute=m)


def find_leg(rotation: list, origin_port: str, destination_port: str) -> Optional[dict]:
    """Walks the rotation (cyclically, in ROTATION_SEQ order) looking for the
    MOST DIRECT connection from `origin_port` to `destination_port` — i.e.
    the fewest intermediate calls (0 for a direct next-port hop, e.g. Laem
    Chabang -> Ho Chi Minh; 1+ for a transshipment-style hop, e.g.
    Bangkok -> Laem Chabang -> Ho Chi Minh). If `origin_port` appears more
    than once in the rotation (as it does here), the occurrence with the
    shortest path to `destination_port` wins, so a same-vessel direct call
    is never shadowed by a longer loop through another occurrence of the
    same origin port. Returns None if no connection is found within 3 hops.
    """
    n = len(rotation)
    origin_indices = [i for i, c in enumerate(rotation) if c["PORT_NM"].upper() == origin_port.upper()]

    # Try shortest hop distance first, across ALL occurrences of the origin,
    # so a direct (hop=1) match always beats an indirect (hop=2/3) one.
    for hop in range(1, 4):
        for i in origin_indices:
            call = rotation[i]
            nxt = rotation[(i + hop) % n]
            if nxt["PORT_NM"].upper() == destination_port.upper():
                via = [rotation[(i + h) % n]["PORT_NM"] for h in range(0, hop + 1)]
                dep_wd, dep_time = parse_wd_time(call["ETD"])
                arr_wd, arr_time = parse_wd_time(nxt["ETA"])
                return {
                    "origin": call["PORT_NM"],
                    "destination": nxt["PORT_NM"],
                    "via": via,
                    "dep_weekday": dep_wd,
                    "dep_time": dep_time,
                    "arr_weekday": arr_wd,
                    "arr_time": arr_time,
                }
    return None


def dates_in_months(year: int, months: list) -> tuple:
    first = dt.date(year, min(months), 1)
    last_month = max(months)
    if last_month == 12:
        last = dt.date(year, 12, 31)
    else:
        last = dt.date(year, last_month + 1, 1) - dt.timedelta(days=1)
    return first, last


def project_leg_dates(leg: dict, year: int, months: list) -> list:
    """Generates every occurrence of this weekly leg whose DEPARTURE date
    falls in the requested month(s)/year."""
    first, last = dates_in_months(year, months)
    day_delta = (leg["arr_weekday"] - leg["dep_weekday"]) % 7

    results = []
    cursor = first
    # walk forward to the first matching departure weekday on/after `first`
    while cursor.weekday() != leg["dep_weekday"]:
        cursor += dt.timedelta(days=1)
    while cursor <= last:
        dep_dt = dt.datetime.combine(cursor, leg["dep_time"])
        arr_dt = dt.datetime.combine(cursor + dt.timedelta(days=day_delta), leg["arr_time"])
        results.append((dep_dt, arr_dt))
        cursor += dt.timedelta(days=7)
    return results


def format_table(title: str, rows: list) -> str:
    lines = [title, "-" * len(title)]
    if not rows:
        lines.append("  (no sailings in the requested period)")
        return "\n".join(lines)
    lines.append(f"  {'Departure':<22}{'Arrival (Ho Chi Minh City)':<28}")
    for dep_dt, arr_dt in rows:
        lines.append(
            f"  {dep_dt.strftime('%a %d %b %Y %H:%M'):<22}"
            f"{arr_dt.strftime('%a %d %b %Y %H:%M'):<28}"
        )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    today = dt.date.today()
    parser.add_argument("--year", type=int, default=today.year, help="Year to project (default: current year)")
    parser.add_argument("--months", type=int, nargs="+", default=[9, 10],
                         help="Month numbers to include, e.g. --months 9 10 (default: 9 10)")
    parser.add_argument("--line-code", default=LINE_CD, help="PANCON service code (default: KST)")
    parser.add_argument("--csv", metavar="FILE", help="Also write the combined results to this CSV file")
    args = parser.parse_args()

    rotation, source = get_rotation(args.line_code)
    print(f"Service {args.line_code} rotation source: {source}")
    print(f"Rotation order: {' -> '.join(c['PORT_NM'] for c in rotation)} -> (repeats)\n")

    bkk_leg = find_leg(rotation, "BANGKOK", "HOCHIMINH CITY")
    lch_leg = find_leg(rotation, "LAEM CHABANG", "HOCHIMINH CITY")

    all_rows_for_csv = []

    if bkk_leg:
        rows = project_leg_dates(bkk_leg, args.year, args.months)
        print(format_table(
            f"BANGKOK -> HO CHI MINH CITY  (via {' -> '.join(bkk_leg['via'][1:-1]) or 'direct'}, "
            f"weekly, ETD {WEEKDAYS[bkk_leg['dep_weekday']]} {bkk_leg['dep_time']})",
            rows,
        ))
        all_rows_for_csv += [("Bangkok", "Ho Chi Minh City", d, a) for d, a in rows]
    else:
        print("Could not find a BANGKOK -> HOCHIMINH CITY connection in this rotation.")

    print()

    if lch_leg:
        rows = project_leg_dates(lch_leg, args.year, args.months)
        print(format_table(
            f"LAEM CHABANG -> HO CHI MINH CITY  (weekly, ETD {WEEKDAYS[lch_leg['dep_weekday']]} {lch_leg['dep_time']})",
            rows,
        ))
        all_rows_for_csv += [("Laem Chabang", "Ho Chi Minh City", d, a) for d, a in rows]
    else:
        print("Could not find a LAEM CHABANG -> HOCHIMINH CITY connection in this rotation.")

    print(
        "\nNote: these are projected dates based on PANCON's published WEEKLY rotation "
        "pattern (day-of-week + time), not a confirmed per-voyage booking schedule — "
        "PANCON does not expose vessel names or per-voyage dates without an e-Service "
        "member login. Please confirm the exact sailing with PANCON or your forwarder "
        "before booking cargo."
    )

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Origin", "Destination", "Departure (local)", "Arrival (local)"])
            for origin, destination, dep_dt, arr_dt in sorted(all_rows_for_csv, key=lambda r: r[2]):
                writer.writerow([origin, destination, dep_dt.strftime("%Y-%m-%d %H:%M"), arr_dt.strftime("%Y-%m-%d %H:%M")])
        print(f"\nSaved {len(all_rows_for_csv)} rows to {args.csv}")


if __name__ == "__main__":
    main()
