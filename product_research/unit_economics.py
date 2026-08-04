"""Conservative per-order unit economics for investment decisions."""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any


@dataclass(frozen=True)
class UnitEconomicsAssumptions:
    """Rates are fractions; fixed costs use the product price currency (USD here)."""

    cogs_rate: float = 0.32
    cogs_per_unit: float | None = None
    platform_fee_rate: float = 0.08
    creator_commission_rate: float = 0.15
    payment_fee_rate: float = 0.02
    seller_discount_rate: float = 0.08
    ad_spend_rate: float = 0.12
    return_rate: float = 0.08
    cod_share: float = 0.20
    cod_rejection_rate: float = 0.10
    return_recovery_rate: float = 0.70
    outbound_shipping_per_order: float = 1.00
    return_shipping_per_order: float = 1.00
    cod_rejection_cost_per_order: float = 0.80
    packaging_per_order: float = 0.25

    def __post_init__(self) -> None:
        rate_names = {
            "cogs_rate", "platform_fee_rate", "creator_commission_rate",
            "payment_fee_rate", "seller_discount_rate", "ad_spend_rate",
            "return_rate", "cod_share", "cod_rejection_rate",
            "return_recovery_rate",
        }
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name in rate_names and not 0 <= value <= 1:
                raise ValueError(f"{item.name} must be between 0 and 1")
            if item.name not in rate_names and value is not None and value < 0:
                raise ValueError(f"{item.name} cannot be negative")

    @classmethod
    def from_mapping(cls, values: dict[str, Any] | None) -> "UnitEconomicsAssumptions":
        if not values:
            return cls()
        allowed = {item.name for item in fields(cls)}
        return cls(**{
            key: (None if value in (None, "") else float(value))
            for key, value in values.items() if key in allowed
        })


@dataclass(frozen=True)
class UnitEconomicsResult:
    realized_revenue: float
    contribution_before_ads: float
    ad_spend: float
    contribution_profit: float
    contribution_margin: float
    max_allowable_cpa: float
    break_even_roas: float | None
    accepted_order_rate: float
    kept_order_rate: float


def estimate_unit_economics(
    price: float,
    assumptions: UnitEconomicsAssumptions,
) -> UnitEconomicsResult:
    """Estimate contribution per placed order, including failed COD and returns."""
    if price < 0:
        raise ValueError("price cannot be negative")

    cod_failure_rate = assumptions.cod_share * assumptions.cod_rejection_rate
    accepted_rate = 1.0 - cod_failure_rate
    return_rate = accepted_rate * assumptions.return_rate
    kept_rate = accepted_rate - return_rate

    realized_revenue = price * (1.0 - assumptions.seller_discount_rate) * kept_rate
    cogs_per_unit = (
        assumptions.cogs_per_unit
        if assumptions.cogs_per_unit is not None
        else price * assumptions.cogs_rate
    )
    cogs_loss = cogs_per_unit * (
        kept_rate + return_rate * (1.0 - assumptions.return_recovery_rate)
    )
    selling_fees = realized_revenue * (
        assumptions.platform_fee_rate
        + assumptions.creator_commission_rate
        + assumptions.payment_fee_rate
    )
    fulfillment_cost = accepted_rate * (
        assumptions.outbound_shipping_per_order + assumptions.packaging_per_order
    )
    reverse_logistics = return_rate * assumptions.return_shipping_per_order
    failed_cod_cost = cod_failure_rate * assumptions.cod_rejection_cost_per_order

    contribution_before_ads = (
        realized_revenue
        - cogs_loss
        - selling_fees
        - fulfillment_cost
        - reverse_logistics
        - failed_cod_cost
    )
    ad_spend = price * assumptions.ad_spend_rate
    contribution_profit = contribution_before_ads - ad_spend
    contribution_margin = (
        contribution_profit / realized_revenue if realized_revenue > 0 else -1.0
    )
    max_allowable_cpa = max(0.0, contribution_before_ads)
    break_even_roas = (
        realized_revenue / max_allowable_cpa if max_allowable_cpa > 0 else None
    )

    return UnitEconomicsResult(
        realized_revenue=round(realized_revenue, 4),
        contribution_before_ads=round(contribution_before_ads, 4),
        ad_spend=round(ad_spend, 4),
        contribution_profit=round(contribution_profit, 4),
        contribution_margin=round(contribution_margin, 6),
        max_allowable_cpa=round(max_allowable_cpa, 4),
        break_even_roas=round(break_even_roas, 4) if break_even_roas else None,
        accepted_order_rate=round(accepted_rate, 6),
        kept_order_rate=round(kept_rate, 6),
    )
