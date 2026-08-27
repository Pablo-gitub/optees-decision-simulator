"""Backend test suite configuration and shared fixtures."""

from decimal import Decimal
from pathlib import Path

import pytest

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

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = REPO_ROOT / "docs" / "contracts" / "schemas"
EXAMPLES_DIR = REPO_ROOT / "docs" / "contracts" / "examples"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def schemas_dir() -> Path:
    return SCHEMAS_DIR


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES_DIR


def build_synthetic_episode() -> EpisodeDefinition:
    return EpisodeDefinition(
        episode_id="ep-def_synthetic_three_rounds",
        title="Synthetic Three Round Benchmark",
        description="3-round benchmark with Static and Reactive policies",
        created_at="2026-08-01T00:00:00Z",
        dataset_snapshot=DatasetSnapshotRef(
            snapshot_id="ds-snap_synthetic_daily_v1",
            source_uri="memory://synthetic_daily_v1",
            checksum_sha256="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            retrieval_time="2026-08-01T00:00:00Z",
            calendar_frequency="1d",
        ),
        calendar=CalendarSpec(
            round_cutoffs=(
                "2026-08-01T00:00:00Z",
                "2026-08-02T00:00:00Z",
                "2026-08-03T00:00:00Z",
            ),
            interval_duration="1d",
            evaluation_delay="1d",
        ),
        policy_versions=(
            PolicyVersionRef(
                policy_id="pol-def_static_baseline",
                policy_version_id="pol-ver_static_v1",
                policy_version="1.0.0",
                policy_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
                config_hash="sha256:2222222222222222222222222222222222222222222222222222222222222222",
            ),
            PolicyVersionRef(
                policy_id="pol-def_reactive_baseline",
                policy_version_id="pol-ver_reactive_v1",
                policy_version="1.0.0",
                policy_hash="sha256:3333333333333333333333333333333333333333333333333333333333333333",
                config_hash="sha256:4444444444444444444444444444444444444444444444444444444444444444",
            ),
        ),
        initial_accounts=(
            InitialAccountSpec(
                policy_id="pol-def_static_baseline",
                balances=(
                    AccountBalanceSpec(resource_id="USD", quantity=Decimal("10000.00")),
                    AccountBalanceSpec(resource_id="RES_ALPHA", quantity=Decimal("0.00")),
                    AccountBalanceSpec(resource_id="RES_BETA", quantity=Decimal("0.00")),
                ),
            ),
            InitialAccountSpec(
                policy_id="pol-def_reactive_baseline",
                balances=(
                    AccountBalanceSpec(resource_id="USD", quantity=Decimal("10000.00")),
                    AccountBalanceSpec(resource_id="RES_ALPHA", quantity=Decimal("0.00")),
                    AccountBalanceSpec(resource_id="RES_BETA", quantity=Decimal("0.00")),
                ),
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


@pytest.fixture
def synthetic_episode_def() -> EpisodeDefinition:
    return build_synthetic_episode()
