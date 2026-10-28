"""
HAL's own view of the Bangkok / Laem Chabang -> Ho Chi Minh City sailings, read from HEUNG-A's SVMS internal API
(the same office key the 'sinokor-ovs-api-th' skill uses). Read-only.

Writes two files in output/:

  svms_schedule.json   every northbound sailing to Ho Chi Minh (VNSGN) from today until the end of the date range
      {"vessel", "svc", "oper", "voyage", "port" (BKK/LCH), "etd", "eta" (yyyymmddhhmm), "pol_terminal",
       "pod_terminal", "doc_close" (yyyymmddhhmm or None), "closed" (booking already closed)}
  space.json           space of the sailings in the next ~3 weeks (from the 'allocation' procedure)
      {"vessel", "voyage", "port", "etd", "bsa", "load", "rob", "balance"}
        bsa      space allocated on the vessel (TEU)
        load     TEU loaded / booked for loading at this port
        rob      TEU on board after this port
        balance  TEU still free for cargo loaded at this port = the smallest (bsa - rob) from this port to the
                 last Thai port of the voyage; <= 0 means full.  port_balance = bsa - rob at this port alone

build_hcm_schedule.py reads svms_schedule.json as HAL's schedule (instead of the 13 Sep snapshot) and the mail uses
space.json for the FULL / NEARLY FULL / SPACE LEFT tags.
If the API client is missing or a call fails, the old files are left untouched.
"""
import datetime as dt
import json
import sys
from pathlib import Path

API_DIR = Path(r"C:\Users\HAL-USER\SinokorAPI\Thailand_HEUNG-A")
OUT_DIR = Path(__file__).resolve().parent / "output"
SPACE_DAYS = 24            # a bit more than the three weeks the mail shows
BOOKING_DAYS = 24          # cut-off times come from existing bookings, so only near voyages have one


def api_available() -> bool:
    return (API_DIR / "ovs_client.py").exists()


def _load_api():
    sys.path.insert(0, str(API_DIR))
    sys.path.insert(0, str(API_DIR / "examples"))
    from ovs_client import OvsClient
    from _th import windows
    return OvsClient(), windows


def clean_name(n: str) -> str:
    return (n or "").replace("[HAS]", "").strip().upper()


