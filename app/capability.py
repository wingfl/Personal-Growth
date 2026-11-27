# -*- coding: utf-8 -*-
"""能力词典与能力证据（第 5 步）。

设计原则（对应产品四原则与架构原则⑥）：
  * 记录优先：证据只能来自已确认的工作事项、项目或成果，不凭空生成能力分。
  * 数据有来源：每条证据带原文 quote（strength_basis）与目标记录 id，可回溯。
  * 时间主线：证据带 occurred_at，可按月份看变化。
  * 长期回顾：能力画像按「证据数量 + 强度」呈现，不造总分。

流程：seed() 建词典（builtin）→ CapabilityMapper 把事项映射成证据建议
（change_proposal，target=capability_evidence）→ 人工 confirm 后才是正式证据。
"""
import json
import re

from .extract import ExtractError, parse_json_reply, render_prompt
from .ids import now_iso, uuid7
from .roles import INFERRED_STRENGTH, chain_text, implied_stages, pick_capability, role_of
from .llm import LLMClient

FRAMEWORK = "产品经理能力框架（自建 v1）"
LEVEL_SCALE = "1 参与｜2 独立完成常规｜3 独立负责复杂｜4 定标准/带人｜5 定义方向并被外部验证"

# 分类 code → (名称, 描述)
CATEGORIES = [
    ("PU", "产品与用户", "判断做什么：用户、场景、方案与数据"),
    ("DQ", "交付与质量", "把事做成：推进、验收与风险"),
    ("CO", "协作与影响", "通过他人拿结果：协作与表达"),
    ("CG", "复盘与迁移", "把经历变成能力：领域知识与复盘"),
]

# (code, 分类, 名称, 定义, 典型行为)
CAPABILITIES = [
    ("PU1", "PU", "用户洞察", "从真实用户场景与反馈中识别问题与需求，而不是从功能清单出发。",
     "能说清目标用户是谁、在什么场景下遇到什么问题，并给出判断依据。"),
    ("PU2", "PU", "产品设计", "把需求转成可交付的方案：范围、流程、验收标准与取舍。",
     "方案里写清做什么、不做什么、怎么验收，开发能直接照此排期。"),
    ("PU3", "PU", "数据分析", "用数据定位问题、验证假设，并让判断可被复核。",
     "先定义指标与口径，再给结论；能量化收益或问题规模。"),
    ("DQ1", "DQ", "项目推进", "拆解、排期、跟进，让多方按节奏交付。",
     "有里程碑与责任人，阻塞能提前暴露并推动解决。"),
    ("DQ2", "DQ", "质量与验收", "定义验收标准并验证上线质量，而不是只看出包。",
     "上线前有验收清单与回归范围，问题闭环有记录。"),
    ("DQ3", "DQ", "风险处理", "提前识别风险、给出取舍，并在需要时升级。",
     "说清风险影响与备选方案，决策有记录。"),
    ("CO1", "CO", "跨团队协作", "对齐目标、处理分歧，推动跨团队共同交付。",
     "能让不同角色对同一目标达成一致，并对齐接口与节奏。"),
    ("CO2", "CO", "沟通表达", "把复杂问题讲清楚，形成可执行的结论与记录。",
     "文档/汇报能让读者快速抓住结论、依据与下一步。"),
    ("CG1", "CG", "领域知识", "在业务与行业上的持续积累，能迁移到新问题。",
     "能解释行业规则与约束，并据此调整方案。"),
    ("CG2", "CG", "复盘迁移", "从经历中提炼可复用方法，并改进下一次做法。",
     "复盘写出有效/无效动作与下次改动，而不只是罗列过程。"),
]

EVIDENCE_TYPES = ("responsibility", "performance", "complexity", "contribution")
EVIDENCE_TYPE_LABEL = {
    "responsibility": "职责常态",
    "performance": "结果突出",
    "complexity": "复杂度高",
    "contribution": "关键贡献",
}
MAX_QUOTE = 300


def _now():
    return now_iso()


