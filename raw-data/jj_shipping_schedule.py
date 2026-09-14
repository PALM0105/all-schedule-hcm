"""
JJ Shipping (yourjjshipping.app) Sailing Schedule Scraper
-----------------------------------------------------------
ดึงตารางการเดินเรือจากเว็บไซต์ JJ Shipping Thailand
เส้นทาง: Bangkok และ Laem Chabang -> Ho Chi Minh City
ช่วงเดือน: กันยายน (9) และ ตุลาคม (10) ปี 2026

วิธีใช้:
    pip install requests beautifulsoup4
    python jj_shipping_schedule.py
"""

import csv
import datetime
import time
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://yourjjshipping.app/wp-admin/admin-ajax.php"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Referer": "https://yourjjshipping.app/sailing-schedules/",
}

# code ปลายทางตามที่ dropdown ของเว็บส่งไป (ค่าต่างกันตามต้นทางที่เลือก)
ROUTES = {
    "Bangkok": "309-7-11,327-4-10",
    "Laem Chabang": "309-4-11,327-7-10",
}

THAI_MONTHS = {
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4,
    "พฤษภาคม": 5, "มิถุนายน": 6, "กรกฎาคม": 7, "สิงหาคม": 8,
    "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
}

TARGET_MONTHS = {9, 10, 11, 12}  # กันยายน ถึง ธันวาคม
TARGET_YEAR = 2026
TARGET_DESTINATION = "Ho Chi Minh"


def thai_date_to_date(thai_str):
    """แปลง 'อังคาร 8 กันยายน 2026' -> datetime.date(2026, 9, 8)"""
    parts = thai_str.strip().split()
    try:
        day = int(parts[1])
        month = THAI_MONTHS.get(parts[2])
        year = int(parts[3])
        if not month:
            return None
        return datetime.date(year, month, day)
    except (IndexError, ValueError):
        return None


def fetch_schedule(page_code, start_date, weeks=3, arrival=0):
    params = {
        "action": "sailing_schedule",
        "page": page_code,
        "date": start_date.strftime("%Y-%m-%d"),
        "arrival": arrival,
        "weeks": weeks,
    }
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def parse_cards(html, search_origin):
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for card in soup.select("div.sailing-card"):
        try:
            closing = card.select_one(".color-soft.text-size-xs").get_text(strip=True)
            closing = closing.replace("Closing", "").strip()

            dept_date_txt = card.select_one(".dept .text-bold").get_text(strip=True)
            origin_port = card.select_one(".dept .origin").get_text(strip=True)

            voy_blocks = card.select(".voys > div")
            vessel = voy_blocks[0].select_one("span").get_text(strip=True) if len(voy_blocks) > 0 else ""
            voy = voy_blocks[1].select_one("span").get_text(strip=True) if len(voy_blocks) > 1 else ""
            code = voy_blocks[2].select_one("span").get_text(strip=True) if len(voy_blocks) > 2 else ""

            days_txt = card.select_one(".days").get_text(strip=True)

            arrv_date_txt = card.select_one(".arrv .text-bold").get_text(strip=True)
            dest_port = card.select_one(".arrv > div").get_text(strip=True)

            results.append({
                "search_origin": search_origin,
                "closing": closing,
                "departure_date_text": dept_date_txt,
                "departure_date": thai_date_to_date(dept_date_txt),
                "origin_port": origin_port,
                "vessel": vessel,
                "voyage": voy,
                "code": code,
                "transit_days": days_txt,
                "arrival_date_text": arrv_date_txt,
                "arrival_date": thai_date_to_date(arrv_date_txt),
                "destination_port": dest_port,
            })
        except AttributeError:
            continue
    return results


def collect_all():
    all_rows = []
    seen = set()

    start = datetime.date(TARGET_YEAR, 9, 1)
    end = datetime.date(TARGET_YEAR, 12, 31)

    for search_origin, page_code in ROUTES.items():
        cursor = start
        while cursor <= end:
            html = fetch_schedule(page_code, cursor, weeks=3, arrival=0)
            for r in parse_cards(html, search_origin):
                if TARGET_DESTINATION not in r["destination_port"]:
                    continue
                if not r["departure_date"]:
                    continue
                if r["departure_date"].year != TARGET_YEAR or r["departure_date"].month not in TARGET_MONTHS:
                    continue
                key = (r["vessel"], r["voyage"], r["departure_date"], r["origin_port"])
                if key in seen:
                    continue
                seen.add(key)
                all_rows.append(r)
            time.sleep(0.5)          # หน่วงเวลาเล็กน้อย ไม่ยิง request ถี่เกินไป
            cursor += datetime.timedelta(days=14)   # เลื่อนหน้าต่างค้นหาทีละ 2 สัปดาห์ (มี overlap กับ weeks=3)

    all_rows.sort(key=lambda r: r["departure_date"])
    return all_rows


def save_csv(rows, filename="jj_shipping_hcm_schedule.csv"):
    fieldnames = ["search_origin", "origin_port", "destination_port",
                  "departure_date", "arrival_date", "transit_days",
                  "vessel", "voyage", "code", "closing"]
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in fieldnames})
    print(f"บันทึกไฟล์ผลลัพธ์แล้ว: {filename}")


def main():
    print(f"กำลังดึงตารางเดินเรือ Bangkok / Laem Chabang -> Ho Chi Minh City "
          f"เดือน 9-12/{TARGET_YEAR} จาก yourjjshipping.app ...\n")
    rows = collect_all()

    if not rows:
        print("ไม่พบข้อมูลตารางเรือที่ตรงกับเงื่อนไข")
        return

    print(f"{'ต้นทาง':<14}{'ปิดรับตู้':<20}{'วันออก':<14}{'เรือ':<18}{'VOY':<10}{'วันถึง':<14}{'ปลายทาง'}")
    print("-" * 110)
    for r in rows:
        print(f"{r['search_origin']:<14}{r['closing']:<20}{str(r['departure_date']):<14}"
              f"{r['vessel']:<18}{r['voyage']:<10}{str(r['arrival_date']):<14}{r['destination_port']}")

    save_csv(rows)


if __name__ == "__main__":
    main()
