"""
probe_form.py -- find the REAL sort parameter by reading SINTA's own form.

probe_sort.py guessed 8 parameter names and SINTA ignored all of them.
Rather than guess a 9th, read the markup: the "Sort by" dropdown and the
"Filter" button are an HTML form, and the form tells us exactly which
parameter names the server accepts.

Also tests whether the page size can be increased. Fewer pages = shorter
crawl = smaller drift window, even if we cannot eliminate drift entirely.

Run from Data Scraping/src/:
    python probe_form.py
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


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def ids_on(html):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for card in soup.select("div.list-item"):
        a = card.select_one("div.affil-name a")
        if a and a.has_attr("href"):
            m = re.search(r"/(\d+)/?$", a["href"])
            if m:
                out.append(int(m.group(1)))
    return out


html = get(f"{BASE}?page=1")
soup = BeautifulSoup(html, "html.parser")

# ---------------------------------------------------------------------
print("=" * 68)
print("1. FORMS on the journals page")
print("=" * 68)

for i, form in enumerate(soup.find_all("form"), 1):
    print(f"\n  form #{i}")
    print(f"    action : {form.get('action')!r}")
    print(f"    method : {form.get('method', 'GET')!r}")

    for inp in form.find_all(["input", "select"]):
        tag = inp.name
        name = inp.get("name")
        if not name:
            continue
        if tag == "select":
            opts = [(o.get("value"), o.get_text(strip=True))
                    for o in inp.find_all("option")]
            print(f"    <select name={name!r}>")
            for val, txt in opts:
                print(f"        value={val!r:<16} text={txt!r}")
        else:
            print(f"    <input name={name!r} type={inp.get('type')!r} "
                  f"value={inp.get('value')!r}>")

if not soup.find_all("form"):
    print("  (no <form> found -- sort may be JS-driven)")

# ---------------------------------------------------------------------
print("\n" + "=" * 68)
print("2. PAGINATION LINKS -- what params do they carry?")
print("=" * 68)

nav = soup.select_one("nav")
if nav:
    for a in nav.find_all("a", href=True)[:6]:
        print(f"    {a.get_text(strip=True):<12} -> {a['href']}")
else:
    print("  (no <nav> found)")

# ---------------------------------------------------------------------
print("\n" + "=" * 68)
print("3. CAN WE GET MORE THAN 10 PER PAGE?")
print("=" * 68)
print("  Fewer pages = shorter crawl = less drift.\n")

for param in ["", "&per_page=100", "&limit=100", "&size=100",
              "&rows=100", "&show=100", "&length=100"]:
    try:
        n = len(ids_on(get(f"{BASE}?page=1{param}")))
        label = param or "(baseline)"
        flag = "  <-- WORKS" if n > 10 else ""
        print(f"    {label:<18} {n:>3} cards{flag}")
    except Exception as e:
        print(f"    {param:<18} ERROR {e}")
    time.sleep(1.5)

# ---------------------------------------------------------------------
print("\n" + "=" * 68)
print("4. HOW FAST DOES IT ACTUALLY DRIFT?")
print("=" * 68)
print("  Re-fetching page 50 at intervals to measure the drift rate.\n")

base_ids = ids_on(get(f"{BASE}?page=50"))
print(f"    t=0s    {base_ids}")

for wait in [30, 60]:
    time.sleep(wait)
    now = ids_on(get(f"{BASE}?page=50"))
    same = len(set(base_ids) & set(now))
    print(f"    t={wait:>3}s   {now}")
    print(f"            {same}/10 unchanged")

print("\n" + "=" * 68)
print("VERDICT")
print("=" * 68)
print("""
If section 1 reveals a real sort param -> use it.
If section 3 finds a working page-size param -> far fewer pages, far
   less drift (150 pages instead of 1546 = 4min crawl instead of 45min).
If neither works -> crawl by journal ID directly. IDs are immutable, so
   /journals/profile/<id> can never drift. That is the only fully
   reliable option.
""")