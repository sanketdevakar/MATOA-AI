# SENTINEL — Indian Army Surveillance Agent System

**Version 3.0.0**

SENTINEL is an advanced AI-powered multi-agent surveillance system designed for the Indian Army's border security operations. It leverages Google's Agent Development Kit (ADK), Gemini AI models, and Google Cloud Platform services to autonomously process security alerts through a coordinated pipeline of specialized agents.

## Overview

SENTINEL processes incoming alerts by:
1. **Vision Analysis**: Fetching satellite imagery and analyzing for security anomalies
2. **Intelligence Scoring**: Evaluating threat levels using historical data and geospatial context
3. **Patrol Planning**: Optimizing response routes and scheduling patrols
4. **Communications**: Drafting and publishing situation reports (SITREPs) in military format

The system integrates seamlessly with Google Cloud services including BigQuery for data storage, Cloud Storage for imagery, Pub/Sub for asynchronous processing, and Maps Platform for geospatial operations.

## Features

- **Multi-Agent AI Pipeline**: Sequential execution of Vision, Intel, Patrol, and Comms agents using Gemini 2.0 Flash
- **Asynchronous Processing**: Pub/Sub integration for scalable alert handling
- **Geospatial Intelligence**: Google Maps integration for satellite imagery, terrain analysis, and routing
- **Historical Analytics**: BigQuery-powered threat scoring based on 14-day incident history
- **Automated Scheduling**: Daily sector scans and patrol rotations
- **RESTful API**: FastAPI-based endpoints for alert ingestion and scan requests
- **Web Dashboard**: Simple HTML interface for monitoring and manual operations
- **Cloud Logging**: Structured logging throughout the system
- **Session Persistence**: Vertex AI session state management for production deployments

## Architecture

### Core Components

- **API Layer** (`api/`): FastAPI application handling HTTP requests
- **Agent Pipeline** (`adk/`): Google ADK agents and pipeline runner
- **Specialized Agents** (`agents/`): Individual agent implementations
- **Database Layer** (`db/`): BigQuery client and schema management
- **MCP Tools** (`mcp_tools/`): Google Cloud service integrations
- **Scheduler** (`scheduler/`): Automated daily scan operations
- **Frontend** (`frontend/`): Web interface
- **Utilities** (`utils/`): Logging and helper functions

### Data Flow

1. Alert received via `/api/v1/alert` endpoint
2. Stored in BigQuery with initial metadata
3. Published to Pub/Sub topic (if enabled)
4. ADK pipeline processes alert asynchronously:
   - Vision Agent: Satellite imagery analysis
   - Intel Agent: Threat scoring and historical context
   - Patrol Agent: Route planning and action scheduling
   - Comms Agent: SITREP generation and publishing
5. Results stored back to BigQuery and GCS

## Installation

### Prerequisites

- Python 3.8+
- Google Cloud Project with necessary APIs enabled
- Service Account with appropriate permissions

### Setup

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd sentinel
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:**
   Create a `.env` file with your settings (see Configuration section)

4. **Set up Google Cloud:**
   - Enable required APIs: BigQuery, Cloud Storage, Pub/Sub, Maps Platform, Vertex AI
   - Create service account and download JSON key to `sa-keys.json`
   - Create BigQuery dataset and GCS bucket as specified in config

5. **Initialize database:**
   ```bash
   python scripts/seed_db.py
   ```

## Configuration

All settings are managed via environment variables or `.env` file. Key configurations:

### Google Cloud
- `GCP_PROJECT_ID`: Your Google Cloud project ID
- `BQ_DATASET`: BigQuery dataset name (default: `sentinel_db`)
- `GCS_BUCKET_NAME`: Cloud Storage bucket for images
- `PUBSUB_TOPIC_ID`: Pub/Sub topic for alerts
- `USE_PUBSUB`: Enable asynchronous processing (default: true)

### AI Models
- `GEMINI_MODEL`: Gemini model version (default: `gemini-2.0-flash`)

### Security
- `COMMANDER_API_KEY`: API key for alert ingestion
- `GOOGLE_APPLICATION_CREDENTIALS`: Path to service account JSON

### Geospatial
- `GOOGLE_MAPS_API_KEY`: Google Maps Platform API key
- `SECTOR_COORDS`: JSON string mapping sector names to coordinates

