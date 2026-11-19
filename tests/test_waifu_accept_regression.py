"""Exercise the reset/confirmation lifecycle without a MySQL server."""
import sqlite3
import unittest
from types import SimpleNamespace

from mcqq.daily_waifu import DailyWaifuStorage
from mcqq.waifu_economy import WaifuEconomy


class Cursor:
    def __init__(self, connection):
        self.cursor = connection.cursor()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, sql, params=()):
        sql = sql.replace('%s', '?').replace(' FOR UPDATE', '')
        sql = sql.replace('INSERT IGNORE', 'INSERT OR IGNORE')
        sql = sql.replace('INSERT INTO waifu_accounts', 'INSERT OR IGNORE INTO waifu_accounts')
        sql = sql.replace(' ON DUPLICATE KEY UPDATE subject=VALUES(subject)', '')
        return self.cursor.execute(sql, params)

    def fetchone(self):
        return self.cursor.fetchone()

    @property
    def rowcount(self):
        return self.cursor.rowcount


class Connection:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def begin(self):
        self.db.execute('BEGIN')

    def cursor(self):
        return Cursor(self.db)

    def commit(self):
        self.db.commit()

    def rollback(self):
        self.db.rollback()


class AcceptAfterResetTests(unittest.TestCase):
    def test_wish_before_first_draw_and_insufficient_points(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript('''
            CREATE TABLE waifu_accounts (subject TEXT PRIMARY KEY, points INTEGER, preference TEXT);
            CREATE TABLE waifu_rewards (subject TEXT, day TEXT, UNIQUE(subject, day));
            CREATE TABLE waifu_operations (event_id TEXT PRIMARY KEY, subject TEXT, kind TEXT, result TEXT);
            CREATE TABLE waifu_wishes (subject TEXT, source_url TEXT, failures INTEGER, UNIQUE(subject, source_url));
            CREATE TABLE daily_waifu_draws (subject TEXT, day TEXT, name TEXT, image_url TEXT,
                source_url TEXT, swapped INTEGER DEFAULT 0, draw_token TEXT, UNIQUE(subject, day));
        ''')
        entries = [dict(name=n, aliases=[], source_url=n, image_url=n, features=[]) for n in ('A', 'B')]
        storage = SimpleNamespace(mysql={}, pymysql=SimpleNamespace(connect=lambda **kw: Connection(db)),
                                  entries=lambda: entries,
                                  result=lambda row, new=False, exchanged=False: dict(
                                      name=row[0], source_url=row[2], swapped=bool(row[3]),
                                      draw_token=row[4], new=new, exchanged=exchanged))
        economy = WaifuEconomy(storage)
        self.assertIn('积分不足', economy.wish('u', '2026-11-17', 'A', 'poor')['error'])
        self.assertIsNone(db.execute('SELECT 1 FROM daily_waifu_draws').fetchone())
        economy.points('u', 'set', 16, 'seed')
        result = economy.wish('u', '2026-11-17', 'A', 'wish')
        self.assertTrue(result['swapped'])
        self.assertEqual(economy.wish('u', '2026-11-17', 'A', 'wish'), result)
        self.assertEqual(economy.points('u', 'query', 0, 'query')['points'], 0)
        self.assertEqual(economy.today('u', '2026-11-17')['source_url'], result['source_url'])

    def test_replacement_is_locked_without_training_twice(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript('''
            CREATE TABLE waifu_accounts (subject TEXT PRIMARY KEY, points INTEGER, preference TEXT);
            CREATE TABLE waifu_rewards (subject TEXT, day TEXT, UNIQUE(subject, day));
            CREATE TABLE waifu_operations (event_id TEXT PRIMARY KEY, subject TEXT, kind TEXT, result TEXT);
            CREATE TABLE daily_waifu_draws (subject TEXT, day TEXT, name TEXT, image_url TEXT,
                source_url TEXT, swapped INTEGER DEFAULT 0, draw_token TEXT, UNIQUE(subject, day));
            CREATE TABLE daily_waifu_resets (event TEXT PRIMARY KEY, day TEXT);
        ''')
        entries = [dict(name=n, aliases=[n], source_url='source' + n,
                        image_url='image' + n, work='work', features=['trait:' + n])
                   for n in ('A', 'B')]
        storage = SimpleNamespace(mysql={}, pymysql=SimpleNamespace(connect=lambda **kw: Connection(db)),
                                  entries=lambda: entries,
                                  result=lambda row, new=False, exchanged=False: dict(
                                      name=row[0], source_url=row[2], swapped=bool(row[3]),
                                      draw_token=row[4], new=new, exchanged=exchanged))
        economy = WaifuEconomy(storage)
        day = '2026-11-17'
        first = economy.today('u', day)
        economy.points('u', 'set', 50, 'seed')
        self.assertTrue(economy.accept('u', day, first['draw_token'], 'accept1')['accepted'])
        self.assertTrue(DailyWaifuStorage.reset_all(storage, day, 'reset')['reset'])
        replacement = economy.today('u', day)
        self.assertNotEqual(first['draw_token'], replacement['draw_token'])
        self.assertIn('error', economy.accept('u', day, first['draw_token'], 'stale'))
        self.assertTrue(economy.accept('u', day, replacement['draw_token'], 'accept2')['accepted'])
        self.assertFalse(economy.swap('u', day, replacement['draw_token'])['exchanged'])
        self.assertIn('error', economy.wish('u', day, 'A', 'wish'))
        self.assertEqual(economy.points('u', 'query', 0, 'q')['points'], 49)
        import json
        preference = json.loads(db.execute('SELECT preference FROM waifu_accounts').fetchone()[0])
        self.assertEqual(preference['_confirmations'], 1)
