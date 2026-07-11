"""通知服务单元测试。

覆盖：
- EmailChannel（mock smtplib）
- WebhookChannel（mock httpx）
- TelegramChannel（mock httpx）
- NotificationService 分发逻辑（mock DB 规则查询）
- build_channel 工厂
- test_channel 测试入口

导入风格参考 conftest.py：顶部注入 backend 根目录到 sys.path。
"""
import sys
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from services.notification_service import (
    NotificationChannel,
    EmailChannel,
    WebhookChannel,
    TelegramChannel,
    NotificationService,
    notification_service,
    build_channel,
    CHANNEL_REGISTRY,
)


# ===========================================================================
# 1. 测试 EmailChannel（mock smtplib）
# ===========================================================================
class TestEmailChannel:
    def test_email_config_parsing(self):
        """字符串收件人列表正确解析为数组"""
        ch = EmailChannel({
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_user": "u@x.com",
            "smtp_password": "pw",
            "to_emails": "a@x.com, b@y.com,",
        })
        assert ch.smtp_host == "smtp.example.com"
        assert ch.smtp_port == 465
        assert ch.to_emails == ["a@x.com", "b@y.com"]
        assert ch.from_email == "u@x.com"  # 默认同 smtp_user

    def test_email_config_list_recipients(self):
        """列表收件人原样保留"""
        ch = EmailChannel({
            "smtp_host": "smtp.example.com",
            "to_emails": ["a@x.com", "b@y.com"],
        })
        assert ch.to_emails == ["a@x.com", "b@y.com"]

    @pytest.mark.asyncio
    async def test_send_success_ssl(self):
        """465 端口走 SMTP_SSL 路径，验证 login + sendmail 被调用"""
        ch = EmailChannel({
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_user": "u@x.com",
            "smtp_password": "pw",
            "to_emails": ["dest@x.com"],
        })
        with patch("services.notification_service.smtplib.SMTP_SSL") as mock_ssl:
            instance = MagicMock()
            mock_ssl.return_value.__enter__.return_value = instance
            ok = await ch.send("标题", "正文", {"k": "v"})
        assert ok is True
        mock_ssl.assert_called_once_with("smtp.example.com", 465, timeout=15)
        instance.login.assert_called_once_with("u@x.com", "pw")
        instance.sendmail.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_success_starttls(self):
        """非 465 端口走 SMTP + starttls 路径"""
        ch = EmailChannel({
            "smtp_host": "smtp.example.com",
            "smtp_port": 587,
            "smtp_user": "u@x.com",
            "smtp_password": "pw",
            "to_emails": ["dest@x.com"],
        })
        with patch("services.notification_service.smtplib.SMTP") as mock_smtp:
            instance = MagicMock()
            mock_smtp.return_value.__enter__.return_value = instance
            ok = await ch.send("标题", "正文", {})
        assert ok is True
        mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=15)
        instance.starttls.assert_called_once()
        instance.login.assert_called_once_with("u@x.com", "pw")

    @pytest.mark.asyncio
    async def test_send_missing_config_returns_false(self):
        """缺少 smtp_host 或 to_emails 时返回 False"""
        ch = EmailChannel({"smtp_host": "", "to_emails": []})
        ok = await ch.send("标题", "正文", {})
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_smtp_exception_returns_false(self):
        """SMTP 抛异常时返回 False 而非向上抛"""
        ch = EmailChannel({
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "to_emails": ["dest@x.com"],
        })
        with patch("services.notification_service.smtplib.SMTP_SSL", side_effect=Exception("conn refused")):
            ok = await ch.send("标题", "正文", {})
        assert ok is False


