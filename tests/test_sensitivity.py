import pandas as pd
import pytest

from analysis.conversion_scoring import prepare_candidate_base, score_candidates
from analysis.desert_detection import add_severity_labels, compute_desert_components, compute_desert_score
from analysis.phase5_delivery import (
    Scenario,
    default_scenarios,
    run_sensitivity,
    score_desert_scenario,
    summarize_candidate_stability,
)


@pytest.fixture
def candidate_base(gas_stations, ev_stations):
    return prepare_candidate_base(gas_stations, ev_stations)


def test_baseline_scenario_matches_main_pipeline(tract_metrics, candidate_base, gas_stations):
    """The sensitivity baseline must reproduce the Phase 3/4 outputs exactly."""
    pipeline_tracts = add_severity_labels(compute_desert_score(compute_desert_components(tract_metrics)))
    scenario_tracts = score_desert_scenario(tract_metrics, Scenario("baseline"), gas=gas_stations)
    pd.testing.assert_series_equal(pipeline_tracts["desert_score"], scenario_tracts["desert_score"])

    pipeline_candidates = score_candidates(candidate_base, pipeline_tracts)
    _, ranked, skipped = run_sensitivity(tract_metrics, candidate_base, gas_stations, [Scenario("baseline")])
    assert not skipped
    baseline = ranked[0].set_index("station_id")["score_baseline"]
    expected = pipeline_candidates.assign(station_id=pipeline_candidates["station_id"].astype(str)).set_index("station_id")["final_score"]
    pd.testing.assert_series_equal(baseline.sort_index(), expected.sort_index(), check_names=False)


def test_scenarios_actually_change_candidate_scores(tract_metrics, candidate_base, gas_stations):
    """Regression: every scenario used to rank the same final_score column."""
    _, ranked, skipped = run_sensitivity(tract_metrics, candidate_base, gas_stations, default_scenarios())
    assert not skipped
    merged = ranked[0]
    for frame in ranked[1:]:
        merged = merged.merge(frame, on="station_id")
    baseline = merged["score_baseline"]
    for col in [c for c in merged if c.startswith("score_") and c != "score_baseline"]:
        assert not baseline.equals(merged[col]), f"{col} is identical to baseline"


def test_gas_buffer_scenario_recounts_gas_access(tract_metrics, gas_stations):
    wide = score_desert_scenario(tract_metrics, Scenario("gas_buffer_5km", gas_access_buffer_km=5), gas=gas_stations)
    assert (wide["gas_access_count_2km"] >= tract_metrics["gas_access_count_2km"]).all()
    assert (wide["gas_access_count_2km"] > tract_metrics["gas_access_count_2km"]).any()


def test_gas_buffer_scenario_requires_gas_layer(tract_metrics):
    with pytest.raises(ValueError):
        score_desert_scenario(tract_metrics, Scenario("gas_buffer_5km", gas_access_buffer_km=5))


def test_redundancy_scenario_changes_penalty(tract_metrics, candidate_base, gas_stations):
    tracts = score_desert_scenario(tract_metrics, Scenario("baseline"))
    one_km = score_candidates(candidate_base, tracts, redundancy_radius_m=1000).set_index("station_id")
    two_km = score_candidates(candidate_base, tracts, redundancy_radius_m=2000).set_index("station_id")
    assert (two_km["nearby_gas_1km"] >= one_km.loc[two_km.index, "nearby_gas_1km"]).all()
    assert (two_km["nearby_gas_1km"] > one_km.loc[two_km.index, "nearby_gas_1km"]).any()


def test_stability_counts_scenarios(tract_metrics, candidate_base, gas_stations):
    scenarios = default_scenarios()
    _, ranked, _ = run_sensitivity(tract_metrics, candidate_base, gas_stations, scenarios)
    stability = summarize_candidate_stability(ranked)
    assert len(stability) == len(candidate_base)
    assert stability["top20_count"].between(0, len(scenarios)).all()
    # With genuinely different scenarios, not every station has identical ranks everywhere
    assert (stability["rank_std"] > 0).any()


def test_stability_threshold_scales_with_scenario_count():
    # 10 scenarios: station "a" is top-20 in 4 of them (40%), "b" in 5 (50%)
    ranked = []
    for k in range(10):
        ranked.append(pd.DataFrame({
            "station_id": ["a", "b"],
            f"score_s{k}": [1.0, 1.0],
            f"rank_s{k}": [1 if k < 4 else 100, 1 if k < 5 else 100],
        }))
    out = summarize_candidate_stability(ranked).set_index("station_id")
    assert not out.loc["a", "stable_candidate"]
    assert out.loc["b", "stable_candidate"]


def test_scenario_metadata_reports_effective_weights():
    from analysis.phase5_delivery import scenario_metadata

    meta = scenario_metadata(default_scenarios()).set_index("name")
    assert meta[["w_gas", "w_pop", "w_ev", "w_dcfc"]].sum(axis=1).round(9).eq(1).all()
    assert meta.loc["ev_gap_high", "w_ev"] == pytest.approx(0.525 / 1.175)
