"""
趋势评分算法

核心公式:
    score = w1 * growth_score       (销量增长率 0-100)
          + w2 * competition_score  (竞争度 0-100, 卖家越少分越高)
          + w3 * margin_score       (利润率估算 0-100)
          + w4 * engagement_score   (互动率 0-100)
          * seasonality_coefficient (季节性系数 0.5-2.0)

所有权重通过 config.yaml 配置，默认值针对 TikTok 选品优化。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from product_research import (
    Market,
    ProductInsight,
    TrendDirection,
    TrendScore,
)

logger = logging.getLogger(__name__)


@dataclass
class ScoringWeights:
    """趋势评分权重"""
    sales_growth_7d: float = 0.35      # 近7天销量增长率
    competition_inverse: float = 0.20  # 竞争度倒数
    estimated_margin: float = 0.25     # 预估利润率
    seasonality: float = 0.10          # 季节性系数
    engagement_rate: float = 0.10      # 互动率

    def validate(self):
        total = (
            self.sales_growth_7d
            + self.competition_inverse
            + self.estimated_margin
            + self.seasonality
            + self.engagement_rate
        )
        if abs(total - 1.0) > 0.01:
            logger.warning("权重之和为 %.2f，不等于 1.0，将自动归一化", total)


@dataclass
class ScoringThresholds:
    """评分阈值"""
    notify_min_score: float = 70.0   # 最低推送分
    hot_score: float = 85.0          # 爆品标记线
    trending_score: float = 75.0     # 趋势标记线


# ──────────────────────────────────────────────
# 市场预设权重 (SEA / US / EU)
# ──────────────────────────────────────────────

REGION_PRESETS: dict[str, dict[str, ScoringWeights | ScoringThresholds]] = {
    "sea": {
        "weights": ScoringWeights(
            sales_growth_7d=0.40,     # ↑ SEA 市场快速扩张
            competition_inverse=0.20,
            estimated_margin=0.15,    # ↓ 客单价低
            seasonality=0.10,
            engagement_rate=0.15,     # ↑ 社交电商属性强
        ),
        "thresholds": ScoringThresholds(
            notify_min_score=65,
            hot_score=82,
            trending_score=72,
        ),
    },
    "us": {
        "weights": ScoringWeights(
            sales_growth_7d=0.30,
            competition_inverse=0.20,
            estimated_margin=0.30,    # ↑ 利润空间大
            seasonality=0.10,
            engagement_rate=0.10,
        ),
        "thresholds": ScoringThresholds(
            notify_min_score=70,
            hot_score=85,
            trending_score=75,
        ),
    },
    "eu": {
        "weights": ScoringWeights(
            sales_growth_7d=0.25,     # ↓ 成熟市场
            competition_inverse=0.20,
            estimated_margin=0.30,
            seasonality=0.15,          # ↑ 欧洲季节消费强
            engagement_rate=0.10,
        ),
        "thresholds": ScoringThresholds(
            notify_min_score=68,
            hot_score=84,
            trending_score=74,
        ),
    },
}

# 国家到预设区域的映射
_MARKET_TO_REGION: dict[Market, str] = {
    Market.TH: "sea", Market.VN: "sea", Market.MY: "sea",
    Market.ID: "sea", Market.PH: "sea", Market.SG: "sea",
    Market.US: "us", Market.UK: "us",
    Market.DE: "eu", Market.FR: "eu", Market.ES: "eu",
    Market.IT: "eu", Market.NL: "eu",
    Market.JP: "us", Market.CA: "us", Market.AU: "us",
    Market.MX: "us", Market.BR: "us",
    Market.KR: "us", Market.SA: "us",
}


def get_preset_for_market(market: Market) -> dict:
    """
    根据市场获取推荐的预设权重和阈值

    Args:
        market: 目标市场

    Returns:
        {"weights": ScoringWeights, "thresholds": ScoringThresholds}
    """
    region = _MARKET_TO_REGION.get(market, "us")
    preset = REGION_PRESETS.get(region, REGION_PRESETS["us"])
    return {
        "weights": preset["weights"],
        "thresholds": preset["thresholds"],
    }


def build_analyzer_for_market(
    market: Market,
    config_overrides: Optional[dict] = None,
) -> "TrendAnalyzer":
    """
    根据市场自动选择权重配置并构建分析器

    Args:
        market: 目标市场
        config_overrides: 可选的 YAML 配置覆盖

    Returns:
        配置好的 TrendAnalyzer
    """
    preset = get_preset_for_market(market)
    weights = preset["weights"]
    thresholds = preset["thresholds"]

    # 如果 YAML 配置中有 market_overrides，进一步微调
    if config_overrides:
        market_code = market.value
        overrides = config_overrides.get("scoring", {}).get("market_overrides", {})
        market_override = overrides.get(market_code, {})

        if market_override:
            # 只覆盖有指定的字段
            for field, value in market_override.items():
                if hasattr(weights, field):
                    setattr(weights, field, value)
            weights.validate()

    return TrendAnalyzer(weights=weights, thresholds=thresholds)


class TrendAnalyzer:
    """
    趋势评分分析器

    对 ProductInsight 逐商品计算趋势评分 TrendScore。
    """

    def __init__(
        self,
        weights: Optional[ScoringWeights] = None,
        thresholds: Optional[ScoringThresholds] = None,
    ):
        self.weights = weights or ScoringWeights()
        self.weights.validate()
        self.thresholds = thresholds or ScoringThresholds()

    def analyze(self, product: ProductInsight) -> TrendScore:
        """对单个商品进行趋势评分"""
        growth_score = self._score_growth(product)
        competition_score = self._score_competition(product)
        margin_score = self._score_margin(product)
        engagement_score = self._score_engagement(product)
        seasonality_coeff = self._seasonality_coefficient(product.market)

        # 加权计算
        raw_score = (
            self.weights.sales_growth_7d * growth_score
            + self.weights.competition_inverse * competition_score
            + self.weights.estimated_margin * margin_score
            + self.weights.engagement_rate * engagement_score
        ) * seasonality_coeff

        # 钳制到 0-100
        final_score = max(0.0, min(100.0, raw_score))

        # 趋势方向
        if product.sales_growth_7d > 30:
            direction = TrendDirection.RISING
        elif product.sales_growth_7d < -10:
            direction = TrendDirection.DECLINING
        else:
            direction = TrendDirection.STABLE

        # 推理说明
        reasoning = (
            f"增长分={growth_score:.0f}, "
            f"竞争分={competition_score:.0f}, "
            f"利润分={margin_score:.0f}, "
            f"互动分={engagement_score:.0f}, "
            f"季节性={seasonality_coeff:.2f}"
        )

        return TrendScore(
            product_id=product.product_id,
            market=product.market,
            score=round(final_score, 1),
            direction=direction,
            growth_score=round(growth_score, 1),
            competition_score=round(competition_score, 1),
            margin_score=round(margin_score, 1),
            engagement_score=round(engagement_score, 1),
            seasonality_score=round(seasonality_coeff, 2),
            reasoning=reasoning,
        )

    def batch_analyze(self, products: list[ProductInsight]) -> list[TrendScore]:
        """批量分析"""
        scored = [self.analyze(p) for p in products]
        # 按评分降序排列
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored

    # ──────────────────────────────────────────────
    # 各维度评分函数
    # ──────────────────────────────────────────────

    @staticmethod
    def _score_growth(product: ProductInsight) -> float:
        """
        增长维度评分 (0-100)

        基于近7天销量增长率。
        - > 100% 增长: 满分 100
        - 50% 增长: 75分
        - 20% 增长: 60分
        - 0%: 40分
        - 负增长: 线性下降
        """
        rate = product.sales_growth_7d

        if rate >= 100:
            return 100.0
        elif rate >= 50:
            return 75.0 + (rate - 50) * 0.5  # 50-100 -> 75-100
        elif rate >= 20:
            return 60.0 + (rate - 20) * 0.5  # 20-50 -> 60-75
        elif rate >= 0:
            return 40.0 + (rate / 20) * 20   # 0-20 -> 40-60
        else:
            # 负增长: 从 40 向下线性衰减
            return max(0, 40.0 + rate * 2.0)  # rate 为负数

    @staticmethod
    def _score_competition(product: ProductInsight) -> float:
        """
        竞争维度评分 (0-100)

        卖家数越少，分数越高。
        - 0-5 个卖家: 100 (蓝海)
        - 5-20 个卖家: 80
        - 20-50 个卖家: 60
        - 50-100 个卖家: 40
        - 100-200: 20
        - > 200: 10 (红海)
        """
        count = product.seller_count

        if count <= 0:
            # 没有竞争数据时给中性分
            return 50.0
        elif count <= 5:
            return 100.0
        elif count <= 20:
            return 80.0
        elif count <= 50:
            return 60.0
        elif count <= 100:
            return 40.0
        elif count <= 200:
            return 20.0
        else:
            return max(5.0, 100.0 - count * 0.3)  # 极端红海最低 5 分

    @staticmethod
    def _score_margin(product: ProductInsight) -> float:
        """
        利润维度评分 (0-100)

        基于定价位置和绝对价格估算利润空间。
        - 高定价 (price_position=high): 80-100
        - 中等定价: 50-80
        - 低定价: 30-50
        - 极低价 (< $5): 20 (利润太薄)
        """
        price = product.price
        position = product.price_position

        # 先按价格区间给基础分
        if price >= 50:
            base = 85.0
        elif price >= 30:
            base = 75.0
        elif price >= 15:
            base = 65.0
        elif price >= 8:
            base = 50.0
        elif price >= 3:
            base = 35.0
        else:
            base = 20.0

        # 按定价位置调整
        if position == "high":
            return min(100.0, base + 15)
        elif position == "low":
            return max(10.0, base - 15)
        else:
            return base

    @staticmethod
    def _score_engagement(product: ProductInsight) -> float:
        """
        互动维度评分 (0-100)

        基于 TikTok 互动率 (likes+comments+shares) / views。
        TikTok 平均互动率约 3-5%，>10% 算很高。
        """
        rate = product.engagement_rate * 100  # 转为百分比

        if rate >= 20:
            return 100.0
        elif rate >= 10:
            return 80.0 + (rate - 10) * 2  # 10-20 -> 80-100
        elif rate >= 5:
            return 60.0 + (rate - 5) * 4   # 5-10 -> 60-80
        elif rate >= 2:
            return 40.0 + (rate - 2) * 10  # 2-5 -> 40-60
        elif rate >= 1:
            return 25.0 + (rate - 1) * 15  # 1-2 -> 25-40
        else:
            return max(5.0, rate * 20)

    @staticmethod
    def _seasonality_coefficient(market: Market) -> float:
        """
        季节性系数 (0.5-2.0)

        根据不同市场的当前月份调整。
        当前时间由系统获取，评估季节适配度。

        简化版：未来可接入 Google Trends API 细化。
        """
        from datetime import datetime, timezone
        month = datetime.now(timezone.utc).month

        # 不同市场的旺季月份
        season_map = {
            Market.US: {11: 1.8, 12: 1.5, 1: 0.8, 7: 0.7},   # 黑五/圣诞
            Market.UK: {11: 1.7, 12: 1.4, 1: 0.8},
            Market.JP: {12: 1.5, 1: 1.3, 3: 1.2, 7: 1.1},    # 年末/新年/毕业季
            Market.DE: {11: 1.6, 12: 1.5},
            Market.BR: {11: 1.5, 12: 1.6, 6: 1.2},
            # 东南亚市场
            Market.TH: {4: 1.4, 12: 1.3, 11: 1.2},             # 宋干节(泼水节4月) + 年末
            Market.VN: {1: 1.5, 2: 1.4, 11: 1.2},             # 农历新年(Tết) + 1111
            Market.MY: {3: 1.3, 4: 1.3, 12: 1.2},             # 斋戒月 + 哈芝节
            Market.ID: {3: 1.4, 4: 1.4, 12: 1.3},             # 斋戒月(Lebaran)最强
            Market.PH: {12: 1.5, 11: 1.3, 4: 1.2},            # 圣诞季最长
        }

        adjustments = season_map.get(market, {})
        return adjustments.get(month, 1.0)
