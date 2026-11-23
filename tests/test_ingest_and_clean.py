import pandas as pd
import pytest

from ingest import fetch_census
from transform.clean_stations import PLANNED_STATUS, clean_ev_station, find_latest_files


def _write_ev_csv(path):
    pd.DataFrame({
        "id": [1, 2, 3, 4],
        "station_name": ["Open", "Planned", "Temp unavailable", "Private"],
        "state": ["CA"] * 4,
        "latitude": [37.8, 37.9, 38.0, 38.1],
        "longitude": [-122.2, -122.3, -122.4, -122.5],
        "status_code": ["E", "P", "T", "E"],
        "access_code": ["public", "public", "public", "private"],
        "ev_dc_fast_num": [2, 4, 1, 0],
        "ev_level1_evse_num": [None, None, None, None],
        "ev_level2_evse_num": [4, 0, 2, 2],
    }).to_csv(path, index=False)


def test_clean_ev_keeps_only_open_public_stations(tmp_path):
    path = tmp_path / "afdc_ev_stations_2026-01-01.csv"
    _write_ev_csv(path)
    clean = clean_ev_station(path)
    assert clean["station_name"].tolist() == ["Open"]
    assert clean.loc[clean.index[0], "total_ev_ports"] == 6


def test_clean_ev_planned_and_all_statuses(tmp_path):
    path = tmp_path / "afdc_ev_stations_2026-01-01.csv"
    _write_ev_csv(path)
    assert clean_ev_station(path, status_codes=PLANNED_STATUS)["station_name"].tolist() == ["Planned"]
    assert len(clean_ev_station(path, status_codes=None)) == 3  # all public stations


def test_find_latest_files_raises_instead_of_exiting(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_latest_files(tmp_path)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_acs_negative_sentinels_become_missing(tmp_path, monkeypatch):
    payload = [
        ["NAME", "B01003_001E", "B19013_001E", "B08201_001E", "B08201_002E", "state", "county", "tract"],
        ["Census Tract 1; Alameda County; California", "4000", "-666666666", "1500", "100", "06", "001", "000100"],
        ["Census Tract 2; Alameda County; California", "0", "-666666666", "0", "0", "06", "001", "000200"],
        ["Census Tract 3; Alameda County; California", "3000", "85000", "1200", "-999999999", "06", "001", "000300"],
    ]
    calls = {}

    def fake_get(url, params=None, timeout=None):
        calls["timeout"] = timeout
        return _FakeResponse(payload)

    monkeypatch.setattr(fetch_census, "CENSUS_API_KEY", "test-key")
    monkeypatch.setattr(fetch_census.requests, "get", fake_get)
    out = fetch_census.fetch_acs_ca_demographics_2024(tmp_path / "acs.csv")
    df = pd.read_csv(out, dtype={"GEOID": str})

    assert calls["timeout"] is not None
    assert df["median_income"].isna().tolist() == [True, True, False]
    assert df["median_income"].min() >= 0
    assert pd.isna(df.loc[2, "no_vehicle_households"])
    assert df["total_population"].tolist() == [4000, 0, 3000]
    assert df["GEOID"].tolist() == ["06001000100", "06001000200", "06001000300"]


def test_missing_census_key_raises(monkeypatch):
    monkeypatch.setattr(fetch_census, "CENSUS_API_KEY", "")
    with pytest.raises(RuntimeError):
        fetch_census.fetch_acs_ca_demographics_2024()
