"""Negotiated public Kick chat, confirmed subscriptions and bounded reconnect behavior."""
import asyncio
import json
import time
from unittest.mock import AsyncMock

import httpx
import pytest

from clipbot.chat import KICK_CHAT_EVENT, KICK_REALTIME_URL, KickChat
from clipbot.config import Settings

ENDPOINT = "wss://realtime.us-west-2.platform.kick.com/connection/websocket"


class Socket:
    def __init__(self, frames=()):
        self.frames = list(frames)
        self.sent = []
        self.closed = False

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        return json.dumps(self.frames.pop(0))

    async def close(self):
        self.closed = True


def descriptor(endpoint=ENDPOINT):
    return {"mode": "websocket", "connections": [{"provider": "centrifugo", "credentials": {"url": endpoint}}]}


def test_negotiation_handshake_and_confirmed_subscription(monkeypatch):
    async def run():
        received = []
        chat = KickChat(Settings(), lambda *args: received.append(args))
        chat._public_connection_request = AsyncMock(side_effect=[descriptor(), {"token": "ephemeral-grant"}])
        await chat.prepare()
        assert chat.url() == ENDPOINT and chat.transport == "centrifugo"
        socket = Socket([{"id": 1, "connect": {"expires": True, "ttl": 120}}])
        await chat.handshake(socket)
        assert not chat._grant and chat._refresh_at > time.monotonic()
        chat.desired = {"chatrooms.668.v2": "kick:fixture"}
        await chat.join(socket, "chatrooms.668.v2")
        assert not chat.joined and chat.join_pending("chatrooms.668.v2")
        await chat.handle(socket, json.dumps({"id": 2, "subscribe": {}}))
        assert chat.joined == {"chatrooms.668.v2"}
        envelope = {"event": KICK_CHAT_EVENT, "data": json.dumps({"content": "one actual message"})}
        publication = {"push": {"channel": "chatrooms.668.v2", "pub": {"data": envelope}}}
        await chat.handle(socket, "{}\n" + json.dumps(publication))
        assert socket.sent[-1] == {} and received[0][:2] == ("kick:fixture", "one actual message")
        await chat.handle(socket, json.dumps({"push": {"channel": "unknown", "pub": {"data": envelope}}}))
        assert len(received) == 1
        assert chat.snapshot()["joined"] == 1 and chat.snapshot()["messages"] == 1
        assert "ephemeral-grant" not in json.dumps(chat.snapshot())
    asyncio.run(run())


@pytest.mark.parametrize("endpoint", [
    "ws://realtime.us-west-2.platform.kick.com/connection/websocket",
    "wss://127.0.0.1/connection/websocket", "wss://example.com/connection/websocket",
    "wss://realtime.us-west-2.platform.kick.com.evil.test/connection/websocket",
    "wss://user:secret@realtime.us-west-2.platform.kick.com/connection/websocket",
    ENDPOINT + "?token=unexpected", ENDPOINT + "#fragment", ENDPOINT.replace("/connection/", ":8099/connection/"),
])
def test_untrusted_transport_never_receives_anonymous_grant(endpoint):
    async def run():
        chat = KickChat(Settings(), lambda *_args: None)
        chat._public_connection_request = AsyncMock(return_value=descriptor(endpoint))
        with pytest.raises(ValueError, match="untrusted"):
            await chat.prepare()
        assert chat._public_connection_request.await_count == 1
    asyncio.run(run())


def test_subscription_failure_is_not_joined_and_bad_frames_do_not_deliver():
    async def run():
        chat = KickChat(Settings(), lambda *_args: pytest.fail("unrelated frame delivered"))
        chat.transport = "centrifugo"
        socket = Socket()
        await chat.join(socket, "chatrooms.1.v2")
        await chat.handle(socket, json.dumps({"id": 1, "error": {"code": 103}}))
        assert not chat.joined and chat.join_pending("chatrooms.1.v2")
        assert chat.channel_errors
        await chat.handle(socket, '{"id": [], "subscribe": {}}')
        await chat.handle(socket, 'not json')
        await chat.handle(socket, '{"push": {"channel": "chatrooms.1.v2", "pub": {"data": {"event": "unrelated"}}}}')
    asyncio.run(run())


