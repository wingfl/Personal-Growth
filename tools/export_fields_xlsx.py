# -*- coding: utf-8 -*-
"""把 schema/model.json 导出为《字段说明》Excel，便于逐字段评审与核对。

输出：docs/个人成长档案系统-数据模型字段清单 V1.0.xlsx
工作表：实体清单 / 字段清单 / 枚举字典 / 需求覆盖
用法：python tools/export_fields_xlsx.py
"""
import io
import json
import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL = os.path.join(ROOT, "schema", "model.json")
OUT = os.path.join(ROOT, "docs", "个人成长档案系统-数据模型字段清单 V1.0.xlsx")

LAYER_CN = {"00_base": "基础与横切机制", "01_source": "01 原始资料层", "02_experience": "02 工作经历",
            "03_achievement": "03 成果沉淀", "04_portrait": "04 个人画像层",
            "05_growth": "05 成长分析与输出层", "06_ai": "AI 与数据运维"}

HEAD_FILL = PatternFill("solid", fgColor="1F4E79")
HEAD_FONT = Font(color="FFFFFF", bold=True, size=11)


def type_text(f, model):
    t = f.get("t")
    if t == "ref":
        ref = f.get("ref")
        return "外键 → " + ref if ref and ref != "ENTITY_TYPE" else "多态引用（任意实体类型）"
    if t == "enum":
        return f"枚举 {f.get('e')}"
    return t


def add_sheet(wb, title, headers, rows, widths):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEAD_FILL
        cell.font = HEAD_FONT
        cell.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append(list(r))
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"
    return ws


def main():
    with io.open(MODEL, encoding="utf-8") as fh:
        model = json.load(fh)
    wb = Workbook()
    wb.remove(wb.active)

    # 实体清单
    ents = []
    for e in model["entities"]:
        ents.append([e["id"], e["name"], LAYER_CN.get(e["layer"], e["layer"]), e["priority"],
                     "、".join(e.get("flags", [])), len(e["full_fields"]), e["purpose"]])
    add_sheet(wb, "实体清单", ["实体名", "中文名", "分层", "优先级", "字段组", "字段数", "用途与职责"],
              ents, [22, 20, 22, 8, 16, 8, 90])

    # 字段清单
    rows = []
    for e in model["entities"]:
        for f in e["full_fields"]:
            rng = ""
            if f.get("min") is not None and f.get("max") is not None:
                rng = f"{f['min']}~{f['max']}"
            elif f.get("min") is not None:
                rng = f"≥ {f['min']}"
            elif f.get("max") is not None:
                rng = f"≤ {f['max']}"
            rows.append([
                e["id"], e["name"], LAYER_CN.get(e["layer"], e["layer"]),
                f["n"], f.get("l", ""), type_text(f, model),
                "是" if f.get("req") else "",
                "是" if f.get("u") else "",
                "是" if f.get("imm") else "",
                "是" if f.get("idx") else "",
                "" if f.get("def") is None else str(f["def"]),
                rng, f.get("d", ""),
            ])
        for ut in e.get("unique_together", []) or []:
            rows.append([e["id"], e["name"], LAYER_CN.get(e["layer"], e["layer"]),
                         "（组合唯一约束）", "、".join(ut), "组合唯一", "", "", "", "", "", "",
                         "组合唯一约束：" + "、".join(ut) + "（部分唯一索引，软删除后不占用唯一值）"])
    add_sheet(wb, "字段清单",
              ["实体名", "实体中文名", "分层", "字段名", "中文名", "类型", "必填", "唯一",
               "写入后不可修改", "索引", "默认值", "取值范围", "说明（来源 / 规则 / 用途）"],
              rows, [22, 20, 22, 26, 20, 26, 6, 6, 14, 6, 10, 10, 95])

    # 枚举字典
    erows = []
    for name, spec in model["enums"].items():
        for code, label, note in spec["v"]:
            erows.append([name, spec["l"], code, label, note])
    add_sheet(wb, "枚举字典", ["枚举名", "枚举中文名", "取值", "取值含义", "附加说明"],
              erows, [26, 30, 24, 24, 60])

    # 需求覆盖
    crows = [[c["id"], c.get("src", ""), c["req"], "、".join(c["entities"]), c.get("note", "")]
             for c in model["coverage"]]
    add_sheet(wb, "需求覆盖", ["编号", "需求出处", "需求点", "承载的实体 / 机制", "实现说明"],
              crows, [12, 18, 60, 46, 80])

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    wb.save(OUT)
    print(f"已生成 {os.path.relpath(OUT, ROOT)}")
    print("工作表：实体清单 / 字段清单 / 枚举字典 / 需求覆盖")


if __name__ == "__main__":
    main()
