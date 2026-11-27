# -*- coding: utf-8 -*-
"""代码索引与项目知识库（stdlib + ast + git，无第三方依赖）。

设计要点（见 docs/技术选型与决策记录.md ADR-0015）：
- 索引是**派生产物**：`.index/index.json` 可随时重建，不进版本库；
  面向人与 Agent 的可读版本生成到 `docs/代码索引.md`（进版本库，便于 review）。
- 用 Python 自带的 `ast` 做符号/引用/调用/导入分析（语言原生解析器，比正则可靠）；
  动态关系（反射、字符串拼命令）无法静态确定，一律进 `unresolved` 而不是猜。
- 增量：按文件 sha256 与既有索引比对，只重新分析变化的文件（不依赖 git 也能工作）。

用法：
    python tools/index_code.py build [--changed] [--quiet]
    python tools/index_code.py check                 # 索引是否与代码一致（CI 闸门）
    python tools/index_code.py report                # 生成 docs/代码索引.md
    python tools/index_code.py stats
    python tools/index_code.py files [--grep 关键字] [--area product|tooling|test|data|doc]
    python tools/index_code.py find <名字> [--kind function|class|method]
    python tools/index_code.py refs <名字>
    python tools/index_code.py callers <名字>
    python tools/index_code.py deps [文件] [--reverse]
    python tools/index_code.py routes
    python tools/index_code.py data [实体名]
    python tools/index_code.py tests [文件]
    python tools/index_code.py config
    python tools/index_code.py unresolved
"""
import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX_DIR = os.path.join(ROOT, ".index")
INDEX_JSON = os.path.join(INDEX_DIR, "index.json")
REPORT_MD = os.path.join(ROOT, "docs", "代码索引.md")

SKIP_DIRS = {".git", ".index", "__pycache__", "data", "backup", "飞书导出", ".vscode", ".idea",
             "node_modules", ".venv", "venv", "dist", "build"}
# 索引自己的生成物不进索引，否则每次生成报告都会把索引标记为过期
SKIP_FILES = {"docs/代码索引.md"}
INCLUDE_EXTS = {".py", ".json", ".md", ".sh", ".sql", ".txt", ".yml", ".yaml", ".gitignore", ""}
TEXT_EXTS = INCLUDE_EXTS - {""}

AREA_RULES = (
    ("app/", "product"),
    ("tests/", "test"),
    ("schema/", "data"),
    ("docs/", "doc"),
    ("prompts/", "prompt"),
    ("tools/reqdoc/", "tooling"),
    ("tools/", "tooling"),
)


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def area_of(rel_path):
    for prefix, area in AREA_RULES:
        if rel_path.startswith(prefix):
            return area
    return "root"


def iter_repo_files():
    """遍历仓库里的文本文件（跳过数据、备份、缓存目录）。"""
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in sorted(files):
            path = os.path.join(base, name)
            rel_path = rel(path)
            if rel_path.startswith(".index/") or rel_path in SKIP_FILES:
                continue
            ext = os.path.splitext(name)[1].lower()
            if name.startswith(".") and name not in (".gitignore",):
                continue
            if ext not in INCLUDE_EXTS:
                continue
            if ext in ("",) and "." not in name and name != "Makefile":
                continue
            yield path, rel_path, ext


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fp:
        return fp.read()


def first_line(text, limit=200):
    if not text:
        return ""
    line = text.strip().splitlines()[0].strip()
    return line[:limit]


# ---------------------------------------------------------------- python 分析
def _call_names(node):
    """收集一个表达式里出现的调用名（简单名与属性名）。"""
    names = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.append(func.id)
            elif isinstance(func, ast.Attribute):
                names.append(_attr_name(func))
    return names


def _attr_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _signature(func, source_lines):
    try:
        return ast.unparse(func.args)
    except Exception:                                        # pragma: no cover - 兜底
        return source_lines[func.lineno - 1].strip()[:120]


