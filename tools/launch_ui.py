# -*- coding: utf-8 -*-
"""一键启动本地只读界面：构建（必要时）→ 起服务 → 打开浏览器。

双击根目录的「启动个人成长档案.cmd」即可；也可以在命令行执行：

    python tools/launch_ui.py

默认读 data/growth.db，端口 8765；被占用时自动往后找空闲端口。
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.web import make_server  # noqa: E402


def free_port(start: int) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise SystemExit(f"从 {start} 起连续 20 个端口都被占用，请手动 --port 指定")


def ensure_dist() -> None:
    dist = ROOT / "web" / "dist" / "index.html"
    if dist.exists():
        return
    print("[启动] 第一次运行，需要构建前端（npm install + build）……")
    web = ROOT / "web"
    if not (web / "node_modules").exists():
        subprocess.run(["npm", "install", "--no-fund", "--no-audit"], cwd=web, check=True)
    subprocess.run(["npm", "run", "build"], cwd=web, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="启动个人成长档案本地界面")
    ap.add_argument("--db", default=str(ROOT / "data" / "growth.db"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    ensure_dist()
    port = free_port(args.port)
    server = make_server(args.db, port)
    thread = threading.Thread(target=server.serve_forever, name="web", daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/"
    print(f"[启动] 界面已就绪：{url}")
    print(f"[启动] 数据库：{args.db}")
    print("[启动] 关闭这个窗口或按 Ctrl+C 结束。")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[退出] 正在关闭……")
        server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
