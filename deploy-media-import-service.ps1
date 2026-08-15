# Deploy media_import_service to Cloud Run (Instagram reel URL → audio)
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
  --set-env-vars "GEONODE_ENABLED=true,GEONODE_ALLOW_DIRECT=false,GEONODE_PROCESSING_MODE=async,GEONODE_PROXY_COUNTRY=US,YT_DLP_AUTO_PROXY=false,YT_DLP_PROXY_FALLBACK_ATTEMPTS=0" `
  --allow-unauthenticated `
  --quiet

$Url = gcloud run services describe $Service --region $Region --project $Project --format="value(status.url)"
Write-Host "Service URL: $Url"
Write-Host ""
Write-Host "If backend gets 403 from this service, in GCP Console add:"
Write-Host "  Principal: song-backend@music-ai-app-489904.iam.gserviceaccount.com"
Write-Host "  Role: Cloud Run Invoker"
Write-Host "  (on service media-import-service)"
