"""
split_convergent.py -- turn convergent_raw.json into the per-entity JSONs.

The spec is explicit:

    "File JSON sebaiknya dipisahkan berdasarkan jenis data yang diambil,
     seperti movies.json, actors.json, review.json, dan sebagainya,
     jangan digabungkan dalam satu file besar."

convergent_raw.json is one big flat dump. This normalises it into one file
per ENTITY, mirroring the ERD -- which also forces the M:N to be resolved
before any SQL is written.

Run from Data Scraping/src/:
    python split_convergent.py
"""

import json
import pathlib
from collections import Counter

DATA = pathlib.Path(__file__).parent.parent / "data"

records = json.loads((DATA / "convergent_raw.json").read_text(encoding="utf-8"))
print(f"read {len(records):,} records\n")

# ---------------------------------------------------------------------
journals = []
affiliations = {}
subjects = {}
journal_subject = set()      # set -> the PK (journal_id, subject_id) is unique
journal_indexing = set()
metrics = []
seen = set()

next_sid = 1

for r in records:
    jid = r["journal_id"]
    if jid is None or jid in seen:
        continue
    seen.add(jid)

    # --- affiliation ---
    aid = r["affiliation_id"]
    if aid is not None and aid not in affiliations:
        affiliations[aid] = {
            "affiliation_id": aid,
            "name": r["affiliation_name"],
            "sinta_url": r["affiliation_url"],
        }

    # --- journal ---
    journals.append({
        "journal_id": jid,
        "name": r["journal_name"],
        "p_issn": r["p_issn"],
        "e_issn": r["e_issn"],
        "affiliation_id": aid,
        "accreditation_label": r["accreditation_label"],
        "accreditation_rank": r["accreditation_rank"],
        "is_scopus": r["is_scopus"],
        "is_garuda": r["is_garuda"],
        "sinta_url": r["profile_url"],
        "website": r["links"].get("website"),
        "google_scholar": r["links"].get("google_scholar"),
        "scraped_at": r["scraped_at"],
    })

    # --- subject areas + M:N ---
    for name in r["subject_areas"]:
        if name not in subjects:
            subjects[name] = {"subject_id": next_sid, "name": name}
            next_sid += 1
        journal_subject.add((jid, subjects[name]["subject_id"]))

    # --- indexing bodies (M:N) ---
    if r["is_scopus"]:
        journal_indexing.add((jid, "Scopus"))
    if r["is_garuda"]:
        journal_indexing.add((jid, "Garuda"))

    # --- metric snapshot (the time-series row) ---
    metrics.append({
        "journal_id": jid,
        "captured_at": r["scraped_at"],
        "impact": r["impact"],
        "h5_index": int(r["h5_index"]) if r["h5_index"] is not None else None,
        "citations": int(r["citations"]) if r["citations"] is not None else None,
        "citations_5yr": int(r["citations_5yr"]) if r["citations_5yr"] is not None else None,
    })

# ---------------------------------------------------------------------
out = {
    "journals.json": journals,
    "affiliations.json": list(affiliations.values()),
    "subject_areas.json": list(subjects.values()),
    "journal_subject.json": [
        {"journal_id": j, "subject_id": s} for j, s in sorted(journal_subject)
    ],
    "journal_indexing.json": [
        {"journal_id": j, "body": b} for j, b in sorted(journal_indexing)
    ],
    "metric_snapshots.json": metrics,
}

for fname, rows in out.items():
    (DATA / fname).write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  {fname:<26} {len(rows):>7,} rows")

# ---------------------------------------------------------------------
print("\n" + "=" * 60)
print("VALIDATION")
print("=" * 60)

expected = {"S1": 268, "S2": 1511, "S3": 2834,
            "S4": 5239, "S5": 5338, "S6": 262}
got = Counter(j["accreditation_label"] for j in journals)

print(f"  {'rank':<10}{'ours':>8}{'SINTA':>8}   diff")
total_exp = 0
for lab in ["S1", "S2", "S3", "S4", "S5", "S6"]:
    ours, exp = got.get(lab, 0), expected[lab]
    total_exp += exp
    d = ours - exp
    mark = "OK" if d == 0 else f"{d:+d}"
    print(f"  {lab:<10}{ours:>8}{exp:>8}   {mark}")

for lab, n in got.items():
    if lab not in expected:
        print(f"  {'NULL' if lab is None else lab:<10}{n:>8}{'--':>8}")

print(f"\n  unique journals : {len(journals):,}")
print(f"  SINTA reports   : 15,453")
print(f"  coverage        : {len(journals) / 15453:.2%}")

ids = [j["journal_id"] for j in journals]
print(f"\n  duplicate ids   : {len(ids) - len(set(ids))}")
if len(ids) == len(set(ids)):
    print("  NO DUPLICATES")

# M:N proof
per = Counter(l["journal_id"] for l in out["journal_subject.json"])
if per:
    over = [j for j, n in per.items() if n > 10]
    print(f"\n  M:N -- {len(out['journal_subject.json']):,} links "
          f"across {len(per):,} journals")
    print(f"        avg {len(out['journal_subject.json'])/len(per):.2f} subjects/journal")
    print(f"        max {max(per.values())} subjects on one journal")
    print(f"        journals with >10 subjects: {len(over)}  "
          f"{'(BAD -- only 10 exist)' if over else '(good)'}")
    print(f"        journals with 0 subjects : {len(journals) - len(per):,}")

print("\n" + "=" * 60)
print("Next: load into PostgreSQL")
print("  psql -U postgres -d sinta_db -f ../../Data Storing/src/schema.sql")
print("  cd '../../Data Storing/src' && python load.py --dsn ...")
print("=" * 60)