# Seleksi Asisten Lab Basis Data 2026: Tugas 1 (ETL Project)

**Data Jurnal Ilmiah Indonesia Berdasarkan Peringkat Akreditasi SINTA, Afiliasi Penerbit, dan Metrik Sitasi**

---

## Author

| | |
|---|---|
| **Nama** | Illona Nasywa Hannum |
| **NIM** | 18224081 |
| **Sumber Data** | [SINTA: Science and Technology Index](https://sinta.kemdiktisaintek.go.id/journals) |
| **DBMS** | PostgreSQL 18.3 |

---

## Daftar Isi

## Daftar Isi

1. [Deskripsi Proyek](#1-deskripsi-proyek)
2. [Etika Data Scraping](#2-etika-data-scraping)
3. [Step 1: Data Scraping](#3-step-1-data-scraping)
4. [Pipeline ETL dan Transformasi Data](#4-pipeline-etl-dan-transformasi-data)
5. [Step 2: Data Modeling](#5-step-2-data-modeling)
6. [Translasi ERD ke Relasional (Detail per Tabel)](#6-translasi-erd-ke-relasional-detail-per-tabel)
7. [Daftar Asumsi](#7-daftar-asumsi)
8. [Data Storing](#8-data-storing)
9. [Bonus: Data Warehouse](#9-bonus-data-warehouse)
10. [Bonus: Automated Scheduling](#10-bonus-automated-scheduling)
11. [Bonus: Query Optimization](#11-bonus-query-optimization)
12. [Struktur Repository](#12-struktur-repository)
13. [Penggunaan AI](#13-penggunaan-ai)
14. [Referensi](#14-referensi)

---

## 1. Deskripsi Proyek

Proyek ini melakukan ETL (Extract, Transform, Load) terhadap data jurnal ilmiah Indonesia yang terdaftar di **SINTA (Science and Technology Index)**, portal resmi Kementerian Pendidikan Tinggi, Sains, dan Teknologi RI.

Cakupan data: 15.448 jurnal beserta afiliasi penerbit, tingkat akreditasi (S1–S6), status indeksasi (Scopus/Garuda), bidang keilmuan, dan metrik sitasi (impact, h5-index, citations, citations 5yr) dari 3 batch scraping pada tanggal berbeda.

### Mengapa topik ini?

1. Legalitas terverifikasi Pemeriksaan `https://sinta.kemdiktisaintek.go.id/robots.txt` mengembalikan **HTTP 404**, tidak ada larangan crawling. SINTA juga tidak memiliki Terms of Service yang melarang scraping.

2. Struktur relasional kaya. Data memiliki relasi 1:N, M:N, dan atribut temporal memadai untuk ERD bermakna.

3. Server-side rendered SINTA menyajikan HTML lengkap tanpa JavaScript, sehingga dapat di-scrape dengan `requests` tanpa melanggar aturan "dilarang menggunakan API".

4. Data berubah antar-waktu Metrik sitasi diperbarui berkala, memungkinkan bonus scheduling dengan perubahan data yang nyata.

### Mengapa PostgreSQL?

- Mendukung `CHECK` dengan **regex** (validasi format ISSN)
- Mendukung `TIMESTAMPTZ` dengan zona waktu (penting untuk time-series lintas batch)
- Mendukung berbagai perilaku `ON DELETE` (`CASCADE`, `SET NULL`, `RESTRICT`)
- Mendukung trigger PL/pgSQL
- Fitur analitik (`FILTER`, CTE, window function) untuk data warehouse

---

## 2. Etika Data Scraping

### Sumber yang dipertimbangkan dan ditolak

| Sumber | Alasan penolakan |
|--------|------------------|
| Circle Chart (K-pop) | Footer situs eksplisit melarang *text and data mining* (TDM) |
| Discogs| ToS eksplisit melarang *"data mining, robots, scraping, harvesting"* |
| BMKG | Menyediakan API resmi, dilarang oleh spesifikasi tugas |
| Hanteo, Ktown4u | Single-Page Application; data hanya via API internal |
| PDDIKTI | React SPA, dan memuat data pribadi mahasiswa |

### Praktik yang diterapkan

| Praktik | Implementasi |
|---|---|
| User-Agent jujur | `SintaAcademicScraper/1.0 (Seleksi Asisten Lab Basis Data ITB 2026; mailto:18224081@std.stei.itb.ac.id)` (tidak menyamar sebagai browser) |
| Rate limiting | Delay 1,2 detik + jitter acak 0–0,3 detik |
| Exponential backoff | Retry hingga 5× dengan jeda 2ⁿ detik (maks 30s) |
| Cache lokal | Halaman disimpan ke disk agar debugging tidak menembak server berulang |
| Off-peak scheduling | Task terjadwal pukul 02:00 |

---

## 3. Step 1: Data Scraping

### 3.1 Tools

| Library | Versi | Fungsi |
|---------|-------|--------|
| `requests` | 2.32.3 | HTTP client |
| `beautifulsoup4` | 4.12.3 | Parsing HTML via CSS selector |
| `re`, `json` | stdlib | Ekstraksi pola & serialisasi |
| `psycopg2-binary` | 2.9.12 | PostgreSQL adapter |

### 3.2 Cara menjalankan

```bash
cd "Data Scraping/src"
pip install -r ../../requirements.txt

python seed_state.py          # bootstrap dari cache (tanpa network)
python scraper_convergent.py  # convergent crawl
python split_convergent.py    # normalisasi → JSON per-entitas
```

### 3.3 Temuan Kritis: Unstable Pagination

Crawl pertama menghasilkan 15.453 kartu, sama persis dengan total resmi SINTA, dan keenam tingkat akreditasi cocok sempurna. Validasi berbasis total menyatakan sukses.

Namun pemeriksaan keunikan mengungkap hanya 12.071 jurnal unik. Sebanyak 3.382 jurnal (22%) tidak pernah ter-scrape, dan celahnya tertutup oleh duplikat. Hal tersebut disebabkan karena SINTA mengurutkan listing berdasarkan Impact, metrik yang berubah terus-menerus. Pengukuran pada halaman ke-50:

```
t =  0 detik : [9291, 6740, 953, ..., 2867, 873]
t = 30 detik : [9291, 6740, 953, ..., 2867, 873]   → 10/10 identik
t = 60 detik : [9291, 6740, 953, ..., 2867, 329]   →  9/10 identik
```

#### Pendekatan yang diuji dan gagal

| # | Pendekatan | Hasil |
|---|---|---|
| 1 | GET sort parameters (8 kandidat) | Diabaikan, sorting ternyata form POST (`changesort=1, sort=1..5`) |
| 2 | Page-size parameters | Terkunci di 10 kartu/halaman |
| 3 | POST accreditation filter | Diabaikan server; partisi S1 mengembalikan 431 alih-alih 268 |

#### Solusi: Convergent Crawling

| Pass | Jurnal baru | Total | Sisa |
|-----:|------------:|------:|-----:|
| seed | — | 12.071 | 3.382 |
| 1 | +2.151 | 14.222 | 1.231 |
| 2 | +805 | 15.027 | 426 |
| 3 | +278 | 15.305 | 148 |
| 4 | +101 | 15.406 | 47 |
| 5 | +35 | 15.441 | 12 |
| 6 | +7 | **15.448** | 5 |

Hasil: 15.448 jurnal unik (99,97%), 0 duplikat. Validasi berbasis agregat adalah *necessary but not sufficient*. Hanya pemeriksaan keunikan yang menangkap kegagalan ini.

### 3.4 Struktur File JSON

| File | Isi | Baris |
|------|-----|------:|
| `journals.json` | Entitas jurnal + atribut | 15.448 |
| `affiliations.json` | Afiliasi/penerbit unik | 2.013 |
| `subject_areas.json` | Bidang keilmuan | 10 |
| `journal_subject.json` | Junction M:N jurnal↔bidang | 6.703 |
| `journal_indexing.json` | Junction M:N jurnal↔indeks | 15.398 |
| `metric_snapshots_20260713.json` | Metrik batch 1 | 15.448 |
| `metric_snapshots_20260717.json` | Metrik batch 2 | 15.018 |
| `metric_snapshots_20260721.json` | Metrik batch 3 | 14.991 |

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

**Penjelasan tiga kolom URL:**

| Kolom | Menunjuk ke | Fungsi |
|---|---|---|
| `sinta_url` | Halaman profil di SINTA | *Traceability*, bukti asal data tiap baris |
| `website` | Situs resmi jurnal | Akses artikel |
| `google_scholar` | Profil jurnal di Google Scholar | **Sumber asli** metrik sitasi yang ditampilkan SINTA |

### 3.5 Karakteristik Data (Terverifikasi)

Nilai NULL, bukan kegagalan pipeline, melainkan properti sumber:

| Kolom | NULL | % | Interpretasi |
|---|---:|---:|---|
| `p_issn` | 4.317 | 27,9% | Jurnal *online-only*, tidak pernah terbit cetak |
| `e_issn` | 81 | 0,5% | Jurnal cetak tanpa versi elektronik |
| `affiliation_id` | 1.941 | 12,6% | Afiliasi tidak dicantumkan SINTA |
| `google_scholar` | 2.561 | 16,6% | Link profil tidak dirender (`href="#!"`) |
| `website` | 8 | 0,05% | Jumlah terlalu kecil untuk pola bermakna |
| `accreditation_label` | 1 | 0,006% | Sesuai chart SINTA: "Not Accredited: 1" |

Ketiadaan link Google Scholar tidak berkorelasi dengan ketiadaan metrik. Dari 2.561 jurnal tanpa link, 1.744 (68%) tetap memiliki data sitasi, sebagian bernilai tinggi (mis. *Gadjah Mada International Journal of Business*: 36.213 sitasi, h5-index 74). SINTA menyimpan metrik hasil sinkronisasi sebelumnya meskipun tautan profil tidak ditampilkan. Sehingga, kolom metrik terisi 100%, tidak ada NULL pada `impact`, `h5_index`, `citations`, maupun `citations_5yr`.

![Proof](Data%20Storing/screenshots/05_sparsitas_subject.png)

---

## 4. Pipeline ETL dan Transformasi Data

Bab ini menjelaskan alur ETL secara menyeluruh, dari HTML mentah hingga baris tabel di PostgreSQL, beserta seluruh transformasi yang terjadi di antaranya. Transformasi berikut merupakan bagian Transform dalam pipeline dan tidak terlihat pada ERD maupun diagram relasional, sehingga perlu didokumentasikan tersendiri.

### 4.1 Alur Tiga Tahap

```
        EXTRACT                    TRANSFORM                      LOAD
   ┌─────────────────┐      ┌──────────────────────┐      ┌─────────────────┐
   │ HTML SINTA      │      │ parser.py            │      │ load.py         │
   │ 1.546 halaman   │ ───► │ split_convergent.py  │ ───► │ load_batch2.py  │
   │ listing jurnal  │      │                      │      │                 │
   └─────────────────┘      └──────────────────────┘      └─────────────────┘
          │                           │                            │
          ▼                           ▼                            ▼
     cache/*.html              data/*.json                  PostgreSQL
     (arsip mentah)          (8 file entitas)              (11 tabel)
```

| Tahap | Script | Keluaran | Prinsip |
|---|---|---|---|
| Extract | `scraper_convergent.py` | `cache/*.html` | Merekam sumber apa adanya, tanpa interpretasi |
| Transform | `parser.py`, `split_convergent.py` | `data/*.json` | Membersihkan, menormalisasi, memisah per entitas |
| Load | `load.py`, `load_batch2.py` | Tabel PostgreSQL | Upsert idempoten dengan constraint sebagai penjaga |

Pemisahan ini disengaja. File JSON hasil tahap Transform tetap menyimpan bentuk yang dekat dengan sumber, misalnya kolom boolean `is_scopus`, sementara normalisasi penuh menjadi relasi M:N baru terjadi saat Load. Dengan demikian jejak bentuk asli data tidak hilang dan proses dapat ditelusuri ulang.

### 4.2 Boolean menjadi Relasi M:N

Di JSON:

```json
{
  "journal_id": 671,
  "is_scopus": true,
  "is_garuda": true
}
```

Di database, dua baris pada `journal_indexing`:

```
journal_id | body_id
-----------+---------
    671    |    1      (Scopus)
    671    |    2      (Garuda)
```

Data mentah SINTA merepresentasikan indeksasi sebagai badge biner pada kartu jurnal:

```html
<span class="num-stat scopus-indexed">Scopus Indexed</span>
<span class="num-stat garuda-indexed">Garuda Indexed</span>
```

Parser merekamnya apa adanya sebagai boolean karena itulah bentuk sumbernya. Pada model relasional keduanya dinormalisasi menjadi relasi M:N dengan tiga alasan.

Pertama, dua kolom boolean sebenarnya merepresentasikan satu konsep, yaitu badan indeks mana yang mencakup jurnal tersebut. Memisahkannya menjadi kolom terpisah adalah denormalisasi.

Kedua, desain boolean tidak scalable. Penambahan badan indeks baru seperti DOAJ atau Web of Science memerlukan `ALTER TABLE ADD COLUMN`. Pada desain relasional cukup `INSERT INTO indexing_body`.

Ketiga, query menjadi lebih ekspresif. Pertanyaan "jurnal yang terindeks di lebih dari satu badan" cukup ditulis `GROUP BY ... HAVING COUNT(*) > 1`. Dengan boolean, kondisi eksplisit harus ditulis untuk setiap kombinasi.

Implementasi pada `split_convergent.py`:

```python
if r["is_scopus"]:
    journal_indexing.add((jid, "Scopus"))
if r["is_garuda"]:
    journal_indexing.add((jid, "Garuda"))
```

Menghasilkan 15.398 baris junction dari 15.448 jurnal. Angka lebih kecil karena 255 jurnal tidak terindeks sama sekali, sementara 205 jurnal menyumbang dua baris masing-masing.

### 4.3 Label Akreditasi menjadi Foreign Key

Di JSON:

```json
{
  "accreditation_label": "S1",
  "accreditation_rank": 1
}
```

Di database:

```sql
journal.accreditation_id = 1   -- FK ke tabel accreditation
```

JSON menyimpan label string karena itulah yang terbaca dari badge HTML. Database menyimpan foreign key ke lookup table.

Proses translasi pada `load.py`:

```python
cur.execute("SELECT accreditation_id, label FROM accreditation")
accred_id_by_label = {lab: aid for aid, lab in cur.fetchall()}
aid = accred_id_by_label.get(label)
```

Penanganan kasus khusus: satu jurnal (ID 5986, *Budapest International Research and Critics Institute*) tidak memiliki badge akreditasi sama sekali. Loader memetakannya ke `NULL`, bukan membuang barisnya, karena itu akan merusak total 15.448.

### 4.4 Angka Format Indonesia menjadi Numerik

Di HTML SINTA:

```
Impact: 104,00      koma sebagai pemisah DESIMAL
Citations: 14.902   titik sebagai pemisah RIBUAN
```

Di database:

```
impact    = 104.00
citations = 14902
```

Transformasi ini merupakan yang paling berisiko dalam seluruh pipeline. `float("14.902")` di Python tidak menghasilkan error, melainkan mengembalikan `14.902` yang salah 1000 kali lipat dari nilai sebenarnya. Bug semacam ini tidak akan pernah terdeteksi tanpa penanganan eksplisit karena tidak ada exception yang dilempar.

Implementasi pada `parser.py`, terverifikasi dengan 18 doctest:

```python
def parse_id_number(raw):
    if "," in s:
        s = s.replace(".", "").replace(",", ".")   # koma sebagai desimal
    else:
        s = s.replace(".", "")                     # titik sebagai ribuan
    return float(s)
```

Sebagai lapisan pertahanan kedua, constraint `CHECK (citations_5yr <= citations)` pada tabel `metric_snapshot` akan gagal jika parsing menghasilkan nilai yang tidak konsisten.

### 4.5 Sentinel Value menjadi NULL

SINTA menggunakan nilai *placeholder* untuk data yang tidak tersedia. Nilai tersebut tampak valid namun sebenarnya bukan data:

| Sumber | Nilai mentah | Setelah preprocessing | Alasan |
|---|---|---|---|
| P-ISSN | `"0"` | `NULL` | Sentinel "tidak ada ISSN cetak", bukan nomor ISSN |
| Google Scholar | `href="#!"` | `NULL` | Link mati, bukan URL |

Jika tidak dibersihkan, nilai `"0"` akan melanggar `CHECK (p_issn ~ '^[0-9]{7}[0-9X]$')` dan membatalkan seluruh transaksi load. Satu baris rusak akan menggagalkan 15.448 baris lainnya.

### 4.6 ID Tersembunyi dalam URL menjadi Primary Key

`journal_id` dan `affiliation_id` tidak muncul sebagai teks di halaman SINTA. Keduanya hanya ada di dalam atribut `href`:

```html
<a href="https://sinta.kemdiktisaintek.go.id/journals/profile/671">
```

Ekstraksi:

```python
re.search(r"/(\d+)/?$", url)   # menghasilkan 671
```

Kedua ID ini menjadi primary key dan foreign key seluruh skema. Tanpa ekstraksi ini, tidak ada cara mencocokkan jurnal antar-batch scraping, dan bonus scheduling tidak dapat diimplementasikan.

### 4.7 Deduplikasi Subject Area

Beberapa kartu jurnal mencantumkan subject area yang sama berulang. Parser menerapkan deduplikasi dengan mempertahankan urutan asli:

```python
subjects = list(dict.fromkeys(raw))   # bukan set(), agar urutan terjaga
```

Deduplikasi tingkat kartu ini bekerja bersama dengan deduplikasi tingkat crawl pada `split_convergent.py`, yang menangani kasus jurnal yang sama ter-scrape berkali-kali akibat unstable pagination sebagaimana dijelaskan pada [bagian 3.3](#33-temuan-kritis-unstable-pagination).

### 4.8 Metadata Audit

Tiga kolom tidak berasal dari SINTA melainkan ditambahkan sistem untuk keperluan pelacakan:

| Kolom | Tabel | Asal |
|---|---|---|
| `first_seen_at` | `journal` | Waktu jurnal pertama kali teramati |
| `last_seen_at` | `journal` | Waktu terakhir teramati, diperbarui trigger |
| `captured_at` | `metric_snapshot` | Timestamp batch scraping |

`captured_at` berperan ganda: sebagai discriminator weak entity sekaligus dimensi waktu untuk analisis tren pada data warehouse.

### 4.9 Ringkasan Transformasi

| # | Transformasi | Dari | Ke | Risiko jika dilewati |
|---|---|---|---|---|
| 1 | Boolean ke M:N | `is_scopus`, `is_garuda` | `journal_indexing` | Denormalisasi, tidak scalable |
| 2 | Label ke FK | `"S1"` | `accreditation_id = 1` | Redundansi string, sulit menjaga konsistensi |
| 3 | Locale numerik | `"14.902"` | `14902` | Nilai salah 1000× tanpa error |
| 4 | Sentinel ke NULL | `"0"`, `"#!"` | `NULL` | Transaksi load gagal total |
| 5 | ID dari URL | `/profile/671` | `journal_id = 671` | Tidak ada kunci untuk deduplikasi |
| 6 | Deduplikasi subject | subject berulang | himpunan unik | Baris junction ganda |
| 7 | Metadata audit | (tidak ada) | timestamp | Tidak dapat melacak perubahan antar-batch |

---

## 5. Step 2: Data Modeling

### 5.1 ERD Konseptual

![ERD](Data%20Storing/design/erd.png)

Notasi Silberschatz (*Database System Concepts*, 7th ed.), sesuai materi IF2140:

| Simbol | Arti |
|---|---|
| Persegi panjang | Entity set |
| Persegi ganda | Weak entity set |
| Belah ketupat | Relationship set |
| Belah ketupat ganda | Identifying relationship |
| Garis bawah penuh | Primary key |
| Garis bawah putus-putus | Discriminator (partial key). Karena keterbatasan tools yang digunakan (draw.io), discriminator pada weak entity ditandai dengan garis bawah penuh tanpa label "PK" |
| Panah (→) | Sisi "one" pada relasi many-to-one |
| Tanpa panah | Many-to-many |
| Garis ganda | Total participation |

9 entity set dan 8 relationship set:

| Relasi | Entitas | Kardinalitas | Partisipasi |
|---|---|---|---|
| memiliki | AFFILIATION → JOURNAL | many-to-one | parsial (1.941 tanpa afiliasi) |
| diberi peringkat | ACCREDITATION → JOURNAL | many-to-one | parsial (1 tanpa akreditasi) |
| tercakup | JOURNAL ↔ SUBJECT_AREA | many-to-many | parsial (76,1% tanpa subject) |
| terindeks | JOURNAL ↔ INDEXING_BODY | many-to-many | parsial (255 tanpa indeks) |
| diukur | JOURNAL → METRIC_SNAPSHOT | one-to-many | total (identifying) |
| bekerja pada | AFFILIATION → AUTHOR | many-to-one | parsial (tabel kosong) |
| terdaftar pada | DEPARTMENT → AUTHOR | many-to-one | parsial (tabel kosong) |
| memiliki program | AFFILIATION ↔ DEPARTMENT | many-to-many | parsial (tabel kosong) |

### 5.2 Weak Entity: METRIC_SNAPSHOT

`METRIC_SNAPSHOT` memenuhi seluruh karakteristik weak entity:

1. Tidak memiliki primary key sendiri, sebuah pengukuran hanya bermakna dalam konteks jurnal yang diukur
2. Existence-dependent pada `JOURNAL` (`ON DELETE CASCADE`)
3. Discriminator `captured_at`, hanya unik dalam satu journal, dua jurnal berbeda boleh memiliki `captured_at` sama
4. Partisipasi total dalam identifying relationship diukur

Detail implementasi pada [bagian 6.9](#69-metric_snapshot-weak-entity).

### 5.3 Fitur ERD Lanjutan yang Tidak Digunakan

| Fitur | Alasan |
|---|---|
| Generalization/Specialization (ISA) | Tidak ada subtipe jurnal dengan atribut berbeda. Status indeksasi (Scopus/Garuda) dimodelkan sebagai relasi M:N, bukan subtipe, karena satu jurnal dapat terindeks di beberapa badan sekaligus. Terbukti: 205 jurnal terindeks Scopus dan Garuda |
| Aggregation | Tidak ada relationship set yang berpartisipasi dalam relationship set lain |
| Multivalued attribute | Semua atribut jamak sudah dimodelkan sebagai entity set terpisah dengan relasi M:N |

Domain data SINTA bersifat entitas datar dengan relasi eksplisit, sehingga model E-R dasar sudah memadai. Memaksakan konstruksi lanjutan akan menghasilkan *over-engineering*.

### 5.4 Diagram Relasional

![Relational Diagram](Data%20Storing/design/relational.png)

11 tabel hasil translasi dari 9 entity set. Selisih dua tabel berasal dari tiga relasi many-to-many yang menghasilkan junction table, dikurangi satu karena relasi 1:N tidak menghasilkan tabel baru melainkan kolom foreign key.

#### Asumsi dalam penyusunan diagram

Diagram ini disusun dengan beberapa asumsi yang tidak dapat diturunkan langsung dari data hasil scraping, melainkan dari pengamatan terhadap struktur situs sumber.

**Asumsi struktural yang diverifikasi ke sumber.** Tiga asumsi berikut dipastikan dengan membuka langsung halaman SINTA yang bersangkutan:

| Asumsi | Verifikasi |
|---|---|
| SINTA memiliki entitas author dengan identifier tersendiri | Halaman `/authors/profile/5980682` menampilkan SINTA ID, afiliasi, departemen, dan metrik h-index |
| Departemen dimiliki banyak afiliasi, sehingga relasinya M:N | Halaman `/departments`: "Administrasi Bisnis (S1)" dengan CODE 63211 terdaftar pada 111 afiliasi |
| Departemen memiliki atribut jenjang dan kode prodi | Halaman `/departments` menampilkan level D3/S1/S2 dan CODE untuk setiap entri |

**Asumsi yang digunakan namun belum dapat dipastikan.** Dua asumsi berikut diterapkan berdasarkan pola yang konsisten pada entitas lain:

| Asumsi | Dasar | Konsekuensi jika berbeda |
|---|---|---|
| `author_id` bersifat stabil antar-waktu | ID pada `journal` dan `affiliation` terbukti stabil, sehingga wajar mengasumsikan pola yang sama berlaku pada author | Natural key perlu diganti surrogate. Tidak berdampak karena tabel kosong |
| Kombinasi `(name, level)` cukup untuk mengidentifikasi departemen | Nama prodi dan jenjang bersama-sama membentuk identitas yang terlihat unik pada halaman `/departments` | Constraint `UNIQUE` perlu ditinjau. Tidak berdampak karena tabel kosong |

**Batas pemodelan yang ditetapkan.** Tiga hal sengaja tidak dimodelkan meskipun ada di domain:

| Hal | Alasan |
|---|---|
| Relasi author ke journal | Hubungan bersifat tidak langsung melalui artikel. Data artikel tidak tersedia pada halaman yang di-scrape, sehingga relasi ini tidak dapat direpresentasikan tanpa mengarang struktur |
| Hierarki afiliasi tiga tingkat (prodi, fakultas, universitas) | Data tersirat dalam string `affiliation.name` namun formatnya tidak konsisten. Parsing berisiko menghasilkan data salah, lihat [bagian 6.10](#610-department) |
| Atribut afiliasi seperti kode institusi, singkatan, dan lokasi | Terlihat pada halaman `/affiliations` namun tidak tersedia pada halaman listing jurnal yang menjadi sumber scraping |

**Prinsip yang dipegang.** Skema hanya memodelkan struktur yang dapat diverifikasi ke sumber. Kolom atau relasi yang bersifat antisipatif tidak ditambahkan, kecuali dinyatakan secara eksplisit beserta dasar penalarannya.

---

## 6. Translasi ERD ke Relasional (Detail per Tabel)

Bagian ini menjelaskan setiap tabel dalam skema relasional: dari mana asalnya di ERD, aturan translasi apa yang diterapkan, dan keputusan desain yang menyertainya.

### Ringkasan translasi

| # | Tabel relasional | Asal di ERD | Aturan translasi |
|---|---|---|---|
| 1 | `accreditation` | Entity set ACCREDITATION | Entity ke tabel |
| 2 | `subject_area` | Entity set SUBJECT_AREA | Entity ke tabel |
| 3 | `indexing_body` | Entity set INDEXING_BODY | Entity ke tabel |
| 4 | `affiliation` | Entity set AFFILIATION | Entity ke tabel |
| 5 | `author` | Entity set AUTHOR + 2 relasi 1:N | Entity ke tabel; relasi 1:N ke FK |
| 6 | `journal` | Entity set JOURNAL + 2 relasi 1:N | Entity ke tabel; relasi 1:N ke FK di sisi "many" |
| 7 | `journal_subject` | Relasi M:N tercakup | M:N ke junction table |
| 8 | `journal_indexing` | Relasi M:N terindeks | M:N ke junction table |
| 9 | `metric_snapshot` | Weak entity METRIC_SNAPSHOT | Weak entity ke tabel dengan composite PK |
| 10 | `department` | Entity set DEPARTMENT | Entity ke tabel |
| 11 | `affiliation_department` | Relasi M:N memiliki program | M:N ke junction table |

9 entity set menjadi 11 tabel. Selisih 2 berasal dari tiga relasi M:N yang menghasilkan junction table.

---

### 6.1 `accreditation`

Asal ERD: Entity set `ACCREDITATION`

```sql
CREATE TABLE accreditation (
    accreditation_id SERIAL PRIMARY KEY,
    label            VARCHAR(20) NOT NULL UNIQUE,
    rank_numeric     SMALLINT,
    CONSTRAINT chk_rank_range
        CHECK (rank_numeric IS NULL OR rank_numeric BETWEEN 1 AND 6)
);
```

Aturan translasi: Entity set ke tabel. Atribut `accreditation_id` (PK), `label`, `rank_numeric` menjadi kolom.

**Keputusan desain:**

1. Surrogate key `SERIAL`, dengan natural key tetap dijaga.

Tabel ini memiliki natural key yang valid, yaitu kolom `label` dengan nilai "S1" sampai "S6", "Cancelled", dan "Not Accredited". Natural key tersebut tetap dijaga melalui constraint `UNIQUE`, sehingga tidak mungkin ada dua baris dengan label sama.

Untuk tabel sekecil ini (8 baris), penghematan penyimpanan dari penggunaan `INTEGER` dibanding `VARCHAR(20)` tidak signifikan. Pemilihan surrogate key lebih didasarkan pada dua pertimbangan praktis.

Pertama, stabilitas terhadap perubahan label. Jika Kemdiktisaintek mengubah penamaan tingkat akreditasi, misalnya "S1" menjadi "Sinta 1", perubahan pada desain surrogate key hanya menyentuh satu baris pada tabel `accreditation`. Pada desain natural key, PostgreSQL menyediakan `ON UPDATE CASCADE` yang menangani hal ini secara otomatis, sehingga keunggulan ini bersifat relatif.

Kedua, konsistensi pola dengan tabel lookup lain dalam skema.

Perlu dicatat bahwa alternatif menggunakan `label` sebagai primary key sama-sama valid, dan justru menghasilkan query yang lebih terbaca karena tidak memerlukan join untuk menyaring berdasarkan tingkat akreditasi. Pilihan ini merupakan preferensi desain, bukan keharusan teknis.

2. `rank_numeric` nullable. Ini yang tidak eksplisit terlihat di ERD. Tingkat akreditasi tidak semuanya numerik:

| label | rank_numeric | Alasan |
|---|---|---|
| S1–S6 | 1–6 | Peringkat numerik |
| `Cancelled` | NULL | Bukan peringkat, melainkan status |
| `Not Accredited` | NULL | Bukan peringkat |

Jika `rank_numeric` dibuat `NOT NULL`, dua status terakhir mustahil disimpan. Inilah alasan `ACCREDITATION` dimodelkan sebagai lookup table dan bukan sekadar kolom `INTEGER` di `journal`.

3. Data seed 8 baris. Diisi langsung dalam `schema.sql`, bukan hasil scraping, karena ini adalah domain nilai yang tetap, bukan data observasi. Tingkat akreditasi SINTA merupakan aturan resmi pemerintah yang sudah diketahui sebelum scraping dimulai, berbeda dengan `subject_area` yang jumlahnya baru diketahui setelah scraping selesai.

---

### 6.2 `subject_area`

Asal ERD: Entity set `SUBJECT_AREA`

```sql
CREATE TABLE subject_area (
    subject_id SERIAL PRIMARY KEY,
    name       VARCHAR(60) NOT NULL UNIQUE
);
```

Aturan translasi: Entity set ke tabel.

**Keputusan desain:**

1. Surrogate key.

Natural key `name` dijaga dengan `UNIQUE` dan hanya berisi 10 nilai tetap.

Pertimbangan utama adalah ukuran junction table `journal_subject` yang menyimpan 6.703 baris. Dengan `INTEGER`, kolom `subject_id` menghabiskan sekitar 26 KB. Dengan `VARCHAR(60)`, penyimpanan dapat mencapai lebih dari 400 KB karena nama bidang seperti "Agriculture" atau "Engineering" akan diulang ribuan kali.

Pada skala ini penghematan mulai terasa, meskipun tetap tidak kritis untuk database berukuran total sekitar 20 MB. Selain itu, composite primary key `(journal_id, subject_id)` pada junction table akan menjadi jauh lebih besar jika salah satu komponennya berupa string, yang berdampak pada ukuran index dan kecepatan join.

2. `VARCHAR(60)`, nama terpanjang pada data aktual adalah "Agriculture" (11 karakter). Batas 60 dipilih agar aman.

3. 10 baris, diisi dari hasil scraping (bukan seed).

---

### 6.3 `indexing_body`

Asal ERD: Entity set `INDEXING_BODY`

```sql
CREATE TABLE indexing_body (
    body_id SERIAL PRIMARY KEY,
    name    VARCHAR(40) NOT NULL UNIQUE
);

INSERT INTO indexing_body (name) VALUES ('Scopus'), ('Garuda');
```

Aturan translasi: Entity set ke tabel.

**Keputusan desain:**

1. Surrogate key `body_id`.

Tabel ini hanya berisi dua baris, sehingga penghematan penyimpanan tidak menjadi pertimbangan. Pemilihan surrogate key murni untuk konsistensi pola dengan tabel lookup lain. Junction table `journal_indexing` menyimpan 15.398 baris, dan penggunaan `INTEGER` menjaga ukurannya tetap kecil.

Natural key `name` tetap dijaga dengan `UNIQUE`. Menggunakan `name` sebagai primary key akan sama efektifnya pada skala ini.

2. Data seed 2 baris. Sama seperti `accreditation`, ini domain nilai tetap yang diketahui dari struktur halaman SINTA sebelum scraping dimulai:

```html
<span class="num-stat scopus-indexed">Scopus Indexed</span>
<span class="num-stat garuda-indexed">Garuda Indexed</span>
```

3. Desain ini scalable. Jika SINTA menambah badan indeks baru:

| Desain | Perubahan yang diperlukan |
|---|---|
| Kolom boolean | `ALTER TABLE journal ADD COLUMN is_doaj BOOLEAN` |
| Tabel `indexing_body` | `INSERT INTO indexing_body VALUES ('DOAJ')` |

Desain kedua tidak mengubah struktur tabel.

---

### 6.4 `affiliation`

Asal ERD: Entity set `AFFILIATION`

```sql
CREATE TABLE affiliation (
    affiliation_id INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    sinta_url      TEXT
);
```

Aturan translasi: Entity set ke tabel.

**Keputusan desain:**

1. Natural key, bukan surrogate.

Berbeda dengan tabel lookup, tabel ini justru menghindari surrogate key.

`affiliation_id` menggunakan ID asli dari SINTA, diekstrak dari URL `/affiliations/profile/9` menjadi `9`. Keputusan ini didasarkan pada dua sifat ID tersebut: bersifat stabil karena ditetapkan oleh sistem SINTA dan tidak berubah antar-kunjungan, serta terjamin unik karena berfungsi sebagai identifier pada sistem asalnya.

Konsekuensi praktisnya terlihat pada proses scraping berulang. Ketika batch kedua dan ketiga dijalankan, afiliasi yang sama akan memiliki ID yang sama, sehingga `ON CONFLICT (affiliation_id) DO UPDATE` bekerja dengan benar tanpa menghasilkan duplikat.

Jika menggunakan `SERIAL`, setiap batch akan menghasilkan ID baru untuk afiliasi yang sebenarnya sama, dan pencocokan hanya dapat dilakukan melalui perbandingan string nama yang panjang dan rawan perbedaan penulisan.

2. `TEXT`, bukan `VARCHAR(n)`. Nama afiliasi bisa sangat panjang, contoh nyata (155 karakter):

```
"The Faculty of Tarbiya and Teacher Training, Universitas Islam Negeri
 Sunan Gunung Djati Bandung Associated with Persatuan Sarjana Pendidikan
 Islam Indonesia (PSPII)"
```

Membatasi panjang berisiko memotong data.

---

### 6.5 `author`

Asal ERD: Entity set `AUTHOR` + dua relasi 1:N (*bekerja pada*, *terdaftar pada*)

```sql
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
    CONSTRAINT fk_author_department
        FOREIGN KEY (department_id) REFERENCES department(department_id)
        ON DELETE SET NULL,

    CONSTRAINT chk_author_hindex CHECK (
        (scopus_h_index IS NULL OR scopus_h_index >= 0) AND
        (gs_h_index     IS NULL OR gs_h_index     >= 0)
    )
);
```

**Status: tabel tambahan yang sengaja dikosongkan.**

Spesifikasi tugas pada Step 2 poin 2 menyatakan: *"Peserta dipersilakan untuk menambahkan tabel lain yang sekiranya relevan atau berkaitan dengan tabel-tabel yang murni didapatkan dari proses data scraping."* Poin 4 sub-a kemudian menyatakan: *"Tabel tambahan yang dibuat pada poin 2 tidak perlu diisi dengan data (baik data dummy maupun data asli). Cukup dibiarkan kosong."*

Tabel `author` merupakan tabel tambahan sebagaimana dimaksud poin 2 tersebut. Relevansinya terhadap tabel hasil scraping terletak pada relasi ke `affiliation`, entitas yang memang diperoleh dari proses scraping. Sesuai poin 4 sub-a, tabel ini dibiarkan kosong.

Alasan teknis mengapa tidak dapat diisi: halaman `/authors` berada di luar cakupan scraping proyek ini yang hanya menyasar listing jurnal. Relasi author ke journal juga tidak dapat dimodelkan karena hubungannya bersifat tidak langsung melalui artikel, sementara data artikel tidak tersedia pada halaman yang di-scrape.

Struktur diturunkan dari halaman profil author. Contoh yang diverifikasi: `https://sinta.kemdiktisaintek.go.id/authors/profile/5980682`

| Elemen di SINTA | Kolom |
|---|---|
| SINTA ID (5980682) | `author_id` |
| Nama peneliti | `name` |
| Afiliasi (Universitas Negeri Padang) | `affiliation_id` |
| Departemen (Pendidikan Kimia S2) | `department_id` |
| Scopus H-index (25) | `scopus_h_index` |
| Google Scholar H-index (38) | `gs_h_index` |

Natural key: `author_id` menggunakan SINTA ID asli, konsisten dengan pola pada `journal` dan `affiliation`.

---

### 6.6 `journal`

Asal ERD: Entity set `JOURNAL` + dua relasi 1:N (*memiliki*, *diberi peringkat*)

```sql
CREATE TABLE journal (
    journal_id       INTEGER PRIMARY KEY,
    name             TEXT NOT NULL,
    p_issn           VARCHAR(20),
    e_issn           VARCHAR(20),
    affiliation_id   INTEGER,       -- FK dari relasi "memiliki"
    accreditation_id INTEGER,       -- FK dari relasi "diberi peringkat"
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

    CONSTRAINT chk_p_issn
        CHECK (p_issn IS NULL OR p_issn ~ '^[0-9]{7}[0-9X]$'),
    CONSTRAINT chk_e_issn
        CHECK (e_issn IS NULL OR e_issn ~ '^[0-9]{7}[0-9X]$'),
    CONSTRAINT chk_seen_order
        CHECK (last_seen_at >= first_seen_at)
);
```

Aturan translasi: Entity set ke tabel. Dua relasi many-to-one direalisasikan sebagai foreign key di sisi "many" (yaitu di `journal`, karena banyak jurnal merujuk satu afiliasi dan satu tingkat akreditasi).

**Keputusan desain:**

1. `journal_id` natural key dari SINTA.

`journal_id` diekstrak dari URL `/journals/profile/671` menjadi 671. Alasan pemilihannya sama dengan `affiliation`, yaitu stabilitas dan keunikan yang dijamin sistem sumber. Namun dampaknya jauh lebih besar karena tabel ini menjadi pusat seluruh skema.

Tanpa natural key, bonus scheduling tidak dapat diimplementasikan. Skenarionya sebagai berikut: batch pertama memuat 15.448 jurnal dengan `SERIAL` 1 sampai 15.448. Batch kedua memuat 15.018 jurnal, namun karena `SERIAL` selalu menghasilkan nilai baru, jurnal yang sama akan mendapat ID 15.449 dan seterusnya. Database akan berisi lebih dari 30.000 baris jurnal padahal jurnal uniknya hanya sekitar 15.448.

Pencocokan alternatif hanya dapat dilakukan melalui ISSN atau nama, yang keduanya bermasalah karena 27,9% jurnal tidak memiliki `p_issn` dan nama jurnal dapat berubah ejaan.

Dengan natural key, `ON CONFLICT (journal_id) DO UPDATE` langsung mengenali jurnal yang sama antar-batch. Hasilnya terbukti pada data: setelah tiga batch, jumlah baris `journal` tetap 15.448 sementara `metric_snapshot` bertambah menjadi 45.452.

2. Kedua FK nullable, mencerminkan partisipasi parsial pada ERD:

| FK | NULL | Alasan |
|---|---:|---|
| `affiliation_id` | 1.941 | SINTA tidak mencantumkan afiliasi untuk jurnal tersebut |
| `accreditation_id` | 1 | Satu jurnal tidak menampilkan badge akreditasi sama sekali |

Alternatifnya adalah membuang baris tersebut (kehilangan data) atau mengarang nilai (kebohongan dalam data). `NULL` adalah representasi jujur dari "SINTA tidak menampilkan informasi ini".

3. `ON DELETE` berbeda per FK, ini tidak terlihat di ERD dan merupakan keputusan semantik:

| FK | Perilaku | Alasan |
|---|---|---|
| `affiliation_id` | SET NULL | Jika afiliasi dihapus, jurnalnya tetap ada, hanya kehilangan informasi penerbitnya |
| `accreditation_id` | RESTRICT | Melarang penghapusan tingkat akreditasi yang masih dipakai. Menghapus "S1" akan merusak makna 268 jurnal |

4. `first_seen_at` dan `last_seen_at`, kolom ini tidak berasal dari data SINTA. Keduanya adalah metadata audit yang ditambahkan sistem untuk melacak kapan jurnal pertama kali dan terakhir kali teramati. `last_seen_at` diperbarui otomatis oleh trigger (lihat [bagian 8.2](#82-constraint-yang-diimplementasikan)).

5. `CHECK` regex ISSN. Validasi format 8 karakter (7 digit + digit/X) diterapkan di boundary database, bukan hanya di scraper. Prinsipnya: database tidak boleh mempercayai aplikasi yang menulisinya.

---

### 6.7 `journal_subject` (Junction Table)

Asal ERD: Relasi many-to-many *tercakup* antara `JOURNAL` dan `SUBJECT_AREA`

```sql
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
```

Aturan translasi: M:N ke junction table. Model relasional tidak dapat merepresentasikan relasi many-to-many secara langsung. Relasi diubah menjadi tabel baru yang memuat foreign key ke kedua entitas.

Tabel ini tidak ada di ERD. Junction table adalah artefak implementasi, bukan konsep. Di tingkat konseptual, yang ada hanyalah relasi M:N antara dua entity set.

**Keputusan desain:**

1. Composite PK `(journal_id, subject_id)`. Menjamin satu jurnal tidak dapat memiliki subject yang sama dua kali. Ini sekaligus indeks otomatis untuk join.

2. `ON DELETE CASCADE` di kedua FK. Jika jurnal atau bidang dihapus, baris relasinya ikut terhapus, karena relasi tidak bermakna tanpa kedua ujungnya.

3. Bukti relasi M:N nyata (dari data aktual):

| Jumlah subject | Jumlah jurnal |
|---:|---:|
| 1 | 1.993 |
| 2 | 907 |
| 3 | 464 |
| 4 | 221 |
| 5 | 82 |
| 6 | 14 |
| 7 | 9 |
| 8 | 3 |
| 9 | 1 |
| **10** | **3** |

Tiga jurnal tercakup dalam kesepuluh bidang keilmuan sekaligus, semuanya jurnal pengabdian masyarakat yang secara alami menerima artikel lintas disiplin:
- *International Journal of Community Service (IJCS)*
- *Teknosains : Jurnal Sains, Teknologi dan Informatika*
- *Multidiciplinary Output Research for Actual and International Issue (Morfai Journal)*

Menyimpan ini sebagai kolom bernilai jamak (mis. `VARCHAR` ber-koma) akan melanggar 1NF dan membuat query "semua jurnal bidang Education" menjadi full scan `LIKE '%Education%'`.

![Bukti M:N](Data%20Storing/screenshots/04_bukti_mn.png)

---

### 6.8 `journal_indexing` (Junction Table)

Asal ERD: Relasi many-to-many *terindeks* antara `JOURNAL` dan `INDEXING_BODY`

```sql
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
```

Aturan translasi: Sama seperti [bagian 6.7](#67-journal_subject-junction-table), M:N ke junction table. Tidak ada di ERD.

Bukti relasi M:N nyata:

| Profil | Jumlah jurnal |
|---|---:|
| Terindeks Garuda | 15.183 |
| Terindeks Scopus | 215 |
| **Terindeks keduanya** | **205** |
| Terindeks satu badan saja | 14.988 |
| Tidak terindeks | 255 |

205 jurnal yang terindeks di dua badan sekaligus membuktikan relasi ini benar-benar many-to-many, bukan many-to-one.

Transformasi dari boolean di JSON menjadi baris junction dijelaskan pada [bagian 4.2](#42-boolean-menjadi-relasi-mn).

![M:N indexing](Data%20Storing/screenshots/06_indexing.png)

---

### 6.9 `metric_snapshot` (Weak Entity)

Asal ERD: Weak entity `METRIC_SNAPSHOT` melalui identifying relationship *diukur*

```sql
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
    CONSTRAINT chk_5yr_lte_total CHECK (
        citations IS NULL OR citations_5yr IS NULL
        OR citations_5yr <= citations
    )
);
```

Aturan translasi: Weak entity ke tabel dengan composite primary key yang terdiri dari:
- Foreign key ke owner entity (`journal_id`)
- Discriminator (`captured_at`)

**Keputusan desain:**

1. Tanpa surrogate key.

Weak entity menurut definisinya tidak memiliki identifier sendiri; identitasnya berasal dari kombinasi owner entity dan discriminator. Memberikan surrogate key akan menjadikannya strong entity, yang tidak sesuai dengan sifat data.

Selain itu, tidak ada foreign key yang menunjuk ke `metric_snapshot`, sehingga identifier tunggal tidak memberi manfaat apa pun. Composite primary key `(journal_id, captured_at)` secara otomatis menghasilkan index yang berguna untuk query time-series, sebagaimana terlihat pada hasil optimasi di [bagian 11.3](#113-analisis).

2. Mengapa dipisah dari `journal`?

| Jika metrik disimpan sebagai kolom di `journal` | Jika dipisah sebagai `metric_snapshot` |
|---|---|
| Scrape ke-2 menimpa data ke-1 | Scrape ke-2 menambah baris |
| Hanya menyimpan kondisi terkini | Menyimpan histori lengkap |
| Analisis tren mustahil | Analisis tren langsung bisa |
| Bonus scheduling tidak dapat dibuktikan | Bonus scheduling terbukti dengan data |

Dengan kata lain: pemisahan ini mengubah database dari "foto" menjadi "film".

3. Composite PK sekaligus jaminan anti-redundansi.

Spesifikasi meminta "Pastikan tidak terdapat redundansi data pada DBMS." PK `(journal_id, captured_at)` menjamin hal itu di level database, bukan bergantung pada logika aplikasi. Menjalankan load dua kali dengan timestamp sama menghasilkan `ON CONFLICT DO NOTHING`, tanpa efek.

4. `CHECK (citations_5yr <= citations)`, constraint semantik yang tidak terlihat di ERD. Sitasi 5 tahun terakhir secara logis tidak mungkin melebihi sitasi sepanjang masa. Constraint ini juga berfungsi sebagai deteksi bug parser: jika angka locale Indonesia salah di-parse, kemungkinan besar constraint ini akan gagal.

5. `NUMERIC(10,2)` untuk impact, bukan `FLOAT`. Tipe floating-point memiliki galat pembulatan. `NUMERIC` menyimpan desimal secara eksak, penting karena `impact` adalah nilai terpublikasi yang harus tersimpan persis seperti aslinya.

---

### 6.10 `department`

Asal ERD: Entity set `DEPARTMENT`

```sql
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
```

Aturan translasi: Entity set ke tabel.

**Status: tabel tambahan yang sengaja dikosongkan.**

Sesuai spesifikasi Step 2 poin 2 dan poin 4 sub-a, `department` merupakan tabel tambahan yang relevan dengan tabel hasil scraping dan dibiarkan kosong. Relevansinya terletak pada relasi M:N ke `affiliation`, entitas yang diperoleh dari scraping.

Alasan teknis mengapa tidak diisi bersifat ganda. Pertama, halaman `/departments` berada di luar cakupan scraping. Kedua, dan lebih penting, data departemen sebenarnya tersirat dalam kolom `affiliation.name` yang memuat hierarki tiga tingkat dalam satu string:

```
"Science Education Study Program, Faculty of Mathematics and Natural Sciences, Universitas Negeri Semarang"
 |__ program studi ________|  |__ fakultas ___________________|  |__ universitas ___|
```

Namun ekstraksi memerlukan parsing teks bebas dengan format tidak konsisten:
- Sebagian hanya menyebut universitas: `"Universitas Airlangga"`
- Sebagian tiga tingkat penuh (contoh di atas)
- Sebagian menggunakan frasa kompleks: `"...in cooperation with the Graduate Program of..."`

Parsing semacam ini berisiko menghasilkan data yang salah. Tabel dirancang untuk menunjukkan normalisasi yang seharusnya, namun tidak diisi demi menjaga integritas data.

**Struktur berdasarkan verifikasi sumber.** Halaman `/departments` menunjukkan bahwa satu program studi dengan nama dan kode yang sama dimiliki oleh banyak perguruan tinggi sekaligus. Contoh: "Administrasi Bisnis (S1)" dengan CODE 63211 terdaftar pada 111 afiliasi berbeda. Relasi affiliation-department karenanya dimodelkan sebagai many-to-many melalui junction table `affiliation_department` (lihat [bagian 6.11](#611-affiliation_department-junction-table)).

Halaman yang sama juga menampilkan jenjang akademik (D3, S1, S2) dan kode program studi untuk setiap departemen, sehingga keduanya dimodelkan sebagai kolom `level` dan `code_prodi`.

**Surrogate key.** Tidak tersedia natural key tunggal dari sumber. Kombinasi `(name, level)` kemungkinan unik dan dijaga melalui constraint `UNIQUE`, namun `code_prodi` juga berpotensi menjadi natural key. Karena tabel ini kosong, keputusan final ditangguhkan hingga data tersedia.

---

### 6.11 `affiliation_department` (Junction Table)

Asal ERD: Relasi many-to-many *memiliki program* antara `AFFILIATION` dan `DEPARTMENT`

```sql
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
```

**Status: tabel tambahan yang sengaja dikosongkan.**

Tabel ini merupakan konsekuensi langsung dari `department` yang juga kosong. Sesuai spesifikasi Step 2 poin 4 sub-a, tabel tambahan tidak perlu diisi dengan data dummy maupun data asli.

Aturan translasi: M:N ke junction table, sama seperti [bagian 6.7](#67-journal_subject-junction-table) dan [6.8](#68-journal_indexing-junction-table). Tabel ini tidak muncul di ERD karena merupakan artefak implementasi.

**Bukti relasi M:N dari sumber:**

| Arah | Bukti terverifikasi |
|---|---|
| Satu afiliasi memiliki banyak departemen | Universitas Gadjah Mada memiliki 294 departemen |
| Satu departemen dimiliki banyak afiliasi | "Administrasi Bisnis (S1)" terdaftar pada 111 afiliasi |

Kedua arah bersifat "banyak", sehingga relasi ini benar-benar many-to-many.

---

## 7. Daftar Asumsi

Bagian ini mendokumentasikan asumsi yang digunakan dalam proyek, dikelompokkan berdasarkan tingkat verifikasi. Asumsi yang khusus berkaitan dengan penyusunan diagram relasional dijelaskan pada [bagian 5.4](#54-diagram-relasional).

### 7.1 Asumsi terverifikasi dari data

| # | Asumsi | Bukti verifikasi |
|---|---|---|
| 1 | `journal_id` dari SINTA unik dan stabil | 15.448 baris = 15.448 ID unik; batch 2 dan 3 berhasil di-*upsert* tanpa duplikat |
| 2 | ISSN berformat 8 karakter (7 digit + digit/X) | 0 pelanggaran `CHECK` dari 15.448 baris |
| 3 | `citations_5yr` tidak melebihi `citations` | 0 pelanggaran `CHECK` |
| 4 | Hanya ada 2 badan indeks (Scopus, Garuda) | 15.398 baris junction, tidak ada nilai lain |
| 5 | Hanya ada 10 subject area | Terverifikasi dari seluruh dataset |
| 6 | Sebagian jurnal tidak punya afiliasi | 1.941 baris `NULL`, sesuai tampilan SINTA |
| 7 | Ada jurnal tanpa badge akreditasi | 1 baris, cocok dengan chart SINTA "Not Accredited: 1" |
| 8 | Metrik selalu terisi | 0 `NULL` pada keempat kolom metrik |
| 9 | Departemen dimiliki banyak afiliasi | Halaman `/departments`: "Administrasi Bisnis (S1)" pada 111 afiliasi |

### 7.2 Asumsi desain

Kelompok ini merupakan keputusan perancangan, bukan temuan dari data.

| # | Keputusan | Justifikasi |
|---|---|---|
| 10 | `metric_snapshot` sebagai weak entity | Pengukuran tidak bermakna tanpa jurnal; discriminator `captured_at` |
| 11 | Surrogate key pada tabel lookup | Konsistensi pola; natural key tetap dijaga `UNIQUE`. Alternatif natural key sama valid |
| 12 | Natural key pada `journal`, `affiliation`, `author` | Memungkinkan deduplikasi idempoten antar-batch |
| 13 | `ON DELETE RESTRICT` pada akreditasi | Melindungi integritas: menghapus "S1" akan merusak makna 268 jurnal |
| 14 | `NUMERIC` bukan `FLOAT` untuk impact | Menghindari galat pembulatan floating-point |
| 15 | Star schema untuk warehouse | Dimensi kecil (4–2.014 baris); normalisasi lanjut tidak menguntungkan |

### 7.3 Hipotesis interpretatif

Dua penjelasan berikut diajukan untuk memaknai pola yang ditemukan dalam data. Keduanya konsisten dengan bukti yang tersedia dan memberikan interpretasi yang paling masuk akal terhadap fenomena yang teramati.

**Hipotesis 1: kelompok "Scopus only" merupakan jurnal berjangkauan internasional.**

Tujuh jurnal yang terindeks Scopus namun tidak terdaftar di Garuda menunjukkan sitasi rata-rata tertinggi (13.068) namun impact SINTA terendah (0,79). Pola ini konsisten dengan karakteristik jurnal yang beroperasi di luar ekosistem publikasi nasional. Garuda merupakan database nasional Indonesia, sehingga ketidakhadiran di dalamnya mengindikasikan orientasi internasional. Sitasi global yang masif tidak terefleksikan pada metrik impact SINTA yang dihitung berdasarkan konteks nasional.

Implikasinya, metrik `impact` sebaiknya dibaca sebagai posisi relatif dalam ekosistem nasional, bukan sebagai ukuran dampak ilmiah universal.

**Hipotesis 2: lima jurnal yang tidak tertangkap kemungkinan sudah tidak aktif.**

Convergent crawling mencapai 15.448 dari 15.453 jurnal yang dilaporkan SINTA. Kurva konvergensi menunjukkan penurunan tajam pada pass terakhir (+7 jurnal baru), mengindikasikan bahwa proses telah mencapai titik jenuh. Lima jurnal sisa kemungkinan besar merupakan entri yang telah dihapus atau dinonaktifkan, sementara counter agregat pada halaman SINTA belum diperbarui. Pola serupa terlihat pada batch kedua yang justru menemukan 5 jurnal baru yang belum ada pada batch pertama, menunjukkan bahwa katalog SINTA memang berubah secara berkala.

### 7.4 Batas cakupan

| # | Hal | Keterangan |
|---|---|---|
| 16 | Halaman yang di-scrape | Hanya listing `/journals?page=N`. Halaman `/authors`, `/affiliations`, `/departments`, dan profil individual tidak di-scrape |
| 17 | Granularitas metrik | Agregat per jurnal, tidak tersedia data per artikel |
| 18 | Rumus `impact` | Tidak dipublikasikan SINTA; angka diambil apa adanya |
| 19 | Coverage | 99,97%, 5 dari 15.453 jurnal tidak tertangkap |

---

## 8. Data Storing

### 8.1 Cara menjalankan

```bash
createdb -U postgres sinta_db
psql -U postgres -d sinta_db -f "Data Storing/src/schema.sql"

cd "Data Storing/src"
python load.py --dsn "postgresql://postgres:PASSWORD@localhost/sinta_db"
psql -U postgres -d sinta_db -f verify.sql
```

### 8.2 Constraint yang Diimplementasikan

| Jenis | Jumlah | Detail |
|---|---:|---|
| PRIMARY KEY | 11 | Seluruh tabel; 4 di antaranya composite |
| FOREIGN KEY | 10 | Dengan `ON DELETE` sesuai semantik |
| UNIQUE | 4 | `accreditation.label`, `subject_area.name`, `indexing_body.name`, `department(name, level)` |
| CHECK | 8 | Regex ISSN (×2), rentang rank, non-negatif metrik, `citations_5yr <= citations`, urutan timestamp, jenjang akademik, h-index non-negatif |
| TRIGGER | 1 | `touch_journal_last_seen` |

**Trigger:**

```sql
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
```

Setiap kali snapshot baru masuk, `journal.last_seen_at` maju. Ini menjadi bukti SQL bahwa scrape berulang benar-benar terjadi:

| Kondisi | Setelah batch 1 | Setelah batch 3 |
|---|---:|---:|
| `last_seen_at = first_seen_at` | 15.448 | 23 |
| `last_seen_at > first_seen_at` | 0 | 15.425 |

Sebelum | Sesudah
:---:|:---:
![Trigger sebelum](Data%20Storing/screenshots/08_trigger_sebelum.png) | ![Trigger sesudah](Data%20Storing/screenshots/08_trigger_sesudah.png)

### 8.3 Justifikasi Pemilihan Key

Implementasi RDBMS mengikuti diagram relasional secara 1:1.

| Tabel | Jenis key | Alasan ringkas |
|---|---|---|
| `journal`, `affiliation`, `author` | Natural (ID SINTA) | Memungkinkan deduplikasi idempoten antar-batch |
| `accreditation`, `subject_area`, `indexing_body`, `department` | Surrogate SERIAL | Konsistensi pola; natural key tetap dijaga UNIQUE |
| `metric_snapshot` | Composite PK | Sesuai model weak entity |
| `journal_subject`, `journal_indexing`, `affiliation_department` | Composite PK | Junction table M:N |

Justifikasi detail per tabel dijelaskan pada masing-masing subbagian di [bagian 6](#6-translasi-erd-ke-relasional-detail-per-tabel).

### 8.4 Validasi Penyimpanan

| Tingkat | Database | SINTA | Selisih |
|---|---:|---:|---:|
| S1 | 268 | 268 | 0 |
| S2 | 1.511 | 1.511 | 0 |
| S3 | 2.833 | 2.834 | −1 |
| S4 | 5.238 | 5.239 | −1 |
| S5 | 5.335 | 5.338 | −3 |
| S6 | 262 | 262 | 0 |
| (tanpa badge) | 1 | — | — |

Coverage 99,97%. Integritas: 15.448 baris sama dengan 15.448 `journal_id` unik, tanpa duplikat. Total `metric_snapshot` 45.452 baris dari 3 batch.

Tiga tabel dibiarkan kosong sesuai spesifikasi Step 2 poin 4 sub-a: `author`, `department`, dan `affiliation_department`.

![Row counts](Data%20Storing/screenshots/01_row_counts.png)

![Validasi akreditasi](Data%20Storing/screenshots/03_validasi_akreditasi.png)

![Integritas](Data%20Storing/screenshots/09_integritas.png)

Query bukti SELECT FROM WHERE:

![Select where](Data%20Storing/screenshots/02_select_where.png)

Query tersebut memfilter ke snapshot terbaru (`captured_at = MAX(captured_at)`). Tanpa filter, setiap jurnal muncul tiga kali, satu per batch. Duplikasi tersebut adalah perilaku yang benar untuk tabel time-series, namun tidak informatif sebagai bukti penyimpanan.

---

## 9. Bonus: Data Warehouse

![Star Schema](Data%20Warehouse/design/warehouse_star_schema.png)

### 9.1 Cara menjalankan

```bash
createdb -U postgres sinta_dw
psql -U postgres -d sinta_dw -f "Data Warehouse/src/warehouse_schema.sql"

cd "Data Warehouse/src"
python warehouse_load.py \
  --src "postgresql://postgres:PW@localhost/sinta_db" \
  --dw  "postgresql://postgres:PW@localhost/sinta_dw"

psql -U postgres -d sinta_dw -f warehouse_queries.sql
```

### 9.2 Desain Star Schema

Grain fact table: satu baris per (jurnal, waktu snapshot).

| Komponen | Tabel | Baris |
|---|---|---:|
| Fact | `fact_journal_metric` | 45.452 |
| Dimension | `dim_time` | 9 |
| | `dim_journal` | 15.448 |
| | `dim_affiliation` | 2.014 (2.013 + Unknown) |
| | `dim_accreditation` | 9 |
| | `dim_indexing` | 4 |
| | `dim_subject` | 10 |
| Bridge | `bridge_journal_subject` | 6.703 |

Measure attributes:

| Measure | Sifat | Aturan agregasi |
|---|---|---|
| `citations`, `citations_5yr`, `h5_index` | Additive | Boleh `SUM` dan `AVG` |
| `impact` | Semi-additive | Hanya `AVG`, nilai sudah berupa rata-rata |

### 9.3 Keputusan Desain

1. Star, bukan snowflake. Dimensi berukuran kecil (4–2.014 baris); normalisasi lanjut hanya menambah join tanpa menghemat ruang.

2. `dim_time` sebagai dimensi wajib. Sesuai materi kuliah, dimensi waktu wajib dalam model multidimensional. Inilah yang mengubah snapshot menjadi warehouse historis.

3. Subject sebagai bridge, bukan dimensi star. Model multidimensional standar mengasumsikan relasi many-to-one dari fact ke dimension. Relasi jurnal-subject bersifat M:N (0–10 bidang per jurnal). Memaksakannya menjadi dimensi akan menyebabkan 76,1% fact menunjuk member "Unclassified". Bridge table adalah pola Kimball untuk M:N dalam warehouse, dan berada di luar cakupan materi kuliah.

Konsekuensinya, agregasi melalui bridge berisiko *double-counting*. Query Q4 menggunakan `COUNT(DISTINCT journal_key)`.

Pada diagram, `bridge_journal_subject` terhubung ke `dim_journal`, bukan ke `fact_journal_metric`. Ini disengaja, menghubungkan bridge langsung ke fact akan menggandakan baris fact dan merusak grain.

4. Member "Unknown" dengan key −1, juga di luar cakupan materi kuliah. Fact table sebaiknya tidak memiliki FK NULL. 1.941 jurnal tanpa afiliasi dipetakan ke `affiliation_key = -1`.

### 9.4 Perbandingan OLTP vs Warehouse

| Aspek | `sinta_db` (OLTP) | `sinta_dw` (OLAP) |
|---|---|---|
| Normalisasi | 3NF/BCNF | Denormalisasi terkendali |
| Tujuan | Integritas dan update | Kecepatan query analitik |
| Tabel | 11 | 8 (1 fact + 6 dim + 1 bridge) |
| Query khas | Cari atau ubah 1 jurnal | Agregasi lintas dimensi |
| Data | Current state | Historis |

### 9.5 Kebutuhan Informasi dan Query Analitik

| # | Pertanyaan Analitik | Pendekatan |
|---|---|---|
| Q1 | Apakah akreditasi tinggi berkorelasi dengan impact tinggi? | Agregasi per `dim_accreditation` |
| Q2 | Apakah indeksasi Scopus menandakan kualitas lebih baik? | Agregasi per `dim_indexing` |
| Q3 | Institusi mana yang paling produktif menghasilkan jurnal top? | Agregasi per `dim_affiliation` |
| Q4 | Bidang keilmuan apa yang paling banyak jurnalnya? | Agregasi via `bridge` |
| Q5 | Bagaimana distribusi indeksasi per tingkat akreditasi? | Cross-tab 2 dimensi |
| Q6 | Bagaimana pertumbuhan sitasi antar-waktu? | Agregasi per `dim_time` |

### 9.6 Temuan Analitik

Seluruh angka berikut diambil dari batch terbaru (21 Juli 2026).

#### Temuan 1: Scopus terkonsentrasi di tingkat akreditasi tertinggi

| Akreditasi | Scopus+Garuda | Scopus saja | Garuda saja | Tidak terindeks |
|---|---:|---:|---:|---:|
| S1 | 192 | 6 | 61 | 2 |
| S2 | 7 | 0 | 1.454 | 25 |
| S3 | 2 | 1 | 2.699 | 61 |
| S4 | 0 | 0 | 4.982 | 79 |
| S5 | 0 | 0 | 5.087 | 72 |
| S6 | 0 | 0 | 243 | 12 |

Dari 201 jurnal dengan profil Scopus+Garuda, sebanyak 192 (95,5%) berada di tingkat S1. Mulai S4 ke bawah, tidak ada satu pun jurnal Scopus.

Interpretasi: akreditasi SINTA dan indeksasi Scopus sangat berkorelasi pada tingkat teratas, namun korelasi tersebut runtuh sepenuhnya di bawah S3. Ini menunjukkan bahwa Scopus berfungsi sebagai penanda kualitas hanya pada segmen elit jurnal Indonesia, sementara mayoritas jurnal (S4–S6, sekitar 10.300 jurnal) beroperasi sepenuhnya di luar ekosistem indeksasi internasional.

![Q5 Matriks silang](Data%20Warehouse/screenshots/Q5_matriks_silang.png)

#### Temuan 2: Anomali jurnal "Scopus only"

| Profil indeks | Jumlah | Rata impact | Rata sitasi |
|---|---:|---:|---:|
| Scopus + Garuda | 201 | 3,71 | 5.433 |
| Garuda only | 14.527 | 2,65 | 1.111 |
| Not indexed | 251 | 1,81 | 1.681 |
| Scopus only | 7 | 0,79 | 13.068 |

Tujuh jurnal yang terindeks Scopus namun tidak terdaftar di Garuda menunjukkan pola yang berlawanan: sitasi rata-rata tertinggi dari seluruh kelompok (13.068, atau 2,4 kali lipat kelompok Scopus+Garuda), namun impact SINTA terendah (0,79, bahkan di bawah kelompok "tidak terindeks").

Interpretasi yang paling masuk akal adalah bahwa kelompok ini merupakan jurnal berjangkauan internasional yang tidak terdaftar di Garuda, database nasional Indonesia. Sitasi globalnya masif karena jangkauan internasional, sementara metrik impact SINTA dihitung berdasarkan konteks nasional sehingga tidak merefleksikan pengaruh global tersebut. Penjelasan lengkap pada [bagian 7.3](#73-hipotesis-interpretatif).

Implikasi metodologis: metrik `impact` SINTA sebaiknya dibaca sebagai posisi relatif dalam ekosistem nasional, bukan sebagai ukuran kualitas absolut.

![Q2 Scopus impact](Data%20Warehouse/screenshots/Q2_scopus_impact.png)

#### Temuan 3: Garuda bersifat near-universal

Sebanyak 15.183 dari 15.448 jurnal (98,3%) terindeks Garuda. Angka ini menjadikan Garuda sebagai baseline nasional, bukan sinyal pembeda kualitas. Hanya 255 jurnal (1,7%) yang tidak terindeks sama sekali.

Sebaliknya, Scopus dengan 215 jurnal (1,4%) merupakan indeks yang benar-benar selektif.

Konsekuensi untuk analisis: dimensi `dim_indexing` memiliki kardinalitas efektif yang sangat rendah. Dari empat kombinasi yang dimodelkan, satu kombinasi (Garuda only) mencakup 94% data. Ini membuat dimensi tersebut kurang informatif untuk segmentasi, kecuali ketika difokuskan pada minoritas Scopus.

#### Temuan 4: Distribusi bidang keilmuan dan limitasi bridge

| Subject area | Jumlah jurnal | Rata impact |
|---|---:|---:|
| Education | 1.505 | 9,20 |
| Social | 1.078 | 22,01 |
| Science | 1.036 | 22,62 |
| Economy | 560 | 41,06 |
| Humanities | 526 | 1,60 |
| Health | 499 | 1,14 |
| Engineering | 471 | 1,33 |
| Agriculture | 344 | 0,97 |
| Religion | 288 | 1,74 |
| Art | 277 | 1,62 |

Education merupakan bidang dengan jurnal terbanyak (1.505 jurnal, 40,7% dari 3.697 jurnal yang memiliki tag subject).

Limitasi metodologis yang perlu dicatat: kolom rata impact menunjukkan nilai yang tidak konsisten. Economy tercatat 41,06 sementara Health hanya 1,14, selisih 36 kali lipat yang tidak masuk akal secara substantif.

Penyebabnya adalah double-counting melalui bridge table. Jurnal yang tercakup dalam banyak bidang sekaligus, terutama jurnal pengabdian masyarakat dengan 8 sampai 10 subject, akan dihitung pada setiap bidangnya. Jika jurnal tersebut memiliki impact tinggi, nilainya akan menggelembungkan rata-rata di semua bidang yang dicakupnya.

Query Q4 sudah menggunakan `COUNT(DISTINCT journal_key)` untuk kolom jumlah jurnal, sehingga angka tersebut akurat. Namun `AVG(impact)` tidak dapat di-*deduplicate* dengan cara yang sama tanpa mengubah semantik pertanyaan. Nilai rata impact per bidang karenanya tidak boleh diinterpretasikan sebagai ukuran kualitas bidang.

![Q4 Subject distribution](Data%20Warehouse/screenshots/Q4_subject_distribution.png)

#### Temuan 5: Impact tidak monotonik terhadap akreditasi

| Akreditasi | Jumlah jurnal | Rata impact | Rata sitasi | Sitasi tertinggi |
|---|---:|---:|---:|---:|
| S1 | 261 | 3,25 | 5.183 | 52.444 |
| S2 | 1.486 | 1,82 | 2.320 | 29.149 |
| S3 | 2.763 | 1,47 | 1.521 | 77.166 |
| S4 | 5.061 | 3,22 | 967 | 47.241 |
| S5 | 5.159 | 3,02 | 687 | 72.371 |
| S6 | 255 | 0,95 | 1.059 | 81.427 |

Rata sitasi menurun secara monotonik seiring turunnya tingkat akreditasi (5.183, 2.320, 1.521, 967, 687), pola yang sesuai ekspektasi.

Namun rata impact tidak mengikuti pola tersebut. S4 (3,22) dan S5 (3,02) justru lebih tinggi daripada S2 (1,82) dan S3 (1,47).

Kemungkinan penjelasan: metrik impact SINTA bukan fungsi langsung dari jumlah sitasi, melainkan kemungkinan melibatkan normalisasi terhadap jumlah artikel atau periode waktu. Jurnal S4 dan S5 yang menerbitkan sedikit artikel namun mendapat sitasi memadai dapat memperoleh impact tinggi. Karena rumus perhitungan impact tidak dipublikasikan SINTA, penjelasan ini tetap bersifat dugaan.

Kolom sitasi tertinggi juga menunjukkan bahwa jurnal dengan sitasi terbesar (81.427) justru berada di S6, bukan S1. Ini menegaskan bahwa akreditasi SINTA tidak semata-mata ditentukan oleh volume sitasi.

![Q1 Impact akreditasi](Data%20Warehouse/screenshots/Q1_impact_akreditasi.png)

#### Temuan 6: Konsentrasi produksi jurnal pada institusi besar

| Afiliasi | Jurnal S1–S2 | Rata impact |
|---|---:|---:|
| Magister Manajemen FEB, Universitas Gadjah Mada | 47 | 1,21 |
| Universitas Airlangga | 44 | 4,89 |
| Universitas Diponegoro | 43 | 1,63 |
| Universitas Indonesia | 35 | 2,84 |
| Jurusan Biologi FMIPA, Universitas Brawijaya | 31 | 1,47 |
| Universitas Padjadjaran | 29 | 1,41 |
| Faculty of Tarbiya, UIN Sunan Gunung Djati | 28 | 2,04 |
| FEB UIN Syarif Hidayatullah Jakarta | 26 | 1,04 |
| Institut Pertanian Bogor | 26 | 1,90 |
| Science Education Study Program, UNNES | 26 | 4,11 |

Sepuluh afiliasi teratas menyumbang 335 jurnal S1–S2 dari total 1.747 (19,2%), sementara jumlah afiliasi keseluruhan mencapai 2.013. Ini menunjukkan konsentrasi produksi jurnal berkualitas pada sejumlah kecil institusi.

Perlu dicatat bahwa granularitas afiliasi di SINTA tidak konsisten. Sebagian entri merujuk universitas secara keseluruhan ("Universitas Airlangga"), sementara sebagian lain merujuk unit yang lebih spesifik ("Magister Manajemen FEB, Universitas Gadjah Mada"). Akibatnya, peringkat ini tidak dapat langsung dibaca sebagai peringkat universitas. UGM misalnya kemungkinan memiliki lebih banyak jurnal yang tersebar di beberapa entri afiliasi berbeda.

Ini merupakan konsekuensi dari keputusan untuk tidak melakukan parsing hierarki afiliasi, sebagaimana dijelaskan pada [bagian 6.10](#610-department).

![Q3 Top afiliasi](Data%20Warehouse/screenshots/Q3_top_afiliasi.png)

---

## 10. Bonus: Automated Scheduling

### 10.1 Implementasi

Pipeline dijadwalkan otomatis via **Windows Task Scheduler**:

| | |
|---|---|
| Nama task | `SINTA_ETL_Weekly` |
| Jadwal | Setiap Senin, 02:00 (jam sepi, sesuai etika scraping) |
| Status | `Ready` |
| Next run | 27 Juli 2026, 02:00 |
| Script | `run_etl.ps1` |

```bash
# Registrasi (sekali, sebagai Administrator)
.\register_task.ps1

# Uji manual
.\run_etl.ps1
```

`run_etl.ps1` menjalankan tiga tahap berurutan tanpa intervensi manual:
1. `scrape_batch2.py`: crawl snapshot baru (3 pass convergent)
2. `load_batch2.py`: append ke `metric_snapshot`
3. `warehouse_load.py`: refresh star schema

**Keamanan:** password dibaca dari environment variable `PGPASSWORD`, tidak di-hardcode dalam script.

![Scheduling task](Data%20Storing/screenshots/scheduling_task.png)

### 10.2 Mekanisme Anti-Redundansi

Spesifikasi meminta *"Pastikan tidak terdapat redundansi data pada DBMS."*

Jaminan berada di level database, bukan script:

```sql
PRIMARY KEY (journal_id, captured_at)
```

Seluruh `INSERT` menggunakan `ON CONFLICT DO NOTHING`. Konsekuensinya:

| Skenario | Hasil |
|---|---|
| Load ulang dengan timestamp sama | Tidak ada baris baru (no-op) |
| Load dengan timestamp baru | Baris baru ditambahkan |
| Pipeline dijalankan 3× | Jurnal unik tetap **15.448** |

### 10.3 Bukti Eksekusi: Tiga Batch

| Batch | Tanggal | Timestamp | Jurnal |
|---|---|---|---:|
| 1 | 13 Juli 2026 | 7 timestamp internal (06:56–10:51 UTC) | 15.448 |
| 2 | 17 Juli 2026 | `2026-07-17T08:11:13Z` | 15.018 |
| 3 | **21 Juli 2026** | `2026-07-21T03:47:48Z` | 14.986 |

**Catatan transparansi:** batch 1 memiliki 7 timestamp berbeda karena convergent crawling menjalankan 7 pass, masing-masing menandai jurnal yang baru ditemukan dengan waktu pass tersebut. Secara logis ini adalah satu batch.

**Catatan pengelolaan file batch.** Versi awal `scrape_batch2.py` menulis ke nama file tetap `metric_snapshots_batch2.json`, sehingga batch yang dijalankan berikutnya menimpa batch sebelumnya. Akibatnya data batch 17 Juli sempat hanya tersisa di dalam database.

Script telah diperbaiki agar menggunakan nama file bertanggal (`metric_snapshots_YYYYMMDD.json`), dan data batch 17 Juli dipulihkan dari database melalui `csv_to_json.py`. Ketiga batch kini tersimpan sebagai file terpisah yang dapat dimuat ulang kapan saja.

**Hasil eksekusi 21 Juli 2026:**
```
[2026-07-21 10:47:45] === ETL PIPELINE MULAI ===
[2026-07-21 13:10:44] --- Tahap 1/3: scraping ---   → 14.991 jurnal
[2026-07-21 13:10:46] --- Tahap 2/3: load ---        → 8 → 9 timestamp
[2026-07-21 13:10:49] --- Tahap 3/3: warehouse ---   → 45.452 fact rows
[2026-07-21 13:10:49] batch tersimpan: 9 | total snapshot: 45452 | jurnal unik: 15448
[2026-07-21 13:10:49] === ETL PIPELINE SELESAI ===
```

![Pipeline log 1](Data%20Storing/screenshots/scheduling_pipeline_log1.png)

![Pipeline log 2](Data%20Storing/screenshots/scheduling_pipeline_log2.png)

Perbedaan timestamp antar-batch:

Sebelum | Sesudah
:---:|:---:
![Timeseries sebelum](Data%20Storing/screenshots/07_timeseries_sebelum.png) | ![Timeseries sesudah](Data%20Storing/screenshots/07_timeseries_sesudah.png)

Delta metrik antar-batch:

![Scheduling delta](Data%20Storing/screenshots/scheduling_delta.png)

### 10.4 Tren Tiga Batch

| Tanggal | Jurnal | Rata sitasi |
|---|---:|---:|
| 2026-07-13 | 15.448 | 1.169 |
| 2026-07-17 | 15.018 | 1.187 |
| 2026-07-21 | 14.986 | 1.184 |

Jumlah jurnal per batch sedikit berbeda karena convergent crawling tidak selalu menangkap himpunan yang identik.

![Q6 Tren 3 batch](Data%20Warehouse/screenshots/Q6_tren_3batch.png)

### 10.5 Bukti Tambahan

**Trigger bekerja:** 15.425 dari 15.448 jurnal memiliki `last_seen_at > first_seen_at`.

**Katalog SINTA bertambah:** batch 2 menemukan 5 jurnal baru (ID: 567, 5607, 15556, 16467, 17290) yang belum ada di batch 1. Foreign key constraint menolak snapshot untuk jurnal yang belum terdaftar, bukti integritas referensial bekerja otomatis.

**Catatan `LastRunTime`:** field ini menunjukkan "never" karena eksekusi 21 Juli dilakukan dengan memanggil `run_etl.ps1` langsung untuk pengujian, bukan melalui trigger scheduler. Field tersebut hanya mencatat eksekusi yang dipicu Task Scheduler. Eksekusi terjadwal pertama berlangsung 27 Juli 2026 pukul 02:00.

---

## 11. Bonus: Query Optimization

### 11.1 Metodologi

Untuk setiap query: jalankan `EXPLAIN (ANALYZE, BUFFERS)` sebelum index dibuat, buat index, jalankan sesudah. Output query harus identik.

```bash
psql -U postgres -d sinta_db -f "Query Optimasi/query_optimasi.sql"
```

**Catatan desain:** index sengaja dikomentari pada `schema.sql` agar kondisi "sebelum" benar-benar tanpa index.

### 11.2 Hasil

| # | Query | Sebelum | Sesudah | Percepatan |
|---|---|---|---|---|
| **1** | Filter jurnal per akreditasi | Seq Scan, **14,67 ms**, 1.569 buffer | Index Scan, **0,56 ms**, 21 buffer | **26×** |
| **2** | Filter jurnal per afiliasi | Seq Scan, **11,04 ms**, 2.278 buffer | Bitmap Index Scan, **6,76 ms**, 844 buffer | **1,6×** |
| **3** | Join M:N per bidang | Seq Scan junction, **4,78 ms** | Bitmap Index Scan, **2,20 ms** | **2,2×** |

**Verifikasi output identik:**

| Query | Baris hasil |
|---|---:|
| Optimasi 1: jurnal S1 | 268 |
| Optimasi 2: jurnal afiliasi 9 | 154 |
| Optimasi 3: jurnal Education | 1.534 |

![Verifikasi optimasi](Query%20Optimasi/screenshots/opt_verify.png)

### 11.3 Analisis

**Optimasi 1: `CREATE INDEX ON journal(accreditation_id)`**

Kondisi sebelum optimasi membaca 15.448 baris lalu membuang 15.180 (`Rows Removed by Filter: 15180`). Kondisi sesudah langsung mengakses 268 baris via index. Buffer turun dari 1.569 ke 21, yaitu pengurangan I/O sebesar 98,7%.

Ini merupakan kasus ideal penggunaan index: selektivitas tinggi (268 dari 15.448 baris, atau 1,7%) pada kolom yang menjadi predikat filter.

Sebelum | Sesudah
:---:|:---:
![Opt1 before](Query%20Optimasi/screenshots/opt1_before.png) | ![Opt1 after](Query%20Optimasi/screenshots/opt1_after.png)

**Optimasi 2: `CREATE INDEX ON journal(affiliation_id)`**

PostgreSQL tidak membuat index otomatis untuk kolom foreign key, berbeda dengan primary key. Padahal foreign key justru sering menjadi titik masuk query, seperti pada kasus ini yang mencari seluruh jurnal terbitan satu afiliasi.

Kondisi sebelum optimasi melakukan Seq Scan pada 15.448 baris untuk menemukan 163 baris yang relevan, membuang 15.285 baris atau 98,9%. Setelah index dibuat, PostgreSQL beralih ke Bitmap Index Scan dan buffer turun dari 2.278 ke 844, yaitu pengurangan I/O sebesar 63%.

Percepatan waktu eksekusi lebih moderat dibanding Optimasi 1 karena bagian dominan query ini adalah pencarian `MAX(captured_at)` pada `metric_snapshot` yang memindai 45.452 baris. Bagian tersebut tidak terpengaruh index pada `journal`. Optimasi lanjutan yang mungkin dilakukan adalah menambah index pada `metric_snapshot(captured_at)`.

Sebelum | Sesudah
:---:|:---:
![Opt2 before](Query%20Optimasi/screenshots/opt2_before.png) | ![Opt2 after](Query%20Optimasi/screenshots/opt2_after.png)

**Optimasi 3: `CREATE INDEX ON journal_subject(subject_id)`**

Junction table `journal_subject` memiliki primary key composite `(journal_id, subject_id)`. Index bawaan PK tersebut disusun dengan `journal_id` sebagai kolom pertama, sehingga hanya efisien untuk pencarian berdasarkan `journal_id`.

Query ini melakukan pencarian sebaliknya, yaitu berdasarkan `subject_id`. Karena `subject_id` bukan kolom pertama pada index PK, PostgreSQL tidak dapat memanfaatkannya dan terpaksa melakukan Seq Scan pada seluruh 6.703 baris.

Setelah index dibuat, Seq Scan berubah menjadi Bitmap Index Scan. Percepatan moderat (2,2×) karena bagian dominan query adalah nested loop join ke `journal` (4.602 buffer) yang sudah menggunakan `journal_pkey`.

Sebelum | Sesudah
:---:|:---:
![Opt3 before](Query%20Optimasi/screenshots/opt3_before.png) | ![Opt3 after](Query%20Optimasi/screenshots/opt3_after.png)

---

## 12. Struktur Repository

```
Seleksi-2026-Tugas-1/
├── Data Scraping/
│   ├── src/
│   │   ├── parser.py                  # Parsing HTML → dict (18 doctest)
│   │   ├── scraper_convergent.py      # Convergent crawler
│   │   ├── seed_state.py              # Bootstrap dari cache
│   │   ├── split_convergent.py        # Normalisasi → JSON per-entitas
│   │   ├── scrape_batch2.py           # Scrape batch berikutnya
│   │   ├── load_batch2.py             # Load snapshot batch baru
│   │   ├── csv_to_json.py             # Pemulihan batch dari export CSV
│   │   ├── run_etl.ps1                # Pipeline otomatis (scheduling)
│   │   └── register_task.ps1          # Registrasi Task Scheduler
│   ├── tools/                         # Script diagnosis (dokumentasi proses)
│   │   ├── probe_sort.py              # Uji 8 sort parameter (semua gagal)
│   │   ├── probe_form.py              # Baca form HTML SINTA
│   │   ├── check_dupes.py             # Deteksi unstable pagination
│   │   ├── debug_subjects.py          # Diagnosis subject duplikat
│   │   ├── inspect_data.py            # Audit JSON sebelum load
│   │   ├── scraper.py                 # Versi awal (cacat, disimpan sbg dokumentasi)
│   │   └── scraper_partitioned.py     # Pendekatan POST filter (gagal)
│   ├── tests/fixture_card.html        # Fixture uji parser
│   └── data/                          # 8 file JSON per-entitas
│
├── Data Storing/
│   ├── design/       erd.png, relational.png
│   ├── src/          schema.sql, load.py, verify.sql
│   ├── export/       sinta_db.sql
│   └── screenshots/  bukti penyimpanan dan scheduling
│
├── Data Warehouse/
│   ├── design/       warehouse_star_schema.png
│   ├── src/          warehouse_schema.sql, warehouse_load.py, warehouse_queries.sql
│   ├── export/       sinta_dw.sql
│   └── screenshots/  6 query analitik
│
├── Query Optimasi/
│   ├── query_optimasi.sql             # 3 query optimasi dengan komentar
│   └── screenshots/                   # bukti sebelum dan sesudah
│
├── .gitignore
├── requirements.txt
└── README.md
```

**Folder `tools/`** berisi script yang digunakan selama investigasi namun tidak menjadi bagian pipeline final. Disertakan sebagai dokumentasi proses, termasuk tiga pendekatan yang gagal pada [bagian 3.3](#33-temuan-kritis-unstable-pagination).

---

## 13. Penggunaan AI

Proyek ini menggunakan bantuan AI (Claude, Anthropic) sebagai alat pendukung dalam proses pengembangan dan dokumentasi.

### 13.1 Bagian yang Dibantu AI

- Diagnosis permasalahan teknis, termasuk identifikasi isu unstable pagination serta perancangan strategi convergent crawling.
- Pembuatan kode pendukung, seperti boilerplate scraper, DDL SQL, script ETL, dan script PowerShell untuk scheduling.
- Identifikasi edge case pada data, seperti format angka Indonesia, ISSN bernilai `"0"`, serta URL dengan nilai `"#!"`.
- Penyusunan dan perapihan dokumentasi README serta dokumentasi kode, termasuk komentar kode, berdasarkan informasi dan struktur yang telah ditentukan oleh penulis.

### 13.2 Bagian yang Dikerjakan Sendiri

- Pemilihan topik proyek dan verifikasi legalitas sumber data, termasuk pemeriksaan `robots.txt` serta evaluasi terhadap beberapa alternatif sumber.
- Inspeksi menggunakan DevTools untuk memahami struktur HTML SINTA, termasuk identifikasi elemen dan nama CSS class yang digunakan.
- Perancangan solusi, pembuatan hipotesis, serta penyusunan diagram ERD, relational schema, dan star schema.
- Perancangan sistem automated scheduling.
- Optimasi query beserta analisis performanya, dengan bantuan AI hanya untuk merapikan penyampaian penjelasan agar lebih mudah dipahami.
- Interpretasi hasil analitik dan pengambilan kesimpulan berdasarkan data yang diperoleh, dengan bantuan AI hanya untuk merapikan penyampaian penjelasan agar lebih mudah dipahami.
- Perancangan struktur dan konten README, termasuk menentukan informasi yang perlu disampaikan. AI digunakan untuk membantu menyusun ulang kalimat, memperbaiki alur dokumentasi, dan meningkatkan keterbacaan.

### 13.3 Refleksi

AI berperan sebagai alat pendukung dalam proses pengembangan, terutama dalam membantu diagnosis masalah, mengevaluasi pendekatan yang digunakan, serta memberikan alternatif solusi terhadap permasalahan teknis yang ditemukan.

Salah satu kontribusi signifikan AI adalah membantu mengidentifikasi permasalahan unstable pagination setelah ditemukan adanya kejanggalan pada hasil data yang telah dikumpulkan. Meskipun proses scraping terlihat berhasil dan seluruh validasi awal menunjukkan hasil yang sesuai, pemeriksaan lebih lanjut menunjukkan adanya kehilangan sekitar 22% data. Berdasarkan diskusi dengan AI, permasalahan tersebut dianalisis dan menghasilkan rekomendasi penggunaan strategi convergent crawling sebagai pendekatan alternatif.

Namun, seluruh rekomendasi dari AI tetap harus diverifikasi terhadap kondisi nyata. Beberapa masukan dan asumsi yang diberikan AI terbukti tidak sesuai setelah dilakukan pengujian langsung terhadap sumber data SINTA maupun hasil implementasi.

| Masukan/Asumsi AI | Hasil Verifikasi |
|---|---|
| Selector `journal-meta`, `stat-prof` dapat digunakan untuk mengambil data tertentu | Tidak sesuai; struktur HTML aktual menggunakan nama elemen seperti `profile-id` dan `stat-prev`, yang ditemukan melalui inspeksi DevTools manual |
| POST accreditation filter dapat digunakan untuk mendapatkan data sesuai kategori tertentu | Tidak sesuai; server mengabaikan filter tersebut sehingga partisi S1 menghasilkan 431 data, bukan 268 data yang diharapkan |
| Path file pada script batch sudah sesuai | Tidak sesuai; menyebabkan hasil crawl pada 2 jam pertama tidak tersimpan dengan benar |
| Jurnal tanpa link Google Scholar tidak memiliki metrik terkait | Tidak sesuai; hasil query verifikasi menunjukkan bahwa sebagian besar kasus masih memiliki data metrik |
| Relasi departemen dan afiliasi dapat dimodelkan sebagai relasi one-to-many | Tidak sesuai; hasil analisis menunjukkan bahwa relasi sebenarnya bersifat many-to-many sehingga membutuhkan perubahan desain skema |
| Penamaan file hasil batch sudah aman untuk seluruh proses scheduling | Tidak sesuai; menyebabkan hasil batch pada 17 Juli tertimpa oleh batch 21 Juli |

Beberapa temuan tersebut ditemukan melalui proses verifikasi manual, pengujian implementasi, serta pemeriksaan kembali terhadap sumber data SINTA. Temuan tersebut kemudian digunakan untuk memperbaiki implementasi dan menyempurnakan desain yang telah dibuat.

Pelajaran utama dari penggunaan AI dalam proyek ini adalah bahwa AI sangat membantu dalam mempercepat eksplorasi masalah, memberikan perspektif alternatif, dan membantu menemukan kemungkinan solusi. Namun, hasil dari AI tidak dapat langsung dianggap benar tanpa validasi empiris. Setiap rekomendasi perlu diuji terhadap kondisi nyata karena struktur data, perilaku sistem, dan batasan implementasi dapat berbeda dari asumsi awal.

---

## 14. Referensi

### Library

| Library | Versi | Kegunaan |
|---|---|---|
| [requests](https://requests.readthedocs.io/) | 2.32.3 | HTTP client |
| [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) | 4.12.3 | HTML parsing |
| [psycopg2-binary](https://www.psycopg.org/) | 2.9.12 | PostgreSQL adapter |

### Sumber Data

- **SINTA (Science and Technology Index)**, Kementerian Pendidikan Tinggi, Sains, dan Teknologi RI
- URL: https://sinta.kemdiktisaintek.go.id/journals
- Tanggal akses: 13, 17, dan 21 Juli 2026
- `robots.txt`: HTTP 404, tidak ada larangan crawling
- API publik: tidak tersedia

### Materi Rujukan

- Silberschatz, A., Korth, H. F., Sudarshan, S. *Database System Concepts*, 7th ed. : notasi E-R, weak entity, reduksi ke skema relasional
- Materi kuliah IF2140 Pemodelan Basis Data : E-R Model, Relational Database Design, Data Warehouse
- Kimball, R. *The Data Warehouse Toolkit* : pola bridge table dan surrogate "Unknown" member