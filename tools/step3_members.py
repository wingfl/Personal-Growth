"""第 3 步演示辅助：挂主题成员，并打印后续命令要用的记录 ID。

用法：eval "$(python tools/step3_members.py)"
输出（stdout，供 bash eval）：theme=… / project=… / duplicate=…
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.archive import Archive  # noqa: E402
from app.store import Store  # noqa: E402

DB = os.path.join("data", "demo.db")
THEME_NAME = "客户数据平台建设"
DUPLICATE_NAME = "客户数据平台"

ITEM_TITLES = [
    "完成客户数据平台指标口径梳理",
    "与业务方确认 3 个争议口径",
    "复盘平台建设经验",
]
DOC_TITLES = ["2024年第12周周报", "2024-03工作月报", "项目复盘-客户数据平台"]


def main():
    store = Store(DB)
    try:
        arc = Archive(store)
        theme = store.find_one("work_theme", name=THEME_NAME)
        project = store.find_one("project", name=THEME_NAME)
        duplicate = store.find_one("project", name=DUPLICATE_NAME)
        if not (theme and project and duplicate):
            raise SystemExit("演示库缺少主题或项目，请先执行 tools/step3_demo.sh")

        added = 0
        for title in ITEM_TITLES:
            item = store.find_one("work_item", title=title)
            if not item:
                print("跳过（找不到事项）：%s" % title, file=sys.stderr)
                continue
            arc.add_theme_member(theme["id"], "work_item", item["id"],
                                 relation_type="primary", match_reason="同一平台建设的连续工作")
            added += 1
        for title in DOC_TITLES:
            doc = store.find_one("source_document", title=title)
            if not doc:
                continue
            arc.add_theme_member(theme["id"], "source_document", doc["id"],
                                 relation_type="secondary", match_reason="主题相关的原始资料")
            added += 1

        print("已挂 %d 个主题成员" % added, file=sys.stderr)
        print("theme=%s" % theme["id"])
        print("project=%s" % project["id"])
        print("duplicate=%s" % duplicate["id"])
    finally:
        store.close()


if __name__ == "__main__":
    main()