def analyze_python(path, rel_path):
    """解析一个 Python 文件，产出文件级与符号级索引片段。"""
    text = read_text(path)
    info = {
        "path": rel_path,
        "module": rel_path[:-3].replace("/", "."),
        "lines": text.count("\n") + 1,
        "sha256": sha256_bytes(text.encode("utf-8")),
        "purpose": "",
        "imports": [],
        "symbols": [],
        "refs": [],
        "calls": [],
        "globals": [],
        "env_vars": [],
        "strings": [],
        "third_party": [],
        "unresolved": [],
    }
    try:
        tree = ast.parse(text, filename=rel_path)
    except SyntaxError as exc:
        info["unresolved"].append({"file": rel_path, "reason": "语法错误：%s" % exc})
        return info
    source_lines = text.splitlines()
    info["purpose"] = first_line(ast.get_docstring(tree) or "")
    if not info["purpose"]:
        for node in tree.body:
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                info["purpose"] = first_line(node.value.value)
                break

    # ---- 导入
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                info["imports"].append({"name": alias.name, "asname": alias.asname,
                                        "line": node.lineno, "level": 0,
                                        "names": [alias.name.split(".")[0]]})
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [a.name for a in node.names]
            info["imports"].append({"name": module, "asname": None, "line": node.lineno,
                                    "level": node.level, "names": names})

    # ---- 符号（含嵌套）
    def visit(node, parent=None, prefix=""):
        for child in node.body if hasattr(node, "body") else []:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = "%s.%s" % (prefix, child.name) if prefix else child.name
                info["symbols"].append({
                    "id": "%s::%s" % (rel_path, qual),
                    "name": child.name,
                    "qualname": qual,
                    "kind": "method" if prefix else "function",
                    "file": rel_path,
                    "line": child.lineno,
                    "end_line": getattr(child, "end_lineno", child.lineno),
                    "signature": _signature(child, source_lines),
                    "decorators": [_attr_name(d) if not isinstance(d, ast.Call) else _attr_name(d.func)
                                   for d in child.decorator_list],
                    "doc": first_line(ast.get_docstring(child) or ""),
                    "parent": prefix or None,
                    "calls": sorted(set(_call_names(child))),
                    "args": [a.arg for a in child.args.args] + [a.arg for a in child.args.kwonlyargs],
                })
                visit(child, child, qual)
            elif isinstance(child, ast.ClassDef):
                qual = "%s.%s" % (prefix, child.name) if prefix else child.name
                bases = [_attr_name(b) if not isinstance(b, ast.Call) else _attr_name(b.func)
                         for b in child.bases]
                info["symbols"].append({
                    "id": "%s::%s" % (rel_path, qual),
                    "name": child.name,
                    "qualname": qual,
                    "kind": "class",
                    "file": rel_path,
                    "line": child.lineno,
                    "end_line": getattr(child, "end_lineno", child.lineno),
                    "signature": ", ".join(bases),
                    "decorators": [],
                    "doc": first_line(ast.get_docstring(child) or ""),
                    "parent": prefix or None,
                    "calls": [],
                    "args": [],
                })
                visit(child, child, qual)

    visit(tree, None, "")

    # ---- 引用、调用、全局常量、环境变量、字符串、第三方
    imported_names = set()
    internal_prefixes = ("app", "tests", "tools")
    for imp in info["imports"]:
        base = (imp["name"] or "").split(".")[0]
        if imp["level"]:
            continue
        if base in sys.stdlib_module_names or base in internal_prefixes:
            imported_names.update(imp["names"])
            imported_names.add(imp["asname"] or base)
        elif base:
            info["third_party"].append({"name": imp["name"], "line": imp["line"]})

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            info["refs"].append({"name": node.id, "line": node.lineno, "kind": "name"})
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            full = _attr_name(node)
            if "." in full:
                info["refs"].append({"name": full.split(".")[-1], "full": full,
                                     "line": node.lineno, "kind": "attr"})
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    try:
                        value = ast.literal_eval(node.value)
                    except Exception:
                        value = None
                    info["globals"].append({
                        "name": target.id, "line": node.lineno,
                        "value": (repr(value)[:120] if value is not None else
                                  source_lines[node.lineno - 1].strip()[:120]),
                    })
        elif isinstance(node, ast.Call):
            func = node.func
            full = _attr_name(func) if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if full in ("os.environ.get", "os.getenv", "environ.get"):
                if node.args and isinstance(node.args[0], ast.Constant):
                    info["env_vars"].append({"name": node.args[0].value, "line": node.lineno,
                                             "file": rel_path})
            elif full == "os.environ" or (isinstance(func, ast.Subscript)
                                          and _attr_name(func.value) == "os.environ"):
                pass
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if 0 < len(node.value) <= 300:
                info["strings"].append({"value": node.value, "line": node.lineno})
    # os.environ["X"] / os.environ.get("X")
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _attr_name(node.value) == "os.environ":
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                info["env_vars"].append({"name": node.slice.value, "line": node.lineno,
                                         "file": rel_path})
    return info