See `config.py` for complete configuration options.

## Usage

### Running the Application

**Development mode:**
```bash
python main.py
```

**Production mode:**
```bash
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### API Endpoints

#### Alert Ingestion
```http
POST /api/v1/alert
Authorization: Bearer {commander_api_key}
Content-Type: application/json

{
  "alert_type": "intrusion",
  "sector": "SECTOR-1",
  "latitude": 34.15,
  "longitude": 74.85,
  "raw_payload": "optional raw data"
}
```

#### Manual Scan Request
```http
POST /api/v1/scan
Authorization: Bearer {commander_api_key}

{
  "sector": "SECTOR-1",
  "zoom": 14
}
```

#### Get Scan Image
```http
GET /api/v1/scan/{scan_id}/image
```

### Web Interface

Access the dashboard at `http://localhost:8000` (served by FastAPI).

### Demo Script

Run the demonstration:
```bash
python scripts/demo.py
```

## Project Structure

```
sentinel/
├── api/                    # FastAPI application
│   └── main.py
├── adk/                    # Agent Development Kit
│   ├── agents.py          # Agent definitions and pipeline
│   ├── runner.py          # Pipeline execution
│   └── tools.py           # Custom ADK tools
├── agents/                 # Specialized agent implementations
│   ├── command_agent.py
│   ├── comms_agent.py
│   ├── intel_agent.py
│   ├── patrol_agent.py
│   └── vision_agent.py
├── db/                     # Database layer
│   ├── bigquery_client.py
│   ├── models.py
│   └── bq_schema.sql
├── frontend/               # Web interface
│   └── index.html
├── mcp_tools/              # Google Cloud integrations
│   ├── calendar_tool.py
│   ├── gcs_tool.py
│   ├── geo_tool.py
│   ├── google_maps_tool.py
│   ├── notes_tool.py
│   ├── pubsub_tool.py
│   └── tasks_tool.py
├── scheduler/              # Automated tasks
│   └── daily_scan.py
├── scripts/                # Utility scripts
│   ├── demo.py
│   └── seed_db.py
├── utils/                  # Helper utilities
│   └── logger.py
├── config.py               # Configuration management
├── main.py                 # Application entry point
├── requirements.txt        # Python dependencies
└── README.md
```

## Dependencies

Key dependencies include:
- **FastAPI**: Web framework
- **Google ADK**: Agent development framework
- **Google Generative AI**: Gemini models
- **Google Cloud Libraries**: BigQuery, Storage, Pub/Sub, Logging
- **Pydantic**: Data validation
- **APScheduler**: Task scheduling
- **Rich**: Terminal formatting

See `requirements.txt` for complete list.

## Docker & Cloud Run Deployment

### Building the Docker Image

A `Dockerfile` is included in the repository for containerization.

```bash
# Build locally (optional for testing)
docker build -t sentinel:latest .

# Run locally
docker run -p 8080:8080 \
  -e GCP_PROJECT_ID=your-project \
  -e BQ_DATASET=sentinel_db \
  -e GCS_BUCKET_NAME=sentinel-vision-scans \
  -e GOOGLE_MAPS_API_KEY=your-key \
  -e USE_PUBSUB=false \
  sentinel:latest
```

### Deploying to Google Cloud Run

#### Prerequisites

1. **Google Cloud Project** with required APIs enabled:
   ```powershell
   gcloud services enable \
     run.googleapis.com \
     cloudbuild.googleapis.com \
     artifactregistry.googleapis.com \
     bigquery.googleapis.com \
     storage.googleapis.com \
     pubsub.googleapis.com \
     aiplatform.googleapis.com
   ```

2. **Service Account** with permissions:
   - `roles/bigquery.dataEditor` (BigQuery access)
   - `roles/storage.objectAdmin` (Cloud Storage access)
   - `roles/aiplatform.user` (Vertex AI access)
   - `roles/pubsub.publisher` (if using Pub/Sub)

#### Step 1: Build and Push Container Image

```powershell
$PROJECT_ID = "your-project-id"

gcloud builds submit --tag gcr.io/$PROJECT_ID/sentinel
```

#### Step 2: Deploy to Cloud Run

