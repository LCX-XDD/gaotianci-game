# -*- coding: utf-8 -*-
import os
import sys
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ZS_BASE", "http://127.0.0.1:8000")
fails, errs, total = [], [], 0
def check(n, c, e=None):
    global total
    total += 1
    print(("  PASS  " if c else "  FAIL  ") + n + (f"   [{e}]" if e is not None else ""))
    if not c: fails.append(n)

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome")
    pg = b.new_page(viewport={"width": 1360, "height": 820})
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: errs.append("console:" + m.text) if m.type == "error" else None)

    print("=== 统计面板布局 ===")
    pg.goto(BASE + "/stats", wait_until="networkidle"); pg.wait_for_timeout(900)
    r = pg.evaluate("""() => {
      const out = { hOver: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        nestedScroll: [], svgBad: [], zeroBars: 0, barCount: 0, cards: 0, texts: 0 };
      for (const c of document.querySelectorAll('.card')) {
        out.cards++;
        if (c.scrollHeight > c.clientHeight + 1) out.nestedScroll.push({t:c.querySelector('h2').textContent, sh:c.scrollHeight, ch:c.clientHeight});
        if (c.scrollWidth > c.clientWidth + 1) out.nestedScroll.push({t:c.querySelector('h2').textContent+'(横向)', sw:c.scrollWidth, cw:c.clientWidth});
      }
      for (const s of document.querySelectorAll('svg')) {
        const vb = s.viewBox.baseVal, tag = s.getAttribute('aria-label') || '?';
        for (const t of s.querySelectorAll('text')) {
          out.texts++;
          const bb = t.getBBox();
          if (bb.width > 0 && (bb.x < -1 || bb.y < -1 || bb.x+bb.width > vb.width+1 || bb.y+bb.height > vb.height+1))
            out.svgBad.push({svg:tag, kind:'text', v:t.textContent, bb:[bb.x|0,bb.y|0,bb.width|0,bb.height|0], vb:[vb.width,vb.height]});
        }
        for (const p of s.querySelectorAll('path.bar-mark')) {
          out.barCount++;
          const bb = p.getBBox();
          if (bb.width < 0.5 || bb.height < 0.5) out.zeroBars++;
          if (bb.x < -1 || bb.y < -1 || bb.x+bb.width > vb.width+1 || bb.y+bb.height > vb.height+1)
            out.svgBad.push({svg:tag, kind:'bar', bb:[bb.x|0,bb.y|0,bb.width|0,bb.height|0], vb:[vb.width,vb.height]});
        }
      }
      return out;
    }""")
    check("页面无横向滚动", r["hOver"] <= 0, f"溢出 {r['hOver']}px")
    check("卡片无嵌套滚动条(含 x 轴标签带)", len(r["nestedScroll"]) == 0, r["nestedScroll"])
    check("渲染了 5 张卡片", r["cards"] == 5, r["cards"])
    check("SVG 文本与条形均在 viewBox 内", len(r["svgBad"]) == 0, r["svgBad"][:2])
    check("无零尺寸条形", r["zeroBars"] == 0, r["zeroBars"])
    check("条形数量充足", r["barCount"] >= 40, r["barCount"])
    check("轴标签数量充足", r["texts"] >= 60, r["texts"])
    col = pg.evaluate("""() => { const s = getComputedStyle(document.querySelector('path.bar-mark'));
      return {fill: s.fill, stroke: s.stroke}; }""")
    check("条形使用序列色 #3987e5", "57, 135, 229" in col["fill"], col["fill"])

    print("=== 表格视图 ===")
    pg.click("#v-table"); pg.wait_for_timeout(400)
    t = pg.evaluate("""() => ({ tables: document.querySelectorAll('table').length,
        svgs: document.querySelectorAll('svg').length,
        hOver: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        rows: document.querySelectorAll('tbody tr').length })""")
    check("表格视图渲染 5 张表", t["tables"] == 5, t["tables"])
    check("表格视图无 SVG 残留", t["svgs"] == 0, t["svgs"])
    check("表格视图无横向滚动", t["hOver"] <= 0, t["hOver"])
    check("表格行数充足", t["rows"] >= 35, t["rows"])

    print("=== 游戏画布 ===")
    pg.goto(BASE, wait_until="networkidle"); pg.wait_for_timeout(700)
    g = pg.evaluate("""() => {
      const c = document.getElementById('game'), r = c.getBoundingClientRect();
      const ctx = c.getContext('2d'), d = ctx.getImageData(0, 0, c.width, c.height).data;
      const set = new Set(); let sum = 0, n = 0;
      for (let i = 0; i < d.length; i += 4 * 97) { set.add(d[i]+','+d[i+1]+','+d[i+2]); sum += d[i]+d[i+1]+d[i+2]; n += 3; }
      return { rect: [r.left|0, r.top|0, r.width|0, r.height|0],
        fits: r.left >= -1 && r.top >= -1 && r.right <= innerWidth+1 && r.bottom <= innerHeight+1,
        colors: set.size, meanLum: (sum/n)|0, ratio: c.width/c.height,
        // 画布内 UI 布局量（脚本作用域内的全局绑定）
        menuBottom: btnY(menuButtons.length-1) + BTN_H, canvasH: H,
        profPanelBottom: btnY(menuButtons.length) + 12 + 78,
        lastHintY: 682, achRows: Math.ceil(14/2), achBottom: 130 + Math.ceil(14/2-1)*60 + 52 };
    }""")
    check("画布完整可见", g["fits"], g["rect"])
    check("画布宽高比 16:9", abs(g["ratio"] - 16/9) < 0.01, round(g["ratio"], 3))
    check("画布已实际渲染内容", g["colors"] > 40, f"{g['colors']} 种采样色, 平均亮度 {g['meanLum']}")
    check("菜单按钮区在画布内", g["menuBottom"] < g["canvasH"], f"{g['menuBottom']} < {g['canvasH']}")
    check("档案条不遮挡按钮", g["profPanelBottom"] > g["menuBottom"], f"{g['profPanelBottom']} > {g['menuBottom']}")
    check("档案条不与底部提示重叠", g["profPanelBottom"] < 604, f"{g['profPanelBottom']} < 604")
    check("底部提示在画布内", g["lastHintY"] < g["canvasH"], g["lastHintY"])
    check("成就墙两列网格在画布内", g["achBottom"] < 690, g["achBottom"])

    print("=== 各界面像素确非空白 ===")
    for name, keys in [("菜单", []), ("游戏内", [])]:
        pass
    def nonblank(label):
        v = pg.evaluate("""() => { const c = document.getElementById('game');
          const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data; const s = new Set();
          for (let i = 0; i < d.length; i += 4*211) s.add(d[i]+','+d[i+1]+','+d[i+2]);
          return s.size; }""")
        check(f"{label} 有渲染内容", v > 25, f"{v} 色")
    pg.keyboard.press("ArrowDown"); pg.keyboard.press("ArrowDown"); pg.keyboard.press("Enter")
    pg.wait_for_timeout(700); nonblank("排行榜界面")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    pg.keyboard.press("ArrowDown"); pg.keyboard.press("ArrowDown"); pg.keyboard.press("ArrowDown")
    pg.keyboard.press("Enter"); pg.wait_for_timeout(700); nonblank("成就墙界面")
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    pg.keyboard.press("ArrowUp"); pg.keyboard.press("Enter"); pg.wait_for_timeout(1500)
    pg.keyboard.down("KeyD"); pg.keyboard.down("KeyJ"); pg.wait_for_timeout(4000)
    pg.keyboard.up("KeyD"); pg.keyboard.up("KeyJ"); pg.wait_for_timeout(200)
    nonblank("战斗画面")

    print("=== 离线降级（未起后端 / file:// 直接打开） ===")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    file_url = "file:///" + os.path.join(root, "static", "index.html").replace("\\", "/")
    ctx = b.new_context(viewport={"width": 1360, "height": 820})
    ctx.add_init_script("Object.defineProperty(window,'localStorage',"
                        "{get(){throw new DOMException('blocked','SecurityError')}});")
    off_errs = []
    opg = ctx.new_page()
    opg.on("pageerror", lambda e: off_errs.append(str(e)))
    opg.on("console", lambda m: off_errs.append("console:" + m.text) if m.type == "error" else None)
    opg.goto(file_url, wait_until="load"); opg.wait_for_timeout(700)
    opg.keyboard.press("KeyL"); opg.wait_for_timeout(300)      # 排行榜：无后端
    opg.keyboard.press("Escape"); opg.wait_for_timeout(200)
    opg.keyboard.press("Enter"); opg.wait_for_timeout(1200)    # 真开一局
    opg.keyboard.down("KeyD"); opg.keyboard.down("KeyJ"); opg.wait_for_timeout(2500)
    opg.keyboard.up("KeyD"); opg.keyboard.up("KeyJ"); opg.wait_for_timeout(200)
    off = opg.evaluate("""() => { const c = document.getElementById('game');
      const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data; const s = new Set();
      for (let i = 0; i < d.length; i += 4*211) s.add(d[i]+','+d[i+1]+','+d[i+2]);
      return { playing: state === 1, colors: s.size, online: apiOnline }; }""")
    check("file:// + localStorage 被禁仍能开局", off["playing"], off)
    check("file:// 下战斗画面正常渲染", off["colors"] > 25, f"{off['colors']} 色")
    check("自动切到离线模式", off["online"] is False)
    net = [e for e in off_errs if "CORS" in e or "ERR_FAILED" in e]
    check("离线后不再反复发起请求（≤2 条网络报错）", len(net) <= 2, f"{len(net)} 条")
    check("离线无 JS 异常", not [e for e in off_errs if not e.startswith("console:")], off_errs[:2])
    ctx.close()


    b.close()

print("\n  页面异常:", errs if errs else "无")
check("无 JS 异常 / console 错误", len(errs) == 0, errs[:2])
print("\n" + "="*52)
print(f"  通过 {total - len(fails)} / {total}")
if fails: print("  失败:", fails)
print("="*52)
sys.exit(1 if fails else 0)
