# Configuration
$CURRENT_PROJECT = gcloud config get-value project
$PROJECT_ID = $CURRENT_PROJECT 
$REGION = "asia-south1"  # Mumbai (Closer to India)
$SERVICE_NAME = "jarvis-backend"
# Use a timestamped tag to force a fresh build and bust caches
$TAG = Get-Date -Format "yyyyMMdd-HHmmss"
$IMAGE_NAME = "gcr.io/${PROJECT_ID}/${SERVICE_NAME}:${TAG}"

Write-Host "Starting deployment for $SERVICE_NAME to Google Cloud Run (Region: $REGION)..." -ForegroundColor Cyan
Write-Host "Project: $PROJECT_ID" -ForegroundColor Gray
Write-Host "Image: $IMAGE_NAME" -ForegroundColor Gray

# Load environment variables from .env if it exists
if (Test-Path ".env") {
    Write-Host "Loading environment variables from .env..." -ForegroundColor Gray
    $env_lines = Get-Content .env
    foreach ($line in $env_lines) {
        if ($line -match "=") {
            $parts = $line.Split('=', 2)
            $name = $parts[0].Trim()
            $value = $parts[1].Trim()
            # Set in current process so we can pass them to gcloud
            [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

# 1. Enable necessary services
Write-Host "Enabling Google Cloud APIs..." -ForegroundColor Yellow
gcloud services enable run.googleapis.com containerregistry.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com --project $PROJECT_ID

# 2. Build and push the image using Cloud Build
Write-Host "Building and pushing container image (Timestamp: $TAG)..." -ForegroundColor Yellow
gcloud builds submit --tag $IMAGE_NAME . --project $PROJECT_ID

# 3. Deploy to Cloud Run
Write-Host "Deploying to Cloud Run in $REGION..." -ForegroundColor Yellow
gcloud run deploy $SERVICE_NAME `
  --image $IMAGE_NAME `
  --platform managed `
  --region $REGION `
  --allow-unauthenticated `
  --project $PROJECT_ID `
  --memory 512Mi `
  --cpu 2 `
  --timeout 300 `
  --set-env-vars "GOOGLE_API_KEY=$($env:GOOGLE_API_KEY),LANGFUSE_PUBLIC_KEY=$($env:LANGFUSE_PUBLIC_KEY),LANGFUSE_SECRET_KEY=$($env:LANGFUSE_SECRET_KEY),LANGFUSE_BASE_URL=$($env:LANGFUSE_BASE_URL),USE_VERTEX_AI=$($env:USE_VERTEX_AI),GOOGLE_CLOUD_PROJECT=$($PROJECT_ID),GOOGLE_MODEL_ID=$($env:GOOGLE_MODEL_ID)"

Write-Host "Deployment complete!" -ForegroundColor Green
$SERVICE_URL = gcloud run services describe $SERVICE_NAME --platform managed --region $REGION --project $PROJECT_ID --format 'value(status.url)'
Write-Host "Service URL: $SERVICE_URL" -ForegroundColor Cyan
