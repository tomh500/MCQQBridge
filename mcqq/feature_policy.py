"""Per-group feature schedules and durable, per-group sliding rate limits."""
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, time as daytime, timedelta
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Shanghai')
log = logging.getLogger(__name__)

# Full officially announced holiday periods, including transferred days off.
# 2026: https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html
# 2027: https://chinajob.mohrss.gov.cn/h5/c/2026-11-09/635850.shtml
HOLIDAYS = {
    2026: [('01-01','01-03'), ('02-15','02-23'), ('04-04','04-06'), ('05-01','05-05'), ('06-19','06-21'), ('09-25','09-27'), ('10-01','10-07')],
    2027: [('01-01','01-03'), ('02-05','02-13'), ('04-03','04-05'), ('05-01','05-05'), ('06-09','06-09'), ('09-15','09-15'), ('10-01','10-07')],
}
_unknown_years = set()


def restricted_day(day, holidays=HOLIDAYS):
    md = day.strftime('%m-%d')
    if day.weekday() >= 5 or '01-10' <= md <= '02-14' or '07-15' <= md <= '08-20':
        return True
    if day.year not in holidays:
        if day.year not in _unknown_years:
            log.warning('No verified Chinese holiday calendar for %s; using restricted hours on unknown weekdays', day.year)
            _unknown_years.add(day.year)
        return True
    return any(start <= md <= end for start, end in holidays[day.year])


def windows(rule):
    result = []
    def minute(value, *, endpoint=False):
        parts = value.split(':')
        if len(parts) != 2 or any(len(part) != 2 or not part.isdigit() for part in parts):
            raise ValueError('invalid time')
        hour, minute = map(int, parts)
        if minute > 59 or hour > 24 or (hour == 24 and (minute != 0 or not endpoint)):
            raise ValueError('invalid time')
        return hour * 60 + minute
    for start, end in rule.get('windows', [['00:00','07:00'], ['14:00','17:00']]):
        first, last = minute(start), minute(end, endpoint=True)
        if first >= last:
            raise ValueError('time windows must not wrap midnight')
        result.append((first, last))
    return result


def in_windows(moment, rule=None):
    local = moment.timetz().replace(tzinfo=None)
    seconds = local.hour * 3600 + local.minute * 60 + local.second + local.microsecond / 1e6
    return any(start * 60 <= seconds < end * 60 for start, end in windows(rule or {}))


def state(rule, now, holidays=HOLIDAYS):
    """Return availability and weekday rate limit without changing state."""
    local = now.astimezone(ZONE)
    md = local.strftime('%m-%d')
    if md in rule.get('closed_dates', []):
        return False, None
    schedule = rule.get('schedule', 'always')
    if schedule == 'always':
        return True, None
    if schedule == 'daily_windows':
        return in_windows(local, rule), rule.get('limit_per_minute')
    if schedule != 'china_school_hours':
        raise ValueError('unknown feature schedule')
    if restricted_day(local.date(), holidays):
        return in_windows(local, rule), None
    return True, rule.get('limit_in_windows', 10) if in_windows(local, rule) else rule.get('limit_outside_windows', 3)


def next_open(rule, now, holidays=HOLIDAYS):
    local = now.astimezone(ZONE)
    for offset in range(370):
        day = local.date() + timedelta(days=offset)
        starts = {0} | {start for start, _ in windows(rule)} if rule.get('schedule') != 'always' else {0}
        for minute in sorted(starts):
            candidate = datetime.combine(day, daytime(minute // 60, minute % 60), ZONE)
            if candidate > local and state(rule, candidate, holidays)[0]:
                return candidate
    return None


class FeaturePolicy:
    def __init__(self, settings, clock=None):
        self.settings = settings
        self.clock = clock or (lambda: datetime.now(ZONE))
        self.holidays = dict(HOLIDAYS)
        for year, ranges in settings.get('feature_policy', {}).get('holiday_ranges', {}).items():
            year = int(year)
            validated = []
            for start, end in ranges:
                first = datetime.strptime(f'{year}-{start}', '%Y-%m-%d').date()
                last = datetime.strptime(f'{year}-{end}', '%Y-%m-%d').date()
                if first > last:
                    raise ValueError('invalid holiday date range')
                validated.append((start, end))
            self.holidays[year] = validated

    def rule(self, group, category):
        return self.settings.get('feature_policy', {}).get('groups', {}).get(group, {}).get(category)

    def category_for(self, value, *, button=False):
        defaults = {'entertainment': {'commands': ['今日老婆', '换老婆'], 'button_prefixes': ['waifu_swap:', 'waifu_accept:']}}
        definitions = {**defaults, **self.settings.get('feature_policy', {}).get('categories', {})}
        for category, definition in definitions.items():
            if button and any(value.startswith(prefix) for prefix in definition.get('button_prefixes', [])):
                return category
            parts = value[1:].split(maxsplit=1) if value.startswith('/') else []
            if not button and parts and parts[0] in definition.get('commands', []):
                return category
        return None

    def check(self, group, category, *, consume=True, schedule=None):
        rule = self.rule(group, category)
        if rule is None:
            return {'allowed': True}
        if schedule is not None:
            rule = {**rule, 'schedule': schedule}
        now = self.clock()
        allowed, limit = state(rule, now, self.holidays)
        if not allowed:
            resume = next_open(rule, now, self.holidays)
            return {'allowed': False, 'reason': 'closed', 'next': resume}
        if limit is not None and (not isinstance(limit, int) or isinstance(limit, bool) or limit < 1):
            raise ValueError('invalid per-minute limit')
        if consume and limit is not None and not self._take(group, category, limit, now.timestamp()):
            return {'allowed': False, 'reason': 'rate'}
        return {'allowed': True}

    def _take(self, group, category, limit, now):
        with closing(sqlite3.connect(self.settings['database'], timeout=5)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS feature_rate_events (group_id TEXT NOT NULL, category TEXT NOT NULL, created REAL NOT NULL)')
            db.execute('CREATE INDEX IF NOT EXISTS feature_rate_lookup ON feature_rate_events(group_id,category,created)')
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('DELETE FROM feature_rate_events WHERE created <= ?', (now - 60,))
                count = db.execute('SELECT COUNT(*) FROM feature_rate_events WHERE group_id=? AND category=? AND created>?', (group, category, now-60)).fetchone()[0]
                if count >= limit:
                    db.commit()
                    return False
                db.execute('INSERT INTO feature_rate_events VALUES (?,?,?)', (group, category, now))
                db.commit()
                return True
            except Exception:
                db.rollback()
                raise
