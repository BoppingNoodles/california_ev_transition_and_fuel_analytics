# California EV Transition & Fuel Station Analytics

Geospatial data science project analyzing the spatial relationship between traditional gas stations and California's EV charging network. Goals include identifying **charging deserts** and ranking **gas-to-EV conversion** candidate sites.

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the full execution plan, methodology, and phased roadmap.

## Setup

**Requirements:** Python 3.11+

```bash
# Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt

# Configure API access
copy .env.example .env        # Windows
# cp .env.example .env        # macOS/Linux
```

Edit `.env` and add your [NREL API key](https://developer.nrel.gov/signup/) (free registration required for AFDC EV station data).

## Project structure

```
├── data/
│   ├── raw/           # Downloaded snapshots (gitignored)
│   ├── processed/     # Cleaned GeoJSON/Parquet
│   └── external/      # CA boundary, tract shapefiles
├── notebooks/         # Analysis notebooks (Phases 1–5)
├── src/               # Reusable pipeline modules
├── outputs/           # Maps, GeoJSON, CSV exports
└── app/               # Optional Streamlit viewer (Phase 5)
```

## Data sources

| Layer | Source |
|-------|--------|
| EV charging stations | [NREL AFDC API](https://developer.nrel.gov/docs/transportation/alt-fuel-stations-v1/) |
| Gas stations | [CEC Gas Stations (ArcGIS)](https://services.arcgis.com/BLN4oKB0N1YSgvY8/arcgis/rest/services/CA_GasStations/FeatureServer/0) |
| Demographics | [Census ACS / TIGER](https://www.census.gov/data.html) |

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Project scaffold | Complete |
| 1 | Data acquisition | Pending |
| 2 | EDA and cleaning | Pending |
| 3 | Charging desert analysis | Pending |
| 4 | Conversion candidate scoring | Pending |
| 5 | Sensitivity, viz, delivery | Pending |

## Findings

_Findings will be documented here after Phase 5._

## Limitations

- CEC gas station data (~2018) may not reflect current closures or new stations.
- AFDC EV data changes frequently; all outputs should note the snapshot date.
- Spatial scores do not account for zoning, grid capacity, or land ownership.
