-- =====================================================================
-- schema.sql -- SINTA journal database
-- Seleksi Asisten Lab Basis Data 2026 | NIM 18224081
--
-- Target: PostgreSQL 14+
-- Run:    psql -U postgres -d sinta_db -f schema.sql
-- =====================================================================

DROP TABLE IF EXISTS metric_snapshot   CASCADE;
DROP TABLE IF EXISTS journal_indexing  CASCADE;
DROP TABLE IF EXISTS journal_subject   CASCADE;
DROP TABLE IF EXISTS journal           CASCADE;
DROP TABLE IF EXISTS affiliation_department CASCADE;
DROP TABLE IF EXISTS author            CASCADE;
DROP TABLE IF EXISTS department        CASCADE;
DROP TABLE IF EXISTS affiliation       CASCADE;
DROP TABLE IF EXISTS subject_area      CASCADE;
DROP TABLE IF EXISTS indexing_body     CASCADE;
DROP TABLE IF EXISTS accreditation     CASCADE;

-- ---------------------------------------------------------------------
-- Lookup tables
-- ---------------------------------------------------------------------

-- Accreditation is NOT a plain integer. SINTA's own chart shows
-- "Not Accredited: 1" alongside S1..S6, and "Cancelled" also exists.
-- An INT column would force NULL to mean two different things
-- ("no rank" vs "cancelled"), so we model it as a lookup.
CREATE TABLE accreditation (
    accreditation_id SERIAL PRIMARY KEY,
    label            VARCHAR(20) NOT NULL UNIQUE,
    rank_numeric     SMALLINT,
    CONSTRAINT chk_rank_range
        CHECK (rank_numeric IS NULL OR rank_numeric BETWEEN 1 AND 6)
);

INSERT INTO accreditation (label, rank_numeric) VALUES
    ('S1', 1), ('S2', 2), ('S3', 3),
    ('S4', 4), ('S5', 5), ('S6', 6),
    ('Cancelled',      NULL),
    ('Not Accredited', NULL);

CREATE TABLE subject_area (
    subject_id SERIAL PRIMARY KEY,
    name       VARCHAR(60) NOT NULL UNIQUE
);

CREATE TABLE indexing_body (
    body_id SERIAL PRIMARY KEY,
    name    VARCHAR(40) NOT NULL UNIQUE
);

INSERT INTO indexing_body (name) VALUES ('Scopus'), ('Garuda');

-- ---------------------------------------------------------------------
-- Core entities
-- ---------------------------------------------------------------------

-- affiliation_id comes from SINTA's own URL (/affiliations/profile/9),
-- so we use their ID as our natural PK rather than inventing a surrogate.
-- This makes cross-batch deduplication trivial and idempotent.
CREATE TABLE affiliation (
    affiliation_id INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    sinta_url      TEXT
);

-- ---------------------------------------------------------------------
-- Extension entity: author
--
-- SINTA mendata peneliti sebagai entitas tersendiri pada halaman
-- /authors, lengkap dengan SINTA ID, afiliasi, departemen, bidang
-- keahlian, dan metrik (Scopus H-index, Google Scholar H-index).
--
-- Struktur tabel ini diturunkan dari hasil verifikasi langsung ke
-- halaman profil author, contoh:
--   https://sinta.kemdiktisaintek.go.id/authors/profile/5980682
--
-- SENGAJA DIBIARKAN KOSONG (sesuai spek). Halaman /authors berada di
-- luar cakupan scraping proyek ini, yang hanya menyasar listing jurnal.
-- Relasi author ke journal juga tidak dapat dimodelkan karena
-- hubungannya bersifat tidak langsung melalui artikel, dan data artikel
-- tidak tersedia pada halaman yang di-scrape.
--
-- author_id menggunakan SINTA ID asli (contoh: 5980682), konsisten
-- dengan pola natural key pada journal dan affiliation.
-- ---------------------------------------------------------------------
CREATE TABLE author (
    author_id      INTEGER PRIMARY KEY,   -- SINTA ID
    name           TEXT NOT NULL,
    affiliation_id INTEGER,
    department_id  INTEGER,
    scopus_h_index INTEGER,
    gs_h_index     INTEGER,

    CONSTRAINT fk_author_affiliation
        FOREIGN KEY (affiliation_id) REFERENCES affiliation(affiliation_id)
        ON DELETE SET NULL,

    CONSTRAINT chk_author_hindex CHECK (
        (scopus_h_index IS NULL OR scopus_h_index >= 0) AND
        (gs_h_index     IS NULL OR gs_h_index     >= 0)
    )
);

