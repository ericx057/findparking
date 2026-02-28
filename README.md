# findparking

Probabilistic parking availibility estimator. Intakes mix of different information, inputs into weighted average. The goal for this project is to drop the amount of time required looking for parking spaces. Lets say I want to go to the beach downtown but I'm not sure if I want to bus or drive, I would then reference this to find a probabilistic result on the closest known parking lots.

## Architecture

- **Backend:** FastAPI + SQLite -- serves probability data via REST API
- **Frontend:** Leaflet.js map with color-coded pins and detail cards
- **CV Pipeline:** OpenCV frame ingestion, YOLOv8n detection, DeepSORT tracking, virtual tripwire counting

## Setup

```bash
# Backend only (lightweight)
make install

# With CV pipeline dependencies (~2 GB)
make install-cv
```

## Running

```bash
# Start the backend server
make run-backend

# Seed parking lot data
make seed

# Run mock event generator (for development/demo)
make run-mock

# Run real CV pipeline
make run-pipeline

# Run tests
make test
```

## API Endpoints

- `GET /api/health` -- health check
- `GET /api/lots` -- all lots with probability scores
- `GET /api/lots/{id}` -- single lot detail with trend data
- `GET /api/lots/{id}/history` -- occupancy time series
- `POST /api/lots/{id}/events` -- record a vehicle crossing event
