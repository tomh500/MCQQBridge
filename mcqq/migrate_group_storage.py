"""Idempotently copy and verify SQLite group data after stopping the QQ bot."""
from collections import defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3

import pymongo
import pymysql

from .config import load
from . import media
from .command_quota import lock_mysql_group, mysql_options
from .group_ai import History, MAX_IMAGE_BYTES
from .group_storage import ExternalHistory


def mysql_history(source, sink, copied):
    rows = source.execute("""SELECT event_id,group_id,member_id,text,image_path,display_name,created,avatar_url
                             FROM group_ai_history ORDER BY id""")
    while batch := rows.fetchmany(200):
        expected = {row[0]: row for row in batch}
        if sink.raw_sql.import_history(batch) != expected:
            raise RuntimeError("MySQL message readback differs from SQLite")
        copied["messages"] += len(batch)
    for group, member, name, updated, avatar, avatar_updated in source.execute(
            "SELECT group_id,member_id,display_name,updated,avatar_url,avatar_updated FROM group_ai_profiles"):
        sink.raw_sql.update_profile(group, member, name, avatar, updated, avatar_updated)
        if sink.raw_sql.profile(group, member) != (name, avatar):
            raise RuntimeError("MySQL profile readback differs from SQLite")
        copied["profiles"] += 1
        copied["avatar_references"] += bool(avatar)
    for event, filename in source.execute("""SELECT event_id,image_path FROM group_ai_history
                                              WHERE image_path IS NOT NULL ORDER BY created,id"""):
        if not re.fullmatch(r"[0-9a-f]{64}\.img", filename):
            continue
        path = sink.local.image_dir / filename
        if path.is_symlink() or not path.is_file() or path.stat().st_size > media.MAX_BYTES:
            continue
        data = path.read_bytes()
        if not data:
            continue
        sink.raw_sql.attach(event, data, MAX_IMAGE_BYTES, path=filename)
        found = sink.raw_sql.rows("SELECT SHA2(data,256) FROM mcqq_group_ai_attachment WHERE event_id=%s", (event,))
        if found != [(hashlib.sha256(data).hexdigest(),)]:
            raise RuntimeError("MySQL attachment readback differs from local image")
        copied["attachments"] += 1


def mysql_reports(source, store, copied):
    for group, day in source.execute("SELECT group_id,day FROM group_ai_daily"):
        pages = source.execute("""SELECT page,image FROM group_ai_daily_images
                                  WHERE group_id=? AND day=? ORDER BY page""", (group, day)).fetchall()
        store.import_report(group, day, pages)
        if store.staged_report(group, day) != (True, pages):
            raise RuntimeError("MySQL staged report readback differs from SQLite")
        copied["reports"] += 1
    for group, day in source.execute("SELECT group_id,day FROM group_ai_daily_start"):
        store.previous_report_groups((group,), day)
        actual = store.rows("SELECT day FROM mcqq_group_ai_daily_start WHERE group_id=%s", (group,))
        if actual != [(day,)]:
            raise RuntimeError("MySQL report calendar readback differs from SQLite")
        copied["report_groups"] += 1


def mysql_quotas(source, options, copied):
    exists = source.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='group_command_quota'").fetchone()
    if not exists:
        return
    with pymysql.connect(**options) as db, db.cursor() as cursor:
        for command, group in source.execute("SELECT DISTINCT command,group_id FROM group_command_quota ORDER BY command,group_id"):
            lock_mysql_group(cursor, command, group)
            for member, created in source.execute(
                    "SELECT member_id,created FROM group_command_quota WHERE command=? AND group_id=?", (command, group)):
                values = (command, group, member, created)
                cursor.execute("""INSERT INTO mcqq_group_command_quota (command_name,group_id,member_id,created)
                    SELECT %s,%s,%s,%s WHERE NOT EXISTS (SELECT 1 FROM mcqq_group_command_quota
                    WHERE command_name=%s AND group_id=%s AND member_id=%s AND created=%s)""", (*values, *values))
                cursor.execute("""SELECT 1 FROM mcqq_group_command_quota
                                  WHERE command_name=%s AND group_id=%s AND member_id=%s AND created=%s""", values)
                if not cursor.fetchone():
                    raise RuntimeError("MySQL quota readback differs from SQLite")
                copied["quota_events"] += 1
            db.commit()


