import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from mcqq.group_ai import GroupAI, History
from mcqq.bot import QQBot


class GroupAITests(unittest.IsolatedAsyncioTestCase):
    async def test_history_bounded_and_memory_recall(self):
        with tempfile.TemporaryDirectory() as root:
            history = History(str(Path(root) / "bot.db"), Path(root) / "images")
            for index in range(305):
                history.add(str(index), "a", "person", f"讯息{index}")
            self.assertEqual(len(history.all_recent("a")), 300)
            self.assertEqual(history.all_recent("a")[0][1], "讯息5")
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
            bot.settings = {"database": str(Path(root) / "bot.db"), "group_ai_config": str(config),
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
