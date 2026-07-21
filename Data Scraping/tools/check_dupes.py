"""
check_dupes.py -- is the 15,453 total actually 15,453 UNIQUE journals?

The subject-duplication bug proved that some journals were scraped more
than once (their subject lists were repeated Nx). That raises a harder
question the validation table could NOT catch:

    If journal X was scraped 3 times, and journal Y was MISSED entirely,
    the total is still 15,453 and every accreditation count still matches
    -- because X's 3 copies backfill Y's absence.

The counts matching is necessary but NOT sufficient. This script checks
uniqueness directly, from the CACHED html.

Run from Data Scraping/src/:
    python check_dupes.py
"""

import json
import pathlib
import re
from collections import Counter

from bs4 import BeautifulSoup

HERE = pathlib.Path(__file__).parent
CACHE = HERE.parent / "cache"
DATA = HERE.parent / "data"

# ---------------------------------------------------------------------
# Walk the cache and record which page each journal_id appeared on
# ---------------------------------------------------------------------
pages = sorted(CACHE.glob("page_*.html"))
print(f"scanning {len(pages)} cached pages...\n")

seen = {}          # journal_id -> [page numbers]
total_cards = 0

for p in pages:
    n = int(re.search(r"(\d+)", p.name).group(1))
    soup = BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser")
    for card in soup.select("div.list-item"):
        a = card.select_one("div.affil-name a")
        if not a or not a.has_attr("href"):
            continue
        m = re.search(r"/(\d+)/?$", a["href"])
        if not m:
            continue
        jid = int(m.group(1))
        seen.setdefault(jid, []).append(n)
        total_cards += 1

uniq = len(seen)
dupes = {j: pp for j, pp in seen.items() if len(pp) > 1}

print("=" * 64)
print("UNIQUENESS")
print("=" * 64)
print(f"  cards scraped   : {total_cards:,}")
print(f"  unique journals : {uniq:,}")
print(f"  duplicated      : {len(dupes):,}")
print(f"  extra copies    : {total_cards - uniq:,}")
print(f"\n  SINTA reports   : 15,453")

if uniq == 15453:
    print("\n  UNIQUE COUNT MATCHES SINTA. No journals were missed.")
elif uniq < 15453:
    print(f"\n  *** {15453 - uniq:,} JOURNALS MISSING ***")
    print("  Duplicates backfilled the total, masking the loss.")
    print("  The validation table was a FALSE POSITIVE.")
else:
    print(f"\n  *** {uniq - 15453:,} MORE than SINTA reports ***")

# ---------------------------------------------------------------------
# Show the worst offenders
# ---------------------------------------------------------------------
if dupes:
    print("\n" + "=" * 64)
    print("MOST-DUPLICATED JOURNALS")
    print("=" * 64)
    worst = sorted(dupes.items(), key=lambda kv: -len(kv[1]))[:8]
    for jid, pp in worst:
        print(f"  id={jid:<7} seen {len(pp)}x on pages {pp}")

    spread = Counter(len(pp) for pp in dupes.values())
    print("\n  copies -> how many journals")
    for k in sorted(spread):
        print(f"    {k}x : {spread[k]:>5}")

# ---------------------------------------------------------------------
# Cross-check against what the scraper actually WROTE
# ---------------------------------------------------------------------
journals = json.loads((DATA / "journals.json").read_text(encoding="utf-8"))
ids_in_json = [j["journal_id"] for j in journals]

print("\n" + "=" * 64)
print("journals.json")
print("=" * 64)
print(f"  rows            : {len(ids_in_json):,}")
print(f"  unique ids      : {len(set(ids_in_json)):,}")
if len(ids_in_json) != len(set(ids_in_json)):
    print(f"  *** {len(ids_in_json) - len(set(ids_in_json)):,} DUPLICATE ROWS ***")
    print("  (journal.journal_id is a PK, so Postgres would reject or")
    print("   upsert these -- but the JSON deliverable is still wrong)")

print("\n" + "=" * 64)
print("WHAT THIS MEANS")
print("=" * 64)
print("""
SINTA sorts by Impact. Over a 45-minute crawl the underlying order can
shift (metrics update; ties sort unstably), so a journal on page 800 in
minute 5 may sit on page 812 by minute 30 -- scraped twice, while its
neighbour slides off and is never seen.

This is the classic UNSTABLE PAGINATION problem, and it is worth a
paragraph in the README: it is exactly the kind of failure that a
naive scraper reports as a clean success.

FIX: crawl with a STABLE sort key. Append &sort=... on an immutable
field (e.g. journal id or name) rather than Impact, so page N always
contains the same journals regardless of when it is fetched.
""")