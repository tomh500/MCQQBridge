"""MySQL implementations of chat history, daily-report state and optional TTL cache."""
import hashlib
import time

import pymysql


def mysql_settings(storage):
    return {**storage["mysql"], "charset": "utf8mb4", "autocommit": False,
            "binary_prefix": True, "connect_timeout": 4, "read_timeout": 8, "write_timeout": 8}


class MySQLGroupData:
    def __init__(self, options, roles):
        self.options = options
        tables = {
            "history": ("mcqq_group_ai_history", "mcqq_group_ai_profile", "mcqq_group_ai_attachment"),
            "reports": ("mcqq_group_ai_daily", "mcqq_group_ai_daily_image", "mcqq_group_ai_daily_start"),
            "cache": ("mcqq_group_ai_cache",),
        }
        with pymysql.connect(**options) as db, db.cursor() as cur:
            for role in roles:
                for table in tables[role]:
                    cur.execute(f"SELECT 1 FROM {table} LIMIT 1")

    def rows(self, sql, args=()):
        with pymysql.connect(**self.options) as db, db.cursor() as cur:
            cur.execute(sql, args)
            return list(cur.fetchall())

    def write(self, sql, args=()):
        with pymysql.connect(**self.options) as db, db.cursor() as cur:
            cur.execute(sql, args)
            db.commit()

    @staticmethod
    def _profile(cur, group, member, name, avatar, name_updated, avatar_updated):
        if member == "__bot__" or not (name or avatar):
            return
        cur.execute("""INSERT INTO mcqq_group_ai_profile
                       (group_id,member_id,display_name,name_updated,avatar_url,avatar_updated)
                       VALUES (%s,%s,%s,%s,%s,%s) AS incoming
                       ON DUPLICATE KEY UPDATE
                           display_name=IF(incoming.display_name<>'' AND
                               incoming.name_updated>=mcqq_group_ai_profile.name_updated,
                               incoming.display_name,mcqq_group_ai_profile.display_name),
                           name_updated=GREATEST(mcqq_group_ai_profile.name_updated,incoming.name_updated),
                           avatar_url=IF(incoming.avatar_url<>'' AND
                               incoming.avatar_updated>=mcqq_group_ai_profile.avatar_updated,
                               incoming.avatar_url,mcqq_group_ai_profile.avatar_url),
                           avatar_updated=GREATEST(mcqq_group_ai_profile.avatar_updated,incoming.avatar_updated)""",
                    (group, member, name, name_updated if name else 0, avatar, avatar_updated if avatar else 0))

    def update_profile(self, group, member, name, avatar, name_updated, avatar_updated):
        with pymysql.connect(**self.options) as db, db.cursor() as cur:
            self._profile(cur, group, member, name, avatar, name_updated, avatar_updated)
            db.commit()

    def add(self, event, group, member, text, image, name, created, avatar):
        with pymysql.connect(**self.options) as db, db.cursor() as cur:
            cur.execute("""INSERT INTO mcqq_group_ai_history
                           (event_id,group_id,member_id,message_text,image_path,display_name,created,avatar_url)
                           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                           ON DUPLICATE KEY UPDATE event_id=mcqq_group_ai_history.event_id""",
                        (event, group, member, text, image, name, created, avatar))
            if cur.rowcount:
                self._profile(cur, group, member, name, avatar, created, created)
            db.commit()

    def attach(self, event, data, budget, path="mysql"):
        lock = "mcqq:attachments:" + hashlib.sha256(str(self.options.get("database")).encode()).hexdigest()[:32]
        with pymysql.connect(**self.options) as db, db.cursor() as cur:
            cur.execute("SELECT GET_LOCK(%s,5)", (lock,))
            if cur.fetchone() != (1,):
                raise TimeoutError("MySQL attachment budget lock unavailable")
            cur.execute("SELECT 1 FROM mcqq_group_ai_history WHERE event_id=%s FOR UPDATE", (event,))
            if not cur.fetchone():
                return
            cur.execute("SELECT COALESCE(SUM(byte_size),0) FROM mcqq_group_ai_attachment WHERE event_id<>%s", (event,))
            total = int(cur.fetchone()[0]) + len(data)
            if total > budget:
                cur.execute("""SELECT event_id,byte_size FROM mcqq_group_ai_attachment
                               WHERE event_id<>%s ORDER BY created,event_id""", (event,))
                for oldest, size in list(cur.fetchall()):
                    cur.execute("DELETE FROM mcqq_group_ai_attachment WHERE event_id=%s", (oldest,))
                    cur.execute("UPDATE mcqq_group_ai_history SET image_path=NULL WHERE event_id=%s", (oldest,))
                    total -= size
                    if total <= budget:
                        break
            cur.execute("""INSERT INTO mcqq_group_ai_attachment (event_id,data,byte_size,created)
                           VALUES (%s,%s,%s,%s) AS incoming ON DUPLICATE KEY UPDATE
                           data=incoming.data,byte_size=incoming.byte_size,created=incoming.created""",
                        (event, data, len(data), time.time()))
            cur.execute("UPDATE mcqq_group_ai_history SET image_path=%s WHERE event_id=%s", (path, event))
            db.commit()

    def import_history(self, rows):
        with pymysql.connect(**self.options) as db, db.cursor() as cur:
            cur.executemany("""INSERT INTO mcqq_group_ai_history
                               (event_id,group_id,member_id,message_text,image_path,display_name,created,avatar_url)
                               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                               ON DUPLICATE KEY UPDATE event_id=mcqq_group_ai_history.event_id""", rows)
            db.commit()
            placeholders = ",".join(["%s"] * len(rows))
            cur.execute(f"""SELECT event_id,group_id,member_id,message_text,image_path,display_name,created,avatar_url
                            FROM mcqq_group_ai_history WHERE event_id IN ({placeholders})""",
                        tuple(row[0] for row in rows))
            return {row[0]: row for row in cur}

    def profile(self, group, member):
        rows = self.rows("""SELECT display_name,avatar_url FROM mcqq_group_ai_profile
                            WHERE group_id=%s AND member_id=%s""", (group, member))
        return rows[0] if rows else ("", "")

    def profile_names(self, group):
        return self.rows("SELECT member_id,display_name FROM mcqq_group_ai_profile WHERE group_id=%s", (group,))

    def day(self, group, start, end):
        return self.rows("""SELECT h.created,h.member_id,COALESCE(NULLIF(h.display_name,''),p.display_name,''),
                                   h.message_text,COALESCE(NULLIF(h.avatar_url,''),p.avatar_url,'')
                            FROM mcqq_group_ai_history AS h
                            LEFT JOIN mcqq_group_ai_profile AS p ON p.group_id=h.group_id AND p.member_id=h.member_id
                            WHERE h.group_id=%s AND h.member_id<>'__bot__' AND h.created>=%s AND h.created<%s
                            ORDER BY h.created,h.id""", (group, start, end))

    def recent(self, group, limit=None):
        base = """SELECT member_id,message_text,image_path,display_name FROM mcqq_group_ai_history WHERE group_id=%s"""
        if limit is None:
            return self.rows(base + " ORDER BY created,id", (group,))
        return list(reversed(self.rows(base + " ORDER BY created DESC,id DESC LIMIT %s", (group, limit))))

    def remove_history(self, cutoff, *, group=None, retained_groups=(), retained_since=None):
        where, params = "created<%s", [cutoff]
        if group is not None:
            where += " AND group_id=%s"
            params.append(group)
        if retained_groups:
            keys = ",".join(["%s"] * len(retained_groups))
            where += f" AND (created<%s OR group_id NOT IN ({keys}))"
            params.extend((retained_since, *retained_groups))
        with pymysql.connect(**self.options) as db, db.cursor() as cur:
            cur.execute(f"DELETE FROM mcqq_group_ai_history WHERE {where}", params)
            db.commit()

    def closed_day(self, group, day):
        return bool(self.rows("SELECT 1 FROM mcqq_group_ai_daily WHERE group_id=%s AND day=%s", (group, day)))

    def store_report(self, group, day, images):
        self.import_report(group, day, enumerate(images, 1))

    def import_report(self, group, day, pages):
        with pymysql.connect(**self.options) as db, db.cursor() as cur:
            cur.execute("""INSERT INTO mcqq_group_ai_daily (group_id,day) VALUES (%s,%s)
                           ON DUPLICATE KEY UPDATE day=mcqq_group_ai_daily.day""", (group, day))
            if cur.rowcount:
                cur.executemany("""INSERT INTO mcqq_group_ai_daily_image (group_id,day,page,image)
                                   VALUES (%s,%s,%s,%s)""", [(group, day, page, image) for page, image in pages])
            db.commit()

    def staged_report(self, group, day):
        with pymysql.connect(**self.options) as db, db.cursor() as cur:
            cur.execute("SELECT 1 FROM mcqq_group_ai_daily WHERE group_id=%s AND day=%s", (group, day))
            exists = bool(cur.fetchone())
            cur.execute("""SELECT page,image FROM mcqq_group_ai_daily_image WHERE group_id=%s AND day=%s
                           ORDER BY page""", (group, day))
            pages = list(cur.fetchall())
        return exists, pages

    def acknowledge_report(self, group, day):
        self.write("DELETE FROM mcqq_group_ai_daily_image WHERE group_id=%s AND day=%s", (group, day))

    def expire_reports(self, oldest):
        self.write("DELETE FROM mcqq_group_ai_daily WHERE day<%s", (oldest,))

    def previous_report_groups(self, groups, day):
        if not groups:
            return ()
        with pymysql.connect(**self.options) as db, db.cursor() as cur:
            cur.executemany("""INSERT INTO mcqq_group_ai_daily_start (group_id,day) VALUES (%s,%s)
                               ON DUPLICATE KEY UPDATE day=mcqq_group_ai_daily_start.day""",
                            [(group, day) for group in groups])
            cur.execute("SELECT group_id FROM mcqq_group_ai_daily_start WHERE day<%s", (day,))
            previous = {group for group, in cur}
            db.commit()
        return tuple(group for group in groups if group in previous)

    def cache_get(self, key):
        digest = hashlib.sha256(key.encode()).digest()
        rows = self.rows("SELECT payload FROM mcqq_group_ai_cache WHERE cache_key=%s AND expires>%s",
                         (digest, time.time()))
        return rows[0][0] if rows else None

    def cache_set(self, key, value, ttl):
        digest = hashlib.sha256(key.encode()).digest()
        expires = time.time() + ttl
        with pymysql.connect(**self.options) as db, db.cursor() as cur:
            cur.execute("DELETE FROM mcqq_group_ai_cache WHERE expires<=%s ORDER BY expires LIMIT 200", (time.time(),))
            cur.execute("""INSERT INTO mcqq_group_ai_cache (cache_key,payload,expires) VALUES (%s,%s,%s) AS incoming
                           ON DUPLICATE KEY UPDATE payload=incoming.payload, expires=incoming.expires""",
                        (digest, value, expires))
            db.commit()
