<#
.SYNOPSIS
    Restores Windows settings from a rollback snapshot JSON.
.PARAMETER BackupPath
    Path to the rollback JSON file created by apply_settings.ps1
#>
param(
    [Parameter(Mandatory=$true)] [string]$BackupPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

function Write-Log {
    param([string]$msg)
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Output "[$ts] $msg"
}

if (-not (Test-Path $BackupPath)) {
    Write-Log "ERROR: Rollback file not found: $BackupPath"
    exit 1
}

Write-Log "Loading rollback snapshot: $BackupPath"
$backup = Get-Content $BackupPath | ConvertFrom-Json

# ── Power Mode ────────────────────────────────────────────────────────────
if ($backup.power_mode) {
    Write-Log "Restoring power mode: $($backup.power_mode)"
    powercfg /setactive $backup.power_mode
}

# ── Visual Effects ────────────────────────────────────────────────────────
if ($null -ne $backup.visual_effects_value) {
    Write-Log "Restoring visual effects setting: $($backup.visual_effects_value)"
    $regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects"
    Set-ItemProperty -Path $regPath -Name "VisualFXSetting" -Value $backup.visual_effects_value -Force
}

# ── File Explorer ─────────────────────────────────────────────────────────
$fePath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
if ($null -ne $backup.hide_ext) {
    Write-Log "Restoring file extension visibility."
    Set-ItemProperty -Path $fePath -Name "HideFileExt" -Value $backup.hide_ext -Force
}
if ($null -ne $backup.hidden) {
    Write-Log "Restoring hidden files setting."
    Set-ItemProperty -Path $fePath -Name "Hidden" -Value $backup.hidden -Force
}
if ($null -ne $backup.launch_to) {
    Write-Log "Restoring Explorer launch target."
    Set-ItemProperty -Path $fePath -Name "LaunchTo" -Value $backup.launch_to -Force
}
if ($null -ne $backup.start_track_docs) {
    Write-Log "Restoring recent files setting."
    Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer" `
        -Name "ShowRecent" -Value $backup.start_track_docs -Force
}

# ── USB Storage ───────────────────────────────────────────────────────────
if ($null -ne $backup.usb_start) {
    Write-Log "Restoring USB storage."
    Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\USBSTOR" `
        -Name "Start" -Value $backup.usb_start -Force
}

Write-Log "Rollback complete."
Write-Log "You may need to restart Explorer or log off for all changes to take effect."
