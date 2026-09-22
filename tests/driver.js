/* ---------------- 测试驱动 ---------------- */
const results = [];
function ok(name, cond, extra) {
  results.push({ name, pass: !!cond, extra });
  console.log((cond ? "  PASS  " : "  FAIL  ") + name + (extra !== undefined ? "   [" + extra + "]" : ""));
}
function flush(n = 6) { let p = Promise.resolve(); for (let i = 0; i < n; i++) p = p.then(() => new Promise(r => setTimeout(r, 0))); return p; }

const kd = winListeners["keydown"] || [], ku = winListeners["keyup"] || [];
const press = c => kd.forEach(f => f({ code: c, preventDefault() {} }));
const release = c => ku.forEach(f => f({ code: c }));
const tap = c => { press(c); release(c); };
let vt = 0;
function step(frames, ms = 16.7) {
  for (let i = 0; i < frames; i++) {
    const cbs = rafQueue.splice(0, rafQueue.length);
    vt += ms;
    for (const cb of cbs) cb(vt);
  }
}
const runCalls = () => fetchCalls.filter(c => c.url === "/api/run");

(async () => {
  console.log("\n=== 1. 启动 / 菜单 ===");
  step(3);
  ok("初始状态为菜单", state === State.MENU, "state=" + state);
  setPlayerName("测试代号"); loadProfile();
  await flush();
  ok("改代号后重新拉取档案", profileCache !== null, profileCache && profileCache.name);

  const s0 = menuSel;
  tap("ArrowDown"); ok("↓ 切换到下一项", menuSel === 1, "menuSel=" + menuSel);
  tap("ArrowUp"); ok("↑ 切回上一项", menuSel === 0, "menuSel=" + menuSel);
  tap("ArrowUp"); ok("↑ 在首项回绕到末项", menuSel === menuButtons.length - 1, "menuSel=" + menuSel);
  menuSel = 0;

  console.log("\n=== 2. 开始双人游戏 ===");
  tap("Enter"); step(2);
  ok("进入游戏", state === State.PLAYING, "state=" + state);
  ok("双人模式", playerCount === 2 && activePlayers().length === 2);
  ok("本局遥测已初始化", runStats !== null && runStats.submitted === false);
  ok("初始背包含手枪", runStats.weapons.has("pistol"));

  console.log("\n=== 3. 20 秒实战（无异常） ===");
  press("KeyD"); press("KeyJ"); press("Digit1");
  let grenCount = 0;
  for (let i = 0; i < 1200; i++) {
    // 保证本阶段不会提前阵亡，让流程走到第 6 节再统一结算
    for (const p of players) { p.lives = 3; if (p.hp < 45) p.hp = p.maxHp; }
    if (i % 200 === 0) { tap("KeyK"); grenCount++; }        // 1P 手雷
    if (i % 150 === 0) { tap("KeyW"); }                      // 跳
    if (i % 260 === 0) { tap("Digit2"); grenCount++; }       // 2P 手雷
    if (i % 400 === 0) { tap("KeyQ"); tap("Digit3"); }       // 换枪
    step(1);
  }
  release("KeyD"); release("KeyJ"); release("Digit1");
  ok("有击杀", kills > 0, "kills=" + kills);
  ok("有得分", score > 0, "score=" + score);
  ok("僵尸类型已被记录", Object.keys(runStats.zombieKills).length > 0, JSON.stringify(runStats.zombieKills));
  ok("武器击杀已被记录", Object.keys(runStats.weaponKills).length > 0, JSON.stringify(runStats.weaponKills));
  ok("地图内未逃逸", players.every(p => p.x >= 0 && p.x <= levelWidth));

  console.log("\n=== 4. 手雷弹跳（原 bug：碰地即炸） ===");
  // 4a. 空地(x=200, 该处无平台) → 应落到地面并弹起
  enemies.length = 0; grenades.length = 0;
  grenades.push({ x: 200, y: 400, vx: 0, vy: 0, fuse: 1.6, rot: 0, owner: players[0] });
  let bounced = false;
  for (let i = 0; i < 88; i++) {
    updateGrenades(1 / 60);
    const g = grenades[0];
    if (!g) break;
    if (g.vy < 0 && g.y > GROUND_Y - 40) bounced = true;
  }
  ok("1.47 秒时手雷仍在（引信未到）", grenades.length === 1, "len=" + grenades.length);
  ok("手雷停在地面上而非穿地/悬空",
    grenades[0] && Math.abs(grenades[0].y - (GROUND_Y - 7)) < 1.5, grenades[0] && grenades[0].y.toFixed(1));
  ok("手雷从地面弹起过", bounced);
  for (let i = 0; i < 14; i++) updateGrenades(1 / 60);
  ok("引信到点后爆炸消失", grenades.length === 0);

  // 4b. 平台上方(x=600 起有平台 y=490) → 应停在平台上并可横向滚动
  grenades.length = 0;
  grenades.push({ x: 600, y: 400, vx: 220, vy: 0, fuse: 1.6, rot: 0, owner: players[0] });
  for (let i = 0; i < 88; i++) { updateGrenades(1 / 60); if (!grenades[0]) break; }
  ok("手雷停在平台顶面 (490-7=483)",
    grenades[0] && Math.abs(grenades[0].y - 483) < 1.5, grenades[0] && grenades[0].y.toFixed(1));
  ok("落地后横向滚动并被摩擦减速", grenades[0] && grenades[0].x > 620 && grenades[0].x < 950,
    grenades[0] && grenades[0].x.toFixed(1));
  for (let i = 0; i < 14; i++) updateGrenades(1 / 60);
  ok("引信到点后爆炸消失", grenades.length === 0);
  grenades.length = 0;

  console.log("\n=== 5. 存档心跳 ===");
  fetchCalls.length = 0;
  heartbeat(true);
  await flush();
  ok("心跳已发送", fetchCalls.some(c => c.url === "/api/heartbeat"));

  console.log("\n=== 6. 阵亡结算 / 提交战绩 ===");
  await flush();
  fetchCalls.length = 0;
  for (const p of players) p.lives = 0;
  for (let i = 0; i < 8 && state === State.PLAYING; i++) {
    for (const p of players) { if (!p.perma) { p.invuln = 0; p.hp = 1; damagePlayer(p, 999, 1); } }
  }
  ok("全员阵亡进入结算", state === State.OVER, "state=" + state);
  await flush(10);
  ok("已向 /api/run 提交", runCalls().length === 1, "n=" + runCalls().length);
  ok("提交结果已回收", lastSubmit && lastSubmit.state === "done", lastSubmit && lastSubmit.state);
  ok("排名已显示", lastSubmit && lastSubmit.rank === 3, lastSubmit && lastSubmit.rank);
  ok("个人最佳标记", lastSubmit && lastSubmit.personal_best === true);
  ok("新成就已回收", lastSubmit && lastSubmit.new_achievements.length === 2);
  ok("档案已刷新", profileCache && profileCache.best_score === 9000);

  const pl = runCalls()[0].body;
  ok("载荷: 代号", pl.name === playerName, pl.name);
  ok("载荷: 得分一致", pl.score === score, pl.score + " vs " + score);
  ok("载荷: 击杀一致", pl.kills === kills, pl.kills + " vs " + kills);
  ok("载荷: 存活时长为正", pl.duration > 0, pl.duration.toFixed(1) + "s");
  ok("载荷: 双人模式", pl.player_count === 2);
  ok("载荷: 武器列表含手枪", pl.weapons.some(w => w.id === "pistol" && w.level >= 1),
    JSON.stringify(pl.weapons.map(w => w.id + ":L" + w.level + "/K" + w.kills)));
  ok("载荷: 最高武器等级合理", pl.max_weapon_level >= 1 && pl.max_weapon_level <= 15, pl.max_weapon_level);
  ok("载荷: 僵尸分布非空", Object.keys(pl.zombies).length > 0, JSON.stringify(pl.zombies));
  ok("载荷: 手雷击杀已统计", pl.grenade_kills >= 0, pl.grenade_kills);
  ok("载荷: 首伤时间已记录", pl.first_damage_at === null || pl.first_damage_at >= 0, pl.first_damage_at);
  ok("重复结算不会重复提交", (submitRun(), runCalls().length === 1));
  step(3);

  console.log("\n=== 7. 结算界面按键 ===");
  tap("Escape"); step(2);
  ok("Esc 回主菜单", state === State.MENU, "state=" + state);

  console.log("\n=== 8. 排行榜 ===");
  tap("KeyL"); step(2);
  ok("L 打开排行榜", state === State.LB, "state=" + state);
  await flush();
  ok("排行榜数据已载入", Array.isArray(lbData) && lbData.length === 2, lbData && lbData.length);
  ok("高亮自己的记录", lbData.some(e => e.name === playerName));
  tap("ArrowRight"); await flush();
  ok("→ 切换排序为击杀", lbSort === "kills", lbSort);
  tap("ArrowLeft"); await flush();
  ok("← 切回得分", lbSort === "score", lbSort);
  step(2);
  tap("Escape"); step(2);
  ok("Esc 退出排行榜回菜单", state === State.MENU, "state=" + state);

  console.log("\n=== 9. 成就墙 ===");
  tap("KeyC"); step(2);
  ok("C 打开成就墙", state === State.ACH, "state=" + state);
  await flush();
  ok("成就数据已载入", achData && achData.achievements.length === 3, achData && achData.achievements.length);
  ok("已解锁项标记正确", achData.achievements.filter(a => a.unlocked).length === 1);
  tap("Escape"); step(2);
  ok("Esc 退出成就墙", state === State.MENU, "state=" + state);

  console.log("\n=== 10. 静音 / 全屏 / 失焦暂停 ===");
  const m0 = muted;
  tap("KeyM");
  ok("M 切换静音", muted === !m0, "muted=" + muted);
  ok("静音状态已持久化", localStorage.getItem("zs_muted") === (muted ? "1" : "0"));
  tap("KeyM");
  ok("M 可切回", muted === m0);
  tap("KeyF");
  ok("F 触发全屏调用未抛错", true);

  tap("Enter"); step(2);
  ok("重新开局", state === State.PLAYING);
  (winListeners["blur"] || []).forEach(f => f());
  ok("失焦自动暂停", state === State.PAUSED, "state=" + state);
  tap("KeyP"); step(2);
  ok("P 恢复游戏", state === State.PLAYING, "state=" + state);
  document.hidden = true;
  (docListeners["visibilitychange"] || []).forEach(f => f());
  ok("切标签页自动暂停", state === State.PAUSED, "state=" + state);
  document.hidden = false;
  step(2);

  const fail = results.filter(r => !r.pass);
  console.log("\n" + "=".repeat(52));
  console.log(`  通过 ${results.length - fail.length} / ${results.length}`);
  if (fail.length) { console.log("  失败项:"); fail.forEach(f => console.log("    - " + f.name + (f.extra !== undefined ? "  [" + f.extra + "]" : ""))); }
  console.log("=".repeat(52) + "\n");
  process.exit(fail.length ? 1 : 0);
})().catch(e => { console.error("\n驱动异常:", e); process.exit(2); });
