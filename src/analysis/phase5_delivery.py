"""Reusable Phase 5 sensitivity-analysis and delivery helpers.

Each scenario re-runs the parts of the model it changes:

1. tract desert scoring (weights, EV supply metric, normalization method,
   gas-access buffer size), then
2. conversion-candidate scoring against that scenario's tract scores
   (redundancy radius), then
3. ranking.

Candidate stability is computed from those scenario-specific rankings.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any
import sys

import geopandas as gpd
import numpy as np
import pandas as pd

try:
    from .desert_detection import (
        add_severity_labels,
        compute_desert_components,
        compute_desert_score,
    )
    from .coverage_metrics import gas_access
    from .conversion_scoring import score_candidates
except ImportError:  # Supports direct execution by file path.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from desert_detection import (  # type: ignore[no-redef]
        add_severity_labels,
        compute_desert_components,
        compute_desert_score,
    )
    from coverage_metrics import gas_access  # type: ignore[no-redef]
    from conversion_scoring import score_candidates  # type: ignore[no-redef]

CRS_ANALYSIS = "EPSG:3310"
BASELINE_GAS_BUFFER_KM = 2.0


@dataclass(frozen=True)
class Scenario:
    name: str
    gas_access_buffer_km: float = BASELINE_GAS_BUFFER_KM
    redundancy_buffer_km: float = 1.0
    ev_supply_metric: str = "ports_per_sq_km"
    normalization: str = "percentile"
    w_gas: float = 0.25
    w_pop: float = 0.25
    w_ev: float = 0.35
    w_dcfc: float = 0.15

    def weights(self) -> dict[str, float]:
        values = np.array([self.w_gas, self.w_pop, self.w_ev, self.w_dcfc])
        if np.any(values < 0) or values.sum() <= 0:
            raise ValueError(f"Invalid weights for scenario {self.name}")
        values = values / values.sum()
        return dict(zip(("w_gas", "w_pop", "w_ev", "w_dcfc"), values))


def default_scenarios() -> list[Scenario]:
    """
    Baseline plus one-at-a-time perturbations. Weight scenarios scale a
    single weight by 0.5x or 1.5x-2x (weights are renormalized to sum to 1),
    which is large enough to reveal which candidates depend on a particular
    modelling choice.
    """
    return [
        Scenario("baseline"),
        Scenario("ev_gap_x1.5", w_ev=0.35 * 1.5),
        Scenario("ev_gap_x0.5", w_ev=0.35 * 0.5),
        Scenario("dcfc_distance_x2", w_dcfc=0.15 * 2),
        Scenario("dcfc_distance_x0.5", w_dcfc=0.15 * 0.5),
        Scenario("gas_access_x0.5", w_gas=0.25 * 0.5),
        Scenario("pop_density_x0.5", w_pop=0.25 * 0.5),
        Scenario("equal_weights", w_gas=0.25, w_pop=0.25, w_ev=0.25, w_dcfc=0.25),
        Scenario("gas_buffer_5km", gas_access_buffer_km=5),
        Scenario("redundancy_2km", redundancy_buffer_km=2),
        Scenario("dcfc_only_supply", ev_supply_metric="dcfc_per_1000"),
        Scenario("per_capita_supply", ev_supply_metric="ports_per_1000"),
        Scenario("minmax_normalization", normalization="minmax"),
    ]


def _metric_column(gdf: pd.DataFrame, metric: str) -> str:
    aliases = {
        "ev_port_density": ["ev_port_density", "ports_per_sq_km"],
        "ports_per_sq_km": ["ports_per_sq_km", "ev_port_density"],
        "dcfc_ports_per_sq_km": ["dcfc_ports_per_sq_km", "dcfc_port_density"],
        "dcfc_per_1000": ["dcfc_per_1000", "dcfc_ports_per_1000", "dcfc_ports_per_1000_people"],
        "ev_ports_per_1000_people": ["ev_ports_per_1000_people", "ports_per_1000_people", "ports_per_1000"],
        "ports_per_1000": ["ports_per_1000", "ev_ports_per_1000_people", "ports_per_1000_people"],
    }
    for column in aliases.get(metric, [metric]):
        if column in gdf:
            return column
    raise KeyError(f"No column available for EV supply metric {metric!r}")


def score_desert_scenario(
    metrics: gpd.GeoDataFrame,
    scenario: Scenario,
    gas: gpd.GeoDataFrame | None = None,
) -> gpd.GeoDataFrame:
    """
    Score tracts under one scenario while retaining transparent components.

    `metrics` is the Phase 3 tract coverage metrics layer. `gas` (cleaned gas
    stations) is required when the scenario changes the gas-access buffer,
    because gas access is then recounted around each tract's reference point.
    """
    df = metrics.copy()
    if df.crs is not None and df.crs != CRS_ANALYSIS:
        df = df.to_crs(CRS_ANALYSIS)

    if scenario.gas_access_buffer_km != BASELINE_GAS_BUFFER_KM:
        if gas is None:
            raise ValueError(f"Scenario {scenario.name!r} changes the gas-access buffer; pass the gas station layer")
        df = gas_access(gas.to_crs(df.crs), df, buffer_m=scenario.gas_access_buffer_km * 1000.0)

    # Derive optional sensitivity metrics from the Phase 3 columns when they
    # were not persisted as dedicated fields.
    if scenario.ev_supply_metric == "dcfc_ports_per_sq_km" and "dcfc_ports_per_sq_km" not in df:
        if {"dcfc_ports", "tract_area_sq_km"}.issubset(df.columns):
            area = pd.to_numeric(df["tract_area_sq_km"], errors="coerce").replace(0, np.nan)
            df["dcfc_ports_per_sq_km"] = pd.to_numeric(df["dcfc_ports"], errors="coerce").fillna(0) / area
    if scenario.ev_supply_metric in {"ev_ports_per_1000_people", "ports_per_1000"} and "ports_per_1000" not in df and "ev_ports_per_1000_people" not in df:
        ports_col = "total_ev_ports" if "total_ev_ports" in df else "total_ports"
        pop_col = "total_population" if "total_population" in df else "population"
        if {ports_col, pop_col}.issubset(df.columns):
            population = pd.to_numeric(df[pop_col], errors="coerce").replace(0, np.nan)
            df["ports_per_1000"] = pd.to_numeric(df[ports_col], errors="coerce").fillna(0) / population * 1000
    if scenario.ev_supply_metric == "dcfc_per_1000" and "dcfc_per_1000" not in df:
        if {"dcfc_ports", "total_population"}.issubset(df.columns):
            population = pd.to_numeric(df["total_population"], errors="coerce").replace(0, np.nan)
            df["dcfc_per_1000"] = pd.to_numeric(df["dcfc_ports"], errors="coerce").fillna(0) / population * 1000
    metric = _metric_column(df, scenario.ev_supply_metric)
    if metric != "ports_per_sq_km":
        # The EV-gap component reads ports_per_sq_km; substitute the scenario's metric.
        df["ports_per_sq_km"] = pd.to_numeric(df[metric], errors="coerce").fillna(0)
    components = compute_desert_components(df, method=scenario.normalization)
    scored = compute_desert_score(components, **scenario.weights())
    return add_severity_labels(scored)


def score_candidate_scenario(
    candidate_base: gpd.GeoDataFrame,
    scored_tracts: gpd.GeoDataFrame,
    scenario: Scenario,
) -> gpd.GeoDataFrame:
    """Re-score conversion candidates against one scenario's tract scores."""
    return score_candidates(
        candidate_base,
        scored_tracts,
        redundancy_radius_m=scenario.redundancy_buffer_km * 1000.0,
    )


