# =====================================================================
# register_task.ps1 -- daftarkan pipeline ETL ke Windows Task Scheduler
# Seleksi Asisten Lab Basis Data 2026 | NIM 18224081  (BONUS)
#
# JALANKAN SEBAGAI ADMINISTRATOR, cukup SEKALI.
#
# Membuat scheduled task bernama "SINTA_ETL_Weekly" yang menjalankan
# run_etl.ps1 setiap Senin pukul 02:00 (jam sepi, sesuai etika scraping).
# =====================================================================

$ErrorActionPreference = "Stop"

$REPO      = "C:\Users\Illona Nasywa Hannum\Seleksi-2026-Tugas-1"
$SCRIPT    = Join-Path $REPO "Data Scraping\src\run_etl.ps1"
$TASK_NAME = "SINTA_ETL_Weekly"

if (-not (Test-Path $SCRIPT)) {
    throw "Tidak ditemukan: $SCRIPT"
}

# Aksi: jalankan PowerShell dengan script ETL
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$SCRIPT`""

# Pemicu: setiap Senin pukul 02:00
# Jam sepi dipilih agar beban ke server SINTA minimal.
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At 2:00AM

# Pengaturan: jalankan meski terlewat, batas 4 jam
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 30)

Register-ScheduledTask `
    -TaskName    $TASK_NAME `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -Description "Pipeline ETL SINTA: scrape -> load -> refresh warehouse. Anti-redundansi dijamin composite PK (journal_id, captured_at)." `
    -Force

Write-Host ""
Write-Host "Task '$TASK_NAME' berhasil didaftarkan." -ForegroundColor Green
Write-Host ""
Write-Host "Verifikasi:"
Write-Host "  Get-ScheduledTask -TaskName $TASK_NAME"
Write-Host ""
Write-Host "Jalankan manual sekarang (untuk uji):"
Write-Host "  Start-ScheduledTask -TaskName $TASK_NAME"
Write-Host ""
Write-Host "Lihat riwayat eksekusi:"
Write-Host "  Get-ScheduledTaskInfo -TaskName $TASK_NAME"
Write-Host ""
Write-Host "Hapus task:"
Write-Host "  Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:`$false"