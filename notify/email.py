"""
邮件通知模块 - SMTP 邮件推送

支持 QQ邮箱 / 163邮箱 / Outlook / Gmail 等主流 SMTP 服务。
当 Telegram/WhatsApp 不可用时作为备选通知渠道。

使用前配置 .env:
    SMTP_HOST=smtp.office365.com
    SMTP_PORT=587
    SMTP_USER=your@email.com
    SMTP_PASSWORD=your_password
    NOTIFY_EMAIL=receiver@email.com
"""
from __future__ import annotations

import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from typing import Optional

from product_research import PushMessage

logger = logging.getLogger(__name__)

# 常见邮箱 SMTP 配置
SMTP_CONFIGS = {
    "outlook": {
        "host": "smtp.office365.com",
        "port": 587,
        "use_tls": True,
    },
    "qq": {
        "host": "smtp.qq.com",
        "port": 465,
        "use_tls": True,  # SSL
    },
    "163": {
        "host": "smtp.163.com",
        "port": 465,
        "use_tls": True,
    },
    "gmail": {
        "host": "smtp.gmail.com",
        "port": 587,
        "use_tls": True,
    },
}


def detect_email_provider(email: str) -> str:
    """根据邮箱地址自动检测提供商"""
    domain = email.lower().split("@")[-1] if "@" in email else ""
    if "outlook" in domain or "hotmail" in domain:
        return "outlook"
    elif "qq" in domain:
        return "qq"
    elif "163" in domain:
        return "163"
    elif "gmail" in domain:
        return "gmail"
    return "outlook"  # 默认


class EmailNotifier:
    """
    SMTP 邮件通知

    支持自定义 SMTP 配置，自动检测常见邮箱提供商。

    使用示例:
        notifier = EmailNotifier(
            smtp_host="smtp.office365.com",
            smtp_port=587,
            smtp_user="isabelle2035@outlook.com",
            smtp_password="your_password",
            notify_email="isabelle2035@outlook.com",  # 收件人(可同地址)
        )
        notifier.send_text("测试消息")
    """

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        notify_email: Optional[str] = None,
        use_tls: bool = True,
    ):
        self.smtp_user = smtp_user or os.getenv("SMTP_USER", "")
        self.smtp_password = smtp_password or os.getenv("SMTP_PASSWORD", "")
        self.notify_email = notify_email or os.getenv("NOTIFY_EMAIL", "")

        if not self.smtp_user or self.smtp_user.startswith("${"):
            raise ValueError("缺少 SMTP 邮箱地址，请设置 SMTP_USER 环境变量")
        if not self.smtp_password or self.smtp_password.startswith("${"):
            raise ValueError("缺少 SMTP 密码，请设置 SMTP_PASSWORD 环境变量")

        # 自动检测提供商配置
        provider = detect_email_provider(self.smtp_user)
        config = SMTP_CONFIGS.get(provider, SMTP_CONFIGS["outlook"])

        self.smtp_host = smtp_host or os.getenv("SMTP_HOST", config["host"])
        self.smtp_port = smtp_port or int(os.getenv("SMTP_PORT", str(config["port"])))
        self.use_tls = use_tls

        # 如果未指定收件人，默认发给发件人自己
        if not self.notify_email or self.notify_email.startswith("${"):
            self.notify_email = self.smtp_user

        logger.info(
            "邮件通知已配置: %s -> %s (%s:%d)",
            self.smtp_user, self.notify_email,
            self.smtp_host, self.smtp_port,
        )

    def send(self, message: PushMessage) -> bool:
        """发送选品推送邮件"""
        subject = f"[TK选品] {message.title[:60]}"
        body = message.format_telegram()
        # Telegram Markdown 转纯文本
        import re
        body = re.sub(r'[*`]', '', body)
        return self._send_mail(subject, body)

    def send_batch(self, messages: list[PushMessage]) -> int:
        """批量发送"""
        success = 0
        for msg in messages:
            if self.send(msg):
                success += 1
        return success

    def send_text(self, text: str) -> bool:
        """发送纯文本通知"""
        return self._send_mail("[TK选品] 通知", text)

    def _send_mail(self, subject: str, body: str) -> bool:
        """发送邮件 (自动尝试 STARTTLS / SSL / 明文)"""
        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = self.smtp_user
            msg["To"] = self.notify_email

            # 策略1: STARTTLS (587)
            try:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10) as server:
                    server.ehlo()
                    server.starttls()
                    server.ehlo()
                    server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.smtp_user, [self.notify_email], msg.as_string())
                logger.info("邮件已发送(STARTTLS): %s -> %s", self.smtp_user, self.notify_email)
                return True
            except (smtplib.SMTPException, OSError):
                pass

            # 策略2: SSL (465)
            try:
                with smtplib.SMTP_SSL(self.smtp_host, 465, timeout=10) as server:
                    server.login(self.smtp_user, self.smtp_password)
                    server.sendmail(self.smtp_user, [self.notify_email], msg.as_string())
                logger.info("邮件已发送(SSL): %s -> %s", self.smtp_user, self.notify_email)
                return True
            except (smtplib.SMTPException, OSError):
                pass

            logger.error("邮件发送失败: %s:%d (STARTTLS 和 SSL 都不通)", self.smtp_host, self.smtp_port)
            return False

        except Exception as exc:
            logger.error("邮件发送异常: %s", exc)
            return False


# ──────────────────────────────────────────────
# 统一通知器 (含邮件)
# ──────────────────────────────────────────────

class NotifierWithEmail:
    """支持邮件回退的统一通知器"""

    def __init__(self):
        self._email = None
        self.logger = logging.getLogger("notifier")

        try:
            self._email = EmailNotifier()
            self.logger.info("邮件通知就绪")
        except ValueError as exc:
            self.logger.warning("邮件未配置: %s", exc)

    def send(self, message: PushMessage) -> bool:
        if self._email:
            return self._email.send(message)
        return False

    def send_batch(self, messages: list[PushMessage]) -> int:
        if self._email:
            return self._email.send_batch(messages)
        return 0

    def send_text(self, text: str) -> bool:
        if self._email:
            return self._email.send_text(text)
        return False