# ---------------------------------------------------------------- CLI 路由
def extract_routes(analyses):
    """从 app/cli.py 的 build_parser() 里还原命令树（命令 → 处理函数）。

    只认静态写法：`x = sub.add_subparsers(...)`、`y = x.add_parser("名字", help=...)`、
    `y.set_defaults(func=_handler)`。动态注册（循环拼命令）会被记为 unresolved。
    """
    cli = analyses.get("app/cli.py")
    if not cli:
        return [], [{"file": "app/cli.py", "reason": "未找到 CLI 文件，路由索引缺失"}]
    path = os.path.join(ROOT, "app/cli.py")
    tree = ast.parse(read_text(path), filename="app/cli.py")
    build = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "build_parser":
            build = node
            break
    if build is None:
        return [], [{"file": "app/cli.py", "reason": "build_parser() 不存在"}]

    var_path = {}                      # 变量名 → 命令路径（按源码顺序推进，允许变量复用）
    routes = []

    def path_of(node):
        if isinstance(node, ast.Name):
            return list(var_path.get(node.id, []))
        if isinstance(node, ast.Call):
            return path_of(node.func)
        if isinstance(node, ast.Attribute):
            return path_of(node.value)
        return []

    def handle(stmt):
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 \
                and isinstance(stmt.targets[0], ast.Name):
            target = stmt.targets[0].id
            value = stmt.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
                attr = value.func.attr
                if attr == "add_subparsers":
                    var_path[target] = path_of(value.func.value)
                elif attr == "add_parser":
                    if not value.args or not isinstance(value.args[0], ast.Constant):
                        return
                    name = value.args[0].value
                    var_path[target] = path_of(value.func.value) + [name]
                    routes.append({
                        "command": " ".join(var_path[target]),
                        "name": name,
                        "parent": " ".join(var_path[target][:-1]),
                        "help": next((k.value.value for k in value.keywords
                                      if k.arg == "help" and isinstance(k.value, ast.Constant)), ""),
                        "handler": None,
                        "file": "app/cli.py",
                        "line": value.lineno,
                    })
            elif isinstance(value, ast.Call):
                var_path[target] = path_of(value.func.value)
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call) \
                and isinstance(stmt.value.func, ast.Attribute) \
                and stmt.value.func.attr == "set_defaults" \
                and isinstance(stmt.value.func.value, ast.Name):
            command = " ".join(var_path.get(stmt.value.func.value.id, []))
            handler = None
            for kw in stmt.value.keywords:
                if kw.arg == "func":
                    if isinstance(kw.value, ast.Name):
                        handler = kw.value.id
                    elif isinstance(kw.value, ast.Lambda):
                        handler = "<lambda>"
            for route in reversed(routes):
                if route["command"] == command:
                    route["handler"] = handler
                    route["handler_line"] = stmt.lineno
                    break

    def walk(node):
        for child in ast.iter_child_nodes(node):
            handle(child)
            walk(child)

    walk(build)
    groups = {r["parent"] for r in routes if r["parent"]}
    for route in routes:
        route["is_group"] = route["command"] in groups
    unresolved = []
    for route in routes:
        if not route.get("handler") and not route["is_group"]:
            unresolved.append({"file": "app/cli.py",
                               "reason": "命令 %s 未静态解析出处理函数" % route["command"]})
    return routes, unresolved


# ---------------------------------------------------------------- 数据/提示词/测试
def index_model():
    path = os.path.join(ROOT, "schema", "model.json")
    with open(path, encoding="utf-8") as fp:
        model = json.load(fp)
    entities = []
    for entity in model["entities"]:
        entities.append({
            "id": entity["id"],
            "name": entity["name"],
            "layer": entity.get("layer"),
            "priority": entity.get("priority"),
            "flags": entity.get("flags", []),
            "fields": len(entity.get("full_fields", [])),
            "custom_fields": len(entity.get("fields", [])),
            "purpose": first_line(entity.get("purpose", "")),
            "source": "schema/model.json",
            "defined_in": "schema/model.core.json + schema/parts/*.entities.json",
        })
    enums = [{"name": name, "label": value.get("l", ""), "values": len(value.get("v", []))}
             for name, value in sorted(model["enums"].items())]
    return {"entities": entities, "enums": enums, "stats": model.get("stats", {})}


