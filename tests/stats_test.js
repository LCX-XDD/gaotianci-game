const fs = require("fs");
const data = JSON.parse(fs.readFileSync("tests/.build/stats_data.json", "utf8"));
const els = {};
function mkEl(id) {
  return els[id] = { id, innerHTML: "", textContent: "", hidden: false, _attrs: {}, _ls: [],
    setAttribute(k, v) { this._attrs[k] = v; }, getAttribute(k) { return this._attrs[k]; },
    addEventListener(ev, fn) { this._ls.push(fn); },
    click() { this._ls.forEach(f => f()); } };
}
globalThis.document = { getElementById: id => els[id] || mkEl(id) };
globalThis.window = globalThis;
globalThis.fetch = () => Promise.resolve({ json: () => Promise.resolve(data) });
globalThis.setInterval = () => 0;

const html = fs.readFileSync("static/stats.html", "utf8");
eval(html.match(/<script>([\s\S]*)<\/script>/)[1]);

let fail = 0, total = 0;
const check = (n, c, e) => { total++; console.log((c ? "  PASS  " : "  FAIL  ") + n + (e !== undefined ? "   ["+e+"]" : "")); if (!c) fail++; };
const G = k => els[k] ? els[k].innerHTML : "";

setTimeout(() => {
  const charts = ["kpis","c-daily","c-weapons","c-zombies","c-ach","c-players"];
  console.log("=== 图表视图 ===");
  for (const k of charts) check(k + " 已渲染", G(k).length > 50, G(k).length + " 字符");
  let all = charts.map(G).join("");
  check("无 NaN / undefined / Infinity", !/NaN|undefined|Infinity/.test(all), (all.match(/NaN|undefined|Infinity/g)||[]).slice(0,3).join(","));
  const paths = all.match(/d="M[^"]*"/g) || [];
  check("生成了条形路径", paths.length > 20, paths.length + " 条");
  check("路径数值全部合法", paths.every(p => /^d="M[-\d.,\sA-ZQZ]+"$/.test(p)));
  check("KPI 呈现总局数", G("kpis").includes(String(data.totals.runs)), data.totals.runs);
  check("KPI 呈现总击杀(千分位)", G("kpis").includes(data.totals.kills.toLocaleString("zh-CN")), data.totals.kills.toLocaleString("zh-CN"));
  check("KPI 无 NaN", !/NaN/.test(G("kpis")));
  check("每日趋势 13 天", (G("c-daily").match(/<title>/g)||[]).length === data.daily.length);
  check("武器图条数与数据一致", (G("c-weapons").match(/<title>/g)||[]).length === data.weapons.length, data.weapons.length);
  check("僵尸图条数与数据一致", (G("c-zombies").match(/<title>/g)||[]).length === data.zombies.length, data.zombies.length);
  check("成就条数与数据一致", (G("c-ach").match(/<title>/g)||[]).length === data.achievements.length, data.achievements.length);
  check("顶尖榜行数与数据一致", (G("c-players").match(/<tr>/g)||[]).length === data.top_players.length + 1, (G("c-players").match(/<tr>/g)||[]).length + " vs " + (data.top_players.length+1));
  check("有 SVG 无表格", /<svg/.test(G("c-weapons")) && !/<\/table>/.test(G("c-weapons")));
  check("峰值已直接标注", /text-anchor="middle">\d+</.test(G("c-daily")));
  check("工具提示用 <title> 而非唯一读数", /<title>/.test(G("c-weapons")));

  console.log("=== 表格视图（无障碍孪生体） ===");
  els["v-table"].click();
  check("切到表格后武器卡变表格", /<\/table>/.test(G("c-weapons")));
  check("表格含武器名", /手枪|冲锋枪|霰弹枪|步枪|火箭筒|激光枪/.test(G("c-weapons")));
  check("成就卡变表格且含难度", /<\/table>/.test(G("c-ach")) && /白金|黄金|白银|青铜/.test(G("c-ach")));
  check("表格视图无 SVG 残留", !/<svg/.test(G("c-weapons")));
  check("按钮 aria-pressed 已切换", els["v-table"].getAttribute("aria-pressed") === "true" && els["v-chart"].getAttribute("aria-pressed") === "false");

  els["v-chart"].click();
  check("切回图表视图", /<svg/.test(G("c-weapons")) && !/<\/table>/.test(G("c-weapons")));

  console.log("\n  通过 " + (18 - fail) + " / 18");
  process.exit(fail ? 1 : 0);
}, 60);
