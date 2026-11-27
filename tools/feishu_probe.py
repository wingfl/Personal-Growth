# -*- coding: utf-8 -*-
"""飞书开放平台连通性探测：拿 token、列知识库（文档库）、列云盘根目录。

权限不足时会打印飞书返回的 code / msg，便于判断该给应用开哪些权限。

用法：python tools/feishu_probe.py
"""
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.feishu import FeishuClient, FeishuError, resolve_feishu_config  # noqa: E402


def show(label, fn):
    print("== %s ==" % label)
    try:
        data = fn()
    except FeishuError as exc:
        print("  失败：%s" % exc)
        return None
    print("  " + json.dumps(data, ensure_ascii=False)[:1200])
    return data


def main():
    cfg = resolve_feishu_config()
    print("app_id=%s  密钥来源=%s" % (cfg.masked_app_id(), cfg.key_source))
    client = FeishuClient(cfg)
    show("tenant_access_token", lambda: {"ok": bool(client.token())})
    show("知识库列表 /open-apis/wiki/v2/spaces",
         lambda: client.request("GET", "/open-apis/wiki/v2/spaces", params={"page_size": 50}))
    show("云盘根目录 /open-apis/drive/v1/files",
         lambda: client.request("GET", "/open-apis/drive/v1/files",
                                params={"page_size": 50, "order_by": "EditedTime", "direction": "DESC"}))


if __name__ == "__main__":
    main()
