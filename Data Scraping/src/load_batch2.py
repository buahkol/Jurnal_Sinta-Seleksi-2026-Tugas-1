"""
load_batch2.py -- append the second snapshot to metric_snapshot.

The journals, affiliations, subjects etc. already exist from batch 1 and
do NOT change. Only the metrics differ. So this loads ONLY the new
snapshots, and relies on the UNIQUE (journal_id, captured_at) constraint:

  * same timestamp as before -> ON CONFLICT DO NOTHING (no-op, safe)
  * new timestamp            -> new rows appended (the trend data)

The AFTER-INSERT trigger on metric_snapshot then advances each journal's
last_seen_at, which is the SQL proof that a scheduled re-run occurred.

Usage:
    python load_batch2.py --dsn "postgresql://postgres:pw@localhost/sinta_db"
"""

import argparse
import json
import pathlib

import psycopg2
import psycopg2.extras

DATA = pathlib.Path(__file__).parent.parent / "data"


def main(dsn):
    snaps = json.loads((DATA / "metric_snapshots_batch2.json").read_text(encoding="utf-8"))
    print(f"batch-2 snapshots: {len(snaps):,}")

    conn = psycopg2.connect(dsn)
    cur = conn.cursor()

    # Filter: only snapshots for journals that already exist in batch 1.
    # Batch 2 (4 days later) may contain journals SINTA registered after
    # batch 1 -- those have no parent row in `journal`, so their FK would
    # fail. We skip them and report the count: it is direct evidence that
    # SINTA's catalogue grew between the two scrapes.
    cur.execute("SELECT journal_id FROM journal")
    existing = {r[0] for r in cur.fetchall()}
    before_filter = len(snaps)
    new_journals = sorted({s["journal_id"] for s in snaps
                           if s["journal_id"] not in existing})
    snaps = [s for s in snaps if s["journal_id"] in existing]
    print(f"  {len(snaps):,} snapshots for existing journals")
    print(f"  {len(new_journals):,} journals are NEW (registered after batch 1) -- skipped")
    if new_journals[:5]:
        print(f"    contoh id jurnal baru: {new_journals[:5]}")

    # how many journals existed before?
    cur.execute("SELECT COUNT(DISTINCT captured_at) FROM metric_snapshot")
    before_batches = cur.fetchone()[0]

    psycopg2.extras.execute_batch(cur, """
        INSERT INTO metric_snapshot (
            journal_id, captured_at, impact, h5_index, citations, citations_5yr
        ) VALUES (
            %(journal_id)s, %(captured_at)s, %(impact)s,
            %(h5_index)s, %(citations)s, %(citations_5yr)s
        )
        ON CONFLICT (journal_id, captured_at) DO NOTHING
    """, snaps, page_size=1000)

    conn.commit()

    cur.execute("SELECT COUNT(DISTINCT captured_at) FROM metric_snapshot")
    after_batches = cur.fetchone()[0]

    print(f"\ndistinct timestamps: {before_batches} -> {after_batches}")

    # Prove the trigger fired: last_seen_at should now exceed first_seen_at
    cur.execute("""
        SELECT COUNT(*) FILTER (WHERE last_seen_at > first_seen_at),
               COUNT(*)
        FROM journal
    """)
    updated, total = cur.fetchone()
    print(f"journals with last_seen_at advanced: {updated:,}/{total:,}")

    # Show a sample of actual metric change
    print("\n--- contoh perubahan sitasi antar-batch ---")
    cur.execute("""
        SELECT j.name,
               MIN(ms.citations) AS batch1,
               MAX(ms.citations) AS batch2,
               MAX(ms.citations) - MIN(ms.citations) AS delta
        FROM metric_snapshot ms
        JOIN journal j ON j.journal_id = ms.journal_id
        GROUP BY j.journal_id, j.name
        HAVING COUNT(DISTINCT ms.captured_at) = 2
           AND MAX(ms.citations) <> MIN(ms.citations)
        ORDER BY delta DESC
        LIMIT 5
    """)
    rows = cur.fetchall()
    if rows:
        for name, b1, b2, d in rows:
            print(f"  {name[:44]:<44} {b1} -> {b2}  (+{d})")
    else:
        print("  (belum ada perubahan -- batch 2 mungkin terlalu dekat waktunya)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dsn", default="postgresql://postgres:postgres@localhost/sinta_db")
    args = ap.parse_args()
    main(args.dsn)