```powershell
$PROJECT_ID = "your-project-id"
$MAPS_KEY = "your-google-maps-api-key"
$GCS_BUCKET = "sentinel-vision-scans"
$SERVICE_ACCOUNT = "command-mind-service-account@$PROJECT_ID.iam.gserviceaccount.com"

gcloud run deploy sentinel `
  --image gcr.io/$PROJECT_ID/sentinel `
  --platform managed `
  --region asia-south1 `
  --allow-unauthenticated `
  --service-account $SERVICE_ACCOUNT `
  --set-env-vars `
GCP_PROJECT_ID=$PROJECT_ID,`
BQ_DATASET=sentinel_db,`
GCS_BUCKET_NAME=$GCS_BUCKET,`
USE_PUBSUB=false,`
GOOGLE_MAPS_API_KEY=$MAPS_KEY,`
APP_ENV=production
```

#### Step 3: Get Your Service URL

```powershell
gcloud run services describe sentinel --platform managed --region asia-south1 --format="value(status.url)"
```

The output is your deployed app URL (e.g., `https://sentinel-abc123.run.app`).

### Environment Variables for Production

| Variable | Required | Example | Notes |
|----------|----------|---------|-------|
| `GCP_PROJECT_ID` | Yes | `commandmind` | Google Cloud project ID |
| `BQ_DATASET` | Yes | `sentinel_db` | BigQuery dataset name |
| `GCS_BUCKET_NAME` | Yes | `sentinel-vision-scans` | Cloud Storage bucket for images |
| `GOOGLE_MAPS_API_KEY` | Yes | `AIza...` | Google Maps Platform API key |
| `USE_PUBSUB` | No | `false` | Enable Pub/Sub async processing (default: false) |
| `PUBSUB_TOPIC_ID` | Conditional | `sentinel-alerts` | Required if `USE_PUBSUB=true` |
| `APP_ENV` | No | `production` | Set to `production` for Cloud Run |
| `GEMINI_MODEL` | No | `gemini-2.0-flash` | AI model to use |

### MCP Toolbox Deployment

SENTINEL uses MCP Toolbox for BigQuery operations. You have two options:

**Option 1: Deploy Toolbox separately (Recommended)**
- Deploy MCP Toolbox as a separate Cloud Run service
- Set `MCP_TOOLBOX_URL` to the toolbox service URL
- Advantage: Decoupled services, easier scaling

**Option 2: Refactor to use direct BigQuery client (Alternative)**
- Modify `db/bigquery_client.py` to use `google-cloud-bigquery` directly
- No separate Toolbox service needed
- Advantage: Single Cloud Run deployment

Current setup uses Option 1. If deploying Toolbox:

```powershell
# Set MCP Toolbox URL in Cloud Run
gcloud run services update sentinel `
  --region asia-south1 `
  --update-env-vars MCP_TOOLBOX_URL=https://your-toolbox-service.run.app
```

### Troubleshooting Cloud Run

**Check service logs:**
```powershell
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=sentinel" \
  --limit=50 --project=$PROJECT_ID --format="value(textPayload)" --order=asc
```

**Verify service account permissions:**
```powershell
$PROJECT_ID = "your-project-id"
$SERVICE_ACCOUNT = "command-mind-service-account@$PROJECT_ID.iam.gserviceaccount.com"

gcloud projects get-iam-policy $PROJECT_ID `
  --flatten="bindings[].members" `
  --filter="bindings.members:serviceAccount:$SERVICE_ACCOUNT"
```

**Update environment variables:**
```powershell
gcloud run services update sentinel `
  --platform managed `
  --region asia-south1 `
  --update-env-vars USE_PUBSUB=true,PUBSUB_TOPIC_ID=sentinel-alerts
```

## Development

### Running Tests

```bash
# Add test commands as needed
```

### Code Style

Follow PEP 8 conventions. Use type hints and docstrings.

### Logging

The system uses structured logging via Google Cloud Logging. Logs are categorized by component (api, adk_runner, etc.).

## Security Considerations

- API endpoints require authentication via `X-API-Key` header
- Service account keys should be securely managed
- Sensitive configuration stored in environment variables
- Cloud resources should follow principle of least privilege

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Support

For support or questions, please contact the development team or create an issue in the repository.