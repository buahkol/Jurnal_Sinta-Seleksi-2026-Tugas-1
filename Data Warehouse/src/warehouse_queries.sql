-- =====================================================================
-- warehouse_queries.sql -- analytic queries on the star schema
-- Seleksi Asisten Lab Basis Data 2026 | NIM 18224081  (BONUS)
--
-- After batch 2, fact_journal_metric holds 2 rows per journal (one per
-- snapshot). Q1-Q5 are point-in-time analyses, so they filter to the
-- LATEST batch. Q6 is the cross-batch trend and uses all rows.
--
-- Run:  psql -U postgres -d sinta_dw -f warehouse_queries.sql
-- =====================================================================

\echo '=== Q1. Rata-rata impact per tingkat akreditasi (batch terbaru) ==='
SELECT da.label                   AS akreditasi,
       COUNT(*)                   AS jml_jurnal,
       ROUND(AVG(f.impact), 2)    AS rata_impact,
       ROUND(AVG(f.citations), 0) AS rata_sitasi,
       MAX(f.citations)           AS sitasi_tertinggi
FROM fact_journal_metric f
JOIN dim_accreditation da ON da.accreditation_key = f.accreditation_key
WHERE f.time_key = (SELECT MAX(time_id) FROM dim_time)
GROUP BY da.label, da.rank_numeric
ORDER BY da.rank_numeric NULLS LAST;


\echo ''
\echo '=== Q2. Apakah indeksasi Scopus berkorelasi dgn impact? (batch terbaru) ==='
SELECT di.label                    AS profil_indeks,
       COUNT(*)                    AS jml_jurnal,
       ROUND(AVG(f.impact), 2)     AS rata_impact,
       ROUND(AVG(f.citations), 0)  AS rata_sitasi
FROM fact_journal_metric f
JOIN dim_indexing di ON di.indexing_key = f.indexing_key
WHERE f.time_key = (SELECT MAX(time_id) FROM dim_time)
GROUP BY di.label
ORDER BY rata_impact DESC NULLS LAST;


\echo ''
\echo '=== Q3. Top 10 afiliasi berdasarkan jumlah jurnal S1-S2 (batch terbaru) ==='
SELECT af.name                  AS afiliasi,
       COUNT(*)                 AS jml_jurnal_top,
       ROUND(AVG(f.impact), 2)  AS rata_impact
FROM fact_journal_metric f
JOIN dim_affiliation af   ON af.affiliation_key   = f.affiliation_key
JOIN dim_accreditation da ON da.accreditation_key = f.accreditation_key
WHERE f.time_key = (SELECT MAX(time_id) FROM dim_time)
  AND da.rank_numeric IN (1, 2)
  AND af.affiliation_key <> -1
GROUP BY af.name
ORDER BY jml_jurnal_top DESC
LIMIT 10;


\echo ''
\echo '=== Q4. Distribusi jurnal per subject area (batch terbaru) ==='
SELECT s.name                        AS subject_area,
       COUNT(DISTINCT b.journal_key) AS jml_jurnal,
       ROUND(AVG(f.impact), 2)       AS rata_impact
FROM bridge_journal_subject b
JOIN dim_subject s        ON s.subject_key = b.subject_key
JOIN fact_journal_metric f ON f.journal_key = b.journal_key
WHERE f.time_key = (SELECT MAX(time_id) FROM dim_time)
GROUP BY s.name
ORDER BY jml_jurnal DESC;


\echo ''
\echo '=== Q5. Matriks silang: akreditasi x profil indeks (batch terbaru) ==='
SELECT da.label AS akreditasi,
       COUNT(*) FILTER (WHERE di.label = 'Scopus + Garuda') AS scopus_garuda,
       COUNT(*) FILTER (WHERE di.label = 'Scopus only')     AS scopus_saja,
       COUNT(*) FILTER (WHERE di.label = 'Garuda only')     AS garuda_saja,
       COUNT(*) FILTER (WHERE di.label = 'Not indexed')     AS tidak_terindeks
FROM fact_journal_metric f
JOIN dim_accreditation da ON da.accreditation_key = f.accreditation_key
JOIN dim_indexing di      ON di.indexing_key      = f.indexing_key
WHERE f.time_key = (SELECT MAX(time_id) FROM dim_time)
GROUP BY da.label, da.rank_numeric
ORDER BY da.rank_numeric NULLS LAST;


\echo ''
\echo '=== Q6. TREN: pertumbuhan sitasi antar-batch (SEMUA batch) ==='
SELECT dt.batch_date,
       COUNT(*)                    AS jml_jurnal,
       ROUND(AVG(f.citations), 0)  AS rata_sitasi,
       SUM(f.citations)            AS total_sitasi
FROM fact_journal_metric f
JOIN dim_time dt ON dt.time_id = f.time_key
GROUP BY dt.batch_date
ORDER BY dt.batch_date;