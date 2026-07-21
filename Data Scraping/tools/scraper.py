"""
scraper.py — crawl all SINTA journal listing pages.

Design notes (worth putting in your README):

  * POLITE BY DEFAULT. 1.5s delay between requests, honest User-Agent that
    identifies who I am and why. SINTA has no robots.txt (404), so nothing
    forbids this crawl -- but "not forbidden" is not "go as fast as you like".

  * CACHED. Every page is written to cache/ before parsing. Re-running during
    development reads from disk and does NOT re-hit their server. This is the
    single most important courtesy: you will run this many times while
    debugging, and without a cache you'd hammer a government server for hours.

  * RESUMABLE. If it dies at page 900, re-running skips the 899 cached pages.

  * SNAPSHOTTED. Every record carries scraped_at. This is what makes the
    scheduling bonus real: batch 1 and batch 2 have different timestamps and
    genuinely different citation counts.

Usage:
    python scraper.py --pages 3          # smoke test on 3 pages
    python scraper.py                    # full crawl (1546 pages, ~40 min)
    python scraper.py --no-cache         # force re-fetch
"""

import argparse
import json
import pathlib
import random
import sys
import time
from datetime import datetime, timezone

import requests

from parser import parse_page

BASE = "https://sinta.kemdiktisaintek.go.id"
LISTING = BASE + "/journals?page={}"

# Identify yourself. Do not pretend to be Chrome.
UA = (
    "SintaAcademicScraper/1.0 "
    "(Seleksi Asisten Lab Basis Data ITB 2026; "
    "mailto:18224081@std.stei.itb.ac.id)"
)

HEADERS = {"User-Agent": UA}

DELAY = 1.5          # seconds between live requests
TIMEOUT = 30
MAX_RETRIES = 3

ROOT = pathlib.Path(__file__).parent.parent
CACHE = ROOT / "cache"
DATA = ROOT / "data"


def fetch_page(page: int, use_cache: bool = True) -> str:
    """Fetch one listing page, preferring the local cache."""
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / f"page_{page:05d}.html"

    if use_cache and cached.exists():
        return cached.read_text(encoding="utf-8")

    url = LISTING.format(page)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            cached.write_text(r.text, encoding="utf-8")

            # Jitter the delay slightly -- a perfectly regular 1.5s pulse is
            # itself a bot signature, and jitter is gentler on their server.
            time.sleep(DELAY + random.uniform(0, 0.5))
            return r.text

        except requests.RequestException as e:
            wait = 2 ** attempt
            print(f"    page {page} attempt {attempt}/{MAX_RETRIES} failed: {e}")
            if attempt == MAX_RETRIES:
                raise
            print(f"    backing off {wait}s")
            time.sleep(wait)


def scrape(max_pages: int | None = None, use_cache: bool = True) -> list:
    """Crawl listing pages until exhausted."""
    DATA.mkdir(exist_ok=True)

    batch_ts = datetime.now(timezone.utc).isoformat()
    print(f"batch timestamp: {batch_ts}")
    print(f"cache: {'ON' if use_cache else 'OFF'}\n")

    records = []
    page = 1

    while True:
        if max_pages and page > max_pages:
            break

        html = fetch_page(page, use_cache)
        rows = parse_page(html)

        if not rows:
            print(f"page {page}: 0 cards -- end of listing")
            break

        for r in rows:
            r["scraped_at"] = batch_ts
        records.extend(rows)

        if page % 25 == 0 or page <= 3:
            print(f"page {page:>5}  cards={len(rows):>2}  total={len(records):>6}")

        page += 1

    print(f"\ndone: {len(records)} journals across {page - 1} pages")
    return records


def split_and_save(records: list) -> None:
    """
    The spec is explicit:

      "File JSON sebaiknya dipisahkan berdasarkan jenis data yang diambil,
       seperti movies.json, actors.json, review.json ... jangan digabungkan
       dalam satu file besar."

    So we normalise into one file per ENTITY, mirroring the ERD. This is not
    cosmetic -- it forces you to actually resolve the M:N before you ever
    touch SQL, and the junction file makes the relationship undeniable.
    """
    DATA.mkdir(exist_ok=True)

    journals = []
    affiliations = {}
    subjects = {}
    journal_subject = set()      # set, not list -- (journal_id, subject_id) is unique
    metrics = []
    seen_journals = set()        # guard against the same journal on two pages

    next_subject_id = 1

    for r in records:
        jid = r["journal_id"]
        if jid is None or jid in seen_journals:
            continue
        seen_journals.add(jid)

        # --- affiliation (dedupe by id) ---
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

        # --- subject areas + the M:N junction ---
        for name in r["subject_areas"]:
            if name not in subjects:
                subjects[name] = {"subject_id": next_subject_id, "name": name}
                next_subject_id += 1
            journal_subject.add((jid, subjects[name]["subject_id"]))

        # --- metric snapshot (the time-series row) ---
        metrics.append({
            "journal_id": jid,
            "captured_at": r["scraped_at"],
            "impact": r["impact"],
            "h5_index": int(r["h5_index"]) if r["h5_index"] is not None else None,
            "citations": int(r["citations"]) if r["citations"] is not None else None,
            "citations_5yr": int(r["citations_5yr"]) if r["citations_5yr"] is not None else None,
        })

    out = {
        "journals.json": journals,
        "affiliations.json": list(affiliations.values()),
        "subject_areas.json": list(subjects.values()),
        "journal_subject.json": [
            {"journal_id": j, "subject_id": s}
            for j, s in sorted(journal_subject)
        ],
        "metric_snapshots.json": metrics,
    }

    print()
    for fname, rows in out.items():
        path = DATA / fname
        path.write_text(
            json.dumps(rows, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  {fname:<26} {len(rows):>6} rows")


def validate(records: list) -> None:
    """
    Cross-check against the aggregate stats SINTA publishes on its own
    journals page. If these match, your ETL provably lost nothing.

    Screenshot this output for your README -- most candidates have no way
    to demonstrate their pipeline is correct. You do.
    """
    print("\n" + "=" * 58)
    print("VALIDATION -- our counts vs SINTA's published figures")
    print("=" * 58)

    expected = {
        "S1": 268, "S2": 1511, "S3": 2834,
        "S4": 5239, "S5": 5338, "S6": 262,
    }

    got = {}
    for r in records:
        lab = r["accreditation_label"]
        got[lab] = got.get(lab, 0) + 1

    print(f"{'rank':<18}{'ours':>8}{'SINTA':>8}   match")
    all_ok = True
    for lab in ["S1", "S2", "S3", "S4", "S5", "S6"]:
        ours = got.get(lab, 0)
        exp = expected[lab]
        ok = ours == exp
        all_ok &= ok
        print(f"{lab:<18}{ours:>8}{exp:>8}   {'YES' if ok else 'NO'}")

    for lab, n in sorted(got.items(), key=lambda kv: (kv[0] is None, str(kv[0]))):
        if lab not in expected:
            shown = "NULL" if lab is None else str(lab)
            print(f"{shown:<18}{n:>8}{'--':>8}   <-- not in SINTA's chart")

    print(f"\ntotal journals: {len(records)}   SINTA reports: 15453")
    print(f"\nALL COUNTS MATCH: {'YES' if all_ok else 'NO -- investigate'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=None,
                    help="limit pages (omit for full crawl)")
    ap.add_argument("--no-cache", action="store_true")
    args = ap.parse_args()

    recs = scrape(max_pages=args.pages, use_cache=not args.no_cache)
    split_and_save(recs)

    if args.pages is None:
        validate(recs)
    else:
        print("\n(skipping validation -- partial crawl)")