# ===========================================================================
# 2. 测试 WebhookChannel（mock httpx）
# ===========================================================================
class TestWebhookChannel:
    @pytest.mark.asyncio
    async def test_send_success(self):
        """2xx 响应返回 True"""
        ch = WebhookChannel({"webhook_url": "https://hook.example.com/x"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("services.notification_service.httpx.AsyncClient") as mock_client_cls:
            client = AsyncMock()
            client.post.return_value = mock_resp
            client.__aenter__.return_value = client
            client.__aexit__.return_value = None
            mock_client_cls.return_value = client
            ok = await ch.send("标题", "正文", {"k": "v"})
        assert ok is True
        client.post.assert_called_once()
        # 验证 payload 含必要字段
        call_kwargs = client.post.call_args
        payload = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert payload["title"] == "标题"
        assert payload["message"] == "正文"
        assert payload["details"] == {"k": "v"}
        assert "timestamp" in payload

    @pytest.mark.asyncio
    async def test_send_failure_status(self):
        """非 2xx 响应返回 False"""
        ch = WebhookChannel({"webhook_url": "https://hook.example.com/x"})
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        with patch("services.notification_service.httpx.AsyncClient") as mock_client_cls:
            client = AsyncMock()
            client.post.return_value = mock_resp
            client.__aenter__.return_value = client
            client.__aexit__.return_value = None
            mock_client_cls.return_value = client
            ok = await ch.send("标题", "正文", {})
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_missing_url_returns_false(self):
        ch = WebhookChannel({"webhook_url": ""})
        ok = await ch.send("标题", "正文", {})
        assert ok is False

    @pytest.mark.asyncio
    async def test_secret_signature_header(self):
        """设置 secret 时应附带 X-Signature 头"""
        ch = WebhookChannel({"webhook_url": "https://hook.example.com/x", "secret": "topsecret"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("services.notification_service.httpx.AsyncClient") as mock_client_cls:
            client = AsyncMock()
            client.post.return_value = mock_resp
            client.__aenter__.return_value = client
            client.__aexit__.return_value = None
            mock_client_cls.return_value = client
            ok = await ch.send("标题", "正文", {})
        assert ok is True
        headers = client.post.call_args.kwargs.get("headers") or {}
        assert "X-Signature" in headers
        assert len(headers["X-Signature"]) == 64  # SHA-256 hex

    @pytest.mark.asyncio
    async def test_no_secret_no_signature(self):
        """未设置 secret 时无 X-Signature 头"""
        ch = WebhookChannel({"webhook_url": "https://hook.example.com/x"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        with patch("services.notification_service.httpx.AsyncClient") as mock_client_cls:
            client = AsyncMock()
            client.post.return_value = mock_resp
            client.__aenter__.return_value = client
            client.__aexit__.return_value = None
            mock_client_cls.return_value = client
            await ch.send("标题", "正文", {})
        headers = client.post.call_args.kwargs.get("headers") or {}
        assert "X-Signature" not in headers


# ===========================================================================
# 3. 测试 TelegramChannel（mock httpx）
# ===========================================================================
class TestTelegramChannel:
    @pytest.mark.asyncio
    async def test_send_success(self):
        """200 + ok=True 返回 True"""
        ch = TelegramChannel({"bot_token": "123:ABC", "chat_id": "-100123"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        with patch("services.notification_service.httpx.AsyncClient") as mock_client_cls:
            client = AsyncMock()
            client.post.return_value = mock_resp
            client.__aenter__.return_value = client
            client.__aexit__.return_value = None
            mock_client_cls.return_value = client
            ok = await ch.send("标题", "正文", {"k": "v"})
        assert ok is True
        # 验证 URL 包含 token
        url = client.post.call_args.args[0] if client.post.call_args.args else client.post.call_args[0]
        assert "123:ABC" in url
        # 验证 payload
        payload = client.post.call_args.kwargs.get("json") or {}
        assert payload["chat_id"] == "-100123"
        assert "标题" in payload["text"]
        assert "正文" in payload["text"]

    @pytest.mark.asyncio
    async def test_send_api_error_returns_false(self):
        """200 但 ok=False 返回 False"""
        ch = TelegramChannel({"bot_token": "123:ABC", "chat_id": "-100123"})
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": False, "description": "chat not found"}
        with patch("services.notification_service.httpx.AsyncClient") as mock_client_cls:
            client = AsyncMock()
            client.post.return_value = mock_resp
            client.__aenter__.return_value = client
            client.__aexit__.return_value = None
            mock_client_cls.return_value = client
            ok = await ch.send("标题", "正文", {})
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_non_200_returns_false(self):
        ch = TelegramChannel({"bot_token": "123:ABC", "chat_id": "-100123"})
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = "unauthorized"
        with patch("services.notification_service.httpx.AsyncClient") as mock_client_cls:
            client = AsyncMock()
            client.post.return_value = mock_resp
            client.__aenter__.return_value = client
            client.__aexit__.return_value = None
            mock_client_cls.return_value = client
            ok = await ch.send("标题", "正文", {})
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_missing_config_returns_false(self):
        ch = TelegramChannel({"bot_token": "", "chat_id": ""})
        ok = await ch.send("标题", "正文", {})
        assert ok is False


# ===========================================================================
# 4. 测试 build_channel 工厂
# ===========================================================================
class TestBuildChannel:
    def test_build_email(self):
        ch = build_channel("email", {"smtp_host": "smtp.x.com", "to_emails": ["a@b.com"]})
        assert isinstance(ch, EmailChannel)

    def test_build_webhook(self):
        ch = build_channel("webhook", {"webhook_url": "https://x.com"})
        assert isinstance(ch, WebhookChannel)

    def test_build_telegram(self):
        ch = build_channel("telegram", {"bot_token": "t", "chat_id": "c"})
        assert isinstance(ch, TelegramChannel)

    def test_build_unknown_returns_none(self):
        assert build_channel("unknown", {}) is None

    def test_build_with_empty_config(self):
        """空配置不抛异常，返回实例（字段有默认值）"""
        ch = build_channel("email", {})
        assert isinstance(ch, EmailChannel)

    def test_registry_keys(self):
        assert set(CHANNEL_REGISTRY.keys()) == {"email", "webhook", "telegram"}


# ===========================================================================
# 5. 测试 NotificationService 分发逻辑
# ===========================================================================
def _make_rule(event_types, channel_type, channel_config=None):
    """构造 _load_rules_for_event 返回的规则 dict。

    注意：_load_rules_for_event 返回的是 list[dict]，不是 ORM 对象，
    因此这里构造 dict 而非 MagicMock。
    """
    return {
        "channel_type": channel_type,
        "channel_config": channel_config or {},
        "_event_types": event_types,  # 仅用于测试断言参考
    }


class TestNotificationService:
    @pytest.mark.asyncio
    async def test_notify_matches_event_type(self):
        """事件类型匹配的规则触发渠道发送"""
        svc = NotificationService()
        rules = [_make_rule(["order_failed", "error"], "webhook", {"webhook_url": "https://x.com"})]

        with patch.object(svc, "_load_rules_for_event", return_value=rules), \
             patch.object(WebhookChannel, "send", new_callable=AsyncMock, return_value=True) as mock_send:
            count = await svc.notify("order_failed", "标题", "正文", {"k": "v"})

        assert count == 1
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notify_no_match_returns_zero(self):
        """无匹配规则返回 0，不调用任何 send"""
        svc = NotificationService()
        with patch.object(svc, "_load_rules_for_event", return_value=[]):
            count = await svc.notify("unrelated_event", "标题", "正文", {})
        assert count == 0

    @pytest.mark.asyncio
    async def test_notify_wildcard_matches_all(self):
        """event_types 含 '*' 通配符匹配所有事件"""
        svc = NotificationService()
        rules = [_make_rule(["*"], "telegram", {"bot_token": "t", "chat_id": "c"})]
        with patch.object(svc, "_load_rules_for_event", return_value=rules), \
             patch.object(TelegramChannel, "send", new_callable=AsyncMock, return_value=True) as mock_send:
            count = await svc.notify("any_event_type", "标题", "正文", {})
        assert count == 1
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notify_multiple_rules_parallel(self):
        """多条规则并发分发，返回成功数"""
        svc = NotificationService()
        rules = [
            _make_rule(["error"], "email", {"smtp_host": "s", "to_emails": ["a@b.com"]}),
            _make_rule(["error"], "webhook", {"webhook_url": "https://x.com"}),
            _make_rule(["error"], "telegram", {"bot_token": "t", "chat_id": "c"}),
        ]
        with patch.object(svc, "_load_rules_for_event", return_value=rules), \
             patch.object(EmailChannel, "send", new_callable=AsyncMock, return_value=True), \
             patch.object(WebhookChannel, "send", new_callable=AsyncMock, return_value=False), \
             patch.object(TelegramChannel, "send", new_callable=AsyncMock, return_value=True):
            count = await svc.notify("error", "标题", "正文", {})
        # 2 成功 1 失败
        assert count == 2

    @pytest.mark.asyncio
    async def test_notify_exception_in_send_does_not_propagate(self):
        """单渠道 send 抛异常时被 _safe_send 捕获，不影响其他渠道"""
        svc = NotificationService()
        rules = [
            _make_rule(["error"], "email", {"smtp_host": "s", "to_emails": ["a@b.com"]}),
            _make_rule(["error"], "webhook", {"webhook_url": "https://x.com"}),
        ]
        with patch.object(svc, "_load_rules_for_event", return_value=rules), \
             patch.object(EmailChannel, "send", new_callable=AsyncMock, side_effect=Exception("boom")), \
             patch.object(WebhookChannel, "send", new_callable=AsyncMock, return_value=True):
            count = await svc.notify("error", "标题", "正文", {})
        # email 抛异常（视为失败），webhook 成功
        assert count == 1

    @pytest.mark.asyncio
    async def test_notify_load_rules_exception_returns_zero(self):
        """_load_rules_for_event 抛异常时返回 0 不向上抛"""
        svc = NotificationService()
        with patch.object(svc, "_load_rules_for_event", side_effect=Exception("db down")):
            count = await svc.notify("error", "标题", "正文", {})
        assert count == 0

    @pytest.mark.asyncio
    async def test_notify_unknown_channel_type_skipped(self):
        """规则中 channel_type 不在注册表中时跳过该规则"""
        svc = NotificationService()
        rules = [
            _make_rule(["error"], "unknown_channel", {}),
            _make_rule(["error"], "webhook", {"webhook_url": "https://x.com"}),
        ]
        with patch.object(svc, "_load_rules_for_event", return_value=rules), \
             patch.object(WebhookChannel, "send", new_callable=AsyncMock, return_value=True):
            count = await svc.notify("error", "标题", "正文", {})
        assert count == 1

    @pytest.mark.asyncio
    async def test_test_channel_with_config(self):
        """test_channel 传入 channel_config 时构建新渠道并测试"""
        svc = NotificationService()
        with patch.object(WebhookChannel, "send", new_callable=AsyncMock, return_value=True) as mock_send:
            ok = await svc.test_channel("webhook", {"webhook_url": "https://x.com"})
        assert ok is True
        mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_test_channel_unknown_type_returns_false(self):
        svc = NotificationService()
        ok = await svc.test_channel("unknown", {})
        assert ok is False

    def test_singleton_identity(self):
        """NotificationService 是单例"""
        a = NotificationService()
        b = NotificationService()
        assert a is b
        assert a is notification_service

    def test_init_channels_loads_defaults(self):
        """init_channels 加载系统级默认渠道"""
        svc = NotificationService()
        svc.init_channels({
            "webhook": {"webhook_url": "https://default.example.com"},
        })
        assert "webhook" in svc._default_channels
        # 清理避免污染其他测试
        svc.init_channels({})


# ===========================================================================
# 6. 测试 NotificationChannel 抽象基类
# ===========================================================================
class TestNotificationChannelABC:
    def test_cannot_instantiate_abstract(self):
        """抽象基类不能直接实例化"""
        with pytest.raises(TypeError):
            NotificationChannel()  # type: ignore[abstract]

    def test_subclass_must_implement_send(self):
        """未实现 send 的子类无法实例化"""
        class IncompleteChannel(NotificationChannel):
            channel_type = "incomplete"
        with pytest.raises(TypeError):
            IncompleteChannel()  # type: ignore[abstract]
