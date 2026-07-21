"""
inspect_data.py -- audit the scraped JSON for anomalies BEFORE loading.

Every issue found here is one that would otherwise surface as a constraint
violation mid-load, aborting the transaction. Better to see them now.

Run from Data Scraping/src/:
    python inspect_data.py
"""

import json
import pathlib
import re
from collections import Counter

DATA = pathlib.Path(__file__).parent.parent / "data"

journals = json.loads((DATA / "journals.json").read_text(encoding="utf-8"))
links = json.loads((DATA / "journal_subject.json").read_text(encoding="utf-8"))
subjects = json.loads((DATA / "subject_areas.json").read_text(encoding="utf-8"))

print(f"{len(journals):,} journals\n")

# ---------------------------------------------------------------------
# 1. Accreditation labels -- what IS that None?
# ---------------------------------------------------------------------
print("=" * 62)
print("1. ACCREDITATION LABELS")
print("=" * 62)
for lab, n in Counter(j["accreditation_label"] for j in journals).most_common():
    print(f"  {str(lab):<18} {n:>6}")

odd = [j for j in journals if j["accreditation_label"] is None]
if odd:
    print(f"\n  {len(odd)} journal(s) with NO accreditation label:")
    for j in odd[:5]:
        print(f"    id={j['journal_id']}  {j['name'][:52]}")
        print(f"      {j['sinta_url']}")
    print("\n  ^ Open that URL. Whatever badge it shows is a label the")
    print("    parser does not recognise. It must be added to the")
    print("    accreditation lookup table, or the FK insert will fail.")

# ---------------------------------------------------------------------
# 2. ISSN validity -- will these survive chk_p_issn?
# ---------------------------------------------------------------------
print("\n" + "=" * 62)
print("2. ISSN vs CHECK CONSTRAINT  ^[0-9]{7}[0-9X]$")
print("=" * 62)
pat = re.compile(r"^[0-9]{7}[0-9X]$")

for field in ("p_issn", "e_issn"):
    bad = [j for j in journals
           if j[field] is not None and not pat.match(str(j[field]))]
    nulls = sum(1 for j in journals if j[field] is None)
    print(f"  {field}: {nulls:>5} null, {len(bad):>5} INVALID")
    for j in bad[:6]:
        print(f"      id={j['journal_id']:<7} {field}={j[field]!r:<12} {j['name'][:34]}")
    if bad:
        print(f"      ^ these WILL be rejected by the CHECK constraint")

# ---------------------------------------------------------------------
# 3. Placeholder URLs
# ---------------------------------------------------------------------
print("\n" + "=" * 62)
print("3. PLACEHOLDER URLs")
print("=" * 62)
for field in ("website", "google_scholar"):
    junk = [j for j in journals
            if j[field] and not str(j[field]).startswith("http")]
    print(f"  {field}: {len(junk)} junk value(s)")
    for v, n in Counter(str(j[field]) for j in junk).most_common(3):
        print(f"      {v!r:<12} x{n}")

# ---------------------------------------------------------------------
# 4. Nullable FK
# ---------------------------------------------------------------------
print("\n" + "=" * 62)
print("4. AFFILIATION FK")
print("=" * 62)
no_aff = [j for j in journals if j["affiliation_id"] is None]
print(f"  {len(no_aff)} journal(s) with NULL affiliation_id")
print("  (FK is nullable -- these load fine, but worth noting in README)")
for j in no_aff[:3]:
    print(f"      id={j['journal_id']:<7} {j['name'][:44]}")

# ---------------------------------------------------------------------
# 5. The M:N -- prove it is real
# ---------------------------------------------------------------------
print("\n" + "=" * 62)
print("5. MANY-TO-MANY: journal <-> subject_area")
print("=" * 62)
per_journal = Counter(l["journal_id"] for l in links)
dist = Counter(per_journal.values())

print(f"  {len(links):,} links across {len(per_journal):,} journals")
print(f"  average {len(links)/len(per_journal):.2f} subjects per journal\n")
for k in sorted(dist):
    print(f"    {k} subject(s): {dist[k]:>6} journals")

no_subject = len(journals) - len(per_journal)
if no_subject:
    print(f"    0 subject(s): {no_subject:>6} journals  <-- no subject area at all")

print(f"\n  {len(subjects)} distinct subject areas:")
name_of = {s["subject_id"]: s["name"] for s in subjects}
for sid, n in Counter(l["subject_id"] for l in links).most_common():
    print(f"    {name_of[sid]:<26} {n:>6} journals")

print("\n" + "=" * 62)
print("If section 1 or 2 shows problems, fix parser.py and re-run")
print("scraper.py (reads from cache -- takes seconds) BEFORE loading.")
print("=" * 62)