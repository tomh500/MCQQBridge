"""Opt-in, in-memory observations. This is neither a login gate nor a game ledger."""
from collections import OrderedDict, deque
import logging
import hmac
import math
import re
import time
import uuid

from aiohttp import web

from .store import BindingError

log = logging.getLogger(__name__)
SNAPSHOTS_PATH = "/v1/server-status/snapshots"
QUERY_PATH = "/v1/server-status/query"
STALE_SECONDS = 30
EXPIRE_SECONDS = 120
SERVER_ID = re.compile(r"[a-z0-9_-]{1,32}\Z")
EVENT_ID = re.compile(r"[A-Za-z0-9._:-]{1,256}\Z")
SNAPSHOT_FIELDS = frozenset(("schema_version", "event_id", "server_id", "observed_at_ms",
                             "availability", "online_players", "max_players", "tps", "mspt_ms"))
QUERY_FIELDS = frozenset(("schema_version", "app_id", "group_openid", "member_openid", "event_id"))


def exact_fields(data, fields):
    if not isinstance(data, dict) or data.keys() != fields or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise ValueError("invalid DTO")


def validate_snapshot(data, servers):
    exact_fields(data, SNAPSHOT_FIELDS)
    if not isinstance(data["event_id"], str) or str(uuid.UUID(data["event_id"])) != data["event_id"]:
        raise ValueError("event_id")
    if not isinstance(data["server_id"], str) or not SERVER_ID.fullmatch(data["server_id"]):
        raise ValueError("server_id")
    if data["server_id"] not in servers:
        raise PermissionError("unknown server")
    observed = data["observed_at_ms"]
    if type(observed) is not int or observed < 0:
        raise ValueError("observed_at_ms")
    if data["availability"] not in ("online", "offline"):
        raise ValueError("availability")
    online, capacity = data["online_players"], data["max_players"]
    if type(online) is not int or type(capacity) is not int or not 0 <= online <= capacity <= 100000 or capacity < 1:
        raise ValueError("players")
    for key, upper in (("tps", 1000), ("mspt_ms", 60000)):
        value = data[key]
        if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= upper):
            raise ValueError(key)
    if data["availability"] == "offline" and (online != 0 or data["tps"] is not None or data["mspt_ms"] is not None):
        raise ValueError("offline metrics")


class Snapshots:
    """Single event-loop writer, bounded by configured servers and 4096 receipts."""
    def __init__(self, servers):
        self.servers = tuple(servers)
        self.latest = {}
        self.seen = OrderedDict()
        self.writes = {}
        self.received_ticks = {}
        self.initial_ages = {}
        self.last_ages = {}
        self.group_queries = OrderedDict()
        self.queries = deque()

    def remember(self, data):
        self.seen[data["event_id"]] = dict(data)
        while len(self.seen) > 4096:
            self.seen.popitem(last=False)

    def receive(self, data, now_ms, tick_ms):
        validate_snapshot(data, self.servers)
        event = data["event_id"]
        if event in self.seen:
            if self.seen[event] != data:
                return 409, "event_conflict"
            return 200, "duplicate"
        if not now_ms - EXPIRE_SECONDS * 1000 <= data["observed_at_ms"] <= now_ms + 5000:
            raise ValueError("observation age")
        server = data["server_id"]
        old = self.latest.get(server)
        if old and data["observed_at_ms"] == old["observed_at_ms"]:
            return 409, "timestamp_conflict"
        if old and data["observed_at_ms"] < old["observed_at_ms"]:
            self.remember(data)
            return 200, "out_of_order"
        if tick_ms - self.writes.get(server, float("-inf")) < 1000:
            return 429, "rate_limited"
        self.latest[server] = dict(data, received_at_ms=now_ms)
        self.writes[server] = tick_ms
        self.received_ticks[server] = tick_ms
        self.initial_ages[server] = max(0, (now_ms - data["observed_at_ms"]) / 1000)
        self.last_ages[server] = self.initial_ages[server]
        self.remember(data)
        return 200, "accepted"

    def query_allowed(self, group, tick_ms):
        while self.queries and self.queries[0] <= tick_ms - 60000:
            self.queries.popleft()
        if len(self.queries) >= 30 or tick_ms - self.group_queries.get(group, float("-inf")) < 5000:
            return False
        self.queries.append(tick_ms)
        self.group_queries[group] = tick_ms
        self.group_queries.move_to_end(group)
        while len(self.group_queries) > 4096:
            self.group_queries.popitem(last=False)
        return True

    def view(self, now_ms, tick_ms):
        result = []
        for server in self.servers:
            snapshot = self.latest.get(server)
            age = max(self.last_ages[server], (now_ms - snapshot["observed_at_ms"]) / 1000,
                      self.initial_ages[server] + (tick_ms - self.received_ticks[server]) / 1000) if snapshot else None
            if snapshot:
                self.last_ages[server] = age
            freshness = ("missing" if snapshot is None else "expired" if age > EXPIRE_SECONDS
                         else "stale" if age > STALE_SECONDS else "fresh")
            result.append(dict(server_id=server, freshness=freshness, age_seconds=age,
                               availability=snapshot["availability"] if freshness == "fresh" else "unknown",
                               snapshot=dict(snapshot) if freshness in ("fresh", "stale") else None))
        return result


