"""
通知模块 - Telegram Bot / 企业微信机器人 / WhatsApp

将选品洞察推送到即时通讯工具，支持 Telegram、WhatsApp、企业微信。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from product_research import PushMessage

logger = logging.getLogger(__name__)

# Export main notifiers
__all__ = [
    "TelegramNotifier", "WeComNotifier", "Notifier",
    "WhatsAppNotifier", "SEANotifier",
]

# ──────────────────────────────────────────────
# Telegram Bot 通知
# ──────────────────────────────────────────────

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


class TelegramNotifier:
    """
    Telegram Bot 推送

    使用步骤:
    1. 在 Telegram 中搜索 @BotFather，创建 Bot，获取 Token
    2. 搜索你的 Bot，发一条消息给他
    3. 访问 https://api.telegram.org/bot<你的Token>/getUpdates 获取 chat_id
    4. 将 Token 和 chat_id 填入配置或环境变量
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")

        if not self.bot_token or self.bot_token.startswith("${"):
            raise ValueError(
                "缺少 Telegram Bot Token。请设置 TELEGRAM_BOT_TOKEN 环境变量。"
            )
        if not self.chat_id or self.chat_id.startswith("${"):
            raise ValueError(
                "缺少 Telegram Chat ID。请设置 TELEGRAM_CHAT_ID 环境变量。"
            )

        self._api_url = TELEGRAM_API.format(token=self.bot_token)

    def send(self, message: PushMessage) -> bool:
        """发送单条推送"""
        text = message.format_telegram()
        return self._send_text(text)

    def send_batch(self, messages: list[PushMessage]) -> int:
        """批量发送，返回成功数"""
        success = 0
        for msg in messages:
            ok = self.send(msg)
            if ok:
                success += 1
        return success

    def send_text(self, text: str) -> bool:
        """发送纯文本（用于非商品消息，如系统通知）"""
        return self._send_text(text)

    def _send_text(self, text: str) -> bool:
        """发送文本消息到 Telegram"""
        try:
            resp = httpx.post(
                self._api_url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"):
                logger.error("Telegram API 返回错误: %s", data.get("description"))
                return False
            return True

        except httpx.HTTPStatusError as exc:
            logger.error("Telegram 推送 HTTP 失败: %s", exc)
            return False
        except Exception as exc:
            logger.error("Telegram 推送异常: %s", exc)
            return False


# ──────────────────────────────────────────────
# 企业微信机器人通知
# ──────────────────────────────────────────────

class WeComNotifier:
    """
    企业微信群机器人推送

    使用步骤:
    1. 在企业微信群中添加群机器人
    2. 复制 Webhook URL
    3. 设置环境变量 WECOM_WEBHOOK_URL
    """

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("WECOM_WEBHOOK_URL", "")
        if not self.webhook_url or self.webhook_url.startswith("${"):
            raise ValueError(
                "缺少企业微信 Webhook URL。请设置 WECOM_WEBHOOK_URL 环境变量。"
            )

    def send(self, message: PushMessage) -> bool:
        """发送单条推送"""
        text = message.format_telegram()  # 复用 Telegram 格式
        return self._send_markdown(text)

    def send_text(self, text: str) -> bool:
        return self._send_markdown(text)

    def _send_markdown(self, text: str) -> bool:
        """发送 Markdown 消息"""
        try:
            resp = httpx.post(
                self.webhook_url,
                json={
                    "msgtype": "markdown",
                    "markdown": {"content": text},
                },
                timeout=15.0,
            )
            resp.raise_for_status()
            return True

        except Exception as exc:
            logger.error("企业微信推送失败: %s", exc)
            return False


# ──────────────────────────────────────────────
# 统一通知接口
# ──────────────────────────────────────────────

class Notifier:
    """
    统一通知器 - 根据配置选择推送渠道
    """

    def __init__(self, channel: str = "telegram"):
        self.channel = channel
        self._telegram: Optional[TelegramNotifier] = None
        self._wecom: Optional[WeComNotifier] = None

        # 按需初始化
        if channel in ("telegram", "all"):
            try:
                self._telegram = TelegramNotifier()
            except ValueError as exc:
                logger.warning("Telegram 未配置: %s", exc)

        if channel in ("wecom", "all"):
            try:
                self._wecom = WeComNotifier()
            except ValueError as exc:
                logger.warning("企业微信未配置: %s", exc)

    def send(self, message: PushMessage) -> bool:
        """推送消息到所有已配置的渠道"""
        ok = True

        if self._telegram:
            ok = self._telegram.send(message) and ok

        if self._wecom:
            ok = self._wecom.send(message) and ok

        return ok

    def send_batch(self, messages: list[PushMessage]) -> int:
        """批量发送"""
        total = 0
        for msg in messages:
            if self.send(msg):
                total += 1
        return total

    def send_text(self, text: str) -> bool:
        """发送纯文本通知"""
        ok = True
        if self._telegram:
            ok = self._telegram.send_text(text) and ok
        if self._wecom:
            ok = self._wecom.send_text(text) and ok
        return ok
