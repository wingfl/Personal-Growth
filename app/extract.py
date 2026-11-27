# -*- coding: utf-8 -*-
"""第 4 步（需求第 7 章第 4 项）：AI 提取、匹配、归并、审核。

数据流向：

    原始资料 source_document / source_fragment
        │
        │  Extraction.run()：组提示词 → 调模型 → 校验 → 落库为建议
        ▼
    ai_job（用了什么模型、什么提示词、送进去多少片段、产出多少建议）
        │
        ├── change_proposal（status=pending；proposed_payload 只包含模型字段）
        └── proposal_evidence（引用原文片段与关键原句，审核时直接看得到出处）
        │
        │  Review.confirm()：用户确认 / 改后确认
        ▼
    project / business_system / function_module / work_item + provenance_link

两条硬约束贯穿本模块（需求 1.4④、数据规则 C1/C2）：
  * 模型永远不能直接写正式档案，只能生成 change_proposal；
  * 每条建议都能追到 ai_job 与原文片段，用户拒绝或修改都留痕。
"""
import json
import os
import re
from datetime import datetime, timezone

from .archive import Archive, ArchiveError, precision_from_period
from .ids import now_iso, uuid7
from .llm import LLMError, LLMClient, resolve_config
from .model_meta import Model, ModelError, ValidationError
from .store import Conflict, NotFound

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMPTS_DIR = os.path.join(ROOT, "prompts")

# 模型输出里的分节键 → 实体类型（document_extract 的契约）
SECTION_ENTITY = {
    "items": "work_item",
    "new_projects": "project",
    "new_systems": "business_system",
    "new_modules": "function_module",
    "new_domains": "work_domain",
}
NAME_FIELD = {
    "work_item": "title",
    "project": "name",
    "business_system": "name",
    "function_module": "name",
    "work_domain": "name",
}
# 实体 → 在事项上对应的外键字段（同一批次内确认后回填）
FK_ON_ITEM = {
    "project": "project_id",
    "business_system": "system_id",
    "function_module": "module_id",
    "work_domain": "domain_id",
}
# 归档时忽略的模型输出字段（不是实体字段）
IGNORED_KEYS = {"evidence", "system", "project", "module", "domain"}
# 由引擎/数据库自动填写的字段：审核界面不该把它们当成「模型漏填的必填项」
ENGINE_FIELDS = {"id", "created_at", "updated_at", "revision", "deleted_at",
                 "origin", "review_status", "reviewed_at", "confidence"}
_PLACEHOLDER_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


class ExtractError(Exception):
    """提取或审核流程中的错误（配置缺失、输出不合契约、建议无法写入等）。"""


def render_prompt(template, variables):
    """替换 {变量}；模板里的 JSON 花括号不受影响（只认小写标识符占位符）。"""
    missing = []

    def repl(match):
        name = match.group(1)
        if name in variables:
            value = variables[name]
            return "" if value is None else str(value)
        missing.append(name)
        return match.group(0)

    text = _PLACEHOLDER_RE.sub(repl, template)
    if missing:
        raise ExtractError("提示词模板缺少变量：%s" % "、".join(sorted(set(missing))))
    return text


def parse_json_reply(text):
    """把模型回复解析成 JSON 对象：容忍 ``` 代码块包裹与前后多余文字。"""
    body = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", body, re.S)
    if fence:
        body = fence.group(1).strip()
    start = body.find("{")
    if start < 0:
        raise LLMError("模型回复里找不到 JSON 对象：%s" % body[:200], code="parse_failed")
    try:
        obj, _end = json.JSONDecoder().raw_decode(body[start:])
    except ValueError as exc:
        raise LLMError("模型回复的 JSON 无法解析：%s（原文片段：%s）"
                       % (exc, body[start:start + 200]), code="parse_failed")
    if not isinstance(obj, dict):
        raise LLMError("模型回复的 JSON 顶层必须是对象", code="parse_failed")
    return obj