async def authorized_request(request, cfg, handler):
    """Uniform errors for only the new routes, including pre-handler failures."""
    request_id = str(uuid.uuid4())
    request["status_request_id"] = request_id
    action = "snapshot" if request.path == SNAPSHOTS_PATH else "query"
    code = "ok"
    try:
        key = "status_reporter_token" if action == "snapshot" else "bot_token"
        token = cfg.get(key, "")
        supplied = request.headers.get("Authorization", "").encode("utf-8")
        expected = ("Bearer " + token).encode("utf-8")
        if not token or not hmac.compare_digest(supplied, expected):
            raise web.HTTPUnauthorized()
        response = await handler(request)
        code = request.get("status_result", str(response.status))
    except (web.HTTPException, BindingError) as exc:
        status = exc.status if isinstance(exc, web.HTTPException) else 409
        code = {401: "unauthorized", 403: "forbidden", 409: "group_not_allowed",
                405: "method_not_allowed", 413: "body_too_large"}.get(status, "invalid_request")
        headers = {"Allow": exc.headers["Allow"]} if isinstance(exc, web.HTTPException) and "Allow" in exc.headers else None
        response = web.json_response(dict(schema_version=1, request_id=request_id, code=code,
                                          error="状态请求无效。"), status=status, headers=headers)
    response.headers["X-Request-ID"] = request_id
    response.headers["Cache-Control"] = "no-store"
    log.info("server_status request_id=%s action=%s result=%s", request_id, action, code)
    return response


def register(app, cfg, identity, *, clock=None, monotonic=None):
    options = cfg.get("server_status", {})
    if not isinstance(options, dict) or type(options.get("enabled", False)) is not bool:
        raise ValueError("invalid server_status configuration")
    enabled = options.get("enabled", False)
    servers = options.get("servers", ["lobby", "survival"])
    if enabled:
        if (not isinstance(servers, list) or not 1 <= len(servers) <= 32
                or any(not isinstance(s, str) or not SERVER_ID.fullmatch(s) for s in servers)
                or len(set(servers)) != len(servers)):
            raise ValueError("invalid status server allowlist")
        token = cfg.get("status_reporter_token", "")
        if (not isinstance(token, str) or not 32 <= len(token) <= 512
                or any(ord(c) < 33 or ord(c) > 126 for c in token)
                or token in (cfg.get("bot_token"), cfg.get("proxy_token"))):
            raise ValueError("status reporter requires a separate service token")
    repository = Snapshots(servers if enabled else [])
    monotonic = monotonic or (clock if clock is not None else time.monotonic)
    clock = clock or time.time

    async def handle(request):
        request_id = request["status_request_id"]
        action = "snapshot" if request.path == SNAPSHOTS_PATH else "query"

        def respond(status, code, payload=None):
            body = dict(schema_version=1, request_id=request_id, **(payload or {}))
            if status != 200:
                body.update(code=code, error="状态请求暂不可用。" if status in (429, 503) else "状态请求无效。")
            headers = {"X-Request-ID": request_id, "Cache-Control": "no-store"}
            if status == 429:
                headers["Retry-After"] = "60" if action == "query" else "1"
            request["status_result"] = code
            return web.json_response(body, status=status, headers=headers)

        if not enabled:
            return respond(503, "disabled")
        now_ms = int(clock() * 1000)
        tick_ms = int(monotonic() * 1000)
        try:
            data = await request.json()
            if action == "snapshot":
                status, reason = repository.receive(data, now_ms, tick_ms)
                return respond(status, reason, dict(event_id=data["event_id"], accepted=reason == "accepted", reason=reason))
            exact_fields(data, QUERY_FIELDS)
            for key in ("app_id", "group_openid", "member_openid"):
                value = data[key]
                if not isinstance(value, str) or not 1 <= len(value) <= 128 or any(ord(c) < 32 or ord(c) == 127 for c in value):
                    raise ValueError("identity")
            if not isinstance(data["event_id"], str) or not EVENT_ID.fullmatch(data["event_id"]):
                raise ValueError("event_id")
            identity(data)
            if not repository.query_allowed(data["group_openid"], tick_ms):
                return respond(429, "rate_limited")
            return respond(200, "ok", dict(generated_at_ms=now_ms, stale_after_seconds=STALE_SECONDS,
                                           expire_after_seconds=EXPIRE_SECONDS, servers=repository.view(now_ms, tick_ms)))
        except PermissionError:
            return respond(403, "unknown_server")
        except (ValueError, KeyError, TypeError, OverflowError):
            return respond(400, "invalid_request")

    app.router.add_post(SNAPSHOTS_PATH, handle)
    app.router.add_post(QUERY_PATH, handle)
