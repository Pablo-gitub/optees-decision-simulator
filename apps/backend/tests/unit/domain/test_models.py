"""Unit tests for domain models immutability, hashing, and validation."""

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from simulator.domain.errors import DuplicateIdentityError
from simulator.domain.lifecycle import LifecycleStatus
from simulator.domain.models import (
    AccountBalanceSpec,
    CalendarSpec,
    CostModelSpec,
    DatasetSnapshotRef,
    EpisodeDefinition,
    EpisodeRulesSpec,
    EpisodeRun,
    FailurePolicySpec,
    InitialAccountSpec,
    PolicyVersionRef,
)


def _make_sample_episode() -> EpisodeDefinition:
    return EpisodeDefinition(
        episode_id="ep-def_test_01",
        title="Test Episode",
        description="Sample test episode",
        created_at="2026-08-01T00:00:00Z",
        dataset_snapshot=DatasetSnapshotRef(
            snapshot_id="ds-snap_01",
            source_uri="file:///test.jsonl",
            checksum_sha256="sha256:0000000000000000000000000000000000000000000000000000000000000000",
            retrieval_time="2026-08-01T00:00:00Z",
            calendar_frequency="1d",
        ),
        calendar=CalendarSpec(
            round_cutoffs=("2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z"),
            interval_duration="1d",
            evaluation_delay="1d",
        ),
        policy_versions=(
            PolicyVersionRef(
                policy_id="pol-def_static",
                policy_version_id="pol-ver_static_v1",
                policy_version="1.0.0",
                policy_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
                config_hash="sha256:2222222222222222222222222222222222222222222222222222222222222222",
            ),
        ),
        initial_accounts=(
            InitialAccountSpec(
                policy_id="pol-def_static",
                balances=(AccountBalanceSpec(resource_id="USD", quantity=Decimal("10000.00")),),
            ),
        ),
        reference_resource_id="USD",
        rules=EpisodeRulesSpec(
            allow_short_positions=False,
            allow_borrowing=False,
            cost_model=CostModelSpec(
                linear_transaction_fee_rate=Decimal("0.001"),
                fixed_transaction_fee=Decimal("1.00"),
                holding_cost_rate=Decimal("0.0"),
            ),
            failure_policy=FailurePolicySpec(),
        ),
    )


def test_episode_definition_immutability() -> None:
    ep = _make_sample_episode()
    with pytest.raises(FrozenInstanceError):
        ep.title = "Changed Title"  # type: ignore[misc]


def test_hashed_json_fields_are_deeply_immutable() -> None:
    source = {"nested": {"items": [1, 2]}}
    episode = replace(_make_sample_episode(), metadata=source)
    original_hash = episode.compute_hash()

    source["nested"]["items"].append(3)
    assert episode.compute_hash() == original_hash
    with pytest.raises(TypeError, match="frozen mapping"):
        episode.metadata["nested"]["new"] = True
    with pytest.raises(AttributeError):
        episode.metadata["nested"]["items"].append(4)


def test_episode_definition_hashing() -> None:
    ep = _make_sample_episode()
    h1 = ep.compute_hash()
    assert h1.startswith("sha256:")
    assert len(h1) == 71  # "sha256:" + 64 hex chars


def test_episode_definition_rejects_duplicate_policy_id() -> None:
    with pytest.raises(DuplicateIdentityError):
        EpisodeDefinition(
            episode_id="ep-def_dup_test",
            title="Duplicate Test",
            description="Duplicate test",
            created_at="2026-08-01T00:00:00Z",
            dataset_snapshot=DatasetSnapshotRef(
                snapshot_id="ds-snap_01",
                source_uri="file:///test.jsonl",
                checksum_sha256="sha256:0000000000000000000000000000000000000000000000000000000000000000",
                retrieval_time="2026-08-01T00:00:00Z",
                calendar_frequency="1d",
            ),
            calendar=CalendarSpec(
                round_cutoffs=("2026-08-01T00:00:00Z",),
                interval_duration="1d",
                evaluation_delay="1d",
            ),
            policy_versions=(
                PolicyVersionRef(
                    policy_id="pol-def_static",
                    policy_version_id="pol-ver_static_v1",
                    policy_version="1.0.0",
                    policy_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
                    config_hash="sha256:2222222222222222222222222222222222222222222222222222222222222222",
                ),
                PolicyVersionRef(
                    policy_id="pol-def_static",  # Duplicate policy_id!
                    policy_version_id="pol-ver_static_v2",
                    policy_version="2.0.0",
                    policy_hash="sha256:3333333333333333333333333333333333333333333333333333333333333333",
                    config_hash="sha256:4444444444444444444444444444444444444444444444444444444444444444",
                ),
            ),
            initial_accounts=(
                InitialAccountSpec(
                    policy_id="pol-def_static",
                    balances=(AccountBalanceSpec(resource_id="USD", quantity=Decimal("10000.00")),),
                ),
            ),
            reference_resource_id="USD",
            rules=EpisodeRulesSpec(
                allow_short_positions=False,
                allow_borrowing=False,
                cost_model=CostModelSpec(
                    linear_transaction_fee_rate=Decimal("0.001"),
                    fixed_transaction_fee=Decimal("1.00"),
                    holding_cost_rate=Decimal("0.0"),
                ),
                failure_policy=FailurePolicySpec(),
            ),
        )


def test_episode_run_hashing() -> None:
    run = EpisodeRun(
        run_id="ep-run_001",
        episode_id="ep-def_test_01",
        episode_definition_hash="sha256:aaaa",
        lifecycle_status=LifecycleStatus.CONFIGURED,
        started_at="2026-08-01T00:00:00Z",
        ended_at=None,
        current_round_index=0,
        total_rounds=2,
        final_state_hash=None,
    )
    h = run.compute_hash()
    assert h.startswith("sha256:")
    assert run.to_dict()["$type"] == "episode_run"
