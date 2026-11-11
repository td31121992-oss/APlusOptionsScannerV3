"""Build the F&O sector map from NSE's official files (reference data; no trading effect).

Source (data/reference/nse_lists, downloaded from NSE / NSE Indices, see SOURCE.txt):
    ind_nifty500list.csv          every Nifty 500 stock with NSE's own "Industry" (its macro-economic classification)
    ind_nifty*list.csv            the official constituent lists of the sectoral indices, used to split NSE's broad groups the way NSE itself does

Label of a stock = the first rule that matches:
    1. in the Nifty Private Bank list                 -> "Private Banks"
    2. in the Nifty PSU Bank list                     -> "PSU Banks"
    3. in the Nifty Capital Markets list              -> "Capital Markets"
    4. in the Nifty India Defence list                -> "Defence"
    5. otherwise NSE's Industry, shown with the name this software already used where there is one (IT, Auto, Pharma/Healthcare, FMCG/Consumer, Metals, Power/Utilities,
       Energy/Oil & Gas, Chemicals, Telecom/Media) and with NSE's own name for the rest (see INDUSTRY_LABEL).
A stock that is not in the Nifty 500 file keeps a manual label (MANUAL) and is marked as such.

Writes data/reference/fno_sector_map_nse.csv  (symbol, sector, nse_industry, nse_lists, old_sector, source) and data/reference/fno_sector_map_changes.md (what moved).
The scanner reads data/reference/fno_sector_map.csv (columns symbol, sector); `--apply` replaces it with the new map after saving the old file next to it.

    python build_nse_sector_map.py                 build the new map and the change report
    python build_nse_sector_map.py --download     fetch fresh copies of NSE's files first
    python build_nse_sector_map.py --apply        also replace the scanner's active map (the old one is kept as fno_sector_map.before-nse-<date>.csv)
"""

from __future__ import annotations

import csv
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REF = ROOT / "data" / "reference"
LISTS = REF / "nse_lists"
NIFTY500 = "ind_nifty500list.csv"
NIFTY500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
INDEX_URL = "https://www.niftyindices.com/IndexConstituent/{}.csv"
SPLIT_LISTS = (("ind_nifty_privatebanklist.csv", "Private Banks"), ("ind_niftypsubanklist.csv", "PSU Banks"), ("ind_niftycapitalmarkets_list.csv", "Capital Markets"),
               ("ind_niftyindiadefence_list.csv", "Defence"))
OTHER_LISTS = ("ind_niftybanklist", "ind_niftyfinancelist", "ind_niftyrealtylist", "ind_niftyautolist", "ind_niftyitlist", "ind_niftypharmalist", "ind_niftyhealthcarelist",
               "ind_niftyfmcglist", "ind_niftymetallist", "ind_niftyenergylist", "ind_niftyoilgaslist", "ind_niftyconsumerdurableslist", "ind_niftymedialist", "ind_niftyinfralist")
INDUSTRY_LABEL = {
    "Information Technology": "IT", "Healthcare": "Pharma/Healthcare", "Fast Moving Consumer Goods": "FMCG/Consumer", "Automobile and Auto Components": "Auto",
    "Metals & Mining": "Metals", "Power": "Power/Utilities", "Oil Gas & Consumable Fuels": "Energy/Oil & Gas", "Chemicals": "Chemicals", "Capital Goods": "Capital Goods",
    "Consumer Durables": "Consumer Durables", "Consumer Services": "Consumer Services", "Services": "Services", "Realty": "Real Estate", "Construction": "Construction/Infra",
    "Construction Materials": "Cement/Construction Materials", "Telecommunication": "Telecom/Media", "Media Entertainment & Publication": "Telecom/Media", "Textiles": "Textiles",
    "Diversified": "Diversified", "Financial Services": "NBFC & Insurance",
}
MANUAL = {"UJJIVANSFB": ("Private Banks", "manual: a small finance bank that is not in the Nifty 500 file"),
          "ICICIPRULI": ("NBFC & Insurance", "manual: a life insurer that is not in the Nifty 500 file")}                  # any F&O stock missing from the NSE files


def download() -> None:
    import urllib.request

    LISTS.mkdir(parents=True, exist_ok=True)
    jobs = [(NIFTY500_URL, NIFTY500)] + [(INDEX_URL.format(n[:-4] if n.endswith(".csv") else n), (n if n.endswith(".csv") else n + ".csv")) for n, _ in SPLIT_LISTS] + \
           [(INDEX_URL.format(n), n + ".csv") for n in OTHER_LISTS]
    for url, name in jobs:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        data = urllib.request.urlopen(req, timeout=40).read()
        if not data.startswith(b"Company Name"):
            raise RuntimeError(f"{url} did not return a constituent list")
        (LISTS / name).write_bytes(data)
        print("downloaded", name, len(data), "bytes")


