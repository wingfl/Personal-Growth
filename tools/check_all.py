#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全量质量闸门：一条命令回答「现在这套东西是不是整体健康的」。

检查项（任一失败即退出码 1）：

  1. 模型构建        运行 tools/build_model.py，必须零错误退出
  2. 模型自洽        实体/字段/枚举/规则/覆盖项的结构与交叉引用
  3. DDL 实跑        把 schema/schema.sql 灌进内存 SQLite，逐表逐索引核对
  4. 已有库同步      data/*.db 是否落后于当前模型（缺列/缺索引）
  5. 依赖边界        app/ 只允许标准库与包内相对导入（ADR-0001）
  6. 编译            compileall app/ tools/ tests/
  7. 密钥扫描        版本库内不得出现凭据，也不得跟踪个人数据
  8. 单元测试        全量 unittest（--fast 可跳过）

用法：
    PYTHONIOENCODING=utf-8 python tools/check_all.py [--fast] [--verbose]
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED = (
    "schema/model.json",
    "schema/schema.sql",
    "docs/个人成长档案系统-数据模型设计 V1.0.md",
    "docs/个人成长档案系统-数据模型字段清单 V1.0.xlsx",
)

# 密钥形态：赋值给敏感名字的长字符串（排除形如 NEORIGIN_API_KEY 的“名字引用”）。
# 不匹配 app_id（cli_xxx 是公开标识，会出现在授权链接里），只关心真正的密钥。
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|app[_-]?secret|access[_-]?token|refresh[_-]?token|client[_-]?secret)\b"
               r"\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{24,})"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
)
# 这些文件本来就在讲“键名”，允许出现名字但不允许出现值
SECRET_SCAN_SKIP_SUFFIX = (".md", ".xlsx", ".docx")


class Step:
    def __init__(self, name: str):
        self.name = name
        self.problems: list[str] = []
        self.notes: list[str] = []
        self.duration = 0.0

    @property
    def failed(self) -> bool:
        return bool(self.problems)

    def fail(self, message: str) -> None:
        self.problems.append(message)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def warn(self, message: str) -> None:
        self.notes.append("警告：" + message)


def run(cmd: list[str], verbose: bool = False) -> tuple[int, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    out = proc.stdout or ""
    if verbose or proc.returncode != 0:
        tail = out.strip().splitlines()[-25:]
        if tail:
            print("    " + "\n    ".join(tail))
    return proc.returncode, out


def hash_generated() -> dict[str, str]:
    import hashlib
    result = {}
    for rel in GENERATED:
        path = ROOT / rel
        if path.exists():
            result[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


# ---------------------------------------------------------------- 1 模型构建

def step_build(verbose: bool) -> Step:
    step = Step("模型构建（tools/build_model.py）")
    before = hash_generated()
    code, out = run([sys.executable, "tools/build_model.py"], verbose)
    if code != 0:
        step.fail(f"tools/build_model.py 退出码 {code}")
        return step
    after = hash_generated()
    changed = [rel for rel in after if before.get(rel) != after[rel]]
    if changed:
        step.warn("生成物在本次构建中变化（说明提交前未重新生成）：" + "、".join(changed))
    line = [l for l in out.splitlines() if "实体" in l and "字段" in l]
    if line:
        step.note(line[-1].strip())
    return step


# ---------------------------------------------------------------- 2 模型自洽

def _load_model(step: Step) -> dict | None:
    path = ROOT / "schema/model.json"
    if not path.exists():
        step.fail("缺少 schema/model.json")
        return None
    model = json.loads(path.read_text(encoding="utf-8"))
    for key in ("entities", "enums", "standard_field_groups", "coverage", "meta"):
        if key not in model:
            step.fail(f"model.json 缺少顶层键 {key}")
    return model


def _entity_map(model: dict) -> dict[str, dict]:
    return {entity["id"]: entity for entity in model["entities"]}


def _fields(entity: dict) -> dict[str, dict]:
    return {field["n"]: field for field in (entity.get("full_fields") or [])}


def step_model(verbose: bool) -> Step:
    step = Step("模型自洽（实体 / 字段 / 枚举 / 规则 / 覆盖）")
    model = _load_model(step)
    if model is None:
        return step
    entities = _entity_map(model)
    enums: dict = model["enums"]
    groups: dict = model["standard_field_groups"]

    used_enums: set[str] = set()
    fields_total = 0
    for eid, entity in entities.items():
        fields = _fields(entity)
        if not fields:
            step.fail(f"{eid} 没有任何字段")
        fields_total += len(fields)
        if "id" not in fields:
            step.fail(f"{eid} 缺少主键 id")
        base_group = entity.get("base_group", "base")
        if base_group not in groups:
            step.fail(f"{eid} 引用了不存在的通用字段组 {base_group}")
        for fname, spec in fields.items():
            if spec.get("t") == "enum":
                enum_name = spec.get("e")
                if enum_name not in enums:
                    step.fail(f"{eid}.{fname} 引用了不存在的枚举 {enum_name}")
                else:
                    used_enums.add(enum_name)
            if spec.get("t") == "ref":
                target = spec.get("ref")
                if target and target != "ENTITY_TYPE" and target not in entities:
                    step.fail(f"{eid}.{fname} 引用了不存在的实体 {target}")
            if spec.get("imm") and spec.get("req") and spec.get("def") not in (None, ""):
                step.warn(f"{eid}.{fname} 同时标了必填、不可修改和默认值，请确认语义")
            if spec.get("t") == "enum" and spec.get("min") is not None:
                step.warn(f"{eid}.{fname} 是枚举字段却带数值范围")
    for group_name, group in groups.items():
        for spec in group.get("fields") or []:
            if spec.get("t") == "enum":
                used_enums.add(spec.get("e"))

    unused = sorted(name for name in enums if name not in used_enums and name != "entity_type")
    if unused:
        step.warn("未被任何字段使用的枚举：" + "、".join(unused))
    if "entity_type" not in enums:
        step.fail("缺少 entity_type 枚举（多态引用靠它做 CHECK）")
    elif len(enums["entity_type"]["v"]) != len(entities):
        step.fail("entity_type 枚举取值数与实体数不一致")

    for eid, entity in entities.items():
        fields = _fields(entity)
        for combo in entity.get("unique_together") or []:
            if len(combo) < 2:
                step.fail(f"{eid} 的组合唯一约束少于两列：{combo}")
            for col in combo:
                if col not in fields:
                    step.fail(f"{eid} 的组合唯一约束引用了不存在的字段 {col}")

    rules_path = ROOT / "schema/rules.json"
    rule_count = 0
    # 规则的 refs 允许四种写法：实体、实体.字段、通用字段组名、枚举名；
    # 也允许写跨实体的通用字段名（created_at / revision 这类由字段组提供的列）。
    all_field_names = {name for entity in entities.values() for name in _fields(entity)}
    bare_ok = (set(entities) | set(groups) | set(enums) | all_field_names)
    if not rules_path.exists():
        step.fail("缺少 schema/rules.json")
    else:
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        for group in rules.get("groups", []):
            for rule in group.get("rules", []):
                rule_count += 1
                for ref in rule.get("refs", []):
                    if "." not in ref:
                        if ref not in bare_ok:
                            step.fail(f"规则 {rule.get('id')} 引用了未知的实体/枚举/字段 {ref}")
                        continue
                    eid, fname = ref.split(".", 1)
                    if eid not in entities:
                        step.fail(f"规则 {rule.get('id')} 引用了不存在的实体 {eid}")
                    elif fname not in _fields(entities[eid]):
                        step.fail(f"规则 {rule.get('id')} 引用了不存在的字段 {ref}")

    coverage = model["coverage"]
    for item in coverage:
        for ref in item.get("entities", []):
            if ref not in entities:
                step.fail(f"覆盖项 {item.get('id')} 引用了不存在的实体 {ref}")

    stats = model.get("stats") or {}
    if stats.get("entities") != len(entities):
        step.fail("stats.entities 与实际实体数不一致")
    if stats.get("fields") != fields_total:
        step.fail("stats.fields 与实际字段数不一致")
    if stats.get("enums") != len(enums):
        step.fail("stats.enums 与实际枚举数不一致")
    step.note(f"实体 {len(entities)}｜字段 {fields_total}｜枚举 {len(enums)}｜规则 {rule_count}｜覆盖项 {len(coverage)}")
    return step


# ---------------------------------------------------------------- 3 DDL 实跑

def step_ddl(verbose: bool) -> Step:
    step = Step("DDL 实跑（schema/schema.sql → 内存 SQLite）")
    sql_path = ROOT / "schema/schema.sql"
    if not sql_path.exists():
        step.fail("缺少 schema/schema.sql")
        return step
    ddl = sql_path.read_text(encoding="utf-8")
    model = _load_model(step)
    if model is None:
        return step

    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.executescript(ddl)
    except sqlite3.Error as exc:
        step.fail(f"DDL 执行失败：{exc}")
        return step
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    entities = _entity_map(model)
    missing = sorted(set(entities) - tables)
    if missing:
        step.fail("模型里有实体但没有建表：" + "、".join(missing))
    extra = sorted(tables - set(entities))
    if extra:
        step.fail("建了表但模型里没有对应实体：" + "、".join(extra))

    for eid, entity in entities.items():
        if eid not in tables:
            continue
        info = {row[1]: row for row in conn.execute(f'PRAGMA table_info("{eid}")')}
        for fname, spec in _fields(entity).items():
            if fname not in info:
                step.fail(f"表 {eid} 缺少列 {fname}")
                continue
            if spec.get("req") and not info[fname][3]:
                step.fail(f"{eid}.{fname} 是必填字段，但 DDL 里没有 NOT NULL")
        for combo in entity.get("unique_together") or []:
            if not all(col in info for col in combo):
                continue
            for idx in [row[1] for row in conn.execute(
                    "SELECT * FROM sqlite_master WHERE type='index' AND tbl_name=?", (eid,))]:
                cols = [row[2] for row in conn.execute(f'PRAGMA index_info("{idx}")')]
                if cols == list(combo):
                    break
            else:
                step.fail(f"{eid} 的组合唯一约束 {combo} 没有对应的唯一索引")
    index_count = conn.execute(
        "SELECT count(*) FROM sqlite_master WHERE type='index'").fetchone()[0]
    step.note(f"建表 {len(tables)} 张，索引 {index_count} 个（含 SQLite 自动索引）")
    conn.close()
    return step


# ---------------------------------------------------------------- 4 已有库同步

def step_databases(verbose: bool) -> Step:
    step = Step("已有数据库与模型是否同步（tools/migrate_db.py --dry-run）")
    dbs = sorted((ROOT / "data").glob("*.db"))
    if not dbs:
        step.note("data/ 下暂无数据库，跳过")
        return step
    sys.path.insert(0, str(ROOT))
    from tools.migrate_db import migrate  # noqa: E402

    model = json.loads((ROOT / "schema/model.json").read_text(encoding="utf-8"))
    for db in dbs:
        try:
            actions = migrate(str(db), model, dry_run=True)
        except Exception as exc:  # noqa: BLE001
            step.fail(f"{db.name} 检查失败：{exc}")
            continue
        pending = [a for a in actions if not a.startswith("跳过")]
        if pending:
            step.warn(f"{db.name} 有 {len(pending)} 项待补：{pending[0]}"
                      f"（运行 `python tools/migrate_db.py {db.as_posix()}`）")
        else:
            step.note(f"{db.name} 已是最新")
    return step


# ---------------------------------------------------------------- 5 依赖边界

def step_dependencies(verbose: bool) -> Step:
    step = Step("依赖边界（app/ 只允许标准库 + 包内相对导入）")
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    allowed = stdlib | {"app"}
    for path in sorted((ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in allowed:
                        step.fail(f"{path.relative_to(ROOT)}:{node.lineno} 引入了非标准库依赖 {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                top = (node.module or "").split(".")[0]
                if top and top not in allowed:
                    step.fail(f"{path.relative_to(ROOT)}:{node.lineno} 引入了非标准库依赖 {node.module}")
    if not step.problems:
        step.note("app/ 无第三方依赖")
    return step


# ---------------------------------------------------------------- 6 编译

def step_compile(verbose: bool) -> Step:
    step = Step("编译（compileall app/ tools/ tests/）")
    for target in ("app", "tools", "tests"):
        code, _ = run([sys.executable, "-m", "compileall", "-q", target], verbose)
        if code != 0:
            step.fail(f"compileall {target} 失败")
    return step


# ---------------------------------------------------------------- 7 密钥扫描

def step_secrets(verbose: bool) -> Step:
    step = Step("密钥扫描与个人数据边界")
    code, out = run(["git", "ls-files"], verbose)
    tracked: list[str] = []
    if code == 0:
        tracked = [line.strip() for line in out.splitlines() if line.strip()]
    else:
        step.warn("不是 git 仓库，改为扫描文件系统")
        tracked = [str(p.relative_to(ROOT)).replace("\\", "/")
                   for p in ROOT.rglob("*") if p.is_file()
                   and "__pycache__" not in p.parts and ".git" not in p.parts]

    bad_paths = [rel for rel in tracked
                 if re.search(r"^(data/.*\.db|飞书导出/|config/feishu\.json)", rel)
                 or "credentials" in rel.lower() or re.search(r"\.bak-\d{8}-\d{6}$", rel)]
    for rel in bad_paths:
        step.fail(f"个人数据/凭据被纳入版本管理：{rel}")

    for rel in tracked:
        if rel.endswith(SECRET_SCAN_SKIP_SUFFIX) or rel.endswith(".json") and "prompt" in rel:
            continue
        path = ROOT / rel
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SECRET_PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(match.lastindex or 0)
                # 允许文档里出现“键名”本身
                if value.isupper() and "_" in value:
                    continue
                step.fail(f"{rel} 疑似包含明文凭据：{match.group(0)[:40]}…")
    if not step.problems:
        step.note(f"检查 {len(tracked)} 个纳入版本管理的文件，未发现凭据")
    return step


# ---------------------------------------------------------------- 8 单元测试

def step_index(verbose: bool) -> Step:
    step = Step("代码索引新鲜度（tools/index_code.py check）")
    code, out = run([sys.executable, "tools/index_code.py", "check"], verbose)
    if code != 0:
        detail = [l.strip() for l in out.splitlines() if l.strip()][-6:]
        step.fail("索引已过期，" + "；".join(detail))
    for line in out.splitlines():
        if line.strip().startswith(("✓", "·")):
            step.note(line.strip())
    return step


def step_tests(verbose: bool) -> Step:
    step = Step("单元测试（unittest discover -s tests）")
    code, out = run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], verbose)
    if code != 0:
        step.fail(f"单元测试失败（退出码 {code}）")
        stripped = [l for l in out.splitlines() if l.startswith(("FAIL:", "ERROR:"))]
        for line in stripped[:10]:
            step.fail(line)
    counts = re.search(r"Ran (\d+) test", out)
    tail = [l for l in out.splitlines() if l.startswith("OK") or l.startswith("FAILED")]
    step.note(("共 %s 条，%s" % (counts.group(1), tail[0] if tail else "")) if counts else "未解析到用例数")
    return step


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="全量质量闸门")
    parser.add_argument("--fast", action="store_true", help="跳过单元测试（只做静态检查）")
    parser.add_argument("--verbose", action="store_true", help="打印每步命令的原始输出")
    args = parser.parse_args(argv)

    steps = [
        ("1/9 模型构建", lambda: step_build(args.verbose)),
        ("2/9 模型自洽", lambda: step_model(args.verbose)),
        ("3/9 DDL 实跑", lambda: step_ddl(args.verbose)),
        ("4/9 库同步", lambda: step_databases(args.verbose)),
        ("5/9 依赖边界", lambda: step_dependencies(args.verbose)),
        ("6/9 编译", lambda: step_compile(args.verbose)),
        ("7/9 密钥扫描", lambda: step_secrets(args.verbose)),
        ("8/9 代码索引", lambda: step_index(args.verbose)),
    ]
    if not args.fast:
        steps.append(("9/9 单元测试", lambda: step_tests(args.verbose)))

    results: list[Step] = []
    for label, func in steps:
        print(f"[{label}] ...")
        started = time.time()
        try:
            step = func()
        except Exception as exc:  # noqa: BLE001
            step = Step(label)
            step.fail(f"检查过程本身出错：{type(exc).__name__}: {exc}")
        step.duration = time.time() - started
        results.append(step)
        for note in step.notes:
            print(f"    · {note}")
        for problem in step.problems:
            print(f"    ✗ {problem}")
        print(f"    {'✗ 失败' if step.failed else '✓ 通过'}（{step.duration:.1f}s）")

    failed = [s for s in results if s.failed]
    total = sum(s.duration for s in results)
    print("\n" + "=" * 60)
    if failed:
        print(f"质量闸门未通过：{len(failed)}/{len(results)} 步失败（{total:.1f}s）")
        for step in failed:
            print(f"  ✗ {step.name}")
        return 1
    print(f"质量闸门全部通过：{len(results)} 步（{total:.1f}s）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
