"""
debug_subjects.py -- find out why some journals appear to have 25 subjects
when only 10 exist.

Reads the CACHED html (no network hit) and prints the RAW div.profile-id
text for the worst offenders, so we can see exactly what the parser is
choking on.

Run from Data Scraping/src/:
    python debug_subjects.py
"""

import json
import pathlib
import re
from collections import Counter

from bs4 import BeautifulSoup

HERE = pathlib.Path(__file__).parent
DATA = HERE.parent / "data"
CACHE = HERE.parent / "cache"

links = json.loads((DATA / "journal_subject.json").read_text(encoding="utf-8"))
subjects = json.loads((DATA / "subject_areas.json").read_text(encoding="utf-8"))
journals = json.loads((DATA / "journals.json").read_text(encoding="utf-8"))

name_of = {s["subject_id"]: s["name"] for s in subjects}
jname = {j["journal_id"]: j["name"] for j in journals}

# ---------------------------------------------------------------------
# Which journals have absurdly many subjects?
# ---------------------------------------------------------------------
per_journal = Counter(l["journal_id"] for l in links)
worst = [(jid, n) for jid, n in per_journal.items() if n > 10]
worst.sort(key=lambda x: -x[1])

print("=" * 66)
print(f"Journals claiming >10 subjects (impossible -- only 10 exist)")
print("=" * 66)

for jid, n in worst[:5]:
    subs = [name_of[l["subject_id"]] for l in links if l["journal_id"] == jid]
    print(f"\njournal_id={jid}  n={n}")
    print(f"  name : {jname.get(jid, '?')[:56]}")
    print(f"  subs : {subs}")

    # Are they duplicates, or genuinely distinct?
    uniq = set(subs)
    print(f"  distinct: {len(uniq)}  -> {sorted(uniq)}")
    if len(uniq) < n:
        print(f"  *** {n - len(uniq)} DUPLICATE rows. The junction table's")
        print(f"      PRIMARY KEY (journal_id, subject_id) will collapse")
        print(f"      these to {len(uniq)} on insert -- so the DB is safe,")
        print(f"      but the JSON is wrong and the count is inflated.")

# ---------------------------------------------------------------------
# What does the RAW html actually say for the worst one?
# ---------------------------------------------------------------------
if worst:
    target = worst[0][0]
    print("\n" + "=" * 66)
    print(f"RAW HTML for journal_id={target}")
    print("=" * 66)

    found = False
    for page in sorted(CACHE.glob("page_*.html")):
        soup = BeautifulSoup(page.read_text(encoding="utf-8"), "html.parser")
        for card in soup.select("div.list-item"):
            a = card.select_one("div.affil-name a")
            if not a or not a.has_attr("href"):
                continue
            m = re.search(r"/(\d+)/?$", a["href"])
            if not m or int(m.group(1)) != target:
                continue

            found = True
            print(f"\nfound in {page.name}\n")

            pid = card.select_one("div.profile-id")
            raw = pid.get_text(" ", strip=True) if pid else "(no div.profile-id)"
            print("div.profile-id text:")
            print(f"  {raw!r}\n")

            m2 = re.search(r"Subject Area\s*:\s*(.+)$", raw)
            if m2:
                tail = m2.group(1)
                print("captured by regex 'Subject Area\\s*:\\s*(.+)$':")
                print(f"  {tail!r}\n")
                parts = [s.strip() for s in tail.split(",") if s.strip()]
                print(f"after .split(','):  {len(parts)} parts")
                for p in parts:
                    ok = p in name_of.values()
                    print(f"    {p!r:<30} {'valid' if ok else '<-- GARBAGE'}")
            break
        if found:
            break

    if not found:
        print(f"  journal {target} not found in cache")

print("\n" + "=" * 66)
print("DIAGNOSIS")
print("=" * 66)
print("If the parts above are all valid subject names but REPEATED,")
print("the card lists the same subject multiple times (SINTA renders")
print("one <a> per subject and some are duplicated).")
print()
print("Fix: dedupe with a set before writing journal_subject.json.")