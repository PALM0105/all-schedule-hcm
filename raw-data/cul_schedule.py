#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cul_schedule.py

Fetch Point-to-Point vessel schedules from the CUL (Culines) website
(https://www.culines.com/en/site/schedule_ptp) for one or more
origin -> destination pairs and date ranges, using the same public
JSON endpoint the website's own search form calls.

No login/cookies are required - the endpoint is public.

Endpoints used (reverse-engineered from the site's JS):

1) Port name -> port code lookup (GET):
   https://www.culines.com/search/getCommon
       ?address_url=https://eservice.culines.com/gnoss/CommonCodeGS.do
       &f_cmd=122
       &loc_nm=<port name>
       &curl_type=get

2) Point-to-point schedule search (POST, form-urlencoded):
   https://www.culines.com/search/getCommon
   body:
       address_url = https://eservice.culines.com/gnoss/CUP_HOM_3001GS.do
       curl_type   = post
       f_cmd       = 3
       por_cd      = <origin port code>
       del_cd      = <destination port code>
       frm_dt      = <YYYY-MM-DD>
       to_dt       = <YYYY-MM-DD>
       ts_ind      = ''  (All)  |  'D' (Direct only)  |  'T' (Transship only)

Usage examples
--------------
    # Default: Bangkok & Laem Chabang -> Ho Chi Minh City, Sep-Oct 2026
    python3 cul_schedule.py

    # Custom route / date range
    python3 cul_schedule.py --origin "Bangkok" --dest "Shanghai" \
        --from 2026-09-01 --to 2026-09-30

    # Save to CSV as well
    python3 cul_schedule.py --csv cul_schedule.csv
