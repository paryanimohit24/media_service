# Deploy media_import_service to Cloud Run (yt-dlp direct)
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

Write-Host "Building Docker image..."
docker build -t $Image .
if ($LASTEXITCODE -ne 0) { throw "docker build failed" }

Write-Host "Pushing image..."
docker push $Image
if ($LASTEXITCODE -ne 0) { throw "docker push failed" }

Write-Host "Deploying to Cloud Run [$Service]..."

$EnvVars = "YT_DLP_AUTO_PROXY=false,YT_DLP_PROXY_FALLBACK_ATTEMPTS=0"
if ($env:YT_DLP_PROXY) {
    $EnvVars = "$EnvVars,YT_DLP_PROXY=$($env:YT_DLP_PROXY)"
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
