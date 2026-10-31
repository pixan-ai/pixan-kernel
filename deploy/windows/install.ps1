# Installs one pixan-kernel agent on Windows (WSL2 + Docker Desktop).
# Run in an elevated PowerShell from this folder, after filling .env.
#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Need($cmd, $hint) { if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd not found. $hint" } }
Need wsl    'Install WSL2: wsl --install, then reboot.'
Need docker 'Install Docker Desktop (WSL2 backend) and start it.'
if (-not (Test-Path .env)) { throw 'Copy .env.example to .env and fill it first.' }

# The key file must be readable only by the current (dedicated agent) account and admins.
icacls .env /inheritance:r /grant:r "$($env:USERNAME):(R,W)" "Administrators:(F)" | Out-Null

# Disk encryption: warn (do not change) if BitLocker is off on the system drive.
$bl = Get-BitLockerVolume -MountPoint $env:SystemDrive -ErrorAction SilentlyContinue
if (-not $bl -or $bl.ProtectionStatus -ne 'On') { Write-Warning 'BitLocker is OFF on the system drive. Ask IT to enable it.' }

# Never sleep on AC power, so the agent stays up.
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

docker compose pull
docker compose up -d
Start-Sleep -Seconds 20
docker compose logs --tail 20
Write-Host 'Look for "heartbeat OK" above. Update: docker compose pull; docker compose up -d'