class Extraction:
    """提示词/工作流配置 + 一次提取作业的执行与落库。"""

    def __init__(self, store, llm=None, archive=None, model=None):
        self.store = store
        self.model = model or store.model
        self.archive = archive or Archive(store)
        self.llm = llm or LLMClient()

    # ---- 提示词与工作流配置 -----------------------------------------
    def prompt_files(self):
        if not os.path.isdir(PROMPTS_DIR):
            return []
        return [os.path.join(PROMPTS_DIR, n) for n in sorted(os.listdir(PROMPTS_DIR))
                if n.endswith(".json")]

    def seed_config(self):
        """把 prompts/*.json 写入 prompt_template 与 agent_workflow（同名同版本则更新）。"""
        out = {"prompt_templates": [], "workflows": []}
        for path in self.prompt_files():
            with open(path, encoding="utf-8") as fp:
                doc = json.load(fp)
            out["prompt_templates"].append(self._seed_template(doc, path))
            if doc.get("workflow"):
                out["workflows"].append(self._seed_workflow(doc["workflow"], out["prompt_templates"][-1]))
        self.store.commit()
        return out

    def _seed_template(self, doc, path):
        existing = self.store.find_one(
            "prompt_template", name=doc["name"], job_type=doc["job_type"], version=doc["version"])
        values = {
            "name": doc["name"],
            "job_type": doc["job_type"],
            "version": doc["version"],
            "system_prompt": doc["system_prompt"],
            "user_prompt_template": doc["user_prompt_template"],
            "variables": json.dumps(doc.get("variables", []), ensure_ascii=False),
            "output_schema": json.dumps(doc.get("output_schema", {}), ensure_ascii=False),
            "output_format_note": doc.get("output_format_note"),
            "applies_to_scopes": json.dumps(doc.get("applies_to_scopes", []), ensure_ascii=False),
            "is_active": True,
        }
        if existing:
            patch = {k: v for k, v in values.items() if k not in ("name", "job_type", "version")}
            self.store.update("prompt_template", existing["id"], patch)
            return {"id": existing["id"], "name": doc["name"], "version": doc["version"],
                    "action": "updated", "file": os.path.relpath(path, ROOT)}
        rid = self.store.insert("prompt_template", values)
        return {"id": rid, "name": doc["name"], "version": doc["version"],
                "action": "created", "file": os.path.relpath(path, ROOT)}

    def _seed_workflow(self, doc, template_info):
        existing = self.store.find_one(
            "agent_workflow", name=doc["name"], job_type=doc["job_type"], version=doc.get("version", 1))
        values = {
            "name": doc["name"],
            "job_type": doc["job_type"],
            "description": doc.get("description"),
            "steps": json.dumps(doc.get("steps", []), ensure_ascii=False),
            "version": doc.get("version", 1),
            "is_active": True,
            "target_models": json.dumps(doc.get("target_models", []), ensure_ascii=False),
            "output_constraints": doc.get("output_constraints"),
            "applies_to_scopes": json.dumps(doc.get("applies_to_scopes", []), ensure_ascii=False),
            "default_prompt_template_id": template_info["id"],
        }
        if existing:
            patch = {k: v for k, v in values.items() if k not in ("name", "job_type", "version")}
            self.store.update("agent_workflow", existing["id"], patch)
            return {"id": existing["id"], "name": doc["name"], "action": "updated"}
        rid = self.store.insert("agent_workflow", values)
        return {"id": rid, "name": doc["name"], "action": "created"}

    def active_template(self, job_type="document_extract"):
        rows = self.store.list("prompt_template", {"job_type": job_type, "is_active": 1},
                               limit=50, order_by="version DESC")
        if not rows:
            raise ExtractError(
                "还没有可用的提示词模板，请先执行：python -m app.cli ai seed")
        return rows[0]

    def active_workflow(self, job_type="document_extract"):
        rows = self.store.list("agent_workflow", {"job_type": job_type, "is_active": 1},
                               limit=50, order_by="version DESC")
        return rows[0] if rows else None

    # ---- 提取 -------------------------------------------------------
    def run(self, document_id, model=None, max_fragments=None, existing_item_limit=50,
            temperature=None, max_tokens=None, trigger_type="manual", dry_run=False):
        template = self.active_template("document_extract")
        workflow = self.active_workflow("document_extract")
        doc = self._require("source_document", document_id)
        fragments = self.store.list("source_fragment", {"document_id": document_id},
                                    limit=2000, order_by="order_index ASC")
        if not fragments:
            raise ExtractError("资料 %s 还没有可用的来源片段" % document_id)
        if max_fragments:
            fragments = fragments[:max_fragments]
        coverage = self._coverage(doc, fragments)

        if model and self.llm.config.model != model:
            self.llm.config = resolve_config(model=model, timeout=self.llm.config.timeout)

        variables = self._variables(doc, fragments, existing_item_limit)
        messages = [
            {"role": "system", "content": template["system_prompt"]},
            {"role": "user", "content": render_prompt(template["user_prompt_template"], variables)},
        ]
        if dry_run:
            return {"dry_run": True, "messages": messages, "coverage": coverage,
                    "template_id": template["id"],
                    "workflow_id": workflow["id"] if workflow else None}

        job_id = self.store.insert("ai_job", {
            "job_type": "document_extract",
            "trigger_type": trigger_type,
            "input_scope": json.dumps({
                "document_id": document_id,
                "fragment_ids": [f["id"] for f in fragments],
                "max_fragments": max_fragments,
            }, ensure_ascii=False),
            "model_provider": self.llm.config.provider,
            "model_name": self.llm.config.model,
            "prompt_template_id": template["id"],
            "workflow_id": workflow["id"] if workflow else None,
            "status": "running",
            "started_at": now_iso(),
            "input_fragment_count": len(fragments),
        })
        self.store.commit()

        started = datetime.now(timezone.utc)
        try:
            reply = self.llm.chat(messages, temperature=temperature, max_tokens=max_tokens)
            data = parse_json_reply(reply.text)
            batch_id = uuid7()
            period = {"start": doc.get("period_start"), "end": doc.get("period_end"),
                      "precision": precision_from_period(doc.get("period_start"),
                                                         doc.get("period_end"))}
            proposals = self._proposals_from_reply(job_id, batch_id, data, fragments, period)
            duration_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
            # input_fragment_count 在作业创建时已经落库（imm，只能写一次），这里不重复提交
            self.store.update("ai_job", job_id, {
                "status": "succeeded",
                "finished_at": now_iso(),
                "duration_ms": duration_ms,
                "token_usage": json.dumps(reply.usage_summary(), ensure_ascii=False),
                "result_summary": "产出 %d 条待审核建议；覆盖片段 %d/%d" % (
                    len(proposals), coverage["used"], coverage["total"]),
                "proposal_count": len(proposals),
            })
        except Exception as exc:
            # 任何失败（模型报错、输出不合契约、落库校验不通过）都要把作业标成 failed 并提交，
            # 否则会留下一条永远 running 的作业记录。
            code = getattr(exc, "code", None) or (
                "parse_failed" if isinstance(exc, (ValidationError, ModelError)) else "unknown")
            try:
                self.store.update("ai_job", job_id, {
                    "status": "failed",
                    "finished_at": now_iso(),
                    "duration_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                    "error_code": code,
                    "error_message": str(exc)[:2000],
                })
                self.store.commit()
            except Exception:  # 记录失败原因本身失败时，不能掩盖原始错误
                self.store.rollback()
            if isinstance(exc, ExtractError):
                raise
            raise ExtractError("AI 作业失败（%s）：%s" % (code, exc))

        self.store.commit()
        return {"job_id": job_id, "batch_id": batch_id, "proposal_ids": proposals,
                "proposal_count": len(proposals), "duration_ms": duration_ms,
                "usage": reply.usage_summary(), "model": reply.model, "coverage": coverage,
                "notes": data.get("notes") or ""}

    # ---- 上下文与变量 -----------------------------------------------
    def _require(self, entity, rid):
        try:
            return self.store.get(entity, rid)
        except NotFound:
            raise ExtractError("找不到 %s 记录：%s" % (entity, rid))

    @staticmethod
    def _coverage(doc, fragments):
        total = len(fragments)
        used = sum(1 for f in fragments if (f["text"] or "").strip())
        return {"total": total, "used": used,
                "document_title": doc["title"], "doc_type": doc["doc_type"]}

    def _names(self, entity, field="name", limit=80):
        rows = self.store.list(entity, limit=limit, order_by="created_at ASC")
        return [r.get(field) or r["id"] for r in rows]

    def _context(self, item_limit=50):
        items = self.store.list("work_item", limit=item_limit, order_by="occurred_at DESC")
        projects = {p["id"]: p["name"] for p in self.store.list("project", limit=500)}
        lines = []
        for it in items:
            project = projects.get(it.get("project_id")) or "-"
            lines.append("%s｜%s｜%s｜项目=%s" % (it.get("occurred_at") or "-", it["title"],
                                              it.get("item_type") or "-", project))
        return {
            "projects": self._project_names(),
            "systems": self._names("business_system"),
            "modules": self._names("function_module"),
            "domains": self._names("work_domain"),
            "items": lines,
        }

    def _project_names(self):
        rows = self.store.list("project", limit=500, order_by="created_at ASC")
        names = []
        for row in rows:
            names.append(row["name"])
            try:
                for alias in json.loads(row.get("alias_names") or "[]"):
                    if alias:
                        names.append(alias)
            except ValueError:
                pass
        return names

    def _enum_text(self, name):
        return " / ".join(self.model.enum_values(name))

    def _variables(self, doc, fragments, existing_item_limit):
        ctx = self._context(existing_item_limit)
        precision = precision_from_period(doc.get("period_start"), doc.get("period_end"))
        schema = self.model.doc  # 供将来扩展

        lines = []
        for frag in fragments:
            text = (frag["text"] or "").strip().replace("\n", " ")
            if len(text) > 1200:
                text = text[:1200] + "…"
            lines.append("[%s] %s | %s" % (frag["id"], frag.get("heading_path") or "-", text))
        return {
            "document_title": doc["title"],
            "doc_type": doc["doc_type"],
            "period_start": doc.get("period_start") or "未提供",
            "period_end": doc.get("period_end") or "未提供",
            "period_precision": precision,
            "fragment_count": len(fragments),
            "fragments": "\n".join(lines) if lines else "（无）",
            "existing_projects": "、".join(ctx["projects"]) or "（无）",
            "existing_systems": "、".join(ctx["systems"]) or "（无）",
            "existing_modules": "、".join(ctx["modules"]) or "（无）",
            "existing_domains": "、".join(ctx["domains"]) or "（无）",
            "existing_item_count": len(ctx["items"]),
            "existing_items": "\n".join(ctx["items"]) or "（无）",
            "item_type_values": self._enum_text("work_item_type"),
            "project_type_values": self._enum_text("project_type"),
            "project_status_values": self._enum_text("project_status"),
            "system_type_values": self._enum_text("system_type"),
            "system_status_values": self._enum_text("system_status"),
            "module_type_values": self._enum_text("module_type"),
            "role_type_values": self._enum_text("role_type"),
            "date_precision_values": self._enum_text("date_precision"),
            "_schema_keys": len(schema.get("entities", [])),
        }

    # ---- 建议落库 ---------------------------------------------------
    def _proposals_from_reply(self, job_id, batch_id, data, fragments, period=None):
        by_id = {f["id"]: f for f in fragments}
        known = {
            "project": {name: row["id"] for row in self.store.list("project", limit=500)
                        for name in [row["name"]]},
            "business_system": {row["name"]: row["id"]
                                for row in self.store.list("business_system", limit=500)},
            "function_module": {row["name"]: row["id"]
                                for row in self.store.list("function_module", limit=2000)},
            "work_domain": {row["name"]: row["id"]
                            for row in self.store.list("work_domain", limit=500)},
        }
        ids = []
        pending_names = {}   # entity -> name -> 批次内的建议（确认后回填外键）
        created_names = {}   # entity -> {名称}：本批次打算新建的记录
        order = ["new_domains", "new_systems", "new_projects", "new_modules", "items"]
        for section in order:
            for raw in data.get(section) or []:
                if not isinstance(raw, dict):
                    continue
                entity = SECTION_ENTITY[section]
                proposal_id = self._create_proposal(
                    job_id, batch_id, entity, raw, by_id, known, pending_names, created_names,
                    period)
                if proposal_id:
                    ids.append(proposal_id)
        # 模型指出「这份资料还属于哪些已有记录」→ 生成「补来源」建议（跨资料归并，需求场景 2）
        for raw in data.get("link_existing") or []:
            if not isinstance(raw, dict):
                continue
            entity = raw.get("entity")
            name = (raw.get("name") or "").strip()
            if entity not in SECTION_ENTITY.values() or not name:
                continue
            if name in created_names.get(entity, set()):
                continue
            target_id = known.get(entity, {}).get(name)
            if not target_id:
                continue
            evidences = [e for e in (raw.get("evidence") or []) if isinstance(e, dict)]
            proposal_id = self._create_link_proposal(
                job_id, batch_id, entity, target_id, name, evidences, by_id,
                reason=raw.get("reason"))
            if proposal_id:
                ids.append(proposal_id)
        return ids

    def _create_proposal(self, job_id, batch_id, entity, raw, fragments_by_id, known,
                         pending_names, created_names=None, period=None):
        fields = self.model.fields(entity)
        evidences = [e for e in (raw.get("evidence") or []) if isinstance(e, dict)]
        payload = {k: v for k, v in raw.items()
                   if k in fields and k not in IGNORED_KEYS and v not in (None, "", [])}
        payload = self._coerce_json_fields(entity, payload)
        name = payload.get(NAME_FIELD[entity]) or ""
        if not name:
            return None

        # 已存在同名记录：不新建，改为「补来源」的关联建议（需求场景 2：跨资料归并）
        existing_id = known.get(entity, {}).get(name)
        if existing_id:
            return self._create_link_proposal(job_id, batch_id, entity, existing_id, name,
                                              evidences, fragments_by_id)

        # 指向本批次内新建的项目/系统/模块：先记下待关联，等它被确认后回填外键
        pending = []
        if created_names is not None:
            created_names.setdefault(entity, set()).add(name)
        if entity == "work_item":
            for ref_entity, src_key in (("work_domain", "domain"), ("business_system", "system"),
                                        ("project", "project"), ("function_module", "module")):
                ref_name = raw.get(src_key)
                if not ref_name:
                    continue
                fk = FK_ON_ITEM[ref_entity]
                if ref_name in known.get(ref_entity, {}):
                    payload[fk] = known[ref_entity][ref_name]
                else:
                    pending.append("待关联 %s:%s → %s" % (ref_entity, ref_name, fk))
        reason = ""
        # 事项时间：原文没给就用所属资料的期间与精度（需求 6.3 的时间口径），并写进理由供审核者核对。
        if entity == "work_item" and period and period.get("start"):
            if not payload.get("occurred_at"):
                payload["occurred_at"] = period["start"]
                reason = "时间取自资料期间 %s（%s）" % (period["start"], period["precision"])
            if payload.get("date_precision") in (None, "", "unknown"):
                if period.get("precision") not in (None, "", "unknown"):
                    payload["date_precision"] = period["precision"]
        if raw.get("is_fact") is False:
            payload.setdefault("is_fact", 0)
        if pending:
            reason = (reason + "；" if reason else "") + "；".join(pending)

        problems = self._problems(entity, payload, require_all=False)
        requirements = self._problems(entity, payload, require_all=True)
        summary = self._summary(entity, name, evidences, requirements)
        proposal_id = self.store.insert("change_proposal", {
            "job_id": job_id,
            "batch_id": batch_id,
            "change_type": "create",
            "target_entity_type": entity,
            "proposed_payload": json.dumps(payload, ensure_ascii=False),
            "diff_summary": summary,
            "reason": reason or None,
            "status": "pending",
            "priority": 3,
        })
        self._write_evidences(proposal_id, evidences, fragments_by_id)
        if entity in FK_ON_ITEM:
            pending_names.setdefault(entity, {})[name] = proposal_id
        if problems:
            self.store.update("change_proposal", proposal_id, {
                "reason": ((reason + "；") if reason else "")
                          + "建议内容尚不完整：" + "；".join(problems[:5]),
            })
        return proposal_id

    def _create_link_proposal(self, job_id, batch_id, entity, existing_id, name, evidences,
                              fragments_by_id, reason=None):
        frag_ids = [e.get("fragment_id") for e in evidences
                    if e.get("fragment_id") in fragments_by_id]
        if not frag_ids:
            # 模型没给证据时，退化成「正文里提到这个名字的片段」，并补上原句
            evidences, seen = [], set()
            for fid, frag in fragments_by_id.items():
                text = frag["text"] or ""
                pos = text.find(name)
                if pos < 0 or fid in seen:
                    continue
                seen.add(fid)
                start = max(0, pos - 40)
                evidences.append({"fragment_id": fid, "quote": text[start:pos + len(name) + 40],
                                  "relevance_type": "supporting"})
                if len(evidences) >= 3:
                    break
            frag_ids = [e["fragment_id"] for e in evidences]
        if not frag_ids:
            return None
        payload = {"relation": "provenance", "fragment_ids": sorted(set(frag_ids))}
        proposal_id = self.store.insert("change_proposal", {
            "job_id": job_id,
            "batch_id": batch_id,
            "change_type": "link",
            "target_entity_type": entity,
            "target_entity_id": existing_id,
            "proposed_payload": json.dumps(payload, ensure_ascii=False),
            "diff_summary": "给已有%s「%s」补上本次资料的来源（%d 个片段，不新建记录）"
                            % (self.model.entity(entity)["name"], name, len(payload["fragment_ids"])),
            "reason": reason or "档案里已有同名记录，按需求「跨时间工作归并」处理：关联而不是新建",
            "status": "pending",
            "priority": 2,
        })
        self._write_evidences(proposal_id, evidences, fragments_by_id)
        return proposal_id

    def _write_evidences(self, proposal_id, evidences, fragments_by_id):
        seen = set()
        for ev in evidences:
            frag = fragments_by_id.get(ev.get("fragment_id"))
            if not frag:
                continue
            quote = (ev.get("quote") or "").strip() or (frag["text"] or "").strip()[:200]
            key = (frag["id"], quote)
            if key in seen:
                continue
            seen.add(key)
            start = (frag["text"] or "").find(quote) if quote else -1
            values = {
                "proposal_id": proposal_id,
                "fragment_id": frag["id"],
                "quote": quote[:2000],
                "relevance_type": ev.get("relevance_type")
                                  if ev.get("relevance_type") in self.model.enum_values("relevance_type")
                                  else "primary_source",
            }
            if start >= 0:
                values["quote_char_start"] = start
                values["quote_char_end"] = start + len(quote)
            self.store.insert("proposal_evidence", values)

    def _problems(self, entity, payload, require_all):
        try:
            self.model.validate_values(entity, payload, require_all=require_all)
            return []
        except ValidationError as exc:
            problems = list(exc.problems)
        except ModelError as exc:
            return [str(exc)]
        if require_all:
            problems = [p for p in problems
                        if not any("%s.%s" % (entity, name) in p for name in ENGINE_FIELDS)]
        return problems

    def _coerce_json_fields(self, entity, payload):
        """模型有时把 json 字段写成「用分号隔开的文字」，这里统一收敛成数组。"""
        for name, value in list(payload.items()):
            spec = self.model.fields(entity).get(name) or {}
            if spec.get("t") != "json" or not isinstance(value, str):
                continue
            text = value.strip()
            if not text:
                payload.pop(name)
                continue
            try:
                payload[name] = json.loads(text)
            except ValueError:
                parts = [p.strip() for p in re.split(r"[；;、,，\n]", text) if p.strip()]
                payload[name] = parts or [text]
        return payload

    def _summary(self, entity, name, evidences, requirements):
        label = self.model.entity(entity)["name"]
        text = "新增%s「%s」（依据 %d 个原文片段）" % (label, name, len(evidences))
        if requirements:
            text += "；确认前还需要补：" + "、".join(requirements[:4])
        return text

    # ---- 查询 -------------------------------------------------------
    def jobs(self, limit=20):
        return self.store.list("ai_job", limit=limit, order_by="created_at DESC")

    def job(self, job_id):
        return self._require("ai_job", job_id)


