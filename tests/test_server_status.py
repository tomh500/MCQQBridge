"""Isolated status contract: mock MC producer -> real API -> mock QQ reply.

All identities, tokens and database contents are synthetic. The test runner permits
loopback sockets only; no QQ client is connected and no Minecraft process starts.
"""
import asyncio
from collections import OrderedDict
import copy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
import uuid

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from mcqq.bot import QQBot
from mcqq.service import create_app


SNAPSHOTS = "/v1/server-status/snapshots"
QUERY = "/v1/server-status/query"


class StatusContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.now = 1800000000.0
        self.cfg = {
            "database": str(Path(self.temp.name) / "synthetic.sqlite"),
            "app_id": "app", "allowed_groups": ["group"] + ["group-" + str(i) for i in range(32)],
            "bot_token": "b" * 40, "proxy_token": "p" * 40,
            "status_reporter_token": "s" * 40,
            "server_status": {"enabled": True, "servers": ["lobby", "survival"]},
        }
        self.resolver = AsyncMock(side_effect=AssertionError("Status must not resolve real game identities"))
        self.clients = []
        self.client = await self.start_client(self.cfg)

    async def asyncTearDown(self):
        for client in reversed(self.clients):
            await client.close()
        self.resolver.assert_not_awaited()
        self.temp.cleanup()

    async def start_client(self, cfg):
        client = TestClient(TestServer(create_app(cfg, resolver=self.resolver, status_clock=lambda: self.now)))
        await client.start_server()
        self.clients.append(client)
        return client

    def snapshot(self, **changes):
        data = {"schema_version": 1, "event_id": str(uuid.uuid4()), "server_id": "survival",
                "observed_at_ms": int(self.now * 1000), "availability": "online",
                "online_players": 3, "max_players": 50, "tps": 19.8, "mspt_ms": 12.5}
        data.update(changes)
        return data

    def query(self, **changes):
        data = {"schema_version": 1, "app_id": "app", "group_openid": "group",
                "member_openid": "member", "event_id": "qq." + uuid.uuid4().hex}
        data.update(changes)
        return data

    async def post(self, path, data, role="bot_token", *, client=None):
        headers = {} if role is None else {"Authorization": "Bearer " + self.cfg.get(role, role)}
        return await (client or self.client).post(path, json=data, headers=headers)

    async def report(self, data=None, **changes):
        return await self.post(SNAPSHOTS, self.snapshot(**changes) if data is None else data,
                               "status_reporter_token")

    async def read(self, **changes):
        response = await self.post(QUERY, self.query(**changes))
        self.assertEqual(response.status, 200, await response.text())
        data = await response.json()
        self.assert_request_id(response, data)
        return data

    def assert_request_id(self, response, data):
        self.assertEqual(str(uuid.UUID(data["request_id"])), data["request_id"])
        self.assertEqual(response.headers["X-Request-ID"], data["request_id"])

    @staticmethod
    def item(data, server="survival"):
        return next(item for item in data["servers"] if item["server_id"] == server)

    def bot(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = dict(self.cfg, service_url=str(self.client.make_url("/")))
        bot.seen = OrderedDict()
        return bot

    @staticmethod
    def message(content="/服务器", **changes):
        fields = {"id": "sdk-" + uuid.uuid4().hex, "content": content, "group_openid": "group",
                  "author": SimpleNamespace(member_openid="member", bot=False), "reply": AsyncMock()}
        fields.update(changes)
        return SimpleNamespace(**fields)

    async def test_mock_mc_to_real_api_to_qq_text_and_duplicate_sdk_event(self):
        # This producer is a mock bridge, not a real Bukkit/Bungee plugin.
        async def mock_bridge():
            return await self.report()

        ack = await mock_bridge()
        self.assertEqual(ack.status, 200)
        data = await ack.json()
        self.assert_request_id(ack, data)
        self.assertEqual((data["schema_version"], data["accepted"], data["reason"]), (1, True, "accepted"))
        bot = self.bot()
        bot.call_service = AsyncMock(wraps=bot.call_service)
        message = self.message("<@!synthetic-bot> /服务器")
        await bot.on_group_message_create(message)
        message.reply.assert_awaited_once()
        text = message.reply.call_args.kwargs["content"]
        for fragment in ("survival", "3/50", "TPS", "ms/tick", "lobby"):
            self.assertIn(fragment, text)
        self.assertNotIn("member", text)
        self.assertNotIn(self.cfg["bot_token"], text)
        bot.call_service.assert_awaited_once()
        self.assertEqual(bot.call_service.call_args.args[0], QUERY)
        self.assertEqual(bot.call_service.call_args.args[1]["member_openid"], "member")
        await bot.on_group_at_message_create(message)
        message.reply.assert_awaited_once()
        bot.call_service.assert_awaited_once()

    async def test_online_status_requires_slash(self):
        for index, command in enumerate(("/在线", "服务器", "在线")):
            with self.subTest(command=command):
                bot = self.bot()
                message = self.message(command, group_openid="group-" + str(index))
                await bot.on_group_message_create(message)
                if command.startswith("/"):
                    message.reply.assert_awaited_once()
                    self.assertIn("未知", message.reply.call_args.kwargs["content"])
                else:
                    message.reply.assert_not_awaited()

    async def test_server_intelligence_includes_host_metrics_and_only_smp_player_count(self):
        self.assertEqual((await self.report()).status, 200)
        self.assertEqual((await self.report(server_id="lobby", online_players=9)).status, 200)
        bot = self.bot()
        message = self.message("/伺服器情报")
        with patch("mcqq.system_info.read_system_info", return_value="【机器状态情报】\n系统：Ubuntu"), \
             patch("mcqq.system_info.read_extra_metrics", return_value="CPU 占用率：25.0%\n硬碟剩余空间：20.0/50.0 GiB"):
            await bot.on_group_message_create(message)
        self.assertEqual(message.reply.await_args.kwargs["content"],
                         "【机器状态情报】\n系统：Ubuntu\nCPU 占用率：25.0%\n"
                         "硬碟剩余空间：20.0/50.0 GiB\nSMP 在线人数：3/50 人")

    async def test_server_intelligence_can_query_local_smp_without_reporter(self):
        async def respond(reader, writer):
            try:
                length = (await reader.readexactly(1))[0]
                await reader.readexactly(length)
                if await reader.readexactly(2) != b"\x01\x00":
                    return
                data = json.dumps({"players": {"online": 7, "max": 80}}).encode()
                writer.write(bytes([len(data) + 2, 0, len(data)]) + data)
                await writer.drain()
            finally:
                writer.close()

        async with await asyncio.start_server(respond, "127.0.0.1", 0) as listener:
            port = listener.sockets[0].getsockname()[1]
            bot = self.bot()
            bot.call_service = AsyncMock()
            message = self.message("/伺服器情报")
            with patch.dict(os.environ, {"MCQQ_SMP_STATUS_PORT": str(port)}):
                await bot.on_group_message_create(message)
            self.assertIn("SMP 在线人数：7/80 人", message.reply.await_args.kwargs["content"])
            bot.call_service.assert_not_awaited()

    async def test_missing_snapshots_and_offline_are_distinct(self):
        missing = self.item(await self.read())
        self.assertEqual((missing["availability"], missing["freshness"], missing["snapshot"]),
                         ("unknown", "missing", None))
        response = await self.report(availability="offline", online_players=0, tps=None, mspt_ms=None)
        self.assertEqual(response.status, 200)
        self.now += 5
        data = await self.read()
        offline = self.item(data)
        self.assertEqual((offline["availability"], offline["freshness"]), ("offline", "fresh"))
        self.assertEqual(offline["snapshot"]["online_players"], 0)
        bot = self.bot()
        message = self.message("/在线", group_openid="group-1")
        await bot.on_group_message_create(message)
        self.assertIn("离线", message.reply.call_args.kwargs["content"])

    async def test_freshness_boundaries_and_expiry_do_not_claim_online(self):
        data = self.snapshot()
        self.assertEqual((await self.report(data)).status, 200)
        initial = self.now
        for index, age, freshness in ((0, 30, "fresh"), (1, 30.001, "stale"),
                                      (2, 120, "stale"), (3, 120.001, "expired")):
            with self.subTest(age=age):
                self.now = initial + age
                result = await self.read(group_openid="group-" + str(index))
                self.assertEqual((result["schema_version"], result["stale_after_seconds"], result["expire_after_seconds"]),
                                 (1, 30, 120))
                item = self.item(result)
                self.assertEqual(item["freshness"], freshness)
                self.assertAlmostEqual(item["age_seconds"], age, places=3)
                self.assertEqual(item["availability"], "online" if freshness == "fresh" else "unknown")
                if freshness == "expired":
                    self.assertIsNone(item["snapshot"])
                else:
                    self.assertEqual(item["snapshot"]["observed_at_ms"], data["observed_at_ms"])
                if age == 30.001:
                    bot = self.bot()
                    message = self.message()
                    await bot.on_group_message_create(message)
                    self.assertIn("数据可能过期", message.reply.call_args.kwargs["content"])

    async def test_null_metrics_are_supported_without_fabricating_tps(self):
        self.assertEqual((await self.report(tps=None, mspt_ms=None)).status, 200)
        result = self.item(await self.read())
        self.assertIsNone(result["snapshot"]["tps"])
        self.assertIsNone(result["snapshot"]["mspt_ms"])
        bot = self.bot()
        message = self.message(group_openid="group-0")
        await bot.on_group_message_create(message)
        self.assertNotIn("20.0", message.reply.call_args.kwargs["content"])

    async def test_identical_event_replay_does_not_refresh_snapshot(self):
        snapshot = self.snapshot()
        first = await self.report(snapshot)
        self.assertEqual(first.status, 200)
        original = self.item(await self.read())["snapshot"]
        self.now += 10
        duplicate = await self.report(snapshot)
        body = await duplicate.json()
        self.assertEqual((duplicate.status, body["accepted"], body["reason"]), (200, False, "duplicate"))
        current = self.item(await self.read())["snapshot"]
        self.assertEqual(current, original)
        self.assertEqual(body["event_id"], snapshot["event_id"])
        self.assert_request_id(duplicate, body)

    async def test_same_event_id_cannot_change_payload_or_server(self):
        snapshot = self.snapshot()
        self.assertEqual((await self.report(snapshot)).status, 200)
        for replacement in (dict(snapshot, online_players=4), dict(snapshot, server_id="lobby")):
            self.assertEqual((await self.report(replacement)).status, 409)
        self.assertEqual(self.item(await self.read())["snapshot"]["online_players"], 3)

    async def test_known_event_can_be_retried_after_observation_expires(self):
        snapshot = self.snapshot()
        self.assertEqual((await self.report(snapshot)).status, 200)
        self.now += 121
        response = await self.report(snapshot)
        data = await response.json()
        self.assertEqual((response.status, data["accepted"], data["reason"]), (200, False, "duplicate"))
        result = self.item(await self.read())
        self.assertEqual(result["freshness"], "expired")
        self.assertIsNone(result["snapshot"])

    async def test_out_of_order_and_equal_timestamp_conflict_keep_latest(self):
        snapshot = self.snapshot()
        self.assertEqual((await self.report(snapshot)).status, 200)
        self.now += 2
        older = self.snapshot(observed_at_ms=snapshot["observed_at_ms"] - 1000)
        response = await self.report(older)
        body = await response.json()
        self.assertEqual((response.status, body["accepted"], body["reason"]), (200, False, "out_of_order"))
        # Even a discarded old event consumes its ID: a later payload cannot
        # turn the same receipt into a different observation.
        changed_old = dict(older, observed_at_ms=int(self.now * 1000), online_players=5)
        self.assertEqual((await self.report(changed_old)).status, 409)
        conflict = self.snapshot(observed_at_ms=snapshot["observed_at_ms"], online_players=4)
        self.assertEqual((await self.report(conflict)).status, 409)
        self.assertEqual(self.item(await self.read())["snapshot"]["event_id"], snapshot["event_id"])

    async def test_reporter_and_bot_and_proxy_credentials_are_separate(self):
        for role in (None, "wrong-token", "bot_token", "proxy_token"):
            with self.subTest(role=role):
                self.assertEqual((await self.post(SNAPSHOTS, self.snapshot(), role)).status, 401)
        for role in (None, "wrong-token", "status_reporter_token", "proxy_token"):
            with self.subTest(role=role):
                self.assertEqual((await self.post(QUERY, self.query(), role)).status, 401)
        self.assertEqual((await self.report()).status, 200)

    async def test_query_identity_cannot_claim_groups_or_admin_roles(self):
        for changes, expected in (({"app_id": "wrong-app"}, 403), ({"group_openid": "outside"}, 409),
                                  ({"member_openid": ""}, 400), ({"member_openid": "bad\nmember"}, 400),
                                  ({"event_id": "/op @a"}, 400), ({"role": "owner"}, 400),
                                  ({"schema_version": True}, 400)):
            with self.subTest(changes=changes):
                self.assertEqual((await self.post(QUERY, self.query(**changes))).status, expected)

    async def test_non_ascii_bearer_is_rejected_with_correlated_json(self):
        response = await self.client.post(QUERY, json=self.query(), headers={"Authorization": "Bearer 合成无效凭证"})
        self.assertEqual(response.status, 401)
        self.assert_request_id(response, await response.json())

    async def test_snapshot_rejects_malicious_fields_types_ranges_and_nonfinite_metrics(self):
        invalid = [
            {"schema_version": True}, {"schema_version": 2}, {"event_id": "not-a-uuid"},
            {"server_id": "../survival"}, {"server_id": "survival;op"}, {"command": "op @a"},
            {"online_players": True}, {"online_players": -1}, {"online_players": 51},
            {"max_players": 0}, {"max_players": 100001}, {"tps": True}, {"tps": -1},
            {"tps": 1001}, {"tps": float("nan")}, {"mspt_ms": float("inf")},
            {"mspt_ms": 60001}, {"observed_at_ms": True}, {"availability": "maybe"},
            {"availability": "offline", "online_players": 1, "tps": None, "mspt_ms": None},
            {"availability": "offline", "online_players": 0},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                self.assertEqual((await self.report(**changes)).status, 400)
        missing = self.snapshot()
        del missing["mspt_ms"]
        self.assertEqual((await self.report(missing)).status, 400)
        self.assertEqual((await self.report([])).status, 400)
        self.assertEqual((await self.report(server_id="unconfigured")).status, 403)

    async def test_observation_clock_skew_and_maximum_ingest_age(self):
        for offset in (-120001, 5001):
            with self.subTest(offset=offset):
                self.assertEqual((await self.report(observed_at_ms=int(self.now * 1000) + offset)).status, 400)
        self.assertEqual((await self.report(observed_at_ms=int(self.now * 1000) + 5000)).status, 200)
        self.assertEqual(self.item(await self.read())["age_seconds"], 0)

    async def test_ingestion_rate_limit_allows_duplicate_ack_and_recovers(self):
        snapshot = self.snapshot()
        self.assertEqual((await self.report(snapshot)).status, 200)
        duplicate = await self.report(snapshot)
        self.assertEqual((await duplicate.json())["reason"], "duplicate")
        response = await self.report(observed_at_ms=int(self.now * 1000) + 1)
        self.assertEqual(response.status, 429)
        self.assertGreaterEqual(int(response.headers["Retry-After"]), 1)
        self.now += 1
        self.assertEqual((await self.report()).status, 200)

    async def test_query_group_rate_limit_and_recovery(self):
        self.assertEqual((await self.post(QUERY, self.query())).status, 200)
        response = await self.post(QUERY, self.query())
        self.assertEqual(response.status, 429)
        self.assertGreaterEqual(int(response.headers["Retry-After"]), 1)
        self.now += 5
        self.assertEqual((await self.post(QUERY, self.query())).status, 200)

    async def test_query_global_limit_is_independent_of_group(self):
        for index in range(30):
            response = await self.post(QUERY, self.query(group_openid="group-" + str(index)))
            self.assertEqual(response.status, 200)
        response = await self.post(QUERY, self.query(group_openid="group-30"))
        self.assertEqual(response.status, 429)
        self.assertIn("Retry-After", response.headers)
        self.now += 60
        self.assertEqual((await self.post(QUERY, self.query(group_openid="group-30"))).status, 200)

    async def test_legacy_status_route_stays_proxy_scoped_and_unchanged(self):
        response = await self.client.get("/v1/status", headers={"Authorization": "Bearer " + self.cfg["proxy_token"]})
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.json(), {"allowed_group_count": len(self.cfg["allowed_groups"]), "binding_count": 0})
        response = await self.client.get("/v1/status", headers={"Authorization": "Bearer " + self.cfg["status_reporter_token"]})
        self.assertEqual(response.status, 401)

    async def test_disabled_default_keeps_auth_before_feature_availability(self):
        cfg = copy.deepcopy(self.cfg)
        del cfg["server_status"]
        del cfg["status_reporter_token"]
        client = await self.start_client(cfg)
        response = await self.post(QUERY, self.query(), client=client)
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["code"], "disabled")
        # No reporter credential exists in the default configuration. A bot
        # credential cannot probe or write the upload endpoint, even when off.
        response = await self.post(SNAPSHOTS, self.snapshot(), client=client)
        self.assertEqual(response.status, 401)
        cfg["status_reporter_token"] = "s" * 40
        response = await self.post(SNAPSHOTS, self.snapshot(), "status_reporter_token", client=client)
        self.assertEqual(response.status, 503)
        self.assertEqual((await response.json())["code"], "disabled")

    async def test_enabled_configuration_requires_independent_reporter_credential(self):
        for token in (None, "short", self.cfg["bot_token"], self.cfg["proxy_token"]):
            with self.subTest(token_length=len(token) if token else 0):
                cfg = copy.deepcopy(self.cfg)
                cfg["status_reporter_token"] = token
                with self.assertRaises(ValueError):
                    create_app(cfg, resolver=self.resolver, status_clock=lambda: self.now)

    async def test_bot_status_parameters_never_forward_to_chat_or_commands(self):
        bot = self.bot()
        bot.relay_group = AsyncMock()
        bot.call_service = AsyncMock()
        for text in ("/服务器 op @a", "/在线 http://127.0.0.1/", "/服务器 ; DROP TABLE bindings"):
            with self.subTest(text=text):
                message = self.message(text)
                await bot.on_group_message_create(message)
                message.reply.assert_awaited_once()
                self.assertIn("/服务器", message.reply.call_args.kwargs["content"])
        bot.relay_group.assert_not_awaited()
        bot.call_service.assert_not_awaited()

    async def test_bot_timeout_or_disconnect_is_not_minecraft_offline(self):
        for error in (asyncio.TimeoutError(), aiohttp.ClientConnectionError("synthetic disconnect")):
            with self.subTest(error=type(error).__name__):
                bot = self.bot()
                bot.call_service = AsyncMock(side_effect=error)
                message = self.message()
                await bot.on_group_message_create(message)
                text = message.reply.call_args.kwargs["content"]
                self.assertIn("状态服务暂时不可用", text)
                self.assertNotIn("离线", text)
                bot.call_service.assert_awaited_once()

    async def test_bot_cooldown_stops_second_status_http_request(self):
        bot = self.bot()
        bot.call_service = AsyncMock(wraps=bot.call_service)
        one, two = self.message(), self.message("/在线")
        await bot.on_group_message_create(one)
        await bot.on_group_message_create(two)
        bot.call_service.assert_awaited_once()
        two.reply.assert_awaited_once()
        self.assertIn("稍后", two.reply.call_args.kwargs["content"])

    async def test_bot_maps_real_api_unavailable_and_rate_limited_responses(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["server_status"]["enabled"] = False
        disabled_client = await self.start_client(cfg)
        bot = self.bot()
        bot.settings["service_url"] = str(disabled_client.make_url("/"))
        message = self.message()
        await bot.on_group_message_create(message)
        self.assertIn("状态", message.reply.call_args.kwargs["content"])
        self.assertNotIn("离线", message.reply.call_args.kwargs["content"])
        await self.read()
        bot = self.bot()
        message = self.message()
        await bot.on_group_message_create(message)
        self.assertIn("稍后", message.reply.call_args.kwargs["content"])

    async def test_bot_rejects_null_list_and_malformed_server_items(self):
        for payload in (None, [], {"schema_version": 1, "servers": [None]},
                        {"schema_version": 1, "servers": [42]},
                        {"schema_version": 1, "servers": [{"server_id": "survival", "freshness": "fresh",
                                                           "age_seconds": 0, "snapshot": None}]}):
            with self.subTest(payload=payload):
                bot = self.bot()
                bot.call_service = AsyncMock(return_value=payload)
                message = self.message()
                await bot.on_group_message_create(message)
                message.reply.assert_awaited_once()
                self.assertIn("状态服务暂时不可用", message.reply.call_args.kwargs["content"])

    async def test_real_http_wait_is_bounded_to_three_seconds(self):
        release = asyncio.Event()
        requests = []

        async def slow_api(request):
            requests.append(await request.json())
            await release.wait()
            return web.json_response({"schema_version": 1, "servers": []})

        app = web.Application()
        app.router.add_post(QUERY, slow_api)
        client = TestClient(TestServer(app))
        await client.start_server()
        self.clients.append(client)
        bot = self.bot()
        bot.settings["service_url"] = str(client.make_url("/"))
        message = self.message()
        started = time.monotonic()
        try:
            await asyncio.wait_for(bot.on_group_message_create(message), timeout=4.5)
        finally:
            release.set()
        elapsed = time.monotonic() - started
        self.assertGreaterEqual(elapsed, 2.5)
        self.assertLess(elapsed, 4.5)
        self.assertEqual(len(requests), 1)
        self.assertIn("状态服务暂时不可用", message.reply.call_args.kwargs["content"])

    async def test_new_api_errors_return_correlated_json_ids(self):
        snapshot = self.snapshot()
        self.assertEqual((await self.report(snapshot)).status, 200)
        requests = (
            (QUERY, self.query(), None, 401),
            (QUERY, self.query(app_id="wrong-app"), "bot_token", 403),
            (QUERY, self.query(group_openid="outside"), "bot_token", 409),
            (SNAPSHOTS, self.snapshot(server_id="unknown"), "status_reporter_token", 403),
            (SNAPSHOTS, self.snapshot(online_players=-1), "status_reporter_token", 400),
            (SNAPSHOTS, dict(snapshot, online_players=4), "status_reporter_token", 409),
        )
        for path, payload, role, expected in requests:
            with self.subTest(path=path, expected=expected):
                response = await self.post(path, payload, role)
                self.assertEqual(response.status, expected)
                self.assert_request_id(response, await response.json())
        response = await self.client.get(QUERY, headers={"Authorization": "Bearer " + self.cfg["bot_token"]})
        self.assertEqual(response.status, 405)
        self.assert_request_id(response, await response.json())

    async def test_observation_logs_omit_credentials_and_qq_identity(self):
        with self.assertLogs("mcqq.server_status", level="INFO") as captured:
            self.assertEqual((await self.report()).status, 200)
            self.assertEqual((await self.post(QUERY, self.query(member_openid="synthetic-private-member"))).status, 200)
            self.assertEqual((await self.report(secret_text="synthetic-private-content")).status, 400)
        output = "\n".join(captured.output)
        self.assertIn("request_id=", output)
        for secret in (self.cfg["bot_token"], self.cfg["proxy_token"], self.cfg["status_reporter_token"],
                       "synthetic-private-member", "synthetic-private-content"):
            self.assertNotIn(secret, output)


class ClockTests(unittest.TestCase):
    def test_clock_corrections_do_not_rejuvenate_observations_or_stall_limits(self):
        from mcqq.server_status import Snapshots
        repository = Snapshots(["survival"])
        wall = 1800000000000
        data = dict(schema_version=1, event_id=str(uuid.uuid4()), server_id="survival",
                    observed_at_ms=wall, availability="online", online_players=1,
                    max_players=50, tps=None, mspt_ms=None)
        self.assertEqual(repository.receive(data, wall, 0), (200, "accepted"))
        self.assertTrue(repository.query_allowed("group", 0))
        self.assertFalse(repository.query_allowed("group", 4999))
        self.assertTrue(repository.query_allowed("group", 5000))
        # Wall clock rolls back while elapsed time keeps advancing.
        self.assertEqual(repository.view(wall - 60000, 121000)[0]["freshness"], "expired")
        # A temporary forward correction must not rejuvenate on the next query.
        repository = Snapshots(["survival"])
        repository.receive(data, wall, 0)
        self.assertEqual(repository.view(wall + 121000, 1000)[0]["freshness"], "expired")
        self.assertEqual(repository.view(wall, 2000)[0]["freshness"], "expired")
        replacement = dict(data, event_id=str(uuid.uuid4()), observed_at_ms=wall + 1000)
        self.assertEqual(repository.receive(replacement, wall + 1000, 3000), (200, "accepted"))
        self.assertEqual(repository.view(wall + 1000, 3000)[0]["freshness"], "fresh")


if __name__ == "__main__":
    unittest.main()
