# -*- coding: utf-8 -*-
"""打印第 4 步演示要用的记录 ID（供 bash `eval` 读取）。

用法：python tools/step4_pick.py [data/demo.db]
输出形如 weekly_doc=xxx，每行一个键值对。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.extract import Review
from app.store import Store


def main():
    db = sys.argv[1] if len(sys.argv) > 1 else "data/demo.db"
    store = Store(db)

    for doc in store.list("source_document", limit=50, order_by="created_at ASC"):
        title = doc["title"]
        if "周报" in title:
            print("weekly_doc=%s" % doc["id"])
        elif "月报" in title:
            print("monthly_doc=%s" % doc["id"])
        else:
            print("review_doc=%s" % doc["id"])

    projects = store.list("project", limit=10, order_by="created_at ASC")
    if projects:
        print("project=%s" % projects[0]["id"])
    systems = store.list("business_system", limit=10, order_by="created_at ASC")
    if systems:
        print("system=%s" % systems[0]["id"])

    review = Review(store)
    items = []
    for row in review.list(status="pending", limit=100):
        if row["change_type"] == "link" and row["target_entity_type"] == "project":
            print("link_project=%s" % row["id"])
        elif row["change_type"] == "create" and row["target_entity_type"] == "work_item":
            items.append(row["id"])
    if items:
        print("item=%s" % items[0])
    if len(items) > 1:
        print("ex_item=%s" % items[-1])


if __name__ == "__main__":
    main()
