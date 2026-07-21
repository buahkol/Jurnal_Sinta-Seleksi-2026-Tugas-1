-- =====================================================================
-- optimization.sql -- 3 query optimizations with before/after proof
-- Seleksi Asisten Lab Basis Data 2026 | NIM 18224081  (BONUS)
--
-- Method: for each query, run EXPLAIN ANALYZE BEFORE (no index -> seq
-- scan), CREATE INDEX, then EXPLAIN ANALYZE AFTER. The RESULT is
-- identical; only the plan and timing change.
--
-- Run:  psql -U postgres -d sinta_db -f optimization.sql
-- Screenshot each BEFORE/AFTER pair into Data Storing/screenshots/
-- =====================================================================

\timing on

-- start clean
DROP INDEX IF EXISTS idx_journal_accreditation;
DROP INDEX IF EXISTS idx_ms_journal_time;
DROP INDEX IF EXISTS idx_js_subject;

\echo ''
\echo '### OPTIMIZATION 1: filter jurnal berdasarkan akreditasi ###'
\echo ''
\echo '=== BEFORE (tanpa index -> Seq Scan 15.448 baris) ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT j.affiliation_id, COUNT(*)
FROM journal j
WHERE j.accreditation_id = 1
GROUP BY j.affiliation_id;

\echo ''
\echo '=== membuat index ==='
CREATE INDEX idx_journal_accreditation ON journal(accreditation_id);

\echo ''
\echo '=== AFTER (dengan index) ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT j.affiliation_id, COUNT(*)
FROM journal j
WHERE j.accreditation_id = 1
GROUP BY j.affiliation_id;


\echo ''
\echo '### OPTIMIZATION 2: lookup metrik time-series per jurnal ###'
\echo ''
\echo '=== BEFORE (tanpa index -> Seq Scan metric_snapshot) ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT captured_at, impact, citations
FROM metric_snapshot
WHERE journal_id = 671
ORDER BY captured_at DESC;

\echo ''
\echo '=== membuat composite index ==='
CREATE INDEX idx_ms_journal_time ON metric_snapshot(journal_id, captured_at DESC);

\echo ''
\echo '=== AFTER (dengan composite index) ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT captured_at, impact, citations
FROM metric_snapshot
WHERE journal_id = 671
ORDER BY captured_at DESC;


\echo ''
\echo '### OPTIMIZATION 3: cari jurnal per bidang (M:N join) ###'
\echo ''
\echo '=== BEFORE (tanpa index pada subject_id) ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT j.name
FROM journal j
JOIN journal_subject js ON js.journal_id = j.journal_id
JOIN subject_area s ON s.subject_id = js.subject_id
WHERE s.name = 'Education';

\echo ''
\echo '=== membuat index ==='
CREATE INDEX idx_js_subject ON journal_subject(subject_id);

\echo ''
\echo '=== AFTER (dengan index) ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT j.name
FROM journal j
JOIN journal_subject js ON js.journal_id = j.journal_id
JOIN subject_area s ON s.subject_id = js.subject_id
WHERE s.name = 'Education';


\echo ''
\echo '### VERIFIKASI: output identik (jumlah baris before = after) ###'
SELECT 'Q1 jurnal S1'        AS query, COUNT(*) AS baris FROM journal WHERE accreditation_id = 1
UNION ALL
SELECT 'Q2 snapshot j671',   COUNT(*) FROM metric_snapshot WHERE journal_id = 671
UNION ALL
SELECT 'Q3 jurnal Education', COUNT(*)
FROM journal_subject js JOIN subject_area s ON s.subject_id = js.subject_id
WHERE s.name = 'Education';