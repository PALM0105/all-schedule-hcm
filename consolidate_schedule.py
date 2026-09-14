#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
consolidate_schedule.py
========================
รวมผลลัพธ์จากสคริปต์ดึงตารางเรือทั้งหมดในโฟลเดอร์ raw-data/
เข้าเป็นชุดข้อมูลเดียว สำหรับเส้นทาง Bangkok / Laem Chabang -> Ho Chi Minh City

แหล่งข้อมูลที่รองรับ (อ่านจาก raw-data/):
    - jj_shipping_hcm_schedule.csv   (จาก jj_shipping_schedule.py)
    - sitc_schedule.csv              (จาก sitc_schedule.py)
    - kmtc_schedule_output.csv       (จาก kmtc_schedule.py ถ้าเว็บไม่บล็อก)
    - ckline_schedule_*.csv          (จาก ckline_schedule.py)
    - cul_schedule.csv               (จาก cul_schedule.py)
    - dongjin_schedule.csv           (จาก dongjin_schedule.py)
    - namsung_schedule_bkk_lcb_to_hcm.csv  (จาก namsung_schedule.py ถ้าเว็บไม่บล็อก)

หมายเหตุ: pancon_kst_schedule.py ให้ "รูปแบบเที่ยวเรือรายสัปดาห์" ที่คาดการณ์วันที่
ล่วงหน้า (ไม่มีชื่อเรือ/เลขเที่ยวจริง) จึงไม่ถูกรวมเข้าตารางหลัก เพราะเที่ยวเรือจริง
ของ PANCON (เช่น PANCON BRIDGE, PANCON CHAMPION) ถูกพบแล้วจาก CK Line และ DONGJIN
ซึ่งมีชื่อเรือ/เลขเที่ยว/เวลาจริงครบถ้วนกว่า

ขั้นตอน:
- อ่าน CSV ทั้งหมดข้างต้น แปลงให้อยู่ใน schema เดียวกัน
- รวมเที่ยวเรือที่เป็นลำเดียวกัน (เรือ+ต้นทาง+วันออกตรงกัน) จากหลายแหล่งข้อมูล
  เป็นแถวเดียว พร้อมระบุว่าพบจากแหล่งข้อมูลใดบ้าง (เลขเที่ยว/voyage อาจเขียนต่างกัน
  ในแต่ละเว็บ จึงไม่ใช้เป็นส่วนหนึ่งของ key ในการรวม)
- Export เป็น schedule_data.json ให้หน้า dashboard (HTML) ใช้แสดงผล

วิธีใช้:
    python consolidate_schedule.py
