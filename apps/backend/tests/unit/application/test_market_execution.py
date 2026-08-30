"""Unit tests for market valuation and execution transition rules."""

from decimal import Decimal

from simulator.application.ports.pricing import PriceEvidence, PriceResolutionResult
from simulator.application.services.execution import ExecutionService
from simulator.domain.lifecycle import ActionType, DecisionStatus
from simulator.domain.models import (
    AccountBalanceSpec,
    BalanceItem,
    CalendarSpec,
    CostModelSpec,
    CumulativeCostItem,
    DatasetSnapshotRef,
    DecisionRationale,
    EpisodeDefinition,
    EpisodeRulesSpec,
    FailurePolicySpec,
    InitialAccountSpec,
    PolicyVersionRef,
    ProposedDecision,
    ReferenceValuation,
    RequestedAction,
    VirtualAccountState,
)


def _build_market_episode_def() -> EpisodeDefinition:
    return EpisodeDefinition(
        episode_id="ep-def_market_benchmark_v1",
        title="Market Benchmark BTC ETH SOL BNB",
        description="Market episode with 4-asset crypto universe",
        created_at="2026-08-01T00:00:00Z",
        dataset_snapshot=DatasetSnapshotRef(
            snapshot_id="ds-snap_binance_spot_1d_v1",
            source_uri="https://data.binance.vision/data/spot/daily/klines/",
            checksum_sha256="sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            retrieval_time="2026-08-01T00:00:00Z",
            calendar_frequency="1d",
        ),
        calendar=CalendarSpec(
            round_cutoffs=("2026-08-04T00:00:00Z", "2026-08-05T00:00:00Z"),
            interval_duration="1d",
            evaluation_delay="1d",
        ),
        policy_versions=(
            PolicyVersionRef(
                policy_id="pol-def_market_test",
                policy_version_id="pol-ver_test_v1",
                policy_version="1.0.0",
                policy_hash="sha256:1111111111111111111111111111111111111111111111111111111111111111",
                config_hash="sha256:2222222222222222222222222222222222222222222222222222222222222222",
            ),
        ),
        initial_accounts=(
            InitialAccountSpec(
                policy_id="pol-def_market_test",
                balances=(AccountBalanceSpec(resource_id="USDT", quantity=Decimal("10000.00")),),
            ),
        ),
        reference_resource_id="USDT",
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


def _make_initial_account(
    policy_id: str,
    cash: Decimal = Decimal("10000.00"),
    extra_balances: dict[str, Decimal] | None = None,
) -> VirtualAccountState:
    balances = [BalanceItem(resource_id="USDT", quantity=cash)]
    if extra_balances:
        for res_id, qty in extra_balances.items():
            balances.append(BalanceItem(resource_id=res_id, quantity=qty))

    return VirtualAccountState(
        account_state_id=f"acc-state_init_{policy_id}",
        policy_id=policy_id,
        round_index=0,
        as_of_time="2026-08-01T00:00:00Z",
        balances=tuple(balances),
        cumulative_costs=(CumulativeCostItem(cost_type="TRANSACTION_FEE", amount=Decimal("0.00")),),
        reference_valuation=ReferenceValuation(
            reference_resource_id="USDT",
            unallocated_cash=cash,
            allocated_resources_value=Decimal("0.00"),
            net_total_value=cash,
        ),
        parent_state_hash=None,
    )


def test_fractional_asset_quantity_preservation() -> None:
    ep_def = _build_market_episode_def()
    current_acc = _make_initial_account("pol-def_market_test", cash=Decimal("10000.00"))

    # Action: Buy fractional BTC quantity (e.g. 0.12345678 BTC)
    btc_qty = Decimal("0.12345678")
    proposal = ProposedDecision(
        decision_id="dec_001",
        round_id="rnd_001",
        policy_id="pol-def_market_test",
        policy_version_id="pol-ver_test_v1",
        knowledge_cutoff="2026-08-04T00:00:00Z",
        generated_at="2026-08-04T00:00:00Z",
        rationale=DecisionRationale(method="market_test"),
        desired_allocations=(),
        requested_actions=(
            RequestedAction(action_type=ActionType.ALLOCATE, resource_id="BTC", quantity=btc_qty),
        ),
    )

    # Pricing context
    # Valuation mark at cutoff T: 64500.00 USDT
    # Execution price at next-bar open: 65000.00 USDT
    pricing = PriceResolutionResult(
        valuation_marks={
            "USDT": PriceEvidence("USDT", Decimal("1.00"), None, None, None, None, Decimal("0")),
            "BTC": PriceEvidence(
                "BTC",
                Decimal("64500.00"),
                "obs_val",
                "2026-08-03T00:00:00Z",
                "2026-08-04T00:00:00Z",
                1,
                Decimal("86400"),
            ),
        },
        execution_prices={
            "USDT": PriceEvidence("USDT", Decimal("1.00"), None, None, None, None, Decimal("0")),
            "BTC": PriceEvidence(
                "BTC",
                Decimal("65000.00"),
                "obs_exec",
                "2026-08-04T00:00:00Z",
                "2026-08-05T00:00:00Z",
                1,
                Decimal("0"),
            ),
        },
    )

    outcome, transition, next_account = ExecutionService.evaluate_and_apply_decision(
        episode_def=ep_def,
        current_account=current_acc,
        proposal=proposal,
        round_id="rnd_001",
        round_index=1,
        effective_time="2026-08-05T00:00:00Z",
        pricing_result=pricing,
    )

    assert outcome.status == DecisionStatus.ACCEPTED
    assert transition is not None

    # Expected exact calculations:
    # Notional: (0.12345678 * 65000.00).quantize(0.01) = 8024.69 USDT
    # Linear fee: (8024.69 * 0.001).quantize(0.01) = 8.02 USDT
    # Fixed fee: 1.00 USDT -> total fee: 9.02 USDT
    # Cash deducted: 8024.69 + 9.02 = 8033.71 USDT
    # Remaining cash: 10000.00 - 8033.71 = 1966.29 USDT
    expected_cash = Decimal("1966.29")
    assert transition.total_cost_reference_unit == Decimal("9.02")

    # Assert BTC balance preserves exact fractional precision without 2-decimal truncation!
    btc_balance = next((b for b in next_account.balances if b.resource_id == "BTC"), None)
    assert btc_balance is not None
    assert btc_balance.quantity == btc_qty  # Exactly Decimal("0.12345678")

    cash_balance = next((b for b in next_account.balances if b.resource_id == "USDT"), None)
    assert cash_balance is not None
    assert cash_balance.quantity == expected_cash

    # Reference valuation:
    # allocated_val = (0.12345678 * 64500.00).quantize(0.01) = 7962.96 USDT
    # net_total_value = 1966.29 + 7962.96 = 9929.25 USDT
    expected_alloc_val = (btc_qty * Decimal("64500.00")).quantize(Decimal("0.01"))
    assert expected_alloc_val == Decimal("7962.96")
    assert next_account.reference_valuation.allocated_resources_value == Decimal("7962.96")
    assert next_account.reference_valuation.unallocated_cash == expected_cash
    assert next_account.reference_valuation.net_total_value == expected_cash + Decimal("7962.96")


def test_partial_liquidation_via_transfer() -> None:
    ep_def = _build_market_episode_def()
    current_acc = _make_initial_account(
        "pol-def_market_test",
        cash=Decimal("2000.00"),
        extra_balances={"ETH": Decimal("5.00000000")},
    )

    # Action: Sell 2.0 ETH
    proposal = ProposedDecision(
        decision_id="dec_002",
        round_id="rnd_002",
        policy_id="pol-def_market_test",
        policy_version_id="pol-ver_test_v1",
        knowledge_cutoff="2026-08-04T00:00:00Z",
        generated_at="2026-08-04T00:00:00Z",
        rationale=DecisionRationale(method="market_test"),
        desired_allocations=(),
        requested_actions=(
            RequestedAction(
                action_type=ActionType.TRANSFER, resource_id="ETH", quantity=Decimal("-2.00000000")
            ),
        ),
    )

    pricing = PriceResolutionResult(
        valuation_marks={
            "USDT": PriceEvidence("USDT", Decimal("1.00"), None, None, None, None, Decimal("0")),
            "ETH": PriceEvidence(
                "ETH",
                Decimal("3000.00"),
                "obs_eth_val",
                "2026-08-03T00:00:00Z",
                "2026-08-04T00:00:00Z",
                1,
                Decimal("86400"),
            ),
        },
        execution_prices={
            "USDT": PriceEvidence("USDT", Decimal("1.00"), None, None, None, None, Decimal("0")),
            "ETH": PriceEvidence(
                "ETH",
                Decimal("3100.00"),
                "obs_eth_exec",
                "2026-08-04T00:00:00Z",
                "2026-08-05T00:00:00Z",
                1,
                Decimal("0"),
            ),
        },
    )

    outcome, transition, next_account = ExecutionService.evaluate_and_apply_decision(
        episode_def=ep_def,
        current_account=current_acc,
        proposal=proposal,
        round_id="rnd_002",
        round_index=1,
        effective_time="2026-08-05T00:00:00Z",
        pricing_result=pricing,
    )

    assert outcome.status == DecisionStatus.ACCEPTED
    assert transition is not None

    # Notional received: (2.0 * 3100.00) = 6200.00 USDT
    # Fee: 6.20 + 1.00 = 7.20 USDT
    # Net cash added: 6200.00 - 7.20 = 6192.80 USDT
    # Total cash: 2000.00 + 6192.80 = 8192.80 USDT
    # Remaining ETH: 5.0 - 2.0 = 3.00000000 ETH
    eth_balance = next(b for b in next_account.balances if b.resource_id == "ETH")
    cash_balance = next(b for b in next_account.balances if b.resource_id == "USDT")
    assert eth_balance.quantity == Decimal("3.00000000")
    assert cash_balance.quantity == Decimal("8192.80")


def test_multi_asset_portfolio_all_four_coins() -> None:
    ep_def = _build_market_episode_def()
    current_acc = _make_initial_account("pol-def_market_test", cash=Decimal("50000.00"))

    proposal = ProposedDecision(
        decision_id="dec_003",
        round_id="rnd_003",
        policy_id="pol-def_market_test",
        policy_version_id="pol-ver_test_v1",
        knowledge_cutoff="2026-08-04T00:00:00Z",
        generated_at="2026-08-04T00:00:00Z",
        rationale=DecisionRationale(method="market_test"),
        desired_allocations=(),
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE, resource_id="BTC", quantity=Decimal("0.25")
            ),
            RequestedAction(
                action_type=ActionType.ALLOCATE, resource_id="ETH", quantity=Decimal("2.5")
            ),
            RequestedAction(
                action_type=ActionType.ALLOCATE, resource_id="SOL", quantity=Decimal("20.0")
            ),
            RequestedAction(
                action_type=ActionType.ALLOCATE, resource_id="BNB", quantity=Decimal("10.0")
            ),
        ),
    )

    pricing = PriceResolutionResult(
        valuation_marks={
            "USDT": PriceEvidence("USDT", Decimal("1.00"), None, None, None, None, Decimal("0")),
            "BTC": PriceEvidence(
                "BTC",
                Decimal("60000.00"),
                "obs_btc",
                "2026-08-03T00:00:00Z",
                "2026-08-04T00:00:00Z",
                1,
                Decimal("86400"),
            ),
            "ETH": PriceEvidence(
                "ETH",
                Decimal("3000.00"),
                "obs_eth",
                "2026-08-03T00:00:00Z",
                "2026-08-04T00:00:00Z",
                1,
                Decimal("86400"),
            ),
            "SOL": PriceEvidence(
                "SOL",
                Decimal("150.00"),
                "obs_sol",
                "2026-08-03T00:00:00Z",
                "2026-08-04T00:00:00Z",
                1,
                Decimal("86400"),
            ),
            "BNB": PriceEvidence(
                "BNB",
                Decimal("500.00"),
                "obs_bnb",
                "2026-08-03T00:00:00Z",
                "2026-08-04T00:00:00Z",
                1,
                Decimal("86400"),
            ),
        },
        execution_prices={
            "USDT": PriceEvidence("USDT", Decimal("1.00"), None, None, None, None, Decimal("0")),
            "BTC": PriceEvidence(
                "BTC",
                Decimal("60000.00"),
                "obs_btc_f",
                "2026-08-04T00:00:00Z",
                "2026-08-05T00:00:00Z",
                1,
                Decimal("0"),
            ),
            "ETH": PriceEvidence(
                "ETH",
                Decimal("3000.00"),
                "obs_eth_f",
                "2026-08-04T00:00:00Z",
                "2026-08-05T00:00:00Z",
                1,
                Decimal("0"),
            ),
            "SOL": PriceEvidence(
                "SOL",
                Decimal("150.00"),
                "obs_sol_f",
                "2026-08-04T00:00:00Z",
                "2026-08-05T00:00:00Z",
                1,
                Decimal("0"),
            ),
            "BNB": PriceEvidence(
                "BNB",
                Decimal("500.00"),
                "obs_bnb_f",
                "2026-08-04T00:00:00Z",
                "2026-08-05T00:00:00Z",
                1,
                Decimal("0"),
            ),
        },
    )

    outcome, transition, next_account = ExecutionService.evaluate_and_apply_decision(
        episode_def=ep_def,
        current_account=current_acc,
        proposal=proposal,
        round_id="rnd_003",
        round_index=1,
        effective_time="2026-08-05T00:00:00Z",
        pricing_result=pricing,
    )

    assert outcome.status == DecisionStatus.ACCEPTED
    assert transition is not None

    # Notionals:
    # BTC: 0.25 * 60000 = 15000 USDT (fee: 15.00 + 1.00 = 16.00)
    # ETH: 2.5 * 3000 = 7500 USDT (fee: 7.50 + 1.00 = 8.50)
    # SOL: 20.0 * 150 = 3000 USDT (fee: 3.00 + 1.00 = 4.00)
    # BNB: 10.0 * 500 = 5000 USDT (fee: 5.00 + 1.00 = 6.00)
    # Total notional: 30500 USDT
    # Total fees: 16.00 + 8.50 + 4.00 + 6.00 = 34.50 USDT
    # Cash remaining: 50000 - 30500 - 34.50 = 19465.50 USDT
    assert transition.total_cost_reference_unit == Decimal("34.50")
    assert next_account.reference_valuation.unallocated_cash == Decimal("19465.50")
    assert next_account.reference_valuation.allocated_resources_value == Decimal("30500.00")
    assert next_account.reference_valuation.net_total_value == Decimal("49965.50")


