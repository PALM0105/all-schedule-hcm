"""
Space (BSA) of the sailings Bangkok / Laem Chabang -> Ho Chi Minh City, read from HEUNG-A's SVMS internal API
(the same office key the 'sinokor-ovs-api-th' skill uses). Read-only.

Writes output/space.json:  [{"vessel", "voyage", "port" (BKK/LCH), "etd" (yyyymmddhhmm), "bsa", "load", "rob", "balance"}]
    bsa      space allocated on the vessel (TEU)
    load     TEU loaded / booked for loading at this port
    rob      TEU on board after this port
    balance  bsa - rob  (TEU still free after loading at this port; <= 0 means full)

Used by build_hcm_schedule.py (--mail-body) to tag HAL's sailings FULL / NEARLY FULL / SPACE LEFT.
If the API client is not installed or the call fails, the old file is left untouched and the mail simply has no space tags.
"""
import datetime as dt
import json
import sys
from pathlib import Path

API_DIR = Path(r"C:\Users\HAL-USER\SinokorAPI\Thailand_HEUNG-A")
OUT = Path(__file__).resolve().parent / "output" / "space.json"
DAYS_AHEAD = 24                    # a bit more than the three weeks shown in the mail


def main() -> int:
    if not (API_DIR / "ovs_client.py").exists():
        print(f"SVMS client not found in {API_DIR} - skipping space data")
        return 1
    sys.path.insert(0, str(API_DIR))
    sys.path.insert(0, str(API_DIR / "examples"))
    from ovs_client import OvsClient
    from _th import windows

    api = OvsClient()
    today = dt.date.today()
    first, last = today.strftime("%Y%m%d"), (today + dt.timedelta(days=DAYS_AHEAD)).strftime("%Y%m%d")

    voyages = {}
    for pol in ("THLCH", "THBKK"):
        for a, b in windows(first, last):
            for r in api.call("booking schedule", {"P_POL_CD": pol, "P_FROM_DT": a, "P_TO_DT": b, "P_POD_CD": "VNSGN"}):
                if str(r["VYG"]).endswith("N"):             # the "S" legs go the other way
                    voyages.setdefault((r["SVC"], r["VSL"], r["VYG"]), r["VSL_NM"])

    out = []
    for (svc, vsl, vyg), name in voyages.items():
        name = name.replace("[HAS]", "").strip().upper()
        try:
            rows = api.call("allocation", {"P_SVC_CD": svc, "P_VSL_CD": vsl, "P_VYG_NO": vyg})
        except Exception as exc:                       # one bad voyage must not lose the others
            print(f"  allocation failed for {name} {vyg}: {str(exc)[:80]}")
            continue
        seen = set()
        for x in rows:
            pol = str(x.get("POL") or "").split()[0] if x.get("POL") else ""
            if x.get("GB") != "TEU" or x.get("VYG") != vyg or pol not in ("THLCH", "THBKK") or pol in seen:
                continue
            if x.get("BSA") is None or x.get("BALANCE") is None:
                continue
            seen.add(pol)
            out.append({"vessel": name, "voyage": vyg, "port": "LCH" if pol == "THLCH" else "BKK",
                        "etd": x.get("ETD"), "bsa": x.get("BSA"), "load": x.get("LOAD"),
                        "rob": x.get("ROB"), "balance": x.get("BALANCE")})

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"generated": dt.datetime.now().isoformat(timespec="seconds"), "rows": out},
                              ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"space data: {len(out)} port calls on {len(voyages)} voyages -> {OUT.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
