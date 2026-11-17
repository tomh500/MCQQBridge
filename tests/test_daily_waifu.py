import json
from datetime import datetime
from zoneinfo import ZoneInfo
import tempfile
import sqlite3
from contextlib import contextmanager
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from mcqq import daily_waifu, reply_controls
from mcqq.bot import QQBot, plain_game_output


class FakeDailyStorage:
    def __init__(self):
        self.values = {}
        self.accepted = set()
        self.catalog = json.loads(daily_waifu.CATALOG_PATH.read_text(encoding="utf-8"))
        self.entry = self.catalog[0]
        self.resets = set()
        self.swapped = set()

    def get_or_create(self, subject, day):
        key = subject, day
        fresh = key not in self.values
        self.values.setdefault(key, self.entry)
        return dict(self.values[key], new=fresh, swapped=key in self.swapped, draw_token="a" * 32)

    def swap_once(self, subject, day, token=None):
        key = subject, day
        if key not in self.values:
            return {"error": "请先抽取。"}
        if token is not None and token != "a" * 32:
            return {"error": "按钮已失效。"}
        if key in self.accepted:
            return dict(self.values[key], swapped=True, exchanged=False, new=False, draw_token="a" * 32)
        fresh = self.values[key] == self.catalog[0]
        self.values[key] = self.catalog[1]
        self.swapped.add(key)
        return dict(self.values[key], swapped=True, exchanged=fresh, new=False, draw_token="a" * 32)

    def accept(self, subject, day, token):
        if (subject, day) not in self.values or token != "a" * 32:
            return {"error": "按钮已失效。"}
        self.accepted.add((subject, day))
        return {"accepted": True}

    def reset_all(self, day, event):
        if event in self.resets:
            return {"reset": False, "count": 0}
        self.resets.add(event)
        count = sum(1 for key in self.values if key[1] == day)
        self.values = {key: value for key, value in self.values.items() if key[1] != day}
        self.swapped = {key for key in self.swapped if key[1] != day}
        return {"reset": True, "count": count}


