"""Anonymous chat readers: Twitch IRC and Kick's negotiated realtime transport.

Both keep a desired channel set (``set_targets``) and join/part to match it, reconnecting
forever with exponential backoff. Every chat line is handed to ``on_message(key, text, t)``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import re
import time
import uuid
from abc import ABC, abstractmethod
from typing import Awaitable, Callable
from urllib.parse import urlsplit

import httpx

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import WebSocketException

from .config import Settings
from .models import Platform, StreamTarget
from .util import Backoff

logger = logging.getLogger("clipbot.chat")

# Protocol constants
TWITCH_IRC_URL = "wss://irc-ws.chat.twitch.tv:443"
TWITCH_ANON_PASS = "SCHMOOPIIE"
# Twitch only accepts anonymous (read-only) logins as justinfan<digits>; any other nick is
# refused with "Improperly formatted auth" and dropped ~10 s later. Protocol, not a setting.
TWITCH_ANON_NICK = "justinfan"
TWITCH_NICK_DIGITS = (10000, 99999)
# Public browser protocol endpoints, not owner account credentials. Kick now
# negotiates its transport instead of publishing a permanent Pusher application key.
KICK_REALTIME_URL = "https://web.kick.com/api/v1/realtime/connection"
KICK_REALTIME_AUTH_URL = "https://web.kick.com/api/v1/realtime/auth/connection"
KICK_ORIGIN = "https://kick.com"
TLS_PORT = 443
KICK_CHAT_EVENT = "App\\Events\\ChatMessageEvent"

OnMessage = Callable[[str, str, float], None]
ChatroomLookup = Callable[[str], Awaitable[dict | None]]


_PRIVMSG_RE = re.compile(r"^(?:@\S+ )?:\S+ PRIVMSG #(?P<chan>\S+) :?(?P<text>.*)$")
_ACTION_RE = re.compile(r"^\x01ACTION (?P<text>.*)\x01$")


def parse_privmsg(line: str) -> tuple[str, str] | None:
    """Return (channel, text) for an IRC PRIVMSG line (tags tolerated), else None."""
    m = _PRIVMSG_RE.match(line)
    if not m:
        return None
    text = m["text"]
    action = _ACTION_RE.match(text)
    return m["chan"].lower(), action["text"] if action else text


def irc_command(line: str) -> str:
    if line.startswith("@"):
        _, _, line = line.partition(" ")
    parts = line.split(" ", 2)
    if line.startswith(":"):
        return parts[1] if len(parts) > 1 else ""
    return parts[0]


def parse_kick_event(raw: str) -> tuple[str, str | None, dict | str | None]:
    """Return (event, channel, data) for a Pusher frame; data JSON-decoded when possible."""
    msg = json.loads(raw)
    data = msg.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            pass
    return msg.get("event", ""), msg.get("channel"), data


class _Client(ABC):
    name = "chat"

    def __init__(self, settings: Settings, on_message: OnMessage) -> None:
        self.settings = settings
        self.on_message = on_message
        self.desired: dict[str, str] = {}     # channel id → target key
        self.joined: set[str] = set()
        self.connected = False
        self.last_error = ""
        self.messages = 0
        self._ws: ClientConnection | None = None
        self._sync = asyncio.Event()
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"chat:{self.name}")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.connected = False

    def set_channels(self, desired: dict[str, str]) -> None:
        self.desired = desired
        self._sync.set()
        if desired:
            self.start()

    def snapshot(self) -> dict:
        return {"connected": self.connected, "joined": len(self.joined),
                "wanted": len(self.desired), "messages": self.messages, "error": self.last_error}

    async def _run(self) -> None:
        c = self.settings.chat
        backoff = Backoff(c.reconnect_min_s, c.reconnect_max_s)
        while True:
            if not self.desired:
                self._sync.clear()
                await self._sync.wait()
                continue
            connected_at = None
            try:
                await self.prepare()
                async with connect(self.url(), ping_interval=c.ping_interval_s,
                                   ping_timeout=c.ping_interval_s, max_size=c.frame_max_bytes,
                                   open_timeout=c.handshake_timeout_s, **self.connection_options()) as ws:
                    self._ws = ws
                    self.joined = set()
                    await asyncio.wait_for(self.handshake(ws), c.handshake_timeout_s)
                    self.connected = True
                    connected_at = time.monotonic()
                    self.last_error = ""
                    self._sync.set()
                    syncer = asyncio.create_task(self._sync_loop(ws))
                    maintenance = asyncio.create_task(self.maintain(ws))
                    try:
                        async for raw in ws:
                            await self.handle(ws, raw if isinstance(raw, str)
                                              else raw.decode("utf-8", "replace"))
                    finally:
                        syncer.cancel()
                        maintenance.cancel()
                        await asyncio.gather(syncer, maintenance, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except (OSError, WebSocketException, httpx.HTTPError, asyncio.TimeoutError, ValueError) as exc:
                self.last_error = str(exc) or type(exc).__name__
                logger.warning("%s chat disconnected: %s", self.name, self.last_error)
            finally:
                if connected_at is not None and time.monotonic() - connected_at >= c.stable_connection_s:
                    backoff.reset()
                self._ws = None
                self.connected = False
                self.joined = set()
            delay = backoff.next()
            logger.info("%s chat reconnecting in %.0fs", self.name, delay)
            await asyncio.sleep(delay)

    async def _sync_loop(self, ws: ClientConnection) -> None:
        while True:
            await self._sync.wait()
            self._sync.clear()
            for ch in [c for c in self.joined if c not in self.desired]:
                await self.part(ws, ch)
                self.joined.discard(ch)
            for ch in [c for c in self.desired if c not in self.joined and not self.join_pending(c)]:
                if ch not in self.desired:
                    continue
                await self.join(ws, ch)
                if not self.confirmed_subscriptions:
                    self.joined.add(ch)
                await asyncio.sleep(self.settings.chat.join_spacing_s)

    def deliver(self, channel: str, text: str) -> None:
        key = self.desired.get(channel)
        if key is None:
            return
        self.messages += 1
        self.on_message(key, text, time.time())

    # platform hooks
    confirmed_subscriptions = False

    def connection_options(self) -> dict:
        return {}

    def join_pending(self, channel: str) -> bool:
        return False

    async def prepare(self) -> None:
        return None

    async def maintain(self, ws: ClientConnection) -> None:
        return None

    @abstractmethod
    def url(self) -> str: ...

    @abstractmethod
    async def handshake(self, ws: ClientConnection) -> None: ...

    @abstractmethod
    async def handle(self, ws: ClientConnection, raw: str) -> None: ...

    @abstractmethod
    async def join(self, ws: ClientConnection, channel: str) -> None: ...

    @abstractmethod
    async def part(self, ws: ClientConnection, channel: str) -> None: ...


class TwitchChat(_Client):
    name = "twitch"

    def url(self) -> str:
        return TWITCH_IRC_URL

    async def handshake(self, ws: ClientConnection) -> None:
        nick = f"{TWITCH_ANON_NICK}{random.randint(*TWITCH_NICK_DIGITS)}"
        await ws.send(f"PASS {TWITCH_ANON_PASS}")
        await ws.send(f"NICK {nick}")

    async def handle(self, ws: ClientConnection, raw: str) -> None:
        for line in raw.split("\r\n"):
            if not line:
                continue
            if line.startswith("PING"):
                await ws.send("PONG" + line[len("PING"):])
                continue
            if " NOTICE * :" in line and "auth" in line.lower():   # login refused (not a channel notice)
                raise ConnectionRefusedError(f"twitch refused the anonymous login: {line}")
            if irc_command(line) == "RECONNECT":
                raise ConnectionResetError("server requested RECONNECT")
            parsed = parse_privmsg(line)
            if parsed:
                self.deliver(*parsed)

    async def join(self, ws: ClientConnection, channel: str) -> None:
        await ws.send(f"JOIN #{channel}")

    async def part(self, ws: ClientConnection, channel: str) -> None:
        await ws.send(f"PART #{channel}")


class KickChat(_Client):
    name = "kick"
    confirmed_subscriptions = True

    def __init__(self, settings: Settings, on_message: OnMessage) -> None:
        super().__init__(settings, on_message)
        self.transport = "not_checked"
        self._endpoint = ""
        self._identity = str(uuid.uuid4())
        self._grant = ""
        self._command_id = 0
        self._pending: dict[int, tuple[str, str]] = {}
        self._joining: set[str] = set()
        self.channel_errors: dict[str, str] = {}
        self._refresh_at: float | None = None

    def snapshot(self) -> dict:
        return {**super().snapshot(), "transport": self.transport,
                "channel_errors": dict(self.channel_errors)}

    def connection_options(self) -> dict:
        return {"origin": KICK_ORIGIN, "proxy": None}

    def join_pending(self, channel: str) -> bool:
        return channel in self._joining

    async def _public_connection_request(self, url: str, payload: dict) -> dict:
        c = self.settings.chat
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                     timeout=c.handshake_timeout_s) as client:
            async with client.stream("POST", url, json=payload,
                                     headers={"Origin": KICK_ORIGIN, "Referer": KICK_ORIGIN + "/"}) as response:
                if response.status_code != 200:
                    raise ValueError(f"Kick chat connection service returned HTTP {response.status_code}")
                raw = bytearray()
                async for part in response.aiter_bytes():
                    raw.extend(part)
                    if len(raw) > c.request_max_bytes:
                        raise ValueError("Kick chat connection response exceeds its configured size limit")
        body = json.loads(raw)
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise ValueError("Kick chat connection service returned an invalid descriptor")
        return data

    async def _connection_grant(self) -> str:
        data = await self._public_connection_request(KICK_REALTIME_AUTH_URL, {"client_id": self._identity})
        token = data.get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("Kick anonymous connection grant is unavailable")
        return token

    async def prepare(self) -> None:
        self._grant = ""
        self._pending.clear()
        self._joining.clear()
        self.channel_errors.clear()
        self._refresh_at = None
        self._command_id = 0
        descriptor = await self._public_connection_request(KICK_REALTIME_URL, {
            "client": {"id": self._identity, "type": "web"},
            "capabilities": {"accepted_providers": [{"provider": "centrifugo"}, {"provider": "pusher"}]},
        })
        connections = descriptor.get("connections")
        if descriptor.get("mode") != "websocket" or not isinstance(connections, list):
            raise ValueError("Kick is not currently offering a websocket chat transport")
        for provider in ("centrifugo", "pusher"):
            for connection in connections:
                if not isinstance(connection, dict) or connection.get("provider") != provider:
                    continue
                credentials = connection.get("credentials")
                if not isinstance(credentials, dict):
                    continue
                if provider == "centrifugo":
                    endpoint = credentials.get("url")
                    if not isinstance(endpoint, str):
                        continue
                    parts = urlsplit(endpoint)
                    if (parts.scheme != "wss" or not re.fullmatch(r"realtime\.[a-z0-9-]+\.platform\.kick\.com", parts.hostname or "")
                            or parts.port not in (None, TLS_PORT) or parts.username or parts.password
                            or parts.path != "/connection/websocket" or parts.query or parts.fragment):
                        raise ValueError("Kick returned an untrusted realtime endpoint")
                    self._grant = await self._connection_grant()
                else:
                    key, cluster = credentials.get("app_key"), credentials.get("cluster")
                    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9]+", key):
                        continue
                    if not isinstance(cluster, str) or not re.fullmatch(r"[a-z0-9]+", cluster):
                        continue
                    endpoint = f"wss://ws-{cluster}.pusher.com/app/{key}?protocol=7&client=ashvane&version=1.0"
                self.transport, self._endpoint = provider, endpoint
                return
        raise ValueError("Kick did not offer a supported chat transport")

    def url(self) -> str:
        if not self._endpoint:
            raise ValueError("Kick transport has not been discovered")
        return self._endpoint

    def _refresh_deadline(self, reply: dict) -> None:
        ttl = reply.get("ttl")
        self._refresh_at = (time.monotonic() + max(1, ttl - self.settings.chat.handshake_timeout_s)
                            if reply.get("expires") is True and type(ttl) in (int, float) and math.isfinite(ttl) and ttl > 0 else None)

    async def _command(self, ws: ClientConnection, name: str, data: dict, channel: str = "") -> int:
        self._command_id += 1
        ident = self._command_id
        self._pending[ident] = name, channel
        await ws.send(json.dumps({"id": ident, name: data}))
        return ident

    async def handshake(self, ws: ClientConnection) -> None:
        if self.transport == "centrifugo":
            ident = await self._command(ws, "connect", {"name": "ashvane", "token": self._grant})
            self._grant = ""  # Short-lived anonymous grant is never logged or persisted.
            while True:
                raw = await ws.recv()
                for line in (raw.decode() if isinstance(raw, bytes) else raw).splitlines():
                    reply = json.loads(line)
                    if isinstance(reply, dict) and reply.get("id") == ident:
                        self._pending.pop(ident, None)
                        if "error" in reply or not isinstance(reply.get("connect"), dict):
                            raise ValueError("Kick rejected the anonymous chat handshake")
                        self._refresh_deadline(reply["connect"])
                        return
        else:
            event, _channel, data = parse_kick_event(await ws.recv())
            if event != "pusher:connection_established":
                code = data.get("code") if isinstance(data, dict) else "unknown"
                raise ValueError(f"Kick Pusher handshake rejected ({code}); transport will be rediscovered")

    async def maintain(self, ws: ClientConnection) -> None:
        try:
            while self.transport == "centrifugo":
                if self._refresh_at is None:
                    await asyncio.Future()
                await asyncio.sleep(max(1, self._refresh_at - time.monotonic()))
                if any(name == "refresh" for name, _channel in self._pending.values()):
                    raise ValueError("Kick did not acknowledge its session refresh")
                token = await self._connection_grant()
                self._refresh_at = time.monotonic() + self.settings.chat.ping_interval_s
                await self._command(ws, "refresh", {"token": token})
        except (ValueError, OSError, httpx.HTTPError, WebSocketException) as exc:
            self.last_error = f"Kick chat session refresh failed: {type(exc).__name__}"
            logger.warning("%s", self.last_error)
            await ws.close()

    async def _centrifugo_frame(self, ws: ClientConnection, reply: dict) -> None:
        if not reply:
            await ws.send("{}")
            return
        if "id" in reply:
            if type(reply["id"]) is not int:
                return
            command = self._pending.pop(reply["id"], None)
            if command is None:
                return
            name, channel = command
            if "error" in reply:
                self.channel_errors[channel or name] = "Provider rejected the subscription or session command"
                self.last_error = self.channel_errors[channel or name]
                if name == "refresh":
                    await ws.close()
            elif name == "subscribe" and isinstance(reply.get("subscribe"), dict):
                self._joining.discard(channel)
                self.joined.add(channel)
                self._sync.set()
            elif name == "refresh" and isinstance(reply.get("refresh"), dict):
                self._refresh_deadline(reply["refresh"])
            return
        push = reply.get("push")
        if not isinstance(push, dict):
            return
        channel = push.get("channel")
        publication = push.get("pub")
        if isinstance(channel, str) and isinstance(publication, dict):
            envelope = publication.get("data")
            if not isinstance(envelope, dict) or envelope.get("event") != KICK_CHAT_EVENT:
                return
            data = envelope.get("data")
            if isinstance(data, str):
                data = json.loads(data)
            if isinstance(data, dict) and isinstance(data.get("content"), str):
                self.deliver(channel, data["content"])
        if "unsubscribe" in push and isinstance(channel, str):
            self.joined.discard(channel)
            self.channel_errors[channel] = "Provider ended this subscription"
        if "disconnect" in push:
            await ws.close()

    async def handle(self, ws: ClientConnection, raw: str) -> None:
        try:
            if self.transport == "centrifugo":
                for line in raw.splitlines():
                    reply = json.loads(line)
                    if isinstance(reply, dict):
                        await self._centrifugo_frame(ws, reply)
                return
            event, channel, data = parse_kick_event(raw)
        except (json.JSONDecodeError, AttributeError) as exc:
            logger.debug("kick: unparseable frame (%s): %.120s", exc, raw)
            return
        if event == "pusher:ping":
            await ws.send(json.dumps({"event": "pusher:pong", "data": {}}))
        elif event == "pusher:error":
            code = data.get("code") if isinstance(data, dict) else "unknown"
            raise ValueError(f"Kick Pusher rejected the current transport ({code}); rediscovering")
        elif event == "pusher_internal:subscription_succeeded" and channel:
            self._joining.discard(channel)
            self.joined.add(channel)
            self._sync.set()
        elif event == KICK_CHAT_EVENT and channel and isinstance(data, dict):
            content = data.get("content")
            if isinstance(content, str):
                self.deliver(channel, content)

    async def join(self, ws: ClientConnection, channel: str) -> None:
        self._joining.add(channel)
        if self.transport == "centrifugo":
            await self._command(ws, "subscribe", {"channel": channel}, channel)
            return
        await ws.send(json.dumps({"event": "pusher:subscribe",
                                  "data": {"auth": "", "channel": channel}}))

    async def part(self, ws: ClientConnection, channel: str) -> None:
        self._joining.discard(channel)
        if self.transport == "centrifugo":
            await self._command(ws, "unsubscribe", {"channel": channel}, channel)
            return
        await ws.send(json.dumps({"event": "pusher:unsubscribe", "data": {"channel": channel}}))


class ChatHub:
    def __init__(self, settings: Settings, on_message: OnMessage,
                 kick_lookup: ChatroomLookup | None) -> None:
        self.settings = settings
        self.twitch = TwitchChat(settings, on_message)
        self.kick = KickChat(settings, on_message)
        self.kick_lookup = kick_lookup
        self.no_chat: set[str] = set()

    def apply(self, settings: Settings) -> None:
        self.settings = settings
        self.twitch.settings = settings
        self.kick.settings = settings

    async def set_targets(self, targets: list[StreamTarget]) -> None:
        tw = {t.login.lower(): t.key for t in targets if t.platform == Platform.TWITCH}
        kk: dict[str, str] = {}
        self.no_chat = set()
        for t in targets:
            if t.platform != Platform.KICK:
                continue
            if t.chatroom_id is None and self.kick_lookup is not None:
                info = await self.kick_lookup(t.login)
                t.chatroom_id = (info or {}).get("chatroom_id")
            if t.chatroom_id:
                kk[f"chatrooms.{t.chatroom_id}.v2"] = t.key
            else:
                self.no_chat.add(t.key)
        if self.no_chat:
            logger.info("kick chat unavailable for %s (chatroom lookup blocked)",
                        ", ".join(sorted(self.no_chat)))
        self.twitch.set_channels(tw)
        self.kick.set_channels(kk)

    async def stop(self) -> None:
        await asyncio.gather(self.twitch.stop(), self.kick.stop())

    def snapshot(self) -> dict:
        return {"twitch": self.twitch.snapshot(), "kick": self.kick.snapshot(),
                "no_chat": sorted(self.no_chat)}
