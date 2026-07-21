"""
probe_sort.py -- find a STABLE sort key before re-crawling.

The Impact-sorted crawl lost 22% of journals to unstable pagination.
Before spending another 45 minutes, we must confirm which sort parameter
SINTA accepts AND that it produces a stable ordering.

Strategy:
  1. Try each candidate sort param on page 1. Which ones change the result?
  2. For the ones that work, fetch page 50 TWICE with a delay between.
     If the same journal IDs come back both times, the sort is stable.

Run from Data Scraping/src/:
    python probe_sort.py
"""

import re
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://sinta.kemdiktisaintek.go.id/journals"

UA = ("SintaAcademicScraper/1.0 "
      "(Seleksi Asisten Lab Basis Data ITB 2026; "
      "mailto:18224081@std.stei.itb.ac.id)")
HEADERS = {"User-Agent": UA}


def ids_on(url: str):
    """Return the journal IDs on one listing page."""
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for card in soup.select("div.list-item"):
        a = card.select_one("div.affil-name a")
        if a and a.has_attr("href"):
            m = re.search(r"/(\d+)/?$", a["href"])
            if m:
                out.append(int(m.group(1)))
    return out


# The dropdown on SINTA's page reads "Sort by: Impact". These are the
# plausible parameter names/values. We do not know which SINTA honours,
# so we test rather than assume.
CANDIDATES = [
    ("baseline (no sort param)", ""),
    ("sort=name",               "&sort=name"),
    ("sort=title",              "&sort=title"),
    ("sort=id",                 "&sort=id"),
    ("sort=issn",               "&sort=issn"),
    ("sort=accreditation",      "&sort=accreditation"),
    ("sort=h5",                 "&sort=h5"),
    ("sort=citation",           "&sort=citation"),
    ("order=asc",               "&order=asc"),
]

print("=" * 68)
print("STEP 1 -- which sort params does SINTA actually honour?")
print("=" * 68)
print("Comparing page 1 under each candidate against the baseline.\n")

baseline = ids_on(f"{BASE}?page=1")
print(f"  baseline page 1: {baseline}\n")
time.sleep(2)

working = []
for label, param in CANDIDATES[1:]:
    url = f"{BASE}?page=1{param}"
    try:
        got = ids_on(url)
    except Exception as e:
        print(f"  {label:<26} ERROR {e}")
        continue

    if not got:
        print(f"  {label:<26} 0 cards -- param breaks the page")
    elif got == baseline:
        print(f"  {label:<26} IGNORED (identical to baseline)")
    else:
        print(f"  {label:<26} CHANGES ORDER  <-- honoured")
        print(f"  {'':<26} {got[:5]}...")
        working.append((label, param))
    time.sleep(2)

# ---------------------------------------------------------------------
print("\n" + "=" * 68)
print("STEP 2 -- is it STABLE? fetch page 50 twice, 20s apart")
print("=" * 68)

to_test = working if working else [("baseline (no sort param)", "")]

for label, param in to_test:
    url = f"{BASE}?page=50{param}"
    print(f"\n  {label}")

    first = ids_on(url)
    print(f"    t=0s   {first}")

    time.sleep(20)

    second = ids_on(url)
    print(f"    t=20s  {second}")

    if first == second:
        print(f"    STABLE -- same 10 journals, same order")
    else:
        overlap = len(set(first) & set(second))
        print(f"    UNSTABLE -- only {overlap}/10 journals in common")
        print(f"    Re-crawling with this sort would lose data again.")

print("\n" + "=" * 68)
print("READ THE RESULTS")
print("=" * 68)
print("""
If a sort param came back STABLE, use it for the re-crawl.

If NOTHING is stable, the listing itself cannot be crawled reliably.
Fallback: crawl by journal PROFILE ID instead of by page. The IDs live
at /journals/profile/<id>, so we can iterate ids directly and never
depend on pagination at all. Slower, but exact.
""")