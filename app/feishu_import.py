# -*- coding: utf-8 -*-
"""飞书资料同步：把知识库 / 云盘里的周报月报抓进原始资料库（第 2 步的输入侧）。

设计要点（对齐需求 6.9 原始资料导入 与 1.4③ 保留来源）：
  - 只读：只调用飞书的读接口，不写回飞书；
  - 每条资料都记录 external_id（文档 token）与 external_url（原文链接），
    重复拉取时按 external_id 判重，不会产生重复档案；
  - 正文仍走 app.importers 的同一套片段切分与字符区间逻辑，
    因此导入后的来源片段、追溯能力与手动上传完全一致；
  - 抓取结果先落成 import_batch，可复盘这一次同步导入了什么。
"""
import os
import sys
from datetime import datetime, timezone

from .feishu import FeishuClient, FeishuError, resolve_feishu_config
from .feishu_auth import FeishuAuthError, UserAuth
from .importers import import_text, infer_doc_type, now_iso

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_KEYWORDS = ("周报", "月报")
SUPPORTED_OBJ_TYPES = ("docx", "doc", "sheet")
WIKI_URL = "https://feishu.cn/wiki/%s"


class FeishuSyncError(Exception):
    pass


def _unix_to_iso(value):
    if not value:
        return None
    try:
        ts = int(str(value)[:10])
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_wiki_node(node):
    """知识库节点 → 统一结构。"""
    token = node.get("obj_token") or node.get("node_token")
    return {
        "source": "wiki",
        "title": (node.get("title") or "").strip(),
        "obj_type": node.get("obj_type"),
        "token": token,
        "node_token": node.get("node_token"),
        "url": WIKI_URL % node.get("node_token") if node.get("node_token") else None,
        "updated_at": _unix_to_iso(node.get("obj_edit_time")),
        "space": node.get("_space_name"),
        "raw": node,
    }


def normalize_drive_item(item):
    """云盘文件 → 统一结构。"""
    return {
        "source": "drive",
        "title": (item.get("name") or "").strip(),
        "obj_type": item.get("type"),
        "token": item.get("token"),
        "node_token": None,
        "url": item.get("url"),
        "updated_at": _unix_to_iso(item.get("modified_time")),
        "space": None,
        "raw": item,
    }