def run_sensitivity(
    metrics: gpd.GeoDataFrame,
    candidate_base: gpd.GeoDataFrame,
    gas: gpd.GeoDataFrame,
    scenarios: list[Scenario] | None = None,
) -> tuple[dict[str, gpd.GeoDataFrame], list[pd.DataFrame], dict[str, str]]:
    """
    Runs every scenario end to end.

    Returns (tract results by scenario, per-scenario candidate rankings,
    skipped scenarios with the reason).
    """
    scenarios = scenarios or default_scenarios()
    tract_results: dict[str, gpd.GeoDataFrame] = {}
    ranked: list[pd.DataFrame] = []
    skipped: dict[str, str] = {}
    for scenario in scenarios:
        try:
            tracts = score_desert_scenario(metrics, scenario, gas=gas)
        except KeyError as exc:
            skipped[scenario.name] = str(exc)
            continue
        tract_results[scenario.name] = tracts
        candidates = score_candidate_scenario(candidate_base, tracts, scenario)
        ranked.append(rank_candidates(candidates, scenario.name))
    return tract_results, ranked, skipped


def rank_candidates(candidates: pd.DataFrame, scenario_name: str) -> pd.DataFrame:
    """Return stable ID, score, and deterministic rank columns for one scenario's scored candidates."""
    id_col = "station_id" if "station_id" in candidates else "id"
    score = pd.to_numeric(candidates["final_score"], errors="coerce").fillna(0)
    result = candidates[[id_col]].copy()
    result["station_id"] = result[id_col].astype(str)
    result[f"score_{scenario_name}"] = score
    result = result.sort_values([f"score_{scenario_name}", "station_id"], ascending=[False, True])
    result[f"rank_{scenario_name}"] = np.arange(1, len(result) + 1)
    return result[["station_id", f"score_{scenario_name}", f"rank_{scenario_name}"]]


