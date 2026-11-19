"""Transactional daily rewards, private points, wishes and preference learning."""
import json
import hashlib
import secrets
from .waifu_preferences import MAX_POINTS, learn, pick


class WaifuEconomy:
    def __init__(self, storage):
        self.storage = storage

    def _lock(self, cur, subject):
        cur.execute("INSERT INTO waifu_accounts(subject,points,preference) VALUES (%s,0,'{}') ON DUPLICATE KEY UPDATE subject=VALUES(subject)", (subject,))
        cur.execute("SELECT points,preference FROM waifu_accounts WHERE subject=%s FOR UPDATE", (subject,))
        points, vector = cur.fetchone()
        return int(points), json.loads(vector) if isinstance(vector, str) else vector

    def _entries(self):
        return self.storage.entries()

    @staticmethod
    def _replay(cur, event, subject, kind):
        # The account row serializes events for this subject. A locking read for
        # a missing event would take an InnoDB gap lock and deadlock unrelated users.
        cur.execute("SELECT subject,kind,result FROM waifu_operations WHERE event_id=%s", (event,))
        row = cur.fetchone()
        if not row:
            return None
        if row[0] != subject or row[1] != kind:
            raise ValueError("event conflict")
        return json.loads(row[2]) if isinstance(row[2], str) else row[2]

    @staticmethod
    def _save(cur, event, subject, kind, result):
        cur.execute("INSERT INTO waifu_operations(event_id,subject,kind,result) VALUES (%s,%s,%s,%s)",
                    (event, subject, kind, json.dumps(result, ensure_ascii=False)))

    def today(self, subject, day):
        entries = self._entries()
        with self.storage.pymysql.connect(**self.storage.mysql) as c:
            c.begin()
            try:
                with c.cursor() as q:
                    points, vector = self._lock(q, subject)
                    q.execute("INSERT IGNORE INTO waifu_rewards(subject,day) VALUES (%s,%s)", (subject, day))
                    if q.rowcount:
                        q.execute("UPDATE waifu_accounts SET points=%s WHERE subject=%s", (min(MAX_POINTS, points + secrets.randbelow(5) + 1), subject))
                    q.execute("SELECT name,image_url,source_url,swapped,draw_token FROM daily_waifu_draws WHERE subject=%s AND day=%s FOR UPDATE", (subject, day))
                    row = q.fetchone()
                    fresh = row is None
                    if fresh:
                        entry = pick(entries, vector)
                        token = secrets.token_hex(16)
                        q.execute("INSERT INTO daily_waifu_draws(subject,day,name,image_url,source_url,draw_token) VALUES (%s,%s,%s,%s,%s,%s)", (subject, day, entry['name'], entry['image_url'], entry['source_url'], token))
                        row = (entry['name'], entry['image_url'], entry['source_url'], 0, token)
                    result = self.storage.result(row, new=fresh)
                c.commit()
                return result
            except Exception:
                c.rollback()
                raise

    def points(self, subject, operation, amount, event):
        with self.storage.pymysql.connect(**self.storage.mysql) as c:
            c.begin()
            try:
                with c.cursor() as q:
                    balance, _ = self._lock(q, subject)
                    if operation == 'query':
                        result = {'points': balance}
                    else:
                        previous = self._replay(q, event, subject, operation)
                        if previous is not None:
                            c.commit()
                            return previous
                        balance = max(0, min(MAX_POINTS, amount if operation == 'set' else balance + amount))
                        q.execute('UPDATE waifu_accounts SET points=%s WHERE subject=%s', (balance, subject))
                        result = {'points': balance}
                        self._save(q, event, subject, operation, result)
                c.commit()
                return result
            except Exception:
                c.rollback()
                raise

    def swap(self, subject, day, expected_token=None):
        entries = self._entries()
        with self.storage.pymysql.connect(**self.storage.mysql) as c:
            c.begin()
            try:
                with c.cursor() as q:
                    _, vector = self._lock(q, subject)
                    q.execute('SELECT name,image_url,source_url,swapped,draw_token FROM daily_waifu_draws WHERE subject=%s AND day=%s FOR UPDATE', (subject, day))
                    row = q.fetchone()
                    if not row:
                        result = {'error': '请先发送 /今日老婆 抽取今天的角色。'}
                    elif expected_token is not None and expected_token != row[4]:
                        result = {'error': '这张换取按钮已失效，请重新发送 /今日老婆。'}
                    elif row[3]:
                        result = self.storage.result(row)
                    else:
                        entry = pick([e for e in entries if e['source_url'] != row[2]], vector)
                        token = secrets.token_hex(16)
                        q.execute('UPDATE daily_waifu_draws SET name=%s,image_url=%s,source_url=%s,swapped=1,draw_token=%s WHERE subject=%s AND day=%s', (entry['name'], entry['image_url'], entry['source_url'], token, subject, day))
                        result = self.storage.result((entry['name'], entry['image_url'], entry['source_url'], 1, token), exchanged=True)
                c.commit()
                return result
            except Exception:
                c.rollback()
                raise

    def accept(self, subject, day, token, event):
        entries = {e['source_url']: e for e in self._entries()}
        with self.storage.pymysql.connect(**self.storage.mysql) as c:
            c.begin()
            try:
                with c.cursor() as q:
                    balance, vector = self._lock(q, subject)
                    previous = self._replay(q, event, subject, 'accept')
                    if previous is not None:
                        c.commit()
                        return previous
                    q.execute('SELECT source_url,swapped,draw_token FROM daily_waifu_draws WHERE subject=%s AND day=%s FOR UPDATE', (subject, day))
                    row = q.fetchone()
                    if not row or row[2] != token:
                        result = {'error': '按钮已失效。'}
                    else:
                        # Lock this draw even if an earlier draw was confirmed today.
                        q.execute('UPDATE daily_waifu_draws SET swapped=1 WHERE subject=%s AND day=%s', (subject, day))
                        # Preference training remains limited to once per subject/day.
                        key = 'accept:' + hashlib.sha256((subject + '|' + day).encode()).hexdigest()
                        q.execute('SELECT 1 FROM waifu_operations WHERE event_id=%s', (key,))
                        already = q.fetchone() is not None
                        if not already:
                            entry = entries.get(row[0])
                            if balance >= 1 and entry:
                                vector = learn(vector, entry)
                                vector['_confirmations'] = min(MAX_POINTS, int(vector.get('_confirmations', 0)) + 1)
                                q.execute('UPDATE waifu_accounts SET points=%s,preference=%s WHERE subject=%s', (balance - 1, json.dumps(vector, ensure_ascii=False), subject))
                            self._save(q, key, subject, 'accepted', {'accepted': True})
                        result = {'accepted': True}
                    self._save(q, event, subject, 'accept', result)
                c.commit()
                return result
            except Exception:
                c.rollback()
                raise

    def wish(self, subject, day, keyword, event):
        entries = self._entries()
        key = keyword.casefold().strip()
        exact = [e for e in entries if key in [x.casefold() for x in [e['name'], *e.get('aliases', [])]]]
        matches = exact or [e for e in entries if any(key in x.casefold() for x in [e['name'], *e.get('aliases', [])])]
        if not key or len(matches) != 1:
            return {'error': '未找到唯一角色，请输入更完整的角色名。'}
        target = matches[0]
        with self.storage.pymysql.connect(**self.storage.mysql) as c:
            c.begin()
            try:
                with c.cursor() as q:
                    balance, vector = self._lock(q, subject)
                    previous = self._replay(q, event, subject, 'wish')
                    if previous is not None:
                        c.commit()
                        return previous
                    q.execute('SELECT swapped FROM daily_waifu_draws WHERE subject=%s AND day=%s FOR UPDATE', (subject, day))
                    row = q.fetchone()
                    if row and row[0]:
                        result = {'error': '今天的更换机会已使用。'}
                    elif balance < 16:
                        result = {'error': f'积分不足，许愿需要 16 积分，目前有 {balance} 积分。'}
                    else:
                        q.execute('INSERT IGNORE INTO waifu_wishes(subject,source_url,failures) VALUES (%s,%s,0)', (subject, target['source_url']))
                        q.execute('SELECT failures FROM waifu_wishes WHERE subject=%s AND source_url=%s FOR UPDATE', (subject, target['source_url']))
                        failures = int(q.fetchone()[0])
                        won = secrets.randbelow(100) < min(100, 50 + failures)
                        other = [e for e in entries if e['source_url'] != target['source_url']]
                        entry = target if won else pick(other, vector)
                        q.execute('UPDATE waifu_wishes SET failures=%s WHERE subject=%s AND source_url=%s', (0 if won else min(50, failures + 1), subject, target['source_url']))
                        q.execute('UPDATE waifu_accounts SET points=points-16 WHERE subject=%s', (subject,))
                        token = secrets.token_hex(16)
                        if row:
                            q.execute('UPDATE daily_waifu_draws SET name=%s,image_url=%s,source_url=%s,draw_token=%s,swapped=1 WHERE subject=%s AND day=%s', (entry['name'], entry['image_url'], entry['source_url'], token, subject, day))
                        else:
                            q.execute('INSERT INTO daily_waifu_draws(subject,day,name,image_url,source_url,draw_token,swapped) VALUES (%s,%s,%s,%s,%s,%s,1)', (subject, day, entry['name'], entry['image_url'], entry['source_url'], token))
                        result = self.storage.result((entry['name'], entry['image_url'], entry['source_url'], 1, token), new=False)
                    self._save(q, event, subject, 'wish', result)
                c.commit()
                return result
            except Exception:
                c.rollback()
                raise