def test_pusher_descriptor_remains_supported_without_retired_key():
    async def run():
        chat = KickChat(Settings(), lambda *_args: None)
        chat._public_connection_request = AsyncMock(return_value={"mode": "websocket", "connections": [
            {"provider": "pusher", "credentials": {"app_key": "freshPublicKey", "cluster": "us2"}}]})
        await chat.prepare()
        assert "freshPublicKey" in chat.url()
        socket = Socket([{"event": "pusher:connection_established", "data": "{}"}])
        await chat.handshake(socket)
        await chat.join(socket, "chatrooms.1.v2")
        assert not chat.joined
        await chat.handle(socket, json.dumps({"event": "pusher_internal:subscription_succeeded", "channel": "chatrooms.1.v2", "data": "{}"}))
        assert chat.joined == {"chatrooms.1.v2"}
        with pytest.raises(ValueError, match="rediscovering"):
            await chat.handle(socket, json.dumps({"event": "pusher:error", "data": {"code": 4001}}))
    asyncio.run(run())


def test_rejected_handshakes_do_not_reset_reconnect_backoff(monkeypatch):
    import clipbot.chat as module

    async def run():
        delays = []
        chat = KickChat(Settings(), lambda *_args: None)
        chat.desired = {"chatrooms.1.v2": "kick:fixture"}
        chat.prepare = AsyncMock()
        chat._endpoint = ENDPOINT
        chat.handshake = AsyncMock(side_effect=ValueError("rejected"))

        class Connect:
            async def __aenter__(self): return Socket()
            async def __aexit__(self, *_args): return None

        async def sleep(delay):
            delays.append(delay)
            if len(delays) == 3:
                raise asyncio.CancelledError()

        monkeypatch.setattr(module, "connect", lambda *_args, **_kwargs: Connect())
        monkeypatch.setattr(module.asyncio, "sleep", sleep)
        with pytest.raises(asyncio.CancelledError):
            await chat._run()
        assert delays == [2, 4, 8]
        assert not chat.connected and not chat.joined
    asyncio.run(run())


def test_connection_response_limits_and_redirects(monkeypatch):
    import clipbot.chat as module
    real_client = httpx.AsyncClient
    settings = Settings()
    settings.chat.request_max_bytes = 1024

    async def run():
        for response, error in [(httpx.Response(200, content=b"x" * 1025), "size limit"),
                                (httpx.Response(302, headers={"Location": "http://127.0.0.1"}), "HTTP 302")]:
            transport = httpx.MockTransport(lambda _request: response)
            monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_kwargs: real_client(transport=transport))
            chat = KickChat(settings, lambda *_args: None)
            with pytest.raises(ValueError, match=error):
                await chat._public_connection_request(KICK_REALTIME_URL, {})
    asyncio.run(run())


def test_short_lived_grants_refresh_and_stop_drains_maintenance(monkeypatch):
    import clipbot.chat as module

    async def run():
        chat = KickChat(Settings(), lambda *_args: None)
        chat.transport = "centrifugo"
        chat._refresh_at = time.monotonic() - 1
        chat._connection_grant = AsyncMock(return_value="fresh-ephemeral-grant")
        socket = Socket()
        real_sleep = asyncio.sleep

        async def sleep(_delay):
            if socket.sent:
                raise asyncio.CancelledError()
            await real_sleep(0)

        monkeypatch.setattr(module.asyncio, "sleep", sleep)
        with pytest.raises(asyncio.CancelledError):
            await chat.maintain(socket)
        assert socket.sent == [{"id": 1, "refresh": {"token": "fresh-ephemeral-grant"}}]
        await chat.handle(socket, '{"id":1,"refresh":{"expires":true,"ttl":120}}')
        assert not chat._pending and chat._refresh_at > time.monotonic()
        assert "fresh-ephemeral-grant" not in json.dumps(chat.snapshot())
    asyncio.run(run())
