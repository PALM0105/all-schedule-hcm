#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kmtc_schedule.py
=================
Query KMTC's (Korea Marine Transport Co.) public "e-KMTC" schedule API
(https://www.ekmtc.com -> Schedule -> Corridor) directly, without a browser.

It reproduces the same request the e-KMTC website makes when you fill in
the "Schedule > Corridor" search form and click Search, so it is fast and
does not need Selenium/Playwright.

Default query (matches the request that was asked for):
    Departure : Bangkok (BKK)  and  Laem Chabang (LCH), Thailand
    Arrival   : Ho Chi Minh / Hochiminh (SGN), Vietnam
    Months    : September (9) and October (10) 2026

Usage
-----
    python kmtc_schedule.py
    python kmtc_schedule.py --pol BKK LCH --pod SGN --year 2026 --months 9 10
    python kmtc_schedule.py --pol-name "Shanghai" --pod-name "Laem Chabang"

Output
------
Prints a readable table to the console and also writes a CSV file
(kmtc_schedule_output.csv by default) with all sailings found, sorted by ETD.

Notes
-----
- This uses KMTC's own public JSON endpoints (the same ones the ekmtc.com
  front-end calls); no login/API key is required.
- KMTC schedules are for reference only -- always confirm with your local
  KMTC office/agent before booking, since sailings can change.
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import requests

BASE = "https://api.ekmtc.com"
PLACES_URL = f"{BASE}/common/commons/places"
SEARCH_URL = f"{BASE}/schedule/schedule/leg/search-schedule"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://www.ekmtc.com/index.html",
    "Origin": "https://www.ekmtc.com",
    "Accept": "application/json, text/plain, */*",
}

# Known port codes so the script works out of the box without an extra
# lookup call. lookup_place() below can resolve any other port name.
KNOWN_PORTS = {
    "bangkok": {"code": "BKK", "name": "Bangkok, Thailand (BKK)", "ctr": "TH"},
    "laem chabang": {"code": "LCH", "name": "Laem Chabang, Thailand (LCH)", "ctr": "TH"},
    "ho chi minh": {"code": "SGN", "name": "Hochiminh, Vietnam (SGN)", "ctr": "VN"},
    "hochiminh": {"code": "SGN", "name": "Hochiminh, Vietnam (SGN)", "ctr": "VN"},
}


@dataclass
class Sailing:
    pol_code: str
    pod_code: str
    vessel: str
    voyage: str
    etd: Optional[datetime]
    eta: Optional[datetime]
    pol_terminal: str
    pod_terminal: str
    transship: bool
    closing_time: Optional[datetime]
    route: str = ""

    @property
    def transit(self) -> str:
        if self.etd and self.eta:
            delta = self.eta - self.etd
            days = delta.days
            hours = delta.seconds // 3600
            return f"{days}d {hours}h"
        return "-"

    def as_row(self) -> list:
        return [
            self.pol_code,
            self.pod_code,
            self.etd.strftime("%Y-%m-%d %H:%M") if self.etd else "-",
            self.eta.strftime("%Y-%m-%d %H:%M") if self.eta else "-",
            self.transit,
            self.vessel,
            self.voyage,
            self.pol_terminal,
            self.pod_terminal,
            "T/S" if self.transship else "Direct",
            self.closing_time.strftime("%Y-%m-%d %H:%M") if self.closing_time else "-",
        ]


