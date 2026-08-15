#!/usr/bin/env bash
# Deploy media-import-service to Cloud Run (Geonode Scraper API)
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

if [[ -z "${GEONODE_API_KEY:-}" ]]; then
  echo "Set GEONODE_API_KEY before deploy (Geonode Scraper API key)." >&2
  exit 1
fi

echo "Building Docker image..."
docker build -t "$IMAGE" .

echo "Pushing image..."
docker push "$IMAGE"

ENV_VARS="GEONODE_API_KEY=${GEONODE_API_KEY}"
ENV_VARS+=",GEONODE_ENABLED=true"
ENV_VARS+=",GEONODE_ALLOW_DIRECT=false"
ENV_VARS+=",GEONODE_PROCESSING_MODE=async"
ENV_VARS+=",GEONODE_PROXY_COUNTRY=US"
ENV_VARS+=",YT_DLP_AUTO_PROXY=false"
ENV_VARS+=",YT_DLP_PROXY_FALLBACK_ATTEMPTS=0"

if [[ -n "${GEONODE_PROXY_URL:-}" ]]; then
  ENV_VARS+=",GEONODE_PROXY_URL=${GEONODE_PROXY_URL}"
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
