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
                        bot_token="b"*40, proxy_token="p"*40, chat_bridge={"servers": ["lobby", "survival", "bw"],
                                                                            "command_targets": ["lobby", "survival", "proxy"]},
                        bot_roles={"owners": ["owner"], "admins": ["admin"]})
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

    async def test_independent_direction_lists_and_target_restriction(self):
        self.cfg["allowed_groups"] = ["group", "other"]
        self.cfg["chat_bridge"].update(inbound_groups=["group"], outbound_groups=["other"])
        self.assertEqual((await self.post("from-qq", self.qq())).status, 200)
        game = dict(uuid=PLAYER, name="Steve", server="lobby", event_id="broadcast", text="hello")
        self.assertEqual((await self.post("from-game", game, True)).status, 200)
        messages = (await (await self.post("to-qq", {})).json())["messages"]
        self.assertEqual([m["group"] for m in messages], ["other"])
        game.update(event_id="blocked", group="group")
        self.assertEqual((await self.post("from-game", game, True)).status, 403)
        self.cfg["chat_bridge"]["outbound_groups"] = []
        game.update(event_id="none", group="")
        self.assertEqual((await self.post("from-game", game, True)).status, 200)
        self.assertEqual(len((await (await self.post("to-qq", {})).json())["messages"]), 1)

    async def test_invalid_outbound_configuration_rejected(self):
        for value in ("group", ["unknown"], None):
            cfg = dict(self.cfg, chat_bridge={"outbound_groups": value})
            with self.assertRaises(ValueError):
                create_app(cfg)

    async def test_group_role_is_trusted_bot_metadata(self):
        for role in ("member", "admin", "owner"):
            data = self.qq(role=role)
            data["event_id"] = role
            self.assertEqual((await self.post("from-qq", data)).status, 200)
        messages = (await (await self.post("to-game", {}, True)).json())["messages"]
        self.assertEqual([m["role"] for m in messages], ["member", "admin", "owner"])
        self.assertEqual((await self.post("from-qq", self.qq(role="invented"))).status, 400)
        self.assertEqual((await self.post("from-qq", self.qq(role="owner"), True)).status, 401)

    async def test_group_command_permission_is_independent_from_chat(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = self.cfg
        bot.settings["chat_bridge"]["command_groups"] = ["other"]
        bot.call_service = AsyncMock()
        message = SimpleNamespace(content="/本群ID", group_openid="group",
                                  author=SimpleNamespace(member_openid="member"), id="event")
        self.assertEqual(await bot.group_response(message), "本群 group_openid：group")
        bot.call_service.assert_not_awaited()
        message.group_openid = "other"
        self.assertEqual(await bot.group_response(message), "本群 group_openid：other")
        bot.settings["chat_bridge"]["command_groups"] = "group"
        message.group_openid = "group"
        self.assertEqual(await bot.group_response(message), "本群 group_openid：group")
        message.content = "/帮助"
        self.assertEqual(await bot.group_response(message), "本群暂未开放机器人命令。")

    async def test_cross_group_message_preserves_spaces_and_checks_destination(self):
        from mcqq.commands import parse
        self.assertEqual(parse('/跨群信息 [朋友群]  hello /op @a !'),
                         ('cross_group', '朋友群', 'hello /op @a !'))
        self.assertEqual(parse('/跨群信息 朋友群 hello !'), ('cross_group', '朋友群', 'hello !'))
        self.assertEqual(parse('/跨群信息 ALL hello'), ('cross_group', 'ALL', 'hello'))
        self.assertEqual(parse('/跨群信息'), ('cross_group_list', None, None))
        self.cfg['allowed_groups'] = ['group', 'other']
        self.cfg['chat_bridge']['outbound_groups'] = ['other']
        self.cfg['chat_bridge']['group_aliases'] = {'other': '朋友群'}
        bot = QQBot.__new__(QQBot)
        bot.settings = self.cfg
        bot.api = SimpleNamespace(post_group_message=AsyncMock())
        bot.group_name = AsyncMock(return_value='官方群名')
        message = SimpleNamespace(content='/跨群信息 [朋友群] hello /op @a !',
                                  group_openid='group', author=SimpleNamespace(member_openid='member', nickname='小明'), id='cross1')
        self.assertEqual(await bot.group_response(message), '已发送到 1 个群。')
        bot.api.post_group_message.assert_awaited_once_with(group_openid='other', msg_type=0,
                                                               content='【跨群信息｜官方群名】小明：hello /op @a !')
        message.content = '/跨群信息 [unknown] hello'
        self.assertIn('目标群未找到', await bot.group_response(message))
        message.content = '/跨群信息'
        self.assertIn('朋友群：other', await bot.group_response(message))
        self.cfg['chat_bridge']['outbound_groups'] = ['group', 'other']
        message.content = '/跨群信息 ALL hello everyone'
        bot.api.post_group_message.reset_mock()
        self.assertEqual(await bot.group_response(message), '已发送到 2 个群。')
        self.assertEqual([c.kwargs['group_openid'] for c in bot.api.post_group_message.await_args_list], ['group', 'other'])

    async def test_remote_command_requires_binding_and_backend_token(self):
        identity = dict(app_id='app', group_openid='group', member_openid='member', event_id='cmd1',
                        command='/say  hi ! @a', target='survival', mode='player')
        response = await self.client.post('/v1/command/submit', json=identity,
                                          headers={'Authorization': 'Bearer ' + self.cfg['bot_token']})
        self.assertEqual(response.status, 409)
        Store(self.cfg['database']).bind(dict(app_id='app', group_openid='group', member_openid='member',
                                              event_id='bind', action='bind', platform='java', name='Steve'),
                                         dict(uuid=PLAYER, name='Steve', platform='java'))
        async def command(route, body, proxy=False):
            return await self.client.post('/v1/command/' + route, json=body,
                headers={'Authorization': 'Bearer ' + self.cfg['proxy_token' if proxy else 'bot_token']})
        self.assertEqual((await command('submit', identity)).status, 200)
        self.assertEqual((await command('poll', {'server': 'survival'})).status, 401)
        batch = await (await command('poll', {'server': 'survival'}, True)).json()
        self.assertEqual(batch['commands'][0]['command'], identity['command'])
        self.assertEqual((await (await command('poll', {'server': 'survival'}, True)).json())['commands'], [])
        self.assertEqual((await command('complete', {'server': 'survival', 'event': 'cmd1', 'result': '已执行'}, True)).status, 200)
        self.assertEqual((await (await command('result', identity)).json())['results'][0]['result'], '已执行')

    async def test_console_command_roles_and_all_targets(self):
        async def command(route, body, proxy=False):
            return await self.client.post('/v1/command/' + route, json=body,
                headers={'Authorization': 'Bearer ' + self.cfg['proxy_token' if proxy else 'bot_token']})
        data = dict(app_id='app', group_openid='group', event_id='admin1', command='/say  hi !',
                    target='survival', mode='console', member_openid='member')
        self.assertEqual((await command('submit', data)).status, 403)
        data['member_openid'] = 'admin'
        self.assertEqual((await command('submit', data)).status, 200)
        data.update(event_id='admin2', target='proxy')
        self.assertEqual((await command('submit', data)).status, 403)
        data.update(event_id='owner1', target='ALL', member_openid='owner')
        self.assertEqual((await command('submit', data)).status, 200)
        for server in ('lobby', 'survival', 'proxy'):
            batch = await (await command('poll', {'server': server}, True)).json()
            self.assertTrue(any(job['event'] == 'owner1' and job['mode'] == 'console' for job in batch['commands']))
            await command('complete', {'server': server, 'event': 'owner1', 'result': 'ok'}, True)
        result = await (await command('result', data)).json()
        self.assertEqual(result['state'], 'done')
        self.assertEqual([item['server'] for item in result['results']], ['lobby', 'proxy', 'survival'])

    async def test_owner_can_grant_and_revoke_admin_without_restart(self):
        from mcqq.bot import mentioned_member
        target = 'A' * 32
        message = SimpleNamespace(raw_data={}, content='/设bot管理 <@!' + target + '>')
        self.assertEqual(mentioned_member(message, '<@!' + target + '>'), target)
        async def command(route, body):
            return await self.client.post('/v1/command/' + route, json=body,
                headers={'Authorization': 'Bearer ' + self.cfg['bot_token']})
        role = dict(app_id='app', group_openid='group', member_openid='member', event_id='role1',
                    target_member_openid=target, action='add')
        self.assertEqual((await command('admin', role)).status, 403)
        role['member_openid'] = 'owner'
        self.assertEqual((await command('admin', role)).status, 200)
        issued = dict(app_id='app', group_openid='group', member_openid=target, event_id='issued1',
                      mode='console', target='lobby', command='/say hi')
        self.assertEqual((await command('submit', issued)).status, 200)
        issued.update(event_id='issued2', target='ALL')
        self.assertEqual((await command('submit', issued)).status, 403)
        role.update(event_id='role2', action='remove')
        self.assertEqual((await command('admin', role)).status, 200)
        issued.update(event_id='issued3', target='lobby')
        self.assertEqual((await command('submit', issued)).status, 403)

    def test_machine_status_format(self):
        from mcqq.system_info import format_system_info
        self.assertEqual(format_system_info('Ubuntu 26.04', '6.8', 90000, 8*1048576, 3*1048576),
                         '【机器状态情报】\n系统：Ubuntu 26.04\n内核：6.8\n已运行：1天1小时\n内存：5.0/8.0 GiB（62%）')

    async def test_console_said_uses_console_identity(self):
        response = await self.post('from-game', dict(source='console', server='survival', event_id='console1',
                                                     text='hello  @a !'), True)
        self.assertEqual(response.status, 200)
        self.assertEqual((await (await self.post('to-qq', {})).json())['messages'][0]['text'],
                         '[Console]Console:hello  @a !')
        self.assertEqual((await (await self.post('to-game', {}, True)).json())['messages'][0]['source'], 'console')

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
