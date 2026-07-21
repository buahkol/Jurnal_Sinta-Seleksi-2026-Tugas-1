-- =====================================================================
-- warehouse_schema.sql -- SINTA Data Warehouse (Star Schema)
-- Seleksi Asisten Lab Basis Data 2026 | NIM 18224081  (BONUS)
--
-- Target: PostgreSQL 14+
-- Run:    createdb -U postgres sinta_dw
--         psql -U postgres -d sinta_dw -f warehouse_schema.sql
--
-- DESIGN RATIONALE
-- ----------------
-- A star schema: one central FACT table surrounded by DIMENSION tables.
-- Chosen over snowflake for query simplicity -- dimensions are small
-- enough that normalising them further buys nothing.
--
-- The grain of the fact table is:
--     ONE ROW PER (journal, time snapshot).
-- i.e. "the measurable metrics of one journal, as observed at one point
-- in time." This grain is what makes historical trend analysis possible
-- once the scheduling bonus adds a second snapshot.
--
-- Dimensions were chosen by DATA COVERAGE, measured on the real data:
--     accreditation : 100%  -> dimension
--     affiliation   :  87%  -> dimension (12.5% "Unknown" member)
--     indexing      :  98%  -> dimension (Garuda near-universal)
--     time          : 100%  -> dimension
--     subject area  :  24%  -> BRIDGE, not a star dimension, because
--                              76% of journals have none. Forcing it into
--                              the star would make most facts point at an
--                              "Unclassified" member, which is meaningless.
-- =====================================================================

DROP TABLE IF EXISTS fact_journal_metric CASCADE;
DROP TABLE IF EXISTS bridge_journal_subject CASCADE;
DROP TABLE IF EXISTS dim_journal      CASCADE;
DROP TABLE IF EXISTS dim_affiliation  CASCADE;
DROP TABLE IF EXISTS dim_accreditation CASCADE;
DROP TABLE IF EXISTS dim_indexing     CASCADE;
DROP TABLE IF EXISTS dim_subject      CASCADE;
DROP TABLE IF EXISTS dim_time         CASCADE;

-- ---------------------------------------------------------------------
-- DIMENSION: time
--   One row per scrape batch. This is the axis that turns a snapshot
--   database into a historical warehouse.
-- ---------------------------------------------------------------------
CREATE TABLE dim_time (
    time_id      SERIAL PRIMARY KEY,
    captured_at  TIMESTAMPTZ NOT NULL UNIQUE,
    batch_date   DATE NOT NULL,
    batch_year   SMALLINT NOT NULL,
    batch_month  SMALLINT NOT NULL,
    batch_label  VARCHAR(40)          -- e.g. "2026-07 batch 1"
);

-- ---------------------------------------------------------------------
-- DIMENSION: accreditation
--   Degenerate-ish lookup, but a proper dimension so facts can slice
--   by tier without joining back to the OLTP database.
-- ---------------------------------------------------------------------
CREATE TABLE dim_accreditation (
    accreditation_key SERIAL PRIMARY KEY,
    label             VARCHAR(20) NOT NULL UNIQUE,
    rank_numeric      SMALLINT,
    is_accredited     BOOLEAN NOT NULL     -- FALSE for Cancelled/Not/Unknown
);

INSERT INTO dim_accreditation (label, rank_numeric, is_accredited) VALUES
    ('S1', 1, TRUE), ('S2', 2, TRUE), ('S3', 3, TRUE),
    ('S4', 4, TRUE), ('S5', 5, TRUE), ('S6', 6, TRUE),
    ('Cancelled',      NULL, FALSE),
    ('Not Accredited', NULL, FALSE),
    ('Unknown',        NULL, FALSE);      -- the 1 journal with no badge

-- ---------------------------------------------------------------------
-- DIMENSION: affiliation
--   Includes a surrogate "Unknown" member (key = -1) so the 1,941
--   journals with no affiliation still join cleanly. This is standard
--   warehouse practice: facts must never have a NULL dimension key.
-- ---------------------------------------------------------------------
CREATE TABLE dim_affiliation (
    affiliation_key    SERIAL PRIMARY KEY,
    source_affiliation_id INTEGER UNIQUE,   -- original SINTA id
    name               TEXT NOT NULL
);

