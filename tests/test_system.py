import asyncio
import json
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

from mcqq.commands import parse
from mcqq.service import create_app
from mcqq.store import BindingError, Store
from mcqq.bot import QQBot
from mcqq.afterglow import Afterglow

JAVA = str(uuid.UUID("12345678-1234-4234-8234-123456789abc"))
OTHER = str(uuid.UUID("87654321-4321-4321-8321-cba987654321"))
BEDROCK = str(uuid.UUID(int=2533274801587734))
BEDROCK2 = str(uuid.UUID(int=2533274801587735))


def payload(member="member", event="event", action="bind", name="Steve"):
    return dict(app_id="app", group_openid="group-openid", member_openid=member,
                event_id=event, action=action, platform="java", name=name)


def profile(id=JAVA, name="Steve", platform="java"):
    return {"uuid": id, "name": name, "platform": platform}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "db.sqlite", cooldown=0)

    def test_bind_replay_unique_and_rebind_revokes(self):
        result = self.store.bind(payload(), profile())
        self.assertEqual(result, self.store.bind(payload(), profile()))
        with self.assertRaises(BindingError):
            self.store.bind(payload(member="other", event="other"), profile())
        with self.assertRaises(BindingError):
            self.store.bind(payload(event="bad-event"), profile(OTHER))
        self.store.bind(payload(event="rebind", action="rebind"), profile(OTHER))
        self.assertFalse(self.store.authorized(JAVA))
        self.assertTrue(self.store.authorized(OTHER))
        self.assertEqual(Store(self.store.path).query("app:member")["game_uuid"], OTHER)

    def test_event_id_reuse_cannot_change_identity(self):
        self.store.bind(payload(), profile())
        with self.assertRaises(BindingError):
            self.store.bind(payload(member="attacker"), profile(OTHER))

    def test_concurrent_claim_only_one_winner(self):
        def claim(i):
            try:
                self.store.bind(payload(member=str(i), event=str(i)), profile())
                return True
            except BindingError:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(claim, range(16))), 1)

    def test_link_requires_java_owner_and_preserves_java_data_identity(self):
        self.store.bind(payload(), profile())
        request = self.store.request_link("app:member", profile(BEDROCK, "Xbox Name", "bedrock"))
        self.assertIsNone(self.store.link_for(BEDROCK))
        with self.assertRaises(BindingError):
            self.store.verify_link(request["code"], OTHER)
        self.store.verify_link(request["code"], JAVA)
        self.assertEqual(self.store.link_for(BEDROCK)["java_uuid"], JAVA)
        self.assertEqual(self.store.link_for(BEDROCK)["java_name"], "Steve")
        self.assertTrue(self.store.authorized(BEDROCK, JAVA))
        self.assertFalse(self.store.authorized(BEDROCK, BEDROCK))
        self.assertTrue(self.store.authorized(JAVA, JAVA))
        with self.assertRaises(BindingError):
            self.store.verify_link(request["code"], JAVA)
        self.store.bind(payload(event="rebind", action="rebind"), profile(OTHER))
        self.assertFalse(self.store.authorized(BEDROCK, JAVA))
        self.assertIsNone(self.store.link_for(BEDROCK))

    def test_replacing_bedrock_alias_revokes_old_one(self):
        self.store.bind(payload(), profile())
        for id in (BEDROCK, BEDROCK2):
            code = self.store.request_link("app:member", profile(id, "Xbox", "bedrock"))["code"]
            self.store.verify_link(code, JAVA)
        self.assertFalse(self.store.authorized(BEDROCK, JAVA))
        self.assertTrue(self.store.authorized(BEDROCK2, JAVA))

    def test_pending_link_cannot_take_a_claimed_account(self):
        self.store.bind(payload(), profile())
        code = self.store.request_link("app:member", profile(BEDROCK, "Xbox", "bedrock"))["code"]
        self.store.bind(payload(member="other", event="second"), profile(BEDROCK, "Xbox", "bedrock"))
        with self.assertRaises(BindingError):
            self.store.verify_link(code, JAVA)

    def test_expired_code_and_rebind_invalidate_pending(self):
        self.store.bind(payload(), profile())
        code = self.store.request_link("app:member", profile(BEDROCK, "Xbox", "bedrock"))["code"]
        with self.store.connect() as db:
            db.execute("UPDATE challenges SET expires=0")
        with self.assertRaises(BindingError):
            self.store.verify_link(code, JAVA)

    def test_unbind_revokes_both_accounts_and_can_bind_again(self):
        self.store.bind(payload(), profile())
        code = self.store.request_link("app:member", profile(BEDROCK, "Steve", "bedrock"))["code"]
        self.store.verify_link(code, JAVA)
        request = payload(event="leave", action="unbind")
        request["confirmed"] = True
        result = self.store.remove(request)
        self.assertTrue(result["removed"])
        self.assertEqual(self.store.remove(request), result)
        self.assertIsNone(self.store.query("app:member"))
        self.assertFalse(self.store.authorized(JAVA, JAVA))
        self.assertFalse(self.store.authorized(BEDROCK, JAVA))
        self.assertIsNone(self.store.link_for(BEDROCK))
        self.store.bind(payload(event="return"), profile())
        self.assertTrue(self.store.authorized(JAVA, JAVA))

    def test_unlink_keeps_java_and_cancels_pending_proof(self):
        self.store.bind(payload(), profile())
        code = self.store.request_link("app:member", profile(BEDROCK, "Steve", "bedrock"))["code"]
        self.store.verify_link(code, JAVA)
        pending = self.store.request_link("app:member", profile(BEDROCK2, "Steve2", "bedrock"))["code"]
        self.store.remove(payload(event="unlink", action="unlink"), only_link=True)
        self.assertTrue(self.store.authorized(JAVA, JAVA))
        self.assertFalse(self.store.authorized(BEDROCK, JAVA))
        with self.assertRaises(BindingError):
            self.store.verify_link(pending, JAVA)

    def test_removal_cannot_remove_another_member(self):
        self.store.bind(payload(), profile())
        self.store.remove(payload(member="other", event="leave-other", action="unbind"))
        self.assertTrue(self.store.authorized(JAVA, JAVA))
        code = self.store.request_link("app:member", profile(BEDROCK, "Xbox", "bedrock"))["code"]
        self.store.bind(payload(event="rebind", action="rebind"), profile(OTHER))
        with self.assertRaises(BindingError):
            self.store.verify_link(code, JAVA)


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = dict(database=str(Path(self.temp.name) / "db"), rebind_cooldown_seconds=0,
                        app_id="app", allowed_groups=["group-openid"], bot_token="b" * 40, proxy_token="p" * 40)
        async def resolver(session, platform, name):
            return profile(BEDROCK, name, "bedrock") if platform == "bedrock" else profile()
        self.client = TestClient(TestServer(create_app(self.cfg, resolver)))
        await self.client.start_server()
        self.bot = {"Authorization": "Bearer " + self.cfg["bot_token"]}
        self.proxy = {"Authorization": "Bearer " + self.cfg["proxy_token"]}

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def test_tokens_scopes_groups_and_untrusted_arguments(self):
        self.assertEqual((await self.client.post("/v1/bind", json=payload())).status, 401)
        self.assertEqual((await self.client.post("/v1/bind", json=payload(), headers=self.proxy)).status, 401)
        forged = payload(); forged["group_openid"] = "outside"
        self.assertEqual((await self.client.post("/v1/bind", json=forged, headers=self.bot)).status, 409)
        self.assertEqual((await self.client.post("/v1/bind", json={}, headers=self.bot)).status, 400)
        self.assertEqual((await self.client.post("/v1/bind", json=payload(), headers=self.bot)).status, 200)
        self.assertEqual((await self.client.post("/v1/verify", json={}, headers=self.bot)).status, 401)

    async def test_complete_link_protocol_and_canonical_login(self):
        await self.client.post("/v1/bind", json=payload(), headers=self.bot)
        request = payload(); request["name"] = "Xbox Name"
        response = await self.client.post("/v1/request-link", json=request, headers=self.bot)
        code = (await response.json())["code"]
        verification = {"code": code, "uuid": JAVA, "java_authenticated": False}
        self.assertEqual((await self.client.post("/v1/verify", json=verification, headers=self.proxy)).status, 409)
        verification["java_authenticated"] = True
        self.assertEqual((await self.client.post("/v1/verify", json=verification, headers=self.proxy)).status, 200)
        response = await self.client.get("/v1/link", params={"uuid": BEDROCK}, headers=self.proxy)
        self.assertEqual(await response.text(), JAVA + "\nSteve\n" + BEDROCK)
        response = await self.client.get("/v1/authorize", params={"uuid": BEDROCK, "session_uuid": JAVA}, headers=self.proxy)
        self.assertEqual(await response.text(), "allow")
        response = await self.client.get("/v1/authorize", params={"uuid": BEDROCK, "session_uuid": OTHER}, headers=self.proxy)
        self.assertEqual(await response.text(), "deny")
        self.assertEqual((await self.client.get("/v1/authorize", params={"uuid": BEDROCK}, headers=self.proxy)).status, 400)

    async def test_remove_requires_confirmation_and_bot_token(self):
        await self.client.post("/v1/bind", json=payload(), headers=self.bot)
        request = payload(event="leave", action="unbind")
        response = await self.client.post("/v1/remove", json=request, headers=self.bot)
        self.assertEqual(response.status, 400)
        request["confirmed"] = True
        self.assertEqual((await self.client.post("/v1/remove", json=request, headers=self.proxy)).status, 401)
        self.assertEqual((await self.client.post("/v1/remove", json=request, headers=self.bot)).status, 200)
        response = await self.client.get("/v1/authorize", params={"uuid": JAVA, "session_uuid": JAVA}, headers=self.proxy)
        self.assertEqual(await response.text(), "deny")


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_never_reaches_afterglow_and_requires_official_member_identity(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = dict(app_id="app", allowed_groups=["group-openid"])
        bot.call_service = AsyncMock(return_value={"name": "Steve", "platform": "java"})
        message = SimpleNamespace(id="id", content="/绑定 Java Steve", group_openid="outside",
                                  author=SimpleNamespace(member_openid="member"))
        self.assertIn("尚未开放", await bot.group_response(message))
        bot.call_service.assert_not_called()
        message.group_openid = "group-openid"
        self.assertIn("入服资格已开通", await bot.group_response(message))
        self.assertEqual(bot.call_service.call_args.args[1]["member_openid"], "member")
        message.author = SimpleNamespace(id="untrusted-fallback")
        self.assertIn("缺少", await bot.group_response(message))

    async def test_same_name_bedrock_binding_routes_to_link_without_rebind(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = dict(app_id="app", allowed_groups=["group-openid"])
        bot.call_service = AsyncMock(side_effect=[
            {"binding": {"platform": "java", "name": "Steve", "bedrock_name": None}},
            {"code": "ABCDEF123456", "java_name": "Steve", "bedrock_name": "Steve"}])
        message = SimpleNamespace(id="id", content="/绑定 基岩 Steve", group_openid="group-openid",
                                  author=SimpleNamespace(member_openid="member"))
        reply = await bot.group_response(message)
        self.assertIn("Java 主账号保留", reply)
        self.assertIn("/qqverify ABCDEF123456", reply)
        self.assertEqual([call.args[0] for call in bot.call_service.call_args_list], ["/v1/query", "/v1/request-link"])

    async def test_unbind_preview_does_not_write_and_confirmation_does(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = dict(app_id="app", allowed_groups=["group-openid"])
        bot.call_service = AsyncMock(return_value={"binding": {"platform": "java", "name": "Steve", "bedrock_name": "Steve"}})
        message = SimpleNamespace(id="id", content="/解绑", group_openid="group-openid",
                                  author=SimpleNamespace(member_openid="member"))
        self.assertIn("/解绑 确认", await bot.group_response(message))
        self.assertEqual(bot.call_service.call_args.args[0], "/v1/query")
        bot.call_service.reset_mock(return_value=True)
        bot.call_service.return_value = {"removed": True}
        message.content = "/解绑 确认"
        self.assertIn("已解绑", await bot.group_response(message))
        self.assertEqual(bot.call_service.call_args.args[0], "/v1/remove")

    async def test_afterglow_owner_only_private_adapter_and_silence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bridge.json"
            path.write_text(json.dumps({"official_users": ["owner"], "ready": True,
                                        "base_url": "http://afterglow", "api_key": "synthetic"}))
            bridge = Afterglow(path)
            self.assertIn("仅向", await bridge.respond("stranger", "hello"))
            self.assertEqual(bridge.history, {})
            response = AsyncMock()
            response.status = 200
            response.json.return_value = {"choices": [{"message": {"content": "reply"}}]}
            context = AsyncMock(); context.__aenter__.return_value = response
            session = AsyncMock(); session.post = lambda *a, **k: context
            outer = AsyncMock(); outer.__aenter__.return_value = session
            with patch("mcqq.afterglow.aiohttp.ClientSession", return_value=outer):
                self.assertEqual(await bridge.respond("owner", "hello"), "reply")
                response.json.return_value = {"policy": {"should_reply": False}}
                self.assertIsNone(await bridge.respond("owner", "hello again"))
            self.assertEqual(len(bridge.history["owner"]), 2)

    def test_command_parser_keeps_xbox_spaces(self):
        self.assertEqual(parse("<@!123> /关联基岩 Xbox Name"), ("link", "bedrock", "Xbox Name"))
        self.assertEqual(parse("/绑定 基岩 Xbox Name"), ("bind", "bedrock", "Xbox Name"))
        with self.assertRaises(ValueError): parse("/绑定 Steve")

    def test_qq_panel_fields_fit_official_display_width_limits(self):
        from sync_commands import panel_config, display_width
        panel = panel_config()
        self.assertEqual(len(panel["items"]), 13)
        self.assertEqual(display_width("本群ID"), 6)
        for item in panel["items"]:
            self.assertLessEqual(display_width(item["name"]), 14)
            self.assertLessEqual(display_width(item["desc"]), 30)

    def test_explicit_commands_and_action_specific_hints(self):
        self.assertEqual(parse("/绑定Java Steve"), ("bind", "java", "Steve"))
        self.assertEqual(parse("/换绑基岩 Xbox Name"), ("rebind", "bedrock", "Xbox Name"))
        self.assertEqual(parse("/解绑 确认"), ("unbind", None, "确认"))
        self.assertEqual(parse("/解除关联"), ("unlink", None, ""))
        with self.assertRaisesRegex(ValueError, "换绑Java GoRichid"):
            parse("/换绑 GoRichid")


if __name__ == "__main__":
    unittest.main()