def run(end: dt.date | None = None, log=print) -> dict:
    """Pull the schedule + space from SVMS and write the two files. Returns {"schedule": [...], "space": [...]}."""
    if not api_available():
        raise RuntimeError(f"SVMS client not found in {API_DIR}")
    api, windows = _load_api()
    today = dt.date.today()
    # always look about two months ahead so that every vessel SVMS knows is seen (the build trims to its own range)
    end = max(end or today, today + dt.timedelta(days=62))
    fmt = lambda d: d.strftime("%Y%m%d")

    # ---- 1) sailings to Ho Chi Minh ----------------------------------------------------------------
    sched = {}
    for pol in ("THLCH", "THBKK"):
        for a, b in windows(fmt(today), fmt(end)):
            for r in api.call("booking schedule", {"P_POL_CD": pol, "P_FROM_DT": a, "P_TO_DT": b, "P_POD_CD": "VNSGN"}):
                if r.get("POD") != "VNSGN" or not str(r.get("VYG", "")).endswith("N") or not r.get("ETD"):
                    continue                                    # the "S" legs go the other way
                key = (pol, r["SVC"], r["VSL"], r["VYG"])
                sched.setdefault(key, {
                    "vessel": clean_name(r["VSL_NM"]), "svc": r["SVC"], "oper": r.get("OPLINER"), "vsl": r["VSL"],
                    "voyage": r["VYG"], "port": "LCH" if pol == "THLCH" else "BKK", "etd": r["ETD"], "eta": r.get("ETA"),
                    "pol_terminal": r.get("POLWNM"), "pod_terminal": r.get("PODWNM"), "doc_close": None, "closed": False})

    # ---- 2) cut-off / closed flag from the booking list (only voyages that already have bookings) -------
    for pol in ("THLCH", "THBKK"):
        port = "LCH" if pol == "THLCH" else "BKK"
        for a, b in windows(fmt(today), fmt(today + dt.timedelta(days=BOOKING_DAYS))):
            for r in api.call("booking list", {"P_FROM_DT": a, "P_TO_DT": b, "P_POL_CD": pol}):
                for key, s in sched.items():
                    if key[0] == pol and s["vsl"] == r.get("VSL") and s["voyage"] == r.get("VYG"):
                        if r.get("DOC_CLOSE"):
                            s["doc_close"] = max(filter(None, [s["doc_close"], str(r["DOC_CLOSE"])]))
                        if str(r.get("HHCLOSING") or "").upper() == "CLOSED":
                            s["closed"] = True
    schedule = sorted(sched.values(), key=lambda s: (s["etd"], s["vessel"]))

    # ---- 3) space of the near sailings ---------------------------------------------------------------
    space, seen_voy = [], {}
    horizon = fmt(today + dt.timedelta(days=SPACE_DAYS))
    for s in schedule:
        if s["etd"][:8] <= horizon:
            seen_voy.setdefault((s["svc"], s["vsl"], s["voyage"]), s["vessel"])
    for (svc, vsl, vyg), name in seen_voy.items():
        try:
            rows = api.call("allocation", {"P_SVC_CD": svc, "P_VSL_CD": vsl, "P_VYG_NO": vyg})
        except Exception as exc:                       # one bad voyage must not lose the others
            log(f"  allocation failed for {name} {vyg}: {str(exc)[:80]}")
            continue
        seen = set()
        for x in rows:
            pol = str(x.get("POL") or "").split()[0] if x.get("POL") else ""
            if x.get("GB") != "TEU" or x.get("VYG") != vyg or pol not in ("THLCH", "THBKK") or pol in seen:
                continue
            if x.get("BSA") is None or x.get("BALANCE") is None:
                continue
            seen.add(pol)
            space.append({"vessel": name, "voyage": vyg, "port": "LCH" if pol == "THLCH" else "BKK",
                          "etd": x.get("ETD"), "bsa": x.get("BSA"), "load": x.get("LOAD"),
                          "rob": x.get("ROB"), "balance": x.get("BALANCE")})

    # Space for cargo loaded at a port is limited by the tightest point of the rest of the trip: cargo booked at
    # Bangkok rides on to Laem Chabang, so Bangkok's own balance is only usable if Laem Chabang still has room too.
    by_voy = {}
    for r in space:
        by_voy.setdefault((r["vessel"], r["voyage"]), []).append(r)
    for rows_ in by_voy.values():
        rows_.sort(key=lambda r: r["etd"] or "")
        for i, r in enumerate(rows_):
            r["port_balance"] = r["balance"]
            r["balance"] = min(x["port_balance"] if "port_balance" in x else x["balance"] for x in rows_[i:])

    OUT_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    (OUT_DIR / "svms_schedule.json").write_text(
        json.dumps({"generated": stamp, "rows": schedule}, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT_DIR / "space.json").write_text(
        json.dumps({"generated": stamp, "rows": space}, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"SVMS: {len(schedule)} sailings to Ho Chi Minh, space for {len(space)} port calls")
    return {"schedule": schedule, "space": space}


def load_schedule(max_age_hours: float = 36):
    """Rows of output/svms_schedule.json if it is fresh enough, else None."""
    try:
        d = json.loads((OUT_DIR / "svms_schedule.json").read_text(encoding="utf-8"))
        if dt.datetime.now() - dt.datetime.fromisoformat(d["generated"]) <= dt.timedelta(hours=max_age_hours):
            return d["rows"]
    except (OSError, ValueError, KeyError):
        pass
    return None


def main() -> int:
    try:
        run()
    except Exception as exc:
        print(f"SVMS pull failed - old files kept: {str(exc)[:120]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
