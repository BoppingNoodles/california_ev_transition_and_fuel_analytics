"""
Shared configuration: paths, CRS constants, and small constants used
across ingest / transform / analysis / viz modules.
"""
from pathlib import Path
from datetime import date
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed yet; fall back to raw os.environ

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
EXTERNAL_DIR = DATA_DIR / "external"

OUTPUTS_DIR = PROJECT_ROOT / "outputs"
MAPS_DIR = OUTPUTS_DIR / "maps"
GEOJSON_DIR = OUTPUTS_DIR / "geojson"
TABLES_DIR = OUTPUTS_DIR / "tables"

for d in (RAW_DIR, PROCESSED_DIR, EXTERNAL_DIR, MAPS_DIR, GEOJSON_DIR, TABLES_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# CRS
# ---------------------------------------------------------------------------
CRS_ANALYSIS = "EPSG:3310"   # California Albers — use for buffers/distances
CRS_WEB = "EPSG:4326"        # WGS84 — use for web maps / exports

# ---------------------------------------------------------------------------
# API keys / secrets
# ---------------------------------------------------------------------------
NREL_API_KEY = os.environ.get("NREL_API_KEY", "DEMO_KEY")

# ---------------------------------------------------------------------------
# Source endpoints
# ---------------------------------------------------------------------------
AFDC_API_URL = "https://developer.nlr.gov/api/alt-fuel-stations/v1.json"
CEC_GAS_STATIONS_URL = (
    "https://services.arcgis.com/BLN4oKB0N1YSgvY8/arcgis/rest/services/"
    "CA_GasStations/FeatureServer/0/query"
)

# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
TODAY_STR = date.today().isoformat()  # stamp raw snapshots with pull date
CA_STATE_ABBR = "CA"