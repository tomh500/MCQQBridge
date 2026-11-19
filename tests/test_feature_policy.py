import concurrent.futures
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from mcqq.bot import QQBot
from mcqq.feature_policy import FeaturePolicy, next_open, state
from mcqq.group_ai import GroupAI

TZ = ZoneInfo('Asia/Shanghai')
SCHOOL = {'schedule': 'china_school_hours', 'closed_dates': ['06-04']}
ALWAYS = {'schedule': 'always', 'closed_dates': ['06-04']}


def at(month, day, hour, minute=0, year=2026):
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


class ScheduleTests(unittest.TestCase):
    def test_weekend_and_holiday_windows_and_boundaries(self):
        for when in (at(11,21,0), at(11,21,6,59), at(11,21,14), at(11,21,16,59), at(6,19,14), at(6,9,14,year=2027)):
            self.assertTrue(state(SCHOOL, when)[0], when)
        for when in (at(11,21,7), at(11,21,13,59), at(11,21,17), at(6,19,9), at(6,9,9,year=2027)):
            self.assertFalse(state(SCHOOL, when)[0], when)
        self.assertEqual(next_open(SCHOOL, at(11,21,7)), at(11,21,14))

    def test_school_ranges_weekdays_and_june_four(self):
        for when in (at(1,10,9), at(2,14,9), at(7,15,9), at(8,20,9)):
            self.assertFalse(state(SCHOOL, when)[0], when)
        self.assertEqual(state(SCHOOL, at(11,17,1)), (True, 10))
        self.assertEqual(state(SCHOOL, at(11,17,7)), (True, 3))
        self.assertEqual(state(SCHOOL, at(11,17,14)), (True, 10))
        self.assertEqual(state(SCHOOL, at(11,17,17)), (True, 3))
        for hour in (0, 6, 14, 23):
            self.assertFalse(state(SCHOOL, at(6,4,hour))[0])
            self.assertFalse(state(ALWAYS, at(6,4,hour))[0])
        self.assertEqual(next_open(SCHOOL, at(6,4,14)), at(6,5,0))

    def test_per_group_sliding_rate_and_persistence(self):
        with tempfile.TemporaryDirectory() as temp:
            current = [at(11,17,8)]
            cfg = {'database': str(Path(temp)/'db'), 'feature_policy': {'groups': {'one': {'entertainment': SCHOOL}}}}
            p = FeaturePolicy(cfg, clock=lambda: current[0])
            for _ in range(3): self.assertTrue(p.check('one','entertainment')['allowed'])
            self.assertEqual(p.check('one','entertainment')['reason'], 'rate')
            self.assertTrue(p.check('other','entertainment')['allowed'])
            self.assertEqual(FeaturePolicy(cfg, clock=lambda: current[0]).check('one','entertainment')['reason'], 'rate')
            current[0] += timedelta(seconds=60)
            self.assertTrue(p.check('one','entertainment')['allowed'])
            current[0] = at(11,17,14)
            for _ in range(10): self.assertTrue(p.check('one','entertainment')['allowed'])
            self.assertEqual(p.check('one','entertainment')['reason'], 'rate')

    def test_custom_feature_and_window(self):
        with tempfile.TemporaryDirectory() as temp:
            current = [at(11,17,12)]
            cfg = {'database':str(Path(temp)/'db'), 'feature_policy':{
                'categories':{'games':{'commands':['小游戏'], 'button_prefixes':['game:']}},
                'groups':{'one':{'games':{'schedule':'daily_windows','windows':[['18:30','20:15']], 'limit_per_minute':2}}}}}
            p = FeaturePolicy(cfg, clock=lambda:current[0])
            self.assertEqual(p.category_for('/小游戏 继续'), 'games')
            self.assertEqual(p.category_for('game:start', button=True), 'games')
            self.assertEqual(p.check('one','games')['next'], at(11,17,18,30))
            current[0] = at(11,17,18,30)
            self.assertTrue(p.check('one','games')['allowed'])
            self.assertTrue(p.check('one','games')['allowed'])
            self.assertEqual(p.check('one','games')['reason'], 'rate')

    def test_concurrent_group_limit(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = {'database': str(Path(temp)/'db'), 'feature_policy': {'groups': {'one': {'entertainment': SCHOOL}}}}
            p = FeaturePolicy(cfg, clock=lambda: at(11,17,8))
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: p.check('one','entertainment')['allowed'], range(20)))
            self.assertEqual(sum(results), 3)