class CapabilityError(Exception):
    """能力词典或证据流程中的错误。"""


def seed(store):
    """幂等写入能力分类与词典。返回 (新增分类, 新增能力)。"""
    existing_categories = {row["name"]: row for row in store.list("capability_category", limit=200)}
    category_ids = {}
    created_categories = 0
    for index, (code, name, description) in enumerate(CATEGORIES):
        row = existing_categories.get(name)
        if row:
            category_ids[code] = row["id"]
            continue
        rid = store.insert("capability_category", {
            "name": name,
            "description": description,
            "sort_order": index,
            "category_path": name,
            "level_depth": 1,
            "is_assignable": True,
            "origin": "system",
        })
        category_ids[code] = rid
        created_categories += 1

    existing_capabilities = {row["code"]: row for row in store.list("capability", limit=500)}
    created_capabilities = 0
    for code, category, name, definition, behavior in CAPABILITIES:
        if code in existing_capabilities:
            continue
        store.insert("capability", {
            "code": code,
            "name": name,
            "category_id": category_ids[category],
            "definition": definition,
            "source_type": "builtin",
            "status": "active",
            "is_core": True,
            "framework_name": FRAMEWORK,
            "level_scale_note": LEVEL_SCALE,
            "typical_behavior": behavior,
            "origin": "system",
        })
        created_capabilities += 1
    store.commit()
    return created_categories, created_capabilities


def capabilities(store):
    """按分类聚合能力词典（带证据数量与平均强度）。"""
    rows = store.query(
        """
        SELECT c.id, c.code, c.name, c.definition, c.typical_behavior,
               cc.name AS category_name, cc.sort_order AS category_order,
               COUNT(e.id) AS evidence_count,
               SUM(CASE WHEN e.is_fact = 0 THEN 1 ELSE 0 END) AS inferred_count,
               SUM(CASE WHEN e.is_fact = 1 THEN 1 ELSE 0 END) AS fact_count,
               AVG(e.strength) AS avg_strength,
               AVG(CASE WHEN e.is_fact = 1 THEN e.strength END) AS fact_avg_strength,
               MAX(e.occurred_at) AS last_evidence_at
          FROM capability c
          JOIN capability_category cc ON cc.id = c.category_id
          LEFT JOIN capability_evidence e
                 ON e.capability_id = c.id AND e.deleted_at IS NULL
         WHERE c.deleted_at IS NULL
         GROUP BY c.id
         ORDER BY cc.sort_order, c.code
        """
    )
    out = []
    for row in rows:
        out.append({
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "definition": row["definition"],
            "typical_behavior": row["typical_behavior"],
            "category": row["category_name"],
            "evidence_count": row["evidence_count"] or 0,
            "inferred_count": row["inferred_count"] or 0,
            "fact_count": row["fact_count"] or 0,
            "avg_strength": round(row["avg_strength"], 2) if row["avg_strength"] is not None else None,
            "fact_avg_strength": (round(row["fact_avg_strength"], 2)
                                  if row["fact_avg_strength"] is not None else None),
            "last_evidence_at": row["last_evidence_at"],
        })
    return out


def evidence(store, capability_id, limit=200):
    rows = store.query(
        """
        SELECT e.id, e.evidence_type, e.strength, e.statement, e.strength_basis,
               e.occurred_at, e.target_type, e.target_id, e.origin,
               e.is_fact, e.fact_basis,
               i.title AS item_title, i.project_id, p.name AS project_name, p.goal AS project_goal,
               e.created_at
          FROM capability_evidence e
          LEFT JOIN work_item i ON i.id = e.target_id AND e.target_type = 'work_item'
          LEFT JOIN project p ON p.id = i.project_id
         WHERE e.capability_id = ? AND e.deleted_at IS NULL
         ORDER BY e.occurred_at DESC, e.created_at DESC
         LIMIT ?
        """,
        (capability_id, limit),
    )
    return [dict(row) for row in rows]


