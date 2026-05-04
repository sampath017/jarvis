#!/bin/bash

# Configuration
PROJECT_ID="gen-lang-client-0513238373" # Update if different
REGION="us-central1"
SERVICE_NAME="jarvis-backend"
IMAGE_NAME="gcr.io/$PROJECT_ID/$SERVICE_NAME"

echo "🚀 Starting deployment for $SERVICE_NAME to Google Cloud Run..."

# 1. Enable necessary services
echo "🔧 Enabling Google Cloud APIs..."
gcloud services enable run.googleapis.com containerregistry.googleapis.com artifactregistry.googleapis.com --project $PROJECT_ID

# 2. Build and push the image using Cloud Build
echo "📦 Building and pushing container image..."
gcloud builds submit --tag $IMAGE_NAME . --project $PROJECT_ID

# 3. Deploy to Cloud Run
echo "🚢 Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image $IMAGE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --project $PROJECT_ID \
  --set-env-vars "GOOGLE_API_KEY=$GOOGLE_API_KEY" \
  --set-env-vars "LANGFUSE_PUBLIC_KEY=$LANGFUSE_PUBLIC_KEY" \
  --set-env-vars "LANGFUSE_SECRET_KEY=$LANGFUSE_SECRET_KEY" \
  --set-env-vars "LANGFUSE_BASE_URL=$LANGFUSE_BASE_URL"

echo "✅ Deployment complete!"
gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --project $PROJECT_ID --format 'value(status.url)'