class BotPolicyTests(unittest.IsolatedAsyncioTestCase):
    async def test_llm_rechecks_after_waiting_for_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp)/'model.yml'
            config.write_text('enabled: true\napi_key: sample\nbase_url: https://example.com\nmodel: sample\n', encoding='utf-8')
            settings = {'database':str(Path(temp)/'db'), 'group_ai_config':str(config), 'feature_policy':{'groups':{'one':{'llm':ALWAYS}}}}
            ai = GroupAI(settings)
            ai.feature_policy = FeaturePolicy(settings, clock=lambda: at(6,4,14))
            ai.history.add('event','one','user','你好')
            ai.complete = AsyncMock()
            self.assertEqual(await ai.reply('one','你好','user'), '维护中暂不可用。')
            self.assertEqual(await ai.summarize('one'), '维护中暂不可用。')
            ai.complete.assert_not_awaited()

    async def test_rate_limit_is_silent_before_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            bot = QQBot.__new__(QQBot)
            bot.settings = {'app_id':'app', 'database':str(Path(temp)/'db'), 'allowed_groups':['one'],
                            'chat_bridge':{'command_groups':['one']}, 'feature_policy':{'groups':{'one':{'entertainment':SCHOOL}}}}
            bot._feature_policy = FeaturePolicy(bot.settings, clock=lambda: at(11,17,8))
            bot.seen = {}
            bot.group_ai = None
            bot.daily_waifu_reply = AsyncMock()
            bot.reply_group_text = AsyncMock()
            msg = SimpleNamespace(id='x',group_openid='one',author=SimpleNamespace(member_openid='user',bot=False),content='/今日老婆',attachments=[])
            for i in range(4):
                msg.id = str(i)
                await bot.on_group_message_create(msg)
            self.assertEqual(bot.daily_waifu_reply.await_count, 3)
            bot.reply_group_text.assert_not_awaited()

    async def test_closed_command_and_llm_do_not_call_services(self):
        with tempfile.TemporaryDirectory() as temp:
            bot = QQBot.__new__(QQBot)
            bot.settings = {'app_id':'app', 'database':str(Path(temp)/'db'), 'allowed_groups':['one'],
                            'chat_bridge':{'command_groups':['one']}, 'feature_policy':{'groups':{'one':{'entertainment':SCHOOL,'llm':ALWAYS}}}}
            bot._feature_policy = FeaturePolicy(bot.settings, clock=lambda: at(6,4,14))
            bot.seen = {}
            bot.call_service = AsyncMock()
            bot.reply_group_text = AsyncMock()
            bot.group_ai = SimpleNamespace(check=lambda x:x, capture=AsyncMock(), reply=AsyncMock(), summarize=AsyncMock())
            author = SimpleNamespace(member_openid='user',bot=False)
            msg = SimpleNamespace(id='one',group_openid='one',author=author,content='/今日老婆',attachments=[])
            await bot.on_group_message_create(msg)
            bot.call_service.assert_not_awaited()
            self.assertIn('不可用', bot.reply_group_text.await_args.args[1])
            msg.id, msg.content = 'two', '你好'
            await bot.on_group_message_create(msg, explicit_at=True)
            bot.group_ai.reply.assert_not_awaited()
            self.assertEqual(bot.group_ai.capture.await_count, 2)
            self.assertEqual(bot.reply_group_text.await_args.args[1], '维护中暂不可用。')

    async def test_closed_button_does_not_exchange(self):
        bot = QQBot.__new__(QQBot)
        bot.settings = {'bot_token':'x'*40, 'feature_policy':{'groups':{'one':{'entertainment':SCHOOL}}}}
        bot._feature_policy = FeaturePolicy(bot.settings, clock=lambda: at(6,4,14))
        bot.api = SimpleNamespace(on_interaction_result=AsyncMock(),post_group_message=AsyncMock())
        bot.call_service = AsyncMock()
        event = SimpleNamespace(id='evt',group_openid='one',group_member_openid='member', data=SimpleNamespace(resolved=SimpleNamespace(button_data='waifu_swap:any')))
        await bot.on_interaction_create(event)
        bot.call_service.assert_not_awaited()
        bot.api.on_interaction_result.assert_awaited_once()
        bot.api.post_group_message.assert_awaited_once()
