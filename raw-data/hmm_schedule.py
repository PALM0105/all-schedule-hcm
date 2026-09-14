"""
hmm_schedule.py
================
Scrapes HMM's (www.hmm21.com) "Point to Point" container-vessel schedule
search for two Thai load ports -> Ho Chi Minh City, across several months,
and saves everything into one Excel file.

Route covered:
    Bangkok (THBKK)       -> Ho Chi Minh City (VNSGN)
    Laem Chabang (THLCH)  -> Ho Chi Minh City (VNSGN)

Period covered:
    One search per calendar month, September - December (edit YEAR / MONTHS
    below), each using the site's widest "weeks ahead" window (8 weeks) so
    every sailing in that month is very likely captured.

WHY THIS RUNS AS A BROWSER-AUTOMATION SCRIPT, NOT A SIMPLE REQUESTS CALL
-------------------------------------------------------------------------
www.hmm21.com's schedule page is a JavaScript app: the port fields use a
jQuery autocomplete box, choosing a port pops up a "Facility Guide List"
modal you must confirm, and the result list is rendered client-side after
an AJAX call. There is no plain documented JSON endpoint to hit directly,
so this script drives a real (headless) Chromium browser with Playwright,
exactly the way a person would use the page.

SETUP (run once)
-----------------
    pip install playwright pandas openpyxl
    playwright install chromium

RUN
---
    python hmm_schedule.py

OUTPUT
------
    hmm_schedule_bkk_lcb_to_hcm.xlsx   <- combined results, one row per sailing
    debug_screens/*.png                <- a screenshot from every search, for
                                           you to sanity-check what the site
                                           actually returned
    debug_html/*.html                  <- full page HTML from every search,
                                           in case the table layout needs a
                                           small tweak later

IMPORTANT NOTE ABOUT THE RESULT-TABLE PARSER
---------------------------------------------
This site was inspected by hand (autocomplete boxes, the Facility Guide List
popup, the date/weeks-ahead controls, and the Retrieve button were all
confirmed directly). The exact HTML structure of the RESULTS table itself
could not be double-checked in the same session because the browser tool
disconnected right before the final "Retrieve" click could be captured.
`scrape_results()` below therefore uses a generic, defensive row-scraper
(any <tr> with 4+ <td> cells) that keeps the *raw* cell text for every row
instead of guessing fixed column names. Once you run this and look at one
screenshot/HTML dump, tell me what the columns actually are (or send me the
HTML) and I will tighten `scrape_results()` into clean columns like
Vessel / Voyage / ETD / ETA / Transit.
"""

import re
import os
from datetime import date
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

BASE_URL = "https://www.hmm21.com/e-service/general/schedule/ScheduleMain.do"

# ---------------------------------------------------------------- SETTINGS
ORIGINS = [
    {"query": "Bangkok",      "label": "BANGKOK"},
    {"query": "Laem Chabang", "label": "LAEM CHABANG"},
]
# NOTE: the site's autocomplete matched "Hochiminh" (no space) but NOT
# "Ho Chi Minh" (with spaces) when this was checked by hand - the code
# below tries the query as given first and automatically retries without
# spaces if no dropdown match shows up, so this is handled either way.
DESTINATION = {"query": "Ho Chi Minh", "label": "HOCHIMINH"}

YEAR = 2026
MONTHS = [9, 10, 11, 12]     # September, October, November, December
WEEKS_AHEAD_LABEL = "8 weeks"   # widest window offered by the site per search

OUT_XLSX = "hmm_schedule_bkk_lcb_to_hcm.xlsx"
SCREEN_DIR = "debug_screens"
HTML_DIR = "debug_html"


# ------------------------------------------------------------- AUTOMATION
def select_location(page, box_index: int, query: str, expected_label: str):
    """
    Fill one of the two "Input a location (at least 2 charaters)." boxes
    (box_index 0 = Origin/Service Term, 1 = Destination/Service Term),
    wait for the autocomplete dropdown, and click the row that matches
    expected_label (e.g. "BANGKOK" or "HOCHIMINH").
    """
    box = page.locator("input[placeholder*='Input a location']").nth(box_index)
    box.click()
    box.fill("")

    def try_query(q):
        box.fill("")
        box.type(q, delay=60)
        item = page.locator(
            "ul li, .autocomplete li, li.ui-menu-item",
            has_text=re.compile(re.escape(expected_label), re.I),
        ).first
        try:
            item.wait_for(state="visible", timeout=4000)
            return item
        except PWTimeout:
            return None

    item = try_query(query)
    if item is None:
        # fallback: the site's index can be picky about spaces
        item = try_query(query.replace(" ", ""))
    if item is None:
        raise RuntimeError(
            f"Could not find '{expected_label}' in the autocomplete list "
            f"for query '{query}'. Try a different spelling."
        )
    item.click()