class FeishuSync(object):
    def __init__(self, store, client=None, config=None, keywords=None, auth="auto", home=None):
        """auth：user 只用用户身份、tenant 只用应用身份、auto 优先用户身份；home 指定凭据目录。"""
        self.store = store
        self.home = home
        self.config = config or resolve_feishu_config(root=ROOT, home=home)
        self.keywords = tuple(keywords) if keywords else DEFAULT_KEYWORDS
        self.auth = auth
        if client is not None:
            self.client = client
            self.auth_mode = "user" if client.as_user else "tenant"
        else:
            self.client, self.auth_mode = self._build_client(auth)
        if not self.config.has_key:
            raise FeishuSyncError(
                "未找到飞书应用凭据。请设置 FEISHU_APP_ID / FEISHU_APP_SECRET 环境变量，"
                "或写入 ~/.dsh/.credentials.yaml 的 refs 段，或放在 config/feishu.json。")

    def _build_client(self, auth):
        user_auth = None
        if auth in ("auto", "user"):
            try:
                candidate = UserAuth(self.config, home=self.home)
            except FeishuAuthError:
                candidate = None
            if candidate is not None and candidate.has_token:
                user_auth = candidate
        if auth == "user" and user_auth is None:
            raise FeishuSyncError(
                "还没有飞书用户授权。请先跑：python -m app.cli feishu auth")
        if user_auth is not None:
            return FeishuClient(self.config, as_user=True, user_auth=user_auth), "user"
        return FeishuClient(self.config), "tenant"

    # ---- 权限与连通性 --------------------------------------------------
    def check(self):
        """返回一份诊断信息：令牌、知识库可见性、云盘可见性。"""
        report = {
            "app_id": self.config.masked_app_id(),
            "key_source": self.config.key_source,
            "base_url": self.config.base_url,
            "auth_mode": self.auth_mode,
            "user_auth": (self.client.user_auth.describe()
                          if self.client.user_auth is not None else "未使用用户身份"),
            "token_ok": False,
            "spaces": None,
            "drive_ok": False,
            "problems": [],
        }
        try:
            if self.client.as_user:
                self.client.utoken()
            else:
                self.client.token()
            report["token_ok"] = True
        except (FeishuError, FeishuAuthError) as exc:
            report["problems"].append("获取 tenant_access_token 失败：%s" % exc)
            return report
        try:
            spaces = self.client.wiki_spaces()
            report["spaces"] = len(spaces)
            if not spaces:
                report["problems"].append(
                    "应用看不到任何知识库：请在知识库里把本应用加为成员（可阅读）")
        except FeishuError as exc:
            report["problems"].append("知识库列表不可读：%s" % exc)
        try:
            self.client.drive_files()
            report["drive_ok"] = True
        except FeishuError as exc:
            report["problems"].append("云盘根目录不可读：%s" % exc)
        return report

    # ---- 扫描 ----------------------------------------------------------
    def scan(self, wiki=True, drive=False, drive_folder=None, drive_depth=3,
             keywords=None, limit=500, include_unsupported=False):
        """列出名称匹配关键词的资料，不写库。"""
        keys = tuple(keywords) if keywords else self.keywords
        found = []
        if wiki:
            for node in self.client.walk_wiki(limit=limit):
                item = normalize_wiki_node(node)
                item["matched_by"] = "wiki"
                found.append(item)
        if drive:
            for entry in self.client.walk_drive(folder_token=drive_folder,
                                                depth=drive_depth, limit=limit):
                if entry.get("type") == "folder":
                    continue
                item = normalize_drive_item(entry)
                item["matched_by"] = "drive"
                found.append(item)

        result, seen = [], set()
        for item in found:
            title = item["title"] or ""
            if keys and not any(k in title for k in keys):
                continue
            if not include_unsupported and item["obj_type"] not in SUPPORTED_OBJ_TYPES:
                item["note"] = "类型 %s 暂不支持读取内容" % item["obj_type"]
            key = (item["token"] or "", title)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    # ---- 导入 ----------------------------------------------------------
    def pull(self, nodes, doc_type=None, duplicate_handling="skip",
             batch_label=None, fmt="markdown", dry_run=False):
        """把扫描结果导入原始资料库，返回汇总。"""
        if not nodes:
            raise FeishuSyncError("没有匹配的资料；先用 `feishu scan` 确认能看到哪些文档")
        batch_id = None
        if not dry_run:
            batch_id = self.store.insert("import_batch", {
                "source_channel": "feishu",
                "file_count": len(nodes),
                "status": "running",
                "initiated_by": "user",
                "started_at": now_iso(),
                "batch_label": batch_label or "飞书同步",
            })
        results, imported, duplicated, failed, skipped = [], 0, 0, 0, 0
        for item in nodes:
            title = item["title"] or item["token"] or "(无标题)"
            if item["obj_type"] not in SUPPORTED_OBJ_TYPES:
                skipped += 1
                results.append({"status": "skipped", "title": title,
                                "note": item.get("note") or ("不支持的类型：%s" % item["obj_type"])})
                continue
            try:
                text, note = self.client.node_text(item["obj_type"], item["token"], title)
            except FeishuError as exc:
                failed += 1
                results.append({"status": "failed", "title": title, "error": str(exc)})
                continue
            if not (text or "").strip():
                skipped += 1
                results.append({"status": "skipped", "title": title,
                                "note": note or "文档正文为空"})
                continue
            if dry_run:
                results.append({"status": "dry_run", "title": title,
                                "chars": len(text), "url": item.get("url")})
                continue
            try:
                result = import_text(
                    self.store, title, text,
                    doc_type=doc_type or infer_doc_type(title),
                    source_channel="feishu",
                    duplicate_handling=duplicate_handling,
                    import_batch_id=batch_id,
                    external_id=item["token"],
                    external_url=item.get("url"),
                    external_updated_at=item.get("updated_at"),
                    fmt=fmt,
                    title_for_infer=title,
                )
            except Exception as exc:  # 单篇失败不阻断整批
                failed += 1
                results.append({"status": "failed", "title": title, "error": str(exc)})
                continue
            result["title"] = title
            result["url"] = item.get("url")
            result["source"] = item["source"]
            results.append(result)
            if result["status"] == "duplicate":
                duplicated += 1
            else:
                imported += 1

        if batch_id:
            batch = self.store.get("import_batch", batch_id)
            self.store.update("import_batch", batch_id, {
                "success_count": imported,
                "failed_count": failed,
                "duplicate_count": duplicated,
                "status": "succeeded" if failed == 0 else "failed",
                "finished_at": now_iso(),
                "failure_reason": None if failed == 0 else "%d 篇拉取失败" % failed,
            }, expected_revision=batch["revision"], remark="飞书同步完成")
            self.store.commit()

        return {"status": "batch", "batch_id": batch_id, "total": len(nodes),
                "imported": imported, "duplicate": duplicated,
                "failed": failed, "skipped": skipped, "results": results}

    def sync(self, wiki=True, drive=False, drive_folder=None, drive_depth=3,
             keywords=None, limit=500, **kwargs):
        """扫描 + 导入一次完成。"""
        nodes = self.scan(wiki=wiki, drive=drive, drive_folder=drive_folder,
                          drive_depth=drive_depth, keywords=keywords, limit=limit)
        return self.pull(nodes, **kwargs)
