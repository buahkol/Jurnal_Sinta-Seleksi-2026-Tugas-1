# =====================================================================
# run_etl.ps1 -- pipeline ETL otomatis untuk SINTA
# Seleksi Asisten Lab Basis Data 2026 | NIM 18224081  (BONUS)
#
# Menjalankan seluruh proses: scrape -> load -> refresh warehouse.
# Dirancang untuk dipanggil Windows Task Scheduler secara berkala.
#
# Anti-redundansi dijamin di level DATABASE, bukan di script:
#   * metric_snapshot PRIMARY KEY (journal_id, captured_at)
#   * seluruh INSERT memakai ON CONFLICT DO NOTHING
# Sehingga menjalankan script ini dua kali dengan data yang sama
# TIDAK menghasilkan baris ganda.
#
# Setup (jalankan SEKALI, sebagai Administrator):
#   .\register_task.ps1
#
# Uji manual:
#   .\run_etl.ps1
# =====================================================================

$ErrorActionPreference = "Stop"

# --- Konfigurasi -----------------------------------------------------
$REPO = "C:\Users\Illona Nasywa Hannum\Seleksi-2026-Tugas-1"
$LOG  = Join-Path $REPO "logs\etl_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# Password dibaca dari environment variable, TIDAK di-hardcode.
# Set sekali dengan:  setx PGPASSWORD "passwordmu"
if (-not $env:PGPASSWORD) {
    throw "PGPASSWORD belum di-set. Jalankan: setx PGPASSWORD `"passwordmu`""
}
$SRC_DSN = "postgresql://postgres@localhost:5432/sinta_db"
$DW_DSN  = "postgresql://postgres@localhost:5432/sinta_dw"

# --- Persiapan -------------------------------------------------------
New-Item -ItemType Directory -Force -Path (Split-Path $LOG) | Out-Null

function Log($msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $LOG -Value $line
}

Log "=== ETL PIPELINE MULAI ==="
Log "repo: $REPO"

try {
    # -----------------------------------------------------------------
    # TAHAP 1: Scrape batch baru
    # -----------------------------------------------------------------
    Log "--- Tahap 1/3: scraping ---"
    Set-Location (Join-Path $REPO "Data Scraping\src")
    python scrape_batch2.py --passes 3 2>&1 | ForEach-Object { Log $_ }
    if ($LASTEXITCODE -ne 0) { throw "scraping gagal (exit $LASTEXITCODE)" }

    # -----------------------------------------------------------------
    # TAHAP 2: Load ke database operasional
    #   ON CONFLICT DO NOTHING -> timestamp sama = no-op,
    #   timestamp baru = baris baru ditambahkan
    # -----------------------------------------------------------------
    Log "--- Tahap 2/3: load ke sinta_db ---"
    python load_batch2.py --dsn $SRC_DSN 2>&1 | ForEach-Object { Log $_ }
    if ($LASTEXITCODE -ne 0) { throw "load gagal (exit $LASTEXITCODE)" }

    # -----------------------------------------------------------------
    # TAHAP 3: Refresh data warehouse
    # -----------------------------------------------------------------
    Log "--- Tahap 3/3: refresh warehouse ---"
    Set-Location (Join-Path $REPO "Data Warehouse\src")
    python warehouse_load.py --src $SRC_DSN --dw $DW_DSN 2>&1 | ForEach-Object { Log $_ }
    if ($LASTEXITCODE -ne 0) { throw "warehouse load gagal (exit $LASTEXITCODE)" }

    # -----------------------------------------------------------------
    # Ringkasan: buktikan batch baru masuk tanpa duplikasi
    # -----------------------------------------------------------------
    Log "--- Ringkasan ---"
    $summary = psql -U postgres -d sinta_db -t -A -F' | ' -c @"
SELECT 'batch tersimpan: ' || COUNT(DISTINCT captured_at)
     || ' | total snapshot: ' || COUNT(*)
     || ' | jurnal unik: ' || COUNT(DISTINCT journal_id)
FROM metric_snapshot;
"@
    Log $summary

    Log "=== ETL PIPELINE SELESAI ==="
    exit 0
}
catch {
    Log "!!! GAGAL: $_"
    exit 1
}