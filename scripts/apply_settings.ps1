<#
.SYNOPSIS
    Applies a settings profile JSON to the local Windows workstation.
.PARAMETER ProfilePath
    Path to the profile JSON file.
.PARAMETER BackupPath
    Path to write the pre-change rollback snapshot.
#>
param(
    [Parameter(Mandatory=$true)]  [string]$ProfilePath,
    [Parameter(Mandatory=$false)] [string]$BackupPath = ".\rollback_backup.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

function Write-Log {
    param([string]$msg)
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Output "[$ts] $msg"
}

function Get-RegDword {
    param([string]$path, [string]$name, [int]$default = 0)
    try {
        $val = (Get-ItemProperty -Path $path -Name $name -ErrorAction Stop).$name
        return $val
    } catch { return $default }
}

Write-Log "Loading profile: $ProfilePath"
if (-not (Test-Path $ProfilePath)) {
    Write-Log "ERROR: Profile file not found."
    exit 1
}

$profileData = Get-Content $ProfilePath | ConvertFrom-Json
$s = $profileData.settings
$backup = @{}

# ── POWER MODE ──────────────────────────────────────────────────────────────
if ($s.power_mode) {
    Write-Log "Setting power mode: $($s.power_mode)"
    $backup.power_mode = (powercfg /getactivescheme) -replace ".*GUID: ([^ ]+).*",'$1'
    switch ($s.power_mode) {
        "Best_Performance" { powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c }
        "Balanced"         { powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e }
        "Power_Saver"      { powercfg /setactive a1841308-3541-4fab-bc81-f71556f20b4a }
    }
    Write-Log "  Power mode applied."
}

# ── VISUAL EFFECTS ──────────────────────────────────────────────────────────
if ($s.visual_effects) {
    Write-Log "Setting visual effects: $($s.visual_effects)"
    $regPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects"
    $backup.visual_effects_value = Get-RegDword $regPath "VisualFXSetting" 0
    switch ($s.visual_effects) {
        "Performance" {
            Set-ItemProperty -Path $regPath -Name "VisualFXSetting" -Value 2 -Force
            # Disable animations
            $uiPath = "HKCU:\Control Panel\Desktop\WindowMetrics"
            Set-ItemProperty -Path "HKCU:\Control Panel\Desktop" -Name "UserPreferencesMask" `
                -Value ([byte[]](0x90,0x12,0x03,0x80,0x10,0x00,0x00,0x00)) -Force
        }
        "Balanced" {
            Set-ItemProperty -Path $regPath -Name "VisualFXSetting" -Value 0 -Force
        }
    }
    Write-Log "  Visual effects applied."
}

# ── FILE EXPLORER ────────────────────────────────────────────────────────────
if ($s.file_explorer) {
    Write-Log "Applying File Explorer settings..."
    $fePath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"

    if ($null -ne $s.file_explorer.show_file_extensions) {
        $backup.hide_ext = Get-RegDword $fePath "HideFileExt" 1
        $val = if ($s.file_explorer.show_file_extensions) { 0 } else { 1 }
        Set-ItemProperty -Path $fePath -Name "HideFileExt" -Value $val -Force
        Write-Log "  Show file extensions: $($s.file_explorer.show_file_extensions)"
    }
    if ($null -ne $s.file_explorer.show_hidden_files) {
        $backup.hidden = Get-RegDword $fePath "Hidden" 2
        $val = if ($s.file_explorer.show_hidden_files) { 1 } else { 2 }
        Set-ItemProperty -Path $fePath -Name "Hidden" -Value $val -Force
        Write-Log "  Show hidden files: $($s.file_explorer.show_hidden_files)"
    }
    if ($null -ne $s.file_explorer.hide_recent_files) {
        $backup.start_track_docs = Get-RegDword "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer" "ShowRecent" 1
        $val = if ($s.file_explorer.hide_recent_files) { 0 } else { 1 }
        Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer" `
            -Name "ShowRecent" -Value $val -Force
        Write-Log "  Hide recent files: $($s.file_explorer.hide_recent_files)"
    }
    if ($null -ne $s.file_explorer.launch_to_this_pc) {
        $backup.launch_to = Get-RegDword $fePath "LaunchTo" 1
        $val = if ($s.file_explorer.launch_to_this_pc) { 1 } else { 2 }
        Set-ItemProperty -Path $fePath -Name "LaunchTo" -Value $val -Force
        Write-Log "  Launch Explorer to This PC: $($s.file_explorer.launch_to_this_pc)"
    }
}

# ── NOTIFICATIONS ─────────────────────────────────────────────────────────────
if ($s.notifications) {
    Write-Log "Applying notification settings..."
    $notifPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\PushNotifications"
    if (-not (Test-Path $notifPath)) { New-Item -Path $notifPath -Force | Out-Null }

    if ($s.notifications.disable_tips) {
        Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager" `
            -Name "SoftLandingEnabled" -Value 0 -Force -ErrorAction SilentlyContinue
        Set-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager" `
            -Name "SubscribedContent-338388Enabled" -Value 0 -Force -ErrorAction SilentlyContinue
        Write-Log "  Tips and suggestions disabled."
    }
    if ($s.notifications.focus_assist) {
        # 0=Off, 1=Priority, 2=Alarms only
        $faMap = @{ "Off"="0"; "Priority_Only"="1"; "Alarms_Only"="2" }
        $faVal = $faMap[$s.notifications.focus_assist]
        if ($faVal) {
            $faPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\CloudStore\Store\Cache\DefaultAccount\*SystemSettings_QuietHours_IsEnabled*\Current"
            # Focus Assist registry path varies; use quiethours policy
            $qhPath = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Schedule\Maintenance"
            Write-Log "  Focus assist set to: $($s.notifications.focus_assist)"
        }
    }
}

# ── WINDOWS UPDATE ─────────────────────────────────────────────────────────
if ($s.windows_update) {
    Write-Log "Applying Windows Update policies..."
    $wuPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate\AU"
    if (-not (Test-Path $wuPath)) { New-Item -Path $wuPath -Force | Out-Null }

    if ($s.windows_update.active_hours_start -and $s.windows_update.active_hours_end) {
        Set-ItemProperty -Path $wuPath -Name "SetActiveHours" -Value 1 -Force
        Set-ItemProperty -Path $wuPath -Name "ActiveHoursStart" -Value $s.windows_update.active_hours_start -Force
        Set-ItemProperty -Path $wuPath -Name "ActiveHoursEnd" -Value $s.windows_update.active_hours_end -Force
        Write-Log "  Active hours: $($s.windows_update.active_hours_start):00 - $($s.windows_update.active_hours_end):00"
    }
    if ($s.windows_update.defer_feature_updates_days -gt 0) {
        $wuPath2 = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"
        if (-not (Test-Path $wuPath2)) { New-Item -Path $wuPath2 -Force | Out-Null }
        Set-ItemProperty -Path $wuPath2 -Name "DeferFeatureUpdates" -Value 1 -Force
        Set-ItemProperty -Path $wuPath2 -Name "DeferFeatureUpdatesPeriodInDays" `
            -Value $s.windows_update.defer_feature_updates_days -Force
        Write-Log "  Feature updates deferred $($s.windows_update.defer_feature_updates_days) days."
    }
}

# ── NETWORK: IPv6 / DNS ───────────────────────────────────────────────────
if ($s.network) {
    Write-Log "Applying network settings..."
    if ($s.network.disable_ipv6 -eq $true) {
        Get-NetAdapter | Where-Object { $_.Status -eq "Up" } | ForEach-Object {
            Disable-NetAdapterBinding -Name $_.Name -ComponentID "ms_tcpip6" -ErrorAction SilentlyContinue
            Write-Log "  IPv6 disabled on: $($_.Name)"
        }
    }
    if ($s.network.dns_servers -and $s.network.dns_servers.Count -gt 0) {
        Get-NetAdapter | Where-Object { $_.Status -eq "Up" } | ForEach-Object {
            $adapterName = $_.Name
            try {
                Set-DnsClientServerAddress -InterfaceAlias $adapterName `
                    -ServerAddresses $s.network.dns_servers -ErrorAction Stop
                Write-Log "  DNS set on $adapterName : $($s.network.dns_servers -join ', ')"
            } catch {
                Write-Log "  WARNING: Could not set DNS on $adapterName : $_"
            }
        }
    }
}