def close_facility_popup(page):
    """
    Selecting a port normally pops up "Facility Guide List". Pick the
    first row (this is "ALL / ALL TERMINAL" on every port checked so far)
    and click Apply. If no popup appears this time, just move on.
    """
    try:
        page.get_by_text("Facility Guide List", exact=False).wait_for(
            state="visible", timeout=4000
        )
    except PWTimeout:
        return

    first_radio = page.locator("input[type=radio]").first
    first_radio.check()
    page.get_by_role("button", name=re.compile("Apply", re.I)).click()
    page.wait_for_timeout(500)


def set_sailing_date(page, iso_date: str):
    date_input = page.locator("input[type=date]").first
    date_input.fill(iso_date)


def set_weeks_ahead(page, weeks_label: str):
    # the "weeks ahead" control is a <select> next to the sailing-date input
    selects = page.locator("select")
    for i in range(selects.count()):
        sel = selects.nth(i)
        options = sel.locator("option").all_inner_texts()
        if any("week" in o.lower() for o in options):
            sel.select_option(label=weeks_label)
            return
    raise RuntimeError("Could not find the 'weeks ahead' dropdown.")


def click_retrieve(page):
    page.get_by_role("button", name=re.compile(r"^Retrieve$", re.I)).click()
    page.wait_for_load_state("networkidle", timeout=20000)
    page.wait_for_timeout(1500)


def scrape_results(page):
    """
    Defensive, structure-agnostic scrape: keep the raw text of every table
    row that has at least 4 cells. See the module docstring for why this
    is intentionally not parsed into fixed columns yet.
    """
    rows = []
    tables = page.locator("table")
    for t in range(tables.count()):
        table = tables.nth(t)
        trs = table.locator("tr")
        for r in range(trs.count()):
            cells = trs.nth(r).locator("td").all_inner_texts()
            cells = [c.strip().replace("\n", " ") for c in cells if c.strip()]
            if len(cells) >= 4:
                rows.append(cells)
    return rows


def run_one_search(page, origin, destination, start_date: date):
    page.goto(BASE_URL, wait_until="networkidle")
    page.wait_for_timeout(1500)

    select_location(page, 0, origin["query"], origin["label"])
    close_facility_popup(page)

    select_location(page, 1, destination["query"], destination["label"])
    close_facility_popup(page)

    set_sailing_date(page, start_date.isoformat())
    set_weeks_ahead(page, WEEKS_AHEAD_LABEL)
    click_retrieve(page)

    return scrape_results(page)


def main():
    os.makedirs(SCREEN_DIR, exist_ok=True)
    os.makedirs(HTML_DIR, exist_ok=True)

    all_rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for origin in ORIGINS:
            for month in MONTHS:
                start = date(YEAR, month, 1)
                tag = f"{origin['label']}_{start.isoformat()}"
                print(f"Searching {origin['label']} -> {DESTINATION['label']} "
                      f"from {start} ({WEEKS_AHEAD_LABEL}) ...")
                try:
                    raw_rows = run_one_search(page, origin, DESTINATION, start)
                    page.screenshot(path=f"{SCREEN_DIR}/{tag}.png", full_page=True)
                    with open(f"{HTML_DIR}/{tag}.html", "w", encoding="utf-8") as f:
                        f.write(page.content())

                    for cells in raw_rows:
                        all_rows.append({
                            "origin": origin["label"],
                            "destination": DESTINATION["label"],
                            "search_month": start.strftime("%Y-%m"),
                            "row_cells": " | ".join(cells),
                        })
                    print(f"  -> {len(raw_rows)} table rows captured")
                except Exception as e:
                    print(f"  ! failed: {e}")
                    page.screenshot(path=f"{SCREEN_DIR}/{tag}_ERROR.png", full_page=True)

        browser.close()

    df = pd.DataFrame(all_rows)
    df.to_excel(OUT_XLSX, index=False)
    print(f"\nSaved {len(df)} rows across {len(ORIGINS) * len(MONTHS)} searches "
          f"to {OUT_XLSX}")
    print(f"Screenshots: ./{SCREEN_DIR}/   HTML dumps: ./{HTML_DIR}/")


if __name__ == "__main__":
    main()