def infer_chain(store, role=None, limit=None, dry_run=False):
    """按岗位链路补出「一句话里程碑」背后的常规环节，计入本人能力（fact_basis 注明来源）。

    只对已经确认的事项做；同一事项 + 同一能力已有证据或待审建议时跳过。
    返回 {"role","chain","items","proposals","by_stage"}。
    """
    role = role or role_of(store)
    caps = {row["code"]: row for row in capabilities(store) if row["evidence_count"] >= 0}
    if not caps:
        raise CapabilityError("能力词典为空：先运行 python -m app.cli capability seed")

    covered = set()
    for row in store.query(
            "SELECT target_id, capability_id FROM capability_evidence WHERE deleted_at IS NULL"):
        covered.add((row["target_id"], row["capability_id"]))
    for row in store.query(
            "SELECT proposed_payload FROM change_proposal WHERE target_entity_type = "
            "'capability_evidence' AND status = 'pending' AND deleted_at IS NULL"):
        try:
            payload = json.loads(row["proposed_payload"] or "{}")
        except ValueError:
            continue
        covered.add((payload.get("target_id"), payload.get("capability_id")))

    items = store.query(
        "SELECT id, title, content, occurred_at, is_routine FROM work_item "
        "WHERE deleted_at IS NULL AND review_status = 'confirmed' AND is_routine = 0 "
        "ORDER BY occurred_at ASC")
    plan = []
    for item in items:
        text = "%s\n%s" % (item["title"] or "", item["content"] or "")
        if len(text.strip()) < 10:
            continue
        matched = implied_stages(text, role)
        if not matched:
            continue
        # 一句话的落点在最后一个命中阶段；补「它 + 前一环」两段，最像一个真实链路
        picked = matched[-2:] if len(matched) > 1 else matched[-1:]
        for stage, stage_caps in picked:
            # 每个阶段按文本线索挑一项能力：稳定、可预期，不会因为已覆盖就滑到下一个
            code, name = pick_capability(text, stage_caps)
            cap = caps.get(code)
            if not cap or (item["id"], cap["id"]) in covered:
                continue
            covered.add((item["id"], cap["id"]))
            plan.append((item, stage, cap, name))
        if limit and len({entry[0]["id"] for entry in plan}) >= limit:
            break

    by_stage = {}
    for _item, stage, _cap, _name in plan:
        by_stage[stage] = by_stage.get(stage, 0) + 1
    summary = {"role": role, "chain": chain_text(role),
               "items": len({entry[0]["id"] for entry in plan}),
               "proposals": len(plan), "by_stage": by_stage}
    if dry_run or not plan:
        return summary

    batch_id = uuid7()
    job_id = store.insert("ai_job", {
        "job_type": "capability_evidence",
        "trigger_type": "manual",
        "input_scope": json.dumps({"batch_id": batch_id, "mode": "role_chain",
                                   "role": role,
                                   "item_ids": sorted({entry[0]["id"] for entry in plan})},
                                  ensure_ascii=False),
        "status": "succeeded",
        "result_summary": "按岗位常规环节补全 %d 条能力证据（计入本人能力）" % len(plan),
    })
    for item, stage, cap, _name in plan:
        store.insert("change_proposal", {
            "job_id": job_id,
            "batch_id": batch_id,
            "change_type": "create",
            "target_entity_type": "capability_evidence",
            "proposed_payload": json.dumps({
                "capability_id": cap["id"],
                "evidence_type": "performance",
                "target_type": "work_item",
                "target_id": item["id"],
                "statement": "完成「%s」通常包含%s环节" % ((item["title"] or "")[:40], stage),
                "occurred_at": item["occurred_at"],
                "strength": INFERRED_STRENGTH,
                "strength_basis": (item["title"] or "")[:200],
                "aspect_focus": cap["name"],
                "is_fact": 1,
                "fact_basis": "按%s的岗位常规环节补全（依据事项「%s」），不是原文逐字" % (role, (item["title"] or "")[:40]),
            }, ensure_ascii=False),
            "diff_summary": "补全能力证据：%s · %s" % (cap["name"], item["title"] or ""),
            "reason": "岗位常规环节，计入你本人的能力；如与实际不符可在确认前删改",
            "status": "pending",
            "priority": 4,
        })
    store.commit()
    summary["job_id"] = job_id
    return summary


