import unittest
from unittest.mock import patch

from notify.email import EmailNotifier, detect_email_provider
from product_research import PushMessage


class NotificationTests(unittest.TestCase):
    def test_formatted_message_contains_financial_body(self):
        message = PushMessage(
            title="Candidate",
            body="Contribution margin 18%",
            score=80,
            product_id="p1",
            source="test",
            market="th",
        )
        self.assertIn("Contribution margin 18%", message.format_telegram())

    def test_qq_email_provider_uses_ssl_endpoint(self):
        self.assertEqual("qq", detect_email_provider("sender@qq.com"))

        env = {
            "SMTP_USER": "sender@qq.com",
            "SMTP_PASSWORD": "authorization-code",
            "NOTIFY_EMAIL": "recipient@example.com",
        }
        with patch.dict("os.environ", env, clear=True):
            notifier = EmailNotifier()

        self.assertEqual("smtp.qq.com", notifier.smtp_host)
        self.assertEqual(465, notifier.smtp_port)
        self.assertEqual("recipient@example.com", notifier.notify_email)


if __name__ == "__main__":
    unittest.main()
