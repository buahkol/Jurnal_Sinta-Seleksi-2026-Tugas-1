"""
seed_state.py -- bootstrap the convergent crawler from the cache you ALREADY have.

Your first crawl fetched 1,547 pages and captured 12,071 unique journals
before the drift problem was discovered. Those 12,071 are perfectly valid
-- the flaw was the MISSING 3,382, not the ones we got.

So there is no reason to re-fetch them. This script parses the existing
cache (no network) and writes convergent_state.json, so
scraper_convergent.py starts at 12,071/15,453 instead of 0.

That turns a 4-pass crawl into roughly a 1-2 pass crawl.

Run from Data Scraping/src/:
    python seed_state.py
"""

import json
import pathlib
from datetime import datetime, timezone

from parser import parse_page

ROOT = pathlib.Path(__file__).parent.parent
DATA = ROOT / "data"

# The original crawl's cache. Filenames may be page_00001.html (old scheme)
# or default_page_00001.html (after the sort-key change).
CACHE = ROOT / "cache"

found = {}
ts = datetime.now(timezone.utc).isoformat()

pages = sorted(CACHE.glob("*page_*.html"))
print(f"parsing {len(pages):,} cached pages (no network)...\n")

for i, p in enumerate(pages, 1):
    try:
        rows = parse_page(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  {p.name}: {e}")
        continue

    for r in rows:
        jid = r["journal_id"]
        if jid is None:
            continue
        r["scraped_at"] = ts
        found[jid] = r

    if i % 400 == 0:
        print(f"  {i:>5}/{len(pages):,}  unique={len(found):>6,}")

DATA.mkdir(exist_ok=True)
out = DATA / "convergent_state.json"
out.write_text(
    json.dumps({str(k): v for k, v in found.items()},
               indent=2, ensure_ascii=False),
    encoding="utf-8")

print(f"\n{'=' * 54}")
print(f"  unique journals : {len(found):,}")
print(f"  SINTA reports   : 15,453")
print(f"  still missing   : {15453 - len(found):,}")
print(f"{'=' * 54}")
print(f"\nwrote {out}")
print("\nNow run:  python scraper_convergent.py")
print("It will resume from here and only needs to find the gap.")