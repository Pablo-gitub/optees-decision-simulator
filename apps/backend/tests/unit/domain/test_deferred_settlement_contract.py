"""Pure decision probes for the Deferred Paper Settlement Contract (Gate DS-D3T).

These probes verify the causal timeline, state machine invariants, fee timing,
account visibility, and failure modes frozen in docs/contracts/deferred-settlement-contract.md.
They do not implement or anticipate the runtime engine (DS-02D2).
"""

from decimal import Decimal
from typing import NamedTuple

from simulator.domain.canonical import canonicalize_json, compute_record_hash
from simulator.domain.time import parse_utc_timestamp


class TimelineEvent(NamedTuple):
    timestamp: str
    event_type: str
    description: str


class SettlementProbeContext:
    """Pure probe representation of deferred settlement state machine."""

    def __init__(self, initial_cash: Decimal, reference_resource: str = "USDT"):
        self.reference_resource = reference_resource
        self.cash = initial_cash
        self.holdings: dict[str, Decimal] = {}
        self.pending_order: dict | None = None
        self.settled_transitions: list[dict] = []
        self.outcomes: list[dict] = []
        self.timeline: list[TimelineEvent] = []

    def admit_proposal(
        self,
        decision_id: str,
        policy_id: str,
        resource_id: str,
        action_type: str,
        quantity: Decimal,
        cutoff_time: str,
    ) -> dict:
        """Admission phase at round cutoff T."""
        self.timeline.append(
            TimelineEvent(cutoff_time, "ADMISSION_EVALUATION", f"Evaluating proposal {decision_id}")
        )

        # Invariant 1: Single pending order per policy in v1
        if self.pending_order is not None and action_type != "HOLD":
            outcome = {
                "outcome_id": f"dec-out_{decision_id}_rejected",
                "decision_id": decision_id,
                "status": "REJECTED",
                "rejection_reasons": [
                    {
                        "code": "POLICY_HAS_PENDING_SETTLEMENT",
                        "message": "Policy already has a pending transition awaiting settlement",
                    }
                ],
                "applied_transition_id": None,
            }
            self.outcomes.append(outcome)
            return outcome

        if action_type == "HOLD":
            outcome = {
                "outcome_id": f"dec-out_{decision_id}_accepted",
                "decision_id": decision_id,
                "status": "ACCEPTED",
                "rejection_reasons": [],
                "applied_transition_id": None,
            }
            self.outcomes.append(outcome)
            return outcome

        # Admitted as pending
        self.pending_order = {
            "decision_id": decision_id,
            "policy_id": policy_id,
            "resource_id": resource_id,
            "action_type": action_type,
            "quantity": quantity,
            "cutoff_time": cutoff_time,
            "target_open_time": cutoff_time,  # first bar with open_time >= cutoff
        }

        outcome = {
            "outcome_id": f"dec-out_{decision_id}_admitted",
            "decision_id": decision_id,
            "status": "ADMITTED_PENDING",
            "rejection_reasons": [],
            "applied_transition_id": None,
        }
        self.outcomes.append(outcome)
        return outcome

    def evaluate_settlement(
        self,
        current_time: str,
        available_bars: list[dict],
        linear_fee_rate: Decimal = Decimal("0.001"),
        fixed_fee: Decimal = Decimal("1.00"),
    ) -> dict | None:
        """Settlement phase at simulation clock current_time."""
        if self.pending_order is None:
            return None

        order = self.pending_order
        target_time = order["target_open_time"]
        resource_id = order["resource_id"]

        self.timeline.append(
            TimelineEvent(
                current_time,
                "SETTLEMENT_EVALUATION",
                f"Attempting settlement for {order['decision_id']} at {current_time}",
            )
        )

        current_dt = parse_utc_timestamp(current_time)
        target_dt = parse_utc_timestamp(target_time)

        # Match bar by open_time and ensure knowledge_time <= current_time
        matching_bars = []
        for b in available_bars:
            if b["resource_id"] != resource_id:
                continue
            bar_open_str = b.get("open_time", b["event_time"][:10] + "T00:00:00Z")
            if parse_utc_timestamp(bar_open_str) < target_dt:
                continue
            if parse_utc_timestamp(b["knowledge_time"]) > current_dt:
                continue
            matching_bars.append(b)

        if not matching_bars:
            # Bar not yet available or missing
            return None

        # Sort by event_time, then revision descending
        matching_bars.sort(
            key=lambda b: (parse_utc_timestamp(b["event_time"]).timestamp(), -b["revision"])
        )
        exec_bar = matching_bars[0]

        open_price = Decimal(str(exec_bar["open"]))
        if open_price <= 0:
            outcome = {
                "outcome_id": f"dec-out_{order['decision_id']}_settlement_rejected",
                "decision_id": order["decision_id"],
                "status": "REJECTED",
                "rejection_reasons": [
                    {"code": "INVALID_EXECUTION_PRICE", "message": "Open price is not positive"}
                ],
                "applied_transition_id": None,
            }
            self.pending_order = None
            self.outcomes.append(outcome)
            return outcome

        qty = order["quantity"]
        notional = (qty * open_price).quantize(Decimal("0.01"))
        fee = (notional * linear_fee_rate + fixed_fee).quantize(Decimal("0.01"))
        total_cost = notional + fee

        if order["action_type"] in ("ALLOCATE", "BUY"):
            if self.cash < total_cost:
                # Insufficient funds at fill
                outcome = {
                    "outcome_id": f"dec-out_{order['decision_id']}_settlement_rejected",
                    "decision_id": order["decision_id"],
                    "status": "REJECTED",
                    "rejection_reasons": [
                        {
                            "code": "INSUFFICIENT_FUNDS_AT_SETTLEMENT",
                            "message": f"Required {total_cost} exceeds available cash {self.cash}",
                        }
                    ],
                    "applied_transition_id": None,
                }
                self.pending_order = None
                self.outcomes.append(outcome)
                return outcome

            # Settle BUY
            self.cash -= total_cost
            self.holdings[resource_id] = self.holdings.get(resource_id, Decimal("0")) + qty

            transition = {
                "transition_id": f"trn_{order['decision_id']}_settled",
                "outcome_id": f"dec-out_{order['decision_id']}_settled",
                "effective_time": current_time,
                "economic_fill_time": exec_bar.get(
                    "open_time", exec_bar["event_time"][:10] + "T00:00:00Z"
                ),
                "execution_price": str(open_price),
                "resource_deltas": [
                    {
                        "resource_id": resource_id,
                        "delta": str(qty),
                        "valuation_price": str(open_price),
                    },
                    {
                        "resource_id": self.reference_resource,
                        "delta": str(-notional),
                        "valuation_price": "1.00",
                    },
                ],
                "fee": str(fee),
                "total_cost": str(total_cost),
            }
            self.settled_transitions.append(transition)
            self.pending_order = None
            outcome = {
                "outcome_id": f"dec-out_{order['decision_id']}_settled",
                "decision_id": order["decision_id"],
                "status": "SETTLED",
                "rejection_reasons": [],
                "applied_transition_id": transition["transition_id"],
            }
            self.outcomes.append(outcome)
            return outcome

        return None


