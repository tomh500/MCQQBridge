import tempfile
import unittest
from datetime import datetime, timedelta
import json
import sqlite3
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from mcqq.bot import QQBot
from mcqq.group_ai import GroupAI, History
from mcqq.group_reports import BEIJING, DailyReports
from mcqq.group_storage import ExternalHistory


class DailyReportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.settings = {"database": str(Path(root.name) / "bot.db"), "allowed_groups": ["one", "two"],
                         "chat_bridge": {"group_aliases": {"one": "一群", "two": "二群"}}}
        self.ai = GroupAI(self.settings)
        self.ai.config = {"enabled": True, "model": "test", "base_url": "https://example.invalid", "api_key": "test"}
        self.send = AsyncMock()
        self.reports = DailyReports(self.ai, self.settings, self.send)
        self.start = datetime(2026, 11, 18, tzinfo=BEIJING)
        self.end = self.start + timedelta(days=1)

    def add(self, event, group, member, text, offset, name=""):
        self.ai.history.add(str(event), group, member, text, display_name=name,
                            created=(self.start + offset).timestamp())

    def test_member_intel_keeps_old_and_new_target_evidence_in_a_busy_group(self):
        from mcqq.plugins import COMMANDS
        from mcqq.plugins.member_intel import select_evidence
        target = "A" * 32
        rows = [(float(i), "others", "", str(i), "") for i in range(1713)]
        expected = {10, 716, 1699}
        for i in expected:
            rows[i] = (float(i), target, "", str(i), "")
        rows[250] = (250., "others", "", f"<@{target}> 直接提及", "")
        skill = COMMANDS["群友情报"].config["skill"]
        evidence = select_evidence(rows, target, skill)
        self.assertEqual({int(row[0]) for row in evidence if row[1] == target}, expected)
        self.assertIn(rows[250], evidence)
        self.assertIn(rows[11], evidence)
        self.assertNotIn(rows[1000], evidence)
        self.assertLessEqual(len(evidence), 16)

    def test_member_intel_quota_enforces_all_rolling_windows_and_group_reset(self):
        from mcqq.command_quota import rejected_message, reset, take
        from mcqq.plugins import COMMANDS
        name = "群友情报"
        limits = COMMANDS[name].config["command"]["quota"]["limits"]
        db = self.settings["database"]
        timestamp = self.start.timestamp()
        self.assertIsNone(take(db, name, "one", "short", limits, now=timestamp))
        minute = take(db, name, "one", "short", limits, now=timestamp+20)
        self.assertEqual(minute[0][1:], (0, 1, timestamp+60))
        self.assertIn("您的一分钟", rejected_message(minute))
        self.assertIn("五小时限额 93%", rejected_message(minute))
        self.assertIsNone(take(db, name, "one", "short", limits, now=timestamp+60))

        for index in range(15):
            self.assertIsNone(take(db, name, "one", "medium", limits, now=timestamp+index*61))
        five_hours = take(db, name, "one", "medium", limits, now=timestamp+15*61)
        self.assertEqual(five_hours[1][1:], (0, 15, timestamp+18000))

        for index in range(80):
            self.assertIsNone(take(db, name, "one", "long", limits, now=timestamp+index*1210))
        week = take(db, name, "one", "long", limits, now=timestamp+80*1210)
        self.assertEqual(week[2][1:], (0, 80, timestamp+604800))
        self.assertIsNone(take(db, name, "two", "long", limits, now=timestamp+80*1210))
        reset(db, name, "one")
        self.assertIsNone(take(db, name, "one", "long", limits, now=timestamp+80*1210))
        self.assertIsNotNone(take(db, name, "two", "long", limits, now=timestamp+80*1210))

    async def test_warm_then_finalize_uses_last_five_minutes_and_persists_on_send_failure(self):
        for index in range(310):
            self.add(index, "one", "alice", "建城", timedelta(seconds=index), "小明")
        self.add("tail", "one", "bob", "红石钟", timedelta(hours=23, minutes=59), "小明")
        self.add("tomorrow", "one", "alice", "新的一天", timedelta(days=1))
        self.add("other", "two", "eve", "另一群的话题", timedelta(hours=8))
        self.assertEqual(self.reports.groups, ("one",))
        self.assertEqual(self.reports.previous_day_groups(self.start), ())
        self.assertEqual(self.reports.previous_day_groups(self.end), ("one",))

        async def complete(prompt, **kwargs):
            content = prompt[-1]["content"]
            if "红石钟" in content:
                return '[{"title":"红石","detail":"讨论红石时钟","users":["u2","u1"]}]'
            return '[{"title":"建城","detail":"讨论城墙","users":["u1"]}]'

        self.ai.complete = AsyncMock(side_effect=complete)
        with patch("mcqq.group_reports.render", return_value=[b"one-report"]) as render:
            await self.reports.report("one", self.start, self.end - timedelta(minutes=5), warm=True)
            warm_calls = self.ai.complete.await_count
            self.send.side_effect = [RuntimeError("QQ"), None]
            with self.assertRaisesRegex(RuntimeError, "QQ"):
                await self.reports.scheduled("one", self.start, self.end)
            self.assertEqual(self.ai.complete.await_count, warm_calls + 1)
            arguments = render.call_args.args
            self.assertEqual(arguments[5], [("小明 · u1", 310, None), ("小明 · u2", 1, None)])
            self.assertEqual(arguments[6][-1][1][0][2], ["小明 · u2"])
            self.assertEqual(self.ai.history.day("one", self.start.timestamp(), self.end.timestamp()), [])
            self.assertTrue(self.ai.history.recall("one", "红石"))
            await self.reports.scheduled("one", self.start, self.end)
            await self.reports.scheduled("one", self.start, self.end)
            self.assertEqual([call.args[1] for call in self.send.await_args_list],
                             [b"one-report", b"one-report"])
            render.assert_called_once()
        self.assertEqual(len(self.ai.history.day("one", self.end.timestamp(), self.end.timestamp()+1)), 1)
        self.assertEqual(len(self.ai.history.day("two", self.start.timestamp(), self.end.timestamp())), 1)

    async def test_evening_cutoff_counts_boundary_message_in_next_report(self):
        notify = AsyncMock()
        reports = DailyReports(
            self.ai, {**self.settings, "daily_report_time": "23:50"}, self.send, notify=notify,
        )
        end = self.start + timedelta(days=1, hours=23, minutes=50)
        start = end - timedelta(days=1)
        self.assertEqual(reports.period_end(end - timedelta(seconds=1)), start)
        self.assertEqual(reports.period_end(end), end)
        self.add("before", "one", "alice", "Before", end - self.start - timedelta(seconds=1), "Alice")
        self.add("at", "one", "bob", "At cutoff", end - self.start, "Bob")
        self.ai.config["enabled"] = False
        with patch("mcqq.group_reports.render", return_value=[b"report"]) as draw:
            await reports.scheduled("one", start, end)
            await reports.scheduled("one", start, end)
        self.send.assert_awaited_once_with("one", b"report")
        notify.assert_awaited_once_with("one", "今日群聊总结已完成，本次触发为自动触发", translate=False)
        self.assertEqual(draw.call_args.args[5], [("Alice", 1, None)])
        self.assertEqual(draw.call_args.args[6][0][0], "23:50 – 03:50")
        self.assertEqual(draw.call_args.args[6][-1][0], "19:50 – 23:50")
        self.assertTrue(self.ai.history.closed_day("one", end.date().isoformat()))
        self.add("late", "one", "alice", "Before but delivered late", end - self.start - timedelta(seconds=1))
        self.add("boundary", "one", "carol", "Delivered at cutoff", end - self.start)
        self.add("after", "one", "dave", "Delivered after cutoff", end - self.start + timedelta(seconds=1))
        self.assertEqual(self.ai.history.day("one", start.timestamp(), end.timestamp()), [])
        next_rows = self.ai.history.day("one", end.timestamp(), (end + timedelta(days=1)).timestamp())
        self.assertEqual([row[1] for row in next_rows], ["bob", "carol", "dave"])

    def test_external_history_checks_persisted_cutoff_before_writing(self):
        local = self.ai.history
        external = ExternalHistory({}, local)
        external.raw_sql = Mock()
        end = self.start + timedelta(hours=23, minutes=50)
        cutoff = end.timestamp()
        external.stage_day("one", end.date().isoformat(), cutoff, "", [b"report"])
        external.raw_sql.remove_history.assert_called_once_with(cutoff, group="one")

        reopened = ExternalHistory({}, History(local.database, local.image_dir))
        reopened.raw_sql = external.raw_sql
        reopened.add("late", "one", "alice", "Late", created=cutoff - 1)
        reopened.add("new", "one", "bob", "New", created=cutoff)
        reopened.raw_sql.add.assert_called_once_with("new", "one", "bob", "New", None, "", cutoff, "")

    def test_upgrades_legacy_sqlite_report_without_losing_delivery_state(self):
        local = self.ai.history
        path = Path(local.database).with_name("legacy.db")
        day = self.start.date().isoformat()
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE group_ai_daily(group_id TEXT, day TEXT, PRIMARY KEY(group_id,day))")
            db.execute("INSERT INTO group_ai_daily VALUES ('one',?)", (day,))
        db.close()
        history = History(str(path), local.image_dir)
        self.assertEqual(history.staged_report("one", day), (True, []))
        cutoff = (self.start + timedelta(days=1)).timestamp()
        history.add("late", "one", "alice", "Legacy day", created=cutoff - 1)
        history.add("new", "one", "alice", "Next day", created=cutoff)
        self.assertEqual([row[3] for row in history.day("one", cutoff - 2, cutoff + 1)], ["Next day"])

    async def test_manual_downgrade_and_cutoff_render_png(self):
        self.ai.complete = AsyncMock(side_effect=ValueError("bad provider response"))
        self.add("long", "two", "eve", "讨论" * 2000, timedelta(hours=3), "群友小夏")
        self.add("future", "two", "eve", "未来讯息", timedelta(hours=5))
        end = self.start + timedelta(hours=4, minutes=30)
        from mcqq.group_report_image import render
        with patch("mcqq.group_reports.render", wraps=render) as draw:
            images, summary = await self.reports.report("two", self.start, end, manual=True)
        self.assertEqual(summary, "")
        self.assertEqual(draw.call_args.args[2], True)
        self.assertEqual(draw.call_args.args[5], [("群友小夏", 1, None)])
        self.assertEqual(draw.call_args.args[6][0], ("00:00 – 04:00", [], True))
        self.assertEqual(len(self.ai.history.day("two", self.start.timestamp(), end.timestamp())[0][3]), 4000)
        with Image.open(BytesIO(images[0])) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.width, 1280)
        self.send.assert_not_awaited()

    async def test_qq_supplied_avatar_draws_and_missing_avatar_has_placeholder(self):
        avatar = "https://thirdqq.qlogo.cn/sample/100"
        msg = SimpleNamespace(id="avatar", author=SimpleNamespace(nickname="小夏"),
                              raw_data={"author": {"avatar": avatar}})
        await self.ai.capture(msg, "two", "eve", "你好", created=self.start.timestamp())
        self.add("without-avatar", "two", "mori", "下午好", timedelta(minutes=1), "Mori")
        raw = BytesIO()
        Image.new("RGB", (40, 40), "#ff0040").save(raw, format="PNG")
        self.ai.config["enabled"] = False
        with patch("mcqq.group_reports.media.fetch", new_callable=AsyncMock,
                   return_value=(avatar, "image/png", "png", raw.getvalue())) as fetch:
            images, _ = await self.reports.report("two", self.start, self.end)
            fetch.assert_awaited_once()
            self.assertEqual(fetch.await_args.args[1], avatar)
        with Image.open(BytesIO(images[0])) as result:
            self.assertEqual(result.getpixel((517, 500)), (255, 0, 64))
            self.assertNotEqual(result.getpixel((119, 547)), (255, 0, 64))

    async def test_manual_group_authority_applies_to_non_scheduled_group(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = self.settings
        bot.seen = {}
        bot.group_ai = self.ai
        bot.daily_reports = SimpleNamespace(report=AsyncMock(return_value=([b"png"], "")))
        bot.role_for = AsyncMock(side_effect=["member", "admin"])
        bot.reply_group_text = AsyncMock()
        bot.send_group_report_image = AsyncMock()
        message = SimpleNamespace(id="denied", content="/群讯息情报统计", group_openid="two",
                                  author=SimpleNamespace(member_openid="user"), raw_data={})
        await bot.on_group_message_create(message)
        bot.daily_reports.report.assert_not_awaited()
        message.id = "allowed"
        message.content = "<@!test-bot> /群讯息情报统计 试运行"
        await bot.on_group_message_create(message, explicit_at=True)
        await bot.on_group_message_create(message)
        bot.send_group_report_image.assert_awaited_once_with("two", b"png", msg_id="allowed", sequence=1)
        group, start, end = bot.daily_reports.report.await_args.args
        self.assertEqual(group, "two")
        self.assertEqual(start.hour, 0)
        self.assertEqual(start.date(), end.date())
        self.assertEqual(bot.daily_reports.report.await_args.kwargs, {"manual": True})

    async def test_member_intel_routes_as_one_image_and_uses_only_its_groups_evidence(self):
        now = datetime.now(BEIJING)
        settings = dict(self.settings, feature_policy={"groups": {"one": {
            "entertainment": {"schedule": "daily_windows", "windows": []}}}})
        bot = QQBot.__new__(QQBot)
        bot.settings, bot.group_ai, bot.seen = settings, self.ai, {}
        bot.role_for = AsyncMock(return_value="owner")
        bot.send_group_report_image = AsyncMock()
        bot.reply_group_text = AsyncMock()
        member = "A" * 32
        self.ai.history.add("profile-incoming", "one", member, "我在研究红石", display_name="小夏",
                            created=now.timestamp()-0.01)
        self.ai.history.add("other-room", "two", member, "另一群专有内容", created=now.timestamp()-0.01)
        self.ai.history.save_summaries("one", [(member, "历史证据：常聊建城"), ("someone", "别人的私有记忆")])
        message = SimpleNamespace(id="portrait", content=f"/群友情报 <@{member}>", group_openid="one",
                                  author=SimpleNamespace(member_openid="requester"), raw_data={})
        inputs = []

        async def complete(messages, **kwargs):
            inputs.append(json.loads(messages[-1]["content"]))
            if isinstance(inputs[-1], list):
                return '{"notes":"目标明确说自己在研究红石，也聊建城"}'
            return ('{"labels":["红石玩家"],"traits":"爱钻研","interests":"红石","style":"措辞直接",'
                    '"catchphrases":[],"strengths":[{"title":"探索主动","detail":"主动研究红石",'
                    '"evidence":["M01","FAKE"]}],"mbti":"INTP","basis":"爱钻研","summary":"重视动手实践"}')

        self.ai.complete = AsyncMock(side_effect=complete)
        from mcqq.plugins.member_intel import render_portrait
        with patch("mcqq.plugins.member_intel.render_portrait", wraps=render_portrait) as rich_render:
            await bot.on_group_message_create(message)
        self.assertIn("M01", rich_render.call_args.kwargs["strengths"][0][2])
        self.assertNotIn("FAKE", rich_render.call_args.kwargs["strengths"][0][2])
        self.assertEqual(rich_render.call_args.kwargs["summary"], "重视动手实践")
        await bot.on_group_message_create(message, explicit_at=True)
        bot.send_group_report_image.assert_awaited_once()
        room, image = bot.send_group_report_image.await_args.args
        self.assertEqual(room, "one")
        with Image.open(BytesIO(image)) as portrait:
            self.assertEqual(portrait.size, (1280, 1830))
        self.assertEqual(bot.send_group_report_image.await_args.kwargs["sequence"], 2)
        self.assertEqual(bot.reply_group_text.await_args.kwargs["sequence"], 1)
        self.assertIn("我在研究红石", repr(inputs))
        self.assertIn("常聊建城", repr(inputs))
        self.assertNotIn("另一群专有内容", repr(inputs))
        self.assertNotIn("别人的私有记忆", repr(inputs))

        message.id = "portrait-cache"
        await bot.on_group_message_create(message)
        self.assertEqual(self.ai.complete.await_count, 1)
        self.assertEqual(bot.send_group_report_image.await_count, 2)

        message.id = "portrait-llm-closed"
        with patch.object(self.ai.feature_policy, "check", return_value={"allowed": False}), \
                patch("mcqq.plugins.member_intel.render_portrait", wraps=render_portrait) as closed_render:
            await bot.on_group_message_create(message)
        self.assertTrue(closed_render.call_args.kwargs["stats_only"])
        self.assertEqual(self.ai.complete.await_count, 1)

        settings["plugins"] = {"member_intel": {"skill": {"cache_ttl_seconds": 0}}}
        self.ai.complete = AsyncMock(side_effect=TimeoutError)
        message.id = "portrait-fallback"
        with patch("mcqq.plugins.member_intel.render_portrait", wraps=render_portrait) as render:
            await bot.on_group_message_create(message)
        self.assertTrue(render.call_args.kwargs["stats_only"])
        self.assertEqual(bot.send_group_report_image.await_count, 4)
        self.assertEqual(bot.reply_group_text.await_count, 4)
        self.assertTrue(all("已提交到队列" in call.args[1] for call in bot.reply_group_text.await_args_list))

    async def test_group_member_quota_rejects_before_model_or_image_and_admin_resets(self):
        bot = QQBot.__new__(QQBot)
        bot.settings, bot.group_ai, bot.seen = self.settings, self.ai, {}
        bot.role_for = AsyncMock(return_value="member")
        bot.send_group_report_image = AsyncMock()
        bot.reply_group_text = AsyncMock()
        member = "A" * 32
        message = SimpleNamespace(id="first", content=f"/群友情报 <@{member}>", group_openid="one",
                                  author=SimpleNamespace(member_openid="requester"), raw_data={})
        with patch("mcqq.bot.match_group_command", wraps=None) as matcher:
            from dataclasses import replace
            from mcqq.plugins import match_group_command
            command, argument = match_group_command(message.content)
            handler = AsyncMock(return_value=b"mock png")
            command = replace(command, handler=handler)
            matcher.return_value = command, argument
            await bot.on_group_message_create(message)
            message.id = "second"
            await bot.on_group_message_create(message)
            handler.assert_awaited_once()
            bot.send_group_report_image.assert_awaited_once()
            self.assertIn("您的一分钟限额不足", bot.reply_group_text.await_args.args[1])
            matcher.return_value = command, "重置"
            message.id = "denied-reset"
            message.content = "/群友情报 重置"
            await bot.on_group_message_create(message)
            self.assertIn("只有 Bot 主人或管理员", bot.reply_group_text.await_args.args[1])
            bot.role_for.return_value = "admin"
            message.id = "allowed-reset"
            await bot.on_group_message_create(message)
            self.assertIn("已重置本群", bot.reply_group_text.await_args.args[1])
            matcher.return_value = command, argument
            bot.role_for.return_value = "member"
            message.id = "after-reset"
            message.content = f"/群友情报 <@{member}>"
            await bot.on_group_message_create(message)
            self.assertEqual(handler.await_count, 2)
