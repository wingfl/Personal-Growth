# -*- coding: utf-8 -*-
"""项目的整理：把同一项目的多个「需求/功能」合并回去，并为每个项目写一句介绍。

项目是经历的容器，需求、功能迭代是它的事项；档案里经常出现「Aether 局部重绘」
「Aether 图层拆分」这种把功能当项目的记录，合并时用 `Archive.merge_records`，
保留血缘（entity_relation.merged_into + merged_from_ids），不物理删除。

项目介绍只使用现存事实（名称、时间、角色、事项标题、已有成果），不编造指标；
模型不可用时用规则稿兜底，宁可用词平实，也不写「赋能/闭环」这类空话。
"""
import json
import re

from .archive import ArchiveError, Archive
from .llm import LLMClient, LLMError

MAX_TITLES = 40

ROLE_LABELS = {
    "lead": "主导", "owner": "负责", "core": "核心参与",
    "participant": "参与", "support": "协助", "observer": "了解",
}

SYSTEM_PROMPT = (
    "你在为个人成长档案写「项目介绍」，读者没见过这个项目。只用给定事实，不补充数字、"
    "客户名、结果。输出 3 句、合计不超过 110 字：\n"
    "1) 项目做什么：面向什么场景、解决什么问题，不要以项目名开头，不要写「这个项目是…」；\n"
    "2) 我承担什么：用动词说明具体动作（需求梳理、方案设计、对接、验收等），不要只写「负责该项目」；\n"
    "3) 做到什么程度：已上线/验收/进行中/已关闭，以及可核对的主要产出。\n"
    "禁止：复述项目名称、元话语（如「未给出」「以下」「已有成果描述」）、评价词（成功、优秀、显著）、"
    "英文职级、编造的数字与时间。用陈述句，不用「赋能」「闭环」「打法」。"
)

# 模型偶尔会漏出推理口吻，落库前清掉
_META = re.compile(r"(已有成果描述[^。；]*[。；]?|做到的程度[^。；]*[。；]?|未给出[^。；]*[。；]?)")


_RISKY_NUMBER = re.compile(r"\d+(?:\.\d+)?\s*%|\d+\s*%|￥\s*\d|\d+\s*万|\d+\s*人|\d+\s*个(?!月)")


def strip_number_sentences(text):
    """把带没给过的量（百分比/金额/人数）的句子整句去掉，保留其余事实陈述。"""
    kept = []
    for sentence in re.split(r"(?<=[。；])", text or ""):
        if not sentence.strip():
            continue
        if _RISKY_NUMBER.search(sentence):
            continue
        kept.append(sentence)
    return "".join(kept).strip()


def has_fabricated_numbers(text):
    """出现百分比、金额、人数这类没给过的量，就不要用它。"""
    return bool(_RISKY_NUMBER.search(text or ""))


def clean_intro(text, name=""):
    text = _META.sub("", text or "")
    text = re.sub(r"\s+", " ", text)
    # 中文句子之间的空格是模型输出噪声，压缩掉
    text = re.sub(r"(?<=[。！？；，、])\s+", "", text)
    text = text.strip()
    if name and text.startswith("这个项目是%s" % name):
        text = text[len("这个项目是%s" % name):].lstrip("，。 ")
    return text.strip()


def _months_between(start, end):
    return start, end


class ProjectCurator:
    """项目合并与介绍生成。"""

    def __init__(self, store, llm=None):
        self.store = store
        self.archive = Archive(store)
        self.llm = llm

    # ---- 合并 -------------------------------------------------------
    def find(self, name):
        rows = self.store.list("project", order_by="name ASC", limit=100000)
        for row in rows:
            if row["name"] == name:
                return row
        for row in rows:
            if name in (row.get("alias_names") or []):
                return row
        raise ArchiveError("找不到项目：%s" % name)

    def merge(self, keep_name, names, note=None):
        """把 names 并入 keep_name；names 可以是名称或 id。"""
        keep = self.find(keep_name)
        drop_ids = []
        aliases = list(keep.get("alias_names") or [])
        for name in names:
            row = self.find(name)
            if row["id"] == keep["id"]:
                continue
            drop_ids.append(row["id"])
            if row["name"] not in aliases:
                aliases.append(row["name"])
        if not drop_ids:
            raise ArchiveError("没有可合并的项目")
        report = self.archive.merge_records(
            "project", keep["id"], drop_ids,
            note=note or "同一项目的功能/需求记录归并：%s" % "、".join(names),
        )
        patch = {"alias_names": aliases}
        if note:
            patch["consolidation_note"] = note
        self.store.update("project", keep["id"], patch)
        self.store.commit()
        report["aliases"] = aliases
        return report

    # ---- 介绍 -------------------------------------------------------
    def items(self, project_id, limit=MAX_TITLES):
        return self.store.list("work_item", {"project_id": project_id},
                               limit=limit, order_by="occurred_at ASC")

    def facts(self, project):
        items = self.items(project["id"])
        dates = [row.get("occurred_at") for row in items if row.get("occurred_at")]
        titles = [row["title"] for row in items]
        return {
            "name": project["name"],
            "start": min(dates) if dates else project.get("start_date"),
            "end": max(dates) if dates else project.get("end_date"),
            "role": ROLE_LABELS.get(project.get("my_role"), project.get("my_role")),
            "titles": titles,
            "outcome": project.get("outcome_summary"),
            "count": len(titles),
        }

    def draft(self, project):
        """规则稿：模型不可用时用，只陈述可核对的事实。"""
        f = self.facts(project)
        if not f["titles"]:
            return ""
        span = " 至 ".join(x for x in (f["start"], f["end"]) if x)
        head = "「%s」%s" % (f["name"], span or "未注明起止时间")
        sample = "、".join(f["titles"][:3])
        tail = "等" if f["count"] > 3 else ""
        body = "档案中有 %d 条记录，涉及%s%s。" % (f["count"], sample, tail)
        return head + "，" + body

    def generate(self, project, model=None, temperature=0.3):
        f = self.facts(project)
        if not f["titles"]:
            return ""
        if self.llm is None:
            return self.draft(project)
        payload = {
            "项目名称": f["name"],
            "时间": [f["start"], f["end"]],
            "我的角色": f["role"],
            "已有成果描述": f["outcome"],
            "相关事项标题": f["titles"],
        }
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=1)},
        ]
        try:
            reply = self.llm.chat(messages, temperature=temperature, max_tokens=4096)
        except LLMError:
            return self.draft(project)
        text = clean_intro((reply.text or "").strip().strip('"'), f["name"])
        text = strip_number_sentences(text)
        if len(text) < 15:
            return self.draft(project)
        return text

    def write(self, project_id, text):
        self.store.update("project", project_id, {"intro": text})
        self.store.commit()
        return text


def make_curator(store, model=None):
    """便于 CLI 与脚本共用：没有显式模型时按项目默认配置建客户端。"""
    from .llm import resolve_config

    try:
        return ProjectCurator(store, LLMClient(resolve_config(model=model)))
    except Exception:
        return ProjectCurator(store, None)
