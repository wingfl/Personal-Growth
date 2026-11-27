# -*- coding: utf-8 -*-
"""读取 schema/model.json，为应用层提供实体/字段/枚举元数据与取值校验。

设计原则（对应需求 1.4②「结构化档案独立于 Agent」）：
应用与数据库结构都由 schema/model.json 驱动，模型改动后重新生成 schema.sql 即可，
业务代码不需要跟着硬编码字段名。
"""
import json
import os
import re
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(ROOT, "schema", "model.json")

# 由 store 自动生成、调用方不必提供的字段
AUTO_FIELDS = {"id", "created_at", "updated_at", "revision", "deleted_at"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?Z?)?$")


class ModelError(Exception):
    """模型使用错误（字段不存在、取值不合法、字段不可修改等）。"""


class ValidationError(ModelError):
    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("；".join(self.problems))


class Model:
    def __init__(self, doc):
        self.doc = doc
        self.version = doc.get("meta", {}).get("version")
        self.entities = {e["id"]: e for e in doc["entities"]}
        self.enums = doc.get("enums", {})
        for e in self.entities.values():
            e["_fields"] = {f["n"]: f for f in e.get("full_fields", [])}

    @classmethod
    def load(cls, path=None):
        path = path or os.environ.get("GROWTH_MODEL") or MODEL_PATH
        with open(path, encoding="utf-8") as fp:
            return cls(json.load(fp))

    # ---- 元数据查询 -------------------------------------------------
    def entity(self, name):
        try:
            return self.entities[name]
        except KeyError:
            raise ModelError("未知实体：%s（模型中共 %d 个实体）" % (name, len(self.entities)))

    def fields(self, name):
        return self.entity(name)["_fields"]

    def field(self, entity, field):
        try:
            return self.fields(entity)[field]
        except KeyError:
            raise ModelError("实体 %s 不存在字段 %s" % (entity, field))

    def enum_values(self, name):
        entry = self.enums.get(name)
        if entry is None:
            raise ModelError("未知枚举：%s" % name)
        return [code for code, _label, _desc in entry["v"]]

    def enum_label(self, name, code):
        for c, label, _desc in self.enums.get(name, {}).get("v", []):
            if c == code:
                return label
        return code

    def ref_targets(self, field):
        """ref 字段的可指向对象：ENTITY_TYPE 表示 44 个实体中的任意一个。"""
        if field.get("ref") == "ENTITY_TYPE":
            return sorted(self.entities)
        if field.get("ref"):
            return [field["ref"]]
        return []

    def base_group(self, entity):
        return self.entity(entity).get("base_group", "base")

    # ---- 校验与规范化 -----------------------------------------------
    def validate_values(self, entity, values, require_all=True):
        """按模型校验一组字段值，返回规范化后的 dict；不合法则抛 ValidationError。"""
        meta = self.entity(entity)
        fields = meta["_fields"]
        problems = []

        unknown = [k for k in values if k not in fields]
        if unknown:
            raise ModelError("实体 %s 不存在字段：%s" % (entity, "、".join(sorted(unknown))))

        if require_all:
            for fname, f in fields.items():
                if fname in values or f.get("def") is not None:
                    continue
                if f.get("req"):
                    problems.append("缺少必填字段 %s.%s（%s）" % (entity, fname, f.get("l", "")))

        clean = {}
        for fname, value in values.items():
            f = fields[fname]
            if value is None:
                if f.get("req") and f.get("def") is None and require_all:
                    problems.append("必填字段 %s.%s 不能为空" % (entity, fname))
                else:
                    clean[fname] = None
                continue
            try:
                clean[fname] = self._coerce(entity, f, value)
            except ValueError as exc:
                problems.append(str(exc))

        if problems:
            raise ValidationError(problems)
        return clean

    def _coerce(self, entity, f, value):
        fname, ftype = f["n"], f["t"]
        label = "%s.%s" % (entity, fname)

        if ftype == "boolean":
            if isinstance(value, bool):
                return 1 if value else 0
            if isinstance(value, int) and value in (0, 1):
                return value
            if isinstance(value, str) and value.strip().lower() in ("1", "0", "true", "false", "yes", "no"):
                return 1 if value.strip().lower() in ("1", "true", "yes") else 0
            raise ValueError("%s 需要布尔值，收到 %r" % (label, value))

        if ftype == "integer":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                if not (isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip())):
                    raise ValueError("%s 需要整数，收到 %r" % (label, value))
                value = int(value)
            return self._check_range(label, f, int(value))

        if ftype == "decimal":
            try:
                return self._check_range(label, f, float(value))
            except (TypeError, ValueError):
                raise ValueError("%s 需要数值，收到 %r" % (label, value))

        if ftype == "enum":
            if value not in self.enum_values(f["e"]):
                raise ValueError(
                    "%s 取值 %r 不在枚举 %s 中（可选：%s）"
                    % (label, value, f["e"], "、".join(self.enum_values(f["e"])))
                )
            return value

        if ftype in ("date", "datetime"):
            if isinstance(value, datetime):
                value = value.strftime("%Y-%m-%dT%H:%M:%SZ")
            elif isinstance(value, date):
                value = value.strftime("%Y-%m-%d")
            if not isinstance(value, str) or not _DATETIME_RE.match(value):
                raise ValueError("%s 需要 %s（如 2024-03-01 或 2024-03-01T08:30:00Z），收到 %r" % (label, ftype, value))
            if ftype == "date" and not _DATE_RE.match(value):
                raise ValueError("%s 只接受日期（YYYY-MM-DD），收到 %r" % (label, value))
            return value

        if ftype == "json":
            if isinstance(value, str):
                try:
                    json.loads(value)
                except ValueError:
                    raise ValueError("%s 需要合法 JSON 文本" % label)
                return value
            return json.dumps(value, ensure_ascii=False)

        if ftype == "ref":
            if f.get("ref") == "ENTITY_TYPE":
                if value not in self.entities:
                    raise ValueError("%s 取值 %r 不是已登记的实体类型" % (label, value))
                return value
            return value

        # uuid / string / text / longtext / file
        return value

    def _check_range(self, label, f, value):
        if f.get("min") is not None and value < f["min"]:
            raise ValueError("%s 不得小于 %s，收到 %s" % (label, f["min"], value))
        if f.get("max") is not None and value > f["max"]:
            raise ValueError("%s 不得大于 %s，收到 %s" % (label, f["max"], value))
        return value

    # ---- 默认值 -----------------------------------------------------
    def defaults_for(self, entity, values):
        out = {}
        for fname, f in self.fields(entity).items():
            if fname not in values and f.get("def") is not None:
                out[fname] = f["def"]
        # AI 写出的结构化记录默认待用户确认（需求 1.4④）
        if "review_status" in self.fields(entity) and "review_status" not in values:
            origin = values.get("origin")
            out["review_status"] = "pending" if origin == "ai_agent" else "confirmed"
        return out
