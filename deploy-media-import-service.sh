#!/usr/bin/env bash
# Deploy media-import-service to Cloud Run (yt-dlp + optional Geonode residential proxy)
# Project: music-ai-app-489904 | Region: asia-south1
set -euo pipefail

PROJECT="music-ai-app-489904"
REGION="asia-south1"
SERVICE="media-import-service"
IMAGE="asia-south1-docker.pkg.dev/${PROJECT}/music-ai-app/${SERVICE}:latest"

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker and re-run." >&2
  exit 1
fi

HAS_PROXY=false
if [[ -n "${GEONODE_PROXY_URL:-}" ]]; then
  HAS_PROXY=true
fi
if [[ -n "${GEONODE_PROXY_USERNAME:-}" && -n "${GEONODE_PROXY_PASSWORD:-}" ]]; then
  HAS_PROXY=true
fi
if [[ -n "${YT_DLP_PROXY:-}" ]]; then
  HAS_PROXY=true
fi

if [[ "$HAS_PROXY" != "true" ]]; then
  echo "WARNING: No residential proxy configured." >&2
  echo "  YouTube / TikTok / Snapchat will fail from Cloud Run without:" >&2
  echo "    GEONODE_PROXY_URL  OR  GEONODE_PROXY_USERNAME + GEONODE_PROXY_PASSWORD" >&2
  echo "  (Geonode Scraper API key alone is NOT the proxy — use proxy dashboard creds.)" >&2
fi

echo "Building Docker image..."
docker build -t "$IMAGE" .

echo "Pushing image..."
docker push "$IMAGE"

ENV_VARS="GEONODE_ALLOW_DIRECT=false"
ENV_VARS+=",YT_DLP_AUTO_PROXY=false"

if [[ -n "${GEONODE_API_KEY:-}" ]]; then
  ENV_VARS+=",GEONODE_API_KEY=${GEONODE_API_KEY}"
  ENV_VARS+=",GEONODE_ENABLED=true"
fi

if [[ -n "${GEONODE_PROXY_URL:-}" ]]; then
  ENV_VARS+=",GEONODE_PROXY_URL=${GEONODE_PROXY_URL}"
fi
if [[ -n "${GEONODE_PROXY_USERNAME:-}" ]]; then
  ENV_VARS+=",GEONODE_PROXY_USERNAME=${GEONODE_PROXY_USERNAME}"
fi
if [[ -n "${GEONODE_PROXY_PASSWORD:-}" ]]; then
  ENV_VARS+=",GEONODE_PROXY_PASSWORD=${GEONODE_PROXY_PASSWORD}"
fi
if [[ -n "${GEONODE_PROXY_HOST:-}" ]]; then
  ENV_VARS+=",GEONODE_PROXY_HOST=${GEONODE_PROXY_HOST}"
fi
if [[ -n "${GEONODE_PROXY_PORT:-}" ]]; then
  ENV_VARS+=",GEONODE_PROXY_PORT=${GEONODE_PROXY_PORT}"
fi

if [[ "$HAS_PROXY" == "true" ]]; then
  ENV_VARS+=",YT_DLP_PROXY_FALLBACK_ATTEMPTS=0"
else
  ENV_VARS+=",YT_DLP_PROXY_FALLBACK_ATTEMPTS=3"
fi

echo "Deploying to Cloud Run [$SERVICE]..."
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --project "$PROJECT" \
  --port 8001 \
  --memory 1Gi \
  --cpu 1 \
  --timeout 360 \
  --min-instances 0 \
  --max-instances 3 \
  --set-env-vars "$ENV_VARS" \
  --allow-unauthenticated \
  --quiet

URL=$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT" --format="value(status.url)")
echo "Service URL: $URL"
echo ""
echo "Backend IAM (if 403): grant Cloud Run Invoker to song-backend@music-ai-app-489904.iam.gserviceaccount.com"
