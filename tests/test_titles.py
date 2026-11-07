import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
import test_chat
from mcqq.bot import QQBot
from mcqq.commands import parse
from mcqq.store import Store
from mcqq.titles import mirror_sql


class TitleTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_chat.ChatTests.asyncSetUp
    asyncTearDown = test_chat.ChatTests.asyncTearDown
    post = test_chat.ChatTests.post
    qq = test_chat.ChatTests.qq
    async def change(self, title="井芹仁菜", role="member", event="title1", member="member", action="set", **kwargs):
        data = dict(app_id="app", group_openid="group", member_openid=member, event_id=event,
                    action=action, title=title, role=role)
        return await self.post("title", dict(data, **kwargs))

    async def test_limit_identity_and_proxy_scope(self):
        self.assertEqual((await self.change("字"*11)).status, 409)
        self.assertEqual((await self.change("😀"*10)).status, 200)
        self.assertEqual((await self.post("title", {}, True)).status, 401)
        with Store(self.cfg["database"]).connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM chat_titles").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT length(title) FROM chat_titles").fetchone()[0], 10)

    async def test_cooldown_persistent_global_and_clear_shared(self):
        response = await self.change()
        self.assertEqual((await response.json())["cooldown_seconds"], 3600)
        self.assertEqual((await self.change(event="title2", action="clear")).status, 409)
        self.cfg["allowed_groups"].append("another-group")
        self.assertEqual((await self.change(event="cross-group", group_openid="another-group")).status, 409)
        # Replayed delivery returns the original success without consuming another quota/outbox.
        self.assertEqual((await self.change()).status, 200)
        with Store(self.cfg["database"]).connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM chat_title_outbox").fetchone()[0], 1)
            db.execute("UPDATE chat_title_cooldowns SET changed=changed-3601")
        self.assertEqual((await self.change(event="title3", action="clear")).status, 200)
        await self.post("from-qq", self.qq())
        batch = await (await self.post("to-game", {}, True)).json()
        self.assertEqual(batch["messages"][0]["title"], "")
        self.assertEqual(batch["title_snapshot"][0]["title"], "")
        self.assertEqual((await self.change(event="title4")).status, 409)

    async def test_admin_owner_30_seconds_and_real_role_on_each_request(self):
        for role in ("admin", "owner"):
            member = role
            response = await self.change(role=role, member=member, event=role)
            self.assertEqual((await response.json())["cooldown_seconds"], 30)
            self.assertEqual((await self.change(role=role, member=member, event=role+"2")).status, 409)
        with Store(self.cfg["database"]).connect() as db:
            db.execute("UPDATE chat_title_cooldowns SET changed=changed-31")
        self.assertEqual((await self.change(role="admin", member="admin", event="admin3")).status, 200)
        self.assertEqual((await self.change(role="member", member="owner", event="demoted")).status, 409)

    async def test_concurrent_requests_only_one_success_and_title_propagates(self):
        replies = await asyncio.gather(self.change(event="a"), self.change(event="b"))
        self.assertEqual(sorted(r.status for r in replies), [200,409])
        await self.post("from-qq", self.qq(role="owner"))
        batch = await (await self.post("to-game", {}, True)).json()
        self.assertEqual(batch["messages"][0]["title"], "井芹仁菜")
        self.assertEqual(batch["messages"][0]["role"], "owner")
        self.assertEqual(batch["title_snapshot"], [{"group":"group","member":"member","title":"井芹仁菜"}])

    async def test_bot_only_uses_event_author_and_role(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = self.cfg
        bot.call_service = AsyncMock(return_value={"title":"井芹仁菜","cooldown_seconds":30})
        message = SimpleNamespace(id="official-event", content="/设置头衔 井芹仁菜", group_openid="group",
            author=SimpleNamespace(member_openid="real-author",member_role="admin"))
        reply = await bot.group_response(message)
        self.assertIn("井芹仁菜", reply)
        self.assertEqual(bot.call_service.call_args.args[1]["member_openid"], "real-author")
        self.assertEqual(bot.call_service.call_args.args[1]["role"], "admin")
        self.assertEqual(parse("/清除头衔"), ("title_clear",None,""))

    def test_sql_strings_are_encoded_and_not_interpolated_as_sql(self):
        text = "'); DROP TABLE bindings;--"
        sql = mirror_sql(dict(subject="app:member", group_id="group", title=text, role="member",changed=1234.0))
        self.assertNotIn(text, sql)
        self.assertIn(text.encode().hex(), sql)
