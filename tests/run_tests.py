#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键跑全部测试。

    python tests/run_tests.py

四组：
  1. 游戏逻辑 —— Node 无头打桩 DOM/Canvas/fetch，真实驱动游戏循环
  2. 统计面板渲染 —— 校验 SVG 生成、无 NaN、表格视图切换
  3. 真实浏览器布局审计 —— Playwright + Chrome，查溢出/裁切/轴带/像素确非空白
  4. 服务端 HTTP —— 静态资源、路径穿越、API、信任边界、协议

第 3 组需要 playwright 与 Chrome；缺失时跳过而不是失败。
"""

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
TESTS = os.path.join(ROOT, "tests")
BUILD = os.path.join(TESTS, ".build")
PY = sys.executable


def log(msg):
    print(msg, flush=True)


TEST_DB = os.path.join(BUILD, "test.db")
# 本进程也指向测试库，否则 import server 时读到的是真实战绩库
os.environ["ZS_DB"] = TEST_DB
CHILD_ENV = dict(os.environ, PYTHONIOENCODING="utf-8", ZS_DB=TEST_DB)


def reset_fixture_db():
    """测试跑在独立库上：既保证数据量稳定，也不碰用户真实战绩。"""
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(TEST_DB + suffix)
        except FileNotFoundError:
            pass
    r = subprocess.run([PY, os.path.join(TESTS, "seed_demo.py")], cwd=ROOT,
                       env=CHILD_ENV, text=True, encoding="utf-8",
                       errors="replace", capture_output=True)
    return r.returncode == 0


def run(cmd, **kw):
    kw.setdefault("env", CHILD_ENV)
    return subprocess.run(cmd, cwd=ROOT, text=True, encoding="utf-8",
                          errors="replace", **kw)


def which_node():
    return shutil.which("node")


def build_node_bundle():
    """把 game 脚本 + 打桩前导 + 测试驱动拼成一个可执行文件。"""
    html = open(os.path.join(ROOT, "static", "index.html"), encoding="utf-8").read()
    game = re.search(r"<script>(.*)</script>", html, re.S).group(1)
    pre = open(os.path.join(TESTS, "prelude.js"), encoding="utf-8").read()
    drv = open(os.path.join(TESTS, "driver.js"), encoding="utf-8").read()
    out = os.path.join(BUILD, "game_test.js")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(pre + '\n;(function(){ "use strict";\n' + game + "\n" + drv + "\n})();\n")
    return out


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    os.makedirs(BUILD, exist_ok=True)
    results = []

    log("\n########## 1/4  游戏逻辑（Node 无头） ##########")
    if not which_node():
        log("  跳过：未找到 node")
        results.append(("游戏逻辑", None))
    else:
        r = run([which_node(), build_node_bundle()], capture_output=True)
        print(r.stdout, end="")
        if r.stderr.strip():
            print(r.stderr, file=sys.stderr)
        results.append(("游戏逻辑", r.returncode == 0))

    log("########## 2/4  统计面板渲染 ##########")
    if not which_node():
        log("  跳过：未找到 node")
        results.append(("统计面板渲染", None))
    else:
        reset_fixture_db()
        sys.path.insert(0, ROOT)
        import server  # noqa: E402
        with open(os.path.join(BUILD, "stats_data.json"), "w", encoding="utf-8") as fh:
            json.dump(server.global_stats(), fh, ensure_ascii=False)
        server.close_db()          # 放开库文件，下一步才能重建
        r = run([which_node(), os.path.join(TESTS, "stats_test.js")], capture_output=True)
        print(r.stdout, end="")
        if r.stderr.strip():
            print(r.stderr, file=sys.stderr)
        results.append(("统计面板渲染", r.returncode == 0))

    log("########## 3/4  真实浏览器布局审计 ##########")
    try:
        import playwright  # noqa: F401
        has_pw = True
    except ImportError:
        has_pw = False
    if not has_pw:
        log("  跳过：未安装 playwright（pip install playwright）")
        results.append(("浏览器布局审计", None))
    else:
        reset_fixture_db()
        port = free_port()
        env = dict(CHILD_ENV)
        srv = subprocess.Popen([PY, os.path.join(ROOT, "server.py"), "--port", str(port)],
                               cwd=ROOT, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try:
                    with socket.create_connection(("127.0.0.1", port), 0.2):
                        break
                except OSError:
                    time.sleep(0.1)
            env["ZS_BASE"] = f"http://127.0.0.1:{port}"
            r = subprocess.run([PY, os.path.join(TESTS, "audit.py")], cwd=ROOT, env=env,
                               text=True, encoding="utf-8", errors="replace", capture_output=True)
            print(r.stdout, end="")
            if r.stderr.strip():
                print(r.stderr, file=sys.stderr)
            results.append(("浏览器布局审计", r.returncode == 0))
        finally:
            srv.terminate()
            try:
                srv.wait(timeout=5)
            except subprocess.TimeoutExpired:
                srv.kill()

    log("########## 4/4  服务端 HTTP ##########")
    reset_fixture_db()
    port = free_port()
    srv = subprocess.Popen([PY, os.path.join(ROOT, "server.py"), "--port", str(port)],
                           cwd=ROOT, env=CHILD_ENV,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", port), 0.2):
                    break
            except OSError:
                time.sleep(0.1)
        r = subprocess.run([PY, os.path.join(TESTS, "http_test.py"), str(port)],
                           cwd=ROOT, text=True, encoding="utf-8", errors="replace",
                           capture_output=True, env=CHILD_ENV)
        print(r.stdout, end="")
        if r.stderr.strip():
            print(r.stderr, file=sys.stderr)
        results.append(("服务端 HTTP", r.returncode == 0))
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=5)
        except subprocess.TimeoutExpired:
            srv.kill()

    log("\n" + "=" * 56)
    bad = 0
    for name, okv in results:
        tag = "跳过" if okv is None else ("通过" if okv else "失败")
        if okv is False:
            bad += 1
        log(f"  {tag}  {name}")
    log("=" * 56)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
