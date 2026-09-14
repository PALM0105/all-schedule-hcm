#!/usr/bin/env python3
"""
SITC Shipping Schedule scraper
==============================

Automates https://api.sitcline.com/app/voyagePlanSearch (SITC's "Shipping
Schedule" web app) with a real browser (Playwright) and pulls every sailing
between a port of loading (POL) and a port of discharge (POD) inside a given
date range, paging through the site's built-in "+2weeks" navigation as needed.

Why a real browser and not `requests`?
The site is a JavaScript single-page app, and the POD value the frontend
sends to its search API (`/svl/voyageInfo/searchPlan`) is a client-side
*encrypted* token that changes based on internal app state -- it is not the
plain port code. Driving the real page with Playwright sidesteps all of that
by clicking exactly what a person would click.

Usage
-----
    pip install playwright --break-system-packages
    playwright install chromium        # not needed in environments where
                                        # chromium ships preinstalled

    python sitc_schedule.py \
        --lanes "Bangkok:Ho Chi Minh" "Laem Chabang:Ho Chi Minh" \
        --start 2026-09-01 --end 2026-10-31 \
        --out sitc_schedule.csv

Each `--lanes` entry is "POL:POD" using the same names you'd type into the
site's search box (e.g. "Bangkok", "Laem Chabang", "Ho Chi Minh"). The script
always picks the first ("plain", non "(SP-ITC)"/terminal-suffixed) suggestion
for each side; edit `PORT_DISAMBIGUATION` below if you need a specific
terminal-coded suggestion instead (e.g. "HO CHI MINH(SP-ITC)").

Output is a CSV with one row per sailing found in the window, plus a summary
printed to stdout.
"""

import argparse
import csv
import re
import sys
import time
from datetime import date, datetime, timedelta

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

SEARCH_URL = "https://api.sitcline.com/app/voyagePlanSearch"

# If a port name has multiple autocomplete matches (e.g. "Ho Chi Minh" also
# matches "HO CHI MINH(SP-ITC)"), by default we click the first suggestion.
# Add entries here to force a specific suggestion substring instead.
PORT_DISAMBIGUATION = {
    # "Ho Chi Minh": "HO CHI MINH(SP-ITC)",
}


def parse_args():
    p = argparse.ArgumentParser(description="Scrape SITC voyage schedules for one or more lanes.")
    p.add_argument(
        "--lanes",
        nargs="+",
        required=True,
        help='One or more "POL:POD" pairs, e.g. "Bangkok:Ho Chi Minh"',
    )
    p.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    p.add_argument("--end", required=True, help="End date YYYY-MM-DD (inclusive)")
    p.add_argument("--out", default="sitc_schedule.csv", help="Output CSV path")
    p.add_argument("--headless", action="store_true", default=True)
    p.add_argument("--show-browser", dest="headless", action="store_false")
    return p.parse_args()


def pick_suggestion(page, input_selector, query, disambiguation=None, timeout=8000):
    """Type `query` into the given input and click the matching autocomplete row.

    The site uses Element UI's <el-autocomplete>: each POL/POD field has its
    own (initially empty) `ul.el-autocomplete-suggestion__list` companion
    element already present in the DOM. Only the list belonging to the field
    you just typed into gets populated with <li> rows, so we simply wait for
    *some* list to have children and use that one -- this avoids accidentally
    matching unrelated text elsewhere on the page (e.g. the "History" panel,
    which repeats port names too).
    """
    box = page.locator(input_selector)
    box.click()
    box.fill("")
    box.type(query, delay=40)

    lists = page.locator("ul.el-autocomplete-suggestion__list")
    deadline = time.time() + timeout / 1000
    active_list = None
    while time.time() < deadline:
        for i in range(lists.count()):
            candidate = lists.nth(i)
            if candidate.locator("li").count() > 0:
                active_list = candidate
                break
        if active_list is not None:
            break
        page.wait_for_timeout(200)

    if active_list is None:
        raise RuntimeError(f"No autocomplete suggestions appeared for '{query}'")

    items = active_list.locator("li")
    texts = [items.nth(i).inner_text().strip() for i in range(items.count())]

    target_index = None
    if disambiguation:
        for i, t in enumerate(texts):
            if disambiguation.upper() in t.upper():
                target_index = i
                break
    if target_index is None:
        # Prefer the shortest / plain match (skips "...MODERN TERMINAL", "(SP-ITC)" etc.)
        target_index = min(range(len(texts)), key=lambda i: len(texts[i]))

    items.nth(target_index).click()
    page.wait_for_timeout(300)


