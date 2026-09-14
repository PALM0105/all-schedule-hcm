#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CK Line (CKLINE) — Vessel Schedule Checker
===========================================

ดึงตารางเรือ (sailing schedule) ของสายเรือ CK Line (CKLINE) จากเว็บไซต์ทางการ
https://es.ckline.co.kr  โดยดึงข้อมูลตรงจาก API เบื้องหลังหน้า
"Schedule > Point to Point" (endpoint: sup.WESSUP401.WESSUP401R01)

ค่าเริ่มต้นของสคริปต์นี้ตั้งไว้ตามที่ขอ:
    ต้นทาง (POL) : Bangkok (THBKK) และ Laem Chabang (THLCH)
    ปลายทาง (POD): Ho Chi Minh (VNSGN)
    เดือน         : กันยายน (9) และ ตุลาคม (10) ของปี YEAR ด้านล่าง

วิธีใช้งาน
----------
    pip install requests
    python3 ckline_schedule.py

ผลลัพธ์:
    - พิมพ์ตารางเรือออกทางหน้าจอ (เรียงตามวันที่ออกเรือ)
    - บันทึกไฟล์ CSV: ckline_schedule_<timestamp>.csv

หมายเหตุ: เว็บไซต์นี้อาจเปลี่ยนแปลง endpoint/พารามิเตอร์ได้ในอนาคต
ควรตรวจสอบผลลัพธ์เทียบกับหน้าเว็บจริงก่อนใช้งานจริงเสมอ
(เว็บไซต์ระบุว่าตารางเรือเป็นข้อมูลอ้างอิง โปรดยืนยันกับตัวแทนสายเรืออีกครั้งก่อนจอง)
"""

import csv
import datetime as dt
import sys
from typing import Optional

import requests

# --------------------------------------------------------------------------
# CONFIG — แก้ไขค่าตรงนี้ได้ตามต้องการ
# --------------------------------------------------------------------------

BASE_URL = "https://es.ckline.co.kr/action/sup.WESSUP401.WESSUP401R01"

# ต้นทาง: ชื่อที่จะแสดง -> (UN/LOCODE, ประเทศ)
ORIGIN_PORTS = {
    "Bangkok":       {"code": "THBKK", "nation": "TH"},
    "Laem Chabang":  {"code": "THLCH", "nation": "TH"},
}

# ปลายทาง
DEST_PORT = {"name": "Ho Chi Minh", "code": "VNSGN", "nation": "VN"}

# ปี และเดือนที่ต้องการค้นหา (กันยายน และ ตุลาคม)
YEAR = 2026
MONTHS = [9, 10, 11, 12]

# ประเภทตู้: CNTR = Container
CARGO_TYPE = "CNTR"

REQUEST_TIMEOUT = 20  # seconds

HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://es.ckline.co.kr/?cmd=SCH",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _parse_dt(date_str: Optional[str], time_str: Optional[str]) -> Optional[dt.datetime]:
    """Parse CK Line's 'YYYYMMDD' + 'HHMM' fields into a datetime object."""
    if not date_str:
        return None
    time_str = time_str or "0000"
    try:
        return dt.datetime.strptime(date_str + time_str, "%Y%m%d%H%M")
    except ValueError:
        return None


