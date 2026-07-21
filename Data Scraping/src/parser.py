"""
parser.py — extract one journal from a SINTA listing card.

Selectors here are taken from SINTA's ACTUAL markup (verified via DevTools),
not guessed. The card structure is:

    div.list-item.row
      div.profile-side.journal-profile     <- cover image
      div.meta-side
        div.affil-name    > a              <- journal name + profile URL
        div.affil-abbrev  > a, a, a        <- Google Scholar / Website / Editor
        div.affil-loc     > a              <- affiliation + affiliation URL
        div.profile-id                     <- "P-ISSN : x | E-ISSN : y  Subject Area : A, B"
        div.stat-prev                      <- accreditation + indexing badges
          span.num-stat.accredited
          span.num-stat.scopus-indexed
          span.num-stat.garuda-indexed
        div.stat-profile
          div.pr-num / div.pr-txt          <- value/label PAIRS (4 metrics)

Two traps this file handles, both of which silently corrupt data:

  1. LOCALE NUMBERS. "14.902" is 14902, not 14.9. Period = thousands sep,
     comma = decimal sep. float() does NOT raise on "14.902" — it returns
     14.902 and your fact table is wrong by 1000x with no error.

  2. THE ID IS IN THE URL. There is no visible journal ID; it lives in
     /journals/profile/671. Same for affiliation: /affiliations/profile/9.
     These are your PRIMARY KEYS and FOREIGN KEYS. Without them you cannot
     dedupe across scrape batches, and the whole scheduling bonus collapses.
"""

import re
from typing import Optional

from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# Preprocessing helpers
# --------------------------------------------------------------------------


def parse_id_number(raw: Optional[str]) -> Optional[float]:
    """
    Indonesian locale number -> float.

    >>> parse_id_number("104,00")
    104.0
    >>> parse_id_number("14.902")
    14902.0
    >>> parse_id_number("62")
    62.0
    >>> parse_id_number("1.234,56")
    1234.56
    >>> parse_id_number("-") is None
    True
    """
    if raw is None:
        return None
    s = re.sub(r"[^\d.,\-]", "", str(raw).strip())
    if not s or s == "-":
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")   # comma is the decimal mark
    else:
        s = s.replace(".", "")                     # periods are thousands seps
    try:
        return float(s)
    except ValueError:
        return None


def id_from_url(url: Optional[str]) -> Optional[int]:
    """
    Pull the trailing numeric ID out of a SINTA profile URL.

    >>> id_from_url("https://sinta.kemdiktisaintek.go.id/journals/profile/671")
    671
    >>> id_from_url("https://sinta.kemdiktisaintek.go.id/affiliations/profile/9")
    9
    >>> id_from_url(None) is None
    True
    """
    if not url:
        return None
    m = re.search(r"/(\d+)/?$", url)
    return int(m.group(1)) if m else None


def clean_issn(raw: Optional[str]) -> Optional[str]:
    """
    Normalise an ISSN, rejecting SINTA's placeholder junk.

    A valid ISSN is 8 characters: 7 digits + a check character that may be
    X. SINTA stores "0" (and sometimes "-") when a journal simply has no
    print ISSN, which is a sentinel, not a value. Passing it through would
    violate the DB CHECK constraint and abort the whole load.

    >>> clean_issn("23391286")
    '23391286'
    >>> clean_issn("2615174X")
    '2615174X'
    >>> clean_issn("0") is None
    True
    >>> clean_issn("-") is None
    True
    >>> clean_issn("") is None
    True
    >>> clean_issn(None) is None
    True
    """
    if raw is None:
        return None
    s = str(raw).strip().upper().replace("-", "")
    if not s or s == "0":
        return None
    return s if re.fullmatch(r"[0-9]{7}[0-9X]", s) else None


def clean_url(raw: Optional[str]) -> Optional[str]:
    """
    Reject placeholder hrefs.

    SINTA renders a dead link as href="#!" when a journal has no Google
    Scholar profile. That is not a URL; storing it would pollute the column
    with a value that looks real but resolves to nothing.

    >>> clean_url("https://example.com")
    'https://example.com'
    >>> clean_url("#!") is None
    True
    >>> clean_url("#") is None
    True
    >>> clean_url(None) is None
    True
    """
    if not raw:
        return None
    s = str(raw).strip()
    if s.startswith("#"):
        return None
    return s if s.startswith(("http://", "https://")) else None


def _text(node) -> Optional[str]:
    return node.get_text(" ", strip=True) if node else None


# --------------------------------------------------------------------------
# The parser
# --------------------------------------------------------------------------

ACCRED_RANK = {
    "S1": 1, "S2": 2, "S3": 3, "S4": 4, "S5": 5, "S6": 6,
}


