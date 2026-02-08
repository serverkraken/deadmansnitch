from unittest.mock import MagicMock, patch

from app.notifications.notifier import Notifier
from app.notifications.providers.base_provider import NotificationProvider
from app.notifications.providers.google_chat import GoogleChatProvider


class MockProvider(NotificationProvider):
    def __init__(self, name: str = "MockProvider"):
        self._name = name
        self.sent_messages: list[str] = []
        self.should_fail = False

    def name(self) -> str:
        return self._name

    def send(self, message: str) -> bool:
        if self.should_fail:
            raise Exception("Failed to send")
        self.sent_messages.append(message)
        return True


class TestNotifications:
    def test_notifier_add_provider(self) -> None:
        notifier = Notifier()
        provider = MockProvider()
        notifier.add_provider(provider)
        assert provider in notifier.providers

    def test_notify_all_success(self) -> None:
        notifier = Notifier()
        p1 = MockProvider("P1")
        p2 = MockProvider("P2")
        notifier.add_provider(p1)
        notifier.add_provider(p2)

        notifier.notify_all("Hello Test")

        assert "Hello Test" in p1.sent_messages
        assert "Hello Test" in p2.sent_messages

    def test_notify_all_with_failure(self) -> None:
        notifier = Notifier()
        p1 = MockProvider("P1")
        p2 = MockProvider("P2")
        p2.should_fail = True
        notifier.add_provider(p1)
        notifier.add_provider(p2)

        # Should not raise exception, but log it
        notifier.notify_all("Hello Test")

        assert "Hello Test" in p1.sent_messages
        assert len(p2.sent_messages) == 0

    def test_send_alert(self) -> None:
        notifier = Notifier()
        p1 = MockProvider()
        notifier.add_provider(p1)
        notifier.send_alert(60.0, "2026-02-08 20:00:00")
        assert "alert" in p1.sent_messages[0]
        assert "60" in p1.sent_messages[0]
        assert "2026-02-08 20:00:00" in p1.sent_messages[0]

    def test_send_recovery(self) -> None:
        notifier = Notifier()
        p1 = MockProvider()
        notifier.add_provider(p1)
        notifier.send_recovery()
        assert "recovered" in p1.sent_messages[0]

    def test_send_status_update(self) -> None:
        notifier = Notifier()
        p1 = MockProvider()
        notifier.add_provider(p1)
        notifier.send_status_update("2026-02-08 20:00:00")
        assert "status" in p1.sent_messages[0]
        assert "2026-02-08 20:00:00" in p1.sent_messages[0]


class TestGoogleChatProvider:
    @patch("requests.post")
    def test_send_success(self, mock_post: MagicMock) -> None:
        mock_post.return_value.status_code = 200
        provider = GoogleChatProvider("http://webhook.url")
        success = provider.send("Test Message")

        assert success is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["text"] == "Test Message"

    @patch("requests.post")
    def test_send_failure_status(self, mock_post: MagicMock) -> None:
        mock_post.return_value.status_code = 500
        provider = GoogleChatProvider("http://webhook.url")
        success = provider.send("Test Message")
        assert success is False

    @patch("requests.post")
    def test_send_exception(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = Exception("Network error")
        provider = GoogleChatProvider("http://webhook.url")
        success = provider.send("Test Message")
        assert success is False