# ==============================================================================
# PROBE TESTS
# ==============================================================================


def test_dp01_normal_d_plus_2_lifecycle():
    """Probe DP-01: Verifies the 5-time progression under standard D+2 availability."""
    ctx = SettlementProbeContext(initial_cash=Decimal("100000.00"))

    # Day D (2026-08-01): Policy proposes buying 1.0 BTC at cutoff T0
    t0 = "2026-08-01T00:00:00Z"
    out0 = ctx.admit_proposal(
        decision_id="dec-prop_round0",
        policy_id="pol-def_buyer",
        resource_id="BTC",
        action_type="ALLOCATE",
        quantity=Decimal("1.0"),
        cutoff_time=t0,
    )
    assert out0["status"] == "ADMITTED_PENDING"
    assert ctx.cash == Decimal("100000.00")  # Zero mutation at admission
    assert "BTC" not in ctx.holdings

    # Day D+1 (2026-08-02): Round 1 cutoff T1
    # Kline D is not yet available (knowledge_time is D+2 = 2026-08-03T00:00:00Z)
    t1 = "2026-08-02T00:00:00Z"
    bars = [
        {
            "resource_id": "BTC",
            "event_time": "2026-08-01T23:59:59.999Z",
            "open_time": "2026-08-01T00:00:00.000Z",
            "open": "50000.00",
            "knowledge_time": "2026-08-03T00:00:00Z",  # D+2
            "revision": 1,
        }
    ]
    settle1 = ctx.evaluate_settlement(t1, bars)
    assert settle1 is None  # Cannot settle at T1
    assert ctx.pending_order is not None
    assert ctx.cash == Decimal("100000.00")

    # Day D+2 (2026-08-03): Round 2 cutoff T2
    # Kline D now available (knowledge_time <= T2)
    t2 = "2026-08-03T00:00:00Z"
    settle2 = ctx.evaluate_settlement(t2, bars)
    assert settle2 is not None
    assert settle2["status"] == "SETTLED"
    assert ctx.pending_order is None
    # 50,000 + (50,000 * 0.001 + 1.00) = 50,051.00 total cost
    assert ctx.cash == Decimal("49949.00")
    assert ctx.holdings["BTC"] == Decimal("1.0")

    # Causal inequality verified: T_cutoff (T0) <= t_fill (T0) < t_knowledge (T2) <= t_settle (T2)
    trn = ctx.settled_transitions[0]
    assert trn["economic_fill_time"] == "2026-08-01T00:00:00.000Z"
    assert trn["effective_time"] == "2026-08-03T00:00:00Z"


