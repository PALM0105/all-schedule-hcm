#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dongjin_schedule.py
====================

Checks container vessel sailing schedules on the DONGJIN Shipping e-Service
"Point to Point Schedule" page:

    https://esvc.djship.co.kr/gnoss/CUP_HOM_3001.do

By default this script checks:
    Origins:      Bangkok (THBKK), Laem Chabang (THLCH)
    Destination:  Ho Chi Minh (VNSGN)
    Months:       September (09) and October (10) of the given year

It calls the same internal search endpoint the web page itself calls
(CUP_HOM_3001GS.do) with requests, so no browser is required.

NOTE: The site enforces a maximum 30-calendar-day search window per
request ("Search period should be shorter than 30 days"), so this script
automatically splits the requested date range into <=30-day chunks and
merges the results.

Usage
-----
    python3 dongjin_schedule.py
    python3 dongjin_schedule.py --year 2026 --months 9 10
    python3 dongjin_schedule.py --origins THBKK THLCH --dest VNSGN
    python3 dongjin_schedule.py --csv out.csv

Requires: requests  (pip install requests --break-system-packages)
"""

from __future__ import annotations

import argparse
import calendar
import csv
import datetime as dt
import sys
from dataclasses import dataclass, field, asdict
from typing import Iterable

import requests

BASE_URL = "https://esvc.djship.co.kr/gnoss"
SEARCH_URL = f"{BASE_URL}/CUP_HOM_3001GS.do"
PAGE_URL = f"{BASE_URL}/CUP_HOM_3001.do"

# Known port codes (UN/LOCODE-style codes used internally by DONGJIN's site).
# Add more here if you need other ports -- see find_port_code() below for
# how to look one up interactively.
KNOWN_PORTS = {
    "BANGKOK": "THBKK",
    "LAEM CHABANG": "THLCH",
    "HO CHI MINH": "VNSGN",
    "HOCHIMINH": "VNSGN",
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Referer": PAGE_URL,
    "Origin": "https://esvc.djship.co.kr",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


@dataclass
class Sailing:
    origin_query: str
    dest_query: str
    doc_closing: str
    doc_closing_day: str
    cargo_closing: str
    cargo_closing_day: str
    loading_port: str
    etd: str
    etd_day: str
    discharging_port: str
    eta: str
    eta_day: str
    lane: str
    vessel_voyage: str
    ocean_days: str
    total_days: str
    routing: str
    status: str


def daterange_chunks(start: dt.date, end: dt.date, max_span_days: int = 29) -> Iterable[tuple[dt.date, dt.date]]:
    """Split [start, end] into inclusive chunks whose span is <= max_span_days
    (i.e. at most max_span_days+1 calendar days), matching the site's
    "shorter than 30 days" limit (30 calendar days == 29 days span)."""
    cur = start
    one_day = dt.timedelta(days=1)
    step = dt.timedelta(days=max_span_days)
    while cur <= end:
        chunk_end = min(cur + step, end)
        yield cur, chunk_end
        cur = chunk_end + one_day


def months_to_range(year: int, months: list[int]) -> tuple[dt.date, dt.date]:
    """Given a list of months (e.g. [9, 10]), return (first_day, last_day)
    spanning from the 1st of the earliest month to the last day of the
    latest month in that year."""
    lo = min(months)
    hi = max(months)
    start = dt.date(year, lo, 1)
    last_day = calendar.monthrange(year, hi)[1]
    end = dt.date(year, hi, last_day)
    return start, end


def fetch_schedule_raw(
    session: requests.Session,
    por_cd: str,
    del_cd: str,
    frm_dt: dt.date,
    to_dt: dt.date,
    tran_tm: int = 20,
    timeout: int = 20,
) -> dict:
    """Call CUP_HOM_3001GS.do and return the parsed JSON response."""
    payload = {
        "f_cmd": "3",
        "por_cd": por_cd,
        "por_nde_cd": "",
        "del_cd": del_cd,
        "del_nde_cd": "",
        "frm_dt": frm_dt.strftime("%Y-%m-%d"),
        "to_dt": to_dt.strftime("%Y-%m-%d"),
        "ts_ind": "",
        "svc_flg": "C",   # C = Container
        "time_flg": "D",  # D = Departure, A = Arrival
        "tran_tm": str(tran_tm),
    }
    resp = session.post(SEARCH_URL, data=payload, headers=DEFAULT_HEADERS, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _leg_routing(item: dict) -> str:
    """Build a human readable routing string, e.g. 'Direct' or
    'via SINGAPORE -> HOCHIMINH'."""
    legs = []
    for prefix in ("n1st", "n2nd", "n3rd", "n4th"):
        loc = item.get(f"{prefix}LocNm") or item.get(f"{prefix}PodLocNm") or item.get(f"{prefix}PolLocNm")
        if loc:
            legs.append(loc.strip())
    # de-duplicate consecutive repeats while preserving order
    dedup = []
    for l in legs:
        if not dedup or dedup[-1] != l:
            dedup.append(l)
    if len(dedup) <= 1:
        return "Direct"
    return "via " + " -> ".join(dedup)


def parse_sailings(raw: dict, origin_label: str, dest_label: str) -> list[Sailing]:
    if raw.get("TRANS_RESULT_KEY") != "S":
        return []
    items = raw.get("list") or []
    out = []
    for it in items:
        out.append(
            Sailing(
                origin_query=origin_label,
                dest_query=dest_label,
                doc_closing=(it.get("dct") or "").split(" ")[0],
                doc_closing_day=it.get("dctDay", ""),
                cargo_closing=(it.get("cct") or "").split(" ")[0],
                cargo_closing_day=it.get("cctDay", ""),
                loading_port=(it.get("n1stLocNm") or "").strip(),
                etd=it.get("polEtdDt", ""),
                etd_day=it.get("polEtdDay", ""),
                discharging_port=(it.get("lstPodLocNm") or "").strip(),
                eta=it.get("podEtaDt", ""),
                eta_day=it.get("podEtaDay", ""),
                lane=it.get("n1stLaneNm", ""),
                vessel_voyage=it.get("n1stVslNm", ""),
                ocean_days=it.get("ocnTzDys", ""),
                total_days=it.get("ttlTzDys", ""),
                routing=_leg_routing(it),
                status=it.get("schStsCd", ""),
            )
        )
    return out


def resolve_port_code(name_or_code: str) -> str:
    """Accept either a raw port code (e.g. 'THBKK') or a known port name
    (e.g. 'Bangkok') and return the code to send to the API."""
    key = name_or_code.strip().upper()
    if key in KNOWN_PORTS.values():
        return key
    if key in KNOWN_PORTS:
        return KNOWN_PORTS[key]
    # Fall back: assume the caller already passed a valid site port code.
    return key


def check_schedules(
    origins: list[str],
    dest: str,
    year: int,
    months: list[int],
    tran_tm: int = 20,
) -> list[Sailing]:
    start, end = months_to_range(year, months)
    dest_code = resolve_port_code(dest)
    results: list[Sailing] = []
    seen = set()

    with requests.Session() as session:
        # Touch the main page first (not strictly required, but mirrors a
        # normal browser visit and picks up any session cookie DONGJIN sets).
        try:
            session.get(PAGE_URL, headers=DEFAULT_HEADERS, timeout=20)
        except requests.RequestException:
            pass

        for origin in origins:
            origin_code = resolve_port_code(origin)
            for chunk_start, chunk_end in daterange_chunks(start, end):
                raw = fetch_schedule_raw(session, origin_code, dest_code, chunk_start, chunk_end, tran_tm)
                sailings = parse_sailings(raw, origin_label=origin.upper(), dest_label=dest.upper())
                for s in sailings:
                    dedup_key = (s.origin_query, s.vessel_voyage, s.etd)
                    if dedup_key in seen:
                        continue
                    seen.add(dedup_key)
                    results.append(s)

    results.sort(key=lambda s: (s.origin_query, s.etd))
    return results


def print_table(sailings: list[Sailing]) -> None:
    if not sailings:
        print("No sailings found for the given criteria.")
        return

    headers = [
        "Origin", "Loading Port", "Doc Closing", "Cargo Closing",
        "ETD", "Discharging Port", "ETA", "Lane", "Vessel / Voyage",
        "Ocean(d)", "Total(d)", "Routing",
    ]
    rows = []
    for s in sailings:
        rows.append([
            s.origin_query,
            s.loading_port,
            f"{s.doc_closing} {s.doc_closing_day}".strip(),
            f"{s.cargo_closing} {s.cargo_closing_day}".strip(),
            f"{s.etd} {s.etd_day}".strip(),
            s.discharging_port,
            f"{s.eta} {s.eta_day}".strip(),
            s.lane,
            s.vessel_voyage,
            s.ocean_days,
            s.total_days,
            s.routing,
        ])

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt_row(cells):
        return " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))

    print(fmt_row(headers))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(fmt_row(row))
    print(f"\nTotal sailings: {len(sailings)}")


def write_csv(sailings: list[Sailing], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Origin", "Destination", "Loading Port", "Doc Closing", "Doc Closing Day",
            "Cargo Closing", "Cargo Closing Day", "ETD", "ETD Day",
            "Discharging Port", "ETA", "ETA Day", "Lane", "Vessel/Voyage",
            "Ocean Days", "Total Days", "Routing", "Status",
        ])
        for s in sailings:
            writer.writerow([
                s.origin_query, s.dest_query, s.loading_port,
                s.doc_closing, s.doc_closing_day,
                s.cargo_closing, s.cargo_closing_day,
                s.etd, s.etd_day,
                s.discharging_port, s.eta, s.eta_day,
                s.lane, s.vessel_voyage,
                s.ocean_days, s.total_days, s.routing, s.status,
            ])
    print(f"Saved {len(sailings)} rows to {path}")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Check DONGJIN Shipping point-to-point schedules.")
    p.add_argument("--origins", nargs="+", default=["Bangkok", "Laem Chabang"],
                   help="Origin port names or site codes (default: Bangkok, Laem Chabang)")
    p.add_argument("--dest", default="Ho Chi Minh",
                   help="Destination port name or site code (default: Ho Chi Minh / VNSGN)")
    p.add_argument("--year", type=int, default=2026, help="Year to search (default: 2026)")
    p.add_argument("--months", type=int, nargs="+", default=[9, 10],
                   help="Months to search, e.g. --months 9 10 (default: 9 10)")
    p.add_argument("--tran-tm", type=int, default=20, dest="tran_tm",
                   help="Max transit-time filter in days sent to the site (default: 20)")
    p.add_argument("--csv", default=None, help="Optional path to also save results as CSV")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    print(f"Checking DONGJIN schedules: {', '.join(args.origins)} -> {args.dest}  "
          f"| {args.year} months {args.months}\n")
    try:
        sailings = check_schedules(
            origins=args.origins,
            dest=args.dest,
            year=args.year,
            months=args.months,
            tran_tm=args.tran_tm,
        )
    except requests.RequestException as exc:
        print(f"Network error while contacting esvc.djship.co.kr: {exc}", file=sys.stderr)
        return 1

    print_table(sailings)

    if args.csv:
        write_csv(sailings, args.csv)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
