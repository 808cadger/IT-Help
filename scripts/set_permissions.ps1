<#
.SYNOPSIS
    Applies Windows ACL permissions to a file system path.
.PARAMETER TargetName
    The user or group to grant/deny access (e.g. "DOMAIN\User" or "BUILTIN\Administrators").
.PARAMETER ResourcePath
    The folder or file path to modify.
.PARAMETER AccessLevel
    One of: FullControl, Modify, ReadAndExecute, Read, Write, NoAccess
#>
param(
    [Parameter(Mandatory=$true)] [string]$TargetName,
    [Parameter(Mandatory=$true)] [string]$ResourcePath,
    [Parameter(Mandatory=$true)] [string]$AccessLevel
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Log {
    param([string]$msg)
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Output "[$ts] $msg"
}

if (-not (Test-Path $ResourcePath)) {
    Write-Log "ERROR: Resource path does not exist: $ResourcePath"
    exit 1
}

Write-Log "Target:   $TargetName"
Write-Log "Path:     $ResourcePath"
Write-Log "Access:   $AccessLevel"

try {
    $acl = Get-Acl -Path $ResourcePath
    Write-Log "Current ACL owner: $($acl.Owner)"

    if ($AccessLevel -eq "NoAccess") {
        # Deny all access
        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $TargetName,
            "FullControl",
            "ContainerInherit,ObjectInherit",
            "None",
            "Deny"
        )
        $acl.AddAccessRule($rule)
        Write-Log "Deny rule added for: $TargetName"
    } else {
        # Map string to FileSystemRights enum
        $rightsMap = @{
            "FullControl"      = [System.Security.AccessControl.FileSystemRights]::FullControl
            "Modify"           = [System.Security.AccessControl.FileSystemRights]::Modify
            "ReadAndExecute"   = [System.Security.AccessControl.FileSystemRights]::ReadAndExecute
            "Read"             = [System.Security.AccessControl.FileSystemRights]::Read
            "Write"            = [System.Security.AccessControl.FileSystemRights]::Write
        }
        $rights = $rightsMap[$AccessLevel]
        if (-not $rights) {
            Write-Log "ERROR: Unknown access level: $AccessLevel"
            exit 1
        }

        # Remove any existing Deny rules for this user
        $denies = $acl.Access | Where-Object {
            $_.IdentityReference -eq $TargetName -and
            $_.AccessControlType -eq "Deny"
        }
        foreach ($d in $denies) {
            $acl.RemoveAccessRule($d) | Out-Null
            Write-Log "  Removed existing Deny rule."
        }

        $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
            $TargetName,
            $rights,
            "ContainerInherit,ObjectInherit",
            "None",
            "Allow"
        )
        $acl.SetAccessRule($rule)
        Write-Log "Allow rule set: $AccessLevel for $TargetName"
    }

    Set-Acl -Path $ResourcePath -AclObject $acl
    Write-Log "ACL applied successfully to: $ResourcePath"

    # Show new ACL summary
    Write-Log ""
    Write-Log "Updated ACL:"
    (Get-Acl -Path $ResourcePath).Access |
        Select-Object IdentityReference, FileSystemRights, AccessControlType |
        ForEach-Object { Write-Log "  $($_.IdentityReference) : $($_.FileSystemRights) [$($_.AccessControlType)]" }

} catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    exit 1
}

Write-Log "Done."
