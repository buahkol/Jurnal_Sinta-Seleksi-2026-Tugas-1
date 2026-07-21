"""
warehouse_load.py -- populate the star schema from the OLTP database.

This is the "load" that turns the normalised operational tables into a
denormalised analytical model. It reads sinta_db and writes sinta_dw.

Design notes worth putting in the README:

  * Facts NEVER carry a NULL dimension key. Journals with no affiliation
    are mapped to the surrogate "Unknown" member (key -1), so every fact
    row joins cleanly. This is standard Kimball practice.

  * impact is SEMI-ADDITIVE: it is an average, so it must be AVG'd across
    journals, never SUM'd. The measure is stored, but the aggregation
    rule is a query-time responsibility -- noted in the analytic queries.

  * Re-running is idempotent: dimensions upsert, and the fact is keyed by
    (journal, time), so loading the same batch twice changes nothing. A
    NEW scrape (new captured_at) adds new fact rows -- that is how the
    scheduling bonus produces trend data.

Usage:
    python warehouse_load.py \
        --src "postgresql://postgres:pw@localhost/sinta_db" \
        --dw  "postgresql://postgres:pw@localhost/sinta_dw"
"""

import argparse

import psycopg2
import psycopg2.extras


def main(src_dsn: str, dw_dsn: str) -> None:
    src = psycopg2.connect(src_dsn)
    dw = psycopg2.connect(dw_dsn)
    dw.autocommit = False
    s = src.cursor()
    d = dw.cursor()

    try:
        # -------------------------------------------------------------
        # dim_time -- one row per distinct snapshot timestamp
        # -------------------------------------------------------------
        s.execute("SELECT DISTINCT captured_at FROM metric_snapshot ORDER BY captured_at")
        times = [r[0] for r in s.fetchall()]
        for i, ts in enumerate(times, 1):
            d.execute("""
                INSERT INTO dim_time (captured_at, batch_date, batch_year,
                                      batch_month, batch_label)
                VALUES (%s, %s::date, EXTRACT(YEAR FROM %s)::int,
                        EXTRACT(MONTH FROM %s)::int, %s)
                ON CONFLICT (captured_at) DO NOTHING
            """, (ts, ts, ts, ts, f"batch {i}"))
        print(f"dim_time          : {len(times)} snapshots")

        # -------------------------------------------------------------
        # dim_journal
        # -------------------------------------------------------------
        s.execute("SELECT journal_id, name, p_issn, e_issn FROM journal")
        jrows = s.fetchall()
        psycopg2.extras.execute_batch(d, """
            INSERT INTO dim_journal (source_journal_id, name, p_issn, e_issn)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (source_journal_id) DO UPDATE
                SET name = EXCLUDED.name
        """, jrows, page_size=1000)
        print(f"dim_journal       : {len(jrows)}")

        # -------------------------------------------------------------
        # dim_affiliation (Unknown = -1 already seeded by schema)
        # -------------------------------------------------------------
        s.execute("SELECT affiliation_id, name FROM affiliation")
        arows = s.fetchall()
        psycopg2.extras.execute_batch(d, """
            INSERT INTO dim_affiliation (source_affiliation_id, name)
            VALUES (%s, %s)
            ON CONFLICT (source_affiliation_id) DO NOTHING
        """, arows, page_size=1000)
        print(f"dim_affiliation   : {len(arows)} (+ Unknown)")

        # -------------------------------------------------------------
        # dim_subject + bridge
        # -------------------------------------------------------------
        s.execute("SELECT name FROM subject_area")
        for (name,) in s.fetchall():
            d.execute("INSERT INTO dim_subject (name) VALUES (%s) "
                      "ON CONFLICT (name) DO NOTHING", (name,))

        # build key lookups
        d.execute("SELECT source_journal_id, journal_key FROM dim_journal")
        jkey = dict(d.fetchall())
        d.execute("SELECT name, subject_key FROM dim_subject")
        skey = dict(d.fetchall())

        s.execute("""
            SELECT js.journal_id, sa.name
            FROM journal_subject js
            JOIN subject_area sa ON sa.subject_id = js.subject_id
        """)
        bridge = [(jkey[jid], skey[sn]) for jid, sn in s.fetchall()
                  if jid in jkey and sn in skey]
        psycopg2.extras.execute_batch(d, """
            INSERT INTO bridge_journal_subject (journal_key, subject_key)
            VALUES (%s, %s) ON CONFLICT DO NOTHING
        """, bridge, page_size=1000)
        print(f"bridge_subject    : {len(bridge)}")

        # -------------------------------------------------------------
        # key lookups for the fact
        # -------------------------------------------------------------
        d.execute("SELECT source_affiliation_id, affiliation_key FROM dim_affiliation")
        akey = {sid: k for sid, k in d.fetchall() if sid is not None}
        UNKNOWN_AFF = -1

        d.execute("SELECT label, accreditation_key FROM dim_accreditation")
        acckey = dict(d.fetchall())

        d.execute("SELECT is_scopus, is_garuda, indexing_key FROM dim_indexing")
        ikey = {(sc, ga): k for sc, ga, k in d.fetchall()}

        d.execute("SELECT captured_at, time_id FROM dim_time")
        tkey = dict(d.fetchall())

        # which journals are Scopus / Garuda?
        s.execute("""
            SELECT j.journal_id,
                   bool_or(ib.name = 'Scopus') AS sc,
                   bool_or(ib.name = 'Garuda') AS ga
            FROM journal j
            LEFT JOIN journal_indexing ji ON ji.journal_id = j.journal_id
            LEFT JOIN indexing_body    ib ON ib.body_id    = ji.body_id
            GROUP BY j.journal_id
        """)
        idxmap = {jid: (bool(sc), bool(ga)) for jid, sc, ga in s.fetchall()}

        # journal -> affiliation + accreditation label
        s.execute("""
            SELECT j.journal_id, j.affiliation_id,
                   COALESCE(a.label, 'Unknown') AS acc
            FROM journal j
            LEFT JOIN accreditation a ON a.accreditation_id = j.accreditation_id
        """)
        jmeta = {jid: (aff, acc) for jid, aff, acc in s.fetchall()}

        # -------------------------------------------------------------
        # fact_journal_metric
        # -------------------------------------------------------------
        s.execute("""
            SELECT journal_id, captured_at, impact, h5_index,
                   citations, citations_5yr
            FROM metric_snapshot
        """)
        facts = []
        for jid, ts, impact, h5, cit, cit5 in s.fetchall():
            if jid not in jkey:
                continue
            aff, acc = jmeta.get(jid, (None, 'Unknown'))
            sc, ga = idxmap.get(jid, (False, False))
            facts.append((
                jkey[jid],
                tkey[ts],
                akey.get(aff, UNKNOWN_AFF),
                acckey.get(acc, acckey['Unknown']),
                ikey[(sc, ga)],
                impact, h5, cit, cit5,
            ))

        psycopg2.extras.execute_batch(d, """
            INSERT INTO fact_journal_metric (
                journal_key, time_key, affiliation_key,
                accreditation_key, indexing_key,
                impact, h5_index, citations, citations_5yr
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (journal_key, time_key) DO NOTHING
        """, facts, page_size=1000)
        print(f"fact_journal_metric: {len(facts)}")

        dw.commit()
        print("\nCOMMITTED")

    except Exception as e:
        dw.rollback()
        print(f"\nROLLED BACK -- {type(e).__name__}: {e}")
        raise
    finally:
        s.close(); d.close(); src.close(); dw.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="postgresql://postgres:postgres@localhost:5432/sinta_db")
    ap.add_argument("--dw",  default="postgresql://postgres:postgres@localhost:5432/sinta_dw")
    args = ap.parse_args()
    main(args.src, args.dw)