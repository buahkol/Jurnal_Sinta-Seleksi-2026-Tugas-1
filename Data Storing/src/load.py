"""
load.py -- load the scraped JSON into PostgreSQL.

IDEMPOTENCY IS THE WHOLE POINT.

The spec demands: "Pastikan tidak terdapat redundansi data pada DBMS."

So every insert here is an UPSERT:

  * affiliation / journal / subject  -> ON CONFLICT DO UPDATE (or DO NOTHING)
    Running twice does NOT create duplicate journals.

  * metric_snapshot                  -> ON CONFLICT (journal_id, captured_at)
                                        DO NOTHING
    Running twice with the SAME timestamp inserts nothing.
    Running LATER, after a fresh scrape, inserts NEW rows with a NEW
    timestamp -- which is exactly what the scheduling bonus needs.

That distinction is the reason metric_snapshot is a separate table rather
than columns on `journal`. Overwriting would destroy history; appending
preserves it.

Usage:
    python load.py
    python load.py --dsn "postgresql://postgres:pass@localhost/sinta_db"
"""

import argparse
import json
import pathlib
import sys

import psycopg2
import psycopg2.extras

ROOT = pathlib.Path(__file__).parent.parent
DATA = ROOT.parent / "Data Scraping" / "data"

DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/sinta_db"


def load_json(name: str) -> list:
    path = DATA / name
    if not path.exists():
        sys.exit(f"missing: {path}\nRun the scraper first.")
    return json.loads(path.read_text(encoding="utf-8"))


def main(dsn: str) -> None:
    journals = load_json("journals.json")
    affiliations = load_json("affiliations.json")
    subjects = load_json("subject_areas.json")
    journal_subject = load_json("journal_subject.json")
    snapshots = load_json("metric_snapshots_20260713.json")

    print(f"read {len(journals):>6} journals")
    print(f"     {len(affiliations):>6} affiliations")
    print(f"     {len(subjects):>6} subject areas")
    print(f"     {len(journal_subject):>6} journal-subject links")
    print(f"     {len(snapshots):>6} metric snapshots\n")

    conn = psycopg2.connect(dsn)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # ---------------------------------------------------------------
        # 1. affiliation
        # ---------------------------------------------------------------
        psycopg2.extras.execute_batch(cur, """
            INSERT INTO affiliation (affiliation_id, name, sinta_url)
            VALUES (%(affiliation_id)s, %(name)s, %(sinta_url)s)
            ON CONFLICT (affiliation_id) DO UPDATE
                SET name      = EXCLUDED.name,
                    sinta_url = EXCLUDED.sinta_url
        """, affiliations, page_size=500)
        print(f"affiliation      : {cur.rowcount if cur.rowcount > 0 else len(affiliations)} upserted")

        # ---------------------------------------------------------------
        # 2. subject_area
        #    We ignore the scraper's subject_id and let Postgres assign
        #    SERIAL ids, then map name -> id. Safer across batches.
        # ---------------------------------------------------------------
        psycopg2.extras.execute_batch(cur, """
            INSERT INTO subject_area (name)
            VALUES (%(name)s)
            ON CONFLICT (name) DO NOTHING
        """, subjects, page_size=500)

        cur.execute("SELECT subject_id, name FROM subject_area")
        subject_id_by_name = {name: sid for sid, name in cur.fetchall()}
        print(f"subject_area     : {len(subject_id_by_name)} total")

        # scraper's local subject_id -> canonical name
        name_by_local_id = {s["subject_id"]: s["name"] for s in subjects}

        # ---------------------------------------------------------------
        # 3. accreditation lookup (already seeded by schema.sql)
        # ---------------------------------------------------------------
        cur.execute("SELECT accreditation_id, label FROM accreditation")
        accred_id_by_label = {lab: aid for aid, lab in cur.fetchall()}

        # ---------------------------------------------------------------
        # 4. journal
        # ---------------------------------------------------------------
        rows = []
        unlabeled = 0
        for j in journals:
            label = j["accreditation_label"]

            if label is None:
                # SINTA shows no accreditation badge for this journal.
                # Load it with NULL rather than dropping it -- dropping
                # would silently break the 15,453 total and defeat the
                # whole point of the validation check.
                aid = None
                unlabeled += 1
            else:
                aid = accred_id_by_label.get(label)
                if aid is None:
                    # A label the schema does not know about. Do NOT coerce
                    # it to NULL silently -- that hides a parser bug.
                    print(f"  !! UNKNOWN accreditation {label!r} "
                          f"on journal {j['journal_id']} -- add it to the "
                          f"accreditation table")
                    aid = None

            rows.append({
                "journal_id":       j["journal_id"],
                "name":             j["name"],
                "p_issn":           j["p_issn"],
                "e_issn":           j["e_issn"],
                "affiliation_id":   j["affiliation_id"],
                "accreditation_id": aid,
                "sinta_url":        j["sinta_url"],
                "website":          j["website"],
                "google_scholar":   j["google_scholar"],
                "seen_at":          j["scraped_at"],
            })

        psycopg2.extras.execute_batch(cur, """
            INSERT INTO journal (
                journal_id, name, p_issn, e_issn,
                affiliation_id, accreditation_id,
                sinta_url, website, google_scholar,
                first_seen_at, last_seen_at
            ) VALUES (
                %(journal_id)s, %(name)s, %(p_issn)s, %(e_issn)s,
                %(affiliation_id)s, %(accreditation_id)s,
                %(sinta_url)s, %(website)s, %(google_scholar)s,
                %(seen_at)s, %(seen_at)s
            )
            ON CONFLICT (journal_id) DO UPDATE SET
                name             = EXCLUDED.name,
                p_issn           = EXCLUDED.p_issn,
                e_issn           = EXCLUDED.e_issn,
                affiliation_id   = EXCLUDED.affiliation_id,
                accreditation_id = EXCLUDED.accreditation_id,
                website          = EXCLUDED.website,
                google_scholar   = EXCLUDED.google_scholar,
                last_seen_at     = GREATEST(journal.last_seen_at,
                                            EXCLUDED.last_seen_at)
        """, rows, page_size=500)
        print(f"journal          : {len(rows)} upserted" +
              (f", {unlabeled} with NULL accreditation" if unlabeled else ""))

        # ---------------------------------------------------------------
        # 5. journal_subject (the M:N)
        # ---------------------------------------------------------------
        js_rows = []
        for link in journal_subject:
            name = name_by_local_id.get(link["subject_id"])
            sid = subject_id_by_name.get(name)
            if sid is None:
                continue
            js_rows.append({"journal_id": link["journal_id"], "subject_id": sid})

        psycopg2.extras.execute_batch(cur, """
            INSERT INTO journal_subject (journal_id, subject_id)
            VALUES (%(journal_id)s, %(subject_id)s)
            ON CONFLICT (journal_id, subject_id) DO NOTHING
        """, js_rows, page_size=1000)
        print(f"journal_subject  : {len(js_rows)} upserted")

        # ---------------------------------------------------------------
        # 6. journal_indexing (Scopus / Garuda) -- M:N
        # ---------------------------------------------------------------
        cur.execute("SELECT body_id, name FROM indexing_body")
        body_id = {name: bid for bid, name in cur.fetchall()}

        idx_path = DATA / "journal_indexing.json"
        if idx_path.exists():
            raw = json.loads(idx_path.read_text(encoding="utf-8"))
            idx_rows = [
                {"journal_id": r["journal_id"], "body_id": body_id[r["body"]]}
                for r in raw if r["body"] in body_id
            ]
        else:
            # fall back to the boolean flags on the journal record
            idx_rows = []
            for j in journals:
                if j["is_scopus"]:
                    idx_rows.append({"journal_id": j["journal_id"],
                                     "body_id": body_id["Scopus"]})
                if j["is_garuda"]:
                    idx_rows.append({"journal_id": j["journal_id"],
                                     "body_id": body_id["Garuda"]})

        psycopg2.extras.execute_batch(cur, """
            INSERT INTO journal_indexing (journal_id, body_id)
            VALUES (%(journal_id)s, %(body_id)s)
            ON CONFLICT (journal_id, body_id) DO NOTHING
        """, idx_rows, page_size=1000)
        print(f"journal_indexing : {len(idx_rows)} upserted")

        # ---------------------------------------------------------------
        # 7. metric_snapshot -- APPEND, never overwrite
        # ---------------------------------------------------------------
        psycopg2.extras.execute_batch(cur, """
            INSERT INTO metric_snapshot (
                journal_id, captured_at, impact,
                h5_index, citations, citations_5yr
            ) VALUES (
                %(journal_id)s, %(captured_at)s, %(impact)s,
                %(h5_index)s, %(citations)s, %(citations_5yr)s
            )
            ON CONFLICT (journal_id, captured_at) DO NOTHING
        """, snapshots, page_size=1000)
        print(f"metric_snapshot  : {len(snapshots)} upserted")

        conn.commit()
        print("\nCOMMITTED")

    except Exception as e:
        conn.rollback()
        print(f"\nROLLED BACK -- {type(e).__name__}: {e}")
        raise
    finally:
        cur.close()
        conn.close()