-- Seed the surrogate "Unknown" member at key -1. SERIAL is just an
-- integer with a sequence default, so an explicit -1 is allowed; the
-- sequence keeps assigning positive keys to real affiliations.
INSERT INTO dim_affiliation (affiliation_key, source_affiliation_id, name)
    VALUES (-1, NULL, 'Unknown / Unaffiliated');

-- ---------------------------------------------------------------------
-- DIMENSION: indexing profile
--   Cardinality is tiny in practice (Garuda 98%, Scopus 1.4%), so we
--   pre-compute the four possible combinations as a dimension rather
--   than keeping a per-body bridge in the warehouse.
-- ---------------------------------------------------------------------
CREATE TABLE dim_indexing (
    indexing_key SERIAL PRIMARY KEY,
    is_scopus    BOOLEAN NOT NULL,
    is_garuda    BOOLEAN NOT NULL,
    label        VARCHAR(30) NOT NULL     -- "Scopus+Garuda", "Garuda only"...
);

INSERT INTO dim_indexing (is_scopus, is_garuda, label) VALUES
    (TRUE,  TRUE,  'Scopus + Garuda'),
    (TRUE,  FALSE, 'Scopus only'),
    (FALSE, TRUE,  'Garuda only'),
    (FALSE, FALSE, 'Not indexed');

-- ---------------------------------------------------------------------
-- DIMENSION: journal (the descriptive attributes that do NOT change
--   per snapshot -- name, issn, links). Metrics live in the FACT.
-- ---------------------------------------------------------------------
CREATE TABLE dim_journal (
    journal_key    SERIAL PRIMARY KEY,
    source_journal_id INTEGER NOT NULL UNIQUE,
    name           TEXT NOT NULL,
    p_issn         VARCHAR(20),
    e_issn         VARCHAR(20)
);

-- ---------------------------------------------------------------------
-- DIMENSION: subject
-- ---------------------------------------------------------------------
CREATE TABLE dim_subject (
    subject_key SERIAL PRIMARY KEY,
    name        VARCHAR(60) NOT NULL UNIQUE
);

-- ---------------------------------------------------------------------
-- BRIDGE: journal <-> subject  (M:N, only 24% of journals participate)
--   A bridge rather than a star dimension, because a journal can have
--   0..10 subjects. Aggregations through a bridge can double-count, so
--   analysts must be aware -- documented, not hidden.
-- ---------------------------------------------------------------------
CREATE TABLE bridge_journal_subject (
    journal_key INTEGER NOT NULL REFERENCES dim_journal(journal_key),
    subject_key INTEGER NOT NULL REFERENCES dim_subject(subject_key),
    PRIMARY KEY (journal_key, subject_key)
);

-- ---------------------------------------------------------------------
-- FACT: journal metrics
--   Grain: one row per (journal, time). Additive measures: citations,
--   citations_5yr, h5_index. Semi-additive: impact (an average -- do not
--   SUM it across journals; AVG it).
-- ---------------------------------------------------------------------
CREATE TABLE fact_journal_metric (
    journal_key       INTEGER NOT NULL REFERENCES dim_journal(journal_key),
    time_key          INTEGER NOT NULL REFERENCES dim_time(time_id),
    affiliation_key   INTEGER NOT NULL REFERENCES dim_affiliation(affiliation_key),
    accreditation_key INTEGER NOT NULL REFERENCES dim_accreditation(accreditation_key),
    indexing_key      INTEGER NOT NULL REFERENCES dim_indexing(indexing_key),

    -- measures
    impact        NUMERIC(10,2),
    h5_index      INTEGER,
    citations     INTEGER,
    citations_5yr INTEGER,

    PRIMARY KEY (journal_key, time_key)
);

CREATE INDEX idx_fact_time    ON fact_journal_metric(time_key);
CREATE INDEX idx_fact_accred  ON fact_journal_metric(accreditation_key);
CREATE INDEX idx_fact_affil   ON fact_journal_metric(affiliation_key);
CREATE INDEX idx_fact_index   ON fact_journal_metric(indexing_key);