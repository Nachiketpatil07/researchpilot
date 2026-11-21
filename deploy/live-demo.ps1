<#
Share the LIVE app from your own PC (for interviews), through a free Cloudflare quick tunnel.

    powershell -ExecutionPolicy Bypass -File deploy\live-demo.ps1 -Site https://your-site.vercel.app

Starts the API in demo mode (read-only, per-visitor rate limits, CORS for *.vercel.app),
opens a tunnel (no Cloudflare account needed), and prints a link like
    https://your-site.vercel.app/?api=https://random-words.trycloudflare.com
Anyone with the link uses the real backend while this script runs. Ctrl+C stops both.

Requires cloudflared:  winget install --id Cloudflare.cloudflared
#>
param(
    [string]$Site = "",
    [int]$Port = 8000
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $env:USERPROFILE ".venvs\researchpilot\Scripts\python.exe"

$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    $guess = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
    if (Test-Path $guess) { $cf = Get-Item $guess } else {
        Write-Host "cloudflared is not installed. Install it with:  winget install --id Cloudflare.cloudflared" -ForegroundColor Yellow
        exit 1
    }
}
$cfPath = if ($cf.Source) { $cf.Source } else { $cf.FullName }

# The API inherits these from this process.
$env:DEMO_MODE = "true"
$env:CORS_ORIGIN_REGEX = 'https://.*\.vercel\.app'

Write-Host "Starting the API on port $Port (demo mode)..."
$api = Start-Process $py -ArgumentList "-m", "uvicorn", "app.api:app", "--port", "$Port" `
    -WorkingDirectory (Join-Path $root "backend") -PassThru -NoNewWindow
$tunnel = $null
$log = Join-Path $env:TEMP "researchpilot-tunnel.log"
try {
    for ($i = 0; $i -lt 90; $i++) {
        try { $null = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 5; break } catch { Start-Sleep 2 }
        if ($api.HasExited) { throw "The API exited. Is another server already using port $Port or the index?" }
    }
    Write-Host "API is up. Opening a Cloudflare tunnel..."
    Remove-Item $log -ErrorAction SilentlyContinue
    $tunnel = Start-Process $cfPath -ArgumentList "tunnel", "--url", "http://localhost:$Port", "--no-autoupdate" `
        -RedirectStandardError $log -PassThru -NoNewWindow
    $url = $null
    for ($i = 0; $i -lt 60 -and -not $url; $i++) {
        Start-Sleep 1
        if (Test-Path $log) {
            $m = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" | Select-Object -First 1
            if ($m) { $url = $m.Matches[0].Value }
        }
    }
    if (-not $url) { throw "No tunnel URL after 60 s. See $log" }

    Write-Host ""
    Write-Host "Live backend: $url" -ForegroundColor Green
    if ($Site) {
        Write-Host "Share this link: $($Site.TrimEnd('/'))/?api=$url" -ForegroundColor Green
    } else {
        Write-Host "Open your Vercel site with ?api=$url appended." -ForegroundColor Green
    }
    Write-Host "Press Ctrl+C to stop sharing."
    Wait-Process -Id $tunnel.Id
}
finally {
    foreach ($p in @($tunnel, $api)) { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force } }
    Write-Host "Stopped the tunnel and the API."
}
