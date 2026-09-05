"""Unit tests for DeferredConfiguration contract and strict parser (DS-02D2C1A)."""

from types import MappingProxyType

import pytest

from simulator.application.contracts.deferred_configuration import (
    DeferredConfiguration,
    DeferredConfigurationError,
    extract_deferred_configuration,
    parse_deferred_configuration,
)


@pytest.fixture
def valid_deferred_config_dict():
    return {
        "schema_version": "1.0.0",
        "settlement_mode": "deferred",
        "calendar_identity": "cal_binance_spot_1d_utc_v1",
        "calendar_sha256": "sha256:" + "a" * 64,
        "resource_to_series_map": {
            "res_btc": "series_btc_usdt_1d",
            "res_eth": "series_eth_usdt_1d",
        },
        "scheduled_openings": {
            "2026-08-01T00:00:00Z": "2026-08-01T00:00:00Z",
            "2026-08-02T00:00:00Z": "2026-08-02T00:00:00Z",
        },
        "scheduled_deadlines": {
            "2026-08-01T00:00:00Z": "2026-08-03T00:00:00Z",
            "2026-08-02T00:00:00Z": "2026-08-04T00:00:00Z",
        },
        "deadline_policy": "inclusive",
    }


def test_valid_parsing(valid_deferred_config_dict):
    cutoffs = ["2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"]
    cfg = parse_deferred_configuration(valid_deferred_config_dict, declared_cutoffs=cutoffs)

    assert isinstance(cfg, DeferredConfiguration)
    assert cfg.schema_version == "1.0.0"
    assert cfg.settlement_mode == "deferred"
    assert cfg.calendar_identity == "cal_binance_spot_1d_utc_v1"
    assert cfg.calendar_sha256 == "sha256:" + "a" * 64
    assert cfg.deadline_policy == "inclusive"
    assert cfg.resource_to_series_map["res_btc"] == "series_btc_usdt_1d"
    assert cfg.scheduled_openings["2026-08-01T00:00:00Z"] == "2026-08-01T00:00:00Z"
    assert cfg.scheduled_deadlines["2026-08-01T00:00:00Z"] == "2026-08-03T00:00:00Z"


def test_extract_deferred_configuration_absent():
    assert extract_deferred_configuration(None) is None
    assert extract_deferred_configuration({}) is None
    assert extract_deferred_configuration({"other_key": 123}) is None


def test_extract_deferred_configuration_present_valid(valid_deferred_config_dict):
    metadata = {"deferred_settlement": valid_deferred_config_dict}
    cfg = extract_deferred_configuration(metadata)
    assert cfg is not None
    assert cfg.settlement_mode == "deferred"


def test_extract_deferred_configuration_present_malformed_fails():
    metadata = {"deferred_settlement": {"schema_version": "invalid"}}
    with pytest.raises(DeferredConfigurationError):
        extract_deferred_configuration(metadata)


def test_immutability(valid_deferred_config_dict):
    cfg = parse_deferred_configuration(valid_deferred_config_dict)
    assert isinstance(cfg.resource_to_series_map, MappingProxyType)
    assert isinstance(cfg.scheduled_openings, MappingProxyType)
    assert isinstance(cfg.scheduled_deadlines, MappingProxyType)

    with pytest.raises(TypeError):
        cfg.resource_to_series_map["res_btc"] = "tampered"  # type: ignore

    with pytest.raises(TypeError):
        cfg.scheduled_openings["2026-08-01T00:00:00Z"] = "tampered"  # type: ignore


def test_missing_keys(valid_deferred_config_dict):
    del valid_deferred_config_dict["calendar_sha256"]
    with pytest.raises(DeferredConfigurationError, match="missing keys"):
        parse_deferred_configuration(valid_deferred_config_dict)


def test_unexpected_extra_keys(valid_deferred_config_dict):
    valid_deferred_config_dict["unknown_key"] = "forbidden"
    with pytest.raises(DeferredConfigurationError, match="unexpected extra keys"):
        parse_deferred_configuration(valid_deferred_config_dict)


def test_invalid_calendar_sha256(valid_deferred_config_dict):
    valid_deferred_config_dict["calendar_sha256"] = "invalid_hash"
    with pytest.raises(DeferredConfigurationError, match="calendar_sha256"):
        parse_deferred_configuration(valid_deferred_config_dict)

    # Uppercase hex is forbidden
    valid_deferred_config_dict["calendar_sha256"] = "sha256:" + "A" * 64
    with pytest.raises(DeferredConfigurationError, match="calendar_sha256"):
        parse_deferred_configuration(valid_deferred_config_dict)


def test_non_utc_timestamps(valid_deferred_config_dict):
    valid_deferred_config_dict["scheduled_openings"]["2026-08-01T00:00:00Z"] = (
        "2026-08-01T00:00:00+02:00"
    )
    with pytest.raises(Exception):
        parse_deferred_configuration(valid_deferred_config_dict)


def test_schedule_opening_precedes_cutoff(valid_deferred_config_dict):
    valid_deferred_config_dict["scheduled_openings"]["2026-08-02T00:00:00Z"] = (
        "2026-08-01T23:59:59Z"
    )
    with pytest.raises(DeferredConfigurationError, match="cannot precede cutoff"):
        parse_deferred_configuration(valid_deferred_config_dict)


def test_schedule_deadline_precedes_opening(valid_deferred_config_dict):
    valid_deferred_config_dict["scheduled_deadlines"]["2026-08-01T00:00:00Z"] = (
        "2026-07-31T23:59:59Z"
    )
    with pytest.raises(DeferredConfigurationError, match="cannot precede opening"):
        parse_deferred_configuration(valid_deferred_config_dict)


def test_declared_cutoffs_mismatch(valid_deferred_config_dict):
    declared = ["2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z"]
    with pytest.raises(DeferredConfigurationError, match="do not match declared cutoffs"):
        parse_deferred_configuration(valid_deferred_config_dict, declared_cutoffs=declared)


def test_duplicate_series_rejection(valid_deferred_config_dict):
    valid_deferred_config_dict["resource_to_series_map"] = {
        "res_btc": "series_shared",
        "res_eth": "series_shared",
    }
    with pytest.raises(DeferredConfigurationError, match="Duplicate series_id"):
        parse_deferred_configuration(valid_deferred_config_dict)


def test_boolean_rejection(valid_deferred_config_dict):
    valid_deferred_config_dict["calendar_identity"] = True
    with pytest.raises(DeferredConfigurationError):
        parse_deferred_configuration(valid_deferred_config_dict)


def test_to_dict_roundtrip(valid_deferred_config_dict):
    cfg = parse_deferred_configuration(valid_deferred_config_dict)
    d = cfg.to_dict()
    assert d == valid_deferred_config_dict
