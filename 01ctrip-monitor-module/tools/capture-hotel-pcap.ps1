param(
    [string]$DeviceSerial = "emulator-5556",
    [string]$AdbPath = "D:\Program Files\.android\sdk\platform-tools\adb.exe",
    [int]$DurationSeconds = 0,
    [string]$OutputPrefix = "ctrip_hotel"
)

$ErrorActionPreference = "Stop"

function Invoke-Adb([string[]]$Arguments) {
    & $AdbPath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "adb failed: $($Arguments -join ' ')"
    }
}

if (!(Test-Path -LiteralPath $AdbPath)) {
    throw "adb not found: $AdbPath"
}

Invoke-Adb @("-s", $DeviceSerial, "root")
Invoke-Adb @("-s", $DeviceSerial, "wait-for-device")

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$remotePcap = "/sdcard/Download/${OutputPrefix}_${stamp}.pcap"
$remoteLog = "/sdcard/Download/${OutputPrefix}_${stamp}.tcpdump.log"

Write-Host "Starting tcpdump on $DeviceSerial"
Write-Host "Remote pcap: $remotePcap"

$startCommand = "rm -f '$remotePcap' '$remoteLog'; nohup tcpdump -i any -s 0 -w '$remotePcap' >'$remoteLog' 2>&1 & echo `$!"
$tcpdumpPid = (& $AdbPath -s $DeviceSerial shell $startCommand | Select-Object -Last 1).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($tcpdumpPid)) {
    throw "failed to start tcpdump"
}

Write-Host "tcpdump pid: $tcpdumpPid"
if ($DurationSeconds -gt 0) {
    Write-Host "Capturing for $DurationSeconds seconds..."
    Start-Sleep -Seconds $DurationSeconds
} else {
    Write-Host "Open Ctrip hotel detail now, then press Enter here to stop capture."
    [void](Read-Host)
}

Write-Host "Stopping tcpdump..."
& $AdbPath -s $DeviceSerial shell "kill -2 $tcpdumpPid 2>/dev/null; sleep 1; ls -l '$remotePcap' '$remoteLog' 2>/dev/null"
if ($LASTEXITCODE -ne 0) {
    throw "failed to stop tcpdump or list output"
}

Write-Host "Done. Pcap saved on device: $remotePcap"