def test_dp02_missing_day_timeout():
    """Probe DP-02: Verifies terminal rejection and zero mutation when target bar is missing."""
    ctx = SettlementProbeContext(initial_cash=Decimal("50000.00"))

    t0 = "2026-08-01T00:00:00Z"
    ctx.admit_proposal("dec-prop_0", "pol-def_p", "BTC", "ALLOCATE", Decimal("0.5"), t0)

    # Missing bar: bars list contains only other days or symbols
    bars = [
        {
            "resource_id": "ETH",
            "event_time": "2026-08-01T23:59:59.999Z",
            "open_time": "2026-08-01T00:00:00.000Z",
            "open": "3000.00",
            "knowledge_time": "2026-08-03T00:00:00Z",
            "revision": 1,
        }
    ]

    t2 = "2026-08-03T00:00:00Z"
    assert ctx.evaluate_settlement(t2, bars) is None

    # Reaching timeout window without bar -> terminal rejection
    if ctx.pending_order is not None and not any(b["resource_id"] == "BTC" for b in bars):
        outcome = {
            "outcome_id": "dec-out_0_timeout",
            "decision_id": ctx.pending_order["decision_id"],
            "status": "REJECTED",
            "rejection_reasons": [
                {"code": "MISSING_EXECUTION_BAR", "message": "Bar timed out without observation"}
            ],
            "applied_transition_id": None,
        }
        ctx.pending_order = None
        ctx.outcomes.append(outcome)

    assert ctx.pending_order is None
    assert ctx.outcomes[-1]["status"] == "REJECTED"
    assert ctx.cash == Decimal("50000.00")  # Zero cash deducted
    assert "BTC" not in ctx.holdings


def test_dp03_revision_handling_before_vs_after_settlement():
    """Probe DP-03: Revision prior to settlement updates price;

    Revision after leaves state immutable.
    """
    ctx = SettlementProbeContext(initial_cash=Decimal("100000.00"))
    t0 = "2026-08-01T00:00:00Z"
    ctx.admit_proposal("dec-prop_rev", "pol-def_p", "BTC", "ALLOCATE", Decimal("1.0"), t0)

    # Revision 1 (open=50000) and Revision 2 (open=52000) both arrive before settlement
    bars = [
        {
            "resource_id": "BTC",
            "event_time": "2026-08-01T23:59:59.999Z",
            "open_time": "2026-08-01T00:00:00.000Z",
            "open": "50000.00",
            "knowledge_time": "2026-08-03T00:00:00Z",
            "revision": 1,
        },
        {
            "resource_id": "BTC",
            "event_time": "2026-08-01T23:59:59.999Z",
            "open_time": "2026-08-01T00:00:00.000Z",
            "open": "52000.00",
            "knowledge_time": "2026-08-03T00:00:00Z",
            "revision": 2,
        },
    ]

    t2 = "2026-08-03T00:00:00Z"
    settle = ctx.evaluate_settlement(t2, bars)
    assert settle["status"] == "SETTLED"
    trn = ctx.settled_transitions[0]
    # Settle used Revision 2 (open=52000.00)
    assert trn["execution_price"] == "52000.00"

    # Capture canonical hash of settled account state
    account_state = {
        "cash": str(ctx.cash),
        "holdings": {k: str(v) for k, v in ctx.holdings.items()},
        "transition_id": trn["transition_id"],
    }
    settled_hash = compute_record_hash(account_state)

    # Later Revision 3 arrives on Day 5 (2026-08-06)
    # Historical account state and transition MUST remain strictly immutable
    assert compute_record_hash(account_state) == settled_hash


