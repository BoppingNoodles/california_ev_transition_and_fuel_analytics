import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

from analysis import coverage_metrics as cm

CRS = "EPSG:3310"


@pytest.mark.parametrize("name, expected", [
    ("Census Tract 4001; Alameda County; California", "Alameda"),
    ("Census Tract 101.02, San Luis Obispo County, California", "San Luis Obispo"),
    ("Something else", None),
    (None, None),
])
def test_parse_county_name(name, expected):
    assert cm.parse_county_name(name) == expected


def test_density_uses_land_area_not_water():
    # 10 km x 10 km polygon, but only 25 km^2 of it is land
    tracts = gpd.GeoDataFrame({"GEOID": ["06001000100"], "ALAND": [25_000_000]},
                              geometry=[box(0, 0, 10_000, 10_000)], crs=CRS)
    demo = pd.DataFrame({"GEOID": ["06001000100"], "NAME": ["Census Tract 1; Marin County; California"],
                         "total_population": [5000], "median_income": [90000]})
    base = cm.prepare_tract_base(tracts, demo)
    assert base.loc[0, "tract_total_area_sq_km"] == pytest.approx(100.0)
    assert base.loc[0, "tract_area_sq_km"] == pytest.approx(25.0)
    assert base.loc[0, "population_density"] == pytest.approx(200.0)
    assert base.loc[0, "county"] == "Marin"


def test_reference_points_prefer_population_weighted_centroid(tmp_path):
    tracts = gpd.GeoDataFrame({"GEOID": ["06001400100", "06001400200"]},
                              geometry=[box(0, 0, 10_000, 10_000), box(10_000, 0, 20_000, 10_000)], crs=CRS)
    target = gpd.GeoSeries([Point(1_000, 9_000)], crs=CRS).to_crs("EPSG:4326")
    path = tmp_path / "cenpop.csv"
    pd.DataFrame({"STATEFP": ["06"], "COUNTYFP": ["001"], "TRACTCE": ["400100"], "POPULATION": [10],
                  "LATITUDE": [target.y[0]], "LONGITUDE": [target.x[0]]}).to_csv(path, index=False)

    out = cm.add_reference_points(tracts, path)
    assert out.loc[0, "ref_point_source"] == "population_weighted"
    assert out.loc[0, "ref_x"] == pytest.approx(1_000, abs=0.01)
    assert out.loc[0, "ref_y"] == pytest.approx(9_000, abs=0.01)
    # Missing tract falls back to a point inside its polygon
    assert out.loc[1, "ref_point_source"] == "representative_point"
    assert tracts.geometry[1].contains(Point(out.loc[1, "ref_x"], out.loc[1, "ref_y"]))


def test_gas_access_buffer_and_rerun(tract_metrics, gas_stations):
    small = cm.gas_access(gas_stations, tract_metrics, buffer_m=500)
    large = cm.gas_access(gas_stations, small, buffer_m=5000)
    assert list(large.columns).count("gas_access_count_2km") == 1
    assert (large["gas_access_count_2km"] >= small["gas_access_count_2km"]).all()


def test_metrics_pipeline_produces_expected_columns(tract_metrics):
    for col in ["county", "ref_x", "ref_y", "gas_access_count_2km", "nearest_dcfc_km",
                "ports_per_sq_km", "ports_per_1000", "dcfc_per_1000", "zero_population_flag"]:
        assert col in tract_metrics.columns
    assert tract_metrics["zero_population_flag"].sum() == 1
