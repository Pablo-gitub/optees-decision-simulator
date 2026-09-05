"""Pure account valuation service for mark-to-market revaluation (DS-02D2C1A).

Produces a new VirtualAccountState snapshot mark-to-market using PriceEvidence
resolved from the pricing port, preserving balances, reservations, and costs.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Final, Mapping

from simulator.application.ports.pricing import PriceEvidence
from simulator.domain.errors import TemporalLeakageError
from simulator.domain.models import (
    BalanceItem,
    ReferenceValuation,
    VirtualAccountState,
)
from simulator.domain.time import parse_utc_timestamp

_CENTS: Final[Decimal] = Decimal("0.01")
_ROUND_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"^rnd_[a-zA-Z0-9_-]+$")


class AccountValuationService:
    """Pure, stateless account revaluation service."""

    @staticmethod
    def revalue_account(
        current_account: VirtualAccountState,
        round_id: str,
        round_index: int,
        as_of_time: str,
        valuation_marks: Mapping[str, PriceEvidence],
        account_state_id: str | None = None,
    ) -> VirtualAccountState:
        """Produce a mark-to-market VirtualAccountState from provided valuation marks.

        Args:
            current_account: Prior account state to revalue.
            round_id: Authoritative round ID triggering revaluation.
            round_index: Round index of the revalued account state.
            as_of_time: UTC timestamp (round cutoff) of the valuation.
            valuation_marks: Mapping of resource_id to provenance-bearing PriceEvidence.
            account_state_id: Optional ID for the new state. If omitted,
                defaults to 'acc-state_{round_id}_{policy_id}'.

        Returns:
            A new, immutable VirtualAccountState with updated reference valuation.

        Raises:
            ValueError: If inputs or valuation marks violate structural or financial rules.
            TemporalLeakageError: If any PriceEvidence knowledge_time exceeds cutoff.
        """
        if not isinstance(current_account, VirtualAccountState):
            raise TypeError(
                "current_account must be a VirtualAccountState, "
                f"got {type(current_account).__name__}"
            )
        if not isinstance(round_id, str) or not _ROUND_ID_PATTERN.match(round_id):
            raise ValueError(f"Invalid round_id: {round_id!r}")
        if not isinstance(round_index, int) or round_index < current_account.round_index:
            raise ValueError(
                f"round_index ({round_index}) must be >= current_account.round_index "
                f"({current_account.round_index})"
            )

        cutoff_dt = parse_utc_timestamp(as_of_time)
        account_dt = parse_utc_timestamp(current_account.as_of_time)
        if cutoff_dt < account_dt:
            raise ValueError(
                f"as_of_time ({as_of_time}) cannot precede current_account.as_of_time "
                f"({current_account.as_of_time})"
            )

        ref_id = current_account.reference_valuation.reference_resource_id

        # Validate marks and extract prices
        clean_prices: dict[str, Decimal] = {}
        for res_id, mark in valuation_marks.items():
            if not isinstance(res_id, str) or not res_id.strip():
                raise ValueError("valuation_marks resource_id must be a non-empty string")

            if not isinstance(mark, PriceEvidence):
                raise TypeError(
                    f"Valuation mark for '{res_id}' must be PriceEvidence, "
                    f"got {type(mark).__name__}"
                )
            if mark.resource_id != res_id:
                raise ValueError(
                    f"Valuation mark key '{res_id}' does not match PriceEvidence "
                    f"resource_id '{mark.resource_id}'"
                )
            if mark.price.is_nan() or mark.price.is_infinite() or mark.price <= Decimal("0"):
                raise ValueError(f"PriceEvidence for '{res_id}' must be positive finite Decimal")
            if mark.knowledge_time is None:
                raise ValueError(f"PriceEvidence for '{res_id}' must include knowledge_time")
            kt = parse_utc_timestamp(mark.knowledge_time)
            if kt > cutoff_dt:
                raise TemporalLeakageError(
                    f"PriceEvidence for '{res_id}' has future knowledge_time "
                    f"({mark.knowledge_time}) relative to cutoff ({as_of_time})"
                )
            clean_prices[res_id] = mark.price

        # Check required marks for held non-reference resources
        unallocated_cash = Decimal("0.00")
        allocated_resources_value = Decimal("0.00")

        new_balances: list[BalanceItem] = []
        for b in current_account.balances:
            new_balances.append(
                BalanceItem(
                    resource_id=b.resource_id,
                    quantity=b.quantity,
                    reserved_quantity=b.reserved_quantity,
                )
            )
            if b.resource_id == ref_id:
                unallocated_cash = b.quantity
            else:
                if b.quantity != Decimal("0"):
                    if b.resource_id not in clean_prices:
                        raise ValueError(
                            "Missing required valuation mark for held "
                            f"non-reference resource '{b.resource_id}'"
                        )
                    price = clean_prices[b.resource_id]
                    term_val = (b.quantity * price).quantize(_CENTS, rounding=ROUND_HALF_EVEN)
                    allocated_resources_value += term_val

        unallocated_cash = unallocated_cash.quantize(_CENTS, rounding=ROUND_HALF_EVEN)
        allocated_resources_value = allocated_resources_value.quantize(
            _CENTS, rounding=ROUND_HALF_EVEN
        )
        net_total_value = (unallocated_cash + allocated_resources_value).quantize(
            _CENTS, rounding=ROUND_HALF_EVEN
        )

        state_id = (
            account_state_id
            if account_state_id is not None
            else f"acc-state_{round_id}_{current_account.policy_id}"
        )

        return VirtualAccountState(
            account_state_id=state_id,
            policy_id=current_account.policy_id,
            round_index=round_index,
            as_of_time=as_of_time,
            balances=tuple(new_balances),
            cumulative_costs=current_account.cumulative_costs,
            reference_valuation=ReferenceValuation(
                reference_resource_id=ref_id,
                unallocated_cash=unallocated_cash,
                allocated_resources_value=allocated_resources_value,
                net_total_value=net_total_value,
            ),
            parent_state_hash=current_account.compute_hash(),
            schema_version="1.0.0",
        )