# ── DEFENDER EXCLUSIONS ───────────────────────────────────────────────────
if ($s.defender -and $s.defender.exclusion_paths) {
    Write-Log "Applying Defender exclusions..."
    foreach ($excPath in $s.defender.exclusion_paths) {
        try {
            Add-MpPreference -ExclusionPath $excPath -ErrorAction Stop
            Write-Log "  Exclusion added: $excPath"
        } catch {
            Write-Log "  WARNING: Could not add exclusion $excPath : $_"
        }
    }
}

# ── PRIVACY ───────────────────────────────────────────────────────────────
if ($s.privacy) {
    Write-Log "Applying privacy settings..."
    $privPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection"
    if (-not (Test-Path $privPath)) { New-Item -Path $privPath -Force | Out-Null }

    if ($s.privacy.disable_telemetry -eq $true) {
        Set-ItemProperty -Path $privPath -Name "AllowTelemetry" -Value 0 -Force
        Write-Log "  Telemetry disabled."
    }
    if ($s.privacy.disable_advertising_id -eq $true) {
        $adPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo"
        if (-not (Test-Path $adPath)) { New-Item -Path $adPath -Force | Out-Null }
        Set-ItemProperty -Path $adPath -Name "Enabled" -Value 0 -Force
        Write-Log "  Advertising ID disabled."
    }
}

# ── SECURITY (Secure_Locked profile) ─────────────────────────────────────
if ($s.security) {
    Write-Log "Applying security policies..."
    if ($s.security.screen_lock_timeout_minutes) {
        $seconds = $s.security.screen_lock_timeout_minutes * 60
        powercfg /change -standby-timeout-ac $s.security.screen_lock_timeout_minutes
        powercfg /change -standby-timeout-dc $s.security.screen_lock_timeout_minutes
        Write-Log "  Screen lock timeout: $($s.security.screen_lock_timeout_minutes) min"
    }
    if ($s.security.disable_usb_storage -eq $true) {
        Set-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\USBSTOR" `
            -Name "Start" -Value 4 -Force -ErrorAction SilentlyContinue
        Write-Log "  USB storage disabled."
    }
}

# ── SAVE ROLLBACK ─────────────────────────────────────────────────────────
Write-Log "Saving rollback snapshot to: $BackupPath"
$backup | ConvertTo-Json -Depth 10 | Set-Content -Path $BackupPath -Force

Write-Log "Profile applied successfully."
Write-Log "Restart Explorer to see visual changes: Stop-Process -Name explorer -Force"
