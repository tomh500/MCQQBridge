"""Opt-in integration tests. Supply a pre-initialized disposable MySQL database."""
from datetime import datetime, timedelta
import os
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4

from mcqq.command_quota import reset_configured, take_configured, take
from mcqq.config import read_mapping
from mcqq.group_ai import GroupAI, History, vector
from mcqq.group_reports import BEIJING, midnight
from mcqq.migrate_group_storage import migrate
from mcqq.command_quota import mysql_options


@unittest.skipUnless(os.environ.get("MCQQ_GROUP_MYSQL_TEST_CONFIG"), "requires explicit disposable MySQL config")
class GroupStorageMySQLTests(unittest.TestCase):
    def setUp(self):
        database = read_mapping(os.environ["MCQQ_GROUP_MYSQL_TEST_CONFIG"])
        if not database["database"].startswith("mcqq_group_test_"):
            self.fail("Use a database explicitly reserved for group storage tests")
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.path = Path(scratch.name)
        self.settings = {
            "database": str(self.path / "unused.db"),
            "group_ai_storage": {
                "history": "mysql", "memory": "mysql", "reports": "mysql", "cache": "mysql",
                "quota": "mysql", "mysql": database,
            },
        }
        self.ai = GroupAI(self.settings)
        self.history = self.ai.history
        self.addCleanup(self.history.close)
        self.group = uuid4().hex
        self.limits = [{"label": "一分钟", "seconds": 60, "max_requests": 1},
                       {"label": "五小时", "seconds": 18000, "max_requests": 15}]

    def test_full_mysql_recovers_reports_and_keeps_no_sqlite_group_data(self):
        h, group = self.history, self.group
        now = datetime.now(BEIJING)
        start = midnight(now)
        day = start.date().isoformat()
        created = start.timestamp() + 10
        event = group + "_picture"
        h.add(event, group, "member", "第一条", display_name="测试成员", created=created)
        h.add(event, group, "member", "重复事件不得覆盖", created=created)
        h.add(group + "_archived", group, "member", "第二条", display_name="稍晚的名称", created=created+2)
        h.add(group + "_older", group, "member", "更早收到", display_name="旧名称", created=created-2)
        other = uuid4().hex
        h.add(group + "_other", other, "member", "另一群", created=created)
        h.attach_image(event, b"\xff\x00attachment\xfe")
        self.assertEqual(h.profile_name(group, "member"), "稍晚的名称")
        self.assertEqual(h.raw_sql.rows("SELECT data FROM mcqq_group_ai_attachment WHERE event_id=%s", (event,)),
                         [(b"\xff\x00attachment\xfe",)])
        self.assertEqual([row[3] for row in h.day(group, created-3, created+3)],
                         ["更早收到", "第一条", "第二条"])
        h.save_summaries(group, [("member", "喜欢红石"), ("member", "喜欢红石")])
        self.assertIn("喜欢红石", h.recall(group, "红石", "member"))
        self.assertEqual(h.previous_report_groups((group,), day), ())
        tomorrow = (start + timedelta(days=1)).date().isoformat()
        self.assertEqual(h.previous_report_groups((group,), tomorrow), (group,))
        h.stage_day(group, day, (start+timedelta(days=1)).timestamp(), "群库存档", [b"\xff\x00image"])
        self.assertEqual(h.staged_report(group, day), (True, [(1, b"\xff\x00image")]))
        self.assertEqual(h.day(group, created-3, created+3), [])
        self.assertTrue(h.day(other, created-3, created+3))
        self.assertTrue(h.recall(group, "群库存档"))
        self.assertEqual(h.raw_sql.rows("SELECT data FROM mcqq_group_ai_attachment WHERE event_id=%s", (event,)), [])
        h.acknowledge_report(group, day)
        self.assertEqual(h.staged_report(group, day), (True, []))
        h.set_cached("test", group, b"\xffcache", 1)
        self.assertEqual(h.get_cached("test", group), b"\xffcache")
        time.sleep(1.1)
        self.assertIsNone(h.get_cached("test", group))
        self.assertIsNone(take_configured(self.settings, "群友情报", group, "member", self.limits))
        self.assertIsNotNone(take_configured(self.settings, "群友情报", group, "member", self.limits))
        reset_configured(self.settings, "群友情报", group)
        self.assertIsNone(take_configured(self.settings, "群友情报", group, "member", self.limits))
        self.assertFalse(Path(self.settings["database"]).exists())
        self.assertIsNone(h.mongo)
        self.assertIsNone(h.cache)

    def test_sqlite_migration_verifies_each_durable_role_and_can_repeat(self):
        path = self.path / "source.db"
        source = History(str(path), self.path / "group-ai-images")
        stamp = time.time()
        event = self.group + "_source"
        source.add(event, self.group, "member", "源记录", display_name="群友", created=stamp)
        source.attach_image(event, b"\xff\x00old image")
        source.remember(self.group, "历史偏好", vector("历史偏好"), member="member")
        source.store_report(self.group, "2026-11-19", [b"\xffreport"])
        source.previous_report_groups((self.group,), "2026-11-19")
        take(str(path), "群友情报", self.group, "member", self.limits)
        for _ in range(2):
            with source.connect() as db:
                counts = migrate(db, self.history, quota_options=mysql_options(self.settings))
            self.assertEqual([counts[key] for key in ("messages", "profiles", "attachments", "memories",
                                                     "reports", "report_groups", "quota_events")],
                             [1, 1, 1, 1, 1, 1, 1])
        self.assertEqual(self.history.staged_report(self.group, "2026-11-19"), (True, [(1, b"\xffreport")]))
