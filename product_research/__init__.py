"""
TikTok 选品自动化 - 数据模型

定义整个管道中流转的核心数据结构，使用 Pydantic 做类型校验。
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Market(str, Enum):
    """支持的国家/地区市场"""
    US = "us"
    UK = "uk"
    JP = "jp"
    DE = "de"
    FR = "fr"
    ES = "es"
    IT = "it"
    ID = "id"
    TH = "th"
    VN = "vn"
    PH = "ph"
    SG = "sg"
    MY = "my"
    SA = "sa"
    MX = "mx"
    BR = "br"
    KR = "kr"
    NL = "nl"
    CA = "ca"
    AU = "au"


class TrendDirection(str, Enum):
    RISING = "rising"      # 上升趋势
    STABLE = "stable"      # 平稳
    DECLINING = "declining"  # 下降趋势


class ProductInsight(BaseModel):
    """
    选品洞察 - 从数据源抓取并分析后的标准化商品信息
    """
    # 基础信息
    product_id: str = Field(..., description="商品 ID（数据源原始 ID）")
    title: str = Field(..., description="商品标题")
    price: float = Field(..., ge=0, description="售价 (USD)")
    sales_volume: int = Field(..., ge=0, description="总销量")
    sales_growth_7d: float = Field(default=0.0, description="近7天销量增长率（百分点，如 35 = +35%）")
    sales_growth_30d: float = Field(default=0.0, description="近30天销量增长率（百分点）")
    revenue_estimate: Optional[float] = Field(default=None, description="预估月收入 (USD)")

    # 竞争数据
    seller_count: int = Field(default=0, ge=0, description="在售卖家数")
    avg_price: float = Field(default=0.0, ge=0, description="同类商品均价 (USD)")
    price_position: str = Field(default="mid", description="定价位置: low/mid/high")

    # 店铺注册前即可收集的供应链与风险字段；缺失时只允许进入询价阶段。
    unit_cost_usd: Optional[float] = Field(default=None, ge=0)
    outbound_shipping_usd: Optional[float] = Field(default=None, ge=0)
    packaging_usd: Optional[float] = Field(default=None, ge=0)
    creator_commission_rate: Optional[float] = Field(default=None, ge=0, le=1)
    platform_fee_rate: Optional[float] = Field(default=None, ge=0, le=1)
    expected_return_rate: Optional[float] = Field(default=None, ge=0, le=1)
    expected_cod_share: Optional[float] = Field(default=None, ge=0, le=1)
    expected_cod_rejection_rate: Optional[float] = Field(default=None, ge=0, le=1)
    content_score: Optional[float] = Field(default=None, ge=0, le=100)
    compliance_risk: str = Field(default="unknown", description="low/medium/high/unknown")
    supplier_moq: Optional[int] = Field(default=None, ge=0)
    lead_time_days: Optional[int] = Field(default=None, ge=0)
    source_url: Optional[str] = None
    category_code: str = Field(default="", description="内部赛道代码")
    product_flags: list[str] = Field(default_factory=list)
    material_spec: Optional[str] = None
    quality_evidence: bool = False
    weight_kg: Optional[float] = Field(default=None, ge=0)
    longest_side_cm: Optional[float] = Field(default=None, ge=0)

    # TikTok 互动
    likes: int = Field(default=0, ge=0, description="总点赞数")
    comments: int = Field(default=0, ge=0, description="总评论数")
    shares: int = Field(default=0, ge=0, description="总分享数")
    engagement_rate: float = Field(default=0.0, description="互动率 (likes+comments+shares)/views")

    # 来源
    source: str = Field(..., description="数据来源: fastmoss / echotik")
    market: Market = Field(..., description="所属市场")

    # 时间
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), description="抓取时间"
    )

    model_config = {"frozen": False, "extra": "ignore"}


class CODInfo(BaseModel):
    """
    COD (货到付款) 信息 - SEA 市场专属

    COD 是东南亚核心支付方式，但拒收率直接影响利润。
    """
    cod_rate: float = Field(default=0.0, ge=0, le=1,
                            description="COD 支付占比 (0-1)")
    rejection_rate: float = Field(default=0.0, ge=0, le=1,
                                  description="COD 拒收率 (0-1)")
    estimated_loss: float = Field(default=0.0, ge=0,
                                  description="预估拒收损失 (USD)")
    delivery_days_estimate: str = Field(default="3-7",
                                        description="预计配送天数")

    # 优化建议
    needs_confirmation: bool = Field(default=True,
                                     description="是否需要 COD 确认流程")
    recommended_action: str = Field(
        default="",
        description="建议操作: send_confirmation / reduce_price / change_shipping"
    )


class SEAProductInsight(ProductInsight):
    """
    SEA 市场扩展商品洞察

    继承 ProductInsight，增加 COD 和本地支付信息。
    使用方式: 在东南亚管道中直接使用此类型。
    """
    cod: Optional[CODInfo] = Field(default=None, description="COD 信息")
    local_payment_options: list[str] = Field(
        default_factory=list,
        description="支持的本地支付方式",
    )
    average_order_value_local: Optional[float] = Field(
        default=None,
        description="本地货币客单价",
    )


class TrendScore(BaseModel):
    """
    趋势评分 - 算法输出的评分结果
    """
    product_id: str
    market: Market
    score: float = Field(..., ge=0, le=100, description="综合趋势评分 0-100")
    direction: TrendDirection = TrendDirection.STABLE
    # 各维度分项
    growth_score: float = Field(default=0.0, description="增长维度得分 (0-100)")
    competition_score: float = Field(default=0.0, description="竞争维度得分 (0-100)")
    margin_score: float = Field(default=0.0, description="利润维度得分 (0-100)")
    engagement_score: float = Field(default=0.0, description="互动维度得分 (0-100)")
    seasonality_score: float = Field(default=1.0, description="季节性系数 (0.5-2.0)")
    estimated_contribution_margin: Optional[float] = Field(
        default=None, description="按配置假设估算的单均贡献利润率"
    )
    max_allowable_cpa: Optional[float] = Field(
        default=None, description="盈亏平衡前最大可承受获客成本 (USD)"
    )
    break_even_roas: Optional[float] = Field(
        default=None, description="按配置假设估算的盈亏平衡 ROAS"
    )
    # 推理备注
    reasoning: str = Field(default="", description="评分的简要推理说明")


class SentimentResult(BaseModel):
    """ChatGPT 评论情感分析结果"""
    product_id: str
    positive_points: list[str] = Field(default_factory=list, description="用户最满意的点")
    pain_points: list[str] = Field(default_factory=list, description="用户抱怨的点")
    improvement_suggestions: list[str] = Field(default_factory=list, description="优化建议")
    overall_sentiment: str = Field(default="neutral", description="整体情感: positive/neutral/negative")
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PushMessage(BaseModel):
    """推送给用户的通知消息"""
    title: str
    body: str
    score: float
    product_id: str
    source: str
    market: str
    sentiment: Optional[SentimentResult] = None
    region: str = Field(default="us", description="区域: sea/us/eu")
    cod_info: Optional[CODInfo] = Field(default=None, description="COD 信息 (SEA)")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def format_telegram(self) -> str:
        """格式化为 Telegram 消息"""
        sentiment_block = ""
        if self.sentiment:
            pain = "\n".join(f"  ❌ {p}" for p in self.sentiment.pain_points[:3])
            good = "\n".join(f"  ✅ {g}" for g in self.sentiment.positive_points[:3])
            sentiment_block = f"\n💬 **评论洞察**\n好评:\n{good}\n痛点:\n{pain}"

        # 区域标签
        region_tag = {
            "sea": "🌏 东南亚",
            "us": "🇺🇸 欧美",
            "eu": "🇪🇺 欧洲",
        }.get(self.region, "")

        # COD 提醒 (SEA)
        cod_block = ""
        if self.cod_info and self.cod_info.cod_rate > 0.3:
            cod_block = (
                f"\n⚠️ **COD 注意**\n"
                f"• COD 占比: {self.cod_info.cod_rate*100:.0f}%\n"
                f"• 拒收率: {self.cod_info.rejection_rate*100:.0f}%\n"
                f"• 建议: {self.cod_info.recommended_action}"
            )

        return (
            f"{self.title}\n"
            f"{region_tag}\n\n"
            f"{self.body}\n\n"
            f"🏆 **评分**: {self.score:.0f}/100\n"
            f"📊 **来源**: {self.source.upper()} | {self.market.upper()}\n"
            f"🆔 **商品ID**: `{self.product_id}`\n"
            f"{sentiment_block}"
            f"{cod_block}\n\n"
            f"🕐 {self.timestamp.strftime('%Y-%m-%d %H:%M')}"
        )