class DailyWaifuTests(unittest.IsolatedAsyncioTestCase):
    async def test_points_commands_parse_self_and_signed_adjustment(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = {'app_id': 'app', 'allowed_groups': ['group'], 'chat_bridge': {'command_groups': ['group']}}
        bot.seen = {}
        bot.call_service = AsyncMock(return_value={'points': 7})
        bot.reply_group_text = AsyncMock()
        author = SimpleNamespace(member_openid='member', bot=False)
        message = SimpleNamespace(id='one', group_openid='group', author=author, content='/今日老婆 积分点 查询 ignored', attachments=[])
        await bot.on_group_message_create(message)
        payload = bot.call_service.await_args.args[1]
        self.assertEqual(payload['action'], 'query')
        self.assertNotIn('target_member_openid', payload)
        self.assertNotIn('amount', payload)
        target = 'A' * 32
        message.id, message.content = 'two', '/今日老婆 积分点 添加 <@' + target + '> -12'
        await bot.on_group_message_create(message)
        payload = bot.call_service.await_args.args[1]
        self.assertEqual((payload['target_member_openid'], payload['amount']), (target, -12))

    async def test_points_authorization_is_enforced_by_api(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'roles.db'
            @contextmanager
            def connect():
                db = sqlite3.connect(path)
                db.row_factory = sqlite3.Row
                try:
                    with db:
                        yield db
                finally:
                    db.close()
            with connect() as db:
                db.execute('CREATE TABLE bot_role_admins(member_openid TEXT PRIMARY KEY, active INTEGER)')
                db.execute('INSERT INTO bot_role_admins VALUES (?,?)', ('manager', 1))
            app = web.Application()
            economy = SimpleNamespace(points=MagicMock(return_value={'points': 5}))
            daily_waifu.register(app, {'daily_waifu': {'enabled': True}, 'bot_roles': {'owners': ['owner']}},
                                 lambda d: 'app:' + d['member_openid'], storage=FakeDailyStorage(),
                                 role_store=SimpleNamespace(connect=connect), economy=economy)
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                req = {'member_openid': 'member', 'action': 'query', 'event_id': 'a'}
                self.assertEqual((await (await client.post('/v1/waifu/points', json=req)).json())['points'], 5)
                req.update(target_member_openid='victim', action='set', amount=10)
                self.assertEqual((await client.post('/v1/waifu/points', json=req)).status, 403)
                req.update(member_openid='manager')
                self.assertEqual((await client.post('/v1/waifu/points', json=req)).status, 200)
                self.assertEqual(economy.points.call_count, 2)
            finally:
                await client.close()

    async def test_accept_locks_current_choice(self):
        app = web.Application()
        storage = FakeDailyStorage()
        daily_waifu.register(app, {"daily_waifu": {"enabled": True}}, lambda d: d["member_openid"], storage=storage)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            data = {"member_openid": "user", "draw_token": "a" * 32}
            first = await (await client.post('/v1/waifu/today', json=data)).json()
            accepted = await (await client.post('/v1/waifu/accept', json=data)).json()
            after = await (await client.post('/v1/waifu/swap', json=data)).json()
            self.assertTrue(accepted['accepted'])
            self.assertFalse(after['exchanged'])
            self.assertEqual(first['image_url'], after['image_url'])
        finally:
            await client.close()

    async def test_daily_assignment_is_stable_per_member_across_groups(self):
        app = web.Application()
        storage = FakeDailyStorage()
        daily_waifu.register(app, {"daily_waifu": {"enabled": True}, "bot_roles": {"owners": ["owner"]}},
                             lambda data: "app:" + data["member_openid"], storage=storage)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            first = await (await client.post("/v1/waifu/today", json={"member_openid": "user", "group": "a"})).json()
            second = await (await client.post("/v1/waifu/today", json={"member_openid": "user", "group": "b"})).json()
            self.assertTrue(first["new"])
            self.assertFalse(second["new"])
            self.assertEqual(first["image_url"], second["image_url"])
            self.assertTrue(daily_waifu.valid_entry(first))
            swapped = await (await client.post("/v1/waifu/swap", json={"member_openid": "user", "draw_token": "a" * 32})).json()
            again = await (await client.post("/v1/waifu/swap", json={"member_openid": "user", "draw_token": "a" * 32})).json()
            after = await (await client.post("/v1/waifu/today", json={"member_openid": "user"})).json()
            self.assertTrue(swapped["exchanged"])
            self.assertNotEqual(first["image_url"], swapped["image_url"])
            self.assertFalse(again["exchanged"])
            self.assertEqual(after["image_url"], swapped["image_url"])
            self.assertTrue(after["swapped"])
            denied = await client.post("/v1/waifu/reset", json={"member_openid": "user", "event_id": "reset"})
            self.assertEqual(denied.status, 403)
            reset = await (await client.post("/v1/waifu/reset", json={"member_openid": "owner", "event_id": "reset"})).json()
            self.assertEqual(reset["count"], 1)
            reset_again = await (await client.post("/v1/waifu/reset", json={"member_openid": "owner", "event_id": "reset"})).json()
            self.assertFalse(reset_again["reset"])
            new_day_draw = await (await client.post("/v1/waifu/today", json={"member_openid": "user"})).json()
            self.assertTrue(new_day_draw["new"])
        finally:
            await client.close()

    async def test_qq_reply_preview_expansion_and_color_cleanup(self):
        self.assertEqual(plain_game_output("§aPlugins: §fMCQQ §x§F§F§0§0§0§0done"),
                         "Plugins: MCQQ done")
        self.assertEqual(reply_controls.localize("服务器内存，请用 /发命令 查询"),
                         "伺服器记忆体，请用 /发命令 查询")
        with tempfile.TemporaryDirectory() as temp:
            bot = QQBot.__new__(QQBot)
            bot.settings = {"database": str(Path(temp) / "reply.db"), "app_id": "app"}
            bot.api = SimpleNamespace(post_group_message=AsyncMock(), on_interaction_result=AsyncMock())
            message = SimpleNamespace(group_openid="group", id="message", reply=AsyncMock())
            await bot.reply_group_text(message, "1\n2\n3\n4\n5\n6\n7")
            message.reply.assert_not_awaited()
            call = bot.api.post_group_message.await_args.kwargs
            self.assertEqual(call["msg_type"], 2)
            self.assertTrue(call["markdown"]["content"].startswith("1\n2\n3\n4\n5\n"))
            token = call["keyboard"]["content"]["rows"][0]["buttons"][0]["action"]["data"].split(":", 1)[1]
            self.assertEqual(await bot.reply_store().load("group", token), "1\n2\n3\n4\n5\n6\n7")
            self.assertIsNone(await bot.reply_store().load("other", token))
            await bot.reply_store().close()

    async def test_first_draw_has_one_exchange_button_repeat_has_none(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = {"bot_token": "secret" * 8}
        bot.waifu_images = SimpleNamespace(resolve=AsyncMock(return_value="qqbot-media://image/v1/test"))
        bot.api = SimpleNamespace(post_group_file=AsyncMock(return_value={"file_info": "test"}),
                                  post_group_message=AsyncMock())
        data = dict(self_entry=json.loads(daily_waifu.CATALOG_PATH.read_text(encoding="utf-8"))[0])
        card = dict(data["self_entry"], day="2026-11-17", draw_token="a" * 32,
                    member_openid="member", new=True, swapped=False)
        await bot.send_waifu_card("group", card, msg_id="first", show_swap=True)
        self.assertEqual(bot.api.post_group_message.await_count, 1)
        button_call = bot.api.post_group_message.await_args.kwargs
        self.assertEqual(button_call["msg_type"], 2)
        buttons = button_call["keyboard"]["content"]["rows"][0]["buttons"]
        self.assertEqual([item["render_data"]["label"] for item in buttons], ["🔄换老婆", "✅就这个了!"])
        self.assertIn("qqbot-media://image/v1/test", button_call["markdown"]["content"])
        self.assertIn(card["work"], button_call["markdown"]["content"])
        self.assertEqual(button_call["keyboard"]["content"]["rows"][1]["buttons"][0]["action"]["data"], "/今日老婆")
        wish = button_call["keyboard"]["content"]["rows"][2]["buttons"][0]["action"]
        self.assertEqual(wish["data"], "/今日老婆 许愿 ")
        self.assertFalse(wish["enter"])
        self.assertTrue(buttons[0]["action"]["data"].startswith("waifu_swap:"))
        bot.api.post_group_message.reset_mock()
        await bot.send_waifu_card("group", dict(card, new=False), msg_id="repeat", show_swap=True)
        self.assertEqual(bot.api.post_group_message.await_count, 1)
        self.assertEqual(bot.api.post_group_message.await_args.kwargs["msg_type"], 2)

    async def test_exchange_button_is_bound_to_original_member(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = {"bot_token": "secret" * 8, "app_id": "app"}
        bot.api = SimpleNamespace(on_interaction_result=AsyncMock())
        bot.call_service = AsyncMock(return_value={"name": "new", "image_url": "test"})
        bot.send_waifu_card = AsyncMock()
        day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        button = bot.waifu_button_data("group", "owner", day, "a" * 32)
        def event(member):
            return SimpleNamespace(id="event", group_openid="group", group_member_openid=member,
                data=SimpleNamespace(resolved=SimpleNamespace(button_data=button)))
        await bot.on_interaction_create(event("someone-else"))
        bot.call_service.assert_not_awaited()
        self.assertEqual(bot.api.on_interaction_result.await_args.args[1], 4)
        await bot.on_interaction_create(event("owner"))
        bot.call_service.assert_awaited_once()
        self.assertEqual(bot.call_service.await_args.args[0], "/v1/waifu/swap")
        bot.send_waifu_card.assert_awaited_once()
