-- =====================================================================
-- query_optimasi.sql
-- Seleksi Asisten Lab Basis Data 2026 | NIM 18224081  (BONUS)
--
-- Berisi 3 query optimasi beserta bukti bahwa versi teroptimasi
-- menghasilkan output identik dengan performa lebih baik.
--
-- METODOLOGI
-- ----------
-- Untuk setiap query dijalankan tiga langkah:
--   1. EXPLAIN (ANALYZE, BUFFERS) pada kondisi TANPA index
--   2. CREATE INDEX
--   3. EXPLAIN (ANALYZE, BUFFERS) pada kondisi DENGAN index
--
-- Output query harus identik pada kedua kondisi. Yang berubah hanya
-- rencana eksekusi (query plan) dan waktu eksekusi.
--
-- CATATAN DESAIN
-- --------------
-- Seluruh index pada schema.sql sengaja dikomentari agar kondisi
-- "sebelum optimasi" benar-benar tanpa index. Membuat index sejak awal
-- akan menghilangkan bukti pembanding yang dibutuhkan.
--
-- CARA MENJALANKAN
-- ----------------
--   psql -U postgres -d sinta_db -f query_optimasi.sql
-- =====================================================================

\timing on

-- Menghapus index dari eksekusi sebelumnya agar kondisi "sebelum
-- optimasi" dapat direproduksi dengan konsisten.
DROP INDEX IF EXISTS idx_journal_accreditation;
DROP INDEX IF EXISTS idx_journal_affiliation;
DROP INDEX IF EXISTS idx_js_subject;


-- =====================================================================
-- OPTIMASI 1: Filter jurnal berdasarkan tingkat akreditasi
-- =====================================================================
--
-- FUNGSI QUERY
--   Menghitung jumlah jurnal berakreditasi S1 (accreditation_id = 1)
--   yang dikelompokkan per afiliasi penerbit. Query semacam ini
--   digunakan untuk menjawab pertanyaan "institusi mana yang paling
--   banyak menerbitkan jurnal S1".
--
-- MASALAH SEBELUM OPTIMASI
--   Tanpa index pada kolom accreditation_id, PostgreSQL harus membaca
--   seluruh 15.448 baris tabel journal, lalu membuang 15.180 baris yang
--   tidak memenuhi filter. Hanya 268 baris yang relevan, sehingga 98%
--   pembacaan terbuang percuma.
--
-- SOLUSI OPTIMASI
--   Membuat index B-tree pada kolom accreditation_id. Index ini
--   memungkinkan PostgreSQL langsung menemukan 268 baris yang relevan
--   tanpa memindai seluruh tabel.
--
-- HASIL YANG DIHARAPKAN
--   Seq Scan berubah menjadi Index Scan, dan jumlah buffer yang dibaca
--   turun drastis.
-- =====================================================================

\echo ''
\echo '### OPTIMASI 1: Filter jurnal berdasarkan akreditasi ###'
\echo ''
\echo '--- SEBELUM: tanpa index, Seq Scan pada 15.448 baris ---'

EXPLAIN (ANALYZE, BUFFERS)
SELECT j.affiliation_id, COUNT(*)
FROM journal j
WHERE j.accreditation_id = 1
GROUP BY j.affiliation_id;

\echo ''
\echo '--- Membuat index pada journal(accreditation_id) ---'

-- Index B-tree pada kolom yang menjadi predikat filter.
-- Kardinalitas kolom ini rendah (hanya 8 nilai berbeda), namun
-- distribusinya sangat tidak merata: S1 hanya 268 dari 15.448 baris,
-- sehingga index tetap efektif untuk nilai yang jarang muncul.
CREATE INDEX idx_journal_accreditation ON journal(accreditation_id);

\echo ''
\echo '--- SESUDAH: dengan index, Index Scan ---'

EXPLAIN (ANALYZE, BUFFERS)
SELECT j.affiliation_id, COUNT(*)
FROM journal j
WHERE j.accreditation_id = 1
GROUP BY j.affiliation_id;


-- =====================================================================
-- OPTIMASI 2: Pencarian jurnal berdasarkan afiliasi penerbit
-- =====================================================================
--
-- FUNGSI QUERY
--   Mengambil seluruh jurnal yang diterbitkan oleh satu afiliasi
--   tertentu beserta metrik terbarunya. Contoh yang digunakan adalah
--   affiliation_id = 9 (Universitas Negeri Semarang) yang menerbitkan
--   163 jurnal.
--
--   Pola query ini merupakan salah satu akses paling umum pada domain
--   ini, misalnya untuk menjawab "tampilkan seluruh jurnal terbitan
--   universitas X beserta impact-nya".
--
-- MASALAH SEBELUM OPTIMASI
--   Kolom journal.affiliation_id tidak memiliki index. PostgreSQL harus
--   memindai seluruh 15.448 baris tabel journal untuk menemukan 163
--   baris yang relevan, artinya 98,9% pembacaan terbuang.
--
--   Selektivitas query ini tinggi: hanya 1,06% baris yang memenuhi
--   filter. Kondisi seperti ini adalah kasus ideal penggunaan index.
--
-- SOLUSI OPTIMASI
--   Membuat index B-tree pada kolom affiliation_id sehingga PostgreSQL
--   dapat langsung menemukan baris yang relevan.
--
-- HASIL YANG DIHARAPKAN
--   Seq Scan pada journal berubah menjadi Index Scan atau Bitmap Index
--   Scan, dengan penurunan jumlah buffer yang dibaca secara signifikan.
-- =====================================================================