def fetch_schedule(pol_code: str, pol_nation: str, year: int, month: int) -> list:
    """
    เรียก API ตารางเรือของ CK Line สำหรับต้นทาง pol_code -> DEST_PORT ในเดือนที่ระบุ
    คืนค่าเป็น list ของ dict (raw records จาก resData.dlt_schedule)
    """
    ym = f"{year}{month:02d}"
    first_day = f"{ym}01"

    payload = {
        "reqMeta": {"PRGCOD": "WESSUP401", "LOGINYN": "N"},
        "reqData": {
            "INPFNT": pol_nation,
            "INPTNT": DEST_PORT["nation"],
            "INPPOR_SCH": pol_code,
            "INPPOL_SCH": pol_code,
            "INPPOD_SCH": DEST_PORT["code"],
            "INPPVY_SCH": DEST_PORT["code"],
            "INPDIR": "N",
            "INPCTYP": CARGO_TYPE,
            "INPDAT": first_day,
            "INPVVD": "",
            "INPYMM": ym,
        },
    }

    resp = requests.post(BASE_URL, json=payload, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    result_code = data.get("resMeta", {}).get("resultCd")
    if result_code != "S":
        msg = data.get("resMeta", {}).get("resultMsg", "Unknown error")
        print(f"  [!] API ตอบกลับผิดพลาด ({result_code}): {msg}", file=sys.stderr)
        return []

    return data.get("resData", {}).get("dlt_schedule", []) or []


def normalize_row(raw: dict, origin_name: str) -> dict:
    """แปลง raw record จาก API ให้เป็นแถวข้อมูลที่อ่านง่าย"""
    etd = _parse_dt(raw.get("OUTETD1"), raw.get("OUTEHD1"))
    eta_field = raw.get("OUTETA1") or raw.get("OUTETA1_F")
    eha_field = raw.get("OUTEHA1") or raw.get("OUTEHA1_F")
    eta = _parse_dt(eta_field, eha_field)

    transit_days = None
    if etd and eta:
        transit_days = round((eta - etd).total_seconds() / 86400, 1)

    is_transship = bool(raw.get("OUTVVD2"))  # มี leg ที่ 2 = T/S

    return {
        "Origin": origin_name,
        "POL Code": raw.get("OUTPOL1"),
        "Loading Terminal": raw.get("OUTLTMLDES"),
        "Destination": DEST_PORT["name"],
        "POD Code": raw.get("OUTLASTPOD") or raw.get("OUTPOD1"),
        "Discharge Terminal": raw.get("OUTDTML1DES"),
        "Vessel": raw.get("VSLDES"),
        "Voyage": raw.get("OUTVVD1"),
        "ETD": etd.strftime("%Y-%m-%d %H:%M") if etd else "",
        "ETA": eta.strftime("%Y-%m-%d %H:%M") if eta else "",
        "Transit (days)": transit_days if transit_days is not None else "",
        "Service": "T/S" if is_transship else "Direct",
        "_etd_sort": etd or dt.datetime.max,
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    all_rows = []

    print("=" * 100)
    print(f"CK LINE SCHEDULE — {' / '.join(ORIGIN_PORTS.keys())}  ->  {DEST_PORT['name']}")
    print(f"Months: {', '.join(str(m) for m in MONTHS)} / {YEAR}")
    print("=" * 100)

    for origin_name, origin in ORIGIN_PORTS.items():
        for month in MONTHS:
            print(f"\n[*] กำลังค้นหา: {origin_name} ({origin['code']}) -> "
                  f"{DEST_PORT['name']} ({DEST_PORT['code']})  เดือน {month}/{YEAR} ...")
            try:
                raw_rows = fetch_schedule(origin["code"], origin["nation"], YEAR, month)
            except requests.RequestException as exc:
                print(f"  [!] เรียก API ไม่สำเร็จ: {exc}", file=sys.stderr)
                continue

            print(f"    พบ {len(raw_rows)} เที่ยวเรือ")
            for raw in raw_rows:
                all_rows.append(normalize_row(raw, origin_name))

    if not all_rows:
        print("\nไม่พบข้อมูลตารางเรือ (ตรวจสอบการเชื่อมต่ออินเทอร์เน็ต หรือพารามิเตอร์ค้นหา)")
        return

    all_rows.sort(key=lambda r: (r["Origin"], r["_etd_sort"]))
    for r in all_rows:
        r.pop("_etd_sort", None)

    # ---- print table ----
    columns = ["Origin", "POL Code", "Loading Terminal", "Destination", "POD Code",
               "Discharge Terminal", "Vessel", "Voyage", "ETD", "ETA",
               "Transit (days)", "Service"]

    col_widths = {c: max(len(c), max((len(str(r[c])) for r in all_rows), default=0)) for c in columns}

    def print_row(values):
        print(" | ".join(str(v).ljust(col_widths[c]) for c, v in zip(columns, values)))

    print("\n" + "-" * 100)
    print_row(columns)
    print("-" * 100)
    for r in all_rows:
        print_row([r[c] for c in columns])
    print("-" * 100)
    print(f"รวมทั้งหมด {len(all_rows)} เที่ยวเรือ")

    # ---- save CSV ----
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = f"ckline_schedule_{timestamp}.csv"
    with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in all_rows:
            writer.writerow({c: r[c] for c in columns})

    print(f"\nบันทึกผลลัพธ์ลงไฟล์: {out_file}")
    print("หมายเหตุ: ตารางเรือนี้เป็นข้อมูลอ้างอิงจากเว็บไซต์ CK Line "
          "โปรดยืนยันกับตัวแทน/สายเรืออีกครั้งก่อนทำการจอง (booking)")


if __name__ == "__main__":
    main()
