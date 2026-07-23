"""
csv_to_json.py -- konversi hasil export CSV batch menjadi JSON.

LATAR BELAKANG
--------------
scrape_batch2.py menulis ke nama file tetap (metric_snapshots_batch2.json),
sehingga batch yang dijalankan berikutnya menimpa batch sebelumnya. Data
batch 17 Juli akibatnya hanya tersimpan di dalam database.

Script ini memulihkan data tersebut dari hasil export CSV agar dapat
dimuat ulang setelah database di-rebuild.

CARA PAKAI
----------
1. Export dari database terlebih dahulu:

   psql -U postgres -d sinta_db -A -F"," -t ^
     -c "COPY (SELECT journal_id, captured_at, impact, h5_index, citations, citations_5yr FROM metric_snapshot WHERE captured_at::date = '2026-07-17') TO STDOUT WITH CSV HEADER" ^
     > "Data Scraping/data/batch2_17juli.csv"

2. Jalankan script ini:

   python csv_to_json.py batch2_17juli.csv metric_snapshots_20260717.json
"""

import csv
import json
import pathlib
import sys

DATA = pathlib.Path(__file__).parent.parent / "data"


def to_num(v, as_int=False):
    """Konversi string CSV menjadi angka, kosong menjadi None."""
    if v is None or v.strip() == "":
        return None
    try:
        return int(float(v)) if as_int else float(v)
    except ValueError:
        return None


def main(src_name: str, dst_name: str) -> None:
    src = DATA / src_name
    dst = DATA / dst_name

    if not src.exists():
        sys.exit(f"File tidak ditemukan: {src}")

    # PowerShell menulis file redirect (">") dengan encoding UTF-16LE
    # beserta BOM, bukan UTF-8. Encoding dideteksi dari byte pertama:
    # 0xFF 0xFE menandakan UTF-16LE, 0xEF 0xBB 0xBF menandakan UTF-8 BOM.
    head = src.open("rb").read(4)
    if head[:2] == b"\xff\xfe":
        enc = "utf-16"
    elif head[:3] == b"\xef\xbb\xbf":
        enc = "utf-8-sig"
    else:
        enc = "utf-8"
    print(f"  encoding   : {enc}")

    rows = []
    with src.open(encoding=enc, newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "journal_id":    int(r["journal_id"]),
                "captured_at":   r["captured_at"],
                "impact":        to_num(r["impact"]),
                "h5_index":      to_num(r["h5_index"], as_int=True),
                "citations":     to_num(r["citations"], as_int=True),
                "citations_5yr": to_num(r["citations_5yr"], as_int=True),
            })

    dst.write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                   encoding="utf-8")

    stamps = sorted({r["captured_at"][:10] for r in rows})
    print(f"  baris      : {len(rows):,}")
    print(f"  tanggal    : {', '.join(stamps)}")
    print(f"  tersimpan  : {dst}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("Cara pakai: python csv_to_json.py <input.csv> <output.json>")
    main(sys.argv[1], sys.argv[2])