CREATE TABLE journal (
    journal_id       INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    p_issn           VARCHAR(20),
    e_issn           VARCHAR(20),
    affiliation_id   INTEGER,
    -- NULLABLE, deliberately. The scraped data contains journals carrying
    -- no accreditation badge at all -- neither S1..S6 nor "Cancelled" nor
    -- "Not Accredited". Forcing NOT NULL here would mean either dropping
    -- those rows (data loss) or inventing a fake label (a lie in the data).
    -- NULL is the honest representation of "SINTA shows no badge".
    accreditation_id INTEGER,
    sinta_url        TEXT,
    website          TEXT,
    google_scholar   TEXT,
    first_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_journal_affiliation
        FOREIGN KEY (affiliation_id) REFERENCES affiliation(affiliation_id)
        ON DELETE SET NULL,

    CONSTRAINT fk_journal_accreditation
        FOREIGN KEY (accreditation_id) REFERENCES accreditation(accreditation_id)
        ON DELETE RESTRICT,

    -- ISSN is 8 chars (digits, possibly trailing X). Reject malformed input
    -- at the DB boundary rather than trusting the scraper.
    CONSTRAINT chk_p_issn
        CHECK (p_issn IS NULL OR p_issn ~ '^[0-9]{7}[0-9X]$'),
    CONSTRAINT chk_e_issn
        CHECK (e_issn IS NULL OR e_issn ~ '^[0-9]{7}[0-9X]$'),

    CONSTRAINT chk_seen_order
        CHECK (last_seen_at >= first_seen_at)
);

-- ---------------------------------------------------------------------
-- M:N junctions
-- ---------------------------------------------------------------------

