"""
NAMSUNG (Namsung Shipping) e-Service - Vessel Schedule Checker
================================================================
เช็คตารางเดินเรือ (schedule) ของสาย NAMSUNG จาก Bangkok และ Laem Chabang
(ประเทศไทย) ไป Ho Chi Minh (เวียดนาม) โดยดึงข้อมูลตรงจาก API ที่หน้าเว็บ
https://ebiz.namsung.co.kr ใช้งานอยู่ (endpoint: /sch/selectScheList)
แทนการเปิดเบราว์เซอร์ทีละหน้า

วิธีใช้:
    pip install requests
    python namsung_schedule.py

ผลลัพธ์:
    - พิมพ์ตารางออกทางหน้าจอ
    - บันทึกไฟล์ CSV ชื่อ namsung_schedule_bkk_lcb_to_hcm.csv ในโฟลเดอร์เดียวกัน

หมายเหตุ:
    - สคริปต์นี้เรียก endpoint ภายใน (internal API) ของเว็บไซต์ NAMSUNG
      โดยตรวจจับมาจากการเฝ้าดู network request ตอนค้นหาบนหน้าเว็บจริง
      หากทาง NAMSUNG เปลี่ยนโครงสร้าง API ในอนาคต สคริปต์นี้อาจต้องปรับปรุง
    - แนะนำให้ยืนยันข้อมูลกับเจ้าหน้าที่ NAMSUNG ก่อนทำการจองจริงเสมอ
      (ตารางเรืออาจเปลี่ยนแปลงได้)
"""

import csv
import json
from datetime import datetime

import requests

BASE_URL = "https://ebiz.namsung.co.kr"
API_ENDPOINT = f"{BASE_URL}/sch/selectScheList"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

HEADERS = {
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
    "User-Agent": USER_AGENT,
    "X-Requested-With": "XMLHttpRequest",
}

# ---- แก้ไขค่าตรงนี้ได้ตามต้องการ -------------------------------------

# ท่าต้นทาง (departure / POL) ที่จะเช็ค: ชื่อ -> {รหัสพอร์ต, คำอธิบายพอร์ตแบบเต็ม}
DEPARTURE_PORTS = {
    "BANGKOK": {"code": "THBKK", "desc": "BANGKOK, THAILAND"},
    "LAEM CHABANG": {"code": "THLCH", "desc": "LAEM CHABANG, THAILAND"},
}

# ท่าปลายทาง (arrival / POD)
ARRIVAL_PORT = {"code": "VNSGN", "desc": "HOCHIMINH, VIETNAM"}

# เดือนที่ต้องการเช็ค รูปแบบ YYYYMM (กันยายน 2026 = 202609, ... ธันวาคม 2026 = 202612)
MONTHS = ["202609", "202610", "202611", "202612"]

# inpdiv: "F" = Full (ตู้สินค้ามีของ) ตามค่า default ของหน้าเว็บ
CARGO_DIV = "F"

# ------------------------------------------------------------------------


def fetch_schedule(session, pol_code, pol_desc, pod_code, pod_desc, month):
    """เรียก API ตารางเรือของ NAMSUNG สำหรับ POL/POD/เดือนที่กำหนด"""
    payload = {
        "dma_search": {
            "bukrs": "1000",
            "inpmon": month,
            "inppolds": pol_desc,
            "inppodds": pod_desc,
            "inppol": pol_code,
            "inppod": pod_code,
            "inpdiv": CARGO_DIV,
            "inpdiv2": "",
            "inpvvd": "",
            "inptsd": "",
            "inplpt": "",
            "inpdpt": "",
            "book": "",
            "own": "",
            "USRNAT": "",
            "nextSearch": "",
        }
    }
    resp = session.post(
        API_ENDPOINT, headers=HEADERS, data=json.dumps(payload), timeout=20
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("dma_search", {}).get("vcursor", []) or []


def format_dt(date_str, time_str):
    """แปลง YYYYMMDD + HHMM ให้อ่านง่าย เช่น 2026-10-03 16:00"""
    if not date_str:
        return "-"
    try:
        dt = datetime.strptime(date_str + (time_str or "0000"), "%Y%m%d%H%M")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return f"{date_str} {time_str or ''}".strip()


def main():
    session = requests.Session()
    # เปิดหน้าแรกก่อนเพื่อตั้งค่า session/cookie ให้เหมือนการเข้าเว็บจริง
    try:
        session.get(BASE_URL + "/", headers={"User-Agent": USER_AGENT}, timeout=20)
    except requests.RequestException as e:
        print(f"[คำเตือน] เปิดหน้าแรกไม่สำเร็จ ({e}) จะลองเรียก API ต่อไปเลย")

    all_rows = []
    for pol_name, pol in DEPARTURE_PORTS.items():
        for month in MONTHS:
            try:
                rows = fetch_schedule(
                    session,
                    pol["code"],
                    pol["desc"],
                    ARRIVAL_PORT["code"],
                    ARRIVAL_PORT["desc"],
                    month,
                )
            except requests.RequestException as e:
                print(f"[ERROR] ดึงข้อมูล {pol_name} เดือน {month} ไม่สำเร็จ: {e}")
                continue

            if not rows:
                print(f"[INFO] ไม่พบเที่ยวเรือ: {pol_name} -> HOCHIMINH เดือน {month}")

            for r in rows:
                all_rows.append(
                    {
                        "departure_port": pol_name,
                        "month": month,
                        "vessel": r.get("VSL_NAME"),
                        "voyage": r.get("VSLVOY"),
                        "etd": format_dt(r.get("EXPORT_DT"), r.get("EXPORT_HH")),
                        "eta": format_dt(r.get("IMPORT_DT"), r.get("IMPORT_HH")),
                        "pol": r.get("LD_PORTD"),
                        "pod": r.get("DC_PORTD"),
                        "loading_terminal": r.get("GRMLTMLD1"),
                        "discharge_terminal": r.get("GRMDTMLD1"),
                        "cargo_closing": r.get("CCLOSING_INFO"),
                        "doc_closing": r.get("DCLOSING_INFO"),
                        "direct_or_ts": r.get("TS_MIN"),
                    }
                )

    # เรียงตามท่าต้นทาง แล้วตามวันออกเรือ
    all_rows.sort(key=lambda x: (x["departure_port"], x["etd"]))

    if not all_rows:
        print("ไม่พบข้อมูลตารางเรือเลย โปรดตรวจสอบการเชื่อมต่อ หรือพารามิเตอร์ค้นหา")
        return

    # พิมพ์ตารางสรุป
    header = f"{'Dep Port':14} {'Vessel/Voyage':26} {'ETD':17} {'ETA':17} {'Direct/TS':10}"
    print(header)
    print("-" * len(header))
    for row in all_rows:
        vv = f"{row['vessel']} {row['voyage']}"
        print(
            f"{row['departure_port']:14} {vv:26} {row['etd']:17} {row['eta']:17} "
            f"{(row['direct_or_ts'] or ''):10}"
        )

    # บันทึกเป็น CSV
    out_file = "namsung_schedule_bkk_lcb_to_hcm.csv"
    with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nพบทั้งหมด {len(all_rows)} เที่ยวเรือ -> บันทึกไฟล์แล้ว: {out_file}")


if __name__ == "__main__":
    main()
