"""Integration tests: use only an explicitly supplied disposable MySQL database."""
import concurrent.futures
import json
import os
import unittest
from unittest.mock import patch

from mcqq.waifu_economy import WaifuEconomy
from mcqq.waifu_preferences import MAX_POINTS


@unittest.skipUnless(os.environ.get('MCQQ_TEST_MYSQL_SOCKET'), 'requires disposable MySQL')
class EconomyMySQLTests(unittest.TestCase):
    def setUp(self):
        import pymysql
        class Storage:
            pass
        self.s = Storage()
        self.s.pymysql = pymysql
        self.s.mysql = {'unix_socket': os.environ['MCQQ_TEST_MYSQL_SOCKET'], 'user': 'root', 'database': 'mcqq_test', 'charset': 'utf8mb4', 'autocommit': True}
        self.entries = [dict(name=n, aliases=[n], source_url='https://bgm.tv/character/'+str(i), image_url='https://lain.bgm.tv/pic/crt/l/'+str(i), work='work', features=['作品:work', '性格:'+n]) for i,n in enumerate(['A','B'], 1)]
        self.s.entries = lambda: self.entries
        self.s.choose = lambda exclude_url=None: next(e for e in self.entries if e['image_url'] != exclude_url)
        self.s.result = lambda r, new=False, exchanged=False: dict(name=r[0], image_url=r[1], source_url=r[2], swapped=bool(r[3]), draw_token=r[4], new=new, exchanged=exchanged)
        self.e = WaifuEconomy(self.s)
        with pymysql.connect(**self.s.mysql) as c:
            with c.cursor() as q:
                for name in ('waifu_operations','waifu_wishes','waifu_rewards','waifu_accounts','daily_waifu_draws'):
                    q.execute('DELETE FROM ' + name)

    def test_reward_once_even_after_reset_and_concurrent_requests(self):
        with patch('mcqq.waifu_economy.secrets.randbelow', return_value=0):
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                values = list(pool.map(lambda _: self.e.today('u','2026-11-17'), range(4)))
        self.assertEqual(sum(v['new'] for v in values), 1)
        self.assertEqual(self.e.points('u','query',0,'query')['points'], 1)
        with self.s.pymysql.connect(**self.s.mysql) as c:
            with c.cursor() as q: q.execute('DELETE FROM daily_waifu_draws')
        self.e.today('u','2026-11-17')
        self.assertEqual(self.e.points('u','query',0,'query')['points'], 1)

    def test_points_clamped_and_event_replayed(self):
        self.assertEqual(self.e.points('u','set',MAX_POINTS,'one')['points'], MAX_POINTS)
        self.assertEqual(self.e.points('u','add',10,'two')['points'], MAX_POINTS)
        self.assertEqual(self.e.points('u','add',-7,'three')['points'], MAX_POINTS-7)
        self.assertEqual(self.e.points('u','add',-7,'three')['points'], MAX_POINTS-7)
        self.assertEqual(self.e.points('u','add',-MAX_POINTS,'four')['points'], 0)

    def test_wish_uses_shared_chance_and_charges_once(self):
        self.e.today('u','2026-11-17')
        self.e.points('u','set',100,'seed')
        with patch('mcqq.waifu_economy.secrets.randbelow', return_value=0):
            result = self.e.wish('u','2026-11-17','A','wish1')
            retry = self.e.wish('u','2026-11-17','A','wish1')
            denied = self.e.wish('u','2026-11-17','A','wish2')
        self.assertEqual(result['source_url'], self.entries[0]['source_url'])
        self.assertEqual(retry, result)
        self.assertIn('error', denied)
        self.assertEqual(self.e.points('u','query',0,'q')['points'], 84)

    def test_insufficient_wish_does_not_consume_shared_chance(self):
        self.e.today('u','2026-11-17')
        self.e.points('u','set',15,'seed')
        self.assertIn('error', self.e.wish('u','2026-11-17','A','w1'))
        with self.s.pymysql.connect(**self.s.mysql) as c:
            with c.cursor() as q:
                q.execute('SELECT swapped FROM daily_waifu_draws WHERE subject=%s AND day=%s', ('u','2026-11-17'))
                self.assertEqual(q.fetchone()[0], 0)
        self.assertEqual(self.e.points('u','query',0,'q')['points'], 15)

    def test_swap_invalidates_old_confirmation_and_blocks_wish(self):
        old = self.e.today('u','2026-11-17')
        self.e.points('u','set',50,'seed')
        swapped = self.e.swap('u', '2026-11-17', old['draw_token'])
        self.assertNotEqual(old['draw_token'], swapped['draw_token'])
        self.assertIn('error', self.e.accept('u', '2026-11-17', old['draw_token'], 'old'))
        self.assertIn('error', self.e.wish('u', '2026-11-17', 'A', 'wish'))
        self.assertTrue(self.e.accept('u', '2026-11-17', swapped['draw_token'], 'new')['accepted'])

    def test_simultaneous_swap_and_wish_share_one_chance(self):
        draw = self.e.today('u','2026-11-17')
        self.e.points('u','set',100,'seed')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            future_swap = pool.submit(self.e.swap, 'u', '2026-11-17', draw['draw_token'])
            future_wish = pool.submit(self.e.wish, 'u', '2026-11-17', 'A', 'wish')
            swapped, wished = future_swap.result(), future_wish.result()
        if 'error' in wished:
            self.assertTrue(swapped.get('exchanged'))
            self.assertEqual(self.e.points('u','query',0,'q')['points'], 100)
        else:
            self.assertFalse(swapped.get('exchanged', False))
            self.assertEqual(self.e.points('u','query',0,'q')['points'], 84)

    def test_confirm_locks_even_with_no_points(self):
        draw = self.e.today('u','2026-11-17')
        self.e.points('u','set',0,'zero')
        self.assertTrue(self.e.accept('u','2026-11-17',draw['draw_token'],'accept')['accepted'])
        self.assertIn('error', self.e.wish('u','2026-11-17','A','wish'))
        self.assertEqual(self.e.points('u','query',0,'q')['points'], 0)

    def test_wish_pity_increases_then_resets(self):
        self.e.today('u','2026-11-17')
        self.e.points('u','set',100,'seed')
        with patch('mcqq.waifu_economy.secrets.randbelow', return_value=50):
            missed = self.e.wish('u','2026-11-17','A','w1')
            self.e.today('u','2026-11-18')
            won = self.e.wish('u','2026-11-18','A','w2')
        self.assertEqual(missed['name'], 'B')
        self.assertEqual(won['name'], 'A')
        with self.s.pymysql.connect(**self.s.mysql) as c:
            with c.cursor() as q:
                q.execute('SELECT failures FROM waifu_wishes WHERE subject=%s', ('u',))
                self.assertEqual(q.fetchone()[0], 0)

    def test_confirmation_trains_only_once(self):
        draw = self.e.today('u','2026-11-17')
        self.e.points('u','set',10,'seed')
        self.e.accept('u','2026-11-17',draw['draw_token'],'accept1')
        self.e.accept('u','2026-11-17',draw['draw_token'],'accept2')
        self.assertEqual(self.e.points('u','query',0,'q')['points'], 9)
        with self.s.pymysql.connect(**self.s.mysql) as c:
            with c.cursor() as q:
                q.execute('SELECT preference FROM waifu_accounts WHERE subject=%s', ('u',))
                self.assertEqual(json.loads(q.fetchone()[0])['_confirmations'], 1)