def parse_card(card) -> dict:
    """Turn one div.list-item into a flat dict."""

    # --- name + journal_id (the PK, hidden in the href) ---
    name_a = card.select_one("div.affil-name a")
    profile_url = name_a["href"] if name_a and name_a.has_attr("href") else None
    journal_id = id_from_url(profile_url)

    # .get_text() also grabs the <i> checkmark icon; it has no text, so
    # strip=True is enough. But collapse internal whitespace runs.
    journal_name = re.sub(r"\s+", " ", _text(name_a) or "").strip()

    # --- affiliation + affiliation_id (the FK) ---
    affil_a = card.select_one("div.affil-loc a")
    affil_url = affil_a["href"] if affil_a and affil_a.has_attr("href") else None
    affiliation_id = id_from_url(affil_url)
    affiliation_name = _text(affil_a)

    # --- external links ---
    links = {}
    for a in card.select("div.affil-abbrev a"):
        label = _text(a)
        if not label:
            continue
        key = label.strip().lower().replace(" ", "_")   # google_scholar / website / editor_url
        links[key] = clean_url(a.get("href"))           # "#!" -> None

    # --- ISSN + subject areas (div.profile-id) ---
    meta = _text(card.select_one("div.profile-id")) or ""

    p_issn = e_issn = None
    subjects = []

    m = re.search(r"P-ISSN\s*:\s*([\w\-]+)", meta)
    if m:
        p_issn = clean_issn(m.group(1))     # "0" -> None

    m = re.search(r"E-ISSN\s*:\s*([\w\-]+)", meta)
    if m:
        e_issn = clean_issn(m.group(1))     # "0" -> None

    m = re.search(r"Subject Area\s*:\s*(.+)$", meta)
    if m:
        # Dedupe. A journal cannot hold the same subject area twice, but
        # SINTA's markup sometimes repeats one. Without this, a journal can
        # appear to carry 25 subjects when only 10 exist in total -- and the
        # junction table's PK would silently collapse them on insert, leaving
        # the DB correct but the JSON deliverable wrong.
        #
        # dict.fromkeys preserves source order, unlike set().
        raw = [s.strip() for s in m.group(1).split(",") if s.strip()]
        subjects = list(dict.fromkeys(raw))

    # --- accreditation + indexing (div.stat-prev) ---
    # Class names are the reliable signal here, NOT the text.
    accred_label = None
    accred_rank = None

    accred_el = card.select_one("span.num-stat.accredited")
    if accred_el:
        txt = _text(accred_el) or ""
        m = re.search(r"\b(S[1-6])\b", txt)
        if m:
            accred_label = m.group(1)
            accred_rank = ACCRED_RANK[accred_label]
        elif "Cancel" in txt:
            accred_label = "Cancelled"
        elif "Not Accredited" in txt:
            accred_label = "Not Accredited"

    is_scopus = card.select_one("span.num-stat.scopus-indexed") is not None
    is_garuda = card.select_one("span.num-stat.garuda-indexed") is not None

    garuda_a = card.select_one("a[href*='garuda']")
    garuda_url = garuda_a["href"] if garuda_a else None

    # --- metrics (div.stat-profile) ---
    # pr-num and pr-txt are SIBLINGS in parallel columns, not nested.
    # Zip them positionally: 4 values, 4 labels, same order.
    nums = [_text(d) for d in card.select("div.stat-profile div.pr-num")]
    labs = [_text(d) for d in card.select("div.stat-profile div.pr-txt")]

    metrics = {}
    for lab, num in zip(labs, nums):
        if not lab:
            continue
        key = lab.strip().lower().replace("-", "_").replace(" ", "_")
        metrics[key] = parse_id_number(num)

    return {
        "journal_id": journal_id,
        "journal_name": journal_name,
        "profile_url": profile_url,
        "p_issn": p_issn,
        "e_issn": e_issn,
        "affiliation_id": affiliation_id,
        "affiliation_name": affiliation_name,
        "affiliation_url": affil_url,
        "subject_areas": subjects,
        "accreditation_label": accred_label,
        "accreditation_rank": accred_rank,
        "is_scopus": is_scopus,
        "is_garuda": is_garuda,
        "garuda_url": garuda_url,
        "links": links,
        "impact": metrics.get("impact"),
        "h5_index": metrics.get("h5_index"),
        "citations": metrics.get("citations"),
        "citations_5yr": metrics.get("citations_5yr"),
    }


def parse_page(html: str) -> list:
    """Parse every journal card on one listing page."""
    soup = BeautifulSoup(html, "html.parser")
    return [parse_card(c) for c in soup.select("div.list-item")]


if __name__ == "__main__":
    import doctest
    import json
    import pathlib

    r = doctest.testmod(verbose=False)
    print(f"doctests: {r.attempted} run, {r.failed} failed\n")

    fixture = pathlib.Path(__file__).parent.parent / "tests" / "fixture_card.html"
    records = parse_page(fixture.read_text())

    print(f"cards parsed: {len(records)}\n")
    print(json.dumps(records[0], indent=2, ensure_ascii=False))