# -*- coding: utf-8 -*-
"""按 RFC 9562 生成 UUIDv7（时间有序），以及 UTC 时间字符串工具。"""
import os
import time
import uuid
from datetime import date, datetime, timedelta, timezone


def uuid7() -> str:
    """UUIDv7：前 48 位为毫秒时间戳，保证 B 树索引的写入局部性。"""
    ms = int(time.time() * 1000) & ((1 << 48) - 1)
    buf = bytearray(ms.to_bytes(6, "big") + os.urandom(10))
    buf[6] = (buf[6] & 0x0F) | 0x70   # version 7
    buf[8] = (buf[8] & 0x3F) | 0x80   # variant 10
    return str(uuid.UUID(bytes=bytes(buf)))


def now_iso() -> str:
    """UTC 时间字符串，与模型「时间统一 UTC」的约定一致。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def date_iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def month_range(year: int, month: int):
    start = date(year, month, 1)
    end = date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)
    return start, end


def quarter_range(year: int, quarter: int):
    start_month = (quarter - 1) * 3 + 1
    start = date(year, start_month, 1)
    end_month = start_month + 2
    end = date(year + (end_month == 12), (end_month % 12) + 1, 1) - timedelta(days=1)
    return start, end


def week_range(year: int, week: int):
    start = date.fromisocalendar(year, week, 1)
    return start, start + timedelta(days=6)