def index_prompts():
    out = []
    prompt_dir = os.path.join(ROOT, "prompts")
    if not os.path.isdir(prompt_dir):
        return out
    for name in sorted(os.listdir(prompt_dir)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(prompt_dir, name)
        with open(path, encoding="utf-8") as fp:
            data = json.load(fp)
        out.append({
            "file": "prompts/" + name,
            "name": data.get("name"),
            "job_type": data.get("job_type"),
            "version": data.get("version"),
            "variables": len(data.get("variables", [])),
            "workflow": (data.get("workflow") or {}).get("name"),
            "target_models": (data.get("workflow") or {}).get("target_models", []),
        })
    return out


def index_tests(test_analyses):
    """测试文件 → 用例清单 + 被覆盖的产品模块（按导入关系推断，不做执行覆盖）。"""
    out = []
    for rel_path, info in sorted(test_analyses.items()):
        cases = []
        for symbol in info["symbols"]:
            if symbol["kind"] == "method" and symbol["parent"] and symbol["name"].startswith("test_"):
                cases.append({"name": "%s.%s" % (symbol["parent"], symbol["name"]),
                              "line": symbol["line"]})
        covers = sorted({imp["name"] for imp in info["imports"]
                         if (imp["name"] or "").startswith("app")})
        out.append({"file": rel_path, "cases": cases, "case_count": len(cases),
                    "covers": covers, "purpose": info["purpose"]})
    return out


# ---------------------------------------------------------------- 构建
def build(incremental=False, quiet=False):
    previous = load_index() if incremental else None
    prev_files = {}
    if previous:
        for item in previous.get("files", []):
            prev_files[item["path"]] = item

    files = []
    analyses = {}
    py_infos = {}
    strings_by_file = {}
    for path, rel_path, ext in iter_repo_files():
        data = open(path, "rb").read()
        digest = sha256_bytes(data)
        entry = {
            "path": rel_path,
            "area": area_of(rel_path),
            "ext": ext or "(无扩展名)",
            "bytes": len(data),
            "sha256": digest,
        }
        if ext == ".py":
            old = prev_files.get(rel_path)
            if old and old.get("sha256") == digest and previous:
                cached = (previous.get("_python") or {}).get(rel_path)
                if cached:
                    entry.update({k: cached.get(k) for k in
                                  ("module", "lines", "purpose", "imports", "symbols", "refs",
                                   "calls", "globals", "env_vars", "strings", "third_party",
                                   "unresolved")})
                    py_infos[rel_path] = cached
                    strings_by_file[rel_path] = cached.get("strings", [])
                    files.append(entry)
                    continue
            info = analyze_python(path, rel_path)
            analyses[rel_path] = info
            py_infos[rel_path] = info
            strings_by_file[rel_path] = info["strings"]
            entry.update({k: info[k] for k in
                          ("module", "lines", "purpose", "imports", "symbols", "refs", "calls",
                           "globals", "env_vars", "strings", "third_party", "unresolved")})
        elif ext in TEXT_EXTS:
            try:
                entry["lines"] = read_text(path).count("\n") + 1
            except OSError:
                entry["lines"] = 0
        files.append(entry)

    # ---- 项目内定义名（用于过滤引用噪声）与模块依赖图
    defined = {}
    for rel_path, info in py_infos.items():
        for symbol in info["symbols"]:
            defined.setdefault(symbol["name"], []).append(
                {"file": rel_path, "line": symbol["line"], "kind": symbol["kind"],
                 "qualname": symbol["qualname"]})
    defined_names = set(defined)
    imported = set()
    for info in py_infos.values():
        for imp in info["imports"]:
            imported.update(imp["names"])
    interesting = defined_names | imported

    refs = []
    calls = []
    for rel_path, info in sorted(py_infos.items()):
        for ref in info["refs"]:
            if ref["name"] in interesting:
                item = dict(ref)
                item["file"] = rel_path
                refs.append(item)
        for symbol in info["symbols"]:
            for called in symbol["calls"]:
                simple = called.split(".")[-1]
                if simple in interesting or simple in ("print", "len", "open", "range", "str",
                                                       "int", "dict", "list", "set", "sorted",
                                                       "isinstance", "getattr"):
                    calls.append({"caller": symbol["qualname"], "caller_id": symbol["id"],
                                  "caller_file": rel_path, "callee": called,
                                  "callee_simple": simple})

    deps = {}
    module_to_file = {}
    for rel_path, info in py_infos.items():
        module_to_file[info["module"]] = rel_path
    for rel_path, info in sorted(py_infos.items()):
        targets = set()
        for imp in info["imports"]:
            if imp["level"]:
                base = os.path.dirname(rel_path).replace("/", ".")
                candidate = ("%s.%s" % (base, imp["name"])).strip(".")
                targets.add(module_to_file.get(candidate, candidate))
                continue
            name = imp["name"]
            for module, target_file in module_to_file.items():
                if module == name or module.startswith(name + "."):
                    targets.add(target_file)
        deps[rel_path] = sorted(t for t in targets if t != rel_path)

    routes, route_unresolved = extract_routes(py_infos)
    model_index = index_model()
    data_refs = {}
    for entity in model_index["entities"]:
        pattern = re.compile(r"(?<![A-Za-z0-9_])%s(?![A-Za-z0-9_])" % re.escape(entity["id"]))
        hits = []
        for rel_path, strings in strings_by_file.items():
            for item in strings:
                if pattern.search(item["value"]):
                    hits.append({"file": rel_path, "line": item["line"]})
                    break
        data_refs[entity["id"]] = hits

    unresolved = []
    for rel_path, info in py_infos.items():
        unresolved.extend(info["unresolved"])
    unresolved.extend(route_unresolved)

    index = {
        "meta": {
            "generated_at": utc_now(),
            "root": ROOT,
            "python": sys.version.split()[0],
            "file_count": len(files),
            "python_file_count": len(py_infos),
            "symbol_count": sum(len(i["symbols"]) for i in py_infos.values()),
            "route_count": len(routes),
            "incremental": bool(incremental),
            "git_head": git_head(),
            "scope": "app/ tests/ tools/ schema/ docs/ prompts/ 与根目录配置文件；"
                     "不含 data/、backup/、.index/、飞书导出/",
            "limits": [
                "动态调用（getattr、反射、字符串拼命令）无法静态确定，见 unresolved",
                "UI/页面/组件：当前项目没有前端，前端索引不适用（需求第 8 章为界面约束）",
                "测试覆盖按导入关系推断，不是运行时覆盖率",
                "数据引用按字符串常量匹配实体 id，属启发式，可能漏判或误判",
            ],
        },
        "files": files,
        "symbols": [s for info in py_infos.values() for s in info["symbols"]],
        "refs": refs,
        "calls": calls,
        "deps": deps,
        "routes": routes,
        "data": {"model": model_index, "refs": data_refs,
                 "prompts": index_prompts()},
        "tests": index_tests({p: i for p, i in py_infos.items() if p.startswith("tests/")}),
        "config": {
            "env_vars": sorted({(v["name"], v["file"], v["line"])
                                for info in py_infos.values() for v in info["env_vars"]}),
            "module_constants": sorted(
                {(g["name"], rel_path, g["line"]) for rel_path, info in py_infos.items()
                 for g in info["globals"]}),
        },
        "third_party": sorted({(t["name"], rel_path, t["line"])
                               for rel_path, info in py_infos.items()
                               for t in info["third_party"]}),
        "unresolved": unresolved,
        "_python": py_infos,
    }
    save_index(index)
    if not quiet:
        meta = index["meta"]
        print("✓ 索引完成：%d 个文件（Python %d）｜符号 %d｜引用 %d｜调用 %d｜命令 %d｜%s"
              % (meta["file_count"], meta["python_file_count"], meta["symbol_count"],
                 len(refs), len(calls), meta["route_count"],
                 "增量" if incremental else "全量"))
        if unresolved:
            print("  未能静态解析 %d 处（见 index unresolved）" % len(unresolved))
    return index


def git_head():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0:
            dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                                   capture_output=True, text=True, timeout=10)
            head = out.stdout.strip()
            return head + ("+dirty" if dirty.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def save_index(index):
    os.makedirs(INDEX_DIR, exist_ok=True)
    with open(INDEX_JSON, "w", encoding="utf-8") as fp:
        json.dump(index, fp, ensure_ascii=False, indent=1, sort_keys=False)


def load_index():
    if not os.path.exists(INDEX_JSON):
        return None
    with open(INDEX_JSON, encoding="utf-8") as fp:
        return json.load(fp)


def check(quiet=False):
    """索引与代码是否一致：比对文件集合与 sha256（不重新解析，快）。"""
    index = load_index()
    if index is None:
        print("✗ 还没有索引，请先运行：python tools/index_code.py build")
        return 1
    known = {item["path"]: item["sha256"] for item in index["files"]}
    current = {}
    for path, rel_path, ext in iter_repo_files():
        current[rel_path] = sha256_bytes(open(path, "rb").read())
    stale = sorted(p for p, digest in current.items()
                   if p in known and known[p] != digest)
    added = sorted(p for p in current if p not in known)
    removed = sorted(p for p in known if p not in current)
    if not (stale or added or removed):
        if not quiet:
            print("✓ 索引与代码一致（%d 个文件，生成于 %s）"
                  % (len(current), index["meta"]["generated_at"]))
        return 0
    print("✗ 索引已过期：变更 %d｜新增 %d｜删除 %d" % (len(stale), len(added), len(removed)))
    for label, items in (("变更", stale), ("新增", added), ("删除", removed)):
        for item in items[:20]:
            print("  %s %s" % (label, item))
        if len(items) > 20:
            print("  … 其余 %d 个" % (len(items) - 20))
    print("  修复：python tools/index_code.py build --changed")
    return 1


# ---------------------------------------------------------------- 查询
def _require_index():
    index = load_index()
    if index is None:
        raise SystemExit("✗ 还没有索引，请先运行：python tools/index_code.py build")
    return index


def cmd_stats(args):
    index = _require_index()
    meta = index["meta"]
    print("索引生成：%s（%s）" % (meta["generated_at"], "增量" if meta["incremental"] else "全量"))
    print("git：%s｜Python %s" % (meta.get("git_head") or "未提交", meta["python"]))
    print("文件 %d（Python %d）｜符号 %d｜引用 %d｜调用 %d｜命令 %d"
          % (meta["file_count"], meta["python_file_count"], meta["symbol_count"],
             len(index["refs"]), len(index["calls"]), meta["route_count"]))
    areas = {}
    for item in index["files"]:
        areas[item["area"]] = areas.get(item["area"], 0) + 1
    print("按区域：" + "｜".join("%s %d" % kv for kv in sorted(areas.items())))
    kinds = {}
    for symbol in index["symbols"]:
        kinds[symbol["kind"]] = kinds.get(symbol["kind"], 0) + 1
    print("按符号类型：" + "｜".join("%s %d" % kv for kv in sorted(kinds.items())))
    model_stats = index["data"]["model"]["stats"]
    print("数据模型：实体 %s｜字段 %s｜枚举 %s｜覆盖项 %s"
          % (model_stats.get("entities"), model_stats.get("fields"),
             model_stats.get("enums"), model_stats.get("coverage")))
    test_cases = sum(item["case_count"] for item in index["tests"])
    print("测试：%d 个文件｜%d 条用例" % (len(index["tests"]), test_cases))
    print("未能静态解析：%d 处" % len(index["unresolved"]))
    return 0


def cmd_files(args):
    index = _require_index()
    items = index["files"]
    if args.area:
        items = [i for i in items if i["area"] == args.area]
    if args.grep:
        items = [i for i in items if args.grep.lower() in i["path"].lower()]
    print("%d 个文件：" % len(items))
    for item in items:
        print("  [%s] %s（%d 行%s）%s" % (item["area"], item["path"], item.get("lines", 0),
                                          "，%d 字节" % item["bytes"], item.get("purpose", "")))
    return 0


def _match_symbols(index, name, kind=None):
    hits = []
    for symbol in index["symbols"]:
        if symbol["name"] == name or symbol["qualname"] == name or symbol["id"] == name:
            if kind and symbol["kind"] != kind:
                continue
            hits.append(symbol)
    if not hits:                       # 退回模糊匹配
        for symbol in index["symbols"]:
            if name.lower() in symbol["qualname"].lower():
                if kind and symbol["kind"] != kind:
                    continue
                hits.append(symbol)
    return hits


def cmd_find(args):
    index = _require_index()
    hits = _match_symbols(index, args.name, args.kind)
    if not hits:
        print("没有找到符号：%s" % args.name)
        return 1
    print("定义 %d 处：" % len(hits))
    for symbol in hits:
        print("  %s:%d  %s %s(%s)%s"
              % (symbol["file"], symbol["line"], symbol["kind"], symbol["qualname"],
                 symbol["signature"], ("  # " + symbol["doc"]) if symbol["doc"] else ""))
    return 0


def cmd_refs(args):
    index = _require_index()
    hits = [r for r in index["refs"] if r["name"] == args.name]
    if not hits and args.name.endswith(")"):
        hits = [r for r in index["refs"] if r["name"] == args.name[:-2]]
    print("引用 %d 处（按文件聚合）：" % len(hits))
    grouped = {}
    for ref in hits:
        grouped.setdefault(ref["file"], []).append(ref)
    for file, items in sorted(grouped.items()):
        lines = ", ".join(str(i["line"]) for i in sorted(items, key=lambda x: x["line"]))
        print("  %s：%d 处｜行 %s" % (file, len(items), lines))
    return 0


def cmd_callers(args):
    index = _require_index()
    hits = [c for c in index["calls"]
            if c["callee_simple"] == args.name or c["callee"] == args.name]
    if not hits:
        print("没有调用方：%s" % args.name)
        return 1
    grouped = {}
    for call in hits:
        grouped.setdefault(call["caller_file"], []).append(call)
    print("被 %d 处调用：" % len(hits))
    for file, items in sorted(grouped.items()):
        names = sorted({"%s (行 %d)" % (i["caller"], index_line_of(index, i["caller_id"]))
                        for i in items})
        print("  %s：%s" % (file, "；".join(names)))
    return 0


def index_line_of(index, symbol_id):
    for symbol in index["symbols"]:
        if symbol["id"] == symbol_id:
            return symbol["line"]
    return 0


def cmd_deps(args):
    index = _require_index()
    deps = index["deps"]
    if args.reverse:
        target = args.file
        users = sorted(f for f, items in deps.items() if target in items)
        print("%s 被 %d 个模块依赖：" % (target, len(users)))
        for user in users:
            print("  %s" % user)
        return 0
    if args.file:
        items = deps.get(args.file)
        if items is None:
            print("索引里没有该文件：%s" % args.file)
            return 1
        print("%s 依赖 %d 个模块：" % (args.file, len(items)))
        for item in items:
            print("  %s" % item)
        return 0
    print("模块依赖图（%d 个模块，仅列内部依赖）：" % len(deps))
    for file, items in sorted(deps.items()):
        if not items:
            continue
        print("  %s → %s" % (file, ", ".join(items)))
    return 0


def cmd_routes(args):
    index = _require_index()
    print("命令 %d 个：" % len(index["routes"]))
    for route in index["routes"]:
        handler = route.get("handler") or "(未解析)"
        print("  %-28s → %-16s %s（app/cli.py:%d）"
              % (route["command"], handler, route["help"], route["line"]))
    return 0


def cmd_data(args):
    index = _require_index()
    model = index["data"]["model"]
    entities = model["entities"]
    if args.name:
        entities = [e for e in entities if args.name in e["id"] or args.name in (e["name"] or "")]
    for entity in entities:
        refs = index["data"]["refs"].get(entity["id"], [])
        print("  %-18s %s｜%s｜字段 %d（自定义 %d）｜代码引用 %d 处"
              % (entity["id"], entity["name"], entity["layer"], entity["fields"],
                 entity["custom_fields"], len(refs)))
        for ref in refs[:5]:
            print("        %s:%d" % (ref["file"], ref["line"]))
        if len(refs) > 5:
            print("        … 其余 %d 处" % (len(refs) - 5))
    print("枚举 %d 组｜提示词 %d 个｜数据模型定义见 schema/model.json"
          % (len(model["enums"]), len(index["data"]["prompts"])))
    return 0


def cmd_tests(args):
    index = _require_index()
    for item in index["tests"]:
        if args.file and args.file not in item["file"]:
            continue
        print("%s：%d 条用例｜覆盖模块 %s" % (item["file"], item["case_count"],
                                              ", ".join(item["covers"]) or "（无）"))
        for case in item["cases"]:
            print("    %s（行 %d）" % (case["name"], case["line"]))
    return 0


def cmd_config(args):
    index = _require_index()
    print("环境变量 %d 处：" % len(index["config"]["env_vars"]))
    for name, file, line in index["config"]["env_vars"]:
        print("  %-28s %s:%d" % (name, file, line))
    consts = index["config"]["module_constants"]
    print("模块级常量 %d 个：" % len(consts))
    for name, file, line in consts:
        print("  %-28s %s:%d" % (name, file, line))
    print("第三方依赖 %d 处：" % len(index["third_party"]))
    for name, file, line in index["third_party"]:
        print("  %-28s %s:%d" % (name, file, line))
    return 0


def cmd_unresolved(args):
    index = _require_index()
    if not index["unresolved"]:
        print("✓ 没有未能解析的项")
        return 0
    print("未能静态解析 %d 处：" % len(index["unresolved"]))
    for item in index["unresolved"]:
        print("  %s：%s" % (item["file"], item["reason"]))
    print("说明：动态调用无法静态确定，属已知局限，不是错误。")
    return 0


# ---------------------------------------------------------------- 报告
def cmd_report(args):
    index = _require_index()
    model = index["data"]["model"]
    lines = []
    add = lines.append
    add("# 代码索引（生成物）")
    add("")
    add("> 本文件由 `python tools/index_code.py report` 生成，**不要手工编辑**。")
    add("> 机器索引在 `.index/index.json`（不进版本库）；本文件进版本库，便于 review 索引变化。")
    add("")
    add("- 生成时间：%s" % index["meta"]["generated_at"])
    add("- git：%s｜Python %s" % (index["meta"].get("git_head") or "未提交", index["meta"]["python"]))
    add("- 覆盖范围：%s" % index["meta"]["scope"])
    add("- 规模：文件 %d（Python %d）｜符号 %d｜引用 %d｜调用 %d｜命令 %d｜测试 %d 条"
        % (index["meta"]["file_count"], index["meta"]["python_file_count"],
           index["meta"]["symbol_count"], len(index["refs"]), len(index["calls"]),
           index["meta"]["route_count"], sum(t["case_count"] for t in index["tests"])))
    add("")
    add("## 1. 索引的边界（先说清楚不代表什么）")
    add("")
    for limit in index["meta"]["limits"]:
        add("- %s" % limit)
    add("")
    if index["unresolved"]:
        add("本次未能静态解析 %d 处：" % len(index["unresolved"]))
        add("")
        for item in index["unresolved"][:20]:
            add("- `%s`：%s" % (item["file"], item["reason"]))
        add("")
    add("## 2. 目录与文件索引")
    add("")
    areas = {}
    for item in index["files"]:
        areas.setdefault(item["area"], []).append(item)
    for area in sorted(areas):
        add("### 2.%d %s（%d 个文件）" % (sorted(areas).index(area) + 1, area, len(areas[area])))
        add("")
        add("| 文件 | 行数 | 用途 |")
        add("| --- | --- | --- |")
        for item in sorted(areas[area], key=lambda x: x["path"]):
            add("| `%s` | %d | %s |" % (item["path"], item.get("lines", 0),
                                        item.get("purpose", "") or "-"))
        add("")
    add("## 3. 命令与入口索引")
    add("")
    add("| 命令 | 处理函数 | 说明 | 位置 |")
    add("| --- | --- | --- | --- |")
    for route in index["routes"]:
        add("| `%s` | `%s` | %s | app/cli.py:%d |"
            % (route["command"], route.get("handler") or "未解析", route["help"], route["line"]))
    add("")
    add("## 4. 模块依赖索引（仅项目内部依赖）")
    add("")
    add("| 模块 | 依赖 |")
    add("| --- | --- |")
    for file, items in sorted(index["deps"].items()):
        add("| `%s` | %s |" % (file, "，".join("`%s`" % i for i in items) if items else "-"))
    add("")
    add("### 4.1 反向依赖（被谁依赖）")
    add("")
    reverse = {}
    for file, items in index["deps"].items():
        for item in items:
            reverse.setdefault(item, []).append(file)
    for target in sorted(reverse):
        add("- `%s` ← %s" % (target, "，".join("`%s`" % f for f in sorted(reverse[target]))))
    add("")
    add("## 5. 数据索引：实体 ↔ 代码")
    add("")
    add("| 实体 | 中文 | 层 | 字段 | 代码引用（文件数） |")
    add("| --- | --- | --- | --- | --- |")
    for entity in model["entities"]:
        refs = index["data"]["refs"].get(entity["id"], [])
        add("| `%s` | %s | %s | %d | %d |"
            % (entity["id"], entity["name"], entity["layer"], entity["fields"], len(refs)))
    add("")
    add("枚举 %d 组，明细见 `docs/个人成长档案系统-数据模型设计 V1.0.md`；"
        "各实体在代码里的引用位置：`python tools/index_code.py data <实体>`。"
        % len(model["enums"]))
    add("")
    add("## 6. 提示词与 Agent 配置索引")
    add("")
    add("| 文件 | 名称 | job_type | 版本 | 变量数 | 工作流 | 目标模型 |")
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for item in index["data"]["prompts"]:
        add("| `%s` | %s | %s | %s | %d | %s | %s |"
            % (item["file"], item["name"], item["job_type"], item["version"], item["variables"],
               item["workflow"], "、".join(item["target_models"])))
    add("")
    add("## 7. 测试索引")
    add("")
    for item in index["tests"]:
        add("### %s（%d 条）" % (item["file"], item["case_count"]))
        add("")
        add("覆盖模块：%s" % ("，".join("`%s`" % c for c in item["covers"]) or "（无）"))
        add("")
        for case in item["cases"]:
            add("- `%s`（行 %d）" % (case["name"], case["line"]))
        add("")
    add("## 8. 配置与环境变量索引")
    add("")
    add("| 环境变量 | 位置 |")
    add("| --- | --- |")
    for name, file, line in index["config"]["env_vars"]:
        add("| `%s` | %s:%d |" % (name, file, line))
    add("")
    add("模块级常量（配置文件之外的固定口径）：")
    add("")
    for name, file, line in index["config"]["module_constants"]:
        add("- `%s` — %s:%d" % (name, file, line))
    add("")
    add("## 9. 外部依赖索引")
    add("")
    if index["third_party"]:
        add("| 依赖 | 位置 |")
        add("| --- | --- |")
        for name, file, line in index["third_party"]:
            add("| `%s` | %s:%d |" % (name, file, line))
    else:
        add("产品代码与工具链**不依赖任何第三方包**（ADR-0001）。")
    add("")
    add("## 10. 维护方式")
    add("")
    add("```bash")
    add("python tools/index_code.py build            # 全量重建")
    add("python tools/index_code.py build --changed  # 只重新分析变化的文件")
    add("python tools/index_code.py check            # 索引是否过期（质量闸门会跑）")
    add("python tools/index_code.py report           # 重新生成本文件")
    add("python tools/index_code.py find|refs|callers|deps|routes|data|tests|config|stats")
    add("```")
    add("")
    with open(REPORT_MD, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines) + "\n")
    print("✓ 已生成 %s（%d 行）" % (rel(REPORT_MD), len(lines)))
    return 0