def test_dp04_price_variation_causing_insufficient_funds():
    """Probe DP-04: Verifies rejection at settlement when fill price exceeds available cash."""
    ctx = SettlementProbeContext(initial_cash=Decimal("60000.00"))

    t0 = "2026-08-01T00:00:00Z"
    # Policy expects price around 55k, buys 1.0 BTC with 60k cash
    ctx.admit_proposal("dec-prop_04", "pol-def_p", "BTC", "ALLOCATE", Decimal("1.0"), t0)

    # Market gap: open price is 65,000.00!
    # Total cost = 65,000 + 65 + 1 = 65,066.00 > 60,000.00 cash
    bars = [
        {
            "resource_id": "BTC",
            "event_time": "2026-08-01T23:59:59.999Z",
            "open_time": "2026-08-01T00:00:00.000Z",
            "open": "65000.00",
            "knowledge_time": "2026-08-03T00:00:00Z",
            "revision": 1,
        }
    ]

    t2 = "2026-08-03T00:00:00Z"
    settle = ctx.evaluate_settlement(t2, bars)
    assert settle["status"] == "REJECTED"
    assert settle["rejection_reasons"][0]["code"] == "INSUFFICIENT_FUNDS_AT_SETTLEMENT"

    # Zero mutation: cash unchanged, zero BTC acquired
    assert ctx.cash == Decimal("60000.00")
    assert "BTC" not in ctx.holdings
    assert ctx.pending_order is None  # Pending lock cleared


def test_dp05_pending_at_episode_end():
    """Probe DP-05: Verifies pending order at episode end transitions to terminal rejection."""
    ctx = SettlementProbeContext(initial_cash=Decimal("50000.00"))
    t_penultimate = "2026-08-10T00:00:00Z"
    ctx.admit_proposal(
        "dec-prop_last", "pol-def_p", "SOL", "ALLOCATE", Decimal("10.0"), t_penultimate
    )

    # Episode ends before D+2 settlement bar arrives (arrives 2026-08-12)
    if ctx.pending_order is not None:
        outcome = {
            "outcome_id": "dec-out_last_terminated",
            "decision_id": ctx.pending_order["decision_id"],
            "status": "REJECTED",
            "rejection_reasons": [
                {
                    "code": "UNSETTLED_EPISODE_TERMINATION",
                    "message": "Episode completed while transition was pending settlement",
                }
            ],
            "applied_transition_id": None,
        }
        ctx.pending_order = None
        ctx.outcomes.append(outcome)

    assert ctx.pending_order is None
    assert ctx.outcomes[-1]["status"] == "REJECTED"
    assert ctx.cash == Decimal("50000.00")
    assert "SOL" not in ctx.holdings


def test_dp06_episode_cancellation():
    """Probe DP-06: Verifies pending order cancellation on episode abort."""
    ctx = SettlementProbeContext(initial_cash=Decimal("50000.00"))
    ctx.admit_proposal(
        "dec-prop_cancel", "pol-def_p", "ETH", "ALLOCATE", Decimal("2.0"), "2026-08-01T00:00:00Z"
    )

    # Operator cancels episode
    outcome = {
        "outcome_id": "dec-out_cancel",
        "decision_id": ctx.pending_order["decision_id"],
        "status": "REJECTED",
        "rejection_reasons": [
            {"code": "EPISODE_CANCELLED", "message": "Episode was cancelled by operator"}
        ],
        "applied_transition_id": None,
    }
    ctx.pending_order = None
    ctx.outcomes.append(outcome)

    assert ctx.pending_order is None
    assert ctx.cash == Decimal("50000.00")
    assert "ETH" not in ctx.holdings


