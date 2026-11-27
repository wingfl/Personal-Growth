# -*- coding: utf-8 -*-
"""模型驱动的数据访问层。

所有写入都遵循 schema/model.json 的约束（必填、枚举、范围、不可修改字段、
乐观锁 revision），并自动追加 audit_log，对应需求 1.4①③④⑦ 与规则 J16/J18。
"""
import json
import os
import sqlite3

from .ids import now_iso, uuid7
from .model_meta import Model, ModelError, ValidationError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_SQL = os.path.join(ROOT, "schema", "schema.sql")
DEFAULT_DB = os.path.join(ROOT, "data", "growth.db")


class Conflict(ModelError):
    """并发写入冲突：revision 与期望值不一致。"""


class NotFound(ModelError):
    pass


class Store:
    def __init__(self, db_path=None, model=None, actor_type="user"):
        self.db_path = db_path or DEFAULT_DB
        self.model = model or Model.load()
        self.actor_type = actor_type
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")

    # ---- 生命周期 ---------------------------------------------------
    @classmethod
    def init(cls, db_path=None, schema_sql=None):
        """按 schema/schema.sql 建库（文件已无 PRAGMA 语句，可直接 executescript）。"""
        db_path = db_path or DEFAULT_DB
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        with open(schema_sql or SCHEMA_SQL, encoding="utf-8") as fp:
            ddl = fp.read()
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(ddl)
            conn.commit()
        finally:
            conn.close()
        return db_path

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.close()
        return False

    # ---- 读取 -------------------------------------------------------
    def get(self, entity, rid, include_deleted=False):
        sql = "SELECT * FROM %s WHERE id = ?" % self.model.entity(entity)["id"]
        if not include_deleted and self._has(entity, "deleted_at"):
            sql += " AND deleted_at IS NULL"
        row = self.conn.execute(sql, (rid,)).fetchone()
        if row is None:
            raise NotFound("%s 中不存在记录 %s" % (entity, rid))
        return dict(row)

    def find_one(self, entity, **where):
        rows = self.list(entity, where=where, limit=1)
        return rows[0] if rows else None

    def _has(self, entity, field):
        return field in self.model.fields(entity)

    def list(self, entity, where=None, limit=100, offset=0, include_deleted=False, order_by=None):
        self.model.entity(entity)
        clauses, params = [], []
        for key, value in (where or {}).items():
            self.model.field(entity, key)
            if value is None:
                clauses.append("%s IS NULL" % key)
            else:
                clauses.append("%s = ?" % key)
                params.append(value)
        # audit_log 等只增不改的表没有 deleted_at
        if not include_deleted and self._has(entity, "deleted_at"):
            clauses.append("deleted_at IS NULL")
        sql = "SELECT * FROM %s" % entity
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY %s" % (order_by or "id DESC")
        sql += " LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [dict(r) for r in self.conn.execute(sql, params)]

    def count(self, entity, where=None, include_deleted=False):
        sql = "SELECT COUNT(*) FROM %s" % entity
        clauses, params = [], []
        for key, value in (where or {}).items():
            self.model.field(entity, key)
            clauses.append("%s = ?" % key)
            params.append(value)
        if not include_deleted and self._has(entity, "deleted_at"):
            clauses.append("deleted_at IS NULL")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        return self.conn.execute(sql, params).fetchone()[0]

    def stats(self):
        out = {}
        for name in self.model.entities:
            out[name] = self.count(name)
        return out

    def query(self, sql, params=()):
        return [dict(r) for r in self.conn.execute(sql, params)]

    # ---- 写入 -------------------------------------------------------
    def insert(self, entity, values, actor_type=None, write_audit=True, remark=None,
               proposal_id=None, job_id=None):
        meta = self.model.entity(entity)
        base_group = self.model.base_group(entity)
        now = now_iso()
        payload = dict(values)
        payload.setdefault("id", uuid7())
        payload.setdefault("created_at", now)
        if base_group == "base":
            payload.setdefault("updated_at", now)
            payload.setdefault("revision", 1)
        for key, value in self.model.defaults_for(entity, payload).items():
            payload.setdefault(key, value)

        clean = self.model.validate_values(entity, payload, require_all=True)
        cols = sorted(clean)
        sql = "INSERT INTO %s (%s) VALUES (%s)" % (
            meta["id"], ", ".join(cols), ", ".join("?" * len(cols)))
        try:
            self.conn.execute(sql, [clean[c] for c in cols])
        except sqlite3.IntegrityError as exc:
            raise ModelError("写入 %s 失败：%s" % (entity, exc))
        if write_audit:
            self._write_audit(entity, clean["id"], "create", None, clean, actor_type, remark,
                              proposal_id, job_id)
        return clean["id"]

    def _require_mutable(self, entity):
        """只追加表（base_group=base_append_only，如 audit_log）不允许改写与删除。"""
        group = self.model.base_group(entity)
        if group != "base":
            raise ModelError("%s 使用字段组 %s，是只追加表，不支持修改或删除" % (entity, group))

    def update(self, entity, rid, patch, expected_revision=None, actor_type=None, remark=None,
               proposal_id=None, job_id=None):
        self._require_mutable(entity)
        fields = self.model.fields(entity)
        before = self.get(entity, rid)
        if expected_revision is not None and int(before["revision"]) != int(expected_revision):
            raise Conflict(
                "%s %s 的 revision 已变为 %s（期望 %s），请重新读取后再改"
                % (entity, rid, before["revision"], expected_revision))
        # imm 字段的语义是「只允许落一次」：首次写入（当前还是空）允许，之后任何修改都拒绝。
        # 这样引擎可以在作业结束时补记 duration_ms / token_usage 这类一次性结果，
        # 但已经记下的原始正文、引用原文永远改不了（需求 1.4①）。
        locked = [k for k in patch if fields[k].get("imm") and before.get(k) not in (None, "")]
        if locked:
            raise ModelError("%s 的字段一旦写入就不可修改：%s" % (entity, "、".join(sorted(locked))))
        clean = self.model.validate_values(entity, patch, require_all=False)
        if not clean:
            return int(before["revision"])
        now = now_iso()
        new = dict(before)
        new.update(clean)
        new["updated_at"] = now
        new["revision"] = int(before["revision"]) + 1
        sets = ", ".join("%s = ?" % c for c in clean)
        guard = " AND deleted_at IS NULL" if self._has(entity, "deleted_at") else ""
        sql = ("UPDATE %s SET %s, updated_at = ?, revision = ? "
               "WHERE id = ? AND revision = ?%s" % (entity, sets, guard))
        params = [clean[c] for c in clean] + [now, new["revision"], rid, before["revision"]]
        cur = self.conn.execute(sql, params)
        if cur.rowcount != 1:
            raise Conflict("%s %s 在本次写入前被其他操作修改，请重试" % (entity, rid))
        after = dict(before)
        after.update(clean)
        after["updated_at"] = now
        after["revision"] = new["revision"]
        self._write_audit(entity, rid, "update", before, {**clean, "revision": new["revision"]},
                          actor_type, remark, proposal_id, job_id)
        return new["revision"]

    def soft_delete(self, entity, rid, expected_revision=None, actor_type=None, remark=None,
                    proposal_id=None, job_id=None):
        self._require_mutable(entity)
        before = self.get(entity, rid)
        if expected_revision is not None and int(before["revision"]) != int(expected_revision):
            raise Conflict("%s %s 的 revision 已变为 %s" % (entity, rid, before["revision"]))
        now = now_iso()
        revision = int(before["revision"]) + 1
        cur = self.conn.execute(
            "UPDATE %s SET deleted_at = ?, updated_at = ?, revision = ? "
            "WHERE id = ? AND revision = ? AND deleted_at IS NULL" % entity,
            (now, now, revision, rid, before["revision"]))
        if cur.rowcount != 1:
            raise Conflict("%s %s 已被删除或被并发修改" % (entity, rid))
        self._write_audit(entity, rid, "delete", before, {"deleted_at": now, "revision": revision},
                          actor_type, remark, proposal_id, job_id)
        return revision

    def log_action(self, entity, rid, action, before=None, after=None, actor_type=None, remark=None,
                   proposal_id=None, job_id=None):
        """记录非增删改的档案动作（confirm / reject / export / merge / split 等）。"""
        self._write_audit(entity, rid, action, before, after, actor_type, remark,
                          proposal_id, job_id)

    # ---- 变更历史 ---------------------------------------------------
    def _write_audit(self, entity, rid, action, before, after, actor_type=None, remark=None,
                     proposal_id=None, job_id=None):
        values = {
            "id": uuid7(),
            "entity_type": entity,
            "entity_id": rid,
            "action": action,
            "before_payload": json.dumps(before, ensure_ascii=False, default=str) if before else None,
            "after_payload": json.dumps(after, ensure_ascii=False, default=str) if after else None,
            "actor_type": actor_type or self.actor_type,
            "occurred_at": now_iso(),
            "remark": remark,
            "proposal_id": proposal_id,
            "job_id": job_id,
            "created_at": now_iso(),
        }
        clean = self.model.validate_values("audit_log", values, require_all=True)
        cols = sorted(clean)
        self.conn.execute(
            "INSERT INTO audit_log (%s) VALUES (%s)" % (", ".join(cols), ", ".join("?" * len(cols))),
            [clean[c] for c in cols])
        return clean["id"]

    def history(self, entity, rid, limit=100):
        # 同一秒内的多条审计要按「写入顺序」倒序，而不是按 UUID 倒序：
        # UUIDv7 只有毫秒级有序，同毫秒的随机位会让先后不可预测（见 app/ids.py:9）。
        return self.query(
            "SELECT * FROM audit_log WHERE entity_type = ? AND entity_id = ? "
            "ORDER BY occurred_at DESC, rowid DESC LIMIT ?", (entity, rid, limit))

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()
