"""
scraper_partitioned.py -- crawl SINTA WITHOUT losing 22% of the data.

THE PROBLEM
-----------
SINTA's listing is sorted by Impact, and Impact changes while you crawl.
Measured directly (probe_form.py section 4):

    page 50 at t=0s   : [..., 2867, 873]
    page 50 at t=30s  : [..., 2867, 873]   10/10 unchanged
    page 50 at t=60s  : [..., 2867, 329]    9/10 unchanged

Drift is SLOW but relentless. Over a 45-minute crawl it cost 3,382
journals (22%): they slid between pages and were never fetched, while
others were fetched repeatedly. The loss was INVISIBLE -- duplicates
backfilled the total so exactly that every accreditation count matched
SINTA's published figures. Total-based validation is necessary but NOT
sufficient; only a uniqueness check catches this.

Sorting cannot fix it: the sort control is a POST form
(changesort=1, sort=1..5), so there is no GET param to pin, and every
sort option is a MUTABLE metric anyway. Page size is locked at 10.

THE FIX -- PARTITION, DON'T FIGHT
---------------------------------
Form #3 exposes accreditation filters:

    filter_accreditation[1..6]   -> S1..S6
    filter_accreditation[91,92]  -> the non-S tiers

Accreditation is a STATIC administrative label. A journal's Impact
fluctuates minute to minute; its S-rank does not. So if we crawl one
tier at a time, the MEMBERSHIP of that partition is fixed for the
duration -- only the order within it wobbles, and each partition is
small enough to finish before the wobble matters:

    S1:   268 journals ->  27 pages -> ~45 seconds
    S6:   262 journals ->  27 pages -> ~45 seconds
    S2: 1,511 journals -> 152 pages -> ~4 minutes
    S3: 2,834 journals -> 284 pages -> ~8 minutes
    S4: 5,239 journals -> 524 pages -> ~15 minutes
    S5: 5,338 journals -> 534 pages -> ~15 minutes

And the partition sizes are KNOWN, so each one self-verifies: if the S1
crawl yields exactly 268 unique journals, we provably have all of them.

Usage:
    python scraper_partitioned.py --probe        # S1 only (~45s)
    python scraper_partitioned.py                # all tiers (~45 min)
    python scraper_partitioned.py --no-cache     # force refetch
"""

import argparse
import json
import pathlib
import random
import time
from datetime import datetime, timezone

import requests

from parser import parse_page

BASE = "https://sinta.kemdiktisaintek.go.id/journals"

UA = ("SintaAcademicScraper/1.0 "
      "(Seleksi Asisten Lab Basis Data ITB 2026; "
      "mailto:18224081@std.stei.itb.ac.id)")

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://sinta.kemdiktisaintek.go.id",
    "Referer": BASE,
}

DELAY = 1.5
TIMEOUT = 30
MAX_RETRIES = 3

ROOT = pathlib.Path(__file__).parent.parent
CACHE = ROOT / "cache_partitioned"
DATA = ROOT / "data"

# code -> (label, expected count from SINTA's own donut chart)
PARTITIONS = {
    "1":  ("S1", 268),
    "2":  ("S2", 1511),
    "3":  ("S3", 2834),
    "4":  ("S4", 5239),
    "5":  ("S5", 5338),
    "6":  ("S6", 262),
    "91": ("Other-91", None),   # Cancelled / Not Accredited -- exact
    "92": ("Other-92", None),   # split unknown; we discover it
}


def fetch(code: str, page: int, session: requests.Session,
          use_cache: bool = True) -> str:
    """
    POST one page of one accreditation partition.

    The filter is a POST form, so we cannot express it as a URL. We send
    the checkbox exactly as the browser would:

        filter_accreditation[3] = 3
        page                    = 12
    """
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / f"acc{code}_page_{page:04d}.html"

    if use_cache and cached.exists():
        return cached.read_text(encoding="utf-8")

    payload = {
        f"filter_accreditation[{code}]": code,
        "page": str(page),
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.post(f"{BASE}?page={page}", data=payload,
                             headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            cached.write_text(r.text, encoding="utf-8")
            time.sleep(DELAY + random.uniform(0, 0.4))
            return r.text
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                raise
            wait = 2 ** attempt
            print(f"      retry {attempt}/{MAX_RETRIES} in {wait}s -- {e}")
            time.sleep(wait)


def crawl_partition(code: str, session: requests.Session,
                    use_cache: bool = True) -> dict:
    """Crawl one accreditation tier. Returns {journal_id: record}."""
    label, expected = PARTITIONS[code]
    print(f"\n{'=' * 58}")
    print(f"{label}  (expecting {expected if expected else '?'} journals)")
    print(f"{'=' * 58}")

    found = {}
    page = 1
    dupes = 0

    while True:
        html = fetch(code, page, session, use_cache)
        rows = parse_page(html)

        if not rows:
            break

        for r in rows:
            jid = r["journal_id"]
            if jid is None:
                continue
            if jid in found:
                dupes += 1
            found[jid] = r

        if page % 50 == 0:
            print(f"  page {page:>4}  unique={len(found):>5}")

        page += 1

        # Safety valve: never loop forever if pagination misbehaves.
        if expected and page > (expected // 10) + 20:
            break

    got = len(found)
    print(f"  pages   : {page - 1}")
    print(f"  unique  : {got:,}")
    print(f"  dupes   : {dupes}")

    if expected:
        if got == expected:
            print(f"  EXACT MATCH -- all {expected:,} journals captured")
        else:
            print(f"  MISMATCH -- expected {expected:,}, got {got:,} "
                  f"(off by {abs(expected - got):,})")

    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true",
                    help="crawl S1 only (~45s) as a smoke test")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--only", help="crawl one tier, e.g. --only 3")
    args = ap.parse_args()

    if args.probe:
        codes = ["1"]
    elif args.only:
        codes = [args.only]
    else:
        # Smallest first: fail fast and cheap if something is wrong.
        codes = ["1", "6", "91", "92", "2", "3", "4", "5"]

    batch_ts = datetime.now(timezone.utc).isoformat()
    print(f"batch timestamp: {batch_ts}")
    print(f"cache: {'ON' if not args.no_cache else 'OFF'}")

    session = requests.Session()
    all_found = {}

    for code in codes:
        part = crawl_partition(code, session, use_cache=not args.no_cache)
        label = PARTITIONS[code][0]

        for jid, rec in part.items():
            rec["scraped_at"] = batch_ts
            if jid in all_found:
                prev = all_found[jid].get("_partition")
                print(f"  !! id={jid} appears in BOTH {prev} and {label}")
            rec["_partition"] = label
            all_found[jid] = rec

    # -----------------------------------------------------------------
    print(f"\n{'=' * 58}")
    print("TOTAL")
    print(f"{'=' * 58}")
    print(f"  unique journals : {len(all_found):,}")
    print(f"  SINTA reports   : 15,453")

    if len(all_found) == 15453:
        print("\n  COMPLETE -- every journal captured, zero loss")
    elif not args.probe and not args.only:
        gap = 15453 - len(all_found)
        print(f"\n  {gap:,} short. Check which partition mismatched above.")

    DATA.mkdir(exist_ok=True)
    out = DATA / "partitioned_raw.json"
    out.write_text(
        json.dumps(list(all_found.values()), indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"\n  wrote {out}")
    print("\n  Next: python split_partitioned.py   (to build the entity JSONs)")


if __name__ == "__main__":
    main()