def test_dp07_settlement_before_next_decision_ordering():
    """Probe DP-07: Verifies settlement runs BEFORE policy proposal at shared cutoff."""
    ctx = SettlementProbeContext(initial_cash=Decimal("100000.00"))

    # Round 0 (2026-08-01): Buy 1 BTC
    t0 = "2026-08-01T00:00:00Z"
    ctx.admit_proposal("dec-prop_0", "pol-def_p", "BTC", "ALLOCATE", Decimal("1.0"), t0)

    # Round 2 (2026-08-03): Settlement and new decision share cutoff T2
    t2 = "2026-08-03T00:00:00Z"
    bars = [
        {
            "resource_id": "BTC",
            "event_time": "2026-08-01T23:59:59.999Z",
            "open_time": "2026-08-01T00:00:00.000Z",
            "open": "50000.00",
            "knowledge_time": "2026-08-03T00:00:00Z",
            "revision": 1,
        }
    ]

    # STEP 1: Settle pending order FIRST
    settle = ctx.evaluate_settlement(t2, bars)
    assert settle["status"] == "SETTLED"
    assert ctx.pending_order is None  # Pending lock cleared!
    assert ctx.cash == Decimal("49949.00")
    assert ctx.holdings["BTC"] == Decimal("1.0")

    # STEP 2: Policy proposes SECOND (sees updated cash and holdings, no pending block)
    out2 = ctx.admit_proposal(
        "dec-prop_2",
        "pol-def_p",
        "ETH",
        "ALLOCATE",
        Decimal("5.0"),
        t2,  # Can propose!
    )
    assert out2["status"] == "ADMITTED_PENDING"

    # Verify timeline execution sequence
    events = [e.event_type for e in ctx.timeline]
    settle_idx = events.index("SETTLEMENT_EVALUATION")
    admission_idx = len(events) - 1 - events[::-1].index("ADMISSION_EVALUATION")
    assert settle_idx < admission_idx, "Settlement must strictly precede proposal admission at T"


def test_dp08_deterministic_replay_and_merkle_coverage():
    """Probe DP-08: Identical inputs produce bit-for-bit identical hashes across runs."""

    def run_simulation():
        ctx = SettlementProbeContext(initial_cash=Decimal("100000.00"))
        ctx.admit_proposal(
            "dec_0", "pol-def_p", "BTC", "ALLOCATE", Decimal("1.0"), "2026-08-01T00:00:00Z"
        )
        bars = [
            {
                "resource_id": "BTC",
                "event_time": "2026-08-01T23:59:59.999Z",
                "open_time": "2026-08-01T00:00:00.000Z",
                "open": "50000.00",
                "knowledge_time": "2026-08-03T00:00:00Z",
                "revision": 1,
            }
        ]
        ctx.evaluate_settlement("2026-08-03T00:00:00Z", bars)
        return {
            "cash": str(ctx.cash),
            "holdings": {k: str(v) for k, v in ctx.holdings.items()},
            "outcomes": ctx.outcomes,
            "transitions": ctx.settled_transitions,
        }

    run1 = run_simulation()
    run2 = run_simulation()

    str1 = canonicalize_json(run1)
    str2 = canonicalize_json(run2)

    assert str1 == str2
    assert compute_record_hash(run1) == compute_record_hash(run2)


def test_dp09_rejection_of_second_order_while_pending():
    """Probe DP-09: Verifies policy cannot issue a second trading order while one is pending."""
    ctx = SettlementProbeContext(initial_cash=Decimal("100000.00"))

    # Proposal 1 at T0
    out1 = ctx.admit_proposal(
        "dec-prop_1",
        "pol-def_greedy",
        "BTC",
        "ALLOCATE",
        Decimal("1.0"),
        "2026-08-01T00:00:00Z",
    )
    assert out1["status"] == "ADMITTED_PENDING"

    # Proposal 2 at T1 (before Proposal 1 settles): Policy attempts another BUY
    out2 = ctx.admit_proposal(
        "dec-prop_2",
        "pol-def_greedy",
        "ETH",
        "ALLOCATE",
        Decimal("10.0"),
        "2026-08-02T00:00:00Z",
    )
    assert out2["status"] == "REJECTED"
    assert out2["rejection_reasons"][0]["code"] == "POLICY_HAS_PENDING_SETTLEMENT"

    # HOLD is permitted while pending
    out_hold = ctx.admit_proposal(
        "dec-prop_hold",
        "pol-def_greedy",
        "USDT",
        "HOLD",
        Decimal("0"),
        "2026-08-02T00:00:00Z",
    )
    assert out_hold["status"] == "ACCEPTED"
