import unittest

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


if __name__ == "__main__":
    unittest.main()
