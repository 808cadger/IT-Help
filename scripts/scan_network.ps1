<#
.SYNOPSIS
    Scans the local subnet and collects WMI data from discovered Windows machines.
.PARAMETER Subnet
    Subnet to scan, e.g. "192.168.1"
.PARAMETER OutputJson
    Path to write results JSON.
#>
param(
    [Parameter(Mandatory=$false)] [string]$Subnet = "",
    [Parameter(Mandatory=$false)] [string]$OutputJson = ".\scan_results.json"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "SilentlyContinue"

function Write-Log {
    param([string]$msg)
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Output "[$ts] $msg"
}

# Auto-detect subnet if not provided
if (-not $Subnet) {
    $ip = (Get-NetIPAddress -AddressFamily IPv4 |
           Where-Object { $_.IPAddress -notmatch "^127\." -and $_.PrefixLength -le 24 } |
           Select-Object -First 1)
    if ($ip) {
        $parts = $ip.IPAddress -split "\."
        $Subnet = "$($parts[0]).$($parts[1]).$($parts[2])"
    }
}

Write-Log "Scanning subnet: $Subnet.0/24"

$results = @()

# Local machine first
$localOS  = Get-WmiObject Win32_OperatingSystem
$localCPU = Get-WmiObject Win32_Processor | Select-Object -First 1
$localDisk = Get-WmiObject Win32_LogicalDisk -Filter "DriveType=3 AND DeviceID='C:'"
$localCS  = Get-WmiObject Win32_ComputerSystem

$localFree  = if ($localDisk) { [math]::Round($localDisk.FreeSpace / 1GB, 1) } else { 0 }
$localTotal = if ($localDisk) { $localDisk.Size } else { 1 }
$localPct   = if ($localTotal -gt 0) { [math]::Round((1 - $localDisk.FreeSpace / $localTotal) * 100, 1) } else { 0 }

$results += [PSCustomObject]@{
    hostname      = $env:COMPUTERNAME
    ip_address    = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch "^127\." } | Select-Object -First 1).IPAddress
    cpu_model     = $localCPU.Name.Trim()
    cores         = $localCPU.NumberOfLogicalProcessors
    ram_gb        = [math]::Round($localCS.TotalPhysicalMemory / 1GB, 1)
    disk_gb_free  = $localFree
    disk_pct_used = $localPct
    os_version    = $localOS.Caption
    status        = "online"
    last_seen     = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
    uptime_hours  = [math]::Round(($localOS.LocalDateTime - $localOS.LastBootUpTime.SubString(0,14) -as [datetime]).TotalHours, 1) 2>$null
    cpu_pct       = (Get-WmiObject Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
    mem_pct       = [math]::Round((1 - $localOS.FreePhysicalMemory / $localOS.TotalVisibleMemorySize) * 100, 1)
}

# Sweep subnet
if ($Subnet) {
    $jobs = 1..254 | ForEach-Object {
        $ip = "$Subnet.$_"
        Start-Job -ScriptBlock {
            param($targetIP)
            if (Test-Connection -ComputerName $targetIP -Count 1 -Quiet -ErrorAction SilentlyContinue) {
                $targetIP
            }
        } -ArgumentList $ip
    }

    Write-Log "Waiting for ping sweep..."
    $online = $jobs | Wait-Job | Receive-Job
    $jobs | Remove-Job

    Write-Log "Found $($online.Count) additional online host(s)."

    foreach ($ip in $online) {
        Write-Log "  Querying $ip via WMI..."
        try {
            $wmiOS   = Get-WmiObject -ComputerName $ip Win32_OperatingSystem -ErrorAction Stop
            $wmiCPU  = Get-WmiObject -ComputerName $ip Win32_Processor | Select-Object -First 1
            $wmiDisk = Get-WmiObject -ComputerName $ip Win32_LogicalDisk -Filter "DriveType=3 AND DeviceID='C:'"
            $wmiCS   = Get-WmiObject -ComputerName $ip Win32_ComputerSystem

            $diskFree = if ($wmiDisk) { [math]::Round($wmiDisk.FreeSpace / 1GB, 1) } else { 0 }
            $diskPct  = if ($wmiDisk -and $wmiDisk.Size -gt 0) {
                [math]::Round((1 - $wmiDisk.FreeSpace / $wmiDisk.Size) * 100, 1)
            } else { 0 }

            $results += [PSCustomObject]@{
                hostname      = $wmiCS.Name
                ip_address    = $ip
                cpu_model     = $wmiCPU.Name.Trim()
                cores         = $wmiCPU.NumberOfLogicalProcessors
                ram_gb        = [math]::Round($wmiCS.TotalPhysicalMemory / 1GB, 1)
                disk_gb_free  = $diskFree
                disk_pct_used = $diskPct
                os_version    = $wmiOS.Caption
                status        = "online"
                last_seen     = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
                uptime_hours  = 0
                cpu_pct       = ($wmiCPU.LoadPercentage -as [double])
                mem_pct       = [math]::Round((1 - $wmiOS.FreePhysicalMemory / $wmiOS.TotalVisibleMemorySize) * 100, 1)
            }
        } catch {
            Write-Log "  WARNING: WMI failed on $ip : $_"
            $results += [PSCustomObject]@{
                hostname      = $ip
                ip_address    = $ip
                cpu_model     = "Unknown"
                cores         = 0
                ram_gb        = 0
                disk_gb_free  = 0
                disk_pct_used = 0
                os_version    = "Unknown"
                status        = "online"
                last_seen     = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
                uptime_hours  = 0
                cpu_pct       = 0
                mem_pct       = 0
            }
        }
    }
}

$results | ConvertTo-Json -Depth 5 | Set-Content -Path $OutputJson -Force
Write-Log "Scan complete. $($results.Count) device(s) found. Results: $OutputJson"