def test_missing_price_causes_zero_mutation_rejection() -> None:
    ep_def = _build_market_episode_def()
    current_acc = _make_initial_account("pol-def_market_test", cash=Decimal("10000.00"))

    proposal = ProposedDecision(
        decision_id="dec_004",
        round_id="rnd_004",
        policy_id="pol-def_market_test",
        policy_version_id="pol-ver_test_v1",
        knowledge_cutoff="2026-08-04T00:00:00Z",
        generated_at="2026-08-04T00:00:00Z",
        rationale=DecisionRationale(method="market_test"),
        desired_allocations=(),
        requested_actions=(
            RequestedAction(
                action_type=ActionType.ALLOCATE, resource_id="BTC", quantity=Decimal("0.1")
            ),
        ),
    )

    # Missing BTC price
    pricing = PriceResolutionResult(
        valuation_marks={
            "USDT": PriceEvidence("USDT", Decimal("1.00"), None, None, None, None, Decimal("0")),
        },
        execution_prices={
            "USDT": PriceEvidence("USDT", Decimal("1.00"), None, None, None, None, Decimal("0")),
        },
    )

    outcome, transition, next_account = ExecutionService.evaluate_and_apply_decision(
        episode_def=ep_def,
        current_account=current_acc,
        proposal=proposal,
        round_id="rnd_004",
        round_index=1,
        effective_time="2026-08-05T00:00:00Z",
        pricing_result=pricing,
    )

    assert outcome.status == DecisionStatus.REJECTED
    assert transition is None
    # Balances, costs, and valuation unmutated
    assert next_account.balances == current_acc.balances
    assert next_account.cumulative_costs == current_acc.cumulative_costs
    assert next_account.reference_valuation == current_acc.reference_valuation