"""

import csv
import glob
import importlib.util
import json
import re
from datetime import date, datetime
from pathlib import Path

FOLDER = Path(__file__).parent
RAW_DIR = FOLDER / "raw-data"
YEAR = 2026

# ผู้ใช้ต้องการให้มีสายเรือ/กลุ่มข้อมูลตรงกับจำนวนแหล่งข้อมูล (ไฟล์ .py) ที่ให้มา
# เท่านั้น (9 ไฟล์ -> 9 สายเรือ) ไม่แยกย่อยตามชื่อเรือจริงอีกต่อไป จึงไม่ใช้การเดา
# สายเรือจากชื่อเรือ (guess_line/KNOWN_VESSEL_PREFIX_TO_LINE แบบเดิม) แล้ว —
# ทุกเที่ยวเรือจะถูกติดป้ายตามแหล่งข้อมูล/เว็บไซต์ที่พบ (ดู SOURCE_TO_LINE_BRAND
# และการเลือก best_source ใน dedupe_merge ด้านล่าง) เท่านั้น


def norm_vessel(v: str) -> str:
    return re.sub(r"\s+", " ", v.strip().upper())


def norm_origin(o: str) -> str:
    key = re.sub(r"\s+", " ", o.strip().upper())
    if key == "BANGKOK":
        return "Bangkok"
    if key == "LAEM CHABANG":
        return "Laem Chabang"
    return o.strip()


def split_vessel_voyage(vessel_voyage: str) -> tuple[str, str]:
    """'SITC XIN 2623N' -> ('SITC XIN', '2623N') โดยตัดคำสุดท้าย (เลขเที่ยว) ออก"""
    parts = vessel_voyage.strip().rsplit(" ", 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return vessel_voyage.strip(), ""


def date_only(s: str) -> str | None:
    if not s:
        return None
    s = s.strip()
    if not s or s == "-":
        return None
    try:
        return date.fromisoformat(s.split(" ")[0]).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Loaders — 1 ต่อ 1 แหล่งข้อมูล คืนค่า list ของ dict ใน schema เดียวกัน:
# source, origin, origin_terminal, destination, vessel, voyage, etd, eta,
# transit_days, closing
# ---------------------------------------------------------------------------

def load_jj():
    path = RAW_DIR / "jj_shipping_hcm_schedule.csv"
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            etd = date_only(r.get("departure_date", ""))
            if not etd:
                continue
            eta = date_only(r.get("arrival_date", ""))
            rows.append({
                "source": "JJ Shipping (forwarder)",
                "origin": norm_origin(r["search_origin"]),
                "origin_terminal": r["origin_port"],
                "destination": r["destination_port"],
                "vessel": r["vessel"].strip(),
                "voyage": r["voyage"].strip(),
                "etd": etd,
                "eta": eta,
                "transit_days": r.get("transit_days", ""),
                "closing": r.get("closing", ""),
            })
    return rows


def load_kmtc():
    path = RAW_DIR / "kmtc_schedule_output.csv"
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 11:
                continue
            pol, pod, etd_s, eta_s, transit, vessel, voyage, pol_trm, pod_trm, typ, closing = row[:11]
            etd = date_only(etd_s)
            eta = date_only(eta_s)
            origin = "Bangkok" if pol == "BKK" else ("Laem Chabang" if pol == "LCH" else pol)
            rows.append({
                "source": "KMTC",
                "origin": origin,
                "origin_terminal": pol_trm,
                "destination": "Ho Chi Minh City",
                "vessel": vessel.strip(),
                "voyage": voyage.strip(),
                "etd": etd,
                "eta": eta,
                "transit_days": transit,
                "closing": closing,
            })
    return rows


MONTH_DAY_RE = re.compile(r"(\d{2})-(\d{2})")


def sitc_md_to_date(md_str: str, year: int) -> str | None:
    m = MONTH_DAY_RE.match(md_str or "")
    if not m:
        return None
    mm, dd = int(m.group(1)), int(m.group(2))
    try:
        return date(year, mm, dd).isoformat()
    except ValueError:
        return None


def load_sitc():
    path = RAW_DIR / "sitc_schedule.csv"
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            vessel, voyage = split_vessel_voyage(r["vessel_voyage"])
            etd = sitc_md_to_date(r["etd"], YEAR)
            eta = sitc_md_to_date(r["eta"], YEAR)
            if eta and etd and eta < etd:
                # ปีถัดไป (ข้ามปีใหม่) กรณีค้นข้ามช่วงสิ้นปี
                eta = date.fromisoformat(eta).replace(year=YEAR + 1).isoformat()
            rows.append({
                "source": "SITC Line",
                "origin": norm_origin(r["pol"]),
                "origin_terminal": r["pol"],
                "destination": "Ho Chi Minh City",
                "vessel": vessel,
                "voyage": voyage,
                "etd": etd,
                "eta": eta,
                "transit_days": "",
                "closing": "",
            })
    return rows


# รายชื่อเรือของ CK Line เอง (เจ้าของเรือ + เรือเช่าประจำ) จาก www.ckline.co.kr/en/service/ship/
# (OWN VESSELS) และ .../charted.jsp (CHARTER VESSELS) ดึงมาเมื่อ 2026-09-14 — ใช้กรอง
# ตาราง es.ckline.co.kr (เว็บ "vessel schedule checker" ที่โชว์เรือของสายพันธมิตร VSA
# ปนอยู่ด้วย) ให้เหลือเฉพาะเที่ยวที่ CK Line ให้บุ๊คได้จริงเท่านั้น เที่ยวของเรือสายอื่น
# (KMTC, PANCON, HMM, DONGJIN, SAWASDEE/Heung-A, SM, STARSHIP, POS ฯลฯ) ที่โชว์ในเว็บนี้
# เพื่ออ้างอิงเฉย ๆ จะถูกตัดออกจากแหล่งข้อมูลนี้ (ถ้าสายเรือเจ้าของเรือจริงมีแหล่งข้อมูล
# อื่นยืนยันเที่ยวเดียวกันด้วย เที่ยวนั้นจะยังปรากฏในตาราง แต่นับเป็นสายเรือนั้นแทน)
CK_LINE_OWN_VESSELS = {
    "SKY AURORA", "SKY CHALLENGE", "SKY FLOWER", "SKY GLORY", "SKY HOPE",
    "SKY ORION", "SKY VICTORIA", "SKY SUNSHINE", "SKY WIND", "SKY RAINBOW",
    "SKY TIARA", "SKY IRIS", "SKY MOON", "SKY JADE", "SKY PRIDE", "SKY PEACE",
}
CK_LINE_CHARTER_VESSELS = {
    "JI PENG", "KAI PING", "PACIFIC MONACO", "ATLANTIC BRIDGE",
    "SUNWIN", "VICTORY STAR", "PROVIDENT",
}
CK_LINE_BOOKABLE_VESSELS = CK_LINE_OWN_VESSELS | CK_LINE_CHARTER_VESSELS


def load_ckline():
    matches = sorted(glob.glob(str(RAW_DIR / "ckline_schedule_*.csv")))
    rows = []
    if not matches:
        return rows
    path = matches[-1]  # ไฟล์ล่าสุด (ชื่อมี timestamp)
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            vessel = r["Vessel"].strip()
            if vessel.upper() not in CK_LINE_BOOKABLE_VESSELS:
                continue  # เรือของสายอื่นที่ CK Line แค่โชว์ไว้อ้างอิง จองผ่าน CK ไม่ได้
            etd = date_only(r.get("ETD", ""))
            if not etd:
                continue
            eta = date_only(r.get("ETA", ""))
            rows.append({
                "source": "CK Line",
                "origin": norm_origin(r["Origin"]),
                "origin_terminal": r.get("Loading Terminal", ""),
                "destination": r.get("Destination", "Ho Chi Minh City"),
                "vessel": vessel,
                "voyage": r["Voyage"].strip(),
                "etd": etd,
                "eta": eta,
                "transit_days": r.get("Transit (days)", ""),
                "closing": "",
            })
    return rows


def load_cul():
    path = RAW_DIR / "cul_schedule.csv"
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            etd = date_only(r.get("departure_date", ""))
            if not etd:
                continue
            eta = date_only(r.get("arrival_date", ""))
            vessel, voyage = split_vessel_voyage(r.get("vessel_voyage", ""))
            rows.append({
                "source": "CUL",
                "origin": norm_origin(r.get("loading_port", r.get("origin_query", ""))),
                "origin_terminal": r.get("loading_port", ""),
                "destination": r.get("discharging_port", "Ho Chi Minh City"),
                "vessel": vessel,
                "voyage": voyage,
                "etd": etd,
                "eta": eta,
                "transit_days": r.get("transit_days", ""),
                "closing": r.get("cargo_closing", ""),
            })
    return rows


def load_dongjin():
    path = RAW_DIR / "dongjin_schedule.csv"
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            etd = date_only(r.get("ETD", ""))
            if not etd:
                continue
            eta = date_only(r.get("ETA", ""))
            vessel, voyage = split_vessel_voyage(r.get("Vessel/Voyage", ""))
            rows.append({
                "source": "Dongjin Shipping",
                "origin": norm_origin(r.get("Loading Port", r.get("Origin", ""))),
                "origin_terminal": r.get("Loading Port", ""),
                "destination": r.get("Discharging Port", "Ho Chi Minh City"),
                "vessel": vessel,
                "voyage": voyage,
                "etd": etd,
                "eta": eta,
                "transit_days": r.get("Total Days", ""),
                "closing": r.get("Cargo Closing", ""),
            })
    return rows


def load_namsung():
    path = RAW_DIR / "namsung_schedule_bkk_lcb_to_hcm.csv"
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            etd = date_only(r.get("etd", ""))
            if not etd:
                continue
            eta = date_only(r.get("eta", ""))
            rows.append({
                "source": "Namsung",
                "origin": norm_origin(r.get("departure_port", "")),
                "origin_terminal": r.get("loading_terminal", ""),
                "destination": r.get("pod", "Ho Chi Minh City"),
                "vessel": (r.get("vessel") or "").strip(),
                "voyage": (r.get("voyage") or "").strip(),
                "etd": etd,
                "eta": eta,
                "transit_days": "",
                "closing": r.get("cargo_closing", ""),
            })
    return rows


def load_hal():
    """generate_hal_schedule.py ไม่ได้ scrape เว็บสด แต่เป็นข้อมูลที่ดึงมาจาก
    ebiz.heungaline.com/Schedule แล้วฝังเป็น list ในตัวสคริปต์ (สร้างไฟล์ Excel)
    เราจึง import โมดูลนี้ตรง ๆ เพื่ออ่าน bangkok_rows / laem_rows กลับมา"""
    path = RAW_DIR / "generate_hal_schedule.py"
    rows = []
    if not path.exists():
        return rows
    spec = importlib.util.spec_from_file_location("hal_schedule_module", path)
    module = importlib.util.module_from_spec(spec)
    import io
    import contextlib
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(module)
    except Exception:
        return rows
    for origin_label, data_rows in (
        ("Bangkok", getattr(module, "bangkok_rows", [])),
        ("Laem Chabang", getattr(module, "laem_rows", [])),
    ):
        for r in data_rows:
            # [Service, Vessel, Voyage, POL/Terminal, POD/Terminal, ETD, ETA, Transit, DOCU Closing, CNTR Closing, Status]
            vessel, voyage = r[1].strip(), r[2].strip()
            etd = date_only(r[5])
            if not etd:
                continue
            eta = date_only(r[6])
            rows.append({
                "source": "Heung-A Line (HAL)",
                "origin": origin_label,
                "origin_terminal": r[3],
                "destination": r[4],
                "vessel": vessel,
                "voyage": voyage,
                "etd": etd,
                "eta": eta,
                "transit_days": r[7],
                "closing": r[9],
            })
    return rows


def load_hmm():
    """hmm_schedule.py (Playwright) ยังดึงข้อมูลไม่สำเร็จ -- เว็บ hmm21.com ตอบ
    net::ERR_HTTP2_PROTOCOL_ERROR/timeout ทุกครั้งหลังการเรียกครั้งแรก (บล็อกคล้าย
    KMTC/Namsung) ไฟล์ผลลัพธ์ hmm_schedule_bkk_lcb_to_hcm.xlsx จึงว่างเปล่า (0 แถว)
    อีกทั้งตัวสคริปต์เองก็ยังเก็บผลเป็นข้อความดิบทั้งแถว (row_cells) ไม่ได้แยกเป็น
    เรือ/เที่ยว/ETD ที่พาร์สได้แน่นอน จึง (ยัง) ไม่ merge เข้าตารางหลักแม้จะมีข้อมูล"""
    path = RAW_DIR / "hmm_schedule_bkk_lcb_to_hcm.xlsx"
    if not path.exists():
        return []
    try:
        import pandas as pd
        df = pd.read_excel(path)
    except Exception:
        return []
    if df.empty or "row_cells" not in df.columns:
        return []
    # มีข้อมูลดิบจริงแต่ไม่มีคอลัมน์ที่พาร์สได้แน่นอน -- ยังไม่แปลงเป็นแถวที่ merge ได้
    return []


# ให้ความสำคัญกับแหล่งข้อมูลที่เป็นสายเรือ/เว็บทางการเองก่อน แล้วค่อยเป็น
# เว็บ "vessel schedule checker" ของสายเรืออื่นที่โชว์ข้อมูล VSA ของหลายสายเรือ
# ใช้ตอนต้องเดาว่าเรือ slot/charter ลำนี้ถูกพบจากสายเรือ/เว็บไหนก่อน
SOURCE_PRIORITY = [
    "SITC Line", "KMTC", "Namsung", "HMM",
    "CK Line", "Dongjin Shipping", "CUL", "JJ Shipping (forwarder)",
    # Heung-A Line (HAL) ไม่ได้ดึงจากเว็บสด (เป็นข้อมูลที่ฝังไว้ในไฟล์สคริปต์)
    # จึงให้ priority ต่ำสุด: ใช้เป็นตัวแทนแสดงผลก็ต่อเมื่อไม่มีเว็บสดเว็บไหนยืนยันเที่ยวนี้
    "Heung-A Line (HAL)",
]
# สายเรือ/กลุ่มข้อมูลตายตัว ตรงกับจำนวนไฟล์สคริปต์ใน raw-data/ พอดี (10 ไฟล์ ณ ตอนนี้)
# ทุกเที่ยวเรือที่พบจากแหล่งข้อมูลใด จะถูกนับเป็นสายเรือนั้นเสมอ (ไม่แยกย่อยตามชื่อ
# เรือจริงอีกต่อไป — ดูหมายเหตุด้านบน KNOWN_VESSEL_PREFIX_TO_LINE เดิมที่ถูกเอาออก)
SOURCE_TO_LINE_BRAND = {
    "JJ Shipping (forwarder)": "JJ Shipping",
    "SITC Line": "SITC",
    "KMTC": "KMTC",
    "Namsung": "Namsung",
    "HMM": "HMM",
    "Heung-A Line (HAL)": "Heung-A",
    "CK Line": "CK Line",
    "CUL": "CUL (Culines)",
    "Dongjin Shipping": "Dongjin Shipping",
    "Pan Continental (PANCON)": "Pan Continental",  # pancon_kst_schedule.py — ดู main()
}


def dedupe_merge(rows):
    """รวมเที่ยวเรือที่เป็นลำเดียวกัน (เรือ+ต้นทาง+วันออกตรงกัน) จากหลายแหล่งข้อมูล
    ให้เหลือแถวเดียว พร้อมรายชื่อแหล่งข้อมูล/สายเรือที่พบ
    หมายเหตุ: ไม่ใช้เลขเที่ยว(voyage) เป็นส่วนหนึ่งของ key เพราะแต่ละเว็บเขียน
    รหัสเที่ยวเรือเดียวกันไม่ตรงกัน (เช่น CK Line เขียน 'PBRG2612N' ส่วน DONGJIN
    เขียน '2612N' สำหรับเรือ/เที่ยวจริงเที่ยวเดียวกัน)"""
    groups = {}
    order = []
    for r in rows:
        if not r.get("etd"):
            continue
        key = (norm_vessel(r["vessel"]), norm_origin(r["origin"]), r["etd"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(r)

    def src_rank(source):
        return SOURCE_PRIORITY.index(source) if source in SOURCE_PRIORITY else 99

    merged = []
    for key in order:
        group = groups[key]
        _, origin, etd_key = key
        sources = sorted(set(r["source"] for r in group))

        # เลือก "แถวตัวแทน" จากแหล่งข้อมูลที่ priority สูงสุดในกลุ่มนี้ แล้วใช้ค่า
        # เรือ/เที่ยว/เวลาถึง ของแถวนั้นทั้งชุด เพื่อให้ข้อมูลที่แสดงตรงกับเว็บไซต์จริง
        # เว็บเดียวเสมอ (ไม่ใช่ค่าผสมข้ามแหล่ง) — ไฟล์ที่ไม่ได้ดึงจากเว็บสด เช่น
        # Heung-A Line (HAL) จะถูกใช้เป็นตัวแทนก็ต่อเมื่อไม่มีเว็บสดเว็บไหนยืนยันเที่ยวนี้
        best_row = min(group, key=lambda r: src_rank(r["source"]))
        best_source = best_row["source"]
        vessel_display = best_row["vessel"]

        eta = best_row.get("eta")
        if not eta:
            etas = [r["eta"] for r in group if r.get("eta")]
            eta = max(etas) if etas else None

        voyage_display = best_row.get("voyage") or ""
        if not voyage_display:
            for r in sorted(group, key=lambda r: src_rank(r["source"])):
                if r.get("voyage"):
                    voyage_display = r["voyage"]
                    break

        # สายเรือ = แหล่งข้อมูล/เว็บที่ priority สูงสุดในกลุ่มนี้เสมอ (9 ค่าคงที่ตรงกับ
        # ไฟล์สคริปต์ 9 ไฟล์) ไม่แยกย่อยตามชื่อเรือจริงอีกต่อไป
        line_guess = SOURCE_TO_LINE_BRAND.get(best_source, best_source)

        merged.append({
            "vessel": vessel_display,
            "voyage": voyage_display,
            "line": line_guess,
            "origin": origin,
            "destination": "Ho Chi Minh City",
            "etd": etd_key,
            "eta": eta,
            "sources": sources,
            "duplicate_count": len(group),
            "raw": group,
        })

    # เก็บเฉพาะเที่ยวที่ออกในช่วง ก.ย.-ธ.ค. 2026 ตามที่ร้องขอ (บางแหล่งข้อมูลส่งคืน
    # เที่ยวที่ล้นไปต้นปีถัดไปมาด้วยเนื่องจาก pattern การค้นหารายสัปดาห์/30 วัน)
    range_start, range_end = f"{YEAR}-09-01", f"{YEAR}-12-31"
    merged = [r for r in merged if range_start <= r["etd"] <= range_end]

    merged.sort(key=lambda r: (r["etd"], r["origin"]))
    return merged


SOURCE_NOTES = {
    "JJ Shipping": "yourjjshipping.app (forwarder, หลายสายเรือ)",
    "SITC Line": "api.sitcline.com (ตารางทางการของสายเรือ SITC)",
    "KMTC": "api.ekmtc.com -- เว็บไซต์บล็อกการเข้าถึงจากเซิร์ฟเวอร์นี้ (Akamai Access Denied) จึงยังไม่มีเที่ยวเรือในกลุ่มนี้ในการรันครั้งนี้",
    "Namsung": "ebiz.namsung.co.kr -- เว็บไซต์บล็อกการเข้าถึงจากเซิร์ฟเวอร์นี้ (Akamai Access Denied)",
    "HMM": "hmm21.com -- เว็บไซต์ตอบ net::ERR_HTTP2_PROTOCOL_ERROR/timeout ทุกครั้งหลังการเรียกครั้งแรก (บล็อกคล้าย KMTC/Namsung) จึงยังไม่มีเที่ยวเรือในกลุ่มนี้",
    "Heung-A Line (HAL)": "ebiz.heungaline.com/Schedule (ไฟล์ที่ดึงไว้เมื่อ 2026-09-13 ไม่ใช่การดึงจากเว็บสด — ทุกเที่ยวที่พบในไฟล์นี้นับเป็น Heung-A ทั้งหมด)",
    "CK Line": "es.ckline.co.kr -- กรองเหลือเฉพาะเรือที่ CK Line ให้บุ๊คได้จริง (23 ลำ: เรือของตัวเอง + เรือเช่าประจำ ตาม www.ckline.co.kr/en/service/ship/) เที่ยวของเรือสายอื่นที่เว็บนี้โชว์ไว้อ้างอิงถูกตัดออก",
    "CUL": "culines.com (ตารางทางการของสายเรือ CUL/Culines)",
    "Dongjin Shipping": "esvc.djship.co.kr (เว็บตรวจสอบตารางเรือ แสดงเที่ยวเรือของหลายสายเรือพันธมิตร)",
}


def main():
    loaders = {
        "JJ Shipping": load_jj,
        "SITC Line": load_sitc,
        "KMTC": load_kmtc,
        "Namsung": load_namsung,
        "HMM": load_hmm,
        "Heung-A Line (HAL)": load_hal,
        "CK Line": load_ckline,
        "CUL": load_cul,
        "Dongjin Shipping": load_dongjin,
    }

    all_rows = []
    sources_status = {}
    for label, loader in loaders.items():
        rows = loader()
        all_rows.extend(rows)
        note = SOURCE_NOTES.get(label, "")
        if rows:
            print(f"{label:<18}: {len(rows)} แถว")
            sources_status[label] = f"ok, {len(rows)} เที่ยว -- {note}"
        else:
            print(f"{label:<18}: 0 แถว (ไม่มีไฟล์ผลลัพธ์ - เว็บไซต์บล็อกการเข้าถึงจากเซิร์ฟเวอร์นี้)")
            sources_status[label] = f"blocked/unavailable -- {note}"

    sources_status["Pan Continental (PANCON)"] = (
        "pancon.co.kr -- not merged: pancon_kst_schedule.py ให้เฉพาะรูปแบบเที่ยวเรือรายสัปดาห์ที่คาดการณ์ล่วงหน้า "
        "ไม่มีชื่อเรือ/เลขเที่ยวจริง จึงยังไม่มีเที่ยวเรือในกลุ่ม 'Pan Continental' ในการรันครั้งนี้ "
        "(เที่ยวของเรือ PANCON ที่พบผ่านเว็บอื่น เช่น CK Line/Dongjin จะถูกนับเป็นสายเรือของเว็บนั้นแทน)"
    )

    merged = dedupe_merge(all_rows)
    print(f"\nรวมทั้งหมด {len(all_rows)} รายการดิบ -> {len(merged)} เที่ยวเรือ (หลังรวมรายการซ้ำ)")

    by_line = {}
    for m in merged:
        by_line.setdefault(m["line"], []).append(m)
    print("\nแจกแจงตามสายเรือ:")
    for line, items in sorted(by_line.items(), key=lambda kv: -len(kv[1])):
        print(f"  - {line:<40} {len(items)} เที่ยว")

    out = {
        "generated_note": "Bangkok / Laem Chabang -> Ho Chi Minh City, ก.ย.-ธ.ค. 2026",
        "sources_status": sources_status,
        "sailings": merged,
    }
    out_path = FOLDER / "schedule_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nบันทึกไฟล์: {out_path.name}")


if __name__ == "__main__":
    main()