def verify(dsn: str) -> None:
    """Print the proof queries. Screenshot this output."""
    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    print("\n" + "=" * 62)
    print("VERIFICATION -- our DB vs SINTA's published figures")
    print("=" * 62)

    cur.execute("""
        SELECT a.label, COUNT(*) AS n
        FROM journal j
        JOIN accreditation a ON a.accreditation_id = j.accreditation_id
        GROUP BY a.label
        ORDER BY a.label
    """)
    expected = {"S1": 268, "S2": 1511, "S3": 2834,
                "S4": 5239, "S5": 5338, "S6": 262}

    print(f"{'rank':<18}{'ours':>8}{'SINTA':>8}   match")
    for label, n in cur.fetchall():
        exp = expected.get(label)
        mark = "" if exp is None else ("YES" if n == exp else "NO")
        print(f"{label:<18}{n:>8}{str(exp or '--'):>8}   {mark}")

    cur.execute("SELECT COUNT(*) FROM journal")
    print(f"\ntotal journals   : {cur.fetchone()[0]}  (SINTA reports 15453)")

    cur.execute("SELECT COUNT(*) FROM journal_subject")
    js = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM journal")
    jn = cur.fetchone()[0]
    print(f"journal_subject  : {js}  ({js/jn:.2f} subjects per journal on average)")
    print("                   ^ >1.0 proves the M:N is real, not decorative")

    cur.execute("SELECT COUNT(DISTINCT captured_at) FROM metric_snapshot")
    print(f"distinct batches : {cur.fetchone()[0]}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    args = ap.parse_args()

    main(args.dsn)
    verify(args.dsn)