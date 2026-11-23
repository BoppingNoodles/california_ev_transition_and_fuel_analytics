"""Shared synthetic fixtures. All geometry is in EPSG:3310 (metres)."""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Point, box

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CRS = "EPSG:3310"
TRACT_SIZE_M = 5_000


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def tract_grid():
    """A 5x5 grid of 5 km tracts; the last tract is unpopulated (e.g. a park)."""
    rows = []
    for i in range(5):
        for j in range(5):
            idx = i * 5 + j
            rows.append({
                "GEOID": f"06001{idx:06d}",
                "ALAND": TRACT_SIZE_M ** 2,
                "geometry": box(i * TRACT_SIZE_M, j * TRACT_SIZE_M, (i + 1) * TRACT_SIZE_M, (j + 1) * TRACT_SIZE_M),
            })
    return gpd.GeoDataFrame(rows, crs=CRS)


@pytest.fixture
def demographics(tract_grid, rng):
    pop = rng.integers(500, 8000, len(tract_grid)).astype(float)
    pop[-1] = 0
    return pd.DataFrame({
        "GEOID": tract_grid["GEOID"],
        "NAME": [f"Census Tract {k}; Alameda County; California" for k in range(len(tract_grid))],
        "total_population": pop,
        "median_income": rng.integers(30_000, 150_000, len(tract_grid)).astype(float),
    })


@pytest.fixture
def gas_stations(rng):
    xy = rng.uniform(0, 5 * TRACT_SIZE_M, size=(120, 2))
    return gpd.GeoDataFrame(
        {"station_id": np.arange(1, len(xy) + 1), "name": [f"Gas {k}" for k in range(len(xy))]},
        geometry=[Point(x, y) for x, y in xy],
        crs=CRS,
    )


@pytest.fixture
def ev_stations(rng):
    xy = rng.uniform(0, 5 * TRACT_SIZE_M, size=(40, 2))
    dcfc = rng.integers(0, 4, len(xy))
    l2 = rng.integers(0, 10, len(xy))
    return gpd.GeoDataFrame(
        {
            "station_id": np.arange(1, len(xy) + 1),
            "dcfc_ports": dcfc,
            "level1_ports": 0,
            "level2_ports": l2,
            "total_ev_ports": dcfc + l2,
        },
        geometry=[Point(x, y) for x, y in xy],
        crs=CRS,
    )


@pytest.fixture
def tract_metrics(tract_grid, demographics, gas_stations, ev_stations):
    """Runs the Phase 3.1 coverage-metrics steps on the synthetic layers."""
    from analysis import coverage_metrics as cm

    base = cm.prepare_tract_base(tract_grid, demographics)
    base = cm.add_reference_points(base, centroids_path=Path("does-not-exist.csv"))
    base = cm.agg_ev(ev_stations, base)
    base = cm.agg_gas(gas_stations, base)
    base = cm.gas_access(gas_stations, base, buffer_m=2000)
    base = cm.calculate_nearest_dcfc(ev_stations, base)
    return cm.create_final_metrics(base)
