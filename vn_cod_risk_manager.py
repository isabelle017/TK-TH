"""
越南 COD 拒收风控管理模块

越南 COD (货到付款) 占比高达 70-80%，拒收率 15-25%，
是越南市场最大的利润杀手。

本模块提供:
1. 拒收风险评分 - 下单时评估拒收概率
2. COD 确认流程 - WhatsApp 自动确认机制
3. 拒收策略引擎 - 按原因分类 + 自动处理
4. 拒收报表 - 监控拒收趋势

使用方法:
    manager = CODRiskManager()

    # 风险评估
    risk = manager.assess_risk(
        order_amount=250000,
        customer_province="Hồ Chí Minh",
        category="beauty",
    )

    # 执行确认流程
    await manager.execute_confirmation_flow(
        order_id="VN12345",
        customer_phone="+84912345678",
        customer_name="Nguyen Van A",
        amount=250000,
    )
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 枚举 & 数据模型
# ──────────────────────────────────────────────

class RejectionCategory(str, Enum):
    """拒收原因分类"""
    SECOND_THOUGHT = "冲动后悔"         # A类: 可预防
    FOUND_CHEAPER = "找到更便宜的"       # A类
    LONG_DELIVERY = "配送太久"           # B类: 物流相关
    WRONG_ADDRESS = "地址错误"           # B类
    UNREACHABLE = "联系不上"             # B类
    NOT_AT_HOME = "不在家"               # C类: 不可控
    THIRD_PARTY = "代收人拒收"           # C类
    OTHER = "其他"                       # 未知


class RiskLevel(str, Enum):
    LOW = "low"            # 低风险，正常发货
    MEDIUM = "medium"      # 中风险，建议确认后发货
    HIGH = "high"          # 高风险，建议先不发，确认再发
    BLOCKED = "blocked"    # 禁止发货


@dataclass
class RiskAssessment:
    """风险评估结果"""
    order_id: str
    risk_level: RiskLevel
    risk_score: float           # 0-100
    rejection_probability: float # 预估拒收概率 (0-1)
    factors: list[str]          # 影响因素
    recommended_action: str     # 建议操作
    assessed_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class CODConfirmation:
    """COD 确认记录"""
    order_id: str
    customer_phone: str
    customer_name: str
    amount_vnd: float           # 越南盾
    attempts: int = 0           # 已确认次数
    last_attempt_at: Optional[datetime] = None
    confirmed: bool = False
    rejected: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────
# 高风险地区库 (内置)
# ──────────────────────────────────────────────

# 越南各省市拒收率参考数据:
# 数据来源: 行业经验 + 公开报 (仅供参考，建议根据实际数据校准)
_HIGH_RISK_PROVINCES: set[str] = {
    "Hà Nội", "Hồ Chí Minh",          # 大城市: 高 COD 单量，拒收率高
    "Bình Dương", "Đồng Nai",         # 工业省份: 工人拒收率高
    "An Giang", "Kiên Giang",         # 湄公河三角洲: 偏远，配送时间长
    "Sóc Trăng", "Bạc Liêu",
    "Lạng Sơn", "Lào Cai",            # 边境省份: 配送难度大
    "Kon Tum", "Gia Lai",             # 中部高原: 偏远
}

_MEDIUM_RISK_PROVINCES: set[str] = {
    "Đà Nẵng", "Hải Phòng", "Cần Thơ",
    "Quảng Ninh", "Thừa Thiên Huế", "Nghệ An",
    "Thanh Hóa", "Đắk Lắk", "Lâm Đồng",
}


# ──────────────────────────────────────────────
# 核心类
# ──────────────────────────────────────────────

class CODRiskManager:
    """
    COD 拒收风控管理器

    核心流程:
    ```
    下单 → 风险评估 → 低风险 → 发货
                    → 中/高风险 → COD 确认流程
                                → 用户确认 → 发货
                                → 用户未确认 → 暂缓发货 + 二次提醒
                                → 用户拒收 → 标记 + 分析原因
    ```

    使用前需要配置:
    - WHATSAPP_API_TOKEN (可选，用于自动发送确认消息)
    - WHATSAPP_PHONE_NUMBER_ID
    """

    def __init__(self):
        self._confirmations: dict[str, CODConfirmation] = {}

    # ──────────────────────────────────────────────
    # 1. 风险评估
    # ──────────────────────────────────────────────

    def assess_risk(
        self,
        order_id: str,
        amount_vnd: float,
        customer_province: str,
        category: str = "",
        is_first_order: bool = True,
    ) -> RiskAssessment:
        """
        评估 COD 拒收风险

        Args:
            order_id: 订单号
            amount_vnd: 订单金额 (越南盾)
            customer_province: 省份
            category: 品类
            is_first_order: 是否首单

        Returns:
            RiskAssessment
        """
        factors: list[str] = []
        score = 0.0

        # 1. 金额因素 (20分)
        # 越南盾兑美元约 1 USD = 25,000 VND
        usd_amount = amount_vnd / 25_000
        if usd_amount > 30:
            score += 20
            factors.append(f"高客单价 (${usd_amount:.0f}) → 拒收风险增加")
        elif usd_amount > 15:
            score += 10
            factors.append(f"中等客单价 (${usd_amount:.0f})")
        elif usd_amount < 5:
            score -= 10  # 低客单价风险低
            factors.append(f"低客单价 (${usd_amount:.0f}) → 风险降低")

        # 2. 地区因素 (30分)
        province_upper = customer_province.strip().title()
        if province_upper in _HIGH_RISK_PROVINCES:
            score += 30
            factors.append(f"高风险地区: {customer_province}")
        elif province_upper in _MEDIUM_RISK_PROVINCES:
            score += 15
            factors.append(f"中等风险地区: {customer_province}")
        else:
            score -= 10
            factors.append(f"低风险地区: {customer_province}")

        # 3. 首单因素 (20分)
        if is_first_order:
            score += 20
            factors.append("首单用户 → 拒收概率更高")

        # 4. 品类因素 (15分)
        high_risk_categories = {"fashion", "accessories", "cosmetics"}
        low_risk_categories = {"food", "baby", "home_essential"}
        if category.lower() in high_risk_categories:
            score += 15
            factors.append(f"高拒收品类: {category}")
        elif category.lower() in low_risk_categories:
            score -= 10
            factors.append(f"低拒收品类: {category}")

        # 5. 时段因素 (15分)
        hour = datetime.now().hour
        if 22 <= hour or hour <= 5:
            score += 15
            factors.append("深夜下单 → 冲动消费概率高")
        elif 12 <= hour <= 14:
            score += 5
            factors.append("午休下单")

        # 钳制到 0-100
        score = max(0.0, min(100.0, score))

        # 风险等级判定
        if score >= 70:
            risk = RiskLevel.BLOCKED
            action = "暂缓发货，确认后再发"
        elif score >= 45:
            risk = RiskLevel.HIGH
            action = "建议发送 COD 确认消息，确认后发货"
        elif score >= 25:
            risk = RiskLevel.MEDIUM
            action = "建议发送简单确认消息"
        else:
            risk = RiskLevel.LOW
            action = "正常发货"

        # 拒收概率估算
        prob = score / 100.0 * 0.6  # 最高 60% 预估拒收率
        prob = min(prob, 0.6)

        return RiskAssessment(
            order_id=order_id,
            risk_level=risk,
            risk_score=round(score, 1),
            rejection_probability=round(prob, 2),
            factors=factors,
            recommended_action=action,
        )

    # ──────────────────────────────────────────────
    # 2. COD 确认流程
    # ──────────────────────────────────────────────

    async def execute_confirmation_flow(
        self,
        order_id: str,
        customer_phone: str,
        customer_name: str,
        amount_vnd: float,
    ) -> CODConfirmation:
        """
        执行 COD 确认流程

        流程:
        1. 创建确认记录
        2. 发送首次确认消息 (WhatsApp)
        3. 等待确认 (实际确认通过 WhatsApp Webhook 接收)
        4. 若 4 小时未回复，发送二次提醒
        5. 若仍无回复，标记为高风险

        Args:
            order_id: 订单号
            customer_phone: 客户手机号 (含国际区号)
            customer_name: 客户名
            amount_vnd: 金额 (越南盾)

        Returns:
            CODConfirmation
        """
        confirmation = CODConfirmation(
            order_id=order_id,
            customer_phone=customer_phone,
            customer_name=customer_name,
            amount_vnd=amount_vnd,
        )

        self._confirmations[order_id] = confirmation

        # 发送首次确认
        success = await self._send_confirmation_message(
            phone=customer_phone,
            name=customer_name,
            order_id=order_id,
            amount_vnd=amount_vnd,
            attempt=1,
        )

        if success:
            confirmation.attempts = 1
            confirmation.last_attempt_at = datetime.utcnow()
            logger.info("COD 确认已发送: 订单 %s, 电话 %s",
                        order_id, customer_phone)
        else:
            logger.warning("COD 确认发送失败: 订单 %s", order_id)

        return confirmation

    async def _send_confirmation_message(
        self,
        phone: str,
        name: str,
        order_id: str,
        amount_vnd: float,
        attempt: int,
    ) -> bool:
        """
        发送 COD 确认消息 (越南语)

        WhatsApp 模板或文本消息
        """
        amount_formatted = f"{amount_vnd:,.0f}"

        # 越南语确认文本
        message = (
            f"Xin chào {name},\n\n"
            f"Cảm ơn bạn đã đặt hàng tại cửa hàng của chúng tôi!\n\n"
            f"🛵 **Mã đơn hàng:** {order_id}\n"
            f"💰 **Tổng tiền:** {amount_formatted}₫\n"
            f"📦 **Thanh toán:** COD (trả tiền khi nhận hàng)\n\n"
            f"Vui lòng xác nhận:\n"
            f"1️⃣ **Tôi vẫn muốn nhận hàng** - Tiến hành giao hàng\n"
            f"2️⃣ **Tôi muốn hủy đơn** - Hủy đơn hàng\n\n"
            f"Nếu không phản hồi trong 4 giờ, "
            f"chúng tôi sẽ gọi điện xác nhận.\n"
            f"Cảm ơn bạn! 🙏"
        )

        # 通过 WhatsApp 发送
        token = os.getenv("WHATSAPP_API_TOKEN", "")
        phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

        if token and phone_id and not token.startswith("${"):
            try:
                import httpx
                url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }
                payload = {
                    "messaging_product": "whatsapp",
                    "to": phone,
                    "type": "text",
                    "text": {"preview_url": False, "body": message},
                }
                resp = await httpx.AsyncClient().post(
                    url, headers=headers, json=payload, timeout=15.0
                )
                resp.raise_for_status()
                return True

            except Exception as exc:
                logger.error("WhatsApp 发送确认失败: %s", exc)
        else:
            logger.warning(
                "WhatsApp 未配置，打印确认消息到日志:\n%s\n"
                "实际使用时请配置 WHATSAPP_API_TOKEN 和 WHATSAPP_PHONE_NUMBER_ID",
                message,
            )
            # 模拟成功 (方便测试)
            return True

        return False

    def handle_confirmation_response(
        self,
        order_id: str,
        confirmed: bool,
        rejection_reason: Optional[str] = None,
    ) -> None:
        """
        处理用户确认响应 (由 WhatsApp Webhook 接收后调用)

        Args:
            order_id: 订单号
            confirmed: true=确认收货 / false=取消
            rejection_reason: 取消原因
        """
        confirmation = self._confirmations.get(order_id)
        if not confirmation:
            logger.warning("未找到 COD 确认记录: %s", order_id)
            return

        confirmation.confirmed = confirmed

        if confirmed:
            logger.info("订单 %s 用户确认收货 ✅", order_id)
        else:
            confirmation.rejected = True
            category = self._classify_rejection(
                rejection_reason or "未提供原因"
            )
            logger.info("订单 %s 用户拒收 ❌ (原因: %s, 分类: %s)",
                        order_id, rejection_reason, category)

    def get_pending_reminders(self) -> list[CODConfirmation]:
        """
        获取需要发送二次提醒的记录

        规则: 首次确认后已过 4 小时且未回复

        Returns:
            需要提醒的确认列表
        """
        now = datetime.utcnow()
        pending = []

        for conf in self._confirmations.values():
            if conf.confirmed or conf.rejected:
                continue
            if conf.last_attempt_at and conf.attempts >= 2:
                continue  # 已提醒过 2 次
            if conf.last_attempt_at:
                elapsed = (now - conf.last_attempt_at).total_seconds()
                if elapsed > 4 * 3600:  # 4 小时
                    pending.append(conf)

        return pending

    # ──────────────────────────────────────────────
    # 3. 拒收原因分类
    # ──────────────────────────────────────────────

    @staticmethod
    def _classify_rejection(reason: str) -> RejectionCategory:
        """
        将用户提供的拒收原因分类

        支持带音调和不带音调的越南语（因为大量越南用户打字不打音调）
        """
        reason_lower = reason.lower()

        # 兼容不带音调的越南语 (telex/vni 风格)
        # 常见映射: o^ -> o, u' -> u, a' -> a, d' -> d, etc.
        # 这里直接同时匹配两种写法

        # A类: 可预防 - Second thoughts / Changed mind
        if any(kw in reason_lower for kw in [
            "không muốn", "thay đổi ý định", "mua rồi",
            "không cần nữa",
            # 无音调版
            "khong muon", "thay doi y dinh", "mua roi",
            "khong can nua", "khong mua nua",
            "doi y",
        ]):
            return RejectionCategory.SECOND_THOUGHT

        if any(kw in reason_lower for kw in [
            "rẻ hơn", "tìm thấy giá rẻ", "mua ở chỗ khác",
            # 无音调版
            "re hon", "tim thay gia re", "mua o cho khac",
            "gia re hon",
        ]):
            return RejectionCategory.FOUND_CHEAPER

        # B类: 物流相关
        if any(kw in reason_lower for kw in [
            "lâu quá", "chậm", "giao lâu", "không chờ được",
            # 无音调版
            "lau qua", "cham", "giao lau", "khong cho duoc",
            "giao hang cham", "toi qua lau",
        ]):
            return RejectionCategory.LONG_DELIVERY

        if any(kw in reason_lower for kw in [
            "sai địa chỉ", "nhầm địa chỉ", "không đúng địa chỉ",
            # 无音调版
            "sai dia chi", "nham dia chi", "khong dung dia chi",
            "dia chi sai",
        ]):
            return RejectionCategory.WRONG_ADDRESS

        if any(kw in reason_lower for kw in [
            "không liên lạc được", "gọi không được",
            # 无音调版
            "khong lien lac duoc", "goi khong duoc",
            "khong nghe may",
        ]):
            return RejectionCategory.UNREACHABLE

        # C类: 不可控
        if any(kw in reason_lower for kw in [
            "không có nhà", "đi vắng", "đi công tác",
            # 无音调版
            "khong co nha", "di vang", "di cong tac",
            "di lam", "vang nha", "khong o nha",
        ]):
            return RejectionCategory.NOT_AT_HOME

        if any(kw in reason_lower for kw in [
            "người khác nhận", "không phải tôi",
            # 无音调版
            "nguoi khac nhan", "khong phai toi",
            "nguoi khac",
        ]):
            return RejectionCategory.THIRD_PARTY

        return RejectionCategory.OTHER

        # C类: 不可控
        if any(kw in reason_lower for kw in [
            "không có nhà", "đi vắng", "đi công tác",
        ]):
            return RejectionCategory.NOT_AT_HOME

        if any(kw in reason_lower for kw in [
            "người khác nhận", "không phải tôi",
        ]):
            return RejectionCategory.THIRD_PARTY

        return RejectionCategory.OTHER

    # ──────────────────────────────────────────────
    # 4. 策略建议
    # ──────────────────────────────────────────────

    def get_strategy_tips(self, current_rejection_rate: float) -> list[str]:
        """
        基于当前拒收率返回优化建议

        Args:
            current_rejection_rate: 当前拒收率 (0-1)

        Returns:
            建议列表
        """
        tips = ["🇻🇳 **越南 COD 优化建议**\n"]

        if current_rejection_rate > 0.25:
            tips.extend([
                "🔴 **拒收率过高 (>25%)**",
                "• 立即启用 COD 确认流程 (WhatsApp 确认)",
                "• 检查高拒收地区，考虑调整配送策略",
                "• 避免深夜时间段推送促销",
                "• 考虑对接拒收保险 (如:  Allied World / AIG 越南)",
            ])
        elif current_rejection_rate > 0.15:
            tips.extend([
                "🟡 **拒收率偏高 (15-25%)**",
                "• 对首单用户 & 高客单价 (>$20) 执行 COD 确认",
                "• 优化配送时间预估，减少因配送久导致的拒收",
                "• 在订单页增加明确的配送时间说明",
            ])
        else:
            tips.extend([
                "🟢 **拒收率正常 (<15%)**",
                "• 维持现有流程",
                "• 持续监控地区级拒收率变化",
                "• 建议对 $30+ 订单仍保持确认流程",
            ])

        # 通用建议
        tips.extend([
            "",
            "**越南 COD 最佳实践:**",
            "• 用 WhatsApp 确认后，拒收率可降低 10-15%",
            "• $5-15 是越南 TikTok COD 的甜蜜点价格区间",
            "• 周一/二下单的拒收率最低 (周四五最高)",
            "• 催付最佳时间: 上午 9-11 点",
            "• 二次配送可挽回 30-40% 的拒收订单",
        ])

        return tips

    # ──────────────────────────────────────────────
    # 5. 统计报表
    # ──────────────────────────────────────────────

    def get_rejection_report(self) -> dict:
        """生成拒收统计报告"""
        total = len(self._confirmations)
        confirmed = sum(1 for c in self._confirmations.values() if c.confirmed)
        rejected = sum(1 for c in self._confirmations.values() if c.rejected)
        pending = sum(1 for c in self._confirmations.values()
                      if not c.confirmed and not c.rejected)

        return {
            "total_orders": total,
            "confirmed": confirmed,
            "rejected": rejected,
            "pending": pending,
            "confirmation_rate": round(confirmed / max(total, 1) * 100, 1),
            "rejection_rate": round(rejected / max(total, 1) * 100, 1),
            "saved_by_confirmation": round(
                rejected * 0.35, 1  # 预估确认流程挽回 35%
            ),
        }


# ──────────────────────────────────────────────
# 便捷函数
# ──────────────────────────────────────────────

def get_cod_manager() -> CODRiskManager:
    """快速获取 COD 风控管理器"""
    return CODRiskManager()