def migrate(source, sink, only=None, quota_options=None):
    copied = defaultdict(int)
    if sink.raw_sql is not None and only in (None, "history"):
        mysql_history(source, sink, copied)
    if sink.raw is not None and only in (None, "history"):
        rows = source.execute("""SELECT id,event_id,group_id,member_id,text,image_path,display_name,created,avatar_url
                                 FROM group_ai_history ORDER BY id""")
        avatars = {}
        while batch := rows.fetchmany(200):
            documents = {
                event: {"group": group, "member": member, "text": text, "image": image,
                        "name": name, "created": created, "order": order, "avatar": avatar}
                for order, event, group, member, text, image, name, created, avatar in batch
            }
            sink.raw.bulk_write([pymongo.UpdateOne({"_id": event}, {"$setOnInsert": data}, upsert=True)
                                 for event, data in documents.items()], ordered=False)
            actual = {row.pop("_id"): row for row in sink.raw.find({"_id": {"$in": list(documents)}})}
            if actual != documents:
                raise RuntimeError("MongoDB message readback differs from SQLite")
            for row in documents.values():
                ident = row["group"], row["member"]
                previous = avatars.get(ident)
                if row["avatar"] and (not previous or row["created"] >= previous[1]):
                    avatars[ident] = row["avatar"], row["created"]
            copied["messages"] += len(documents)
        for group, member, name, updated, profile_avatar, avatar_updated in source.execute(
                "SELECT group_id,member_id,display_name,updated,avatar_url,avatar_updated FROM group_ai_profiles"):
            sink.update_profile(group, member, name, "", updated)
            profile = sink.profiles.find_one({"group": group, "member": member})
            if name and (not profile or profile.get("name") != name):
                raise RuntimeError("MongoDB member profile readback differs from SQLite")
            candidate = avatars.get((group, member))
            if profile_avatar and (not candidate or avatar_updated > candidate[1]):
                avatars[group, member] = profile_avatar, avatar_updated
            copied["profiles"] += 1
        for (group, member), (avatar, created) in avatars.items():
            sink.update_profile(group, member, "", avatar, created)
            profile = sink.profiles.find_one({"group": group, "member": member})
            if not profile or profile.get("avatar") != avatar:
                raise RuntimeError("MongoDB avatar reference readback differs from SQLite")
            copied["avatar_references"] += 1
    if sink.mysql is not None and only in (None, "memory"):
        rows = source.execute("SELECT group_id,member_id,summary,embedding,created FROM group_ai_memory ORDER BY id")
        while batch := rows.fetchmany(200):
            sink.import_memories(batch)
            with pymysql.connect(**sink.mysql) as db, db.cursor() as cursor:
                for group, member, summary, embedding, _ in batch:
                    digest = hashlib.sha256(summary.encode()).digest()
                    cursor.execute("""SELECT summary,embedding FROM mcqq_group_ai_memory
                                      WHERE group_id=%s AND member_id=%s AND digest=%s""", (group, member, digest))
                    row = cursor.fetchone()
                    if not row or row[0] != summary or json.loads(row[1]) != json.loads(embedding):
                        raise RuntimeError("MySQL memory readback differs from SQLite")
                    copied["memories"] += 1
    if sink.report_store is not sink.local and only in (None, "reports"):
        mysql_reports(source, sink.report_store, copied)
    if quota_options is not None and only in (None, "quota"):
        mysql_quotas(source, quota_options, copied)
    return {key: copied[key] for key in ("messages", "profiles", "avatar_references", "attachments",
                                         "memories", "reports", "report_groups", "quota_events")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("history", "memory", "reports", "quota"))
    args = parser.parse_args()
    settings = load()
    db_path = Path(settings["database"])
    storage = settings.get("group_ai_storage", {})
    selected = {role for role in ("history", "memory", "reports", "quota")
                if storage.get(role) in ("mysql", "mongodb")}
    if not selected:
        raise SystemExit("Select a durable external backend before migrating")
    if args.only and args.only not in selected:
        raise SystemExit("Select the external backend for the requested migration component")
    local = History(str(db_path), db_path.parent / "group-ai-images")
    external = ExternalHistory(storage, local)
    try:
        with sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True) as source:
            source.execute("BEGIN")
            print(json.dumps(migrate(source, external, args.only, mysql_options(settings)), sort_keys=True))
    finally:
        external.close()


if __name__ == "__main__":
    main()