def summarize_candidate_stability(ranked: list[pd.DataFrame]) -> pd.DataFrame:
    """Merge scenario ranks and calculate top-N stability statistics."""
    merged = ranked[0].copy()
    for frame in ranked[1:]:
        merged = merged.merge(frame, on="station_id", how="outer")
    rank_cols = [c for c in merged if c.startswith("rank_")]
    ranks = merged[rank_cols]
    merged["top20_count"] = (ranks <= 20).sum(axis=1)
    merged["top50_count"] = (ranks <= 50).sum(axis=1)
    merged["average_rank"] = ranks.mean(axis=1)
    merged["worst_rank"] = ranks.max(axis=1)
    merged["rank_std"] = ranks.std(axis=1).fillna(0)
    scenario_count = len(rank_cols)
    merged["stable_candidate"] = (merged["top20_count"] >= max(1, min(4, scenario_count))) | (merged["top50_count"] == scenario_count)
    return merged.sort_values(["stable_candidate", "top20_count", "average_rank"], ascending=[False, False, True])


def scenario_metadata(scenarios: list[Scenario]) -> pd.DataFrame:
    return pd.DataFrame([asdict(s) | s.weights() for s in scenarios])


def severity_sensitivity(results: dict[str, gpd.GeoDataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for name, frame in results.items():
        severity = frame["severity_score"]
        rows.append({"scenario": name, "tract_count": len(frame), **severity.value_counts().to_dict(),
                     "median_score": frame["desert_score"].median(), "max_score": frame["desert_score"].max()})
    return pd.DataFrame(rows).fillna(0)


def run_and_export(scenarios: list[Scenario] | None = None) -> dict[str, Path]:
    """Loads Phase 3/4 inputs, runs every scenario, and writes the sensitivity tables."""
    try:
        from .conversion_scoring import load_data, load_planned, prepare_candidate_base
    except ImportError:
        from conversion_scoring import load_data, load_planned, prepare_candidate_base  # type: ignore[no-redef]
    from config import PROCESSED_DIR, TABLES_DIR  # on sys.path via the analysis modules

    scenarios = scenarios or default_scenarios()
    metrics = gpd.read_parquet(PROCESSED_DIR / "tract_coverage_metrics.parquet")
    gas, ev, _, highways = load_data()
    candidate_base = prepare_candidate_base(gas, ev, highways, load_planned())

    tract_results, ranked, skipped = run_sensitivity(metrics, candidate_base, gas, scenarios)
    if skipped:
        print(f"Skipped scenarios: {skipped}")

    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "scenarios": TABLES_DIR / "sensitivity_scenarios.csv",
        "severity": TABLES_DIR / "severity_sensitivity.csv",
        "stability": TABLES_DIR / "candidate_stability.csv",
    }
    scenario_metadata(scenarios).to_csv(paths["scenarios"], index=False)
    severity_sensitivity(tract_results).to_csv(paths["severity"], index=False)
    stability = summarize_candidate_stability(ranked)
    stability.to_csv(paths["stability"], index=False)
    print(f"Stable candidates: {int(stability['stable_candidate'].sum())} of {len(stability)}")
    for path in paths.values():
        print(f"Saved {path}")
    return paths


if __name__ == "__main__":
    run_and_export()
