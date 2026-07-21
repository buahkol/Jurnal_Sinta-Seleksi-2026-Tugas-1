"""
scrape_batch2.py -- crawl a SECOND snapshot for the scheduling bonus.

WHY A SEPARATE SCRIPT
---------------------
scraper_convergent.py resumes from convergent_state.json. Run it again and
it sees 15,448 journals already known and does nothing -- correct for
completeness, useless for scheduling.

The scheduling bonus needs a NEW snapshot: the same journals, re-scraped at
a LATER time, so their citation counts differ and the timestamps prove a
scheduled re-run happened. So this script:

  1. crawls fresh (ignores the old state)
  2. stamps everything with a NEW captured_at
  3. writes metric_snapshots_batch2.json
  4. that file is loaded with the SAME load.py -- which APPENDS to
     metric_snapshot (ON CONFLICT DO NOTHING on (journal_id, captured_at))
     rather than overwriting.

After loading, dim_time gains a second date and warehouse Q6 becomes a
real trend query -- no schema change.

Usage:
    python scrape_batch2.py --passes 3
"""

import argparse
import json
import pathlib
import random
import time
from datetime import datetime, timezone

import requests
import sys

# reuse the parser from Data Scraping/src
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "Data Scraping" / "src"))
try:
    from parser import parse_page
except ImportError:
    # fallback if run from a different layout
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
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
MAX_RETRIES = 5

ROOT = pathlib.Path(__file__).parent.parent
DATA = ROOT / "data"


def fetch(page, session):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(BASE.format(page), headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            time.sleep(DELAY + random.uniform(0, 0.3))
            return r.text
        except requests.RequestException:
            if attempt == MAX_RETRIES:
                return None
            time.sleep(min(2 ** attempt, 30))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=3,
                    help="convergent passes (3 pass sudah cukup)")
    args = ap.parse_args()

    batch_ts = datetime.now(timezone.utc).isoformat()
    print(f"BATCH 2 timestamp: {batch_ts}")
    print(f"(this must differ from batch 1 -- run at least hours later)\n")

    session = requests.Session()
    found = {}     # journal_id -> latest record this batch

    for n in range(1, args.passes + 1):
        before = len(found)
        page = 1
        print(f"pass {n}...")
        while True:
            html = fetch(page, session)
            if html is None:
                page += 1
                continue
            rows = parse_page(html)
            if not rows:
                break
            for r in rows:
                if r["journal_id"] is not None:
                    found[r["journal_id"]] = r
            if page % 300 == 0:
                print(f"  page {page:>4}  known={len(found):,}")
            page += 1
        new = len(found) - before
        print(f"  pass {n}: +{new} -> {len(found):,} total\n")

        # CHECKPOINT: save after every pass so a crash never loses the crawl.
        snaps_ckpt = [{
            "journal_id": jid,
            "captured_at": batch_ts,
            "impact": r["impact"],
            "h5_index": int(r["h5_index"]) if r["h5_index"] is not None else None,
            "citations": int(r["citations"]) if r["citations"] is not None else None,
            "citations_5yr": int(r["citations_5yr"]) if r["citations_5yr"] is not None else None,
        } for jid, r in found.items()]
        DATA.mkdir(parents=True, exist_ok=True)
        (DATA / "metric_snapshots_batch2.json").write_text(
            json.dumps(snaps_ckpt, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  (checkpoint saved: {len(snaps_ckpt):,} snapshots)\n")

        if new < 10 and n > 1:
            break

    # build metric snapshots ONLY -- journals/affiliations already exist
    snapshots = []
    for jid, r in found.items():
        snapshots.append({
            "journal_id": jid,
            "captured_at": batch_ts,
            "impact": r["impact"],
            "h5_index": int(r["h5_index"]) if r["h5_index"] is not None else None,
            "citations": int(r["citations"]) if r["citations"] is not None else None,
            "citations_5yr": int(r["citations_5yr"]) if r["citations_5yr"] is not None else None,
        })

    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / "metric_snapshots_batch2.json"
    out.write_text(json.dumps(snapshots, indent=2, ensure_ascii=False),
                   encoding="utf-8")

    print(f"{'=' * 54}")
    print(f"  journals in batch 2 : {len(found):,}")
    print(f"  snapshots written   : {len(snapshots):,}")
    print(f"  timestamp           : {batch_ts}")
    print(f"  wrote {out}")
    print(f"{'=' * 54}")
    print(f"\nNext: load ONLY these snapshots:")
    print(f"  python load_batch2.py --dsn \"postgresql://...\"")


if __name__ == "__main__":
    main()