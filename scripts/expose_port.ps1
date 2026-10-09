# Make the portal reachable from other computers as http://<this-pc-address>:<port>.
# Run ON THE DEMO PC in an Administrator PowerShell. Docker in WSL publishes the port on localhost only;
# this forwards it from the PC's network addresses and allows it through Windows Firewall.
#
#   .\expose_port.ps1                  # NBE_PORT from .env (8200 if unset)
#   .\expose_port.ps1 -Port 8300
#   .\expose_port.ps1 -From Any        # any network instead of Tailscale addresses only
#   .\expose_port.ps1 -Remove          # undo
#
# The microphone (D4 voice) stays blocked on such an address: browsers allow it only on localhost or
# https. Use scripts/remote_tunnel.ps1 for voice, or allow the address in the browser (see the end).
param(
    [int]$Port = 0,
    [string]$From = "100.64.0.0/10",   # Tailscale's address range
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Run this in an Administrator PowerShell." -ForegroundColor Red
    exit 1
}
if (-not $Port) {
    $envFile = Join-Path (Split-Path -Parent $PSScriptRoot) ".env"
    $line = if (Test-Path $envFile) { Select-String -Path $envFile -Pattern '^NBE_PORT=(\d+)' | Select-Object -First 1 }
    $Port = if ($line) { [int]$line.Matches[0].Groups[1].Value } else { 8200 }
}
$rule = "NBE demo portal $Port"

$addresses = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.|172\.)' }).IPAddress
netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=$Port | Out-Null
foreach ($a in $addresses) { netsh interface portproxy delete v4tov6 listenaddress=$a listenport=$Port | Out-Null }
Get-NetFirewallRule -DisplayName $rule -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Remove) {
    Write-Host "Port $Port is no longer forwarded or allowed."
    exit 0
}

# Listen on each network address, never on 0.0.0.0: a wildcard listener also takes 127.0.0.1:<port> away
# from WSL's own localhost forwarding and then forwards to itself. The target is the IPv6 loopback, where
# WSL publishes the port; unlike the WSL address it does not change when WSL restarts.
foreach ($a in $addresses) {
    netsh interface portproxy add v4tov6 listenaddress=$a listenport=$Port connectaddress=::1 connectport=$Port | Out-Null
}
New-NetFirewallRule -DisplayName $rule -Direction Inbound -Action Allow -Protocol TCP -LocalPort $Port -RemoteAddress $From | Out-Null

Write-Host "Port $Port is open to $From. From the other computer:" -ForegroundColor Green
foreach ($a in $addresses) { Write-Host "  http://${a}:$Port" }
Write-Host "For the microphone in Chrome or Edge on that computer: open chrome://flags/#unsafely-treat-insecure-origin-as-secure,"
Write-Host "add the address above, enable the flag and relaunch."
