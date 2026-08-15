# Manual proxy test (Windows PowerShell)
# 1. Copy .env.example -> .env and set YT_DLP_PROXY + TEST_REEL_URL
# 2. Run: .\test-with-proxy.ps1

param(
    [string]$ReelUrl = "",
    [string]$Proxy = "",
    [string]$OutFile = "proxy_test_output.m4a"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path ".env") {
    Get-Content ".env" | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $parts = $line.Split("=", 2)
            $key = $parts[0].Trim()
            $val = $parts[1].Trim().Trim('"').Trim("'")
            if ($key -and -not [string]::IsNullOrWhiteSpace($val)) {
                Set-Item -Path "env:$key" -Value $val
            }
        }
    }
    Write-Host "Loaded .env"
}

if ($Proxy) {
    $env:YT_DLP_PROXY = $Proxy
}

if (-not $ReelUrl) {
    $ReelUrl = $env:TEST_REEL_URL
}

if (-not $ReelUrl) {
    Write-Error "Pass -ReelUrl or set TEST_REEL_URL in .env"
}

Write-Host "Proxy: $($env:YT_DLP_PROXY)"
Write-Host "Reel:  $ReelUrl"

python test_import.py --out $OutFile $ReelUrl
exit $LASTEXITCODE
