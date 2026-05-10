# Sales Map System

A Streamlit application for enterprise customer mapping, geocoding, and route optimization.

## Features
- Address cleaning and standardization.
- Geocoding via Mapbox API with local caching.
- Interactive map visualization with MarkerCluster.
- Spatial radius filtering.
- Route optimization (TSP) via Mapbox Optimization API.
- One-click Google Maps navigation link generation.

## Installation
```bash
pip install -r requirements.txt
```

## Usage
1. Create a `.env` file with your `MAPBOX_API_KEY`.
2. Run the app:
```bash
streamlit run app.py
```