# ---------------------------------------------------------------- CLI
def build_parser():
    parser = argparse.ArgumentParser(
        description="代码索引与项目知识库（stdlib + ast）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", help="建立/更新索引")
    p.add_argument("--changed", action="store_true", help="只重新分析变化的文件（增量）")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=lambda a: (build(a.changed, a.quiet), 0)[1])

    p = sub.add_parser("check", help="校验索引是否与代码一致（过期退出码 1）")
    p.set_defaults(func=lambda a: check())

    p = sub.add_parser("report", help="生成 docs/代码索引.md")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("stats", help="索引规模概览")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("files", help="文件索引")
    p.add_argument("--area", choices=["product", "tooling", "test", "data", "doc", "prompt", "root"])
    p.add_argument("--grep")
    p.set_defaults(func=cmd_files)

    p = sub.add_parser("find", help="按名字找定义")
    p.add_argument("name")
    p.add_argument("--kind", choices=["function", "class", "method"])
    p.set_defaults(func=cmd_find)

    p = sub.add_parser("refs", help="看某个名字被哪些文件引用")
    p.add_argument("name")
    p.set_defaults(func=cmd_refs)

    p = sub.add_parser("callers", help="看某个函数被谁调用")
    p.add_argument("name")
    p.set_defaults(func=cmd_callers)

    p = sub.add_parser("deps", help="模块依赖")
    p.add_argument("file", nargs="?")
    p.add_argument("--reverse", action="store_true", help="反向：谁依赖了这个文件")
    p.set_defaults(func=cmd_deps)

    p = sub.add_parser("routes", help="命令路由索引")
    p.set_defaults(func=cmd_routes)

    p = sub.add_parser("data", help="数据实体索引")
    p.add_argument("name", nargs="?")
    p.set_defaults(func=cmd_data)

    p = sub.add_parser("tests", help="测试索引")
    p.add_argument("file", nargs="?")
    p.set_defaults(func=cmd_tests)

    p = sub.add_parser("config", help="环境变量、常量与外部依赖")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("unresolved", help="未能静态解析的项")
    p.set_defaults(func=cmd_unresolved)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