def read_list(name: str) -> dict[str, dict[str, str]]:
    path = LISTS / name
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as h:
        return {r["Symbol"].strip().upper(): r for r in csv.DictReader(h)}


def classify(symbol: str, nifty500: dict[str, dict[str, str]], splits: dict[str, set[str]], member_of: dict[str, list[str]]) -> tuple[str, str, str]:
    """(sector label, NSE industry, source) of one stock."""
    row = nifty500.get(symbol)
    if row is None:
        label, why = MANUAL.get(symbol, ("UNCLASSIFIED", "not in the NSE files"))
        return label, "", why
    for _, label in SPLIT_LISTS:
        if symbol in splits[label]:
            return label, row["Industry"], f"NSE {label} index list"
    return INDUSTRY_LABEL.get(row["Industry"], row["Industry"]), row["Industry"], "NSE Nifty 500 Industry"


def build(universe: list[str], old: dict[str, str]) -> list[dict[str, str]]:
    nifty500 = read_list(NIFTY500)
    splits = {label: set(read_list(name)) for name, label in SPLIT_LISTS}
    member_of: dict[str, list[str]] = defaultdict(list)
    for name in [n for n, _ in SPLIT_LISTS] + [n + ".csv" for n in OTHER_LISTS]:
        for sym in read_list(name):
            member_of[sym].append(name.replace("ind_", "").replace("list.csv", "").replace("_.csv", "").replace(".csv", ""))
    out = []
    for sym in sorted(universe):
        label, industry, source = classify(sym, nifty500, splits, member_of)
        out.append({"symbol": sym, "sector": label, "nse_industry": industry, "nse_lists": ";".join(sorted(member_of.get(sym, []))), "old_sector": old.get(sym, ""), "source": source})
    return out


def load_old(path: Path) -> dict[str, str]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as h:
            return {r["symbol"].strip().upper(): r["sector"].strip() for r in csv.DictReader(h) if r.get("symbol")}
    except OSError:
        return {}


def report(rows: list[dict[str, str]]) -> str:
    sizes = Counter(r["sector"] for r in rows)
    moved = [r for r in rows if r["old_sector"] and r["old_sector"] != r["sector"]]
    lines = ["# F&O sector map rebuilt from NSE's official files", "", f"{len(rows)} stocks; {len(moved)} changed label. Sectors with fewer than 4 stocks are never ranked by the sector rules.", "",
             "## Sectors", ""] + [f"- **{k}** - {v}" + ("  (under 4: not ranked)" if v < 4 else "") for k, v in sizes.most_common()]
    flow: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in moved:
        flow[(r["old_sector"], r["sector"])].append(r["symbol"])
    lines += ["", "## What moved (old label -> new label)", ""]
    for (a, b), syms in sorted(flow.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"- {a} -> **{b}** ({len(syms)}): {', '.join(sorted(syms))}")
    manual = [r for r in rows if r["source"].startswith("manual") or r["sector"] == "UNCLASSIFIED"]
    if manual:
        lines += ["", "## Not in the NSE files", ""] + [f"- {r['symbol']}: {r['sector']} ({r['source']})" for r in manual]
    return "\n".join(lines) + "\n"


def main() -> int:
    if "--download" in sys.argv:
        download()
    active = REF / "fno_sector_map.csv"
    backups = sorted(REF.glob("fno_sector_map.before-nse-*.csv"))
    old = load_old(backups[0] if backups else active)                     # compare with the map from before the NSE rebuild
    try:                                                                    # the scanner's own F&O stock list (the old map file was missing a few of them)
        sys.path.insert(0, str(ROOT))
        from order_book_recorder import _universe

        universe = sorted(set(_universe()) | set(load_old(active) or old))
    except Exception:                                                       # noqa: BLE001
        universe = list(load_old(active) or old)
    rows = build(universe, old)
    cols = ["symbol", "sector", "nse_industry", "nse_lists", "old_sector", "source"]
    with (REF / "fno_sector_map_nse.csv").open("w", encoding="utf-8", newline="") as h:
        w = csv.DictWriter(h, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    (REF / "fno_sector_map_changes.md").write_text(report(rows), encoding="utf-8")
    print(f"{len(rows)} stocks -> data/reference/fno_sector_map_nse.csv and fno_sector_map_changes.md")
    if "--apply" in sys.argv:
        if not backups:
            shutil.copy(active, REF / f"fno_sector_map.before-nse-{date.today().isoformat()}.csv")
        with active.open("w", encoding="utf-8-sig", newline="") as h:
            w = csv.writer(h)
            w.writerow(["symbol", "sector"])
            w.writerows((r["symbol"], r["sector"]) for r in rows)
        print("scanner map replaced: data/reference/fno_sector_map.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
