#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_hcm_schedule.py
=====================

Aggregates the **Bangkok / Laem Chabang -> Ho Chi Minh City** sailing schedule from the carrier
scripts in the raw-data/ folder into a single dataset, and builds a sailing calendar and an
easy-to-read HTML dashboard (one self-contained file) in the same format as the
Laem Chabang -> Shanghai dashboard.

Sources
-------
    Pulled live:
      raw-data/sitc_api_schedule.py    -> SITC       (public JSON API)
      raw-data/ckline_schedule.py      -> CK Line    (public JSON API)
      raw-data/cul_schedule.py         -> CU Lines   (public JSON API)
      raw-data/dongjin_schedule (1).py -> Dongjin    (public JSON API)
      raw-data/jj_shipping_schedule.py -> SJJ        (NVOCC JJ Shipping website)
    Static (not a live pull):
      raw-data/generate_hal_schedule.py -> HAL (Heung-A): rows extracted from ebiz.heungaline.com
    Read from saved files (the site blocks scripted access, so the rows were collected through a normal browser):
      KMTC/*.txt -> KMTC  (a live pull is tried first and used automatically if it ever works)
    Blocked from this network (reported as "blocked" on the dashboard):
      Namsung (Akamai "Access Denied"), HMM (connection reset)

Notes
-----
* es.ckline.co.kr also lists other carriers' vessels for reference only. Only the vessels CK Line can
  really book (its own + chartered fleet, www.ckline.co.kr/en/service/ship/) are kept for CK Line.
* Duplicate sailings (same vessel, same origin port, ETD within 1 day) are merged into one entry that
  lists every carrier able to book it, with each one's voyage / ETD / ETA / cut-off.

Install
-------
    pip install requests pandas openpyxl beautifulsoup4 pillow

Usage
-----
    python build_hcm_schedule.py
    python build_hcm_schedule.py --start 2026-10-01 --end 2026-12-31
    python build_hcm_schedule.py --only sitc,ckline
    python build_hcm_schedule.py --skip sjj
    python build_hcm_schedule.py --offline      # no network, reuse output/_cache.json
    python build_hcm_schedule.py --serve        # local helper: the Refresh button pulls live data
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import html
import io
import json
import math
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
INPUT_DIR = HERE / "raw-data"       # folder holding the carrier scripts
OUT_DIR = HERE / "output"
CACHE_FILE = OUT_DIR / "_cache.json"
PAGES_FILE = HERE / "dashboard.html"      # copy of the dashboard published through GitHub Pages
PAGE_NAME = "hcm_schedule_dashboard.html"
DEFAULT_PORT = 8792               # port for --serve

LANE = "Bangkok / Laem Chabang  \u2192  Ho Chi Minh City"
POD_NAME = "Ho Chi Minh City"
ORIGINS = ("Bangkok", "Laem Chabang")

# Colour and order of each source (used on the dashboard + calendar)
SOURCE_META = {
    "SITC":     {"color": "#f97316", "label": "SITC"},              # orange
    "KMTC":     {"color": "#38bdf8", "label": "KMTC"},              # light blue
    "HAL":      {"color": "#2563eb", "label": "HAL (Heung-A)"},     # blue
    "CK Line":  {"color": "#84cc16", "label": "CK Line"},           # lime
    "CU Lines": {"color": "#14b8a6", "label": "CU Lines"},          # teal
    "Dongjin":  {"color": "#e11d48", "label": "Dongjin Shipping"},  # rose
    "SJJ":      {"color": "#7c3aed", "label": "SJJ"},               # violet
    "Namsung":  {"color": "#a16207", "label": "Namsung"},           # brown
    "HMM":      {"color": "#eab308", "label": "HMM"},               # amber
}
DEFAULT_COLOR = "#64748b"


def _fg(hex_color: str) -> str:
    """Pick a text colour (white/black) that is readable on a hex_color background"""
    h = (hex_color or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "#fff"
    return "#1a1a1a" if (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.62 else "#fff"


# --------------------------------------------------------------------------- #
#  helpers                                                                     #
# --------------------------------------------------------------------------- #
def norm_vessel(name: str | None) -> str:
    """Normalise vessel names so they can be compared: upper case / strip special characters / collapse spaces"""
    if not name:
        return ""
    s = str(name).upper()
    s = s.replace("M.V.", " ").replace("MV ", " ").replace("M/V", " ")
    s = re.sub(r"[^A-Z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_MONTH_NAMES = ["", "January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"]
MONTHS = {name.lower(): i for i, name in enumerate(_MONTH_NAMES)}
MONTHS.update({name.lower()[:3]: i for i, name in enumerate(_MONTH_NAMES) if name})


def parse_dt(value) -> tuple[str | None, dt.date | None]:
    """
    Accepts date/time values in the various formats emitted by the scrapers and returns
        (text 'YYYY-MM-DD [HH:MM]', datetime.date or None)
    Supported:
        2026-09-14 05:00 / 2026-09-14
        2026/09/14 05:00 / 2026/09/14
        08-September-2026
        Mon 14 September 2026  /  14 September 2026
        2026-09-14T05:00:00+03:00
    """
    if value is None:
        return None, None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "-", "n/a"}:
        return None, None

    s = s.replace("T", " ")
    # ISO offset such as +03:00 at the end
    s = re.sub(r"([+\-]\d{2}:?\d{2})$", "", s).strip()
    # strip a leading weekday name, e.g. 'Monday, 14-SEP-2026' (CMA CGM format)
    s = re.sub(r"^[A-Za-z]{3,},\s*", "", s).strip()

    # 1) YYYY-MM-DD or YYYY/MM/DD (optionally with a time)
    m = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?:[ ](\d{1,2}):(\d{2}))?", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            date = dt.date(y, mo, d)
        except ValueError:
            return s, None
        if m.group(4) is not None:
            return f"{date.isoformat()} {int(m.group(4)):02d}:{m.group(5)}", date
        return date.isoformat(), date

    # 1b) YYYY.Mon.DD [HH:MM]  (KMTC export format, e.g. '2026.Nov.15 23:00')
    m = re.match(r"(\d{4})\.([A-Za-z]{3,})\.(\d{1,2})(?:[ ](\d{1,2}):(\d{2}))?", s)
    if m and m.group(2).lower() in MONTHS:
        y, mo, d = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
        try:
            date = dt.date(y, mo, d)
        except ValueError:
            return s, None
        if m.group(4) is not None:
            return f"{date.isoformat()} {int(m.group(4)):02d}:{m.group(5)}", date
        return date.isoformat(), date

    # 1c) DD/MM/YYYY  (RCL format)
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:[ ](\d{1,2}):(\d{2}))?", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            date = dt.date(y, mo, d)
        except ValueError:
            return s, None
        if m.group(4) is not None:
            return f"{date.isoformat()} {int(m.group(4)):02d}:{m.group(5)}", date
        return date.isoformat(), date

    # 2) DD-Month-YYYY  /  DD-SEP-2026
    m = re.match(r"(\d{1,2})[-\s]([A-Za-z]+)[-\s](\d{4})", s)
    if m and m.group(2).lower() in MONTHS:
        d, mo, y = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
        try:
            date = dt.date(y, mo, d)
            return date.isoformat(), date
        except ValueError:
            return s, None

    # 3) [Ddd] DD Month YYYY  (SJJ / JJ Shipping format)
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", s)
    if m and m.group(2).lower() in MONTHS:
        d, mo, y = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3))
        try:
            date = dt.date(y, mo, d)
            return date.isoformat(), date
        except ValueError:
            return s, None

    return s, None


def to_float(value) -> float | None:
    if value is None:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(m.group()) if m else None


def clean(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none"}:
        return None
    return s


class SourceBlocked(RuntimeError):
    """Raised when a source blocks access at the IP/region level (e.g. Akamai)"""


def http_retry(call, *, tries: int = 3, delay: float = 2.0):
    """
    Calls an HTTP function, retrying up to `tries` times (with an increasing delay)
    - On a 401/403 carrying Akamai's "Access Denied" page, stop retrying immediately
      and raise SourceBlocked (retrying would be blocked the same way)
    """
    import requests

    last = None
    for attempt in range(1, tries + 1):
        try:
            return call()
        except requests.HTTPError as exc:
            last = exc
            resp = getattr(exc, "response", None)
            code = getattr(resp, "status_code", None)
            body = (getattr(resp, "text", "") or "")[:2000]
            if code in (401, 403) and ("Access Denied" in body or "edgesuite" in body
                                       or "denied" in body.lower()):
                raise SourceBlocked(
                    f"Blocked at the IP/region level (HTTP {code} – Akamai Access Denied). "
                    f"Try running this script from another machine/network (e.g. an office network in Thailand) "
                    f"or through a VPN, and this source should work again"
                ) from exc
            time.sleep(delay * attempt)
        except requests.RequestException as exc:
            last = exc
            time.sleep(delay * attempt)
    raise last if last else RuntimeError("http_retry: unknown failure")


# --------------------------------------------------------------------------- #
#  Each data source: fetch + convert to the common record format                #
#  Returns list[dict] with keys: source, carrier, service, vessel, voyage,       #
#        etd, eta, etd_date, pol, pod, pol_terminal, pod_terminal,             #
#        transit_days, direct_or_ts, doc_cutoff, cy_cutoff, vgm_cutoff         #
# --------------------------------------------------------------------------- #
def _rec(source, **kw) -> dict:
    etd_txt, etd_date = parse_dt(kw.get("etd"))
    eta_txt, _ = parse_dt(kw.get("eta"))
    doc_txt, _ = parse_dt(kw.get("doc_cutoff"))
    cy_txt, _ = parse_dt(kw.get("cy_cutoff"))
    vgm_txt, _ = parse_dt(kw.get("vgm_cutoff"))
    ts_etd_txt, _ = parse_dt(kw.get("ts_etd"))
    vessel = clean(kw.get("vessel")) or ""
    return {
        "source": source,
        "carrier": kw.get("carrier") or source,
        "service": clean(kw.get("service")),
        "vessel": vessel,
        "vessel_key": norm_vessel(vessel),
        "voyage": clean(kw.get("voyage")),
        "etd": etd_txt,
        "eta": eta_txt,
        "etd_date": etd_date.isoformat() if etd_date else None,
        "pol": clean(kw.get("pol")),
        "pod": clean(kw.get("pod")),
        "pol_terminal": clean(kw.get("pol_terminal")),
        "pod_terminal": clean(kw.get("pod_terminal")),
        "transit_days": to_float(kw.get("transit_days")),
        "direct_or_ts": clean(kw.get("direct_or_ts")) or "Direct",
        "doc_cutoff": doc_txt,
        "cy_cutoff": cy_txt,
        "vgm_cutoff": vgm_txt,
        "ts_place": clean(kw.get("ts_place")),     # transshipment port, when the source lists one
        "ts_etd": ts_etd_txt,
    }


def _load_module(name: str, filename: str):
    """Import one of the carrier scripts in raw-data/ by file name (some names contain spaces)."""
    import importlib.util
    path = INPUT_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod            # @dataclass looks the module up in sys.modules
    spec.loader.exec_module(mod)
    return mod


def _ymd_hm(d, t=None):
    """'20261005' + '1430' -> '2026-10-05 14:30' (time optional)"""
    d = clean(d)
    if not d or len(d) < 8 or not d[:8].isdigit():
        return None
    s = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    t = clean(t)
    if t and len(t) >= 4 and t[:4].isdigit():
        s += f" {t[:2]}:{t[2:4]}"
    return s


def _days_between(etd, eta):
    """Transit time in days (1 decimal) from two 'YYYY-MM-DD [HH:MM]' texts, or None."""
    a, _ = parse_dt(etd)
    b, _ = parse_dt(eta)
    try:
        x, y = dt.datetime.fromisoformat(a), dt.datetime.fromisoformat(b)
    except (TypeError, ValueError):
        return None
    days = (y - x).total_seconds() / 86400
    return round(days, 1) if days >= 0 else None


def _months_between(start: dt.date, end: dt.date) -> list[tuple[int, int]]:
    out, cur = [], dt.date(start.year, start.month, 1)
    while cur <= end:
        out.append((cur.year, cur.month))
        cur = dt.date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)
    return out


def _in_range(rec: dict, start: dt.date, end: dt.date) -> bool:
    d = rec.get("etd_date")
    return bool(d) and start.isoformat() <= d <= end.isoformat()


def _name_voy(text):
    """'JARU BHUM 2634N' -> ('JARU BHUM', '2634N'); returns voyage=None when there is no trailing voyage number"""
    if not text:
        return None, None
    parts = str(text).split()
    if len(parts) > 1 and re.match(r"^\d+[A-Za-z]?$", parts[-1]):
        return " ".join(parts[:-1]), parts[-1]
    return str(text), None


def fetch_sitc(start: dt.date, end: dt.date) -> list[dict]:
    m = _load_module("sitc_api_schedule", "sitc_api_schedule.py")
    out = []
    for pol in ("BANGKOK", "LAEM CHABANG"):
        rows = http_retry(lambda pol=pol: m.fetch_schedule(
            pol, "HO CHI MINH", start.isoformat(), end.isoformat()))
        for r in rows:
            out.append(_rec(
                "SITC", carrier="SITC",
                service=r.get("serviceLineCode"),
                vessel=r.get("vesselName"), voyage=r.get("voyageNo"),
                pol=r.get("polName"), pod=r.get("podName"),
                pol_terminal=r.get("polTerminalName"), pod_terminal=r.get("podTerminalName"),
                etd=r.get("weekEtd") or r.get("etd"),
                eta=r.get("weekEta") or r.get("eta"),
                transit_days=r.get("underway"),
            ))
    return out


# Vessels CK Line can really book: its own fleet + chartered vessels (www.ckline.co.kr/en/service/ship/,
# checked 2026-09-14). es.ckline.co.kr also shows other carriers' vessels for reference only.
CK_LINE_FLEET = {
    "SKY AURORA", "SKY CHALLENGE", "SKY FLOWER", "SKY GLORY", "SKY HOPE", "SKY ORION", "SKY VICTORIA",
    "SKY SUNSHINE", "SKY WIND", "SKY RAINBOW", "SKY TIARA", "SKY IRIS", "SKY MOON", "SKY JADE",
    "SKY PRIDE", "SKY PEACE",
    "JI PENG", "KAI PING", "PACIFIC MONACO", "ATLANTIC BRIDGE", "SUNWIN", "VICTORY STAR", "PROVIDENT",
}


def fetch_ckline(start: dt.date, end: dt.date) -> list[dict]:
    m = _load_module("ckline_schedule", "ckline_schedule.py")
    out = []
    for origin, info in m.ORIGIN_PORTS.items():
        for year, month in _months_between(start, end):
            rows = http_retry(lambda info=info, year=year, month=month: m.fetch_schedule(
                info["code"], info["nation"], year, month))
            for raw in rows:
                vessel = (raw.get("VSLDES") or "").strip()
                if vessel.upper() not in CK_LINE_FLEET:
                    continue
                etd = _ymd_hm(raw.get("OUTETD1"), raw.get("OUTEHD1"))
                eta = _ymd_hm(raw.get("OUTETA1") or raw.get("OUTETA1_F"),
                              raw.get("OUTEHA1") or raw.get("OUTEHA1_F"))
                is_ts = bool(raw.get("OUTVVD2"))
                out.append(_rec(
                    "CK Line", carrier="CK Line",
                    service=raw.get("OUTROT1"),
                    vessel=vessel, voyage=raw.get("OUTVVD1"),
                    pol=origin, pod=POD_NAME,
                    pol_terminal=raw.get("OUTLTMLDES"), pod_terminal=raw.get("OUTDTML1DES"),
                    etd=etd, eta=eta, transit_days=_days_between(etd, eta),
                    direct_or_ts="T/S" if is_ts else "Direct",
                    ts_place=raw.get("OUTPOL2") if is_ts else None,
                ))
    return out


def fetch_culines(start: dt.date, end: dt.date) -> list[dict]:
    m = _load_module("cul_schedule", "cul_schedule.py")
    dest = m.resolve_port_code(POD_NAME)
    out = []
    for origin in ORIGINS:
        code = m.resolve_port_code(origin)
        rows = http_retry(lambda code=code: m.fetch_schedule(
            code, dest, start.isoformat(), end.isoformat()))
        for it in rows:
            vessel, voyage = _name_voy(it.get("n1stVslNm"))
            ts_place = clean(it.get("n2ndLocNm"))
            out.append(_rec(
                "CU Lines", carrier="CU Lines",
                service=it.get("n1stLaneNm"),
                vessel=vessel, voyage=voyage or it.get("consVoyNr"),
                pol=it.get("n1stLocNm") or origin, pod=it.get("lstPodLocNm") or POD_NAME,
                etd=it.get("polEtdDt"), eta=it.get("lstPodEtaDt"),
                transit_days=it.get("ttlTzDys"),
                direct_or_ts="T/S" if ts_place else "Direct", ts_place=ts_place,
                cy_cutoff=(it.get("cct") or "").replace(".0", ""),
            ))
    return out


def fetch_dongjin(start: dt.date, end: dt.date) -> list[dict]:
    m = _load_module("dongjin_schedule", "dongjin_schedule (1).py")
    last_month = end.month if end.year == start.year else 12
    months = list(range(start.month, last_month + 1))
    sailings = http_retry(lambda: m.check_schedules(
        list(ORIGINS), "Ho Chi Minh", start.year, months))
    out = []
    for s in sailings:
        vessel, voyage = _name_voy(s.vessel_voyage)
        routing = (s.routing or "").strip()
        out.append(_rec(
            "Dongjin", carrier="Dongjin",
            service=s.lane,
            vessel=vessel, voyage=voyage,
            pol=s.loading_port or s.origin_query, pod=s.discharging_port or POD_NAME,
            etd=s.etd, eta=s.eta, transit_days=_days_between(s.etd, s.eta),
            direct_or_ts="Direct" if routing.endswith("Direct") or not routing else "T/S",
            doc_cutoff=s.doc_closing, cy_cutoff=s.cargo_closing,
        ))
    return out


def fetch_hal(start: dt.date, end: dt.date) -> list[dict]:
    """HAL (Heung-A): rows extracted from ebiz.heungaline.com and kept in generate_hal_schedule.py
    (the site blocks scripted access). Not a live pull -- see SOURCE_NOTES."""
    import contextlib
    path = INPUT_DIR / "generate_hal_schedule.py"
    if not path.exists():
        raise SourceBlocked(f"{path.name} not found in {INPUT_DIR.name}/ -- HAL rows are read from it")
    with contextlib.redirect_stdout(io.StringIO()):          # the script prints + writes an xlsx when imported
        mod = _load_module("generate_hal_schedule", "generate_hal_schedule.py")
    out = []
    for origin, rows in (("Bangkok", getattr(mod, "bangkok_rows", [])),
                         ("Laem Chabang", getattr(mod, "laem_rows", []))):
        for r in rows:
            # [Service, Vessel, Voyage, POL - terminal, POD - terminal, ETD, ETA, Transit, DOCU closing, CNTR closing, Status]
            def term(x):
                return x.split(" - ", 1)[1] if x and " - " in x else x
            out.append(_rec(
                "HAL", carrier="HAL",
                service=r[0], vessel=r[1], voyage=r[2],
                pol=origin, pod=POD_NAME,
                pol_terminal=term(r[3]), pod_terminal=term(r[4]),
                etd=r[5], eta=r[6], transit_days=_days_between(r[5], r[6]),
                doc_cutoff=r[8] if r[8] != "-" else None,
                cy_cutoff=r[9] if r[9] != "-" else None,
            ))
    return out


def fetch_jj(start: dt.date, end: dt.date) -> list[dict]:
    m = _load_module("jj_shipping_schedule", "jj_shipping_schedule.py")
    out, seen = [], set()
    for origin, page_code in m.ROUTES.items():
        cursor = start
        while cursor <= end:
            page = http_retry(lambda page_code=page_code, cursor=cursor: m.fetch_schedule(
                page_code, cursor, weeks=3, arrival=0))
            for r in m.parse_cards(page, origin):
                if "Ho Chi Minh" not in (r.get("destination_port") or "") or not r.get("departure_date"):
                    continue
                key = (origin, r["vessel"], r["voyage"], r["departure_date"])
                if key in seen:
                    continue
                seen.add(key)
                pol_t = (r.get("origin_port") or "").split(":", 1)[-1].strip() or None
                out.append(_rec(
                    "SJJ", carrier="SJJ",
                    service=r.get("code"),
                    vessel=r["vessel"], voyage=r["voyage"],
                    pol=origin, pod=POD_NAME, pol_terminal=pol_t,
                    etd=r["departure_date"].isoformat(),
                    eta=r["arrival_date"].isoformat() if r.get("arrival_date") else None,
                    transit_days=r.get("transit_days"),
                    doc_cutoff=r.get("closing"),
                ))
            time.sleep(0.4)
            cursor += dt.timedelta(days=14)
    return out


KMTC_DIR = HERE / "KMTC"
NAMSUNG_DIR = HERE / "NAMSUNG"
HMM_DIR = HERE / "HMM"


def _kmtc_ts(s: str) -> str | None:
    """'202610141830' -> '2026-10-14 18:30'; '20261209240000' (HHMMSS, 24:00 = end of day) -> '2026-12-09 24:00'"""
    s = (s or "").strip()
    if len(s) < 12 or not s.isdigit():
        return None
    return f"{s[:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}"


def _kmtc_from_files() -> list[dict]:
    """
    KMTC rows saved in KMTC/*.txt. ekmtc.com blocks scripted access from this network, so the rows were
    collected through a normal Chrome browser (the same api.ekmtc.com call the website makes).
    Columns: origin(B/L)|vessel|voyage|ETD|ETA|origin terminal|destination terminal|closing|service
    """
    out = []
    for f in sorted(KMTC_DIR.glob("*.txt")) if KMTC_DIR.is_dir() else []:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            p = line.split("|")
            if len(p) < 9:
                continue
            o, vessel, voyage, etd_s, eta_s, pol_t, pod_t, closing, svc = (x.strip() for x in p[:9])
            etd, eta = _kmtc_ts(etd_s), _kmtc_ts(eta_s)
            out.append(_rec(
                "KMTC", carrier="KMTC", service=svc, vessel=vessel, voyage=voyage,
                pol="Bangkok" if o == "B" else "Laem Chabang", pod=POD_NAME,
                pol_terminal=pol_t, pod_terminal=pod_t,
                etd=etd, eta=eta, transit_days=_days_between(etd, eta),
                cy_cutoff=_kmtc_ts(closing),
            ))
    return out


def fetch_kmtc(start: dt.date, end: dt.date) -> list[dict]:
    try:
        return _kmtc_live(start, end)
    except SourceBlocked:
        recs = _kmtc_from_files()
        if recs:
            return recs
        raise


def _kmtc_live(start: dt.date, end: dt.date) -> list[dict]:
    m = _load_module("kmtc_schedule", "kmtc_schedule.py")
    pod = m.KNOWN_PORTS["ho chi minh"]
    out = []
    for origin in ORIGINS:
        pol = m.KNOWN_PORTS[origin.lower()]
        for year, month in _months_between(start, end):
            sailings = http_retry(lambda pol=pol, year=year, month=month: m.search_schedule(
                pol["code"], pol["name"], pol["ctr"], pod["code"], pod["name"], pod["ctr"], year, month))
            for s in sailings:
                etd = s.etd.strftime("%Y-%m-%d %H:%M") if s.etd else None
                eta = s.eta.strftime("%Y-%m-%d %H:%M") if s.eta else None
                out.append(_rec(
                    "KMTC", carrier="KMTC", service=s.route or None,
                    vessel=s.vessel, voyage=s.voyage, pol=origin, pod=POD_NAME,
                    pol_terminal=s.pol_terminal, pod_terminal=s.pod_terminal,
                    etd=etd, eta=eta, transit_days=_days_between(etd, eta),
                    direct_or_ts="T/S" if s.transship else "Direct",
                    cy_cutoff=s.closing_time.strftime("%Y-%m-%d %H:%M") if s.closing_time else None,
                ))
    return out


def _namsung_live(start: dt.date, end: dt.date) -> list[dict]:
    import requests
    m = _load_module("namsung_schedule", "namsung_schedule.py")
    session = requests.Session()
    out = []
    for origin in ORIGINS:
        info = m.DEPARTURE_PORTS[origin.upper()]
        for year, month in _months_between(start, end):
            rows = http_retry(lambda info=info, year=year, month=month: m.fetch_schedule(
                session, info["code"], info["desc"], m.ARRIVAL_PORT["code"], m.ARRIVAL_PORT["desc"],
                f"{year}{month:02d}"))
            for r in rows:
                ts = (r.get("TS_MIN") or "").strip()
                out.append(_rec(
                    "Namsung", carrier="Namsung",
                    vessel=r.get("VSL_NAME"), voyage=r.get("VSLVOY"),
                    pol=origin, pod=POD_NAME,
                    pol_terminal=r.get("GRMLTMLD1"), pod_terminal=r.get("GRMDTMLD1"),
                    etd=m.format_dt(r.get("EXPORT_DT"), r.get("EXPORT_HH")),
                    eta=m.format_dt(r.get("IMPORT_DT"), r.get("IMPORT_HH")),
                    direct_or_ts="Direct" if not ts or ts.lower().startswith("d") else "T/S",
                    doc_cutoff=r.get("DCLOSING_INFO"), cy_cutoff=r.get("CCLOSING_INFO"),
                ))
    return out


def _namsung_from_files() -> list[dict]:
    """
    Namsung rows saved in NAMSUNG/*.txt. ebiz.namsung.co.kr blocks scripted access from this network (Akamai 403), so
    the rows were collected through a normal Chrome browser (the same /sch/selectScheList call the web page makes).
    Columns: origin(B/L)|vessel|voyage|ETD|ETA|direct(D)/ts|CY cutoff|doc cutoff
    """
    out = []
    for f in sorted(NAMSUNG_DIR.glob("*.txt")) if NAMSUNG_DIR.is_dir() else []:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            p = line.split("|")
            if len(p) < 8:
                continue
            o, vessel, voyage, etd_s, eta_s, ts, cy, doc = (x.strip() for x in p[:8])
            etd, eta = _kmtc_ts(etd_s), _kmtc_ts(eta_s)
            out.append(_rec(
                "Namsung", carrier="Namsung", vessel=vessel, voyage=voyage,
                pol="Bangkok" if o == "B" else "Laem Chabang", pod=POD_NAME,
                etd=etd, eta=eta, transit_days=_days_between(etd, eta),
                direct_or_ts="Direct" if not ts or ts.lower().startswith("d") else "T/S",
                cy_cutoff=_kmtc_ts(cy), doc_cutoff=_kmtc_ts(doc),
            ))
    return out


def fetch_namsung(start: dt.date, end: dt.date) -> list[dict]:
    try:
        return _namsung_live(start, end)
    except SourceBlocked:
        recs = _namsung_from_files()
        if recs:
            return recs
        raise


def _hmm_from_files() -> list[dict]:
    """
    HMM rows saved in HMM/*.txt (hmm21.com resets scripted connections; collected through a normal Chrome browser).
    Columns: origin port|vessel|voyage|ETD|ETA|transit/type|route|inland cut-off|port cut-off|doc cut-off
    """
    out = []
    for f in sorted(HMM_DIR.glob("*.txt")) if HMM_DIR.is_dir() else []:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            p = line.split("|")
            if len(p) < 10:
                continue
            org, vessel, voyage, etd, eta, tt, route, inland, port_cut, doc = (x.strip() for x in p[:10])
            out.append(_rec(
                "HMM", carrier="HMM", service=route, vessel=vessel, voyage=voyage,
                pol="Bangkok" if "BANGKOK" in org.upper() else "Laem Chabang", pod=POD_NAME,
                etd=etd, eta=eta, transit_days=_days_between(etd, eta),
                direct_or_ts="Direct" if "direct" in tt.lower() else "T/S",
                cy_cutoff=port_cut, doc_cutoff=doc,
            ))
    return out


def _hmm_live(start: dt.date, end: dt.date) -> list[dict]:
    import requests
    try:
        requests.get("https://www.hmm21.com/", timeout=8, headers={"User-Agent": "Mozilla/5.0"})
    except requests.RequestException as exc:
        raise SourceBlocked(
            "hmm21.com resets / times out connections from this network (HTTP/2 protocol error, connection reset)") from exc
    raise RuntimeError("hmm21.com is reachable again, but raw-data/hmm_schedule.py only dumps raw table rows -- "
                       "it needs a parser before HMM can be merged")


def fetch_hmm(start: dt.date, end: dt.date) -> list[dict]:
    try:
        return _hmm_live(start, end)
    except RuntimeError:                      # SourceBlocked is a RuntimeError; so is "needs a parser"
        recs = _hmm_from_files()
        if recs:
            return recs
        raise


SOURCES = {
    "sitc":    ("SITC",     fetch_sitc),
    "kmtc":    ("KMTC",     fetch_kmtc),
    "hal":     ("HAL",      fetch_hal),
    "ckline":  ("CK Line",  fetch_ckline),
    "culines": ("CU Lines", fetch_culines),
    "dongjin": ("Dongjin",  fetch_dongjin),
    "sjj":     ("SJJ",      fetch_jj),
    "namsung": ("Namsung",  fetch_namsung),
    "hmm":     ("HMM",      fetch_hmm),
}

# Shown in the dashboard footer and the Sources sheet of the Excel file
SOURCE_NOTES = {
    "kmtc": "ekmtc.com blocks scripted access from this network, so the rows come from KMTC/*.txt (collected 2026-10-28 through a normal Chrome browser); a live pull is used automatically when it works",
    "namsung": "ebiz.namsung.co.kr blocks scripted access from this network (Akamai 403), so the rows come from NAMSUNG/*.txt (collected 2026-10-28 through a normal Chrome browser); a live pull is used automatically when it works",
    "hmm": "hmm21.com resets scripted connections from this network, so the rows come from HMM/*.txt (collected 2026-10-28 through a normal Chrome browser; HMM sells only part of these sailings); a live pull is used automatically when it works",
    "hal": "static rows extracted from ebiz.heungaline.com on 2026-09-13 (not a live pull); every vessel on HAL's page counts as bookable via HAL",
    "ckline": "only vessels CK Line can book (own + chartered fleet); other carriers' vessels on es.ckline.co.kr are left out",
    "sjj": "JJ Shipping only publishes about the next 5 weeks",
}


# --------------------------------------------------------------------------- #
#  Merge duplicate sailings                                                    #
# --------------------------------------------------------------------------- #
def dedupe_records(records: list[dict]) -> list[dict]:
    """Drop rows that are exact duplicates from the same source (some APIs repeat rows)"""
    out, seen = [], set()
    for r in records:
        k = (r["source"], r["vessel_key"], r.get("voyage"), r.get("etd"), r.get("eta"))
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def _voy_key(voyage: str | None) -> str:
    """'KUS12616N' / '2616N' / 'PBRG2612N' -> '2616N' / '2616N' / '2612N' (carriers write voyage codes differently)."""
    m = re.search(r"(\d{4}[A-Za-z]?)$", (voyage or "").strip())
    return m.group(1).upper() if m else ""


# Rows that are not a live pull. When a live source lists the same sailing, its dates win
# (a static copy goes stale when the carrier re-times a voyage).
STATIC_SOURCES = {"HAL"}


def merge_sailings(records: list[dict]) -> list[dict]:
    """
    Merges records that are 'the same vessel leaving the same origin port' and either depart on the same day
    (<= 1 day apart) or carry the same voyage code (<= 10 days apart, to follow re-timed voyages) into a single
    sailing, keeping each source/carrier's own details under 'offers'
    """
    clusters: list[dict] = []

    def dpick(rec):
        _, d = parse_dt(rec.get("etd_date") or rec.get("etd"))
        return d

    for rec in sorted(records, key=lambda r: (r["vessel_key"], r.get("etd_date") or "9999")):
        d = dpick(rec)
        placed = False
        vk = _voy_key(rec.get("voyage"))
        if rec["vessel_key"] and d:
            for c in clusters:
                if c["vessel_key"] != rec["vessel_key"] or c["okey"] != _origin_key(rec["pol"]):
                    continue
                gap = abs((c["_date"] - d).days) if c["_date"] else 999
                if gap <= 1 or (vk and vk in c["voys"] and gap <= 10):
                    c["offers"].append(rec)
                    if vk:
                        c["voys"].add(vk)
                    if d < c["_date"]:
                        c["_date"] = d
                    placed = True
                    break
        if not placed:
            clusters.append({
                "vessel_key": rec["vessel_key"],
                "vessel": rec["vessel"],
                "okey": _origin_key(rec["pol"]),
                "origin": _port_name(rec["pol"]),
                "_date": d,
                "voys": {vk} if vk else set(),
                "offers": [rec],
            })

    merged = []
    for c in clusters:
        offers = c["offers"]
        carriers = sorted({o["carrier"] for o in offers})
        # dates / times come from the live sources when there are any, else from everything we have
        basis = [o for o in offers if o["source"] not in STATIC_SOURCES] or offers
        transit_vals = [o["transit_days"] for o in basis if o["transit_days"]]
        etas = [o["eta"] for o in basis if o["eta"]]
        etds = [o["etd"] for o in basis if o["etd"]]
        etd_dates = sorted(o["etd_date"] for o in basis if o.get("etd_date"))
        is_direct = any((o.get("direct_or_ts") or "").lower().startswith("direct") for o in offers)
        merged.append({
            "vessel": c["vessel"] or (offers[0]["vessel"]),
            "origin": c["origin"],
            "etd_date": etd_dates[0] if etd_dates else None,
            "etd": min(etds) if etds else None,
            "eta": min(etas) if etas else None,
            "transit_days": (min(transit_vals), max(transit_vals)) if transit_vals else None,
            "direct_or_ts": "Direct" if is_direct else "Transshipment",
            "carriers": carriers,
            "n_sources": len(carriers),
            "n_offers": len(offers),
            "offers": sorted(offers, key=lambda o: o["carrier"]),
        })
    merged.sort(key=lambda x: (x["etd_date"] or "9999", x["vessel"]))
    return merged


# --------------------------------------------------------------------------- #
#  Daily mail (English): which HAL sailings to sell first + which days to watch #
# --------------------------------------------------------------------------- #
def build_mail(merged: list[dict], statuses: list[dict], now: dt.datetime, result: str = "ok",
               weeks: int = 3) -> tuple[str, str]:
    """(subject, html) for the daily mail. Written for Outlook's (Word-based) renderer: plain tables, bgcolor cells."""
    def port(x):
        return "BKK" if "bangkok" in (x.get("origin") or "").lower() else "LCH"

    def own(x):
        return "HAL" in x["carriers"] or (x.get("vessel") or "").upper().startswith("HEUNG")

    def parse_cut(t):
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime((t or "").strip(), fmt)
            except ValueError:
                pass
        return None

    dfmt = lambda d: f"{d:%a} {d.day} {d:%b}"                  # Thu 29 Oct
    today = now.date()
    wstart = lambda d: d - dt.timedelta(days=d.weekday())            # Monday of d's week
    horizon = wstart(today) + dt.timedelta(days=6 + 7 * (weeks - 1))   # Sunday of the last week shown
    week_starts = [wstart(today) + dt.timedelta(days=7 * k) for k in range(weeks)]

    def week_title(ws):
        we = ws + dt.timedelta(days=6)
        rel = {0: " &middot; this week", 1: " &middot; next week"}.get((ws - wstart(today)).days // 7, "")
        return f"Week {ws.isocalendar()[1]} &middot; {ws.day} {ws:%b} &ndash; {we.day} {we:%b}{rel}"

    comp_by = {}                                    # (port, date) -> competitor sailings from that port
    comp_day = {}                                   # date -> competitor sailings (both ports)
    own_day = {}                                    # date -> HAL sailings
    for x in merged:
        if not x.get("etd_date"):
            continue
        d = dt.date.fromisoformat(x["etd_date"])
        if own(x):
            own_day.setdefault(d, []).append(x)
        else:
            comp_by.setdefault((port(x), d), []).append(x)
            comp_day.setdefault(d, []).append(x)

    own_by_vessel = {}                              # vessel name -> HAL sailings (any date in range)
    for x in merged:
        if own(x) and x.get("etd_date"):
            own_by_vessel.setdefault((x.get("vessel") or "").upper(), []).append(x)

    # space (BSA) per vessel / port / ETD from SVMS; ignored when missing or older than 36 h
    space_rows = []
    space_ok = False
    try:
        sp_file = json.loads((OUT_DIR / "space.json").read_text(encoding="utf-8"))
        if now - dt.datetime.fromisoformat(sp_file["generated"]) <= dt.timedelta(hours=36):
            space_rows, space_ok = sp_file["rows"], True
    except (OSError, ValueError, KeyError):
        pass

    def space_for(x):
        """SVMS space row of this HAL sailing: same vessel name and port, nearest ETD within 36 h"""
        try:
            etd_dt = dt.datetime.strptime((x.get("etd") or "")[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            etd_dt = dt.datetime.combine(dt.date.fromisoformat(x["etd_date"]), dt.time(12))
        best = None
        for r in space_rows:
            if r["vessel"] != (x.get("vessel") or "").upper() or r["port"] != port(x) or not r.get("etd"):
                continue
            gap = abs(dt.datetime.strptime(r["etd"], "%Y%m%d%H%M") - etd_dt)
            if gap <= dt.timedelta(hours=36) and (best is None or gap < best[0]):
                best = (gap, r)
        return best[1] if best else None

    def space_level(r):
        """FULL / NEARLY FULL / SPACE LEFT from balance = BSA - TEU on board after this port"""
        if not r:
            return None
        bal, bsa = r["balance"], r["bsa"] or 0
        if bal <= 0:
            return "FULL"
        return "NEARLY FULL" if bal <= max(10, 0.10 * bsa) else "SPACE LEFT"

    def space_tag(r):
        lv = space_level(r)
        if not lv:
            return ""
        col = {"FULL": "#dc2626", "NEARLY FULL": "#d97706", "SPACE LEFT": "#15803d"}[lv]
        bal = r["balance"]
        if lv == "FULL":                              # how far over is not shown, only that it is full
            return f" <b style='color:{col};font-size:12px'>{lv}</b>"
        txt = f"{bal} TEU left"
        return f" <b style='color:{col};font-size:12px'>{lv}</b><span style='color:#64748b;font-size:12px'> ({txt})</span>"

    def voy_of(x, own_ship=False):
        """voyage number: SVMS's for HAL ships when matched, else HAL's own row, else the first carrier row that has one"""
        if own_ship:
            sp = space_for(x)
            if sp and sp.get("voyage"):
                return sp["voyage"]
        for o in sorted(x["offers"], key=lambda o: o["source"] != "HAL"):
            v = (o.get("voyage") or "").strip()
            if v:
                return v
        return ""

    def voy_html(x, own_ship=False):
        v = voy_of(x, own_ship)
        return f" <span style='color:#475569;font-size:12px'>Voy {v}</span>" if v else ""

    def share_note(x):
        """carriers that sell this sailing besides HAL ("shared with ...") as small grey text"""
        others = [c for c in x["carriers"] if c != "HAL"]
        return others

    # ---- 1) HAL sailings to sell first ------------------------------------------------------------
    flagged = []                                    # one entry per HAL sailing that needs attention
    for x in merged:
        if not x.get("etd_date") or not own(x):
            continue
        etd = dt.date.fromisoformat(x["etd_date"])
        if not (today <= etd <= horizon):
            continue
        near = [c for k in (-1, 0, 1) for c in comp_by.get((port(x), etd + dt.timedelta(days=k)), [])]
        offers = sorted(x["offers"], key=lambda o: o["source"] != "HAL")
        cut = next((c for c in (parse_cut(o.get("cy_cutoff")) for o in offers) if c), None)
        if cut and cut < now:
            continue                                # already closed
        left = (cut - now) if cut else None
        r_comp = len(near) >= 4
        r_close = left is not None and left <= dt.timedelta(days=3)
        if not (r_comp or r_close):
            continue
        sp = space_for(x)
        full = space_level(sp) == "FULL"
        r_space = bool(r_close and sp and sp["balance"] >= max(40, 0.25 * (sp["bsa"] or 0)))
        why = []
        if r_comp:
            why.append(f"{len(near)} competitor sailings from {port(x)} within &plusmn;1 day")
        if r_close:
            hrs = int(left.total_seconds() // 3600)
            when = f"{dfmt(cut)} {cut:%H:%M}"
            why.append(f"cargo cut-off in {hrs} h ({when})" if hrs < 48 else f"cargo cut-off {when}")
        if r_space:
            why.append(f"closing soon but <b>{sp['balance']} TEU still free</b> &ndash; push sales now")
        flagged.append({"x": x, "etd": etd, "port": port(x), "why": why, "full": full, "sp": sp,
                        "urgent": (not full) and ((r_comp and r_close) or r_space),
                        "also": [c for c in x["carriers"] if c != "HAL"]})

    groups = []                                     # same vessel, both ports (ETDs within 3 days) -> one row
    for f in sorted(flagged, key=lambda f: (f["x"]["vessel"], f["etd"])):
        g = groups[-1] if groups else None
        if g and g["vessel"] == f["x"]["vessel"] and (f["etd"] - g["items"][-1]["etd"]).days <= 3:
            g["items"].append(f)
        else:
            groups.append({"vessel": f["x"]["vessel"], "items": [f]})
    for g in groups:
        g["full"] = all(i["full"] for i in g["items"])
        g["urgent"] = any(i["urgent"] for i in g["items"])
        g["etd"] = min(i["etd"] for i in g["items"])
    groups.sort(key=lambda g: (wstart(g["etd"]), g["full"], not g["urgent"], g["etd"]))
    n_urgent = sum(1 for g in groups if g["urgent"])

    FONT = "font-family:Segoe UI,Arial,sans-serif"
    th = f"{FONT};padding:6px 10px;text-align:left;font-size:12px;color:#64748b;border-bottom:2px solid #cbd5e1"
    td = f"{FONT};padding:8px 10px;border-bottom:1px solid #e2e8f0;vertical-align:top;font-size:14px"
    # badge = a one-cell table with a background colour (Outlook ignores rounded spans / padding on <span>)
    pill = lambda text, col: (f"<table cellpadding='0' cellspacing='0' border='0'><tr>"
                              f"<td bgcolor='{col}' style='{FONT};padding:3px 9px;color:#ffffff;font-size:11px;"
                              f"font-weight:bold;white-space:nowrap'>{text}</td></tr></table>")
    def week_row(ws, cols, note, tone="#0f172a"):
        return (f"<tr><td colspan='{cols}' bgcolor='{tone}' style='{FONT};padding:7px 10px;color:#ffffff;"
                f"font-size:13px;font-weight:bold'>{week_title(ws)}"
                f"<span style='font-weight:normal;color:#cbd5e1'> &nbsp;&nbsp;{note}</span></td></tr>")

    def clear_row(cols, text):
        return (f"<tr><td colspan='{cols}' style='{FONT};padding:9px 10px;color:#15803d;font-size:13px;"
                f"border-bottom:1px solid #e2e8f0'>{text}</td></tr>")

    sell_rows = ""
    for ws in week_starts:
        wg = [g for g in groups if wstart(g["etd"]) == ws]
        nu = sum(1 for g in wg if g["urgent"])
        nf = sum(1 for g in wg if g["full"])
        note = (f"{nu} urgent &middot; {len(wg) - nu - nf} sell first" + (f" &middot; {nf} full" if nf else "")
                if wg else "all clear")
        sell_rows += week_row(ws, 3, note, "#7f1d1d" if nu else "#0f172a")
        if not wg:
            sell_rows += clear_row(3, "No HAL sailing needs special attention this week.")
        for g in wg:
            bg = "#fef2f2" if g["urgent"] else "#ffffff"
            badge = (pill("URGENT", "#dc2626") if g["urgent"] else pill("FULL", "#64748b") if g["full"]
                     else pill("SELL FIRST", "#d97706"))
            also = sorted({c for i in g["items"] for c in i["also"]})
            lines = "".join(
                f"<div style='margin-bottom:4px'><b>{i['port']} {i['etd'].day} {i['etd']:%b}</b>"
                f"{voy_html(i['x'], True)}{space_tag(i['sp'])} &ndash; {'; '.join(i['why'])}</div>"
                for i in g["items"])
            sell_rows += (
                f"<tr bgcolor='{bg}'><td bgcolor='{bg}' style='{td};white-space:nowrap'>{badge}</td>"
                f"<td bgcolor='{bg}' style='{td};min-width:150px'><b style='font-size:15px'>{g['vessel']}</b>"
                + (f"<div style='color:#64748b;font-size:12px'>shared with: {', '.join(also)}</div>" if also else
                   "<div style='color:#94a3b8;font-size:12px'>HAL only</div>")
                + f"</td><td bgcolor='{bg}' style='{td}'>{lines}</td></tr>")
    sell = ("<table cellpadding='0' cellspacing='0' style='border-collapse:collapse;width:100%'>"
            f"<tr><td style='{th}'>Level</td><td style='{th}'>HAL vessel</td><td style='{th}'>Why</td></tr>"
            + sell_rows + "</table>")

    # ---- 2) days to watch -------------------------------------------------------------------------
    def level(n_comp, n_hal):
        if (n_comp >= 3 and n_hal == 0) or n_comp >= 4:
            return 2
        if (n_comp >= 2 and n_hal == 0) or n_comp >= 3:
            return 1
        return 0

    watch_rows, n_high = "", 0
    day_list = []                                   # (date, level) for flagged days
    for i in range((horizon - today).days + 1):
        d = today + dt.timedelta(days=i)
        lv = level(len(comp_day.get(d, [])), len(own_day.get(d, [])))
        if lv:
            day_list.append((d, lv))
    n_high = sum(1 for _, lv in day_list if lv == 2)
    watch_by_week = {}
    for d, lv in day_list:
        comp, mine = comp_day.get(d, []), own_day.get(d, [])
        badge = pill("HIGH", "#dc2626") if lv == 2 else pill("WATCH", "#d97706")
        def comp_line(c):
            carriers = c["carriers"]
            tag = (f"shared by {', '.join(carriers)}" if len(carriers) > 1 else f"{carriers[0]} only")
            hal_too = [m for m in own_by_vessel.get((c.get("vessel") or "").upper(), [])
                       if dt.date.fromisoformat(m["etd_date"]) >= today]
            hal_note = (f"<br><b style='color:#15803d;font-size:12px'>HAL also has this ship: "
                        + ", ".join(f"{port(m)} {dt.date.fromisoformat(m['etd_date']).day} "
                                    f"{dt.date.fromisoformat(m['etd_date']):%b}" for m in hal_too[:3])
                        + "</b>") if hal_too else ""
            return (f"<div style='margin-bottom:4px'><b>{c['vessel']}</b> ({port(c)}){voy_html(c)} "
                    f"<span style='color:#64748b;font-size:12px'>&middot; {tag}</span>{hal_note}</div>")

        def mine_line(m):
            others = share_note(m)
            tag = f"shared with {', '.join(others)}" if others else "HAL only"
            return (f"<div style='margin-bottom:4px'><b>{m['vessel']}</b> ({port(m)}){voy_html(m, True)} "
                    f"<span style='color:#64748b;font-size:12px'>&middot; {tag}</span>{space_tag(space_for(m))}</div>")

        comp_txt = "".join(comp_line(c) for c in sorted(comp, key=lambda c: (c["vessel"], port(c))))
        mine_txt = ("".join(mine_line(m) for m in mine) if mine
                    else "<b style='color:#dc2626'>No HAL sailing</b>")
        row_html = (
            f"<tr><td style='{td};white-space:nowrap'><b>{dfmt(d)}</b></td><td style='{td}'>{badge}</td>"
            f"<td style='{td}'>{comp_txt}<div style='color:#64748b;font-size:12px'>"
            f"{len(comp)} competitor sailings</div></td><td style='{td}'>{mine_txt}</td></tr>")
        watch_by_week.setdefault(wstart(d), []).append(row_html)
    for ws in week_starts:
        wl = [lv for d, lv in day_list if wstart(d) == ws]
        note = (f"{sum(1 for v in wl if v == 2)} high &middot; {sum(1 for v in wl if v == 1)} watch" if wl
                else "all clear")
        watch_rows += week_row(ws, 4, note, "#7f1d1d" if 2 in wl else "#0f172a")
        watch_rows += "".join(watch_by_week.get(ws, [])) or clear_row(4, "No special watch days this week.")
    watch = ("<table cellpadding='0' cellspacing='0' style='border-collapse:collapse;width:100%'>"
             f"<tr><td style='{th}'>Date (ETD)</td><td style='{th}'>Level</td>"
             f"<td style='{th}'>Competitor vessels</td><td style='{th}'>HAL that day</td></tr>"
             + watch_rows + "</table>")

    # ---- 3) data quality (one line) -----------------------------------------------------------------
    bad = [s["Source"] for s in statuses if s["Status"] != "ok"]
    saved = [s["Source"] for s in statuses if s["Status"] == "ok"
             and ("not a live pull" in (s.get("Detail") or "") or ".txt" in (s.get("Detail") or ""))]
    ok_n = sum(1 for s in statuses if s["Status"] == "ok")
    data = f"Data pulled from {ok_n}/{len(statuses)} carriers"
    if saved:
        data += f" &middot; saved data (may be out of date): {', '.join(saved)}"
    if bad:
        data += f" &middot; <span style='color:#dc2626'>not available: {', '.join(bad)}</span>"

    # ---- assemble -------------------------------------------------------------------------------------
    box = lambda n, label, col: (
        f"<td bgcolor='#f1f5f9' style='{FONT};padding:10px 18px;text-align:center'>"
        f"<div style='font-size:26px;font-weight:bold;color:{col}'>{n}</div>"
        f"<div style='font-size:12px;color:#64748b'>{label}</div></td><td width='10'></td>")
    banner = ""
    if result == "failed":
        banner = (f"<p style='{FONT};background:#fef2f2;color:#b91c1c;padding:10px 12px'>"
                  "<b>The automatic update failed.</b> The figures below may be from the previous run and the "
                  "website still shows the old data (details: update_log.txt on the updater PC).</p>")
    elif result == "nochange":
        banner = f"<p style='{FONT};color:#64748b'>Refreshed &ndash; nothing changed since the last update.</p>"
    html_body = (
        f"<div style='{FONT};font-size:14px;color:#0f172a;max-width:780px'>"
        "<div style='font-size:19px;font-weight:bold'>Bangkok / Laem Chabang &rarr; Ho Chi Minh City</div>"
        f"<div style='color:#64748b;margin-bottom:12px'>Daily summary &middot; {dfmt(today)} {today.year}, "
        f"{now:%H:%M} &middot; {len(merged)} sailings (duplicates merged)</div>{banner}"
        "<table cellpadding='0' cellspacing='0'><tr>"
        + box(n_urgent, "HAL sailings to sell NOW (urgent)", "#dc2626" if n_urgent else "#15803d")
        + box(len(groups), "HAL vessels needing attention", "#d97706" if groups else "#15803d")
        + box(n_high, "days with heavy competition (high)", "#dc2626" if n_high else "#15803d")
        + "</tr></table>"
        f"<h3 style='{FONT};margin:24px 0 6px'>1. HAL sailings to sell first &ndash; week by week</h3>" + sell +
        f"<h3 style='{FONT};margin:24px 0 6px'>2. Days to watch &ndash; competitor sailings, week by week</h3>"
        + watch +
        f"<p style='{FONT};margin-top:24px'>Full dashboard: "
        "<a href='https://palm0105.github.io/all-schedule-hcm/dashboard.html'>palm0105.github.io/all-schedule-hcm</a>"
        "<br><span style='color:#64748b'>or open the HTML file attached to this mail "
        "(its Refresh button does not work from an attachment).</span></p>"
        f"<p style='{FONT};color:#64748b;font-size:12px;border-top:1px solid #e2e8f0;padding-top:10px'>{data}<br>"
        "How sailings are picked: SELL FIRST = 4+ competitor sailings leave the same port within &plusmn;1 day, "
        "or the cargo cut-off is within 3 days; URGENT = both (sailings already past cut-off are left out). "
        "Competitor = a vessel HAL cannot book. HAL's own cut-off data was collected on 13 Sep and may be incomplete. "
        + ("Space tags come from SVMS: space left = allocated TEU (BSA) minus TEU on board after loading at that port; "
           "FULL = nothing left, NEARLY FULL = 10% or less of the allocation left; URGENT also covers ships closing "
           "within 3 days that still have 25%+ of the allocation free."
           if space_ok else "Space data (SVMS) was not available this run, so no FULL / SPACE LEFT tags are shown.")
        + "<br>Automatic message from the HCM schedule updater.</p></div>")
    if result == "failed":
        subject = f"[HCM] Update FAILED - {dfmt(today)}"
    else:
        parts = []
        if n_urgent:
            parts.append(f"{n_urgent} HAL sailing{'s' if n_urgent > 1 else ''} to sell NOW")
        if n_high:
            parts.append(f"{n_high} heavy-competition day{'s' if n_high > 1 else ''}")
        subject = f"[HCM] {dfmt(today)} - " + (" | ".join(parts) if parts else "nothing urgent")
    return subject, html_body


# --------------------------------------------------------------------------- #
#  Export: Excel                                                              #
# --------------------------------------------------------------------------- #
def transit_text(t) -> str:
    if not t:
        return ""
    lo, hi = t
    if lo == hi:
        return f"{lo:g}"
    return f"{lo:g}\u2013{hi:g}"


def write_excel(merged: list[dict], records: list[dict], statuses: list[dict], path: Path):
    import pandas as pd

    merged_rows = []
    for mrec in merged:
        merged_rows.append({
            "ETD Date": mrec["etd_date"],
            "Origin": mrec["origin"],
            "Vessel": mrec["vessel"],
            "ETD": mrec["etd"],
            "ETA": mrec["eta"],
            "Transit (days)": transit_text(mrec["transit_days"]),
            "Type": mrec["direct_or_ts"],
            "# Lines": mrec["n_sources"],
            "Bookable via": ", ".join(mrec["carriers"]),
            "Voyages": " | ".join(
                f"{o['carrier']}:{o['voyage'] or '-'}" for o in mrec["offers"]),
        })
    df_merged = pd.DataFrame(merged_rows)

    df_all = pd.DataFrame([{
        "Source": r["source"], "Carrier": r["carrier"], "Service": r["service"],
        "Vessel": r["vessel"], "Voyage": r["voyage"],
        "POL": r["pol"], "POL Terminal": r["pol_terminal"],
        "ETD": r["etd"], "ETA": r["eta"],
        "POD": r["pod"], "POD Terminal": r["pod_terminal"],
        "Transit (days)": r["transit_days"], "Type": r["direct_or_ts"],
        "Doc Cut-off": r["doc_cutoff"], "CY Cut-off": r["cy_cutoff"],
        "VGM Cut-off": r["vgm_cutoff"],
    } for r in sorted(records, key=lambda r: (r.get("etd_date") or "9999", r["carrier"]))])

    df_src = pd.DataFrame(statuses)

    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df_merged.to_excel(writer, index=False, sheet_name="Merged", startrow=1)
        df_all.to_excel(writer, index=False, sheet_name="All Sailings", startrow=1)
        df_src.to_excel(writer, index=False, sheet_name="Sources")
        for name, df in (("Merged", df_merged), ("All Sailings", df_all)):
            sh = writer.sheets[name]
            sh["A1"] = (f"Sailing Schedule  {LANE}   "
                        f"(generated {dt.datetime.now():%Y-%m-%d %H:%M})")
            sh["A1"].font = sh["A1"].font.copy(bold=True, size=12)
            for col in sh.columns:
                width = max((len(str(c.value)) if c.value is not None else 0) for c in col)
                sh.column_dimensions[col[0].column_letter].width = min(max(width + 2, 12), 48)


# --------------------------------------------------------------------------- #
#  Export: ICS calendar                                                      #
# --------------------------------------------------------------------------- #
def write_ics(merged: list[dict], path: Path):
    def esc(s):
        return (str(s).replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\n", "\\n"))

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//hcm service//build_hcm_schedule//TH",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:BKK/LCH \u2192 Ho Chi Minh City Sailing Schedule"]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for i, mrec in enumerate(merged):
        if not mrec["etd_date"]:
            continue
        d = mrec["etd_date"].replace("-", "")
        _, eta_date = parse_dt(mrec["eta"])
        summary = f"\U0001F6A2 {mrec['vessel']} {mrec['origin']} \u2192 Ho Chi Minh City ({', '.join(mrec['carriers'])})"
        desc_parts = [
            f"Type: {mrec['direct_or_ts']}",
            f"Transit: {transit_text(mrec['transit_days'])} days",
            f"ETD: {mrec['etd']}   ETA: {mrec['eta']}",
            "Bookable via:",
        ]
        for o in mrec["offers"]:
            desc_parts.append(
                f"  - {o['carrier']} | Voy {o['voyage'] or '-'} | "
                f"svc {o['service'] or '-'} | ETD {o['etd'] or '-'} | ETA {o['eta'] or '-'}"
                + (f" | CY {o['cy_cutoff']}" if o['cy_cutoff'] else ""))
        lines += [
            "BEGIN:VEVENT",
            f"UID:hcm-{d}-{i}@hcm-service",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{d}",
            f"DTEND;VALUE=DATE:{(eta_date + dt.timedelta(days=1)).strftime('%Y%m%d') if eta_date else d}",
            f"SUMMARY:{esc(summary)}",
            f"DESCRIPTION:{esc(chr(10).join(desc_parts))}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    path.write_text("\r\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------- #
#  Export: HTML dashboard + calendar                                         #
# --------------------------------------------------------------------------- #
CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--accent:#0ea5e9}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
     font-family:"Segoe UI",Roboto,"Helvetica Neue",Arial,"Noto Sans Thai",sans-serif;font-size:14px}
.wrap{max-width:1180px;margin:0 auto;padding:24px}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:16px;margin:28px 0 12px;padding-bottom:6px;border-bottom:2px solid var(--line)}
.sub{color:var(--muted);margin:0 0 20px}
.grid{display:grid;gap:14px}
.kpis{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.kpi .v{font-size:26px;font-weight:700}
.kpi .l{color:var(--muted);font-size:12px;margin-top:2px}
.dot{width:11px;height:11px;border-radius:50%;flex:none}
.bar{display:flex;align-items:center;gap:8px;margin:6px 0}
.bar .lab{width:150px;font-size:12px;color:var(--muted);text-align:right;flex:none}
.bar .track{flex:1;background:#eef2f7;border-radius:6px;overflow:hidden}
.bar .fill{height:16px;border-radius:6px}
.bar .num{width:34px;font-size:12px;font-weight:600;flex:none}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);
      border-radius:12px;overflow:hidden}
th,td{padding:9px 10px;text-align:left;border-bottom:1px solid var(--line);font-size:13px;vertical-align:top}
th{background:#f1f5f9;font-size:12px;text-transform:uppercase;letter-spacing:.03em;color:var(--muted)}
tr.main{cursor:pointer}
tr.main:hover{background:#f8fafc}
tr.details{display:none;background:#fbfcfe}
tr.details.show{display:table-row}
tr.wk-off,tr.wk-off + tr.details{display:none !important}
.badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;font-weight:600;margin:1px 2px}
.pill{display:inline-block;padding:1px 7px;border-radius:6px;font-size:11px;background:#eef2f7;color:#334155;margin-right:4px}
.tag-direct{background:#dcfce7;color:#166534}.tag-ts{background:#fef9c3;color:#854d0e}
.mtabs{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 14px}
.mtab{border:1px solid var(--line);background:var(--card);border-radius:8px;padding:6px 12px;
      cursor:pointer;font:inherit;font-size:13px;font-weight:600;color:var(--muted)}
.mtab:hover{border-color:var(--accent);color:var(--ink)}
.mtab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.mtab .cnt{display:inline-block;margin-left:7px;background:rgba(0,0,0,.12);border-radius:999px;
           padding:0 7px;font-size:11px}
.mtab.active .cnt{background:rgba(255,255,255,.28)}
.wtabs{display:flex;flex-wrap:wrap;gap:5px;margin:0 0 12px}
.wtab{border:1px solid var(--line);background:var(--card);border-radius:7px;padding:4px 10px;
      cursor:pointer;font:inherit;font-size:12px;font-weight:600;color:var(--muted)}
.wtab:hover{border-color:var(--accent);color:var(--ink)}
.wtab.active{background:#e0f2fe;border-color:var(--accent);color:#0369a1}
.wtab .cnt{display:inline-block;margin-left:6px;background:rgba(0,0,0,.10);border-radius:999px;
           padding:0 6px;font-size:10px}
.otabs{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 14px}
.otab{border:1px solid var(--line);background:var(--card);border-radius:8px;padding:6px 12px;
      cursor:pointer;font:inherit;font-size:13px;font-weight:600;color:var(--muted)}
.otab:hover{border-color:#0f172a;color:var(--ink)}
.otab.active{background:#0f172a;color:#fff;border-color:#0f172a}
.otab .cnt{display:inline-block;margin-left:7px;background:rgba(0,0,0,.12);border-radius:999px;
           padding:0 7px;font-size:11px}
.otab.active .cnt{background:rgba(255,255,255,.28)}
.cal .ev small{opacity:.75;font-size:9px;font-weight:700}
.calpanel[hidden],.detpanel[hidden]{display:none}
.cal{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:18px}
.cal .h{font-size:11px;color:var(--muted);text-align:center;padding:4px 0;font-weight:600}
.cal .cell{background:var(--card);border:1px solid var(--line);border-radius:8px;min-height:78px;padding:4px}
.cal .cell.dim{background:#f1f5f9}
.cal .d{font-size:11px;color:var(--muted);font-weight:600}
.cal .ev{font-size:10px;line-height:1.25;margin-top:2px;padding:1px 3px;border-radius:4px;
         display:flex;align-items:center;gap:3px;white-space:nowrap;overflow:hidden}
.cal .ev .et{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis}
.cal .ev .cd{flex:none;width:7px;height:7px;border-radius:50%;border:1px solid rgba(255,255,255,.95);
             box-shadow:0 0 0 .5px rgba(15,23,42,.35)}
.ch{font-size:12px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);margin:2px 0 8px}
.cgrid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:0 0 8px}
@media (max-width:1000px){.cgrid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:480px){.cgrid{grid-template-columns:minmax(0,1fr)}}
.cc{display:flex;align-items:center;gap:12px;min-width:0;padding:9px 16px 9px 10px;background:var(--card);
    border:2px solid var(--c);border-radius:14px;box-shadow:0 0 0 3px var(--cs);cursor:pointer;
    font:inherit;text-align:left;color:var(--ink);user-select:none;transition:opacity .15s,filter .15s,transform .1s}
.cc:hover{transform:translateY(-1px)}
.cc.off{opacity:.4;filter:grayscale(1);box-shadow:none;border-color:var(--line)}
.cc .lg{flex:none;width:84px;height:42px;display:flex;align-items:center;justify-content:center;background:#fff;
        border:1px solid var(--line);border-radius:9px;padding:4px 6px;overflow:hidden}
.cc .lg img{max-width:100%;max-height:100%;object-fit:contain;display:block}
.cc .lg.tx{border:0;font-weight:800;font-size:13px;letter-spacing:.02em;padding:0 4px;text-align:center;line-height:1.1}
.cc .ct{display:flex;flex-direction:column;gap:1px;min-width:0}
.cc .ct b{font-size:14px;font-weight:700;white-space:nowrap}
.cc .ct i{font-style:normal;font-size:12.5px;color:var(--muted);white-space:nowrap}
.cbar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:6px 0 16px;font-size:12.5px;color:var(--muted)}
.cbar button{border:1px solid var(--line);background:var(--card);border-radius:8px;padding:4px 12px;font:inherit;
             font-size:12px;font-weight:600;color:var(--muted);cursor:pointer}
.cbar button:hover{border-color:var(--accent);color:var(--ink)}
tr.c-off,tr.c-off + tr.details{display:none !important}
.cal .ev[hidden]{display:none}
.cal .ev{cursor:default}
.tip{position:fixed;display:none;z-index:70;width:372px;max-width:calc(100vw - 16px);background:#fff;color:#334155;
     border:1px solid #e2e8f0;border-radius:12px;padding:13px 15px;box-shadow:0 12px 36px rgba(15,23,42,.18);
     font-size:12px;line-height:1.45;pointer-events:none}
.tip .th{display:flex;justify-content:space-between;align-items:flex-start;gap:10px}
.tip .th b{font-size:15px;color:#0f172a}
.tip .tc{display:flex;flex-wrap:wrap;gap:4px;justify-content:flex-end}
.tip i{font-style:normal;font-weight:700;font-size:10.5px;padding:1px 7px;border-radius:999px;white-space:nowrap}
.tip .tm{color:#64748b;margin:2px 0 8px}
.tip .arr{background:#f1f5f9;border-radius:9px;padding:8px 11px;display:flex;flex-wrap:wrap;align-items:baseline;
          justify-content:space-between;gap:2px 10px;margin-bottom:9px}
.tip .arr span{color:#64748b}
.tip .arr b{color:#15803d;font-size:13.5px}
.tip .arr small{flex-basis:100%;color:#b45309;font-size:10.5px}
.tip .tl{font-size:10.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:#94a3b8;margin:4px 0 5px}
.tip .rt{position:relative;padding-left:18px;margin-bottom:9px}
.tip .rt:before{content:"";position:absolute;left:5px;top:10px;bottom:14px;width:2px;background:#cbd5e1}
.tip .rn{position:relative;display:flex;justify-content:space-between;gap:10px;padding:2px 0}
.tip .rn .dt{position:absolute;left:-18px;top:5px;width:12px;height:12px;border-radius:50%;background:#38bdf8;
             border:2px solid #fff;box-shadow:0 0 0 1.5px #38bdf8}
.tip .rn.d .dt{background:#22c55e;box-shadow:0 0 0 1.5px #22c55e}
.tip .rn.t .dt{background:#f59e0b;box-shadow:0 0 0 1.5px #f59e0b}
.tip .rm b{color:#0f172a;font-size:13px}
.tip .rm small{display:block;color:#64748b;font-size:10.5px;max-width:200px}
.tip .rw{text-align:right;white-space:nowrap;color:#334155}
.tip .rw em{display:block;font-style:normal;color:#94a3b8;font-size:10px;font-weight:700}
.tip .rl{margin:1px 0;color:#0369a1;font-size:11px}
.tip .ot{width:100%;border-collapse:collapse;background:transparent;border:0;border-radius:0}
.tip .ot th,.tip .ot td{padding:3px 4px;border:0;border-top:1px solid #e2e8f0;font-size:11px;text-align:left;
                        background:transparent;color:#334155;text-transform:none;letter-spacing:0;vertical-align:middle}
.tip .ot th{color:#94a3b8;font-size:10px;text-transform:uppercase;letter-spacing:.04em}
.tip .ot td.on{color:#b45309;font-size:10.5px;border-top:0;padding-top:0}
.tip .note{color:#b45309;font-size:10.5px;margin:-3px 0 8px}
.topbar{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;flex-wrap:wrap}
.banner{--hz:100px;position:relative;height:calc(var(--hz) + 194px);border-radius:18px;overflow:hidden;
        margin:0 0 6px;color:#fff;box-shadow:0 10px 30px rgba(7,52,99,.28);isolation:isolate;
        background:linear-gradient(180deg,#0a2a66 0%,#1561b8 48%,#4cb2ee 100%)}
.banner .bn-sun{position:absolute;left:58%;top:6px;width:150px;height:150px;border-radius:50%;z-index:0;
                background:radial-gradient(circle,rgba(255,236,170,.55) 0,rgba(255,236,170,.18) 38%,transparent 68%)}
.banner .bn-cloud{position:absolute;z-index:0;height:22px;width:120px;border-radius:999px;background:rgba(255,255,255,.16);
                  filter:blur(1px);animation:bnDrift linear infinite}
.banner .bn-cloud:before,.banner .bn-cloud:after{content:"";position:absolute;background:inherit;border-radius:50%}
.banner .bn-cloud:before{width:46px;height:32px;left:20px;top:-14px}
.banner .bn-cloud:after{width:36px;height:26px;left:62px;top:-10px}
@keyframes bnDrift{from{transform:translateX(-160px)}to{transform:translateX(1500px)}}
.banner .bn-sky{position:absolute;left:0;right:0;top:0;height:var(--hz);z-index:1}
.banner .bn-city{position:absolute;bottom:0;height:70px;fill:#082a55;opacity:.62}
.banner .bn-city.hcm{right:0;width:310px}
.banner .bn-city.lch{left:0;width:210px;height:44px;opacity:.5}
.banner .bn-sea{position:absolute;left:0;right:0;top:var(--hz);bottom:0;z-index:1;
                background:linear-gradient(180deg,#1aa0e0 0%,#0b78b9 40%,#07517f 100%)}
.banner .bn-sea:before{content:"";position:absolute;inset:0;
   background:repeating-linear-gradient(180deg,transparent 0 17px,rgba(255,255,255,.1) 17px 18px) 0 14px/100% 100% no-repeat}
.banner .bn-wave{position:absolute;left:0;right:0;height:14px;background-repeat:repeat-x;animation:bnWave linear infinite}
.banner .bn-wave.w1{top:-1px;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='14'%3E%3Cpath d='M0 7Q15 0 30 7T60 7T90 7T120 7V14H0Z' fill='rgba(255,255,255,0.2)'/%3E%3C/svg%3E");
                    background-size:120px 14px;animation-duration:9s}
.banner .bn-wave.w2{bottom:0;height:20px;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='160' height='20'%3E%3Cpath d='M0 10Q20 0 40 10T80 10T120 10T160 10V20H0Z' fill='rgba(255,255,255,0.14)'/%3E%3C/svg%3E");
                    background-size:160px 20px;animation-duration:6s;animation-direction:reverse}
@keyframes bnWave{to{background-position-x:-480px}}
.banner .bn-mark{position:absolute;top:calc(var(--hz) + 3px);z-index:2;font-size:9.5px;font-weight:700;
                 letter-spacing:.14em;text-transform:uppercase;color:rgba(255,255,255,.8)}
.banner .bn-mark.l{left:12px}.banner .bn-mark.r{right:112px;text-align:right}
.banner .bn-fin{position:absolute;right:104px;top:calc(var(--hz) + 16px);bottom:6px;width:8px;z-index:2;opacity:.85;
                background:repeating-conic-gradient(#fff 0 25%,#0f172a 0 50%) 0 0/8px 8px;border-radius:2px}
.banner .bn-ship{position:absolute;z-index:calc(3 + var(--i));display:flex;align-items:flex-end;
                 top:calc(var(--hz) + 12px + var(--i) * 18px);left:10px;opacity:0;
                 animation:var(--a) 18s linear infinite}
.banner .bn-ship .pl{width:68px;text-align:center;font-size:9.5px;font-weight:800;line-height:14px;height:14px;border-radius:7px;
                     margin:0 3px 4px 0;background:var(--c);color:var(--fg);white-space:nowrap;
                     box-shadow:0 1px 3px rgba(0,0,0,.35)}
.banner .bn-ship svg{width:66px;height:30px;display:block;overflow:visible;animation:bnBob 1.7s ease-in-out infinite;
                     animation-delay:calc(var(--i) * -.37s);filter:drop-shadow(0 2px 2px rgba(0,0,0,.35))}
.banner .bn-ship .wk{position:absolute;right:60px;bottom:2px;width:96px;height:5px;border-radius:5px;z-index:-1;
                     background:linear-gradient(270deg,rgba(255,255,255,.75),rgba(255,255,255,0))}
.banner .bn-ship .bn-trophy{position:absolute;right:-2px;bottom:26px;width:38px;height:41px;opacity:0;overflow:visible;
                            transform-origin:50% 100%;animation:bnTrophy 18s linear infinite;
                            filter:drop-shadow(0 0 5px rgba(253,224,71,.95)) drop-shadow(0 2px 2px rgba(0,0,0,.4))}
@keyframes bnBob{0%,100%{transform:translateY(0) rotate(-.6deg)}50%{transform:translateY(-1.8px) rotate(.8deg)}}
.banner .bn-top{position:relative;z-index:20;display:flex;justify-content:space-between;align-items:flex-start;
                gap:16px;padding:20px 24px 0}
.banner h1{font-size:26px;line-height:1.2;margin:0 0 4px;color:#fff;text-shadow:0 2px 10px rgba(4,28,70,.55);
           font-weight:800;letter-spacing:.2px}
.banner .sub{color:rgba(255,255,255,.88);margin:0;text-shadow:0 1px 6px rgba(4,28,70,.55)}
.banner .tb-side{gap:6px}
.banner .refresh{background:#fff;color:#075985;border-color:#fff;box-shadow:0 4px 14px rgba(4,28,70,.3)}
.banner .refresh.live{background:#16a34a;color:#fff;border-color:#fff}
.banner .rinfo{color:rgba(255,255,255,.9);text-shadow:0 1px 4px rgba(4,28,70,.6)}
.banner .rinfo.stale{color:#fde68a}
@media (max-width:760px){
  .banner{--hz:196px}
  .banner h1{font-size:21px}
  .banner .bn-top{flex-direction:column;padding:16px 16px 0}
  .banner .tb-main{flex:none}
  .banner .tb-side{flex-direction:row;align-items:center;gap:10px}
  .banner .bn-city.hcm{width:190px}
  .banner .bn-fin{right:58px}
  .banner .bn-mark.r{right:70px}
}
@media (prefers-reduced-motion:reduce){
  .banner *{animation:none!important}
  .banner .bn-ship{opacity:1;left:calc(10px + (100% - 250px) * var(--f))}
  .banner .bn-ship .bn-trophy{opacity:1}
}
.tb-main{flex:1 1 420px;min-width:0}
.tb-side{display:flex;flex-direction:column;align-items:flex-end;gap:5px;flex:none}
.refresh{display:inline-flex;align-items:center;gap:7px;border:1px solid var(--accent);background:var(--accent);
         color:#fff;border-radius:999px;padding:8px 16px;font:inherit;font-weight:700;font-size:13px;cursor:pointer}
.refresh:hover{filter:brightness(.93)}
.refresh.live{background:#16a34a;border-color:#16a34a}
.refresh:disabled{opacity:.8;cursor:progress}
.refresh .ri{font-size:17px;line-height:1;display:inline-block}
.refresh.spin .ri{animation:rot 1s linear infinite}
@keyframes rot{to{transform:rotate(360deg)}}
.rinfo{font-size:11.5px;color:var(--muted);text-align:right}
.rinfo.stale{color:#b45309;font-weight:600}
.toast{position:fixed;right:18px;bottom:18px;background:#0f172a;color:#fff;padding:10px 16px;
       border-radius:10px;font-size:13px;box-shadow:0 6px 20px rgba(0,0,0,.25);z-index:50}
.toast.err{background:#b91c1c}
.mask{position:fixed;inset:0;background:rgba(15,23,42,.45);display:flex;align-items:center;
      justify-content:center;z-index:60;padding:16px}
.dlg{background:#fff;border-radius:14px;padding:22px 24px;max-width:480px;width:100%;
     box-shadow:0 18px 50px rgba(0,0,0,.3);font-size:13.5px;line-height:1.55}
.dlg h3{margin:0 0 10px;font-size:17px}
.dlg p{margin:0 0 10px}
.dlg code{background:#f1f5f9;border-radius:5px;padding:1px 6px;font-size:12.5px}
.dbtn{display:flex;gap:8px;justify-content:flex-end;margin-top:14px}
.dbtn button{border:1px solid var(--accent);background:var(--accent);color:#fff;border-radius:8px;
             padding:7px 16px;font:inherit;font-weight:600;cursor:pointer}
.dbtn button.sec{background:#fff;color:var(--muted);border-color:var(--line)}
.foot{color:var(--muted);font-size:12px;margin-top:30px;text-align:center}
"""

JS = r"""
var LIVE = false;        // true when served by `build_hcm_schedule.py --serve` (can pull fresh data on demand)
var curOrigin='all';     // origin-port filter: all | Bangkok | Laem Chabang
var refreshing = false;

function initDash(){
  // click a row to expand the per-carrier details
  document.querySelectorAll('tr.main').forEach(function(r){
    r.addEventListener('click',function(){
      var n=r.nextElementSibling;
      if(n&&n.classList.contains('details'))n.classList.toggle('show');
    });
  });
  // month selector: .mtabs[data-panels="xxx"] controls the panels with class .xxx whose data-m matches
  document.querySelectorAll('.mtabs').forEach(function(group){
    var cls=group.getAttribute('data-panels');
    group.querySelectorAll('.mtab').forEach(function(t){
      t.addEventListener('click',function(){
        group.querySelectorAll('.mtab').forEach(function(x){x.classList.remove('active');});
        t.classList.add('active');
        document.querySelectorAll('.'+cls).forEach(function(p){
          p.hidden = (p.getAttribute('data-m') !== t.getAttribute('data-m'));
        });
      });
    });
  });
  // week filter inside that month's detail table
  document.querySelectorAll('.wtabs').forEach(function(group){
    var panel=group.closest('.detpanel');
    group.querySelectorAll('.wtab').forEach(function(t){
      t.addEventListener('click',function(){
        group.querySelectorAll('.wtab').forEach(function(x){x.classList.remove('active');});
        t.classList.add('active');
        var w=t.getAttribute('data-w');
        panel.querySelectorAll('tr.main').forEach(function(r){
          r.classList.toggle('wk-off', w!=='all' && r.getAttribute('data-w')!==w);
        });
      });
    });
  });
  // carrier filter: click a card = toggle it, double-click = show only that carrier (again = show all).
  // One control drives both the calendar and the detail table.
  document.querySelectorAll('.cc').forEach(function(card){
    card.addEventListener('click',function(){ card.classList.toggle('off'); applyCarrierFilter(); });
    card.addEventListener('dblclick',function(e){
      e.preventDefault();
      var all=[].slice.call(document.querySelectorAll('.cc'));
      var solo=!card.classList.contains('off') && all.every(function(x){return x===card||x.classList.contains('off');});
      all.forEach(function(x){ x.classList.toggle('off', solo ? false : x!==card); });
      applyCarrierFilter();
    });
  });
  var selAll=document.getElementById('ccAll');
  if(selAll) selAll.addEventListener('click',function(){
    document.querySelectorAll('.cc').forEach(function(x){x.classList.remove('off');});
    applyCarrierFilter();
  });
  // origin port filter (Bangkok / Laem Chabang): works together with the carrier cards
  var oa=document.querySelector('.otab.active'); curOrigin=oa?oa.getAttribute('data-o'):'all';
  document.querySelectorAll('.otab').forEach(function(t){
    t.addEventListener('click',function(){
      document.querySelectorAll('.otab').forEach(function(x){x.classList.remove('active');});
      t.classList.add('active'); curOrigin=t.getAttribute('data-o'); applyCarrierFilter();
    });
  });
  applyCarrierFilter();
  // refresh button
  var b=document.getElementById('refreshBtn');
  if(b) b.addEventListener('click', doRefresh);
  applyMode();
  tickAge();
}

// ---- "last updated ..." status ----
function fmtAge(ms){
  var m=Math.floor(ms/60000);
  if(m<1) return 'just now';
  if(m<60) return m+' min ago';
  var h=Math.floor(m/60);
  if(h<48) return h+' h ago';
  return Math.floor(h/24)+' d ago';
}
function tickAge(){
  var info=document.getElementById('refreshInfo'), el=document.getElementById('rAge');
  if(!info||!el) return;
  var gen=Date.parse(info.getAttribute('data-gen'));
  if(isNaN(gen)) return;
  var age=Date.now()-gen;
  el.textContent=fmtAge(age);
  info.classList.toggle('stale', age>12*3600*1000);   // older than 12 h = amber warning
}
setInterval(tickAge, 30000);

// ---- button mode: LIVE (pulls fresh data) or reload the latest published data ----
function applyMode(){
  var b=document.getElementById('refreshBtn');
  if(!b) return;
  var lbl=b.querySelector('.rt');
  b.classList.toggle('live', LIVE);
  if(LIVE){
    lbl.textContent='Refresh (live)';
    b.title='Pull fresh data from the carriers right now (takes ~1-2 minutes)';
  }else if(location.protocol==='file:'){
    lbl.textContent='Refresh';
    b.title='Opened from a file: click to switch to live mode (start the helper with run_hcm_dashboard.bat)';
  }else{
    lbl.textContent='Refresh';
    b.title='Reload the latest published data (for a live pull, run with --serve)';
  }
}
function probeLive(){
  if(location.protocol==='file:') return;
  fetch('/api/status',{cache:'no-store'}).then(function(r){return r.ok?r.json():null;})
    .then(function(j){ if(j&&j.live){ LIVE=true; applyMode(); } }).catch(function(){});
}

// A sailing is visible when at least one of its carriers is switched on
function applyCarrierFilter(){
  var on={}, nOn=0, nAll=0;
  document.querySelectorAll('.cc').forEach(function(b){
    nAll++;
    var isOn=!b.classList.contains('off');
    if(isOn){ on[b.getAttribute('data-c')]=1; nOn++; }
    b.setAttribute('aria-pressed', isOn?'true':'false');
  });
  var all=(nOn===nAll);
  function visible(el){
    if(curOrigin!=='all' && el.getAttribute('data-origin')!==curOrigin) return false;
    if(all) return true;
    return (el.getAttribute('data-carriers')||'').split(',').some(function(c){return on[c];});
  }
  // a sailing is painted in the colour of the first carrier that is switched on (so picking KMTC shows the
  // KMTC colour); the dots mark every carrier that can book it, greyed out when that carrier is off
  var col={};
  document.querySelectorAll('.cc').forEach(function(b){ col[b.getAttribute('data-c')]=getComputedStyle(b).getPropertyValue('--c').trim(); });
  function fgOf(hex){
    hex=hex.replace('#',''); if(hex.length===3) hex=hex.split('').map(function(c){return c+c;}).join('');
    var r=parseInt(hex.substr(0,2),16), g=parseInt(hex.substr(2,2),16), b=parseInt(hex.substr(4,2),16);
    return (0.299*r+0.587*g+0.114*b)/255>0.62 ? '#1a1a1a' : '#fff';
  }
  document.querySelectorAll('.cal .ev').forEach(function(ev){
    ev.hidden=!visible(ev);
    var pick = all ? null : (ev.getAttribute('data-carriers')||'').split(',').filter(function(c){return on[c];})[0];
    if(pick && col[pick]){ ev.style.background=col[pick]; ev.style.color=fgOf(col[pick]); }
    else { ev.style.background=ev.getAttribute('data-bg'); ev.style.color=ev.getAttribute('data-fg'); }
    ev.querySelectorAll('.cd').forEach(function(d){ d.style.opacity=(all||on[d.getAttribute('data-c')])?1:.25; });
  });
  var shown=0, total=0;
  document.querySelectorAll('tr.main').forEach(function(r){
    var v=visible(r);
    r.classList.toggle('c-off', !v);
    total++; if(v) shown++;
  });
  var st=document.getElementById('ccStat');
  if(st) st.textContent=shown+' of '+total+' sailings shown';
}

// ---- remember the selection (month/week/carrier) before swapping the content, restore it after the refresh ----
function snapshot(){
  var s={off:[],m:{},w:{},o:curOrigin};
  document.querySelectorAll('.cc.off').forEach(function(b){ s.off.push(b.getAttribute('data-c')); });
  document.querySelectorAll('.mtabs').forEach(function(g){
    var a=g.querySelector('.mtab.active');
    if(a) s.m[g.getAttribute('data-panels')]=a.getAttribute('data-m');
  });
  document.querySelectorAll('.detpanel').forEach(function(p){
    var a=p.querySelector('.wtab.active');
    if(a) s.w[p.getAttribute('data-m')]=a.getAttribute('data-w');
  });
  return s;
}
function restore(s){
  if(s.o && s.o!=='all'){ var ob=document.querySelector('.otab[data-o="'+s.o+'"]'); if(ob) ob.click(); }
  document.querySelectorAll('.mtabs').forEach(function(g){
    var want=s.m[g.getAttribute('data-panels')];
    if(!want) return;
    var b=g.querySelector('.mtab[data-m="'+want+'"]');
    if(b) b.click();
  });
  document.querySelectorAll('.detpanel').forEach(function(p){
    var want=s.w[p.getAttribute('data-m')];
    if(!want||want==='all') return;
    var b=p.querySelector('.wtab[data-w="'+want+'"]');
    if(b) b.click();
  });
  if(s.off&&s.off.length){
    document.querySelectorAll('.cc').forEach(function(b){
      if(s.off.indexOf(b.getAttribute('data-c'))!==-1) b.classList.add('off');
    });
    applyCarrierFilter();
  }
}

function toast(msg, isErr){
  var t=document.createElement('div');
  t.className='toast'+(isErr?' err':'');
  t.textContent=msg;
  document.body.appendChild(t);
  setTimeout(function(){ if(t.parentNode) t.parentNode.removeChild(t); }, 4200);
}

// Opened from an .html file (file://): the page cannot fetch data itself, so it looks for the local helper
// (started with run_hcm_dashboard.bat / --serve); if found it hands over to the helper's live page, otherwise it explains how to start it
function showHelp(){
  var gi=document.getElementById('refreshInfo');
  var when=gi?gi.textContent.split('·')[0].trim():'';
  var m=document.createElement('div');
  m.className='mask';
  m.innerHTML='<div class="dlg"><h3>Live refresh</h3>'
    +'<p>This file shows the data as of when it was generated ('+when+') — a page opened from a file cannot pull data from the carriers by itself.</p>'
    +'<p><b>To pull live data:</b> double-click <code>run_hcm_dashboard.bat</code> (in the project folder). The dashboard will reopen and its Refresh button will then pull fresh data.</p>'
    +'<p style="color:#64748b;font-size:12px">Or run <code>python build_hcm_schedule.py</code> yourself, then click "Reload file" below.</p>'
    +'<div class="dbtn"><button type="button" id="dlgReload">Reload file</button><button type="button" id="dlgClose" class="sec">Close</button></div></div>';
  document.body.appendChild(m);
  document.getElementById('dlgClose').onclick=function(){ m.remove(); };
  document.getElementById('dlgReload').onclick=function(){ location.reload(); };
  m.addEventListener('click',function(e){ if(e.target===m) m.remove(); });
}
function fileModeRefresh(){
  var base='http://127.0.0.1:@@PORT@@';
  var btn=document.getElementById('refreshBtn');
  var lbl=btn.querySelector('.rt');
  btn.disabled=true; btn.classList.add('spin'); lbl.textContent='Looking for the helper…';
  // no-cors: the server needs no CORS setup — we only need to know whether it is reachable
  fetch(base+'/api/status',{mode:'no-cors',cache:'no-store'}).then(function(){
    toast('Helper found, opening the live page…');
    location.href=base+'/@@PAGE@@';
  }).catch(function(){
    btn.disabled=false; btn.classList.remove('spin'); applyMode(); showHelp();
  });
}

async function doRefresh(){
  if(refreshing) return;
  if(location.protocol==='file:'){ fileModeRefresh(); return; }
  refreshing=true;
  var btn=document.getElementById('refreshBtn');
  var lbl=btn.querySelector('.rt');
  btn.disabled=true; btn.classList.add('spin');
  var t0=Date.now();
  var timer=setInterval(function(){
    lbl.textContent=(LIVE?'Pulling data… ':'Loading… ')+Math.floor((Date.now()-t0)/1000)+' s';
  },500);
  var snap=snapshot();
  var oldInfo=document.getElementById('refreshInfo');
  var oldGen=oldInfo?oldInfo.getAttribute('data-gen'):'';
  try{
    if(LIVE){
      var r=await fetch('/api/refresh',{method:'POST',headers:{'X-Requested-With':'refresh'}});
      var j=await r.json();
      if(!j.ok) throw new Error(j.error||('HTTP '+r.status));
    }
    var url=location.href.split('#')[0].split('?')[0]+'?_='+Date.now();
    var res=await fetch(url,{cache:'no-store'});
    if(!res.ok) throw new Error('HTTP '+res.status);
    var doc=new DOMParser().parseFromString(await res.text(),'text/html');
    var neu=doc.querySelector('.wrap');
    if(!neu) throw new Error('The response is not the dashboard');
    var ni=neu.querySelector('#refreshInfo');
    var newGen=ni?ni.getAttribute('data-gen'):'';
    document.querySelector('.wrap').innerHTML=neu.innerHTML;
    initDash();
    restore(snap);
    toast(LIVE ? 'Live data pulled ✓' : (newGen!==oldGen ? 'Updated to the latest data ✓' : 'This is already the latest published data'));
  }catch(e){
    toast('Refresh failed: '+e.message, true);
    btn.disabled=false; btn.classList.remove('spin'); applyMode();
  }finally{
    clearInterval(timer); refreshing=false;
  }
}

// ---- hover card on calendar events: vessel, routing and arrival time ----
var _sd=null, _sdEl=null, tipEl=null;
function sailData(){
  var el=document.getElementById('sailData');
  if(!el) return [];
  if(el!==_sdEl){ _sdEl=el; try{ _sd=JSON.parse(el.textContent); }catch(e){ _sd=[]; } }
  return _sd;
}
function esc(s){
  return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});
}
function tipNode(cls, name, terminal, label, when){
  return '<div class="rn '+cls+'"><i class="dt"></i><div class="rm"><b>'+esc(name)+'</b>'
    +(terminal?'<small>'+esc(terminal)+'</small>':'')+'</div>'
    +'<span class="rw">'+(when?'<em>'+label+'</em>'+esc(when):'')+'</span></div>';
}
function tipHtml(s){
  var h='<div class="th"><b>'+esc(s.v)+'</b><span class="tc">'+s.c.map(function(c){
    return '<i style="background:'+c.col+';color:'+c.fg+'">'+esc(c.n)+'</i>'; }).join('')+'</span></div>';
  h+='<div class="tm">'+esc(s.t)+(s.tt?' &middot; '+esc(s.tt)+' days transit':'')+'</div>';
  h+='<div class="arr"><span>Arrives '+esc(s.pod)+'</span><b>'+esc(s.eta||'not published')+'</b>'
    +(s.etaVar?'<small>ETA differs by carrier &mdash; see the table below</small>':'')+'</div>';
  if(s.off && s.o.length) h+='<div class="note">Listed by the carrier as '+esc(s.o[0].r)+'</div>';
  h+='<div class="tl">Routing</div><div class="rt">';
  h+=tipNode('o', s.pol, s.polT, 'ETD', s.etd);
  var lab=(s.t==='Direct'?'Direct':'Transshipment')+(s.svc?' &middot; service '+esc(s.svc):'');
  h+='<div class="rl">'+lab+'</div>';
  (s.ts||[]).forEach(function(t){
    h+=tipNode('t', t.p, 'transshipment port', 'T/S ETD', t.e)+'<div class="rl">onward</div>';
  });
  h+=tipNode('d', s.pod, s.podT, 'ETA', s.eta)+'</div>';
  h+='<table class="ot"><tr><th>Carrier</th><th>Voyage</th><th>Service</th><th>ETD</th><th>ETA</th></tr>';
  s.o.forEach(function(o){
    h+='<tr><td><i style="background:'+o.col+';color:'+o.fg+'">'+esc(o.n)+'</i></td><td>'+esc(o.voy||'—')+'</td><td>'
      +esc(o.svc||'—')+'</td><td>'+esc(o.etd||'—')+'</td><td>'+esc(o.eta||'—')+'</td></tr>';
    if(o.r) h+='<tr><td colspan="5" class="on">'+esc(o.n)+' route: '+esc(o.r)+'</td></tr>';
  });
  return h+'</table>';
}
function placeTip(x,y){
  var w=tipEl.offsetWidth, h=tipEl.offsetHeight, vw=window.innerWidth, vh=window.innerHeight;
  var l=x+16, t=y+16;
  if(l+w>vw-8) l=Math.max(8, x-w-16);
  if(t+h>vh-8) t=Math.max(8, vh-h-8);
  tipEl.style.left=l+'px'; tipEl.style.top=t+'px';
}
function showTip(ev,x,y){
  var s=sailData()[+ev.getAttribute('data-i')];
  if(!s) return;
  if(!tipEl){ tipEl=document.createElement('div'); tipEl.className='tip'; document.body.appendChild(tipEl); }
  tipEl.innerHTML=tipHtml(s);
  tipEl.style.display='block';
  placeTip(x,y);
}
function hideTip(){ if(tipEl) tipEl.style.display='none'; }
function evOf(e){ return e.target && e.target.closest ? e.target.closest('.cal .ev') : null; }
document.addEventListener('mouseover',function(e){ var ev=evOf(e); if(ev) showTip(ev,e.clientX,e.clientY); });
document.addEventListener('mousemove',function(e){
  if(!tipEl||tipEl.style.display!=='block') return;
  if(!evOf(e)) hideTip(); else placeTip(e.clientX,e.clientY);
});
document.addEventListener('mouseout',function(e){ if(evOf(e) && !(e.relatedTarget && evOf({target:e.relatedTarget}))) hideTip(); });
window.addEventListener('scroll',hideTip,true);
// touch screens have no hover: tap an event to open the card, tap anywhere else to close it
document.addEventListener('click',function(e){
  if(!(window.matchMedia && matchMedia('(hover: none)').matches)) return;
  var ev=evOf(e);
  if(!ev){ hideTip(); return; }
  var r=ev.getBoundingClientRect(); showTip(ev, r.left, r.bottom);
});

initDash();
probeLive();
""".replace("@@PORT@@", str(DEFAULT_PORT)).replace("@@PAGE@@", PAGE_NAME)


def _calendar(merged: list[dict], start: dt.date, end: dt.date) -> str:
    """One calendar with month selector buttons (one month shown at a time)"""
    by_day: dict[str, list[dict]] = {}
    for m in merged:
        if m["etd_date"]:
            by_day.setdefault(m["etd_date"], []).append(m)

    def carrier_color(m):
        return SOURCE_META.get(m["carriers"][0], {}).get("color", DEFAULT_COLOR)

    dows = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    months: list[dt.date] = []
    cur = dt.date(start.year, start.month, 1)
    last = dt.date(end.year, end.month, 1)
    while cur <= last:
        months.append(cur)
        cur = dt.date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)

    def month_count(mo: dt.date) -> int:
        pre = f"{mo:%Y-%m}"
        return sum(len(v) for k, v in by_day.items() if k.startswith(pre))

    # default month = the first month that has sailings (the first month if none do)
    default_idx = next((i for i, mo in enumerate(months) if month_count(mo)), 0)

    tabs, panels = [], []
    for i, mo in enumerate(months):
        ym = f"{mo:%Y-%m}"
        is_def = (i == default_idx)
        tabs.append(
            f"<button class='mtab{' active' if is_def else ''}' data-m='{ym}'>"
            f"{mo:%b %Y}<span class='cnt'>{month_count(mo)}</span></button>")

        first_dow = mo.weekday()
        nxt = dt.date(mo.year + (mo.month == 12), (mo.month % 12) + 1, 1)
        ndays = (nxt - mo).days
        cells = ["<div class='cell dim'></div>"] * first_dow
        for day in range(1, ndays + 1):
            iso = dt.date(mo.year, mo.month, day).isoformat()
            evs = by_day.get(iso, [])
            def dots(e):
                """one coloured dot per carrier that can book the sailing (only when there is more than one)"""
                if len(e["carriers"]) < 2:
                    return ""
                return "".join(
                    f"<i class='cd' data-c='{html.escape(c)}' "
                    f"style='background:{SOURCE_META.get(c, {}).get('color', DEFAULT_COLOR)}'></i>"
                    for c in e["carriers"])

            ev_html = "".join(
                f"<div class='ev' style='background:{carrier_color(e)};color:{_fg(carrier_color(e))}' "
                f"data-bg='{carrier_color(e)}' data-fg='{_fg(carrier_color(e))}' "
                f"data-carriers='{html.escape(','.join(e['carriers']))}' "
                f"data-origin='{html.escape(e['origin'])}' data-i='{e['_i']}'>"
                f"<span class='et'>{html.escape(e['vessel'][:22])} <small>{_origin_abbr(e['origin'])}</small></span>"
                f"{dots(e)}</div>"
                for e in evs)
            cells.append(f"<div class='cell'><div class='d'>{day}</div>{ev_html}</div>")
        head = "".join(f"<div class='h'>{d}</div>" for d in dows)
        panels.append(
            f"<div class='calpanel' data-m='{ym}'{'' if is_def else ' hidden'}>"
            f"<div class='cal'>{head}{''.join(cells)}</div></div>")

    return (f"<div class='mtabs' data-panels='calpanel'>{''.join(tabs)}</div>"
            f"{''.join(panels)}")


def _detail_by_month(merged: list[dict], start: dt.date, end: dt.date) -> str:
    """Sailing detail table: month selector buttons, with a week filter inside each month"""
    months: list[dt.date] = []
    cur = dt.date(start.year, start.month, 1)
    last = dt.date(end.year, end.month, 1)
    while cur <= last:
        months.append(cur)
        cur = dt.date(cur.year + (cur.month == 12), (cur.month % 12) + 1, 1)

    by_month: dict[str, list[dict]] = {}
    for m in merged:
        if m["etd_date"]:
            by_month.setdefault(m["etd_date"][:7], []).append(m)

    default_idx = next((i for i, mo in enumerate(months)
                        if by_month.get(f"{mo:%Y-%m}")), 0)

    head = ("<tr><th>ETD date</th><th>Origin</th><th>Vessel</th><th>ETD</th><th>ETA</th>"
            "<th>Transit (days)</th><th>Type</th><th>Bookable via</th></tr>")
    tabs, panels = [], []
    for i, mo in enumerate(months):
        ym = f"{mo:%Y-%m}"
        items = sorted(by_month.get(ym, []),
                       key=lambda m: (m["etd_date"] or "", m["vessel"]))
        is_def = (i == default_idx)
        tabs.append(
            f"<button class='mtab{' active' if is_def else ''}' data-m='{ym}'>"
            f"{mo:%b %Y}<span class='cnt'>{len(items)}</span></button>")

        # group by week (the Monday of the week the vessel departs)
        m_last = dt.date(mo.year + (mo.month == 12), (mo.month % 12) + 1, 1) - dt.timedelta(days=1)
        wk: dict[dt.date, int] = {}
        for it in items:
            d = dt.date.fromisoformat(it["etd_date"])
            wk[d - dt.timedelta(days=d.weekday())] = wk.get(d - dt.timedelta(days=d.weekday()), 0) + 1

        wbtns = [f"<button class='wtab active' data-w='all'>Whole month"
                 f"<span class='cnt'>{len(items)}</span></button>"]
        for monday in sorted(wk):
            a = max(monday, mo)
            b = min(monday + dt.timedelta(days=6), m_last)
            lbl = (f"{a.day}–{b.day} {mo:%b}" if a.month == b.month
                   else f"{a.day} {a:%b}–{b.day} {b:%b}")
            wbtns.append(f"<button class='wtab' data-w='{monday.isoformat()}'>{lbl}"
                         f"<span class='cnt'>{wk[monday]}</span></button>")
        wtabs_html = f"<div class='wtabs'>{''.join(wbtns)}</div>" if len(wbtns) > 1 else ""

        body = "".join(_detail_row(m) for m in items) or (
            "<tr><td colspan='8' style='color:var(--muted)'>No sailings this month</td></tr>")
        panels.append(
            f"<div class='detpanel' data-m='{ym}'{'' if is_def else ' hidden'}>"
            f"{wtabs_html}<table>{head}{body}</table></div>")

    return (f"<div class='mtabs' data-panels='detpanel'>{''.join(tabs)}</div>"
            f"{''.join(panels)}")


def _detail_row(m: dict) -> str:
    if m["etd_date"]:
        d = dt.date.fromisoformat(m["etd_date"])
        wk = (d - dt.timedelta(days=d.weekday())).isoformat()
    else:
        wk = ""
    badges = ""
    for c in m["carriers"]:
        col = SOURCE_META.get(c, {}).get("color", DEFAULT_COLOR)
        badges += (f"<span class='badge' style='background:{col};color:{_fg(col)}'>"
                   f"{html.escape(c)}</span>")
    tag = "tag-direct" if m["direct_or_ts"] == "Direct" else "tag-ts"
    sub = []
    for o in m["offers"]:
        sub.append(
            "<tr><td>" + html.escape(o["carrier"]) + "</td>"
            "<td>" + html.escape(o["voyage"] or "—") + "</td>"
            "<td>" + html.escape(o["service"] or "—") + "</td>"
            "<td>" + html.escape(o["etd"] or "—") + "</td>"
            "<td>" + html.escape(o["eta"] or "—") + "</td>"
            "<td>" + html.escape(f"{o['transit_days']:g}" if o["transit_days"] else "—") + "</td>"
            "<td>" + html.escape(o["pol_terminal"] or "—") + "</td>"
            "<td>" + html.escape(" / ".join(
                x for x in [o["doc_cutoff"], o["cy_cutoff"], o["vgm_cutoff"]] if x) or "—")
            + "</td></tr>")
    detail = (
        "<tr class='details'><td colspan='8'><table>"
        "<tr><th>Carrier / service</th><th>Voyage</th><th>Service</th><th>ETD</th>"
        "<th>ETA</th><th>Transit</th><th>Origin terminal</th><th>Cut-off (Doc/CY/VGM)</th></tr>"
        + "".join(sub) + "</table></td></tr>")
    carriers_attr = html.escape(",".join(m["carriers"]))
    return (
        f"<tr class='main' data-w='{wk}' data-carriers='{carriers_attr}' data-origin='{html.escape(m['origin'])}'>"
        f"<td>{html.escape(m['etd_date'] or '—')}</td>"
        f"<td><span class='pill'>{html.escape(m['origin'])}</span></td>"
        f"<td><b>{html.escape(m['vessel'])}</b></td>"
        f"<td>{html.escape(m['etd'] or '—')}</td>"
        f"<td>{html.escape(m['eta'] or '—')}</td>"
        f"<td>{html.escape(transit_text(m['transit_days']) or '—')}</td>"
        f"<td><span class='pill {tag}'>{html.escape(m['direct_or_ts'])}</span></td>"
        f"<td>{badges}</td></tr>{detail}")


LOGO_DIR = HERE / "logos"
# File name (without extension) of each source's logo inside logos/ — drop e.g. logos/sitc.png or
# logos/kmtc.png in there and the card picks it up on the next build; a text badge is used until then.
LOGO_KEYS = {"SITC": "sitc", "T.S. Lines": "ts-lines", "KMTC": "kmtc", "HAL": "hal",
             "CU Lines": "cu-lines", "COSCO": "cosco", "Yang Ming": "yang-ming", "SJJ": "sjj"}
LOGO_CROP = {"cu-lines": 6, "sitc": 70}   # px cut from every edge first (the supplied JPGs come with a
                                           # grey frame / soft shadow around the logo)
_logo_cache: dict = {}


def _logo_data_uri(source: str) -> str | None:
    """The carrier's logo from logos/ as a small base64 data URI, so the dashboard stays one file."""
    if source in _logo_cache:
        return _logo_cache[source]
    key = LOGO_KEYS.get(source) or re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")
    uri = None
    files = sorted(LOGO_DIR.glob(key + ".*")) if LOGO_DIR.is_dir() else []
    if files:
        p = files[0]
        try:
            from PIL import Image, ImageChops
            im = Image.open(p).convert("RGBA")
            crop = LOGO_CROP.get(key, 0)
            if crop:
                im = im.crop((crop, crop, im.width - crop, im.height - crop))
            flat = Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im).convert("RGB")
            diff = ImageChops.difference(flat, Image.new("RGB", im.size, (255, 255, 255)))
            box = diff.point(lambda v: 255 if v > 12 else 0).getbbox()      # trim the white margins
            if box:
                pad = 2
                im = im.crop((max(box[0] - pad, 0), max(box[1] - pad, 0),
                              min(box[2] + pad, im.width), min(box[3] + pad, im.height)))
            if im.height > 72:                                              # 2x of the 36px it is shown at
                resample = getattr(Image, "Resampling", Image).LANCZOS
                im = im.resize((max(1, round(im.width * 72 / im.height)), 72), resample)
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
            data, mime = buf.getvalue(), "image/png"
        except Exception:                                                   # no Pillow / unreadable: embed as is
            mime = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".webp": "image/webp", ".svg": "image/svg+xml"}.get(p.suffix.lower(), "image/png")
            data = p.read_bytes()
        uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    _logo_cache[source] = uri
    return uri


def _carrier_filter_bar(merged: list[dict]) -> str:
    """
    Carrier cards (logo + name + sailing count) that double as the legend.
    Click = toggle a carrier, double-click = show only that carrier. The selection filters the
    calendar and the sailing detail table at the same time, across the whole page.
    """
    counts: dict[str, int] = {}
    for m in merged:
        for c in m["carriers"]:
            counts[c] = counts.get(c, 0) + 1

    cards = []
    for name, meta in SOURCE_META.items():
        if name not in counts:
            continue
        col = meta["color"]
        r, g, b = (int(col[i:i + 2], 16) for i in (1, 3, 5))
        uri = _logo_data_uri(name)
        if uri:
            logo = f"<span class='lg'><img src='{uri}' alt=''></span>"
        else:
            logo = f"<span class='lg tx' style='background:{col};color:{_fg(col)}'>{html.escape(name)}</span>"
        label = html.escape(meta["label"])
        cards.append(
            f"<button type='button' class='cc' data-c='{html.escape(name)}' aria-pressed='true' "
            f"style='--c:{col};--cs:rgba({r},{g},{b},.2)' "
            f"title='Click to toggle · double-click to show only {label}'>"
            f"{logo}<span class='ct'><b>{label}</b><i>{counts[name]} sailings</i></span></button>")
    return ("<div class='ch'>Choose carriers (click a logo to toggle · double-click to show only that carrier)</div>"
            f"<div class='cgrid'>{''.join(cards)}</div>"
            "<div class='cbar'><button type='button' id='ccAll'>Select all</button><span id='ccStat'></span></div>")


def _fmt_when(s: str | None, short: bool = False) -> str:
    """'2026-10-09 23:00' -> 'Fri 09 Oct 2026 23:00' (short: '09 Oct 23:00'); date-only values stay date-only"""
    if not s:
        return ""
    try:
        d = dt.datetime.fromisoformat(s) if len(s) > 10 else dt.datetime.combine(dt.date.fromisoformat(s), dt.time())
    except ValueError:
        return s
    t = f" {d:%H:%M}" if len(s) > 10 else ""
    return (f"{d:%d %b}" if short else f"{d:%a %d %b %Y}") + t


def _is_bkk(s: str | None) -> bool:
    u = (s or "").strip().upper()
    return "BANGKOK" in u or u in {"THBKK", "BKK"}


def _is_lch(s: str | None) -> bool:
    u = (s or "").strip().upper()
    return "LAEM" in u or u in {"THLCB", "THLCH", "LCH", "LCB"}


def _is_hcm(s: str | None) -> bool:
    u = (s or "").strip().upper()
    return "HO CHI" in u or "HOCHI" in u or "SAIGON" in u or u in {"VNSGN", "SGN", "VNHCM", "HCM"}


def _port_name(s: str | None) -> str:
    if _is_bkk(s):
        return "Bangkok"
    if _is_lch(s):
        return "Laem Chabang"
    if _is_hcm(s):
        return POD_NAME
    t = (s or "").strip()
    return t.title() if t.isupper() else t


def _origin_key(s: str | None) -> str:
    """Bangkok and Laem Chabang departures of the same vessel are different sailings."""
    return "BKK" if _is_bkk(s) else "LCH" if _is_lch(s) else (s or "").strip().upper()


def _origin_abbr(origin: str) -> str:
    return {"Bangkok": "BKK", "Laem Chabang": "LCH"}.get(origin, origin[:3].upper())


def _clip(s: str | None, n: int = 64) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _origin_bar(merged: list[dict]) -> str:
    """Origin-port selector (All / Bangkok / Laem Chabang); filters the calendar and the table together."""
    counts: dict[str, int] = {}
    for m in merged:
        counts[m["origin"]] = counts.get(m["origin"], 0) + 1
    btns = [f"<button type='button' class='otab active' data-o='all'>All origins"
            f"<span class='cnt'>{len(merged)}</span></button>"]
    for o in ORIGINS:
        if o in counts:
            btns.append(f"<button type='button' class='otab' data-o='{html.escape(o)}'>{html.escape(o)}"
                        f"<span class='cnt'>{counts[o]}</span></button>")
    return f"<div class='ch'>Origin port</div><div class='otabs'>{''.join(btns)}</div>"


def _sailing_payload(m: dict) -> dict:
    """Everything the calendar hover card shows for one merged sailing (vessel, routing, arrival)."""
    offers = m["offers"]
    main = next((o for o in offers if _is_hcm(o["pod"])), offers[0])
    pol_t = next((o["pol_terminal"] for o in [main] + offers if o.get("pol_terminal")), None)
    pod_t = next((o["pod_terminal"] for o in [main] + offers if o.get("pod_terminal")), None)
    etas = {o["eta"] for o in offers if o.get("eta")}

    ts, seen = [], set()
    for o in offers:
        if o.get("ts_place") and o["ts_place"] not in seen:
            seen.add(o["ts_place"])
            ts.append({"p": o["ts_place"], "e": _fmt_when(o.get("ts_etd"))})

    def color(c):
        col = SOURCE_META.get(c, {}).get("color", DEFAULT_COLOR)
        return col, _fg(col)

    rows = []
    for o in offers:
        col, fg = color(o["carrier"])
        rows.append({
            "n": o["carrier"], "col": col, "fg": fg,
            "voy": o.get("voyage") or "", "svc": o.get("service") or "",
            "etd": _fmt_when(o.get("etd"), short=True), "eta": _fmt_when(o.get("eta"), short=True),
            "r": "",
        })

    return {
        "v": m["vessel"], "t": m["direct_or_ts"], "tt": transit_text(m["transit_days"]),
        "pol": m["origin"] or _port_name(main["pol"]), "pod": POD_NAME,
        "polT": _clip(pol_t), "podT": _clip(pod_t),
        "etd": _fmt_when(m["etd"] or m["etd_date"]), "eta": _fmt_when(m["eta"]),
        "etaVar": len(etas) > 1,
        "svc": " / ".join(dict.fromkeys(o["service"] for o in offers if o.get("service"))),
        "ts": ts,
        "off": False,
        "c": [{"n": c, "col": color(c)[0], "fg": color(c)[1]} for c in m["carriers"]],
        "o": rows,
    }


def _banner(merged, statuses, start, end, gen) -> str:
    """Header banner: one ship per carrier racing from Bangkok / Laem Chabang to Ho Chi Minh City (pure CSS animation)."""
    names = [n for n in SOURCE_META if any(n in m["carriers"] for m in merged)]
    # finishing order (fixed, shuffled) and the wobble of each ship's pace so the lead keeps changing
    others = iter([2, 5, 1, 7, 3, 6, 4, 8, 9])           # finishing places of the other carriers (fixed, shuffled)
    ks = [3, 2, 3, 1, 2, 3, 1, 2]                    # wobble of each ship's pace, so the lead keeps changing
    amps = [.10, .09, .08, .12, .09, .10, .08, .11]
    kf, ships = [], []
    for i, name in enumerate(names):
        meta = SOURCE_META[name]
        col = meta["color"]
        win = name == "HAL"
        place = 0 if win else next(others)           # HAL always wins
        fin = 1 - 0.03 * place                     # where the ship parks; HAL alone reaches the line
        t_fin = 54 + 3.4 * place                     # % of the 18 s cycle at which this ship crosses the line
        k, amp = (1, 0.14) if win else (ks[i % 8], amps[i % 8])   # k=1 keeps HAL's wobble on the leading side
        stops = []
        for st in range(0, 17):
            u = st / 16
            p = fin * (u + amp * math.sin(math.pi * k * u))
            stops.append(f"{3 + (t_fin - 3) * u:.2f}%{{left:calc(10px + (100% - 250px) * {max(p, 0):.4f});opacity:1}}")
        end_p = f"left:calc(10px + (100% - 250px) * {fin:.3f})"
        if win:
            kf.append(
                f"@keyframes bnTrophy{{0%,{t_fin:.1f}%{{opacity:0;transform:translateY(8px) scale(.3)}}"
                f"{t_fin + 3:.1f}%{{opacity:1;transform:translateY(-3px) scale(1.3) rotate(-8deg)}}"
                f"{t_fin + 5:.1f}%{{opacity:1;transform:translateY(0) scale(1)}}"
                f"{t_fin + 7:.1f}%{{transform:translateY(-2px) scale(1.08) rotate(6deg)}}"
                f"{t_fin + 9:.1f}%,100%{{opacity:1;transform:translateY(0) scale(1)}}}}")
        kf.append(
            f"@keyframes bnR{i}{{0%{{left:10px;opacity:0}}" + "".join(stops) +
            f"92%{{{end_p};opacity:1}}96%{{{end_p};opacity:0}}96.1%{{left:10px;opacity:0}}100%{{left:10px;opacity:0}}}}")
        ships.append(
            f"<div class='bn-ship' style='--i:{i};--c:{col};--fg:{_fg(col)};--a:bnR{i};--f:{fin:.3f}'>"
            f"<span class='wk'></span><span class='pl'>{html.escape(name)}</span>"
            f"<svg viewBox='0 0 64 28'><use href='#bnShip'/></svg>"
            + ("<svg class='bn-trophy' viewBox='0 0 24 26' aria-hidden='true'><use href='#bnTrophy'/></svg>" if win else "")
            + "</div>")
    ok = sum(1 for s in statuses if s["Status"] == "ok")
    symbol = (
        "<svg width='0' height='0' style='position:absolute' aria-hidden='true'><defs>"
        "<symbol id='bnShip' viewBox='0 0 64 28'>"
        "<path d='M2 17h58l-6 9H9z' fill='#1e293b'/><path d='M4 17h56l-1.6 2.4H5.6z' fill='#e11d48'/>"
        "<g style='fill:var(--c)'>"
        "<rect x='8' y='10' width='6.6' height='7'/><rect x='15' y='10' width='6.6' height='7'/>"
        "<rect x='22' y='10' width='6.6' height='7'/><rect x='29' y='10' width='6.6' height='7'/>"
        "<rect x='11.5' y='3' width='6.6' height='7'/><rect x='18.5' y='3' width='6.6' height='7'/>"
        "<rect x='25.5' y='3' width='6.6' height='7'/></g>"
        "<g fill='#fff' fill-opacity='.28'><rect x='15' y='10' width='6.6' height='7'/>"
        "<rect x='29' y='10' width='6.6' height='7'/><rect x='18.5' y='3' width='6.6' height='7'/></g>"
        "<rect x='41' y='5' width='10' height='12' rx='1' fill='#f8fafc'/>"
        "<rect x='42.5' y='7' width='7' height='2.4' fill='#0f172a'/>"
        "<rect x='44.5' y='1.5' width='3.6' height='3.5' style='fill:var(--c)'/></symbol>"
        "<symbol id='bnTrophy' viewBox='0 0 24 26'>"
        "<path d='M6 3h12v6a6 6 0 0 1-12 0z' fill='#fbbf24' stroke='#b45309' stroke-width='1'/>"
        "<path d='M6 5H2.5c0 4 1.6 6 4 6.4M18 5h3.5c0 4-1.6 6-4 6.4' fill='none' stroke='#d97706' stroke-width='1.6'/>"
        "<rect x='10.6' y='15' width='2.8' height='4' fill='#d97706'/>"
        "<path d='M7 24l1.4-5h7.2L17 24z' fill='#92400e'/><rect x='6' y='23' width='12' height='2.4' rx='1' fill='#b45309'/>"
        "<path d='M9 4.5v4.5' stroke='#fff' stroke-opacity='.6' stroke-width='1.4' stroke-linecap='round'/>"
        "<path d='M12 5.2l.9 1.8 2 .3-1.4 1.4.3 2-1.8-.9-1.8.9.3-2L9.1 7.3l2-.3z' fill='#fff7ed'/></symbol>"
        "</defs></svg>")
    city_hcm = (
        "<svg class='bn-city hcm' viewBox='0 0 310 70' preserveAspectRatio='xMaxYMax meet'>"
        "<rect x='40' y='52' width='28' height='18'/><rect x='72' y='46' width='20' height='24'/>"
        "<rect x='96' y='54' width='26' height='16'/><rect x='126' y='40' width='16' height='30'/>"
        "<rect x='146' y='48' width='22' height='22'/><rect x='172' y='34' width='14' height='36'/>"
        "<rect x='190' y='44' width='20' height='26'/>"
        # Bitexco Financial Tower: tapered tower with its helipad
        "<path d='M216 70V30c0-8 5-14 12-18 7 4 12 10 12 18v40z'/><rect x='236' y='24' width='13' height='3'/>"
        "<rect x='246' y='40' width='14' height='30'/>"
        # Landmark 81
        "<rect x='264' y='48' width='11' height='22'/><path d='M279 70V28h17v42z'/>"
        "<rect x='281' y='14' width='13' height='14'/><rect x='284' y='5' width='7' height='9'/>"
        "<rect x='286.7' y='0' width='1.6' height='6'/></svg>")
    city_lch = (
        "<svg class='bn-city lch' viewBox='0 0 210 44' preserveAspectRatio='xMinYMax meet'>"
        "<rect x='0' y='38' width='210' height='6'/>"
        "<path d='M20 38V10h4v28zM60 38V10h4v28zM20 10h58v3H20zM64 10l22 7v3L64 14z'/>"
        "<path d='M110 38V14h4v24zM150 38V14h4v24zM110 14h58v3h-58zM154 14l22 7v3l-22-6z'/>"
        "<rect x='180' y='28' width='10' height='10'/><rect x='192' y='30' width='10' height='8'/></svg>")
    clouds = ("<i class='bn-cloud' style='top:14px;animation-duration:70s;animation-delay:-20s'></i>"
              "<i class='bn-cloud' style='top:46px;width:90px;animation-duration:95s;animation-delay:-60s;opacity:.7'></i>"
              "<i class='bn-cloud' style='top:30px;width:150px;animation-duration:120s;animation-delay:-5s;opacity:.55'></i>")
    return f"""<style>{''.join(kf)}</style>{symbol}
<div class="banner" role="banner">
  <div class="bn-sun"></div>{clouds}
  <div class="bn-sky">{city_lch}{city_hcm}</div>
  <div class="bn-sea"><div class="bn-wave w1"></div></div>
  <span class="bn-mark l">Bangkok &middot; Laem Chabang</span><span class="bn-mark r">Ho Chi Minh City</span><div class="bn-fin"></div>
  {''.join(ships)}
  <div class="bn-sea" style="background:none;pointer-events:none;z-index:30"><div class="bn-wave w2"></div></div>
  <div class="bn-top">
    <div class="tb-main">
      <h1>Sailing schedule &mdash; {html.escape(LANE)}</h1>
      <p class="sub">Data range {start:%d %b %Y} &ndash; {end:%d %b %Y}
      &nbsp;|&nbsp; combined from {ok}/{len(statuses)} carriers</p>
    </div>
    <div class="tb-side">
      <button id="refreshBtn" class="refresh" type="button" title="Load the latest data"><span class="ri">&#8635;</span><span class="rt">Refresh</span></button>
      <div id="refreshInfo" class="rinfo" data-gen="{gen.isoformat(timespec='seconds')}">Updated {gen:%d %b %Y %H:%M} &middot; <span id="rAge"></span></div>
    </div>
  </div>
</div>
"""


def write_html(merged, records, statuses, start, end, path: Path):
    for i, m in enumerate(merged):
        m["_i"] = i                     # index used by the calendar events to find their hover-card data
    sail_json = json.dumps([_sailing_payload(m) for m in merged],
                           ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    total = len(merged)
    vessels = len({m["vessel"] for m in merged})
    carriers_all = sorted({c for m in merged for c in m["carriers"]})
    multi = sum(1 for m in merged if m["n_sources"] > 1)
    n_bkk = sum(1 for m in merged if m["origin"] == "Bangkok")
    n_lch = sum(1 for m in merged if m["origin"] == "Laem Chabang")
    transit_all = [t for m in merged if m["transit_days"] for t in m["transit_days"]]
    avg_transit = f"{sum(transit_all) / len(transit_all):.1f}" if transit_all else "—"

    gen = dt.datetime.now().astimezone()
    notes = "".join(
        f"<br>{html.escape(s['Source'])} &ndash; {html.escape(s['Status'])}: {html.escape(s['Detail'])}"
        for s in statuses if s.get("Detail"))

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bangkok / Laem Chabang → Ho Chi Minh City sailing schedule</title><style>{CSS}</style></head>
<body><div class="wrap">
{_banner(merged, statuses, start, end, gen)}

<h2>Sailing calendar (by ETD date)</h2>
{_carrier_filter_bar(merged)}
{_origin_bar(merged)}
{_calendar(merged, start, end)}

<h2>Overview</h2>
<div class="grid kpis">
  <div class="card kpi"><div class="v">{total}</div><div class="l">Sailings (duplicates merged)</div></div>
  <div class="card kpi"><div class="v">{len(records)}</div><div class="l">Raw rows from all sources</div></div>
  <div class="card kpi"><div class="v">{vessels}</div><div class="l">Vessels</div></div>
  <div class="card kpi"><div class="v">{len(carriers_all)}</div><div class="l">Carriers / services</div></div>
  <div class="card kpi"><div class="v">{n_bkk}</div><div class="l">Sailings from Bangkok</div></div>
  <div class="card kpi"><div class="v">{n_lch}</div><div class="l">Sailings from Laem Chabang</div></div>
  <div class="card kpi"><div class="v">{multi}</div><div class="l">Sailings bookable via &gt;1 carrier</div></div>
  <div class="card kpi"><div class="v">{avg_transit}</div><div class="l">Average transit (days)</div></div>
</div>

<h2>Sailing details (pick a month / week &middot; click a row for per-carrier details)</h2>
{_detail_by_month(merged, start, end)}

<script type="application/json" id="sailData">{sail_json}</script>

<p class="foot">For preliminary reference only — please confirm schedules / cut-offs with the carrier or agent before relying on them.{notes}<br>
Generated by build_hcm_schedule.py</p>
</div><script>{JS}</script></body></html>"""
    path.write_text(doc, encoding="utf-8")


# --------------------------------------------------------------------------- #
#  serve: open the dashboard locally + a Refresh button that really pulls live data   #
# --------------------------------------------------------------------------- #
def serve(port: int, open_browser: bool = True, extra_args: list[str] | None = None) -> None:
    """
    Opens the dashboard at http://127.0.0.1:PORT/ — pressing "Refresh (live)" on the page
    makes the server re-run build_hcm_schedule.py (pulling from the carriers, ~1-2 min)
    and swaps the new data into the same page without reloading it

    Security: bound to 127.0.0.1 only, the Host header is checked (against DNS rebinding) and
    POST needs an X-Requested-With header (other sites cannot call it cross-origin because of the preflight)
    """
    import http.server
    import subprocess
    import threading
    import webbrowser

    page = OUT_DIR / PAGE_NAME
    if not page.exists():
        sys.exit(f"{page} does not exist yet — run `python build_hcm_schedule.py` once, then use --serve")

    lock = threading.Lock()
    script = Path(__file__).resolve()
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    cmd = [sys.executable, str(script)] + list(extra_args or [])

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(OUT_DIR), **kw)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def _json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in allowed_hosts

        def do_GET(self):
            if not self._host_ok():
                return self.send_error(403)
            route = self.path.split("?")[0]
            if route == "/api/status":
                return self._json(200, {"live": True, "busy": lock.locked()})
            if route in ("", "/"):
                self.send_response(302)
                self.send_header("Location", f"/{PAGE_NAME}")
                self.end_headers()
                return None
            return super().do_GET()

        def do_POST(self):
            if not self._host_ok() or self.path.split("?")[0] != "/api/refresh":
                return self.send_error(404)
            if self.headers.get("X-Requested-With") != "refresh":
                return self._json(403, {"ok": False, "error": "forbidden"})
            if not lock.acquire(blocking=False):
                return self._json(409, {"ok": False, "error": "A refresh is already running, please wait"})
            try:
                print(f"[{dt.datetime.now():%H:%M:%S}] refresh: pulling live data ...", flush=True)
                env = dict(os.environ, PYTHONIOENCODING="utf-8")
                cp = subprocess.run(cmd, cwd=str(HERE), env=env, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=900)
                ok = cp.returncode == 0
                print(f"[{dt.datetime.now():%H:%M:%S}] refresh: {'succeeded' if ok else 'failed'}", flush=True)
                return self._json(200 if ok else 500,
                                  {"ok": ok, "error": None if ok else (cp.stderr or cp.stdout)[-300:]})
            except subprocess.TimeoutExpired:
                return self._json(504, {"ok": False, "error": "Timed out (over 15 minutes)"})
            finally:
                lock.release()

        def log_message(self, fmt, *args):   # no need to log every request
            pass

    class Server(http.server.ThreadingHTTPServer):
        # On Windows SO_REUSEADDR lets two programs bind the same port, so requests can reach the wrong app
        # disabled so that a busy port fails loudly
        allow_reuse_address = False

    try:
        httpd = Server(("127.0.0.1", port), Handler)
    except OSError as exc:
        sys.exit(f"Cannot open port {port} ({exc}) — try another port, e.g. --serve --port {port + 1}")
    url = f"http://127.0.0.1:{port}/{PAGE_NAME}"
    print(f"Dashboard ready at {url}")
    print("Click 'Refresh (live)' on the page to pull fresh data — press Ctrl+C to stop the server")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped")
    finally:
        httpd.server_close()


# --------------------------------------------------------------------------- #
#  main                                                                      #
# --------------------------------------------------------------------------- #
HUB_LINK = ('<a href="./" style="position:fixed;top:10px;left:10px;z-index:9999;padding:6px 12px;'
            'border-radius:999px;background:rgba(15,23,42,.85);color:#fff;font:600 12px/1 system-ui,sans-serif;'
            'text-decoration:none;box-shadow:0 2px 8px rgba(0,0,0,.25)">← SERVICE LINE</a>')


def with_hub_link(html):
    """Published (GitHub Pages) copy only: add a link back to the SERVICE LINE hub."""
    return html.replace("<body>", "<body>" + HUB_LINK, 1)


def main():
    today = dt.date.today()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default=today.replace(day=1).isoformat(),
                    help="start date YYYY-MM-DD (default: the 1st of the current month)")
    ap.add_argument("--end", default=(dt.date(today.year + (today.month >= 11), (today.month + 1) % 12 + 1, 1)
                                       - dt.timedelta(days=1)).isoformat(),
                    help="end date YYYY-MM-DD (default: the last day of NEXT month, i.e. this month + next month)")
    ap.add_argument("--only", default="", help="use only some sources, e.g. --only sitc,tslines")
    ap.add_argument("--skip", default="", help="skip some sources, e.g. --skip sjj,hal")
    ap.add_argument("--offline", action="store_true",
                    help="no network; reuse the data in output/_cache.json from the last run")
    ap.add_argument("--serve", action="store_true",
                    help="serve the dashboard locally with a Refresh button that pulls live data")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"port for --serve (default {DEFAULT_PORT})")
    ap.add_argument("--no-browser", action="store_true", help="--serve: do not open a browser automatically")
    ap.add_argument("--mail-body", choices=["ok", "nochange", "failed"],
                    help="write output/mail_subject.txt + output/mail_body.html from the cached data and exit")
    args = ap.parse_args()

    if args.mail_body:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        subject, body = build_mail(merge_sailings(cache["records"]), cache["statuses"], dt.datetime.now(),
                                   args.mail_body)
        OUT_DIR.mkdir(exist_ok=True)
        (OUT_DIR / "mail_subject.txt").write_text(subject, encoding="utf-8")
        (OUT_DIR / "mail_body.html").write_text(body, encoding="utf-8")
        print(subject)
        return

    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    if end < start:
        sys.exit("--end must not be before --start")

    if args.serve:
        extra = ["--start", args.start, "--end", args.end]
        if args.only:
            extra += ["--only", args.only]
        if args.skip:
            extra += ["--skip", args.skip]
        return serve(args.port, open_browser=not args.no_browser, extra_args=extra)

    OUT_DIR.mkdir(exist_ok=True)
    if not INPUT_DIR.is_dir():
        sys.exit(f"Folder {INPUT_DIR} not found (the original scraper scripts must be inside)")
    sys.path.insert(0, str(INPUT_DIR))
    sys.path.insert(0, str(HERE))

    only = {s.strip().lower() for s in args.only.split(",") if s.strip()}
    skip = {s.strip().lower() for s in args.skip.split(",") if s.strip()}

    records: list[dict] = []
    statuses: list[dict] = []

    if args.offline:
        if not CACHE_FILE.exists():
            sys.exit(f"Cache file {CACHE_FILE} not found — run online at least once first")
        cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        records = cached["records"]
        statuses = cached["statuses"]
        start = dt.date.fromisoformat(cached.get("start", args.start))
        end = dt.date.fromisoformat(cached.get("end", args.end))
        print(f"[offline] loaded from cache: {len(records)} records")
    else:
        for key, (label, fn) in SOURCES.items():
            if only and key not in only:
                continue
            if key in skip:
                statuses.append({"Source": label, "Status": "skipped", "Sailings": 0, "Detail": "skipped with --skip"})
                continue
            print(f"[{label}] pulling data {start} -> {end} ...")
            try:
                recs = [r for r in fn(start, end) if _in_range(r, start, end)]
                for r in recs:
                    records.append(r)
                st = "ok" if recs else "empty"
                statuses.append({"Source": label, "Status": st, "Sailings": len(recs),
                                 "Detail": SOURCE_NOTES.get(key, "")})
                print(f"   -> {len(recs)} records")
            except SourceBlocked as exc:
                short = str(exc).splitlines()[0][:200]
                statuses.append({"Source": label, "Status": "blocked", "Sailings": 0, "Detail": short})
                print(f"   !! blocked: {short}")
            except Exception as exc:  # noqa: BLE001 - one failing source must not sink the whole run
                short = str(exc).splitlines()[0][:180]
                statuses.append({"Source": label, "Status": "failed", "Sailings": 0, "Detail": short})
                print(f"   !! failed: {short}")

    if not records:
        print("\nNo data from any source — the dashboard is still built (empty) so you can see the source status")

    records = dedupe_records(records)
    merged = merge_sailings(records)

    xlsx = OUT_DIR / "combined_schedule.xlsx"
    htmlf = OUT_DIR / PAGE_NAME
    ics = OUT_DIR / "hcm_schedule.ics"

    write_excel(merged, records, statuses, xlsx)
    write_ics(merged, ics)
    write_html(merged, records, statuses, start, end, htmlf)

    # copy for GitHub Pages (dashboard.html in the repo root)
    docs_page = PAGES_FILE
    docs_page.write_text(with_hub_link(htmlf.read_text(encoding="utf-8")), encoding="utf-8")
    CACHE_FILE.write_text(json.dumps(
        {"start": start.isoformat(), "end": end.isoformat(),
         "records": records, "statuses": statuses, "merged": len(merged),
         "generated": dt.datetime.now().isoformat()},
        ensure_ascii=False, indent=1), encoding="utf-8")

    ok = sum(1 for s in statuses if s["Status"] == "ok")
    print(f"\n=== Summary ===")
    print(f"Sources OK             : {ok}/{len(statuses)}")
    for s in statuses:
        print(f"  - {s['Source']:<12} {s['Status']:<8} {s['Sailings']} sailings  {s.get('Detail') or ''}")
    print(f"Raw records            : {len(records)}")
    print(f"Sailings after merging : {len(merged)}")
    print(f"\nOutput files:")
    print(f"  {xlsx}")
    print(f"  {htmlf}")
    print(f"  {ics}")
    print(f"  {docs_page}   (GitHub Pages)")


if __name__ == "__main__":
    main()
