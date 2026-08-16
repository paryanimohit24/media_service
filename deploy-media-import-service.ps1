# Deploy media_import_service to Cloud Run (yt-dlp + Geonode residential proxy)
# Project: music-ai-app-489904 | Region: asia-south1

$ErrorActionPreference = "Stop"
$Project = "music-ai-app-489904"
$Region = "asia-south1"
$Service = "media-import-service"
$Image = "asia-south1-docker.pkg.dev/$Project/music-ai-app/${Service}:latest"

Write-Host "Checking Docker daemon..."
docker info 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not running. Start it, then re-run."
}

$HasProxy = $false
if ($env:GEONODE_PROXY_URL) { $HasProxy = $true }
if ($env:GEONODE_PROXY_USERNAME -and $env:GEONODE_PROXY_PASSWORD) { $HasProxy = $true }
if ($env:YT_DLP_PROXY) { $HasProxy = $true }

if (-not $HasProxy) {
    Write-Warning "No residential proxy set. YouTube/TikTok/Snapchat need GEONODE_PROXY_USERNAME/PASSWORD or GEONODE_PROXY_URL."
}

Write-Host "Building Docker image..."
docker build -t $Image .
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }

Write-Host "Pushing image..."
docker push $Image
if ($LASTEXITCODE -ne 0) { throw "docker push failed" }

Write-Host "Deploying to Cloud Run [$Service]..."

$EnvVars = "GEONODE_ALLOW_DIRECT=false,YT_DLP_AUTO_PROXY=false"
if ($env:GEONODE_API_KEY) {
    $EnvVars = "GEONODE_API_KEY=$($env:GEONODE_API_KEY),GEONODE_ENABLED=true,$EnvVars"
}
if ($env:GEONODE_PROXY_URL) {
    $EnvVars = "$EnvVars,GEONODE_PROXY_URL=$($env:GEONODE_PROXY_URL)"
}
if ($env:GEONODE_PROXY_USERNAME) {
    $EnvVars = "$EnvVars,GEONODE_PROXY_USERNAME=$($env:GEONODE_PROXY_USERNAME)"
}
if ($env:GEONODE_PROXY_PASSWORD) {
    $EnvVars = "$EnvVars,GEONODE_PROXY_PASSWORD=$($env:GEONODE_PROXY_PASSWORD)"
}
if ($env:GEONODE_PROXY_HOST) {
    $EnvVars = "$EnvVars,GEONODE_PROXY_HOST=$($env:GEONODE_PROXY_HOST)"
}
if ($env:GEONODE_PROXY_PORT) {
    $EnvVars = "$EnvVars,GEONODE_PROXY_PORT=$($env:GEONODE_PROXY_PORT)"
}
if ($HasProxy) {
    $EnvVars = "$EnvVars,YT_DLP_PROXY_FALLBACK_ATTEMPTS=0"
} else {
    $EnvVars = "$EnvVars,YT_DLP_PROXY_FALLBACK_ATTEMPTS=3"
}

gcloud run deploy $Service `
    --image $Image `
    --region $Region `
    --project $Project `
    --port 8001 `
    --memory 1Gi `
    --cpu 1 `
    --timeout 360 `
    --min-instances 0 `
    --max-instances 3 `
    --set-env-vars $EnvVars `
    --allow-unauthenticated `
    --quiet

if ($LASTEXITCODE -ne 0) { throw "gcloud run deploy failed" }

$Url = gcloud run services describe $Service --region $Region --project $Project --format="value(status.url)"
Write-Host "Service URL: $Url"
