-- =====================================================================
-- verify.sql -- proof-of-storage queries
-- Seleksi Asisten Lab Basis Data 2026 | NIM 18224081
--
-- The spec requires:
--   "Folder screenshots berisi tangkapan layar bukti dari penyimpanan
--    data ke dalam RDBMS (Query SELECT FROM WHERE pada RDBMS)."
--
-- Run:  psql -U postgres -d sinta_db -f verify.sql
-- Screenshot the output of each section into Data Storing/screenshots/
-- =====================================================================

\echo '=== 1. ROW COUNTS ==='
SELECT 'journal'          AS tabel, COUNT(*) FROM journal
UNION ALL SELECT 'affiliation',      COUNT(*) FROM affiliation
UNION ALL SELECT 'subject_area',     COUNT(*) FROM subject_area
UNION ALL SELECT 'journal_subject',  COUNT(*) FROM journal_subject
UNION ALL SELECT 'journal_indexing', COUNT(*) FROM journal_indexing
UNION ALL SELECT 'metric_snapshot',  COUNT(*) FROM metric_snapshot
UNION ALL SELECT 'accreditation',    COUNT(*) FROM accreditation
UNION ALL SELECT 'indexing_body',    COUNT(*) FROM indexing_body
UNION ALL SELECT 'publisher (kosong, sesuai spek)',  COUNT(*) FROM publisher
UNION ALL SELECT 'department (kosong, sesuai spek)', COUNT(*) FROM department;


\echo ''
\echo '=== 2. SELECT ... FROM ... WHERE -- jurnal S1 terindeks Scopus ==='
SELECT j.name,
       a.name          AS afiliasi,
       ms.impact,
       ms.citations
FROM journal j
JOIN accreditation ac  ON ac.accreditation_id = j.accreditation_id
JOIN affiliation   a   ON a.affiliation_id    = j.affiliation_id
JOIN metric_snapshot ms ON ms.journal_id      = j.journal_id
WHERE ac.label = 'S1'
  AND EXISTS (
      SELECT 1 FROM journal_indexing ji
      JOIN indexing_body ib ON ib.body_id = ji.body_id
      WHERE ji.journal_id = j.journal_id AND ib.name = 'Scopus'
  )
ORDER BY ms.impact DESC NULLS LAST
LIMIT 10;


\echo ''
\echo '=== 3. VALIDASI: distribusi akreditasi vs angka resmi SINTA ==='
-- SINTA (donut chart): S1=268 S2=1511 S3=2834 S4=5239 S5=5338 S6=262
SELECT COALESCE(ac.label, '(tanpa badge)') AS akreditasi,
       COUNT(*)                            AS jumlah_kami,
       CASE ac.label
            WHEN 'S1' THEN 268  WHEN 'S2' THEN 1511
            WHEN 'S3' THEN 2834 WHEN 'S4' THEN 5239
            WHEN 'S5' THEN 5338 WHEN 'S6' THEN 262
       END                                 AS jumlah_sinta,
       COUNT(*) - CASE ac.label
            WHEN 'S1' THEN 268  WHEN 'S2' THEN 1511
            WHEN 'S3' THEN 2834 WHEN 'S4' THEN 5239
            WHEN 'S5' THEN 5338 WHEN 'S6' THEN 262
       END                                 AS selisih
FROM journal j
LEFT JOIN accreditation ac ON ac.accreditation_id = j.accreditation_id
GROUP BY ac.label
ORDER BY ac.label NULLS LAST;


\echo ''
\echo '=== 4. BUKTI M:N -- jurnal dengan >1 subject area ==='
-- Membuktikan junction table journal_subject memang perlu:
-- satu jurnal dapat memiliki banyak subject area sekaligus.
SELECT j.name,
       COUNT(js.subject_id)              AS jml_subject,
       STRING_AGG(s.name, ', ' ORDER BY s.name) AS daftar_subject
FROM journal j
JOIN journal_subject js ON js.journal_id = j.journal_id
JOIN subject_area   s  ON s.subject_id   = js.subject_id
GROUP BY j.journal_id, j.name
HAVING COUNT(js.subject_id) > 3
ORDER BY COUNT(js.subject_id) DESC
LIMIT 10;


\echo ''
\echo '=== 5. SPARSITAS -- berapa jurnal punya subject area? ==='
SELECT CASE WHEN js.journal_id IS NULL THEN 'tanpa subject area'
            ELSE 'punya subject area' END AS status,
       COUNT(DISTINCT j.journal_id)       AS jumlah,
       ROUND(100.0 * COUNT(DISTINCT j.journal_id)
             / (SELECT COUNT(*) FROM journal), 1) AS persen
FROM journal j
LEFT JOIN journal_subject js ON js.journal_id = j.journal_id
GROUP BY (js.journal_id IS NULL);


\echo ''
\echo '=== 6. M:N indexing -- Scopus, Garuda, atau keduanya? ==='
SELECT COALESCE(ib.name, '(tidak terindeks)') AS badan_indeks,
       COUNT(*)                               AS jumlah_jurnal
FROM journal j
LEFT JOIN journal_indexing ji ON ji.journal_id = j.journal_id
LEFT JOIN indexing_body    ib ON ib.body_id    = ji.body_id
GROUP BY ib.name
ORDER BY jumlah_jurnal DESC;

\echo ''
\echo '--- jurnal yang terindeks Scopus DAN Garuda sekaligus ---'
SELECT COUNT(*) AS jml_jurnal_dua_indeks
FROM (
    SELECT ji.journal_id
    FROM journal_indexing ji
    GROUP BY ji.journal_id
    HAVING COUNT(*) = 2
) t;


\echo ''
\echo '=== 7. TIME-SERIES -- berapa batch tersimpan? ==='
-- Inilah alasan metric_snapshot dipisah dari journal:
-- setiap scrape MENAMBAH baris, bukan menimpa.
SELECT captured_at,
       COUNT(*) AS jml_jurnal
FROM metric_snapshot
GROUP BY captured_at
ORDER BY captured_at;


\echo ''
\echo '=== 8. TRIGGER bekerja -- first_seen vs last_seen ==='
SELECT COUNT(*) FILTER (WHERE first_seen_at = last_seen_at) AS belum_pernah_update,
       COUNT(*) FILTER (WHERE last_seen_at > first_seen_at) AS sudah_ter_update
FROM journal;


\echo ''
\echo '=== 9. INTEGRITAS -- tidak ada duplikat, FK valid ==='
SELECT (SELECT COUNT(*) FROM journal)                    AS baris_journal,
       (SELECT COUNT(DISTINCT journal_id) FROM journal)  AS journal_id_unik,
       (SELECT COUNT(*) FROM journal WHERE affiliation_id IS NULL)
                                                         AS tanpa_afiliasi,
       (SELECT COUNT(*) FROM journal WHERE accreditation_id IS NULL)
                                                         AS tanpa_akreditasi;