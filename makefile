include .env 
export 
gcloud run deploy $env:SERVICE_NAME `
  --source . `
  --region $env:GOOGLE_CLOUD_LOCATION `
  --project $env:GOOGLE_CLOUD_PROJECT `
  --allow-unauthenticated `
  --port=8000 `
  --set-env-vars="GOOGLE_CLOUD_PROJECT=$env:GOOGLE_CLOUD_PROJECT,GOOGLE_CLOUD_LOCATION=$env:GOOGLE_CLOUD_LOCATION,GOOGLE_GENAI_USE_VERTEXAI=$env:GOOGLE_GENAI_USE_VERTEXAI"