# Seleksi Asisten Lab Basis Data 2026 — Tugas 1 (ETL Project)

**Data Jurnal Ilmiah Indonesia Berdasarkan Peringkat Akreditasi SINTA, Afiliasi Penerbit, dan Metrik Sitasi**

---

## Author

| | |
|---|---|
| **Nama** | Illona Nasywa Hannum |
| **NIM** | 18224081 |
| **Sumber Data** | [SINTA — Science and Technology Index](https://sinta.kemdiktisaintek.go.id/journals) |
| **DBMS** | PostgreSQL 18.3 |

---

## Daftar Isi

1. [Deskripsi Proyek](#1-deskripsi-proyek)
2. [Etika Data Scraping](#2-etika-data-scraping)
3. [Step 1 — Data Scraping](#3-step-1--data-scraping)
4. [Step 2 — Data Modeling & Storing](#4-step-2--data-modeling--storing)
5. [Bonus — Data Warehouse](#5-bonus--data-warehouse)
6. [Bonus — Automated Scheduling](#6-bonus--automated-scheduling)
7. [Bonus — Query Optimization](#7-bonus--query-optimization)
8. [Struktur Repository](#8-struktur-repository)
9. [Penggunaan AI](#9-penggunaan-ai)
10. [Referensi](#10-referensi)

---

## 1. Deskripsi Proyek

Proyek ini melakukan ETL (Extract, Transform, Load) terhadap data jurnal ilmiah Indonesia yang terdaftar di **SINTA (Science and Technology Index)**, portal resmi Kementerian Pendidikan Tinggi, Sains, dan Teknologi RI.

**Data yang dikumpulkan:** 15.448 jurnal beserta afiliasi penerbit, tingkat akreditasi (S1–S6), status indeksasi (Scopus/Garuda), bidang keilmuan, dan metrik sitasi (impact, h5-index, citations, citations 5yr).

### Mengapa topik ini?

**1. Legalitas terverifikasi.** Pemeriksaan `robots.txt` pada `https://sinta.kemdiktisaintek.go.id/robots.txt` mengembalikan **HTTP 404** — tidak ada larangan crawling. SINTA juga tidak memiliki Terms of Service yang melarang scraping.

**2. Struktur relasional kaya.** Data memiliki relasi 1:N (afiliasi→jurnal), M:N (jurnal↔bidang, jurnal↔badan indeks), dan atribut temporal (metrik sitasi) — memadai untuk ERD yang bermakna, bukan sekadar tabel datar.

**3. Server-side rendered.** SINTA menyajikan HTML lengkap tanpa JavaScript, sehingga dapat di-scrape dengan `requests` biasa tanpa melanggar aturan "dilarang menggunakan API".

**4. Data berubah antar-waktu.** Metrik sitasi diperbarui berkala, memungkinkan implementasi bonus scheduling dengan data yang benar-benar berubah.

### Mengapa PostgreSQL?

Mendukung penuh constraint (CHECK dengan regex, FK dengan berbagai `ON DELETE`, trigger), tipe `TIMESTAMPTZ` untuk time-series, serta fitur analitik (`FILTER`, CTE) yang dibutuhkan untuk data warehouse.

---

## 2. Etika Data Scraping

### Sumber yang dipertimbangkan dan ditolak

| Sumber | Alasan penolakan |
|--------|------------------|
| **Circle Chart** (K-pop) | Footer situs eksplisit melarang *text and data mining* (TDM) |
| **Discogs** | Terms of Service eksplisit melarang *"data mining, robots, scraping, harvesting"* |
| **BMKG** | Menyediakan API resmi — dilarang oleh spesifikasi tugas |
| **Hanteo, Ktown4u** | Single-Page Application; data hanya via API internal (setara penggunaan API) |
| **PDDIKTI** | React SPA, dan memuat data pribadi mahasiswa (masalah etika) |

SINTA lolos seluruh kriteria: tidak ada larangan TDM, tidak ada API publik, server-rendered, berisi data institusional publik.

### Praktik scraping yang diterapkan

| Praktik | Implementasi |
|---|---|
| **User-Agent jujur** | `SintaAcademicScraper/1.0 (Seleksi Asisten Lab Basis Data ITB 2026; mailto:18224081@std.stei.itb.ac.id)` |
| **Rate limiting** | Delay 1,2 detik + jitter acak 0–0,3 detik |
| **Exponential backoff** | Retry hingga 5× dengan jeda 2ⁿ detik (maks 30s) |
| **Cache lokal** | Halaman disimpan ke disk agar debugging tidak menembak server berulang |

---

## 3. Step 1 — Data Scraping

### 3.1 Tools

| Library | Versi | Fungsi |
|---------|-------|--------|
| `requests` | 2.32.3 | HTTP client |
| `beautifulsoup4` | 4.12.3 | Parsing HTML via CSS selector |
| `re`, `json` | stdlib | Ekstraksi pola & serialisasi |

**Tidak menggunakan:** API (dilarang spek), Selenium/Playwright (tidak perlu — SINTA server-rendered).

### 3.2 Cara menjalankan

```bash
cd "Data Scraping/src"
pip install -r ../../requirements.txt

python seed_state.py          # bootstrap dari cache (tanpa network)
python scraper_convergent.py  # convergent crawl
python split_convergent.py    # normalisasi → JSON per-entitas
```

### 3.3 Temuan Kritis: Unstable Pagination

**Crawl pertama menghasilkan 15.453 kartu** — persis sama dengan total resmi SINTA — dan keenam tingkat akreditasi cocok sempurna. Validasi berbasis total menyatakan sukses.

**Namun pemeriksaan keunikan mengungkap hanya 12.071 jurnal unik.** Sebanyak **3.382 jurnal (22%) tidak pernah ter-scrape** — celahnya tertutup persis oleh 3.382 duplikat.

#### Penyebab

SINTA mengurutkan listing berdasarkan **Impact**, metrik yang berubah terus-menerus. Pengukuran langsung pada halaman ke-50:

```
t =  0 detik : [9291, 6740, 953, ..., 2867, 873]
t = 30 detik : [9291, 6740, 953, ..., 2867, 873]   → 10/10 identik
t = 60 detik : [9291, 6740, 953, ..., 2867, 329]   →  9/10 identik
```

Selama crawl 45 menit, jurnal bergeser antar-halaman: sebagian terambil berkali-kali, sebagian tidak pernah terambil.

#### Pendekatan yang diuji dan gagal

| # | Pendekatan | Hasil |
|---|---|---|
| 1 | GET sort parameters (8 kandidat) | Semua diabaikan — sorting ternyata form POST (`changesort=1, sort=1..5`) |
| 2 | Page-size parameters (`per_page`, `limit`, dll.) | Terkunci di 10 kartu/halaman |
| 3 | POST accreditation filter | Diabaikan server; partisi S1 mengembalikan 431 alih-alih 268 |

#### Solusi: Convergent Crawling

Karena drift bersifat **acak**, setiap pass melewatkan himpunan jurnal yang berbeda. Union hasil beberapa pass menutup celahnya — masalah *coupon collector* dengan konvergensi cepat:

| Pass | Jurnal baru | Total | Sisa |
|-----:|------------:|------:|-----:|
| seed | — | 12.071 | 3.382 |
| 1 | +2.151 | 14.222 | 1.231 |
| 2 | +805 | 15.027 | 426 |
| 3 | +278 | 15.305 | 148 |
| 4 | +101 | 15.406 | 47 |
| 5 | +35 | 15.441 | 12 |
| 6 | +7 | **15.448** | 5 |

**Hasil akhir: 15.448 jurnal unik (99,97%), 0 duplikat.**

Lima jurnal sisa kemungkinan tidak lagi eksis — counter "15.453" di halaman SINTA dapat berupa nilai ter-cache.

> **Pelajaran:** validasi berbasis agregat adalah *necessary but not sufficient*. Hanya pemeriksaan keunikan yang menangkap kegagalan ini. Tanpa itu, seluruh ERD, warehouse, dan analisis akan dibangun di atas dataset yang **22% tidak lengkap** — tanpa satu pun indikasi kesalahan.

### 3.4 Preprocessing

**1. Angka format Indonesia**

```
"104,00"  →  104.0     (koma = pemisah desimal)
"14.902"  →  14902     (titik = pemisah ribuan)
```

`float("14.902")` mengembalikan `14.902` — **salah 1000×** tanpa raise exception. Parser menangani konversi locale ini dengan 18 doctest.

**2. ISSN placeholder** — SINTA menyimpan `"0"` untuk jurnal tanpa ISSN cetak. Dinormalisasi menjadi `NULL`; jika tidak, akan melanggar CHECK constraint saat load.

**3. URL placeholder** — link mati dirender sebagai `href="#!"`, dibersihkan menjadi `NULL`.

**4. Ekstraksi ID dari URL** — `journal_id` dan `affiliation_id` (PK & FK) tidak muncul dalam teks; diekstrak dari `https://sinta.kemdiktisaintek.go.id/journals/profile/671` → `671`.

**5. Deduplikasi subject area** — dinormalisasi dengan `dict.fromkeys()` yang mempertahankan urutan.

### 3.5 Struktur File JSON

| File | Isi | Baris |
|------|-----|------:|
| `journals.json` | Entitas jurnal + atribut | 15.448 |
| `affiliations.json` | Afiliasi/penerbit unik | 2.013 |
| `subject_areas.json` | Bidang keilmuan | 10 |
| `journal_subject.json` | Junction M:N jurnal↔bidang | 6.703 |
| `journal_indexing.json` | Junction M:N jurnal↔indeks | 15.398 |
| `metric_snapshots.json` | Metrik batch 1 | 15.448 |
| `metric_snapshots_batch2.json` | Metrik batch 2 | 15.023 |

**Contoh `journals.json`:**

```json
{
  "journal_id": 671,
  "name": "Jurnal Pendidikan IPA Indonesia (Indonesian Journal of Science Education)",
  "p_issn": "23391286",
  "e_issn": "20894392",
  "affiliation_id": 9,
  "accreditation_label": "S1",
  "accreditation_rank": 1,
  "is_scopus": true,
  "is_garuda": true,
  "sinta_url": "https://sinta.kemdiktisaintek.go.id/journals/profile/671",
  "website": "https://journal.unnes.ac.id/journals/jpii",
  "google_scholar": "https://scholar.google.co.id/citations?user=NgzWOogAAAAJ&hl=en",
  "scraped_at": "2026-07-13T10:51:54.541093+00:00"
}
```

**Penjelasan kolom URL:**
- `sinta_url` — halaman asal data, untuk *traceability* hasil scraping
- `website` — situs resmi jurnal
- `google_scholar` — profil jurnal di Google Scholar, **sumber asli** metrik sitasi yang ditampilkan SINTA

### 3.6 Karakteristik Data (Terverifikasi)

Nilai NULL pada dataset — bukan kegagalan pipeline, melainkan properti sumber:

| Kolom | NULL | Persentase | Interpretasi |
|---|---:|---:|---|
| `p_issn` | 4.317 | 27,9% | Jurnal *online-only*, tidak pernah terbit cetak |
| `e_issn` | 81 | 0,5% | Jurnal cetak tanpa versi elektronik |
| `affiliation_id` | 1.941 | 12,6% | Afiliasi tidak dicantumkan SINTA |
| `google_scholar` | 2.561 | 16,6% | Link profil tidak dirender (`href="#!"`) |
| `website` | 8 | 0,1% | — |
| `accreditation_label` | 1 | 0,006% | Sesuai chart SINTA: "Not Accredited: 1" |

**Observasi:** ketiadaan link Google Scholar **tidak berkorelasi** dengan ketiadaan metrik. Dari 2.561 jurnal tanpa link tersebut, **1.744 (68%) tetap memiliki data sitasi** — sebagian bernilai tinggi (mis. *Gadjah Mada International Journal of Business*: 36.213 sitasi, h5-index 74). SINTA tampaknya menyimpan metrik hasil sinkronisasi sebelumnya meskipun tautan profil tidak ditampilkan.

**Kolom metrik terisi 100%** — tidak ada NULL pada `impact`, `h5_index`, `citations`, maupun `citations_5yr`.

---

## 4. Step 2 — Data Modeling & Storing

### 4.1 Cara menjalankan

```bash
createdb -U postgres sinta_db
psql -U postgres -d sinta_db -f "Data Storing/src/schema.sql"

cd "Data Storing/src"
python load.py --dsn "postgresql://postgres:PASSWORD@localhost/sinta_db"
psql -U postgres -d sinta_db -f verify.sql
```

### 4.2 Struktur ERD

![ERD](Data%20Storing/design/erd.png)

Notasi **Silberschatz** (sesuai materi IF2140):

| Simbol | Arti |
|---|---|
| Persegi panjang | Entity set |
| **Persegi ganda** | Weak entity set |
| Belah ketupat | Relationship set |
| **Belah ketupat ganda** | Identifying relationship |
| Garis bawah penuh | Primary key |
| **Garis bawah putus-putus** | Discriminator (partial key) |
| Panah (→) | Sisi "one" pada relasi many-to-one |
| Tanpa panah | Many-to-many |
| **Garis ganda** | Total participation |

**8 entity set:** `JOURNAL`, `AFFILIATION`, `ACCREDITATION`, `SUBJECT_AREA`, `INDEXING_BODY`, `METRIC_SNAPSHOT` (weak), `PUBLISHER`, `DEPARTMENT`.

**7 relationship set:**

| Relasi | Entitas | Kardinalitas | Partisipasi |
|---|---|---|---|
| *memiliki* | AFFILIATION → JOURNAL | many-to-one | parsial (1.941 tanpa afiliasi) |
| *menerbitkan* | PUBLISHER → JOURNAL | many-to-one | parsial |
| *diberi peringkat* | ACCREDITATION → JOURNAL | many-to-one | parsial (1 tanpa akreditasi) |
| *tercakup* | JOURNAL ↔ SUBJECT_AREA | **many-to-many** | parsial (76,1% tanpa subject) |
| *terindeks* | JOURNAL ↔ INDEXING_BODY | **many-to-many** | parsial (255 tanpa indeks) |
| *diukur* | JOURNAL → METRIC_SNAPSHOT | one-to-many | **total** (identifying) |
| *terbagi atas* | AFFILIATION → DEPARTMENT | many-to-one | total |

#### Weak Entity: METRIC_SNAPSHOT

Memenuhi seluruh karakteristik weak entity:

1. **Tidak memiliki primary key sendiri** — sebuah pengukuran hanya bermakna dalam konteks jurnal yang diukur
2. **Existence-dependent** pada `JOURNAL` (`ON DELETE CASCADE`)
3. **Discriminator** `captured_at`, hanya unik *dalam* satu journal
4. **Partisipasi total** dalam identifying relationship *diukur*

Translasi ke relasional: `PRIMARY KEY (journal_id, captured_at)` — FK ke owner entity + discriminator.

> Desain awal menggunakan surrogate key `snapshot_id BIGSERIAL`. Kolom tersebut **tidak pernah direferensikan tabel manapun**, sehingga dihapus. Composite PK sekaligus menjadi jaminan anti-redundansi yang diminta spesifikasi.

#### Fitur ERD lanjutan yang tidak digunakan

| Fitur | Alasan |
|---|---|
| **Generalization/Specialization (ISA)** | Tidak ada subtipe jurnal dengan atribut berbeda. Status indeksasi dimodelkan sebagai relasi M:N, bukan subtipe, karena satu jurnal dapat terindeks di beberapa badan sekaligus (terbukti: 205 jurnal Scopus+Garuda) |
| **Aggregation** | Tidak ada relationship set yang berpartisipasi dalam relationship set lain |
| **Multivalued attribute** | Semua atribut jamak sudah dimodelkan sebagai entity set terpisah dengan relasi M:N |

> Domain data SINTA bersifat entitas datar dengan relasi eksplisit, sehingga model E-R dasar sudah memadai. Memaksakan konstruksi lanjutan akan menghasilkan *over-engineering*.

### 4.3 Diagram Relasional

![Relational Diagram](Data%20Storing/design/relational.png)

**10 tabel** hasil translasi dari 8 entity set.

### 4.4 Proses Translasi ERD → Diagram Relasional

#### Aturan 1 — Entity set → Tabel

Setiap entity set menjadi satu tabel; atribut menjadi kolom, primary key menjadi PK tabel.

#### Aturan 2 — Relasi 1:N → Foreign key di sisi "many"

| Relasi ERD | Implementasi |
|---|---|
| AFFILIATION → JOURNAL | `journal.affiliation_id` (nullable) |
| PUBLISHER → JOURNAL | `journal.publisher_id` (nullable) |
| ACCREDITATION → JOURNAL | `journal.accreditation_id` (nullable) |
| AFFILIATION → DEPARTMENT | `department.affiliation_id` (NOT NULL) |

Nullability mencerminkan **partisipasi parsial** pada ERD.

#### Aturan 3 — Relasi M:N → Junction table

| Relasi ERD | Tabel hasil | Primary key |
|---|---|---|
| JOURNAL ↔ SUBJECT_AREA | `journal_subject` | `(journal_id, subject_id)` |
| JOURNAL ↔ INDEXING_BODY | `journal_indexing` | `(journal_id, body_id)` |

**Inilah sebabnya 8 entity set menjadi 10 tabel.** Junction table adalah artefak implementasi, bukan konsep — karena itu tidak muncul di ERD.

**Bukti relasi M:N nyata (terverifikasi dari data):**
- **3 jurnal** tercakup dalam kesepuluh subject area sekaligus
- Distribusi subject per jurnal: 1→1.993, 2→907, 3→464, 4→221, 5→82, 6→14, 7→9, 8→3, 9→1, 10→3
- **205 jurnal** terindeks di Scopus **dan** Garuda bersamaan

Menyimpan ini sebagai kolom bernilai jamak akan melanggar **1NF**.

#### Aturan 4 — Weak entity → Composite primary key

`METRIC_SNAPSHOT` menjadi tabel dengan PK gabungan FK ke owner + discriminator:

```sql
PRIMARY KEY (journal_id, captured_at)
```

### 4.5 Constraint yang Diimplementasikan

| Jenis | Jumlah | Keterangan |
|---|---:|---|
| **PRIMARY KEY** | 10 | Seluruh tabel |
| **FOREIGN KEY** | 8 | Dengan `ON DELETE` sesuai semantik: `CASCADE` (weak entity, junction), `SET NULL` (relasi opsional), `RESTRICT` (lookup) |
| **UNIQUE** | 3 | `accreditation.label`, `subject_area.name`, `indexing_body.name` |
| **CHECK** | 6 | Format ISSN (regex `^[0-9]{7}[0-9X]$`), rentang rank 1–6, metrik non-negatif, `citations_5yr ≤ citations`, `last_seen_at ≥ first_seen_at` |
| **TRIGGER** | 1 | `touch_journal_last_seen` — memperbarui `journal.last_seen_at` saat snapshot baru masuk |

### 4.6 Penggunaan Surrogate Key — Justifikasi

Implementasi RDBMS mengikuti diagram relasional secara **1:1**.

**Natural key dipertahankan:**

`journal.journal_id` dan `affiliation.affiliation_id` menggunakan **ID asli dari SINTA** (diekstrak dari URL), bukan surrogate. Ini memungkinkan **deduplikasi idempoten antar-batch** — tanpa ini, batch 2 akan membuat 15.023 baris baru yang tidak dapat dicocokkan dengan batch 1, dan bonus scheduling menjadi mustahil.

**Surrogate key digunakan pada:**

`accreditation`, `subject_area`, `indexing_body`, `publisher`, `department` — natural key tetap dijaga melalui constraint `UNIQUE`. Surrogate `SERIAL` digunakan sebagai FK agar lebih ringkas (INTEGER 4 byte vs VARCHAR) dan perubahan nama tidak memerlukan cascade update.

**Surrogate key dihindari pada:**

`metric_snapshot` — menggunakan composite PK sesuai model weak entity.

### 4.7 Tabel Tambahan (Sengaja Kosong)

**`publisher`** — SINTA memiliki entitas penerbit terpisah, namun tidak ditampilkan pada halaman listing yang menjadi sumber scraping. Data berada di halaman `/publishers` yang di luar cakupan.

> **Catatan kejujuran:** kolom `country` bersifat **antisipatif** dan belum terverifikasi tersedia di SINTA. Disertakan karena relevan secara domain (banyak jurnal Indonesia diterbitkan penerbit internasional seperti IAES), namun tidak diturunkan dari data.

**`department`** — Kolom afiliasi SINTA memuat hierarki tiga tingkat dalam satu string:

```
"Science Education Study Program, Faculty of Mathematics and Natural Sciences, Universitas Negeri Semarang"
 └── program studi ──────────┘  └── fakultas ───────────────────────┘  └── universitas ───────┘
```

Data ini **tersirat** dalam `affiliation.name`. Namun ekstraksi memerlukan parsing teks bebas dengan format tidak konsisten (sebagian hanya menyebut universitas, sebagian menggunakan frasa *"in cooperation with"*), sehingga berisiko menghasilkan data salah. Tabel dirancang untuk menunjukkan normalisasi yang seharusnya, namun tidak diisi demi menjaga integritas.

### 4.8 Validasi Penyimpanan

| Tingkat | Database | SINTA | Selisih |
|---|---:|---:|---:|
| S1 | 268 | 268 | 0 |
| S2 | 1.511 | 1.511 | 0 |
| S3 | 2.833 | 2.834 | −1 |
| S4 | 5.238 | 5.239 | −1 |
| S5 | 5.335 | 5.338 | −3 |
| S6 | 262 | 262 | 0 |
| (tanpa badge) | 1 | — | — |

**Coverage: 99,97%. Integritas: 15.448 baris = 15.448 `journal_id` unik → 0 duplikat.**

Screenshot bukti: `Data Storing/screenshots/` (18 file).

---

## 5. Bonus — Data Warehouse

![Star Schema](Data%20Warehouse/design/warehouse_star_schema.png)

### 5.1 Cara menjalankan

```bash
createdb -U postgres sinta_dw
psql -U postgres -d sinta_dw -f "Data Warehouse/src/warehouse_schema.sql"

cd "Data Warehouse/src"
python warehouse_load.py \
  --src "postgresql://postgres:PW@localhost/sinta_db" \
  --dw  "postgresql://postgres:PW@localhost/sinta_dw"

psql -U postgres -d sinta_dw -f warehouse_queries.sql
```

### 5.2 Desain: Star Schema

**Grain fact table:** satu baris per **(jurnal, waktu snapshot)**.

| Komponen | Tabel | Baris |
|---|---|---:|
| **Fact** | `fact_journal_metric` | 30.466 |
| **Dimension** | `dim_time` | 8 |
| | `dim_journal` | 15.448 |
| | `dim_affiliation` | 2.014 (2.013 + Unknown) |
| | `dim_accreditation` | 9 |
| | `dim_indexing` | 4 |
| | `dim_subject` | 10 |
| **Bridge** | `bridge_journal_subject` | 6.703 |

**Measure attributes:**

| Measure | Sifat | Aturan agregasi |
|---|---|---|
| `citations`, `citations_5yr`, `h5_index` | Additive | Boleh `SUM` dan `AVG` |
| `impact` | **Semi-additive** | **Hanya `AVG`** — nilai ini sudah berupa rata-rata |

### 5.3 Keputusan Desain

**1. Star, bukan snowflake.** Dimensi berukuran kecil (4–2.014 baris), sehingga normalisasi lebih lanjut hanya menambah join tanpa menghemat ruang berarti.

**2. `dim_time` sebagai dimensi wajib.** Sesuai materi kuliah, dimensi waktu adalah dimensi wajib dalam model multidimensional. Inilah yang mengubah snapshot menjadi warehouse historis — setelah scrape kedua, analisis tren menjadi mungkin **tanpa perubahan skema**.

**3. Subject sebagai bridge, bukan dimensi star** *(di luar materi kuliah)*. Model multidimensional standar mengasumsikan relasi many-to-one dari fact ke dimension. Namun relasi jurnal↔subject bersifat many-to-many (0–10 bidang per jurnal). Memaksakannya menjadi dimensi star akan menyebabkan 76,1% fact menunjuk member "Unclassified". **Bridge table** adalah pola standar Kimball untuk M:N dalam warehouse.

> **Konsekuensi:** agregasi melalui bridge berisiko *double-counting*. Query Q4 karenanya menggunakan `COUNT(DISTINCT journal_key)`.

**Catatan pada diagram:** `bridge_journal_subject` tidak terhubung langsung ke `fact_journal_metric`, melainkan ke `dim_journal`. Ini disengaja — menghubungkan bridge langsung ke fact akan menggandakan baris fact dan merusak grain.

**4. Member "Unknown" (key −1)** *(di luar materi kuliah)*. Fact table sebaiknya tidak memiliki FK NULL. 1.941 jurnal tanpa afiliasi dipetakan ke surrogate member `affiliation_key = -1`.

### 5.4 Perbandingan OLTP vs Warehouse

| Aspek | `sinta_db` (OLTP) | `sinta_dw` (OLAP) |
|---|---|---|
| Normalisasi | 3NF/BCNF | Denormalisasi terkendali |
| Tujuan | Integritas & update | Kecepatan query analitik |
| Tabel | 10 | 8 (1 fact + 6 dim + 1 bridge) |
| Query khas | Cari/ubah 1 jurnal | Agregasi lintas dimensi |
| Data | Current state | **Historis** (via `dim_time`) |

### 5.5 Kebutuhan Informasi & Query Analitik

| # | Pertanyaan Analitik | Pendekatan |
|---|---|---|
| Q1 | Apakah akreditasi tinggi berkorelasi dengan impact tinggi? | Agregasi per `dim_accreditation` |
| Q2 | Apakah indeksasi Scopus menandakan kualitas lebih baik? | Agregasi per `dim_indexing` |
| Q3 | Institusi mana yang paling produktif menghasilkan jurnal top? | Agregasi per `dim_affiliation` |
| Q4 | Bidang keilmuan apa yang paling banyak jurnalnya? | Agregasi via `bridge` |
| Q5 | Bagaimana distribusi indeksasi per tingkat akreditasi? | Cross-tab 2 dimensi |
| Q6 | Bagaimana pertumbuhan sitasi antar-waktu? | Agregasi per `dim_time` |

### 5.6 Temuan Analitik

**Temuan 1 — Scopus terkonsentrasi di puncak (Q5)**

| Akreditasi | Scopus+Garuda | Garuda saja |
|---|---:|---:|
| S1 | **195** | 61 |
| S2 | 7 | 1.449 |
| S3 | 2 | 2.690 |
| S4 | **0** | 5.027 |
| S5 | **0** | 5.084 |
| S6 | **0** | 243 |

Dari 204 jurnal Scopus+Garuda pada batch terbaru, **195 berada di S1**. Mulai S4 ke bawah: **nol**.

**Temuan 2 — Anomali "Scopus only" (Q2)**

| Profil indeks | Jumlah | Rata impact | Rata sitasi |
|---|---:|---:|---:|
| Scopus + Garuda | 204 | 3,65 | 5.534 |
| Garuda only | 14.555 | 2,65 | 1.110 |
| Not indexed | 249 | 1,82 | 1.681 |
| **Scopus only** | **10** | **0,55** ⬇ | **11.412** ⬆ |

Sepuluh jurnal terindeks Scopus namun bukan Garuda memiliki **sitasi rata-rata tertinggi** namun **impact SINTA terendah**.

> **Interpretasi (hipotesis):** kemungkinan jurnal internasional yang tidak terdaftar di Garuda (database nasional). Sitasi globalnya masif, namun metrik impact SINTA berbasis konteks nasional. *Hipotesis ini belum diverifikasi ke sumber primer.*

**Temuan 3 — Garuda near-universal**

15.183 dari 15.448 jurnal (98,3%) terindeks Garuda. Ini **baseline nasional**, bukan sinyal pembeda. Scopus (215 jurnal, 1,4%) adalah indeks yang benar-benar selektif.

**Temuan 4 — Limitasi bridge double-counting (Q4)**

Rata impact per subject area menunjukkan nilai tinggi untuk beberapa bidang (Economy: 41,06). Ini kemungkinan **artefak double-counting**: jurnal multi-subject dengan impact tinggi dihitung pada setiap bidangnya. Dicatat sebagai limitasi metodologis, bukan temuan substantif.

---

## 6. Bonus — Automated Scheduling

### 6.1 Implementasi

| Batch | Tanggal | Timestamp | Jurnal |
|---|---|---|---:|
| 1 | 13 Juli 2026 | 7 timestamp internal (06:56–10:51 UTC) | 15.448 |
| 2 | **17 Juli 2026** | `2026-07-17T08:11:13Z` | 15.023 |

**Jeda: 4 hari.**

```bash
cd "Data Scraping/src"
python scrape_batch2.py --passes 3
python load_batch2.py --dsn "postgresql://postgres:PW@localhost/sinta_db"
```

> **Catatan transparansi:** batch 1 memiliki 7 timestamp berbeda karena convergent crawling menjalankan 7 pass, masing-masing menandai jurnal yang baru ditemukan dengan waktu pass tersebut. Secara logis ini adalah **satu batch**; batch 2 memiliki timestamp tunggal.

### 6.2 Mekanisme Anti-Redundansi

Kunci desainnya: **pemisahan `metric_snapshot` dari `journal`**.

| Jika metrik disimpan di... | Konsekuensi scrape kedua |
|---|---|
| Kolom `journal.impact`, `journal.citations` | Batch 2 **menimpa** batch 1 → histori hilang |
| Tabel `metric_snapshot` terpisah | Batch 2 **menambah** baris → histori terjaga |

Dijamin oleh composite primary key:

```sql
PRIMARY KEY (journal_id, captured_at)
```

Timestamp sama → `ON CONFLICT DO NOTHING` (no-op). Timestamp baru → baris ditambahkan.

### 6.3 Bukti Perubahan

**Timestamp bertambah:**
```
distinct timestamps : 7 → 8
metric_snapshot     : 15.448 → 30.466 baris
```

**Trigger bekerja:**

| Kondisi | Sebelum batch 2 | Sesudah batch 2 |
|---|---:|---:|
| `last_seen_at = first_seen_at` | 15.448 | 430 |
| `last_seen_at > first_seen_at` | **0** | **15.018** |

**Delta sitasi (4 hari):**

| Jurnal | Batch 1 | Batch 2 | Δ |
|---|---:|---:|---:|
| Jurnal Multidisiplin Indonesia | 0 | 3.741 | +3.741 |
| Indonesian Journal of Science and Mathematics | 1.978 | 5.261 | +3.283 |
| JURNAL BIOSAINSTEK | 0 | 846 | +846 |
| JIPFRI | 926 | 1.574 | +648 |
| Journal of Insan Mulia Education | 0 | 511 | +511 |

> Beberapa jurnal naik dari 0 ke ribuan sitasi. Ini kemungkinan bukan pertumbuhan organik, melainkan jurnal yang metriknya baru disinkronkan SINTA.

**Katalog SINTA bertambah:**

Batch 2 menemukan **5 jurnal baru** (ID: 567, 5607, 15556, 16467, 17290) yang belum ada di batch 1. Foreign key constraint pada `metric_snapshot` menolak snapshot untuk jurnal yang belum terdaftar — bukti langsung integritas referensial bekerja otomatis.

**Tren di warehouse (Q6):**

| Tanggal | Jurnal | Rata sitasi | Total sitasi |
|---|---:|---:|---:|
| 2026-07-13 | 15.448 | 1.169 | 18.064.654 |
| 2026-07-17 | 15.018 | **1.187** | 17.821.849 |

Rata-rata sitasi naik dari 1.169 ke 1.187. Query yang **sama persis**, tanpa perubahan skema, kini menghasilkan analisis tren.

### 6.4 Keterbatasan

Scheduling dijalankan **manual**, bukan otomatis via cron/Task Scheduler. Yang didemonstrasikan adalah **mekanisme anti-redundansi dan penyimpanan historis** — bagian yang secara arsitektur penting. Otomasi penjadwalan dapat ditambahkan dengan `schtasks` (Windows) atau `cron` (Unix) tanpa perubahan kode.

---

## 7. Bonus — Query Optimization

### 7.1 Metodologi

Untuk setiap query: jalankan `EXPLAIN (ANALYZE, BUFFERS)` **sebelum** index dibuat, buat index, jalankan **sesudah**. Output query harus identik.

```bash
psql -U postgres -d sinta_db -f "Data Storing/src/optimization.sql"
```

> **Catatan desain:** index sengaja **dikomentari** pada `schema.sql` agar kondisi "before" benar-benar tanpa index.

### 7.2 Hasil

| # | Query | Before | After | Percepatan |
|---|---|---|---|---|
| **1** | Filter jurnal per akreditasi | Seq Scan, **8,74 ms**, 1.070 buffer | Index Scan, **0,28 ms**, 16 buffer | **31×** |
| **2** | Lookup metrik time-series | Bitmap on PK, **0,44 ms** | Bitmap on composite index, **0,13 ms** | **3,5×** |
| **3** | Join M:N per bidang | Seq Scan junction, **5,49 ms** | Bitmap Index Scan, **2,54 ms** | **2,2×** |

**Verifikasi output identik:**

| Query | Baris hasil |
|---|---:|
| Q1 jurnal S1 | 268 |
| Q2 snapshot jurnal 671 | 2 |
| Q3 jurnal Education | 1.534 |

### 7.3 Analisis

**Optimasi 1 — Index pada `journal(accreditation_id)`**

`BEFORE` membaca 15.448 baris lalu membuang 15.180 (`Rows Removed by Filter: 15180`). `AFTER` langsung mengakses 268 baris via index. Buffer turun dari 1.070 ke 16 — **98,5% pengurangan I/O**.

**Optimasi 2 — Composite index `(journal_id, captured_at DESC)`**

Temuan menarik: pada `BEFORE`, PostgreSQL **sudah menggunakan index** (`Bitmap Index Scan on metric_snapshot_pkey`) — bukan Seq Scan.

> Ini konsekuensi langsung dari memodelkan `metric_snapshot` sebagai **weak entity** dengan composite PK. PostgreSQL otomatis membuat index pada PK, sehingga lookup per jurnal sudah efisien tanpa index tambahan.
>
> Index eksplisit dengan urutan `captured_at DESC` tetap memberi percepatan 3,5× karena menghindari operasi sort pada `ORDER BY captured_at DESC`.
>
> **Pelajaran: keputusan desain (weak entity) sekaligus merupakan keputusan performa.**

**Optimasi 3 — Index pada `journal_subject(subject_id)`**

Seq Scan pada 6.703 baris junction berubah menjadi Bitmap Index Scan. Percepatan moderat (2,2×) karena bagian dominan adalah nested loop join ke `journal` (4.602 buffer) yang sudah menggunakan `journal_pkey`.

---

## 8. Struktur Repository

```
Seleksi-2026-Tugas-1/
├── Data Scraping/
│   ├── src/
│   │   ├── parser.py                  # Parsing HTML → dict (18 doctest)
│   │   ├── scraper_convergent.py      # Convergent crawler
│   │   ├── seed_state.py              # Bootstrap dari cache
│   │   ├── split_convergent.py        # Normalisasi → JSON per-entitas
│   │   ├── scrape_batch2.py           # Scrape batch kedua
│   │   └── load_batch2.py             # Load snapshot batch 2
│   ├── tools/                         # Script diagnosis (dokumentasi proses)
│   ├── tests/fixture_card.html        # Fixture uji parser
│   └── data/                          # 7 file JSON
│
├── Data Storing/
│   ├── design/  erd.png, relational.png
│   ├── src/     schema.sql, load.py, verify.sql, optimization.sql
│   ├── export/  sinta_db.sql
│   └── screenshots/                   # 18 screenshot
│
├── Data Warehouse/
│   ├── design/  warehouse_star_schema.png
│   ├── src/     warehouse_schema.sql, warehouse_load.py, warehouse_queries.sql
│   ├── export/  sinta_dw.sql
│   └── screenshots/                   # 6 screenshot
│
├── .gitignore
├── requirements.txt
└── README.md
```

---

## 9. Penggunaan AI

Proyek ini menggunakan bantuan AI (Claude, Anthropic).

### Bagian yang dibantu AI

- **Diagnosis masalah teknis** — identifikasi unstable pagination dan perancangan convergent crawling
- **Penulisan kode** — boilerplate scraper, DDL SQL, script ETL
- **Identifikasi edge case data** — angka format Indonesia, ISSN `"0"`, URL `"#!"`
- **Desain star schema** — struktur fact/dimension, aturan semi-additive measure
- **Penyusunan dokumentasi README**

### Bagian yang dikerjakan sendiri

- **Pemilihan topik** dan verifikasi legalitas sumber
- **Inspeksi DevTools** untuk menemukan struktur HTML SINTA — nama CSS class (`list-item`, `affil-name`, `profile-id`, `stat-prev`, `pr-num`) tidak dapat ditebak AI dan harus diambil manual
- **Menjalankan, men-debug, dan memvalidasi** setiap tahap di mesin lokal
- **Keputusan akhir desain database** — termasuk mengubah `metric_snapshot` menjadi weak entity dan menambahkan relasi `publisher → journal`
- **Pembuatan seluruh diagram** ERD, relasional, dan star schema
- **Interpretasi temuan analitik**

### Refleksi

AI mempercepat identifikasi masalah yang mudah terlewat — khususnya unstable pagination, yang **melaporkan dirinya sebagai sukses** (semua angka validasi cocok sempurna) padahal 22% data hilang.

Namun setiap solusi tetap harus **diverifikasi terhadap data nyata**. Beberapa asumsi AI terbukti salah dan baru ketahuan saat dijalankan:

- Selector CSS yang ditebak (`journal-meta`, `stat-prof`) ternyata salah; nama sebenarnya (`profile-id`, `stat-prev`) baru diketahui setelah inspeksi DevTools manual
- Strategi POST accreditation filter diprediksi berhasil, ternyata diabaikan server
- Path file pada script batch 2 salah, menyebabkan kehilangan hasil crawl 2 jam pertama
- Klaim bahwa jurnal tanpa link Google Scholar tidak memiliki metrik ternyata salah untuk 68% kasus — baru ketahuan setelah query verifikasi dijalankan

Pelajaran terpenting: **AI berguna untuk mempercepat eksplorasi, tetapi verifikasi empiris tidak dapat didelegasikan.**

---

## 10. Referensi

### Library

| Library | Versi | Kegunaan |
|---|---|---|
| [requests](https://requests.readthedocs.io/) | 2.32.3 | HTTP client |
| [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) | 4.12.3 | HTML parsing |
| [psycopg2-binary](https://www.psycopg.org/) | 2.9.12 | PostgreSQL adapter |

### Sumber Data

- **SINTA (Science and Technology Index)**, Kemdiktisaintek RI
- URL: https://sinta.kemdiktisaintek.go.id/journals
- Tanggal akses: 13 Juli 2026 (batch 1), 17 Juli 2026 (batch 2)
- `robots.txt`: HTTP 404 — tidak ada larangan crawling
- API publik: tidak tersedia

### Materi Rujukan

- Silberschatz, A., Korth, H. F., Sudarshan, S. *Database System Concepts*, 7th ed.
- Materi kuliah IF2140 Pemodelan Basis Data
- Kimball, R. *The Data Warehouse Toolkit* — pola bridge table dan surrogate "Unknown" member