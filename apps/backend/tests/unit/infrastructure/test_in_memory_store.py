"""Unit tests for InMemoryStore adapter."""

from decimal import Decimal

import pytest

from simulator.domain.errors import FrozenRecordMutationError
from simulator.domain.models import (
    AccountBalanceSpec,
    CalendarSpec,
    CostModelSpec,
    DatasetSnapshotRef,
    EpisodeDefinition,
    EpisodeRulesSpec,
    FailurePolicySpec,
    InitialAccountSpec,
    PolicyVersionRef,
)
from simulator.infrastructure.adapters.in_memory_store import InMemoryStore


def _make_ep(ep_id: str, title: str) -> EpisodeDefinition:
    return EpisodeDefinition(
        episode_id=ep_id,
        title=title,
        description="Desc",
        created_at="2026-08-01T00:00:00Z",
        dataset_snapshot=DatasetSnapshotRef(
            "ds1",
            "file:///a",
            "sha256:0000000000000000000000000000000000000000000000000000000000000000",
            "2026-08-01T00:00:00Z",
            "1d",
        ),
        calendar=CalendarSpec(("2026-08-01T00:00:00Z",), "1d", "1d"),
        policy_versions=(
            PolicyVersionRef(
                "p1",
                "pv1",
                "1.0.0",
                "sha256:1111111111111111111111111111111111111111111111111111111111111111",
                "sha256:2222222222222222222222222222222222222222222222222222222222222222",
            ),
        ),
        initial_accounts=(InitialAccountSpec("p1", (AccountBalanceSpec("USD", Decimal("100")),)),),
        reference_resource_id="USD",
        rules=EpisodeRulesSpec(
            False,
            False,
            CostModelSpec(Decimal("0"), Decimal("0"), Decimal("0")),
            FailurePolicySpec(),
        ),
    )


def test_store_episode_definition_immutability() -> None:
    store = InMemoryStore()
    ep1 = _make_ep("ep_1", "Title 1")
    store.save_episode_definition(ep1)

    # Identical save is idempotent
    store.save_episode_definition(ep1)

    # Modified save with same ID raises FrozenRecordMutationError
    ep1_mod = _make_ep("ep_1", "Mutated Title")
    with pytest.raises(FrozenRecordMutationError):
        store.save_episode_definition(ep1_mod)