def lookup_place(name: str) -> dict:
    """Resolve a free-text port name (e.g. 'Laem Chabang') to KMTC's port
    code/country via the same autocomplete API the website uses."""
    key = name.strip().lower()
    if key in KNOWN_PORTS:
        return KNOWN_PORTS[key]

    resp = requests.get(PLACES_URL, params={"plcNm": name}, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    results = resp.json()
    if not results:
        # Retry without spaces, KMTC's DB sometimes stores names as one word
        # (e.g. "Hochiminh" instead of "Ho Chi Minh").
        resp = requests.get(
            PLACES_URL, params={"plcNm": name.replace(" ", "")}, headers=HEADERS, timeout=15
        )
        resp.raise_for_status()
        results = resp.json()
    if not results:
        raise ValueError(f"No KMTC port found matching '{name}'. Try a shorter/simpler name.")
    top = results[0]
    return {"code": top["plcCd"], "name": top["plcEnm"], "ctr": top["ctrCd"]}


def _parse_dt(date_str: str, time_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    time_str = time_str or "0000"
    try:
        return datetime.strptime(date_str + time_str, "%Y%m%d%H%M")
    except ValueError:
        return None


def search_schedule(
    pol_code: str,
    pol_name: str,
    pol_ctr: str,
    pod_code: str,
    pod_name: str,
    pod_ctr: str,
    year: int,
    month: int,
    direct_only: bool = False,
) -> list[Sailing]:
    """Call KMTC's corridor schedule search for one POL/POD/month and return
    a list of Sailing records."""
    params = {
        "startPlcCd": pol_code,
        "searchMonth": f"{month:02d}",
        "pointChangeYN": "",
        "bound": "O",
        "filterPolCd": "",
        "pointLength": "",
        "startPlcName": pol_name,
        "destPlcCd": pod_code,
        "searchYear": str(year),
        "filterYn": "N",
        "searchYN": "Y",
        "filterPodCd": "",
        "hiddestPlcCd": "",
        "startCtrCd": pol_ctr,
        "destCtrCd": pod_ctr,
        "polTrmlStr": "",
        "podTrmlStr": "",
        "rteCd": "",
        "filterTs": "N" if direct_only else "Y",
        "filterDirect": "Y",
        "filterTranMax": "0",
        "filterTranMin": "0",
        "hidstartPlcCd": "",
        "destPlcName": pod_name,
        "main": "N",
        "legIdx": "0",
        "vslType01": "01",
        "vslType03": "03",
        "unno": "",
        "commodityCd": "",
        "eiCatCd": "O",
        "calendarOrList": "C",
        "cpYn": "N",
        "promotionChk": "N",
        "vslCd": "",
        "voyNo": "",
    }

    resp = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    sailings = []
    for item in data.get("listSchedule", []):
        etd = _parse_dt(item.get("etd", ""), item.get("etdTm", ""))
        eta = _parse_dt(item.get("eta", ""), item.get("etaTm", ""))
        closing = _parse_dt(item.get("closeTime", "")[:8], item.get("closeTime", "")[8:12])
        sailings.append(
            Sailing(
                pol_code=item.get("pol", pol_code),
                pod_code=item.get("pod", pod_code),
                vessel=item.get("vslNm", ""),
                voyage=item.get("voyNo", ""),
                etd=etd,
                eta=eta,
                pol_terminal=item.get("otrmlNm", "").strip(),
                pod_terminal=item.get("itrmlNm", "").strip(),
                transship=(item.get("ts") == "Y"),
                closing_time=closing,
                route=item.get("rteCdNm", ""),
            )
        )
    return sailings


def collect(
    pol_list: list[dict],
    pod: dict,
    year: int,
    months: list[int],
    direct_only: bool = False,
) -> list[Sailing]:
    all_sailings: dict[tuple, Sailing] = {}
    for pol in pol_list:
        for month in months:
            try:
                results = search_schedule(
                    pol["code"], pol["name"], pol["ctr"],
                    pod["code"], pod["name"], pod["ctr"],
                    year, month, direct_only=direct_only,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  ! Failed to fetch {pol['code']} -> {pod['code']} "
                      f"for {year}-{month:02d}: {exc}", file=sys.stderr)
                continue
            for s in results:
                # Keep only sailings that actually depart within the
                # requested calendar month/year (KMTC pads results with a
                # few days from the neighbouring month).
                if s.etd and (s.etd.year, s.etd.month) == (year, month):
                    key = (s.pol_code, s.pod_code, s.vessel, s.voyage, s.etd)
                    all_sailings[key] = s
    return sorted(all_sailings.values(), key=lambda s: (s.pol_code, s.etd or datetime.max))


def print_table(sailings: list[Sailing]) -> None:
    headers = [
        "POL", "POD", "ETD", "ETA", "Transit", "Vessel", "Voyage",
        "POL Terminal", "POD Terminal", "Type", "Closing",
    ]
    rows = [s.as_row() for s in sailings]
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(str(cell)))

    def fmt_row(row):
        return " | ".join(str(c).ljust(widths[i]) for i, c in enumerate(row))

    print(fmt_row(headers))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(fmt_row(row))


def save_csv(sailings: list[Sailing], path: str) -> None:
    headers = [
        "POL", "POD", "ETD", "ETA", "Transit", "Vessel", "Voyage",
        "POL Terminal", "POD Terminal", "Type", "Closing",
    ]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for s in sailings:
            writer.writerow(s.as_row())


def main():
    parser = argparse.ArgumentParser(description="Look up KMTC container schedules.")
    parser.add_argument("--pol-name", nargs="*", default=["Bangkok", "Laem Chabang"],
                         help="Departure port name(s) (default: Bangkok, Laem Chabang)")
    parser.add_argument("--pod-name", default="Ho Chi Minh",
                         help="Arrival port name (default: Ho Chi Minh)")
    parser.add_argument("--year", type=int, default=2026, help="Year to search (default: 2026)")
    parser.add_argument("--months", type=int, nargs="+", default=[9, 10],
                         help="Months to search, e.g. --months 9 10 (default: 9 10)")
    parser.add_argument("--direct-only", action="store_true",
                         help="Only show direct sailings (no transshipment)")
    parser.add_argument("--csv", default="kmtc_schedule_output.csv",
                         help="Output CSV file path (default: kmtc_schedule_output.csv)")
    args = parser.parse_args()

    print("Resolving ports ...")
    pol_list = []
    for name in args.pol_name:
        place = lookup_place(name)
        pol_list.append(place)
        print(f"  {name!r} -> {place['name']} ({place['code']}, {place['ctr']})")
    pod = lookup_place(args.pod_name)
    print(f"  {args.pod_name!r} -> {pod['name']} ({pod['code']}, {pod['ctr']})")

    print(f"\nFetching KMTC schedules for {args.year}, months {args.months} ...")
    sailings = collect(pol_list, pod, args.year, args.months, direct_only=args.direct_only)

    if not sailings:
        print("No sailings found for this route/period.")
        return

    print(f"\nFound {len(sailings)} sailing(s):\n")
    print_table(sailings)

    save_csv(sailings, args.csv)
    print(f"\nSaved to {args.csv}")
    print("\nNote: schedules are for reference only -- please confirm with your "
          "local KMTC office/agent before booking, as sailings can change.")


if __name__ == "__main__":
    main()
