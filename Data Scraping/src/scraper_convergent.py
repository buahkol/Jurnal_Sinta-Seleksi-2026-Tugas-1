"""
scraper_convergent.py -- reach all 15,453 journals despite unstable pagination.

THE INSIGHT
-----------
Drift is slow, not chaotic. Measured (probe_form.py):

    page 50 @ t=0s   vs t=30s  -> 10/10 identical
    page 50 @ t=0s   vs t=60s  ->  9/10 identical

So any SINGLE pass captures most journals and misses a few. But the ones
it misses are RANDOM -- they depend on exactly when each page was fetched.
A second pass, run at a different moment, drifts differently and therefore
misses a DIFFERENT set.

Union the passes and the gaps fill in:

    pass 1  -> ~12,000 unique
    pass 2  -> ~12,000 unique, but a different ~12,000
    union   -> ~14,500
    pass 3  -> union ~15,200
    pass 4  -> union 15,453   <- converged

This is the coupon-collector problem, and it converges fast because the
miss rate per pass is only ~22%.

WHY THIS BEATS THE ALTERNATIVES
-------------------------------
  * POST filtering: tried, SINTA ignores the filter (returned 431 for a
    partition that should hold 268 -- it just served the normal listing).
  * Sort params: tried 8, all ignored. Sort is a POST form.
  * Page size: locked at 10.
  * ID crawling: works, but needs ~15k requests (~7 hours).

Convergent crawling needs ~3-5 passes x 1,546 pages = 5-8k requests,
and every pass is independently useful.

STOPPING RULE
-------------
Stop when unique == 15,453 (SINTA's published total), or when a pass adds
fewer than 10 new journals (diminishing returns -> the rest may not exist).

Usage:
    python scraper_convergent.py --passes 1     # one pass (~45 min)
    python scraper_convergent.py                # until converged
    python scraper_convergent.py --resume       # add passes to existing set
"""

import argparse
import json
import pathlib
import random
import time
from datetime import datetime, timezone

import requests

from parser import parse_page

BASE = "https://sinta.kemdiktisaintek.go.id/journals?page={}"

UA = ("SintaAcademicScraper/1.0 "
      "(Seleksi Asisten Lab Basis Data ITB 2026; "
      "mailto:18224081@std.stei.itb.ac.id)")
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
}

DELAY = 1.2
TIMEOUT = 30
MAX_RETRIES = 5           # DNS has been flaky -- retry harder
TARGET = 15453

ROOT = pathlib.Path(__file__).parent.parent
DATA = ROOT / "data"
STATE = DATA / "convergent_state.json"


def fetch(page: int, session: requests.Session) -> str | None:
    """Fetch one listing page. Returns None if it ultimately fails."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(BASE.format(page), headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            time.sleep(DELAY + random.uniform(0, 0.3))
            return r.text
        except requests.RequestException as e:
            if attempt == MAX_RETRIES:
                print(f"    page {page}: GAVE UP after {MAX_RETRIES} tries")
                return None
            wait = min(2 ** attempt, 30)
            # DNS failures are transient -- wait and retry rather than die.
            time.sleep(wait)
    return None


def load_state() -> dict:
    """Resume from whatever we already have."""
    if STATE.exists():
        raw = json.loads(STATE.read_text(encoding="utf-8"))
        return {int(k): v for k, v in raw.items()}
    return {}


def save_state(found: dict) -> None:
    DATA.mkdir(exist_ok=True)
    STATE.write_text(
        json.dumps({str(k): v for k, v in found.items()},
                   indent=2, ensure_ascii=False),
        encoding="utf-8")


def one_pass(session: requests.Session, found: dict, n: int) -> int:
    """One full sweep. Mutates `found`. Returns how many were NEW."""
    before = len(found)
    batch_ts = datetime.now(timezone.utc).isoformat()

    print(f"\n{'=' * 58}")
    print(f"PASS {n}   (starting from {before:,} known)")
    print(f"{'=' * 58}")

    page = 1
    failed = 0

    while True:
        html = fetch(page, session)
        if html is None:
            failed += 1
            page += 1
            if failed > 20:
                print("  too many failures -- aborting pass")
                break
            continue

        rows = parse_page(html)
        if not rows:
            break

        for r in rows:
            jid = r["journal_id"]
            if jid is None:
                continue
            r["scraped_at"] = batch_ts
            found[jid] = r        # last write wins; fine, fields are stable

        if page % 200 == 0:
            print(f"  page {page:>4}  known={len(found):>6,}")

        page += 1

    new = len(found) - before
    print(f"\n  pages fetched : {page - 1:,}  ({failed} failed)")
    print(f"  NEW journals  : {new:,}")
    print(f"  total known   : {len(found):,} / {TARGET:,}")
    print(f"  remaining     : {TARGET - len(found):,}")

    save_state(found)
    print(f"  (state saved -- safe to Ctrl+C)")

    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=10,
                    help="max passes (default: until converged)")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore saved state, start over")
    args = ap.parse_args()

    found = {} if args.fresh else load_state()
    if found:
        print(f"resuming with {len(found):,} journals already known")

    session = requests.Session()

    for n in range(1, args.passes + 1):
        if len(found) >= TARGET:
            print(f"\nCONVERGED -- {len(found):,} journals")
            break

        new = one_pass(session, found, n)

        if new < 10 and n > 1:
            print(f"\n  Only {new} new this pass -- diminishing returns.")
            print(f"  Stopping at {len(found):,} / {TARGET:,}.")
            break

    # -----------------------------------------------------------------
    print(f"\n{'=' * 58}")
    print("RESULT")
    print(f"{'=' * 58}")
    print(f"  unique journals : {len(found):,}")
    print(f"  SINTA reports   : {TARGET:,}")

    if len(found) == TARGET:
        print("\n  COMPLETE -- zero loss, zero duplicates")
    else:
        print(f"\n  {TARGET - len(found):,} still missing")
        print("  Run again to add another pass.")

    out = DATA / "convergent_raw.json"
    out.write_text(
        json.dumps(list(found.values()), indent=2, ensure_ascii=False),
        encoding="utf-8")
    print(f"\n  wrote {out}")


if __name__ == "__main__":
    main()