import numpy as np
import pandas as pd
import pytest

from analysis.desert_detection import (
    add_severity_labels,
    compute_desert_components,
    compute_desert_score,
    normalize_coverage_metrics,
    scorable_tracts,
)


def test_percentile_normalization_is_robust_to_outliers():
    s = pd.Series([0, 1, 2, 3, 10_000])
    pct = normalize_coverage_metrics(s)
    minmax = normalize_coverage_metrics(s, method="minmax")
    assert pct.tolist() == [0.0, 0.25, 0.5, 0.75, 1.0]
    # min-max squashes everything but the outlier toward 0
    assert minmax.iloc[3] < 0.001


def test_normalization_ties_nulls_and_constants():
    pct = normalize_coverage_metrics(pd.Series([0, 0, 5, np.nan]))
    assert pct.iloc[0] == pct.iloc[1] == 0.25
    assert pct.iloc[2] == 1.0
    assert np.isnan(pct.iloc[3])
    const = normalize_coverage_metrics(pd.Series([3.0, 3.0, np.nan]))
    assert const.iloc[:2].tolist() == [0.5, 0.5] and np.isnan(const.iloc[2])
    with pytest.raises(ValueError):
        normalize_coverage_metrics(pd.Series([1, 2]), method="zscore")


def _frame():
    return pd.DataFrame({
        "total_population": [1000, 0, 3000, np.nan, 2000],
        "population_density": [100.0, 0.0, 900.0, np.nan, 300.0],
        "gas_access_count_2km": [1, 50, 8, 0, 3],
        "ports_per_sq_km": [0.0, 0.0, 12.0, 0.0, 1.0],
        "nearest_dcfc_km": [25.0, 80.0, 0.5, 10.0, 4.0],
    })


def test_unpopulated_tracts_are_not_scored():
    df = _frame()
    assert scorable_tracts(df).tolist() == [True, False, True, False, True]
    labeled = add_severity_labels(compute_desert_score(compute_desert_components(df)))
    assert labeled.loc[[1, 3], "desert_score"].isna().all()
    assert (labeled.loc[[1, 3], "severity_score"] == "not_scored").all()
    assert labeled.loc[[0, 2, 4], "desert_score"].notna().all()


def test_unpopulated_tracts_do_not_affect_populated_scores():
    df = _frame()
    with_empty = compute_desert_score(compute_desert_components(df))
    without_empty = compute_desert_score(compute_desert_components(df.drop(index=[1, 3])))
    pd.testing.assert_series_equal(with_empty.loc[[0, 2, 4], "desert_score"], without_empty["desert_score"])


def test_severity_thresholds():
    df = pd.DataFrame({"desert_score": [10.0, 50.0, 74.99, 75.0, np.nan]})
    assert add_severity_labels(df)["severity_score"].tolist() == [
        "adequate", "moderate_desert", "moderate_desert", "severe_desert", "not_scored"
    ]


def test_score_is_bounded_0_100():
    scored = compute_desert_score(compute_desert_components(_frame()))
    valid = scored["desert_score"].dropna()
    assert valid.between(0, 100).all()


def test_geojson_export_is_simplified_compact_and_gap_free(tmp_path):
    import json

    import geopandas as gpd
    from shapely.geometry import Polygon

    from analysis.desert_detection import export_desert_geojson

    # Two tracts sharing a wiggly edge with many small (<50 m) vertices
    wiggle = [(5_000 + (15 if k % 2 else -15), k * 20) for k in range(0, 251)]
    left = Polygon([(0, 0)] + wiggle + [(0, 5_000)])
    right = Polygon([(10_000, 0), (10_000, 5_000)] + wiggle[::-1])
    gdf = gpd.GeoDataFrame(
        {"GEOID": ["a", "b"], "desert_score": [80.123456, np.nan], "severity_score": ["severe_desert", "not_scored"]},
        geometry=[left, right], crs="EPSG:3310",
    )
    full = tmp_path / "full.geojson"
    gdf.to_crs("EPSG:4326").to_file(full, driver="GeoJSON")
    out = export_desert_geojson(gdf, tmp_path / "web.geojson", simplify_m=50)

    assert out.stat().st_size < full.stat().st_size / 3
    data = json.loads(out.read_text(encoding="utf-8"))
    props = [f["properties"] for f in data["features"]]
    assert props[0]["desert_score"] == 80.1235
    assert props[1]["desert_score"] is None

    web = gpd.read_file(out).to_crs("EPSG:3310")
    assert web.is_valid.all()
    # Shared edge stays shared: no sliver gap or overlap between neighbours
    union_area = web.geometry.union_all().area
    assert union_area == pytest.approx(web.area.sum(), rel=1e-6)
    assert union_area == pytest.approx(gdf.area.sum(), rel=0.01)