def parse_window_header(page):
    """Read the 'ETD dd-mm -- dd-mm' (or ETA) header text shown above results."""
    header = page.locator("text=/ETD|ETA/").first.inner_text()
    m = re.search(r"(\d{2}-\d{2})\s*--\s*(\d{2}-\d{2})", header)
    return m.groups() if m else (None, None)


def month_day_to_date(md, ref_year):
    mm, dd = map(int, md.split("-"))
    return date(ref_year, mm, dd)


def scrape_lane(page, pol, pod, start_date, end_date):
    page.goto(SEARCH_URL, wait_until="networkidle")
    page.wait_for_selector("input[placeholder='POL']")

    pick_suggestion(page, "input[placeholder='POL']", pol)
    pick_suggestion(page, "input[placeholder='POD']", pod, PORT_DISAMBIGUATION.get(pod))

    # Set the Start Date field explicitly so results begin from the date we want.
    start_input = page.locator("input[placeholder*='date'], input[placeholder*='日期']").first
    start_input.click()
    start_input.fill("")
    start_input.type(start_date.strftime("%Y-%m-%d"), delay=30)
    page.keyboard.press("Escape")

    page.get_by_text("SEARCH", exact=True).click()
    page.wait_for_timeout(2000)

    results = []
    seen = set()
    ref_year = start_date.year
    prev_window = None

    for _ in range(60):  # hard safety cap on pagination
        # Wait for the window header to actually update before scraping,
        # since clicking "+2weeks" is async and a fixed sleep is unreliable.
        deadline = time.time() + 8
        cur_window = parse_window_header(page)
        while cur_window == prev_window and time.time() < deadline:
            page.wait_for_timeout(300)
            cur_window = parse_window_header(page)
        prev_window = cur_window
        page.wait_for_timeout(500)

        # Every voyage card repeats this label sequence; scrape them by block.
        body_text = page.inner_text("body")
        blocks = re.split(r"\nDIRECT\n", body_text)[1:]
        for block in blocks:
            def grab(label):
                mm = re.search(rf"{label}\s*:\s*\n?\s*([^\n]+)", block)
                return mm.group(1).strip() if mm else ""

            vessel = grab("VESSEL/VOYAGE")
            etd = grab("ETD")
            eta = grab("ETA")
            ctd = grab("CTD")
            cta = grab("CTA")
            key = (vessel, etd)
            if not vessel or key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "pol": pol,
                    "pod": pod,
                    "vessel_voyage": vessel,
                    "etd": etd,
                    "eta": eta,
                    "ctd": ctd,
                    "cta": cta,
                }
            )

        win_start_md, win_end_md = cur_window
        if win_end_md is None:
            break
        win_end = month_day_to_date(win_end_md, ref_year)
        # handle year rollover (Dec -> Jan) just in case a range spans it
        if win_end < month_day_to_date(win_start_md, ref_year):
            win_end = win_end.replace(year=ref_year + 1)

        if win_end >= end_date:
            break

        next_btn = page.get_by_text("+2weeks", exact=True)
        if next_btn.count() == 0:
            break
        next_btn.click()

    return results


def within_range(etd_str, start_date, end_date):
    m = re.match(r"(\d{2})-(\d{2})", etd_str)
    if not m:
        return True  # keep if unparseable rather than silently dropping
    mm, dd = int(m.group(1)), int(m.group(2))
    year = start_date.year
    d = date(year, mm, dd)
    if d < start_date and (d.month, d.day) < (start_date.month, start_date.day):
        d = d.replace(year=year + 1)
    return start_date <= d <= end_date


def main():
    args = parse_args()
    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date = datetime.strptime(args.end, "%Y-%m-%d").date()

    all_rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)
        page = browser.new_page(viewport={"width": 900, "height": 800})

        for lane in args.lanes:
            if ":" not in lane:
                print(f"Skipping malformed lane '{lane}' (expected POL:POD)", file=sys.stderr)
                continue
            pol, pod = [s.strip() for s in lane.split(":", 1)]
            print(f"Searching {pol} -> {pod} ...", file=sys.stderr)
            try:
                rows = scrape_lane(page, pol, pod, start_date, end_date)
            except (PWTimeout, RuntimeError) as e:
                print(f"  failed: {e}", file=sys.stderr)
                continue
            rows = [r for r in rows if within_range(r["etd"], start_date, end_date)]
            print(f"  found {len(rows)} sailings", file=sys.stderr)
            all_rows.extend(rows)

        browser.close()

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["pol", "pod", "vessel_voyage", "etd", "eta", "ctd", "cta"]
        )
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nWrote {len(all_rows)} sailings to {args.out}")


if __name__ == "__main__":
    main()
