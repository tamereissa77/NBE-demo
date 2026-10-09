# Open the NBE demos from a remote Windows laptop as http://localhost:<port>.
# Run this ON THE LAPTOP, not on the demo PC. It forwards the portal's port over SSH, so the browser
# sees "localhost" and allows the microphone (D4 voice), which it refuses on a plain http://<ip> address.
# Nothing is opened on the demo PC's firewall: only its SSH port is used.
#
#   .\remote_tunnel.ps1 -Server <demo-pc-address> -User <windows-user>
#   .\remote_tunnel.ps1 -Server <demo-pc-address> -User <windows-user> -LocalPort 8301   # if the port is busy here
#
# -Server and -User default to the NBE_DEMO_HOST and NBE_DEMO_USER environment variables.
# Leave the window open while you use the demos; Ctrl+C closes the tunnel.
param(
    [string]$Server = $env:NBE_DEMO_HOST,
    [string]$User = $(if ($env:NBE_DEMO_USER) { $env:NBE_DEMO_USER } else { $env:USERNAME }),
    [int]$Port = 8200,                  # NBE_PORT on the demo PC
    [int]$LocalPort = 0,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
if (-not $Server) {
    Write-Host "Give the demo PC's address: .\remote_tunnel.ps1 -Server <address> (or set NBE_DEMO_HOST)." -ForegroundColor Red
    exit 1
}
if (-not $LocalPort) { $LocalPort = $Port }
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Host "ssh was not found. Install it with: Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0" -ForegroundColor Red
    exit 1
}

$url = "http://localhost:$LocalPort"
Write-Host "Tunnel: $url  ->  ${Server}:$Port  (as $User)" -ForegroundColor Green
Write-Host "Keep this window open. Ctrl+C closes the tunnel."

if (-not $NoBrowser) {
    # Open the browser once the tunnel answers (after the password or key prompt)
    Start-Job -ArgumentList $url, $LocalPort -ScriptBlock {
        param($url, $port)
        for ($i = 0; $i -lt 120; $i++) {
            try { (New-Object Net.Sockets.TcpClient("127.0.0.1", $port)).Close(); Start-Process $url; break }
            catch { Start-Sleep -Seconds 1 }
        }
    } | Out-Null
}

ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L "${LocalPort}:127.0.0.1:${Port}" "$User@$Server"
