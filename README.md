# California EV Transition & Fuel Station Analytics

Geospatial data science project analyzing the spatial relationship between traditional gas stations and California's EV charging network. Goals include identifying **charging deserts** and ranking **gas-to-EV conversion** candidate sites.

See [detailed_phase_by_phase_technical_guide.md](detailed_phase_by_phase_technical_guide.md) for the full execution plan, methodology, and phased roadmap.

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

Edit `.env` and add:

- `NREL_API_KEY`: [NREL developer key](https://developer.nlr.gov/signup/) for AFDC EV station data (falls back to the rate-limited `DEMO_KEY`).
- `CENSUS_API_KEY`: [Census API key](https://api.census.gov/data/key_signup.html) for ACS demographics (required).

## Running the pipeline

Regenerate every output from the same code and data snapshot:

```bash
python run_pipeline.py                 # fetch fresh data, then run every step
python run_pipeline.py --skip-fetch    # reuse the latest raw snapshots in data/raw
python run_pipeline.py --from scoring  # resume from a step
python run_pipeline.py --list          # list the steps
```

Steps: fetch EV / gas / Census / highways → clean stations → tract coverage metrics → desert scores → conversion scores → sensitivity tables → interactive map. Each module can also be run on its own (e.g. `python src/analysis/desert_detection.py`), and notebooks 01–05 walk through the same phases with EDA.

View the results:

```bash
streamlit run app/streamlit_app.py
```

Run the tests (synthetic data, no network needed):

```bash
python -m pytest
```

## Project structure

```
├── data/
│   ├── raw/           # Downloaded snapshots (gitignored)
│   ├── processed/     # Cleaned GeoParquet layers
│   └── external/      # Tract shapefiles, population-weighted centroids
├── notebooks/         # Analysis notebooks (Phases 1–5)
├── src/               # Reusable pipeline modules
├── tests/             # pytest suite
├── outputs/           # Maps, GeoJSON, CSV exports
├── app/               # Streamlit viewer (Phase 5)
└── run_pipeline.py    # End-to-end runner
```

## Data sources

| Layer | Source |
|-------|--------|
| EV charging stations | [NREL AFDC API](https://developer.nlr.gov/docs/transportation/alt-fuel-stations-v1/) |
| Gas stations | [CEC Gas Stations (ArcGIS)](https://services.arcgis.com/BLN4oKB0N1YSgvY8/arcgis/rest/services/CA_GasStations/FeatureServer/0) |
| Demographics | [Census ACS 2024 5-year](https://www.census.gov/data/developers/data-sets/acs-5year.html) |
| Tract boundaries, highways | [Census TIGER/Line 2024](https://www.census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html) (tracts, primary roads) |
| Population-weighted tract centroids | [Census 2020 centers of population](https://www.census.gov/geographies/reference-files/time-series/geo/centers-population.html) |

## Methodology notes

- **EV supply** counts only open (`status_code = E`), public AFDC stations. Planned stations (`P`) are kept separately and drive the planned-infrastructure penalty in conversion scoring.
- **Tract metrics** use land area (`ALAND`) for densities. Distances and buffers are measured from each tract's population-weighted centroid. All distances are straight-line (EPSG:3310), not drive distance.
- **Desert score** (0–100) is a weighted sum of four components: gas access, population density, EV gap, and DCFC distance. Each component is a percentile rank across populated tracts. Severity labels are `severe_desert` (≥ 75), `moderate_desert` (50–75) and `adequate` (< 50). Zero-population and water-only tracts are labelled `not_scored`.
- **Conversion score** (0–100) combines the tract desert score (30 points), distance to the nearest open DCFC (25), population-density percentile plus highway proximity (20), and a flat 15-point site-suitability placeholder. It subtracts up to 10 points for nearby competing gas stations and up to 10 for a planned DCFC within 5 km. The placeholder affects absolute scores but not rankings. The desert score already includes DCFC distance and density, so those factors are partly counted twice by design.
- **Sensitivity**: each scenario re-scores tracts and candidates from scratch, varying one weight at a time (raw weight ×0.5 to ×2, then renormalized; effective weights are in `sensitivity_scenarios.csv`), equal weights, gas-access buffer, redundancy radius, EV supply metric, and normalization method. A candidate is marked stable if it ranks in the top 20 in at least half the scenarios, or in the top 50 in all of them.

## Status

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Project scaffold | Complete |
| 1 | Data acquisition | Complete |
| 2 | EDA and cleaning | Complete |
| 3 | Charging desert analysis | Complete |
| 4 | Conversion candidate scoring | Complete |
| 5 | Sensitivity, viz, delivery | Complete |

## Outputs

| File | Contents |
|------|----------|
| `outputs/geojson/charging_deserts.geojson` | Tract desert scores, components and severity (outlines simplified ~50 m for the web) |
| `data/processed/charging_deserts.parquet` | Same layer at full resolution (EPSG:3310); use this for spatial joins |
| `outputs/tables/conversion_candidates.csv` | Ranked gas stations with score breakdown and rationale |
| `outputs/tables/candidate_stability.csv` | Per-scenario ranks and stability flags |
| `outputs/tables/severity_sensitivity.csv` | Severity counts per scenario |
| `outputs/maps/charging_deserts.html` | Interactive map |

Rankings are model-based prioritization signals, not site-feasibility determinations.

## Limitations

- CEC gas station data is from around 2018. Stations that have since closed can still appear as candidates, and newer stations are missing. Check top-ranked sites against current imagery or listings.
- AFDC EV data changes frequently; all outputs should note the snapshot date.
- Distances are straight-line, which understates real access in mountainous and rural areas.
- Population-weighted centroids are from the 2020 Census; ACS demographics are 2020–2024 estimates.
- Spatial scores do not account for zoning, grid capacity, or land ownership.