class CapabilityMapper:
    """把已确认的工作事项映射成能力证据建议（不直接写正式证据）。"""

    def __init__(self, store, llm=None):
        self.store = store
        self.llm = llm or LLMClient()

    def template(self):
        row = self.store.find_one("prompt_template", job_type="capability_evidence", version=1)
        if not row:
            raise CapabilityError("提示词模板缺失：先运行 python -m app.cli ai seed")
        return row

    def _items(self, limit=None):
        done = self.store.query(
            "SELECT DISTINCT target_id FROM capability_evidence WHERE deleted_at IS NULL")
        done_ids = {row["target_id"] for row in done}
        # 已经生成过、还没确认的建议也跳过，避免重跑时同一事项被标注两次
        pending = self.store.query(
            "SELECT proposed_payload FROM change_proposal "
            "WHERE target_entity_type = 'capability_evidence' AND status = 'pending' "
            "AND deleted_at IS NULL")
        for row in pending:
            try:
                target = json.loads(row["proposed_payload"] or "{}").get("target_id")
            except ValueError:
                continue
            if target:
                done_ids.add(target)
        rows = self.store.query(
            """
            SELECT i.id, i.title, i.content, i.item_type, i.occurred_at, i.project_id,
                   p.name AS project_name
              FROM work_item i
              LEFT JOIN project p ON p.id = i.project_id
             WHERE i.deleted_at IS NULL
             ORDER BY i.occurred_at ASC, i.created_at ASC
            """
        )
        items = [dict(row) for row in rows if row["id"] not in done_ids]
        if limit:
            items = items[:limit]
        return items

    def _capability_lines(self):
        rows = capabilities(self.store)
        if not rows:
            raise CapabilityError("能力词典为空：先运行 python -m app.cli capability seed")
        return "\n".join(
            "%s | %s | %s | %s" % (row["code"], row["name"], row["definition"], row["typical_behavior"])
            for row in rows
        ), {row["code"]: row for row in rows}

    @staticmethod
    def _item_lines(items):
        lines = []
        for item in items:
            content = re.sub(r"\s+", " ", item.get("content") or "").strip()[:200]
            lines.append("%s | %s | %s | %s | %s | %s" % (
                item["id"], item.get("occurred_at") or "", item.get("item_type") or "",
                item.get("project_name") or "—", item.get("title") or "", content))
        return "\n".join(lines)

    def run(self, limit=None, batch_size=25, dry_run=False, temperature=None, max_tokens=None):
        template = self.template()
        items = self._items(limit)
        capability_text, by_code = self._capability_lines()
        if not items:
            return {"items": 0, "proposals": 0, "message": "没有待标注的事项"}
        if dry_run:
            first = items[:batch_size]
            messages = [
                {"role": "system", "content": template["system_prompt"]},
                {"role": "user", "content": render_prompt(
                    template["user_prompt_template"],
                    {"capabilities": capability_text, "items": self._item_lines(first)})},
            ]
            return {"dry_run": True, "items": len(items), "messages": messages}

        batch_id = uuid7()
        job_id = self.store.insert("ai_job", {
            "job_type": "capability_evidence",
            "trigger_type": "manual",
            "input_scope": json.dumps({"batch_id": batch_id, "item_ids": [i["id"] for i in items]},
                                      ensure_ascii=False),
            "model_provider": self.llm.config.provider,
            "model_name": self.llm.config.model,
            "prompt_template_id": template["id"],
            "status": "running",
            "started_at": now_iso(),
            "input_fragment_count": len(items),
        })
        self.store.commit()

        made, skipped, calls = 0, 0, []
        try:
            for start in range(0, len(items), batch_size):
                chunk = items[start:start + batch_size]
                messages = [
                    {"role": "system", "content": template["system_prompt"]},
                    {"role": "user", "content": render_prompt(
                        template["user_prompt_template"],
                        {"capabilities": capability_text, "items": self._item_lines(chunk)})},
                ]
                reply = self._chat(messages, temperature, max_tokens)
                data = parse_json_reply(reply.text)
                calls.append({"batch": start // batch_size + 1, "items": len(chunk)})
                created, bad = self._proposals(job_id, batch_id, data, chunk, by_code)
                made += created
                skipped += bad
                # 每批提交一次：网关偶发 503 时已完成的部分不会丢
                self.store.commit()
            self.store.update("ai_job", job_id, {
                "status": "succeeded",
                "finished_at": now_iso(),
                "result_summary": "标注 %d 条事项，生成 %d 条证据建议，跳过 %d 条不合格输出"
                                  % (len(items), made, skipped),
            })
            self.store.commit()
        except Exception as exc:  # 失败也要留下 job 记录
            self.store.update("ai_job", job_id, {
                "status": "failed",
                "finished_at": now_iso(),
                "error_message": "%s: %s" % (type(exc).__name__, exc)[:500],
            })
            self.store.commit()
            raise
        return {"job_id": job_id, "batch_id": batch_id, "items": len(items),
                "proposals": made, "skipped": skipped, "calls": calls}

    def _chat(self, messages, temperature, max_tokens, attempts=4):
        """网关偶发 503/超时时重试；4xx 校验类错误直接抛出。"""
        import time

        from .llm import LLMError

        delay = 5
        for attempt in range(1, attempts + 1):
            try:
                return self.llm.chat(messages, temperature=temperature,
                                     max_tokens=max_tokens, json_object=True)
            except LLMError as exc:
                text = str(exc)
                transient = ("503" in text or "502" in text or "overloaded" in text
                             or "timed out" in text or "Timeout" in text)
                if not transient or attempt == attempts:
                    raise
                time.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable")

    def _proposals(self, job_id, batch_id, data, chunk, by_code):
        by_id = {item["id"]: item for item in chunk}
        rows = data.get("evidence") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ExtractError("模型输出缺少 evidence 数组")
        made, bad = 0, 0
        seen = set()
        for row in rows:
            item = by_id.get(row.get("item_id"))
            capability = by_code.get(row.get("capability"))
            if not item or not capability:
                bad += 1
                continue
            if item["id"] in seen:
                bad += 1
                continue
            strength = row.get("strength")
            if not isinstance(strength, int) or not 1 <= strength <= 5:
                bad += 1
                continue
            if row.get("evidence_type") not in EVIDENCE_TYPES:
                bad += 1
                continue
            quote = str(row.get("quote") or "").strip()
            haystack = "%s\n%s" % (item.get("title") or "", item.get("content") or "")
            if not quote or quote not in haystack or len(quote) > MAX_QUOTE:
                bad += 1
                continue
            statement = str(row.get("statement") or "").strip()
            if not statement:
                bad += 1
                continue
            seen.add(item["id"])
            self.store.insert("change_proposal", {
                "job_id": job_id,
                "batch_id": batch_id,
                "change_type": "create",
                "target_entity_type": "capability_evidence",
                "proposed_payload": json.dumps({
                    "capability_id": capability["id"],
                    "evidence_type": row["evidence_type"],
                    "target_type": "work_item",
                    "target_id": item["id"],
                    "statement": statement[:200],
                    "occurred_at": item.get("occurred_at"),
                    "strength": strength,
                    "strength_basis": quote,
                    "aspect_focus": capability["name"],
                    "is_fact": 1,
                }, ensure_ascii=False),
                "diff_summary": "新增能力证据：%s · %s" % (capability["name"], item.get("title") or ""),
                "reason": "AI 依据事项原文标注（%s）" % capability["code"],
                "status": "pending",
                "priority": 3,
            })
            made += 1
        return made, bad


# CLI/API 使用的别名，避免与模块名或循环导入混淆
seed_capabilities = seed
capability_rows = capabilities
capability_evidence = evidence