class Review:
    """建议审核：列表、查看、确认（含改后确认）、拒绝。"""

    def __init__(self, store, archive=None, extraction=None, model=None):
        self.store = store
        self.model = model or store.model
        self.archive = archive or Archive(store)
        self.extraction = extraction or Extraction(store, archive=self.archive, model=self.model)

    # ---- 查询 -------------------------------------------------------
    def list(self, status=None, job_id=None, batch_id=None, limit=50):
        # store.list 的 where 只支持等值比较（没有 IN），多状态时逐个查询再合并。
        where = {}
        if job_id:
            where["job_id"] = job_id
        if batch_id:
            where["batch_id"] = batch_id
        if not status or status == "all":
            return self.store.list("change_proposal", where or None, limit=limit,
                                   order_by="created_at ASC")
        wanted = [status] if isinstance(status, str) else list(status)
        rows = []
        for one in wanted:
            rows.extend(self.store.list("change_proposal", dict(where, status=one),
                                        limit=limit, order_by="created_at ASC"))
        rows.sort(key=lambda r: (r.get("created_at") or "", r.get("id") or ""))
        return rows[:limit]

    def show(self, proposal_id):
        proposal = self._require(proposal_id)
        evidences = self.store.list("proposal_evidence", {"proposal_id": proposal_id},
                                    limit=200, order_by="created_at ASC")
        for ev in evidences:
            try:
                frag = self.store.get("source_fragment", ev["fragment_id"])
                doc = self.store.get("source_document", frag["document_id"])
                ev["document_title"] = doc["title"]
                ev["heading_path"] = frag["heading_path"]
                ev["fragment_text"] = frag["text"]
            except NotFound:
                ev["document_title"] = "（片段已删除）"
        payload = self._payload(proposal)
        entity = proposal["target_entity_type"]
        out = {
            "proposal": proposal,
            "payload": payload,
            "evidences": evidences,
            "target": None,
            "requirements": [],
        }
        if entity in self.model.entities and proposal["change_type"] in ("create", "update"):
            # link / merge / delete 的 payload 是引擎自己的指令，不做实体字段校验
            out["requirements"] = self.extraction._problems(entity, payload, require_all=True)
        if proposal.get("target_entity_id"):
            try:
                out["target"] = self.store.get(entity, proposal["target_entity_id"])
            except NotFound:
                out["target"] = None
        return out

    def _require(self, proposal_id):
        try:
            return self.store.get("change_proposal", proposal_id)
        except NotFound:
            raise ExtractError("找不到建议：%s" % proposal_id)

    @staticmethod
    def _payload(proposal):
        raw = proposal.get("final_payload") or proposal.get("proposed_payload") or "{}"
        try:
            return json.loads(raw)
        except ValueError:
            return {}

    # ---- 审核动作 ---------------------------------------------------
    def confirm(self, proposal_id, overrides=None, note=None, actor_type="user"):
        proposal = self._require(proposal_id)
        if proposal["status"] not in ("pending",):
            raise ExtractError("建议 %s 已经是 %s，不能重复确认" % (proposal_id, proposal["status"]))
        payload = dict(self._payload(proposal))
        overrides = {k: v for k, v in (overrides or {}).items() if v is not None}
        payload.update(overrides)
        entity = proposal["target_entity_type"]
        change_type = proposal["change_type"]
        job_id = proposal.get("job_id")

        # 写库前先按模型校验，避免把不完整的建议写进正式档案
        if change_type in ("create", "update"):
            if entity not in self.model.entities:
                raise ExtractError("未知实体类型：%s" % entity)
            problems = self.extraction._problems(entity, payload, require_all=True)
            if problems:
                raise ExtractError("建议内容不完整，无法写入：%s（可用 --set 字段=值 补充）"
                                   % "；".join(problems[:6]))

        try:
            applied_entity, applied_id = self._apply(proposal, payload, actor_type, note)
        except (ArchiveError, ModelError, ValidationError, Conflict) as exc:
            self.store.rollback()
            raise ExtractError("写入正式档案失败：%s" % exc)

        status = "modified" if overrides else "confirmed"
        duration = self._review_duration_ms(proposal)
        patch = {
            "status": status,
            "reviewed_at": now_iso(),
            "applied_at": now_iso(),
            "applied_entity_id": applied_id,
            "reviewer_note": note,
        }
        if status == "modified":
            patch["final_payload"] = json.dumps(payload, ensure_ascii=False)
        if duration is not None:
            patch["review_duration_ms"] = duration
        self.store.update("change_proposal", proposal_id, patch)
        if applied_entity and applied_id:
            self.store.log_action(applied_entity, applied_id, "confirm",
                                  after={"proposal_id": proposal_id, "change_type": change_type},
                                  actor_type=actor_type, proposal_id=proposal_id, job_id=job_id,
                                  remark=note or "由 AI 建议确认写入")
        self.store.commit()
        relinked = self._relink_same_batch(proposal, entity, applied_id,
                                           payload.get(NAME_FIELD.get(entity, "")))
        return {"proposal_id": proposal_id, "status": status, "entity": applied_entity,
                "applied_entity_id": applied_id, "relinked": relinked}

    def reject(self, proposal_id, note=None, actor_type="user"):
        proposal = self._require(proposal_id)
        if proposal["status"] not in ("pending",):
            raise ExtractError("建议 %s 已经是 %s，不能重复处理" % (proposal_id, proposal["status"]))
        patch = {"status": "rejected", "reviewed_at": now_iso(), "reviewer_note": note}
        duration = self._review_duration_ms(proposal)
        if duration is not None:
            patch["review_duration_ms"] = duration
        self.store.update("change_proposal", proposal_id, patch)
        self.store.log_action("change_proposal", proposal_id, "reject",
                              after={"status": "rejected"}, actor_type=actor_type,
                              proposal_id=proposal_id, job_id=proposal.get("job_id"),
                              remark=note or "用户拒绝该建议")
        self.store.commit()
        return {"proposal_id": proposal_id, "status": "rejected"}

    # ---- 写入实现 ---------------------------------------------------
    def _apply(self, proposal, payload, actor_type, note):
        entity = proposal["target_entity_type"]
        change_type = proposal["change_type"]
        proposal_id = proposal["id"]
        job_id = proposal.get("job_id")
        evidences = self.store.list("proposal_evidence", {"proposal_id": proposal_id}, limit=200)

        if change_type == "create":
            values = dict(payload)
            values["origin"] = "ai_agent"
            if "review_status" in self.model.fields(entity):
                values["review_status"] = "confirmed"
                values["reviewed_at"] = now_iso()
            values.setdefault("is_fact", 1)
            record = self.archive._insert(
                entity, values, proposal_id=proposal_id, job_id=job_id, actor_type=actor_type,
                remark=note or "由 AI 建议确认写入（内容来自模型，用户已确认）")
            self._link_evidences(entity, record["id"], evidences)
            return entity, record["id"]

        if change_type == "update":
            target_id = proposal.get("target_entity_id")
            if not target_id:
                raise ExtractError("修改类建议缺少 target_entity_id")
            patch = dict(payload)
            patch.pop("review_status", None)
            self.store.update(entity, target_id, patch, proposal_id=proposal_id, job_id=job_id,
                              actor_type=actor_type, remark=note or "由 AI 建议确认修改")
            self._link_evidences(entity, target_id, evidences)
            return entity, target_id

        if change_type == "link":
            target_id = proposal.get("target_entity_id")
            if not target_id:
                raise ExtractError("关联建议缺少 target_entity_id")
            self._link_evidences(entity, target_id, evidences)
            return entity, target_id

        if change_type == "merge":
            keep = payload.get("keep_id") or proposal.get("target_entity_id")
            drop = payload.get("drop_ids") or []
            if not keep or not drop:
                raise ExtractError("合并建议需要 keep_id 与 drop_ids")
            report = self.archive.merge_records(entity, keep, drop, note=note, commit=False)
            return entity, keep

        if change_type == "delete":
            target_id = proposal.get("target_entity_id")
            if not target_id:
                raise ExtractError("删除建议缺少 target_entity_id")
            self.store.soft_delete(entity, target_id, actor_type=actor_type, proposal_id=proposal_id,
                                   job_id=job_id, remark=note or "由 AI 建议确认删除")
            return entity, target_id

        raise ExtractError("暂不支持的建议类型：%s（split / unlink 在后续步骤实现）" % change_type)

    def _link_evidences(self, entity, entity_id, evidences):
        for ev in evidences:
            try:
                self.archive.link_fragment(
                    entity, entity_id, ev["fragment_id"],
                    relation_type=ev.get("relevance_type") or "primary_source",
                    match_method="ai_extract", origin="ai_agent")
            except (ArchiveError, ModelError):
                continue
        doc_ids = set()
        for ev in evidences:
            try:
                frag = self.store.get("source_fragment", ev["fragment_id"])
                doc_ids.add(frag["document_id"])
            except NotFound:
                continue
        if len(doc_ids) == 1 and "source_document_id" in self.model.fields(entity):
            record = self.store.get(entity, entity_id)
            if not record.get("source_document_id"):
                self.store.update(entity, entity_id, {"source_document_id": doc_ids.pop()})
        self.store.commit()

    def _review_duration_ms(self, proposal):
        created = proposal.get("created_at")
        if not created:
            return None
        try:
            start = datetime.strptime(created[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        return max(0, int((datetime.now(timezone.utc) - start).total_seconds() * 1000))

    def _relink_same_batch(self, proposal, entity, applied_id, name):
        """同一批次里「待关联」的事项建议，在本条建议确认后回填外键。"""
        if not name or entity not in FK_ON_ITEM:
            return []
        batch_id = proposal.get("batch_id")
        if not batch_id:
            return []
        fk = FK_ON_ITEM[entity]
        marker = "待关联 %s:%s" % (entity, name)
        fixed = []
        for other in self.store.list("change_proposal", {"batch_id": batch_id, "status": "pending"},
                                     limit=500, order_by="created_at ASC"):
            if other["id"] == proposal["id"] or fk not in self.model.fields(
                    other["target_entity_type"]):
                continue
            if marker not in (other.get("reason") or ""):
                continue
            payload = self._payload(other)
            payload[fk] = applied_id
            self.store.update("change_proposal", other["id"], {
                "proposed_payload": json.dumps(payload, ensure_ascii=False),
                "reason": (other.get("reason") or "").replace(marker, "已关联 %s:%s" % (entity, name)),
            })
            fixed.append(other["id"])
        if fixed:
            self.store.commit()
        return fixed
