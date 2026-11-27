# -*- coding: utf-8 -*-
"""岗位工作链路：把「一句话里程碑」还原成一条常见的工作过程。

周报里常见「XX 需求完成评审并推进」这种写法。它不是全部工作——评审之前通常有调研、
对比、需求文档、方案与验收标准。这里用**岗位常识**补出隐含环节，但只作为「推断」：
写入 `capability_evidence` 时 `is_fact=0`，并在页面上单独标注，不能冒充原文事实。

角色来自 `user_profile.current_title`（没有则用通用链路）。
"""
import re

DEFAULT_ROLE = "通用"

# 每个岗位：阶段 → 触发词 → 该阶段会用到/练到的能力
PLAYBOOKS = {
    "产品经理": [
        ("调研与验证", ["调研", "竞品", "访谈", "验证", "评估", "分析", "摸底"],
         [("PU1", "用户洞察"), ("PU3", "数据分析"), ("CG1", "领域知识")]),
        ("PRD 与方案", ["需求", "PRD", "方案", "规划", "原型", "流程", "设计", "评审"],
         [("PU2", "产品设计"), ("DQ3", "风险处理")]),
        ("推进与协作", ["推进", "评审", "排期", "协调", "对齐", "拉通", "交付"],
         [("DQ1", "项目推进"), ("CO1", "跨团队协作"), ("CO2", "沟通表达")]),
        ("验收与复盘", ["上线", "验收", "发布", "复盘", "回顾", "交付"],
         [("DQ2", "质量与验收"), ("CG2", "复盘迁移")]),
    ],
    "设计师": [
        ("调研与定义", ["评审", "改版", "需求", "设计", "上线"],
         [("PU1", "用户洞察"), ("CG1", "领域知识")]),
        ("方案与交付", ["设计", "方案", "原型", "视觉", "交互"],
         [("PU2", "产品设计"), ("DQ3", "风险处理")]),
        ("协作与验收", ["推进", "评审", "交付", "上线", "验收"],
         [("CO1", "跨团队协作"), ("DQ2", "质量与验收")]),
    ],
    "研发工程师": [
        ("理解与设计", ["需求", "评审", "方案", "设计", "技术方案"],
         [("CG1", "领域知识"), ("PU2", "产品设计")]),
        ("实现与联调", ["开发", "联调", "实现", "接入", "改造"],
         [("DQ1", "项目推进"), ("DQ3", "风险处理")]),
        ("测试与上线", ["测试", "上线", "发布", "验收", "灰度"],
         [("DQ2", "质量与验收"), ("CO1", "跨团队协作")]),
    ],
    "测试工程师": [
        ("用例与方案", ["需求", "评审", "用例", "方案", "测试"],
         [("PU3", "数据分析"), ("PU2", "产品设计")]),
        ("执行与缺陷", ["测试", "缺陷", "回归", "验收", "上线"],
         [("DQ2", "质量与验收"), ("DQ3", "风险处理")]),
        ("协作与复盘", ["协作", "推进", "复盘", "发布"],
         [("CO1", "跨团队协作"), ("CG2", "复盘迁移")]),
    ],
    "运营": [
        ("洞察与策划", ["活动", "增长", "投放", "用户", "策略", "复盘"],
         [("PU1", "用户洞察"), ("PU3", "数据分析")]),
        ("执行与协同", ["上线", "推进", "落地", "投放", "联动"],
         [("DQ1", "项目推进"), ("CO1", "跨团队协作"), ("CO2", "沟通表达")]),
        ("复盘与迭代", ["复盘", "回顾", "数据", "迭代"],
         [("CG2", "复盘迁移"), ("DQ2", "质量与验收")]),
    ],
    DEFAULT_ROLE: [
        ("理解与准备", ["需求", "评审", "方案", "调研", "规划"],
         [("CG1", "领域知识"), ("PU2", "产品设计")]),
        ("执行与协作", ["推进", "交付", "上线", "协作", "对齐"],
         [("DQ1", "项目推进"), ("CO1", "跨团队协作")]),
        ("验收与复盘", ["验收", "发布", "复盘", "回顾"],
         [("DQ2", "质量与验收"), ("CG2", "复盘迁移")]),
    ],
}

MILESTONES = ("评审", "上线", "发布", "验收", "推进", "立项", "交付", "复盘", "回顾")

# 推断证据的强度上限：只是「按岗位链路应当发生过」，不等于本人做得深
INFERRED_STRENGTH = 2


def playbook(role):
    """按岗位名取链路；叫不出名字的岗位回落到通用链路。"""
    if not role:
        return DEFAULT_ROLE, PLAYBOOKS[DEFAULT_ROLE]
    for name, stages in PLAYBOOKS.items():
        if name != DEFAULT_ROLE and name in role:
            return name, stages
    return role, PLAYBOOKS[DEFAULT_ROLE]


def stage_capabilities(text, role=None):
    """一句话里出现了哪些里程碑，按岗位链路补出隐含阶段与能力。

    返回 [(阶段, 能力 code, 能力名)]；没有里程碑词时返回空列表。
    """
    text = text or ""
    if not any(word in text for word in MILESTONES):
        return []
    _, stages = playbook(role)
    out, seen = [], set()
    for stage, triggers, caps in stages:
        if not any(word in text for word in triggers):
            continue
        for code, name in caps:
            if code in seen:
                continue
            seen.add(code)
            out.append((stage, code, name))
    return out


# 同一阶段里，按文本线索挑更贴近的能力（否则「复盘」会被算成「质量与验收」）
CAPABILITY_HINTS = {
    "CG2": ("复盘", "回顾", "总结", "沉淀"),
    "DQ2": ("验收", "上线", "发布", "质量", "回归"),
    "DQ3": ("风险", "阻塞", "问题", "异常", "兜底"),
    "CO1": ("协作", "对齐", "拉通", "跨团队", "联动"),
    "CO2": ("沟通", "汇报", "宣讲", "表达"),
    "PU1": ("调研", "用户", "访谈", "竞品"),
    "PU3": ("数据", "指标", "口径", "分析"),
    "CG1": ("领域", "行业", "知识", "规范"),
    "DQ1": ("推进", "排期", "交付", "上线", "落地"),
    "PU2": ("需求", "PRD", "方案", "原型", "设计", "流程"),
}


def pick_capability(text, caps):
    """在一个阶段的能力里挑最贴合文本线索的一项。"""
    for code, name in caps:
        if any(word in text for word in CAPABILITY_HINTS.get(code, ())):
            return code, name
    return caps[0]


def implied_stages(text, role=None):
    """按出现顺序返回命中的阶段：[(阶段, [(code, name), ...])]。"""
    text = text or ""
    if not any(word in text for word in MILESTONES):
        return []
    _, stages = playbook(role)
    out = []
    for stage, triggers, caps in stages:
        if any(word in text for word in triggers):
            out.append((stage, caps))
    return out


def chain_text(role):
    """给提示词/界面用的一句话链路描述。"""
    name, stages = playbook(role)
    return "%s：%s" % (name, " → ".join(stage for stage, _, _ in stages))


def role_of(store):
    row = store.find_one("user_profile", deleted_at=None)
    if row and row.get("current_title"):
        return row["current_title"]
    return None


def looks_like_milestone(text):
    return any(word in (text or "") for word in MILESTONES)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()
