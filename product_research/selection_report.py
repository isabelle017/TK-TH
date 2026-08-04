"""Markdown output for the pre-store product-selection funnel."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from product_research import ProductInsight, TrendScore
from product_research.selection_engine import SelectionDecision, SelectionStage

STAGE_LABELS = {
    SelectionStage.SAMPLE_TEST: "样品测试",
    SelectionStage.SUPPLIER_VALIDATION: "询价/合规验证",
    SelectionStage.WATCH: "观察",
    SelectionStage.REJECT: "淘汰",
}


def write_selection_report(
    rows: list[tuple[ProductInsight, TrendScore, SelectionDecision]],
    output_path: str = "reports/latest_selection.md",
) -> str:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = {
        stage: sum(1 for _, _, decision in rows if decision.stage == stage)
        for stage in SelectionStage
    }
    lines = [
        "# 泰国店铺注册前选品报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "> 本报告不依赖店铺 ID。没有准确供应链成本的商品只能进入询价阶段，不能直接采购。",
        "",
        "## 漏斗概览",
        "",
        f"- 样品测试：{counts[SelectionStage.SAMPLE_TEST]}",
        f"- 询价/合规验证：{counts[SelectionStage.SUPPLIER_VALIDATION]}",
        f"- 观察：{counts[SelectionStage.WATCH]}",
        f"- 淘汰：{counts[SelectionStage.REJECT]}",
        "",
        "## 候选明细",
        "",
        "| 阶段 | 赛道 | 商品 | 售价(USD) | 分数 | 7日增长 | 估算贡献利润率 | 保本ROAS | 依据 |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ]
    order = {
        SelectionStage.SAMPLE_TEST: 0,
        SelectionStage.SUPPLIER_VALIDATION: 1,
        SelectionStage.WATCH: 2,
        SelectionStage.REJECT: 3,
    }
    for product, score, decision in sorted(rows, key=lambda row: (order[row[2].stage], -row[1].score)):
        title = product.title.replace("|", "/")[:60]
        if product.source_url:
            safe_url = product.source_url.replace(" ", "%20").replace(")", "%29")
            title = f"[{title}]({safe_url})"
        reasons = "；".join(decision.reasons).replace("|", "/")
        margin = score.estimated_contribution_margin
        margin_text = f"{margin:.1%}" if margin is not None else "-"
        roas_text = f"{score.break_even_roas:.2f}" if score.break_even_roas else "-"
        lines.append(
            f"| {STAGE_LABELS[decision.stage]} | {product.category_code or '-'} | {title} | ${product.price:.2f} | {score.score:.1f} | "
            f"{product.sales_growth_7d:.1f}% | {margin_text} | {roas_text} | {reasons} |"
        )
    lines.extend([
        "",
        "## 后续店铺信息覆盖",
        "",
        "店铺注册后只需更新平台类目费率、结算费率、仓配报价和实际退货/COD数据；"
        "商品趋势、供应链和内容验证结果继续保留。",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)
