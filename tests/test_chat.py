import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer
from mcqq.bot import QQBot
from mcqq.service import create_app
from mcqq.store import Store

PLAYER = "12345678-1234-4234-8234-123456789abc"


class ChatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cfg = dict(database=str(Path(self.temp.name)/"db"), app_id="app", allowed_groups=["group"],
                        bot_token="b"*40, proxy_token="p"*40, chat_bridge={"servers": ["lobby", "survival", "bw"]})
        self.client = TestClient(TestServer(create_app(self.cfg)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def post(self, route, payload, proxy=False):
        response = await self.client.post("/v1/chat/"+route, json=payload,
                                          headers={"Authorization": "Bearer "+self.cfg["proxy_token" if proxy else "bot_token"]})
        return response

    def qq(self, **extra):
        return dict(app_id="app", group_openid="group", member_openid="member", event_id="qq1", text="hello  /op @a %name% & 任意符号", **extra)

    async def test_scope_dedup_identity_and_ack(self):
        self.assertEqual((await self.post("from-qq", self.qq(), True)).status, 401)
        self.assertEqual((await self.post("to-game", {})).status, 401)
        bad = self.qq(); bad["group_openid"] = "elsewhere"
        self.assertEqual((await self.post("from-qq", bad)).status, 409)
        for _ in range(2): self.assertEqual((await self.post("from-qq", self.qq())).status, 200)
        messages = (await (await self.post("to-game", {}, True)).json())["messages"]
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["qq_id"], "member")
        self.assertEqual(messages[0]["text"], self.qq()["text"])
        await self.post("ack-game", {"ids": [messages[0]["id"]]}, True)
        self.assertEqual((await (await self.post("to-game", {}, True)).json())["messages"], [])

    async def test_bound_player_name_qq_nickname_and_server_scope(self):
        store = Store(self.cfg["database"])
        store.bind(dict(app_id="app", group_openid="group", member_openid="member", event_id="bind", action="bind", platform="java", name="Steve"),
                   dict(uuid=PLAYER, name="Steve", platform="java"))
        await self.post("from-qq", self.qq(nickname="群昵称"))
        messages = (await (await self.post("to-game", {}, True)).json())["messages"]
        self.assertEqual((messages[0]["uuid"], messages[0]["name"]), (PLAYER, "Steve"))
        game = dict(uuid=PLAYER, name="Steve", server="other", event_id="game1", text="/op  @a %s & !")
        self.assertEqual((await self.post("from-game", game, True)).status, 403)
        game["server"] = "survival"
        self.assertEqual((await self.post("from-game", game, True)).status, 200)
        self.assertEqual((await (await self.post("to-qq", {})).json())["messages"][0]["text"], "[游戏内]群昵称:"+game["text"])

    async def test_explicit_group_routes_and_alias(self):
        self.cfg["allowed_groups"] = ["group", "other"]
        self.cfg["chat_bridge"].update(inbound_groups=["group"], group_aliases={"group": "测试群"})
        forbidden = self.qq(); forbidden["group_openid"] = "other"
        self.assertEqual((await self.post("from-qq", forbidden)).status, 403)
        self.assertEqual((await self.post("from-qq", self.qq())).status, 200)
        incoming = (await (await self.post("to-game", {}, True)).json())["messages"]
        self.assertEqual(incoming[0]["group_name"], "测试群")
        game = dict(uuid=PLAYER, name="Steve", server="lobby", event_id="target", text="hello", group="other")
        self.assertEqual((await self.post("from-game", game, True)).status, 200)
        outgoing = (await (await self.post("to-qq", {})).json())["messages"]
        self.assertEqual([item["group"] for item in outgoing], ["other"])
        game.update(group="unknown", event_id="bad")
        self.assertEqual((await self.post("from-game", game, True)).status, 403)

    async def test_group_role_is_trusted_bot_metadata(self):
        for role in ("member", "admin", "owner"):
            data = self.qq(role=role)
            data["event_id"] = role
            self.assertEqual((await self.post("from-qq", data)).status, 200)
        messages = (await (await self.post("to-game", {}, True)).json())["messages"]
        self.assertEqual([m["role"] for m in messages], ["member", "admin", "owner"])
        self.assertEqual((await self.post("from-qq", self.qq(role="invented"))).status, 400)
        self.assertEqual((await self.post("from-qq", self.qq(role="owner"), True)).status, 401)

    def test_format_config_preserves_other_settings(self):
        from deploy.configure_chat_format import updated
        text = 'globalChat="old"\nlocalChat="old"\ndefaultPrefix="[Member]"\nother="unchanged"\n'
        result = updated(text)
        self.assertIn('other="unchanged"', result)
        self.assertNotIn('[Member]', result)
        self.assertEqual(result.count('%mcqq_origin%'), 2)

    async def test_fallback_expiry_and_persistence(self):
        game = dict(uuid=PLAYER, name="Steve", server="bw", event_id="game1", text="test")
        await self.post("from-game", game, True)
        self.assertEqual((await (await self.post("to-qq", {})).json())["messages"][0]["text"], "[游戏内]Steve:test")
        with Store(self.cfg["database"]).connect() as db:
            db.execute("UPDATE chat_queue SET created=0")
        self.assertEqual((await (await self.post("to-qq", {})).json())["messages"], [])

    async def test_full_message_commands_self_echo_and_duplicate_at(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = self.cfg
        bot.seen = OrderedDict()
        bot.call_service = AsyncMock(return_value={"ok": True})
        bot.group_response = AsyncMock(return_value="help")
        m = SimpleNamespace(id="1", content="hello", group_openid="group", author=SimpleNamespace(member_openid="member", bot=False, member_role="admin"), reply=AsyncMock())
        await bot.on_group_message_create(m)
        bot.call_service.assert_awaited_once()
        self.assertEqual(bot.call_service.call_args.args[1]["role"], "admin")
        bot.group_response.assert_not_awaited()
        await bot.on_group_at_message_create(m)
        m.reply.assert_not_awaited()
        m.id="2"; m.content="/群服互通"
        await bot.on_group_message_create(m)
        m.reply.assert_awaited_once_with(content="help")
        bot.call_service.reset_mock(); m.id="3"; m.content="hello"; m.author.bot=True
        await bot.on_group_message_create(m)
        bot.call_service.assert_not_awaited()

    async def test_empty_and_mention_only_messages_do_not_reply(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = self.cfg
        bot.seen = OrderedDict()
        bot.group_response = AsyncMock(return_value="help")
        bot.relay_group = AsyncMock()
        m = SimpleNamespace(id="1", content="", author=SimpleNamespace(bot=False), reply=AsyncMock())
        await bot.on_group_message_create(m)
        m.id = "2"; m.content = "<@!123> "
        await bot.on_group_at_message_create(m)
        m.reply.assert_not_awaited()
        bot.group_response.assert_not_awaited()
        bot.relay_group.assert_not_awaited()
