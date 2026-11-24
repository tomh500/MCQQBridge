import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from mcqq.group_ai import GroupAI, History
from mcqq.bot import QQBot
from mcqq.feature_policy import ZONE


class GroupAITests(unittest.IsolatedAsyncioTestCase):
    async def test_full_history_and_memory_recall(self):
        with tempfile.TemporaryDirectory() as root:
            history = History(str(Path(root) / "bot.db"), Path(root) / "images")
            for index in range(305):
                history.add(str(index), "a", "person", f"讯息{index}")
            self.assertEqual(len(history.all_recent("a")), 305)
            self.assertEqual(history.all_recent("a")[0][1], "讯息0")
            self.assertEqual(len(history.recent("a")), 30)
            history.add("other", "b", "person", "另一群")
            self.assertEqual(len(history.all_recent("b")), 1)
            from mcqq.group_ai import vector
            history.remember("a", "小明喜欢建造城堡", vector("小明喜欢建造城堡"))
            self.assertEqual(history.recall("a", "城堡"), ["小明喜欢建造城堡"])
            self.assertEqual(history.recall("b", "城堡"), [])
            history.add("named", "a", "person", "我喜欢美美", display_name="小樱")
            history.remember("a", "小樱喜欢美美", vector("美美"), "person")
            self.assertIn("小樱喜欢美美", history.recall("a", "小樱最近喜欢谁？"))
            self.assertEqual(history.recall("b", "小樱最近喜欢谁？"), [])

    async def test_only_explicit_mention_talks_and_commands_require_slash(self):
        with tempfile.TemporaryDirectory() as root:
            config = Path(root) / "ai.yml"
            config.write_text("enabled: true\napi_key: test\nbase_url: https://example.invalid\nmodel: test\n", encoding="utf-8")
            bot = QQBot.__new__(QQBot)
            bot_id = "b" * 32
            bot.settings = {"database": str(Path(root) / "bot.db"), "group_ai_config": str(config),
                            "group_ai_mention_openid": bot_id.upper(),
                            "allowed_groups": ["group"], "chat_bridge": {"command_groups": ["group"]}}
            bot.group_ai = GroupAI(bot.settings)
            bot.group_ai.reply = AsyncMock(return_value="回应")
            bot.group_ai.capture = AsyncMock()
            bot.seen = {}
            bot.relay_group = AsyncMock()
            bot.reply_group_text = AsyncMock()
            bot.group_response = AsyncMock(return_value="命令回执")
            def msg(content, index):
                return SimpleNamespace(content=content, id=str(index), group_openid="group",
                    author=SimpleNamespace(member_openid="person", bot=False), attachments=[], raw_data={}, reply=AsyncMock())
            await bot.on_group_message_create(msg("你好", 1))
            bot.group_ai.reply.assert_not_awaited()
            bot.group_response.assert_not_awaited()
            await bot.on_group_message_create(msg("<@!another-member> 你好", 2))
            bot.group_ai.reply.assert_not_awaited()
            await bot.on_group_at_message_create(msg("<@!bot> 你好", 3))
            bot.group_ai.reply.assert_awaited_once()
            await bot.on_group_message_create(msg("<@!bot> 另一个话题", 4))
            await bot.on_group_at_message_create(msg("<@!bot> 另一个话题", 4))
            self.assertEqual(bot.group_ai.reply.await_count, 2)
            await bot.on_group_message_create(msg("<@!bot> /帮助", 5))
            bot.group_response.assert_awaited_once()
            self.assertEqual(bot.group_ai.reply.await_count, 2)

            other_id = "a" * 32
            other = msg(f"<@{other_id}> 你好", 6)
            await bot.on_group_message_create(other)
            await bot.on_group_message_create(msg("<@all> 你好", 7))
            self.assertEqual(bot.group_ai.reply.await_count, 2)

            mention = msg(f"<@!{bot_id}> 你好", 8)
            mention.raw_data = {"mentions": [{"member_openid": bot_id.upper(), "bot": True}]}
            await bot.on_group_message_create(mention)
            bot.group_ai.reply.assert_awaited_with("group", "你好", "person")
            await bot.on_group_at_message_create(msg("你好", 8))
            self.assertEqual(bot.group_ai.reply.await_count, 3)

            await bot.on_group_at_message_create(msg("又见面了", 9))
            await bot.on_group_message_create(msg(f"<@{bot_id}> 又见面了", 9))
            self.assertEqual(bot.group_ai.reply.await_count, 4)

    async def test_mentions_take_one_llm_slot_per_model_request(self):
        with tempfile.TemporaryDirectory() as root:
            bot = QQBot.__new__(QQBot)
            bot.settings = {
                "database": str(Path(root) / "bot.db"),
                "allowed_groups": ["group"],
                "feature_policy": {"groups": {"group": {"llm": {
                    "schedule": "daily_windows", "windows": [["00:00", "24:00"]],
                    "limit_per_minute": 2,
                }}}},
            }
            bot.seen = {}
            bot.reply_group_text = AsyncMock()
            bot.group_ai = ai = GroupAI(bot.settings)
            ai.config = {"enabled": True, "api_key": "test", "base_url": "https://example.invalid", "model": "test"}
            ai.complete = AsyncMock(return_value="回应")
            now = datetime(2026, 11, 24, 12, tzinfo=ZONE)
            bot.feature_rules().clock = ai.feature_policy.clock = lambda: now

            def message(event):
                return SimpleNamespace(content="你好", id=event, group_openid="group", attachments=[],
                                       author=SimpleNamespace(member_openid="person", bot=False), raw_data={})

            ai.config["enabled"] = False
            await bot.on_group_at_message_create(message("disabled"))
            ai.complete.assert_not_awaited()
            ai.config["enabled"] = True
            await bot.on_group_at_message_create(message("first"))
            await bot.on_group_at_message_create(message("first"))
            await bot.on_group_at_message_create(message("second"))
            await bot.on_group_at_message_create(message("rate-limited"))
            self.assertEqual(ai.complete.await_count, 2)
            self.assertEqual([call.args[1] for call in bot.reply_group_text.await_args_list],
                             ["群对话尚未设定模型服务。", "回应", "回应", "维护中暂不可用。"])
            with ai.history.connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM feature_rate_events").fetchone(), (2,))

    async def test_vectorization_saves_per_member_memory_and_name_lookup(self):
        with tempfile.TemporaryDirectory() as root:
            config = Path(root) / "ai.yml"
            config.write_text("enabled: true\napi_key: test\nbase_url: https://example.invalid\nmodel: test\n", encoding="utf-8")
            ai = GroupAI({"database": str(Path(root) / "bot.db"), "group_ai_config": str(config)})
            ai.history.add("one", "group", "member-1", "我喜欢种花", display_name="小樱")
            ai.history.add("two", "group", "member-2", "我喜欢造城堡", display_name="小明")
            ai.complete = AsyncMock(return_value='{"group":"大家在讨论兴趣","users":{"u1":"喜欢种花","u2":"喜欢造城堡"}}')
            result = await ai.summarize("group")
            self.assertIn("2 位群友", result)
            memories = ai.history.recall("group", "小樱喜欢什么？")
            self.assertTrue(any("小樱：喜欢种花" in item for item in memories))
            self.assertFalse(any("小明：" in item for item in memories))
            self.assertEqual(ai.history.recall("other-group", "小樱喜欢什么？"), [])

    async def test_full_compression_sends_oldest_longest_and_newest_rows_and_keeps_memory(self):
        with tempfile.TemporaryDirectory() as root:
            ai = GroupAI({"database": str(Path(root) / "bot.db")})
            ai.config = {"enabled": True, "base_url": "https://example.invalid", "model": "test", "api_key": "test"}
            original = [f"讯息-{index}" for index in range(322)]
            original[0] += "历史正文" * 700
            for index, value in enumerate(original):
                ai.history.add(str(index), "group", "member", value, created=index)
            seen = []

            async def complete(messages, **kwargs):
                seen.extend(text for _, text in json.loads(messages[-1]["content"]))
                return '{"group":"持续讨论历史","users":{"u1":"喜欢历史"}}'

            ai.complete = AsyncMock(side_effect=complete)
            self.assertIn("322 条", await ai.summarize("group"))
            self.assertEqual("".join(seen), "".join(original))
            self.assertEqual(len(ai.history.all_recent("group")), 322)
            ai.history.save_summaries("group", [("member", f"资料第{index}条") for index in range(110)])
            self.assertEqual(len(ai.history.member_memories("group", "member")), 111)