-- The real many-to-many. Evidence from the source data:
--   "Jurnal Pendidikan IPA Indonesia" -> Education                    (1)
--   "Journal of Islamic Law"          -> Religion, Economy,
--                                        Humanities, Social            (4)
-- A comma-joined VARCHAR would violate 1NF and make
-- "all Education journals" a LIKE '%...%' full scan.
CREATE TABLE journal_subject (
    journal_id INTEGER NOT NULL,
    subject_id INTEGER NOT NULL,

    PRIMARY KEY (journal_id, subject_id),

    CONSTRAINT fk_js_journal
        FOREIGN KEY (journal_id) REFERENCES journal(journal_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_js_subject
        FOREIGN KEY (subject_id) REFERENCES subject_area(subject_id)
        ON DELETE CASCADE
);

CREATE TABLE journal_indexing (
    journal_id INTEGER NOT NULL,
    body_id    INTEGER NOT NULL,

    PRIMARY KEY (journal_id, body_id),

    CONSTRAINT fk_ji_journal
        FOREIGN KEY (journal_id) REFERENCES journal(journal_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_ji_body
        FOREIGN KEY (body_id) REFERENCES indexing_body(body_id)
        ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- Time-series fact
-- ---------------------------------------------------------------------

-- THIS TABLE IS WHY THE SCHEDULING BONUS WORKS.
--
-- If impact/citations lived on the journal row, the second scrape would
-- overwrite the first and all history would be destroyed. By snapshotting
-- with (journal_id, captured_at), batch 2 ADDS rows instead of clobbering
-- them -- so the timestamp delta the spec asks for is directly queryable.
--
-- The UNIQUE constraint is the anti-redundancy guarantee the spec demands:
-- "Pastikan tidak terdapat redundansi data pada DBMS."
-- WEAK ENTITY.
--
-- metric_snapshot tidak memiliki identitas sendiri: sebuah pengukuran
-- hanya bermakna dalam konteks jurnal yang diukur. Karakteristik weak
-- entity terpenuhi:
--
--   * existence-dependent pada journal (ON DELETE CASCADE)
--   * tidak punya natural key sendiri
--   * discriminator = captured_at, yang hanya unik DALAM satu journal
--
-- Primary key = (journal_id, captured_at): composite dari FK ke owner
-- entity + discriminator. Ini notasi weak entity yang benar; surrogate
-- key BIGSERIAL sebelumnya tidak pernah direferensikan tabel manapun,
-- sehingga hanya menambah kolom tanpa manfaat.
--
-- Composite PK ini SEKALIGUS menjadi jaminan anti-redundansi yang
-- diminta spek: scrape ulang dengan timestamp sama tidak akan
-- menghasilkan baris ganda.
CREATE TABLE metric_snapshot (
    journal_id    INTEGER     NOT NULL,
    captured_at   TIMESTAMPTZ NOT NULL,
    impact        NUMERIC(10,2),
    h5_index      INTEGER,
    citations     INTEGER,
    citations_5yr INTEGER,

    -- identifying relationship: PK memuat FK ke owner entity
    PRIMARY KEY (journal_id, captured_at),

    CONSTRAINT fk_ms_journal
        FOREIGN KEY (journal_id) REFERENCES journal(journal_id)
        ON DELETE CASCADE,

    CONSTRAINT chk_nonneg CHECK (
        (impact        IS NULL OR impact        >= 0) AND
        (h5_index      IS NULL OR h5_index      >= 0) AND
        (citations     IS NULL OR citations     >= 0) AND
        (citations_5yr IS NULL OR citations_5yr >= 0)
    ),

    -- 5-year citations can never exceed all-time citations.
    -- A violation here means the locale-number parser broke.
    CONSTRAINT chk_5yr_lte_total CHECK (
        citations IS NULL OR citations_5yr IS NULL
        OR citations_5yr <= citations
    )
);

-- ---------------------------------------------------------------------
-- Extension tables (spec: may be added, may be left empty)
--
--   "Peserta dipersilakan untuk menambahkan tabel lain yang sekiranya
--    relevan ... Tabel tambahan ... tidak perlu diisi dengan data."
--
-- Both appear in SINTA's navigation but not on the journals listing,
-- so they are defensibly relevant and legitimately empty.
-- ---------------------------------------------------------------------

-- (author dipindah ke atas, sebelum journal, agar urutan CREATE TABLE
--  mengikuti dependensi foreign key)

-- Extension entity: department
--
-- Verifikasi ke halaman /departments menunjukkan bahwa departemen di
-- SINTA BUKAN milik satu afiliasi. Satu program studi dengan nama dan
-- kode yang sama dapat dimiliki banyak perguruan tinggi sekaligus.
-- Contoh terverifikasi: "Administrasi Bisnis (S1)" dengan CODE 63211
-- terdaftar pada 111 afiliasi berbeda.
--
-- Karena itu relasi affiliation-department dimodelkan sebagai
-- MANY-TO-MANY melalui junction table affiliation_department, bukan
-- 1:N sebagaimana asumsi awal.
--
-- Atribut level (D3/S1/S2/S3) dan code_prodi diturunkan dari tampilan
-- halaman /departments yang menampilkan jenjang akademik dan kode prodi
-- untuk setiap departemen.
--
-- SENGAJA DIBIARKAN KOSONG (sesuai spek). Halaman /departments berada
-- di luar cakupan scraping.
-- ---------------------------------------------------------------------
CREATE TABLE department (
    department_id SERIAL PRIMARY KEY,
    name          TEXT NOT NULL,
    level         VARCHAR(5),      -- D3, D4, S1, S2, S3
    code_prodi    VARCHAR(10),     -- contoh: 63211

    CONSTRAINT chk_dept_level
        CHECK (level IS NULL OR level IN ('D1','D2','D3','D4','S1','S2','S3','Sp')),

    CONSTRAINT uq_dept_name_level
        UNIQUE (name, level)
);

-- ---------------------------------------------------------------------
-- Junction M:N antara affiliation dan department.
--
-- Menggantikan asumsi awal bahwa departemen milik satu afiliasi.
-- SENGAJA DIBIARKAN KOSONG (sesuai spek).
-- ---------------------------------------------------------------------
CREATE TABLE affiliation_department (
    affiliation_id INTEGER NOT NULL,
    department_id  INTEGER NOT NULL,

    PRIMARY KEY (affiliation_id, department_id),

    CONSTRAINT fk_ad_affiliation
        FOREIGN KEY (affiliation_id) REFERENCES affiliation(affiliation_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_ad_department
        FOREIGN KEY (department_id) REFERENCES department(department_id)
        ON DELETE CASCADE
);

-- ---------------------------------------------------------------------
-- Trigger (spec explicitly asks for one)
-- ---------------------------------------------------------------------

-- Keeps journal.last_seen_at current whenever a new snapshot lands.
-- This is how you prove, in SQL, that batch 2 actually ran: the
-- last_seen_at moves forward while first_seen_at stays put.
CREATE OR REPLACE FUNCTION trg_touch_journal_last_seen()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE journal
       SET last_seen_at = NEW.captured_at
     WHERE journal_id   = NEW.journal_id
       AND last_seen_at < NEW.captured_at;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER touch_journal_last_seen
    AFTER INSERT ON metric_snapshot
    FOR EACH ROW
    EXECUTE FUNCTION trg_touch_journal_last_seen();

-- ---------------------------------------------------------------------
-- Indexes
--
-- NOTE: do NOT create these before you run the bonus-3 optimisation task.
-- Run your 3 queries with EXPLAIN ANALYZE FIRST (seq scans, slow), THEN
-- add these, THEN re-run. The before/after delta IS the deliverable.
-- Creating them upfront destroys the evidence you need.
-- ---------------------------------------------------------------------

-- CREATE INDEX idx_journal_accreditation ON journal(accreditation_id);
-- CREATE INDEX idx_journal_affiliation   ON journal(affiliation_id);
-- CREATE INDEX idx_js_subject            ON journal_subject(subject_id);
-- CREATE INDEX idx_ms_journal_time       ON metric_snapshot(journal_id, captured_at DESC);


-- ---------------------------------------------------------------------
-- FK author -> department ditambahkan di akhir karena tabel department
-- dibuat setelah author dalam urutan skrip ini.
-- ---------------------------------------------------------------------
ALTER TABLE author
    ADD CONSTRAINT fk_author_department
    FOREIGN KEY (department_id) REFERENCES department(department_id)
    ON DELETE SET NULL;