\echo ''
\echo '### OPTIMASI 2: Pencarian jurnal berdasarkan afiliasi ###'
\echo ''
\echo '--- SEBELUM: tanpa index pada affiliation_id, Seq Scan ---'

EXPLAIN (ANALYZE, BUFFERS)
SELECT j.name, ms.impact, ms.citations
FROM journal j
JOIN metric_snapshot ms ON ms.journal_id = j.journal_id
WHERE j.affiliation_id = 9
  AND ms.captured_at = (SELECT MAX(captured_at) FROM metric_snapshot);

\echo ''
\echo '--- Membuat index pada journal(affiliation_id) ---'

-- Index B-tree pada foreign key yang sering menjadi predikat filter.
-- PostgreSQL tidak membuat index otomatis untuk kolom foreign key,
-- berbeda dengan primary key. Padahal FK justru sering digunakan
-- sebagai titik masuk query, sehingga index eksplisit diperlukan.
CREATE INDEX idx_journal_affiliation ON journal(affiliation_id);

\echo ''
\echo '--- SESUDAH: dengan index ---'

EXPLAIN (ANALYZE, BUFFERS)
SELECT j.name, ms.impact, ms.citations
FROM journal j
JOIN metric_snapshot ms ON ms.journal_id = j.journal_id
WHERE j.affiliation_id = 9
  AND ms.captured_at = (SELECT MAX(captured_at) FROM metric_snapshot);


-- =====================================================================
-- OPTIMASI 3: Pencarian jurnal berdasarkan bidang keilmuan (join M:N)
-- =====================================================================
--
-- FUNGSI QUERY
--   Mengambil seluruh jurnal yang tercakup dalam bidang keilmuan
--   "Education". Query ini melewati junction table journal_subject yang
--   merepresentasikan relasi many-to-many antara jurnal dan bidang.
--
-- MASALAH SEBELUM OPTIMASI
--   Junction table journal_subject memiliki primary key composite
--   (journal_id, subject_id). Index bawaan PK tersebut disusun dengan
--   journal_id sebagai kolom pertama, sehingga hanya efisien untuk
--   pencarian berdasarkan journal_id.
--
--   Query ini melakukan pencarian sebaliknya, yaitu berdasarkan
--   subject_id. Karena subject_id bukan kolom pertama pada index PK,
--   PostgreSQL tidak dapat memanfaatkannya dan terpaksa melakukan
--   Seq Scan pada seluruh 6.703 baris junction table.
--
-- SOLUSI OPTIMASI
--   Membuat index terpisah pada kolom subject_id agar pencarian dari
--   arah bidang keilmuan juga dapat memanfaatkan index.
--
-- CATATAN
--   Percepatan bersifat moderat karena bagian dominan dari query ini
--   adalah nested loop join ke tabel journal (4.602 buffer) yang sudah
--   menggunakan journal_pkey. Optimasi lanjutan yang mungkin dilakukan
--   adalah covering index pada journal(journal_id, name).
-- =====================================================================

\echo ''
\echo '### OPTIMASI 3: Pencarian jurnal per bidang keilmuan ###'
\echo ''
\echo '--- SEBELUM: tanpa index pada subject_id, Seq Scan junction ---'

EXPLAIN (ANALYZE, BUFFERS)
SELECT j.name
FROM journal j
JOIN journal_subject js ON js.journal_id = j.journal_id
JOIN subject_area   s   ON s.subject_id  = js.subject_id
WHERE s.name = 'Education';

\echo ''
\echo '--- Membuat index pada journal_subject(subject_id) ---'

-- Index pada kolom kedua dari composite PK. Diperlukan karena index
-- bawaan PK (journal_id, subject_id) tidak dapat melayani pencarian
-- yang hanya menyebutkan subject_id.
CREATE INDEX idx_js_subject ON journal_subject(subject_id);

\echo ''
\echo '--- SESUDAH: dengan index, Bitmap Index Scan ---'

EXPLAIN (ANALYZE, BUFFERS)
SELECT j.name
FROM journal j
JOIN journal_subject js ON js.journal_id = j.journal_id
JOIN subject_area   s   ON s.subject_id  = js.subject_id
WHERE s.name = 'Education';


-- =====================================================================
-- VERIFIKASI: output identik sebelum dan sesudah optimasi
-- =====================================================================
--
-- FUNGSI QUERY
--   Menghitung jumlah baris hasil dari ketiga query di atas. Angka ini
--   harus sama persis pada kondisi sebelum maupun sesudah optimasi.
--
--   Optimasi index tidak boleh mengubah hasil query, hanya cara
--   PostgreSQL mencapai hasil tersebut. Jika jumlah baris berbeda,
--   berarti query telah diubah dan perbandingan performa menjadi tidak
--   valid.
-- =====================================================================

\echo ''
\echo '### VERIFIKASI: jumlah baris hasil harus identik ###'

SELECT 'Optimasi 1: jurnal S1'         AS query,
       COUNT(*)                        AS jumlah_baris
FROM journal
WHERE accreditation_id = 1

UNION ALL

SELECT 'Optimasi 2: jurnal afiliasi 9',
       COUNT(*)
FROM journal j
JOIN metric_snapshot ms ON ms.journal_id = j.journal_id
WHERE j.affiliation_id = 9
  AND ms.captured_at = (SELECT MAX(captured_at) FROM metric_snapshot)

UNION ALL

SELECT 'Optimasi 3: jurnal Education',
       COUNT(*)
FROM journal_subject js
JOIN subject_area s ON s.subject_id = js.subject_id
WHERE s.name = 'Education';