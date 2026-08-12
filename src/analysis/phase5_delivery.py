"""Reusable Phase 5 sensitivity-analysis and delivery helpers."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd

from .desert_detection import (
    add_severity_labels,
    compute_desert_components,
    compute_desert_score,
)


@dataclass(frozen=True)
class Scenario:
    name: str
    gas_access_buffer_km: float = 2.0
    redundancy_buffer_km: float = 1.0
    ev_supply_metric: str = "ports_per_sq_km"
    normalization_scope: str = "statewide"
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
    return [
        Scenario("baseline"),
        Scenario("ev_gap_high", w_gas=.25, w_pop=.25, w_ev=.385, w_dcfc=.15),
        Scenario("dcfc_distance_high", w_gas=.25, w_pop=.25, w_ev=.35, w_dcfc=.165),
        Scenario("gas_access_high", w_gas=.275, w_pop=.25, w_ev=.35, w_dcfc=.15),
        Scenario("gas_buffer_5km", gas_access_buffer_km=5),
        Scenario("redundancy_2km", redundancy_buffer_km=2),
        Scenario("dcfc_only_supply", ev_supply_metric="dcfc_per_1000"),
        Scenario("per_capita_supply", ev_supply_metric="ports_per_1000"),
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


def score_desert_scenario(metrics: gpd.GeoDataFrame, scenario: Scenario) -> gpd.GeoDataFrame:
    """Score tracts under one scenario while retaining transparent components."""
    df = metrics.copy()
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
        df["ports_per_sq_km"] = pd.to_numeric(df[metric], errors="coerce").fillna(0)
    components = compute_desert_components(df)
    scored = compute_desert_score(components, **scenario.weights())
    return add_severity_labels(scored)


def rank_candidates(candidates: pd.DataFrame, scenario_name: str) -> pd.DataFrame:
    """Return stable ID, score, and deterministic rank columns for one scenario."""
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
