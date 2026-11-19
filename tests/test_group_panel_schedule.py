import unittest
from datetime import datetime

from mcqq.feature_policy import ZONE
from sync_group_panel import group_panel, same_items


class GroupPanelScheduleTest(unittest.TestCase):
    def test_panel_tracks_schedule_without_rate_limit_consumption(self):
        cfg = {'feature_policy': {'groups': {'one': {'entertainment': {
            'schedule': 'china_school_hours', 'closed_dates': ['06-04']}}}}}
        def description(when):
            panel = group_panel(cfg, 'one', datetime.fromisoformat(when).replace(tzinfo=ZONE))
            return next(item['desc'] for item in panel['items'] if item['name'] == '老婆')
        self.assertEqual(description('2026-11-21T06:59'), '当前可用')
        self.assertEqual(description('2026-11-21T07:00'), '下次 11-21 14:00')
        self.assertEqual(description('2026-06-04T15:00'), '下次 06-05 00:00')

    def test_comparison_ignores_extra_response_fields(self):
        self.assertTrue(same_items([{'type': 'command', 'name': 'x', 'desc': 'a', 'extra': 1}],
                                   [{'type': 'command', 'name': 'x', 'desc': 'a', 'only_admin': False}]))


if __name__ == '__main__':
    unittest.main()
