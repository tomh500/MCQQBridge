"""Compose group data stores according to the selected YAML topology."""
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import pymongo
import pymysql
import redis

from . import media
from .group_ai import MAX_IMAGE_BYTES, similarity, vector
from .group_mysql import MySQLGroupData, mysql_settings

log = logging.getLogger(__name__)


class ExternalHistory:
    def __init__(self, settings, local):
        self.local = local
        self.mongo = self.raw = self.profiles = self.mysql = self.cache = None
        self.raw_sql = self.cache_sql = None
        self.reported_cache_issue = False
        backends = {
            "history": ("sqlite", "mysql", "mongodb"),
            "memory": ("sqlite", "mysql"),
            "reports": ("sqlite", "mysql"),
            "cache": ("local", "mysql", "redis"),
        }
        selected = {role: settings.get(role, allowed[0]) for role, allowed in backends.items()}
        for role, allowed in backends.items():
            if selected[role] not in allowed:
                raise ValueError(f"Unsupported backend for group_ai_storage.{role}")
        history, memory, reports, cache = (selected[role] for role in backends)
        sql_roles = [role for role in ("history", "reports", "cache") if selected[role] == "mysql"]
        sql = MySQLGroupData(mysql_settings(settings), sql_roles) if sql_roles else None
        self.raw_sql = sql if history == "mysql" else None
        self.report_store = sql if reports == "mysql" else local
        self.cache_sql = sql if cache == "mysql" else None
        self.shared_cache = cache != "local"
        if history == "mongodb":
            mongo = settings["mongodb"]
            self.mongo = pymongo.MongoClient(mongo["uri"], serverSelectionTimeoutMS=3000, socketTimeoutMS=5000)
            db = self.mongo[mongo.get("database") or "mcqq"]
            prefix = mongo.get("collection_prefix", "mcqq_group")
            self.raw = db[prefix + "_history"]
            self.profiles = db[prefix + "_profiles"]
            self.raw.create_index([("group", 1), ("created", 1), ("order", 1)])
            self.raw.create_index("created")
            self.profiles.create_index([("group", 1), ("member", 1)], unique=True)
        if memory == "mysql":
            self.mysql = mysql_settings(settings)
            with pymysql.connect(**self.mysql) as db, db.cursor() as cur:
                cur.execute("SELECT 1 FROM mcqq_group_ai_memory LIMIT 1")
        if cache == "redis":
            options = settings["redis"]
            self.cache = redis.Redis.from_url(options["url"], decode_responses=False,
                                              socket_connect_timeout=1, socket_timeout=1)
            self.key_prefix = options.get("key_prefix", "mcqq:group-ai")

    def close(self):
        if self.mongo is not None:
            self.mongo.close()
        if self.cache is not None:
            self.cache.close()

    def get_cached(self, namespace, key):
        try:
            if self.cache is not None:
                return self.cache.get(self.cache_key(namespace, key))
            if self.cache_sql is not None:
                return self.cache_sql.cache_get(namespace + ":" + key)
        except (redis.RedisError, pymysql.MySQLError) as error:
            self.report_cache_issue(error)
        return None

    def set_cached(self, namespace, key, value, ttl):
        try:
            if self.cache is not None:
                self.cache.setex(self.cache_key(namespace, key), ttl, value)
            elif self.cache_sql is not None:
                self.cache_sql.cache_set(namespace + ":" + key, value, ttl)
        except (redis.RedisError, pymysql.MySQLError) as error:
            self.report_cache_issue(error)

    def report_cache_issue(self, error):
        if not self.reported_cache_issue:
            self.reported_cache_issue = True
            log.warning("Shared group cache unavailable (%s)", type(error).__name__)

    def cache_key(self, namespace, key):
        return f"{self.key_prefix}:{namespace}:" + hashlib.sha256(key.encode()).hexdigest()

    def update_profile(self, group, member, name, avatar, created):
        identity = {"group": group, "member": member}
        values = {}
        for field, value in (("name", name[:80]), ("avatar", avatar)):
            if value:
                values[field] = {"$cond": [
                    {"$lte": [{"$ifNull": ["$" + field + "_updated", 0]}, created]},
                    {"$literal": value}, "$" + field,
                ]}
                values[field + "_updated"] = {"$max": [{"$ifNull": ["$" + field + "_updated", 0]}, created]}
        if values and member != "__bot__":
            self.profiles.update_one(identity, [{"$set": values}], upsert=True)

    def add(self, event_id, group, member, text, image_path=None, display_name="", created=None, avatar_url=""):
        if self.raw is None and self.raw_sql is None and self.report_store is self.local:
            return self.local.add(event_id, group, member, text, image_path, display_name, created, avatar_url)
        created = time.time() if created is None else created
        day = datetime.fromtimestamp(created, timezone(timedelta(hours=8))).date().isoformat()
        with self.local.image_lock:
            if self.report_store.closed_day(group, day):
                return
            if self.raw_sql is not None:
                return self.raw_sql.add(event_id, group, member, text, image_path, display_name[:80], created, avatar_url)
            if self.raw is None:
                return self.local.add(event_id, group, member, text, image_path, display_name, created, avatar_url)
            record = {"group": group, "member": member, "text": text, "image": image_path,
                      "name": display_name[:80], "created": created, "order": time.time(), "avatar": avatar_url}
            if self.raw.update_one({"_id": event_id}, {"$setOnInsert": record}, upsert=True).upserted_id is not None:
                self.update_profile(group, member, display_name, avatar_url, created)

    def attach_image(self, event_id, data):
        if self.raw_sql is not None:
            if 0 < len(data) <= media.MAX_BYTES:
                self.raw_sql.attach(event_id, data, MAX_IMAGE_BYTES)
            return
        if self.raw is None:
            return self.local.attach_image(event_id, data)
        with self.local.image_lock:
            if not self.raw.find_one({"_id": event_id}, {"_id": 1}):
                return
            path = self.local.save_image(event_id, data)
            if path:
                self.raw.update_one({"_id": event_id}, {"$set": {"image": path}})

    def remove(self, predicate):
        for row in self.raw.find(predicate, {"image": 1}):
            self.raw.delete_one({"_id": row["_id"]})
            self.unlink_images([row.get("image")])

    def unlink_images(self, paths):
        for path in paths:
            if path and re.fullmatch(r"[0-9a-f]{64}\.img", path):
                (self.local.image_dir / path).unlink(missing_ok=True)

    def prune(self, cutoff, retained_groups=(), retained_since=None):
        if self.raw_sql is not None:
            with self.local.image_lock:
                self.raw_sql.remove_history(cutoff, retained_groups=retained_groups, retained_since=retained_since)
            return
        if self.raw is None:
            return self.local.prune(cutoff, retained_groups, retained_since)
        with self.local.image_lock:
            predicate = {"created": {"$lt": cutoff}}
            if retained_groups:
                predicate["$or"] = [{"created": {"$lt": retained_since}}, {"group": {"$nin": retained_groups}}]
            self.remove(predicate)

    def stage_day(self, group, day, cutoff, summary, images):
        if self.raw is None and self.raw_sql is None and self.mysql is None and self.report_store is self.local:
            return self.local.stage_day(group, day, cutoff, summary, images)
        with self.local.image_lock:
            if not self.report_store.closed_day(group, day):
                if summary:
                    self.save_summaries(group, [("", summary)])
                self.report_store.store_report(group, day, images)
            self.catchup_group(group, cutoff)

    def catchup_group(self, group, cutoff):
        with self.local.image_lock:
            if self.raw_sql is not None:
                self.raw_sql.remove_history(cutoff, group=group)
            elif self.raw is not None:
                self.remove({"group": group, "created": {"$lt": cutoff}})
            elif self.report_store is not self.local or self.mysql is not None:
                self.local.remove_group_history(group, cutoff)

    def staged_report(self, group, day):
        return self.report_store.staged_report(group, day)

    def acknowledge_report(self, group, day):
        self.report_store.acknowledge_report(group, day)

    def expire_reports(self, oldest):
        self.report_store.expire_reports(oldest)

    def previous_report_groups(self, groups, day):
        return self.report_store.previous_report_groups(groups, day)

    def day(self, group, start, end):
        if self.raw_sql is not None:
            return self.raw_sql.day(group, start, end)
        if self.raw is None:
            return self.local.day(group, start, end)
        rows = list(self.raw.find({"group": group, "member": {"$ne": "__bot__"},
                                   "created": {"$gte": start, "$lt": end}}).sort([("created", 1), ("order", 1)]))
        members = list({row["member"] for row in rows})
        profiles = {row["member"]: row for row in self.profiles.find({"group": group, "member": {"$in": members}})}
        return [(row["created"], row["member"], row.get("name") or profiles.get(row["member"], {}).get("name", ""),
                 row["text"], row.get("avatar") or profiles.get(row["member"], {}).get("avatar", "")) for row in rows]

    def recent(self, group, limit=30):
        if self.raw_sql is not None:
            return self.raw_sql.recent(group, limit)
        if self.raw is None:
            return self.local.recent(group, limit)
        rows = self.raw.find({"group": group}).sort([("created", -1), ("order", -1)]).limit(limit)
        return list(reversed([(r["member"], r["text"], r.get("image"), r.get("name", "")) for r in rows]))

    def all_recent(self, group):
        if self.raw_sql is not None:
            return self.raw_sql.recent(group)
        if self.raw is None:
            return self.local.all_recent(group)
        return [(r["member"], r["text"], r.get("image"), r.get("name", ""))
                for r in self.raw.find({"group": group}).sort([("created", 1), ("order", 1)])]

    def avatar_url(self, group, member):
        if self.raw_sql is not None:
            return self.raw_sql.profile(group, member)[1]
        if self.profiles is None:
            return self.local.avatar_url(group, member)
        profile = self.profiles.find_one({"group": group, "member": member})
        return profile.get("avatar", "") if profile else ""

    def member_evidence(self, group, member, start, end):
        if self.mysql is None:
            memories = self.local.member_memories(group, member)
        else:
            with pymysql.connect(**self.mysql) as db, db.cursor() as cur:
                cur.execute("""SELECT summary FROM mcqq_group_ai_memory
                               WHERE group_id=%s AND member_id=%s ORDER BY created,digest""", (group, member))
                memories = [summary for (summary,) in cur]
        return self.day(group, start, end), memories, self.profile_name(group, member)

    def profile_name(self, group, member):
        if self.raw_sql is not None:
            return self.raw_sql.profile(group, member)[0]
        if self.profiles is None:
            return self.local.profile_name(group, member)
        profile = self.profiles.find_one({"group": group, "member": member})
        return profile.get("name", "") if profile else ""

    def profile_names(self, group):
        if self.raw_sql is not None:
            return self.raw_sql.profile_names(group)
        if self.profiles is None:
            return self.local.profile_names(group)
        return [(profile["member"], profile.get("name", ""))
                for profile in self.profiles.find({"group": group}, {"name": 1, "member": 1})]

    def save_summaries(self, group, entries):
        if self.mysql is None:
            return self.local.save_summaries(group, entries)
        when = time.time()
        self.import_memories((group, member, summary[:4000], json.dumps(vector(summary[:4000])), when)
                             for member, summary in dict.fromkeys(entries))

    def import_memories(self, entries):
        params = [(group, member, hashlib.sha256(summary.encode()).digest(), summary, embedding, when)
                  for group, member, summary, embedding, when in entries]
        if not params:
            return
        with pymysql.connect(**self.mysql) as db, db.cursor() as cur:
            cur.executemany("""INSERT INTO mcqq_group_ai_memory (group_id,member_id,digest,summary,embedding,created)
                               VALUES (%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE digest=mcqq_group_ai_memory.digest""", params)
            db.commit()

    def recall(self, group, query, speaker=None, limit=3):
        if self.mysql is None:
            return self.local.recall(group, query, speaker, limit, names=self.profile_names(group))
        names = {}
        for member, name in self.profile_names(group):
            if len(name) >= 2 and name in query:
                names.setdefault(name, set()).add(member)
        mentioned = {next(iter(ids)) for ids in names.values() if len(ids) == 1}
        mentioned.update(re.findall(r"\b[0-9A-Fa-f]{32}\b", query))
        targets = sorted({"", *mentioned} | ({speaker} if speaker else set()))
        placeholders = ",".join(["%s"] * len(targets))
        q = vector(query)
        with pymysql.connect(**self.mysql) as db, db.cursor() as cur:
            cur.execute(f"""SELECT member_id,summary,embedding FROM mcqq_group_ai_memory
                            WHERE group_id=%s AND member_id IN ({placeholders}) ORDER BY created DESC""", (group, *targets))
            ranked = sorted(((similarity(q, json.loads(embedding)) + (2 if member in mentioned else 1 if member == speaker else 0), summary)
                             for member, summary, embedding in cur), reverse=True)
        return [summary for score, summary in ranked[:limit] if score > 0]
