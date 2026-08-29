#!/usr/bin/env bash
# Deploy media-import-service to Cloud Run (yt-dlp direct)
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

echo "Building Docker image..."
docker build -t "$IMAGE" .

echo "Pushing image..."
docker push "$IMAGE"

ENV_VARS="YT_DLP_AUTO_PROXY=false,YT_DLP_PROXY_FALLBACK_ATTEMPTS=0"

if [[ -n "${YT_DLP_PROXY:-}" ]]; then
  ENV_VARS+=",YT_DLP_PROXY=${YT_DLP_PROXY}"
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
