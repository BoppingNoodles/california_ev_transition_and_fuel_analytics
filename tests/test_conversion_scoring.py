import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point

from analysis.conversion_scoring import calculate_gas_conv, planned_dcfc_penalty, score_candidates
from analysis.desert_detection import add_severity_labels, compute_desert_components, compute_desert_score

CRS = "EPSG:3310"


def test_planned_dcfc_penalty_tiers():
    gas = gpd.GeoDataFrame({"station_id": [1, 2, 3]},
                           geometry=[Point(0, 0), Point(4_000, 0), Point(20_000, 0)], crs=CRS)
    planned = gpd.GeoDataFrame({"dcfc_ports": [2, 0]},
                               geometry=[Point(1_000, 0), Point(20_000, 0)], crs=CRS)  # L2-only site is ignored
    out = planned_dcfc_penalty(gas, planned)
    assert out["planned_infra_penalty"].tolist() == [10.0, 5.0, 0.0]
    assert planned_dcfc_penalty(gas, None)["planned_infra_penalty"].tolist() == [0.0, 0.0, 0.0]


def _candidates(**overrides):
    df = pd.DataFrame({
        "station_id": [1, 2, 3],
        "desert_score": [60.0, 60.0, 60.0],
        "nearest_dcfc_km": [5.0, 5.0, 5.0],
        "population_density": [10.0, 1_000.0, 100.0],
        "total_population": [4_000, 4_000, 4_000],
        "nearest_highway_km": [50.0, 50.0, 50.0],
        "nearby_gas_1km": [0, 0, 0],
        "redundancy_penalty": [0.0, 0.0, 0.0],
    })
    for key, value in overrides.items():
        df[key] = value
    return df


def test_demand_term_uses_density_not_tract_population():
    scored = calculate_gas_conv(_candidates()).set_index("station_id")
    # Identical tract populations, different densities -> densest site scores highest
    assert scored.loc[2, "pts_pop_corridor"] > scored.loc[3, "pts_pop_corridor"] > scored.loc[1, "pts_pop_corridor"]


def test_planned_penalty_lowers_score():
    base = calculate_gas_conv(_candidates()).set_index("station_id")
    penalized = calculate_gas_conv(_candidates(planned_infra_penalty=[10.0, 0.0, 0.0])).set_index("station_id")
    assert penalized.loc[1, "final_score"] == base.loc[1, "final_score"] - 10.0
    assert penalized.loc[2, "final_score"] == base.loc[2, "final_score"]


def test_score_candidates_attaches_county_and_ranks(tract_metrics, gas_stations, ev_stations):
    from analysis.conversion_scoring import prepare_candidate_base

    tracts = add_severity_labels(compute_desert_score(compute_desert_components(tract_metrics)))
    out = score_candidates(prepare_candidate_base(gas_stations, ev_stations), tracts)
    assert out["rank"].tolist() == list(range(1, len(out) + 1))
    assert out["final_score"].is_monotonic_decreasing
    assert (out["county"].dropna() == "Alameda").all()
    assert out["final_score"].between(0, 100).all()
    assert np.isfinite(out["nearest_dcfc_km"]).all()
