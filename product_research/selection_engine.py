"""Store-independent stage gates for pre-launch product selection."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from product_research import ProductInsight, TrendScore


class SelectionStage(str, Enum):
    REJECT = "reject"
    WATCH = "watch"
    SUPPLIER_VALIDATION = "supplier_validation"
    SAMPLE_TEST = "sample_test"


@dataclass(frozen=True)
class SelectionDecision:
    product_id: str
    stage: SelectionStage
    reasons: tuple[str, ...]
    uses_exact_costs: bool


def decide_selection_stage(
    product: ProductInsight,
    score: TrendScore,
    gates: dict,
) -> SelectionDecision:
    reasons: list[str] = []
    category_profiles = gates.get("category_profiles", {})
    profile = category_profiles.get(product.category_code, {})
    exact_costs = all(
        value is not None
        for value in (
            product.unit_cost_usd,
            product.outbound_shipping_usd,
            product.packaging_usd,
        )
    )

    if product.compliance_risk == "high":
        return SelectionDecision(
            product.product_id, SelectionStage.REJECT,
            ("合规风险为高，店铺注册前不应投入样品或库存",), exact_costs,
        )
    disallowed_flags = set(profile.get("disallowed_flags", []))
    matched_flags = sorted(disallowed_flags.intersection(product.product_flags))
    if matched_flags:
        return SelectionDecision(
            product.product_id,
            SelectionStage.REJECT,
            ("命中类目禁入标签：" + "、".join(matched_flags),),
            exact_costs,
        )
    if (score.estimated_contribution_margin or -1) < 0:
        return SelectionDecision(
            product.product_id, SelectionStage.REJECT,
            ("基础假设下贡献利润为负",), exact_costs,
        )

    min_trend_score = float(profile.get("min_research_score", gates.get("min_research_score", 55)))
    min_content_score = float(profile.get("min_content_score", gates.get("min_content_score", 60)))
    max_moq = int(profile.get("max_prelaunch_moq", gates.get("max_prelaunch_moq", 100)))
    max_lead_time = int(profile.get("max_lead_time_days", gates.get("max_lead_time_days", 30)))
    min_price = profile.get("min_price_usd")
    max_price = profile.get("max_price_usd")

    if score.score < min_trend_score:
        reasons.append(f"综合分 {score.score:.1f} 低于研究线 {min_trend_score:.0f}")
    if product.sales_growth_7d <= 0:
        reasons.append("近7天销量没有正增长")
    if product.content_score is not None and product.content_score < min_content_score:
        reasons.append("内容可演示性不足")
    if product.supplier_moq is not None and product.supplier_moq > max_moq:
        reasons.append(f"MOQ {product.supplier_moq} 高于前期上限 {max_moq}")
    if product.lead_time_days is not None and product.lead_time_days > max_lead_time:
        reasons.append(f"交期 {product.lead_time_days} 天过长")
    if min_price is not None and product.price < float(min_price):
        reasons.append(f"售价低于赛道价格带 ${float(min_price):.2f}")
    if max_price is not None and product.price > float(max_price):
        reasons.append(f"售价高于赛道价格带 ${float(max_price):.2f}")
    if reasons:
        return SelectionDecision(
            product.product_id, SelectionStage.WATCH, tuple(reasons), exact_costs,
        )

    min_margin = float(gates.get("min_contribution_margin", 0.12))
    max_roas = float(gates.get("max_break_even_roas", 3.5))
    min_sales = int(gates.get("min_sales_volume", 100))
    margin = score.estimated_contribution_margin or -1
    roas = score.break_even_roas
    if margin < min_margin:
        reasons.append(f"贡献利润率 {margin:.1%} 低于 {min_margin:.0%}")
    if roas is None or roas > max_roas:
        reasons.append("保本 ROAS 超过风险上限")
    if product.sales_volume < min_sales:
        reasons.append("销量证据不足")
    if reasons:
        return SelectionDecision(
            product.product_id, SelectionStage.WATCH, tuple(reasons), exact_costs,
        )

    missing: list[str] = []
    if not exact_costs:
        missing.append("准确进货/物流/包装成本")
    if product.content_score is None:
        missing.append("内容可演示性评分")
    if product.compliance_risk == "unknown":
        missing.append("类目与商品合规结论")
    if product.supplier_moq is None or product.lead_time_days is None:
        missing.append("供应商 MOQ 与交期")
    if category_profiles and (not product.category_code or not profile):
        missing.append("家居日用/平价首饰赛道归类")
    required_labels = {
        "material_spec": "明确材质与镀层说明",
        "quality_evidence": "材质/耐用性证据或样品质检",
        "weight_kg": "单件包装后重量",
        "longest_side_cm": "包装最长边",
    }
    for field_name in profile.get("required_for_sample", []):
        value = getattr(product, field_name, None)
        if value in (None, "", False):
            missing.append(required_labels.get(field_name, field_name))
    if missing:
        return SelectionDecision(
            product.product_id,
            SelectionStage.SUPPLIER_VALIDATION,
            ("待补：" + "、".join(missing),),
            exact_costs,
        )

    return SelectionDecision(
        product.product_id,
        SelectionStage.SAMPLE_TEST,
        ("需求、内容、供应链、合规与压力利润均通过，可投入单件样品验证",),
        exact_costs,
    )
