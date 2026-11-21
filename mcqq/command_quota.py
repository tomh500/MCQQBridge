"""Atomic rolling per-member quotas for group commands."""
from contextlib import closing
from datetime import datetime
import sqlite3
import time

from .feature_policy import ZONE


def calculate(events, limits, now):
    status = []
    for rule in limits:
        window = rule["seconds"]
        cap = rule["max_requests"]
        recent = [stamp for stamp in events if stamp > now-window]
        remaining = max(0, cap-len(recent))
        next_available = max(0, len(recent)-cap)
        resets = recent[next_available] + window if recent else now
        status.append((rule["label"], remaining, cap, resets))
    return status if any(remaining == 0 for _, remaining, _, _ in status) else None


def ensure_table(db):
    db.execute("""CREATE TABLE IF NOT EXISTS group_command_quota (
               command TEXT NOT NULL, group_id TEXT NOT NULL, member_id TEXT NOT NULL, created REAL NOT NULL)""")
    db.execute("""CREATE INDEX IF NOT EXISTS group_command_quota_member
               ON group_command_quota (command,group_id,member_id,created)""")
    db.execute("""CREATE INDEX IF NOT EXISTS group_command_quota_expiry
               ON group_command_quota (command,created)""")


def take(database, command, group, member, limits, *, now=None):
    with closing(sqlite3.connect(database, timeout=8)) as db, db:
        ensure_table(db)
        db.execute("BEGIN IMMEDIATE")
        now = time.time() if now is None else now
        oldest = now - max(item["seconds"] for item in limits)
        db.execute("DELETE FROM group_command_quota WHERE command=? AND created<=?", (command, oldest))
        events = [row[0] for row in db.execute(
            """SELECT created FROM group_command_quota
               WHERE command=? AND group_id=? AND member_id=? ORDER BY created""",
            (command, group, member))]
        if (status := calculate(events, limits, now)) is not None:
            return status
        db.execute("INSERT INTO group_command_quota VALUES (?,?,?,?)", (command, group, member, now))
        return None


def reset(database, command, group):
    with closing(sqlite3.connect(database, timeout=8)) as db, db:
        ensure_table(db)
        db.execute("DELETE FROM group_command_quota WHERE command=? AND group_id=?", (command, group))


def mysql_options(settings):
    storage = settings.get("group_ai_storage", {})
    backend = storage.get("quota", "sqlite")
    if backend == "sqlite":
        return None
    if backend != "mysql":
        raise ValueError("Unsupported group command quota backend")
    from .group_mysql import mysql_settings
    return mysql_settings(storage)


def lock_mysql_group(cursor, command, group):
    cursor.execute("""INSERT INTO mcqq_group_command_quota_lock (command_name,group_id) VALUES (%s,%s)
                   ON DUPLICATE KEY UPDATE group_id=mcqq_group_command_quota_lock.group_id""", (command, group))


def take_configured(settings, command, group, member, limits):
    if not limits or any(not isinstance(rule.get("seconds"), int) or rule["seconds"] < 1
                         or not isinstance(rule.get("max_requests"), int) or rule["max_requests"] < 1
                         or not rule.get("label") for rule in limits):
        raise ValueError("Invalid command quota limits")
    options = mysql_options(settings)
    if options is None:
        return take(settings["database"], command, group, member, limits)
    import pymysql
    with pymysql.connect(**options) as db, db.cursor() as cursor:
        lock_mysql_group(cursor, command, group)
        cursor.execute("SELECT UNIX_TIMESTAMP(CURRENT_TIMESTAMP(6))")
        now = float(cursor.fetchone()[0])
        oldest = now - max(item["seconds"] for item in limits)
        cursor.execute("""DELETE FROM mcqq_group_command_quota
                          WHERE command_name=%s AND group_id=%s AND created<=%s""", (command, group, oldest))
        cursor.execute("""SELECT created FROM mcqq_group_command_quota
                          WHERE command_name=%s AND group_id=%s AND member_id=%s ORDER BY created""",
                       (command, group, member))
        status = calculate([row[0] for row in cursor], limits, now)
        if status is None:
            cursor.execute("""INSERT INTO mcqq_group_command_quota (command_name,group_id,member_id,created)
                              VALUES (%s,%s,%s,%s)""", (command, group, member, now))
        db.commit()
    return status


def reset_configured(settings, command, group):
    options = mysql_options(settings)
    if options is None:
        return reset(settings["database"], command, group)
    import pymysql
    with pymysql.connect(**options) as db, db.cursor() as cursor:
        lock_mysql_group(cursor, command, group)
        cursor.execute("DELETE FROM mcqq_group_command_quota WHERE command_name=%s AND group_id=%s",
                       (command, group))
        db.commit()


def rejected_message(status):
    exhausted = "/".join(label for label, remaining, _, _ in status if remaining == 0)
    balances = "，".join(f"{label}限额 {remaining*100//cap}%" for label, remaining, cap, _ in status)
    resets = "，".join(datetime.fromtimestamp(stamp, ZONE).strftime("%m-%d %H:%M:%S")
                       for _, _, _, stamp in status)
    return f"您的{exhausted}限额不足。当前剩余{balances}。重置时间分别为 {resets}（北京时间）。"
