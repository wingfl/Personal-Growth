# -*- coding: utf-8 -*-
"""路径口径：工作区根、数据库与附件目录之间的唯一约定。

架构审计第 6 条指出「附件落盘目录按数据库算、`storage_path` 却按工作区算」基准不一致。
这里把口径收敛到一处：

1. **附件目录跟着数据库走**：数据库放在哪里，附件就在它的同级 `attachments/` 下。
   备份/迁移时数据库与附件必须一起搬（见 docs/部署与运维.md）。
2. **`attachment.storage_path` 统一记录相对数据库目录的路径**（如 `attachments/xxx.docx`，
   正斜杠）。数据库放到工作区之外时这个口径依然成立。
3. 历史数据里可能存的是「相对工作区根」或绝对路径，读取一律走 `resolve_storage_ref` 兼容。

本模块只依赖标准库。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def db_dir(db_path):
    """数据库所在目录（附件目录的基准）。"""
    return os.path.dirname(os.path.abspath(db_path))


def attachments_dir(db_path):
    """附件目录：数据库同级的 `attachments/`。"""
    return os.path.join(db_dir(db_path), "attachments")


def storage_ref(db_path, file_path):
    """把附件文件的真实路径转成入库口径（相对数据库目录，正斜杠）。"""
    target = os.path.abspath(file_path)
    try:
        rel = os.path.relpath(target, db_dir(db_path))
    except ValueError:            # 跨盘符无法求相对路径，退回绝对路径
        return target.replace("\\", "/")
    return rel.replace("\\", "/")


def resolve_storage_ref(db_path, ref):
    """把入库口径还原成可用的文件路径；兼容绝对路径与「相对工作区根」的历史写法。"""
    if not ref:
        return ref
    cleaned = str(ref).replace("\\", "/")
    if os.path.isabs(cleaned):
        return os.path.normpath(cleaned)
    candidates = [os.path.join(db_dir(db_path), cleaned), os.path.join(ROOT, cleaned)]
    for candidate in candidates:
        if os.path.exists(candidate):
            return os.path.normpath(candidate)
    return os.path.normpath(candidates[0])


def is_inside(path, base):
    """path 是否在 base 目录之内（用于「附件与数据库是否在同一处」这类判断）。"""
    path = os.path.abspath(path)
    base = os.path.abspath(base)
    return path == base or path.startswith(base + os.sep)