"""

import argparse
import csv
import sys
from datetime import datetime

import requests

BASE_URL = "https://www.culines.com/search/getCommon"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.culines.com/en/site/schedule_ptp",
}

# Known port codes (looked up once via the site's own autocomplete API,
# hardcoded here so the script works even if the lookup call is
# unavailable). lookup_port() below can resolve any other port name.
KNOWN_PORTS = {
    "BANGKOK": "THBKK",
    "LAEM CHABANG": "THLCH",
    "HO CHI MINH CITY": "VNSGN",
}


def lookup_port(name: str) -> dict:
    """Resolve a free-text port/city name to CUL's internal port code.

    Returns a dict like {"locCd": "THBKK", "locNm": "BANGKOK",
    "locAndCntNm": "BANGKOK, THAILAND"} or raises ValueError if nothing
    matched.
    """
    params = {
        "address_url": "https://eservice.culines.com/gnoss/CommonCodeGS.do",
        "f_cmd": 122,
        "loc_nm": name,
        "curl_type": "get",
    }
    r = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not data.get("list"):
        raise ValueError(f"No port match found for '{name}'")
    best = data["list"][0]
    return {
        "locCd": best["locCd"],
        "locNm": best["locNm"],
        "locAndCntNm": best["locAndCntNm"],
    }


def resolve_port_code(name: str) -> str:
    """Use the hardcoded table first, fall back to a live lookup."""
    key = name.strip().upper()
    if key in KNOWN_PORTS:
        return KNOWN_PORTS[key]
    return lookup_port(name)["locCd"]


def fetch_schedule(por_cd: str, del_cd: str, frm_dt: str, to_dt: str,
                    ts_ind: str = "") -> list:
    """Call the point-to-point schedule search endpoint.

    ts_ind: '' = All, 'D' = Direct only, 'T' = Transship only
    """
    payload = {
        "address_url": "https://eservice.culines.com/gnoss/CUP_HOM_3001GS.do",
        "curl_type": "post",
        "f_cmd": 3,
        "por_cd": por_cd,
        "del_cd": del_cd,
        "frm_dt": frm_dt,
        "to_dt": to_dt,
        "ts_ind": ts_ind,
    }
    headers = dict(HEADERS)
    headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
    r = requests.post(BASE_URL, data=payload, headers=headers, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("TRANS_RESULT_KEY") != "S":
        raise RuntimeError(f"CUL API returned an error: {data}")
    return data.get("list", [])


def simplify_sailing(item: dict) -> dict:
    """Pull out the human-relevant fields from one raw result row."""
    return {
        "cargo_closing": item.get("cct", "").replace(".0", ""),
        "loading_port": item.get("n1stLocNm", ""),
        "departure_date": item.get("polEtdDt", ""),
        "discharging_port": item.get("lstPodLocNm", ""),
        "arrival_date": item.get("lstPodEtaDt", ""),
        "lane": item.get("n1stLaneNm", ""),
        "vessel_voyage": item.get("n1stVslNm", ""),
        "consortium_voyage": item.get("consVoyNr", ""),
        "transit_days": item.get("ttlTzDys", ""),
        "routing": item.get("n2ndLocNm", "") or "Direct",
    }


def print_table(rows: list, title: str) -> None:
    print(f"\n=== {title} ({len(rows)} sailings) ===")
    if not rows:
        print("  (no sailings found in this date range)")
        return
    rows = sorted(rows, key=lambda x: x["departure_date"])
    headers = [
        ("departure_date", "Departure"),
        ("arrival_date", "Arrival"),
        ("transit_days", "Transit(d)"),
        ("loading_port", "Loading Port"),
        ("discharging_port", "Discharging Port"),
        ("vessel_voyage", "Vessel / Voyage"),
        ("consortium_voyage", "Consortium Voy."),
        ("routing", "Routing"),
        ("cargo_closing", "Cargo Closing"),
    ]
    widths = {k: max(len(h), *(len(str(r.get(k, ""))) for r in rows)) for k, h in headers}
    line = " | ".join(h.ljust(widths[k]) for k, h in headers)
    print(line)
    print("-" * len(line))
    for r in rows:
        print(" | ".join(str(r.get(k, "")).ljust(widths[k]) for k, h in headers))


def main():
    parser = argparse.ArgumentParser(description="Look up CUL (Culines) point-to-point vessel schedules.")
    parser.add_argument("--origins", nargs="+", default=["Bangkok", "Laem Chabang"],
                         help="One or more origin port names (default: Bangkok, Laem Chabang)")
    parser.add_argument("--dest", default="Ho Chi Minh City",
                         help="Destination port name (default: Ho Chi Minh City)")
    parser.add_argument("--from", dest="frm_dt", default=None,
                         help="Start date YYYY-MM-DD (default: 1st of current month)")
    parser.add_argument("--to", dest="to_dt", default=None,
                         help="End date YYYY-MM-DD (default: last day of next month, "
                              "i.e. covers this month + next month)")
    parser.add_argument("--ts-ind", choices=["", "D", "T"], default="",
                         help="'' = All (default), 'D' = Direct only, 'T' = Transship only")
    parser.add_argument("--csv", default=None, help="Optional path to save all results as CSV")
    args = parser.parse_args()

    # Default date range: months 9 and 10 (September & October) of the
    # current year, matching the user's request. Override with --from/--to.
    today = datetime.now()
    frm_dt = args.frm_dt or f"{today.year}-09-01"
    to_dt = args.to_dt or f"{today.year}-10-31"

    print(f"Date range: {frm_dt} -> {to_dt}   |   Destination: {args.dest}   |   Filter: "
          f"{{'':'All','D':'Direct only','T':'Transship only'}}[{args.ts_ind!r}]")

    dest_code = resolve_port_code(args.dest)
    print(f"Resolved destination '{args.dest}' -> {dest_code}")

    all_rows = []
    csv_rows = []

    for origin in args.origins:
        try:
            origin_code = resolve_port_code(origin)
        except ValueError as e:
            print(f"[!] {e}", file=sys.stderr)
            continue
        print(f"Resolved origin '{origin}' -> {origin_code}")

        try:
            raw = fetch_schedule(origin_code, dest_code, frm_dt, to_dt, args.ts_ind)
        except Exception as e:
            print(f"[!] Failed to fetch schedule for {origin} -> {args.dest}: {e}", file=sys.stderr)
            continue

        rows = [simplify_sailing(item) for item in raw]
        for r in rows:
            r["origin_query"] = origin
        print_table(rows, f"{origin} -> {args.dest}")
        all_rows.extend(rows)
        csv_rows.extend(rows)

    if args.csv and csv_rows:
        fieldnames = [
            "origin_query", "loading_port", "discharging_port",
            "departure_date", "arrival_date", "transit_days",
            "vessel_voyage", "consortium_voyage", "lane", "routing",
            "cargo_closing",
        ]
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"\nSaved {len(csv_rows)} sailings to {args.csv}")

    print(f"\nTotal sailings found across all origins: {len(all_rows)}")
    print("\nNote: CUL states these schedules are estimates and subject to change - "
          "please confirm with your local CUL office/agent before booking.")


if __name__ == "__main__":
    main()
