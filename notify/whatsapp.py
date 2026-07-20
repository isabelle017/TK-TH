"""
WhatsApp Business API 通知模块

东南亚客服第一大渠道。通过 Meta Cloud API 发送消息。
相比 Telegram，WhatsApp 在泰国/越南/马来西亚/印尼的渗透率更高。

使用前需要在 Meta Business Platform 配置:
1. 创建 WhatsApp Business Account
2. 获取 Phone Number ID
3. 生成 Access Token
4. 配置 Webhook (接收用户消息)
5. 设置环境变量:
   WHATSAPP_API_TOKEN=<your_token>
   WHATSAPP_PHONE_NUMBER_ID=<your_phone_number_id>

文档: https://developers.facebook.com/docs/whatsapp/cloud-api
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from product_research import PushMessage

logger = logging.getLogger(__name__)

# Meta Cloud API 端点
WHATSAPP_API_BASE = "https://graph.facebook.com/v21.0/{phone_number_id}/messages"


class WhatsAppNotifier:
    """
    WhatsApp Business API 通知推送

    支持:
    - 文本消息推送 (选品洞察)
    - 模板消息 (预设回复模板)
    - 批量发送
    - 发送状态回调
    """

    def __init__(
        self,
        token: Optional[str] = None,
        phone_number_id: Optional[str] = None,
        recipient: Optional[str] = None,
    ):
        self.token = token or os.getenv("WHATSAPP_API_TOKEN", "")
        self.phone_number_id = (
            phone_number_id or os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
        )
        self.recipient = recipient or os.getenv("WHATSAPP_RECIPIENT", "")

        if not self.token or self.token.startswith("${"):
            raise ValueError(
                "缺少 WhatsApp API Token。请设置 WHATSAPP_API_TOKEN 环境变量。"
            )
        if not self.phone_number_id or self.phone_number_id.startswith("${"):
            raise ValueError(
                "缺少 WhatsApp Phone Number ID。"
                "请设置 WHATSAPP_PHONE_NUMBER_ID 环境变量。"
            )

        self._api_url = WHATSAPP_API_BASE.format(
            phone_number_id=self.phone_number_id
        )
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def send(self, message: PushMessage, language: str = "en") -> bool:
        """
        发送选品推送消息

        Args:
            message: 推送消息对象
            language: 语言代码 (en/th/vi/ms)

        Returns:
            是否发送成功
        """
        text = message.format_telegram()
        # WhatsApp 不支持 Markdown，需要纯文本
        # 去除 Markdown 标记
        import re
        text = re.sub(r'[*`]', '', text)
        return self._send_text(text)

    def send_batch(self, messages: list[PushMessage], language: str = "en") -> int:
        """批量发送，返回成功数"""
        success = 0
        for msg in messages:
            if self.send(msg, language):
                success += 1
        return success

    def send_text(self, text: str) -> bool:
        """发送纯文本消息"""
        return self._send_text(text)

    def send_template(self, template_name: str, parameters: list[str]) -> bool:
        """
        发送 WhatsApp 模板消息（用于 COD 确认等场景）

        Args:
            template_name: 模板名称 (在 Meta Business 后台创建)
            parameters: 模板参数列表

        Returns:
            是否发送成功
        """
        payload = {
            "messaging_product": "whatsapp",
            "to": self.recipient,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "en"},
                "components": [{
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in parameters],
                }],
            },
        }

        try:
            resp = httpx.post(
                self._api_url,
                headers=self._headers,
                json=payload,
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                logger.error("WhatsApp 模板消息失败: %s", data["error"])
                return False
            return True

        except Exception as exc:
            logger.error("WhatsApp 模板消息异常: %s", exc)
            return False

    def _send_text(self, text: str) -> bool:
        """发送文本消息到 WhatsApp"""
        if not self.recipient:
            logger.error("WhatsApp 未配置接收号码")
            return False

        payload = {
            "messaging_product": "whatsapp",
            "to": self.recipient,
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text[:4096],  # WhatsApp 单条消息上限 4096 字符
            },
        }

        try:
            resp = httpx.post(
                self._api_url,
                headers=self._headers,
                json=payload,
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                logger.error("WhatsApp 发送失败: %s", data["error"])
                return False
            logger.debug("WhatsApp 消息已发送: message_id=%s",
                         data.get("messages", [{}])[0].get("id"))
            return True

        except httpx.HTTPStatusError as exc:
            logger.error("WhatsApp API HTTP 错误: %s", exc)
            return False
        except Exception as exc:
            logger.error("WhatsApp 发送异常: %s", exc)
            return False

    def send_cod_confirmation(self, order_id: str, customer_name: str,
                              amount: float) -> bool:
        """
        发送 COD 订单确认消息 (SEA 专属)

        在下单后主动联系买家确认，降低 COD 拒收率。
        """
        text = (
            f"🛵 COD 订单确认\n\n"
            f"订单编号: {order_id}\n"
            f"客户: {customer_name}\n"
            f"金额: ${amount:.2f}\n\n"
            f"请回复以下数字确认:\n"
            f"1️⃣ 确认收货，我会准备发货\n"
            f"2️⃣ 需要修改信息\n"
            f"3️⃣ 取消订单"
        )
        return self._send_text(text)


# ──────────────────────────────────────────────
# 统一通知器 (SEA 版 - 含 WhatsApp)
# ──────────────────────────────────────────────

class SEANotifier:
    """
    东南亚统一通知器

    支持同时推送到 Telegram + WhatsApp
    """

    def __init__(self, channel: str = "telegram"):
        self.channel = channel
        self._telegram = None
        self._whatsapp = None
        self.logger = logging.getLogger("notifier")

        # 初始化 Telegram
        if channel in ("telegram", "all"):
            try:
                from notify import TelegramNotifier
                self._telegram = TelegramNotifier()
            except Exception as exc:
                self.logger.warning("Telegram 未配置: %s", exc)

        # 初始化 WhatsApp
        if channel in ("whatsapp", "all"):
            try:
                self._whatsapp = WhatsAppNotifier()
            except Exception as exc:
                self.logger.warning("WhatsApp 未配置: %s", exc)

    def send(self, message: PushMessage, language: str = "en") -> bool:
        ok = True
        if self._telegram:
            ok = self._telegram.send(message) and ok
        if self._whatsapp:
            ok = self._whatsapp.send(message, language) and ok
        return ok

    def send_batch(self, messages: list[PushMessage],
                   language: str = "en") -> int:
        total = 0
        for msg in messages:
            if self.send(msg, language):
                total += 1
        return total

    def send_text(self, text: str) -> bool:
        ok = True
        if self._telegram:
            ok = self._telegram.send_text(text) and ok
        if self._whatsapp:
            ok = self._whatsapp.send_text(text) and ok
        return ok

    def send_cod_confirmation(self, order_id: str, customer_name: str,
                              amount: float) -> bool:
        """发送 COD 确认 (仅 WhatsApp)"""
        if self._whatsapp:
            return self._whatsapp.send_cod_confirmation(
                order_id, customer_name, amount
            )
        return False
