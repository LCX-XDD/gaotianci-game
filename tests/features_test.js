/* ---------------- 新功能 / 回归测试 ---------------- */
/* 覆盖：激光枪卡死回归、冲刺、连击、波次强化、主循环健壮性 */

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
function clearField() {
  enemies.length = 0; bullets.length = 0; beams.length = 0; grenades.length = 0;
  particles.length = 0; pickups.length = 0; floatTexts.length = 0;
  spawnedThisWave = 0; waveBudget = 1; spawnTimer = 999;
  for (const p of players) { p.hp = p.maxHp; p.invuln = 0; p.dead = false; p.perma = false; }
}
function frontEnemy(type, dx, extra) {
  const e = makeZombie(type, players[0].x + dx, -1);
  e.x = players[0].x + dx; e.y = GROUND_Y - e.h; e.vx = 0; e.speed = 0;   // 钉住不动，保证几何可复现
  Object.assign(e, extra || {});
  enemies.push(e);
  return e;
}
/* 把 1P 摆成"站在地面上、面朝右、不开火冷却"的确定状态 */
function armShooter(p, weapon, lv) {
  p.guns = ["pistol", weapon]; p.gunIdx = 1;
  p.wlv[weapon] = { lv, xp: 0 };
  p.x = 400; p.y = GROUND_Y - p.h; p.vx = 0; p.vy = 0;
  p.facing = 1; p._moveX = 0; p.shootCd = 0; p.invuln = 0; p.dead = false; p.perma = false;
}

(async () => {
  step(3);
  setPlayerName("测试代号");
  tap("Enter"); step(2);

  /* ================= 1. 激光枪卡死回归（原 bug） ================= */
  console.log("\n=== 1. 激光枪（原 bug：一捡到就卡死） ===");
  {
    const p = players[0];
    clearField();
    armShooter(p, "laser", 1);

    // 直接调用：原代码在 `const beams = m.beams` 遮蔽全局数组后 beams.push 抛 TypeError
    let threw = null;
    try { p.shootCd = 0; playerShoot(p); } catch (err) { threw = err; }
    ok("激光开火不抛异常", threw === null, threw && threw.message);
    ok("光束进入渲染数组 beams", beams.length === 1, "beams=" + beams.length);

    // 通过真实主循环驱动：异常会让 rAF 断链、画面永久冻结
    clearField();
    frameError = null;
    armShooter(p, "laser", 1);                 // p.x=400, 站地, 朝右
    const target = frontEnemy("walker", 250);
    target.hp = target.maxHp = 1e6;
    const hp0 = target.hp;
    press("KeyJ");
    let framesWithoutRaf = 0;
    for (let i = 0; i < 40; i++) { step(1); if (!rafQueue.length) framesWithoutRaf++; }
    release("KeyJ");
    ok("激光连射后主循环仍在调度（未冻结）", framesWithoutRaf === 0, "断链帧=" + framesWithoutRaf);
    ok("整段激光连射无帧异常", frameError === null, frameError && frameError.message);
    ok("激光确实打出伤害", target.hp < hp0, "掉血=" + (hp0 - target.hp));
    ok("激光不消耗子弹", bullets.length === 0, "bullets=" + bullets.length);

    // 高等级多光束：同一目标应被多条光束叠加命中
    clearField();
    armShooter(p, "laser", 15);
    const mods = weaponMods(p, "laser");
    ok("Lv15 激光为四光束", mods.beams === 4, "beams=" + mods.beams);
    const boss = frontEnemy("boss", 250);
    boss.hp = boss.maxHp = 1e6;
    p.shootCd = 0; playerShoot(p);
    const drop = 1e6 - boss.hp;
    ok("四光束对同一目标叠加生效", drop > mods.dmg * 3.5 && drop <= mods.dmg * 4.5,
      "掉血=" + drop.toFixed(1) + " 单束=" + mods.dmg.toFixed(1));
    ok("光束数组未与光束数量变量混淆", beams.length === 4, "beams=" + beams.length);
  }

  /* ================= 2. 冲刺 ================= */
  console.log("\n=== 2. 冲刺（Shift，带无敌帧） ===");
  {
    const p = players[0];
    clearField();
    p.buffs = {}; p.dashCd = 0; p.dashT = 0; p.airDash = true;
    p.x = 400; p.y = GROUND_Y - p.h; p.vx = 0; p.vy = 0;
    p.facing = 1; p._dashHeld = false;

    // 对照组：5 帧普通走位能走多远
    press("KeyD"); step(5); release("KeyD"); step(1);
    const walkDx = p.x - 400;

    // 冲刺：同样 5 帧
    p.dashCd = 0; p.dashT = 0; p.x = 400; p.vx = 0; p.vy = 0; p._dashHeld = false;
    press("ShiftLeft"); step(1);
    ok("Shift 触发冲刺", p.dashT > 0, "dashT=" + p.dashT.toFixed(3));
    ok("冲刺期间速度远高于常态", p.vx > 1000, "vx=" + Math.round(p.vx) + " 走位=" + 430);
    ok("冲刺自带无敌帧", p.invuln > 0, "invuln=" + p.invuln.toFixed(3));
    const x0 = p.x;
    step(5);                                   // 冲刺全长 0.16s ≈ 10 帧
    const dashDx = p.x - x0;
    ok("冲刺位移显著快于走位", dashDx > walkDx * 2,
      "冲刺=" + Math.round(dashDx) + "px 走位=" + Math.round(walkDx) + "px");
    release("ShiftLeft"); step(8);
    ok("冲刺结束后恢复普通速度", p.dashT <= 0 && p.vx === 0, "dashT=" + p.dashT.toFixed(3));

    // 冷却：刚用完立刻再按无效
    p.dashCd = 0.5; p.dashT = 0;
    press("ShiftLeft"); step(1);
    ok("冷却中无法再次冲刺", p.dashT <= 0, "dashCd=" + p.dashCd.toFixed(2));
    release("ShiftLeft"); step(1);

    p.dashCd = 0;
    press("ShiftLeft"); step(1);
    ok("冷却结束后可再次冲刺", p.dashT > 0);
    release("ShiftLeft"); step(1);

    // 空中冲刺只允许一次
    clearField();
    p.dashT = 0; p.dashCd = 0; p.airDash = true; p.onGround = false;
    p.y = 400; p.vy = 0; p._dashHeld = false;
    press("ShiftLeft"); step(1);
    ok("空中可冲刺一次", p.dashT > 0 && p.airDash === false,
      "dashT=" + p.dashT.toFixed(3) + " airDash=" + p.airDash);
    release("ShiftLeft"); step(1);
    p.dashT = 0; p.dashCd = 0; p.vy = 0; p.y = 400;
    press("ShiftLeft"); step(1);
    ok("空中第二次冲刺被拒", p.dashT <= 0, "dashT=" + p.dashT.toFixed(3));
    release("ShiftLeft");

    // 落地恢复空中冲刺额度
    p.dashT = 0; p.dashCd = 0; p.airDash = false; p.vy = 400; p.y = GROUND_Y - p.h;
    step(2);
    ok("落地后空中冲刺额度恢复", p.airDash === true && p.onGround === true,
      "airDash=" + p.airDash + " onGround=" + p.onGround);
  }

  /* ================= 3. 连击 ================= */
  console.log("\n=== 3. 连击倍率 ===");
  {
    const p = players[0];
    clearField();
    p.buffs = {}; p.invuln = 0; p.maxHp = 100; p.hp = 100;
    score = 0; kills = 0; combo = 0; comboT = 0; comboBest = 0;
    const kx = () => { const e = makeZombie("walker", 500, -1); e.x = 500; enemies.push(e); killEnemy(e, p, "pistol"); };

    for (let i = 0; i < 5; i++) kx();
    ok("前 5 杀倍率仍为 ×1", combo === 5 && comboMul(combo) === 1, "combo=" + combo);
    ok("前 5 杀得分为基础分 40", score === 40, "score=" + score);

    kx();
    ok("第 6 杀触发 ×1.5", combo === 6 && comboMul(combo) === 1.5, "×" + comboMul(combo));
    ok("第 6 杀分数按倍率结算 (40+12)", score === 52, "score=" + score);
    ok("最高连击被记录", comboBest === 6, "best=" + comboBest);

    for (let i = 0; i < 6; i++) kx();
    ok("满 12 连进入 ×2 档", comboMul(combo) === 2, "combo=" + combo + " ×" + comboMul(combo));

    // 受伤中断
    p.invuln = 0;
    damagePlayer(p, 5, 1);
    ok("受伤清空连击", combo === 0 && comboT === 0, "combo=" + combo);

    // 超时中断
    enemies.length = 0; spawnedThisWave = 0; waveBudget = 1; spawnTimer = 999;
    combo = 20; comboT = 0.05;
    update(0.1);
    ok("连击窗口耗尽后归零", combo === 0, "combo=" + combo);
  }

  /* ================= 4. 波次强化 ================= */
  console.log("\n=== 4. 波次三选一强化 ===");
  {
    const p = players[0];
    clearField();
    for (const q of players) { q.buffs = {}; q.maxHp = 100; q.hp = 100; }
    upgradeOffer = null; awaitingWave = false;
    wave = 1; spawnedThisWave = 5; waveBudget = 5; enemies.length = 0;

    update(0.016);
    ok("清空一波后弹出强化", Array.isArray(upgradeOffer) && upgradeOffer.length === 3,
      JSON.stringify(upgradeOffer));
    ok("强化卡来自强化表且不重复",
      upgradeOffer.every(id => BUFF_BY_ID[id]) && new Set(upgradeOffer).size === 3);

    const frozenX = p.x, frozenT = runTime;
    update(1.0);
    ok("强化选择时世界静止", p.x === frozenX, "x=" + p.x);
    ok("强化倒计时在走", upgradeT < UPGRADE_TIME, "upgradeT=" + upgradeT.toFixed(1));

    const picked = upgradeOffer[0];
    pickUpgrade(0);
    ok("选择后强化对双方生效",
      players.every(q => buffLv(q, picked) === 1), picked);
    ok("选择后关闭界面并进入下一波", upgradeOffer === null && wave === 2, "wave=" + wave);

    // 各强化实际效果
    for (const q of players) { q.buffs = {}; q.maxHp = 100; q.hp = 100; }
    const base = weaponMods(p, "pistol");
    applyBuff(p, "dmg");
    ok("火力强化：伤害 +15%",
      Math.abs(weaponMods(p, "pistol").dmg / base.dmg - 1.15) < 1e-9,
      (weaponMods(p, "pistol").dmg / base.dmg).toFixed(4));
    applyBuff(p, "rate");
    ok("扳机改装：射击间隔变短", weaponMods(p, "pistol").rate < base.rate,
      weaponMods(p, "pistol").rate.toFixed(4));
    applyBuff(p, "crit");
    ok("致命一击：暴击率 +8%", Math.abs(weaponMods(p, "pistol").crit - 0.08) < 1e-9);
    applyBuff(p, "hp");
    ok("防弹背心：上限 +20 且回满", p.maxHp === 120 && p.hp === 120, p.maxHp + "/" + p.hp);
    applyBuff(p, "speed");
    ok("轻装战靴：移速提升", speedMul(p) > 1.09, speedMul(p).toFixed(3));
    applyBuff(p, "dash");
    ok("瞬身训练：冲刺 CD 缩短", dashCdOf(p) < DASH_CD, dashCdOf(p).toFixed(3));
    applyBuff(p, "combo");
    ok("杀戮节拍：连击窗口延长", comboWinOf(p) > COMBO_WINDOW, comboWinOf(p).toFixed(2));
    applyBuff(p, "nade");
    ok("弹药补给：手雷 CD 缩短", nadeCdOf(p) < 6, nadeCdOf(p).toFixed(3));
    applyBuff(p, "vamp");
    p.hp = 50; p.invuln = 0;
    const ve = makeZombie("walker", 500, -1); ve.x = 500; enemies.push(ve);
    killEnemy(ve, p, "pistol");
    ok("嗜血：击杀回血 +2", p.hp === 52, "hp=" + p.hp);

    // 超时自动选择，绝不能让流程卡在强化界面
    clearField();
    upgradeOffer = null; awaitingWave = false;
    wave = 2; spawnedThisWave = 4; waveBudget = 4; enemies.length = 0;
    update(0.016);
    ok("再次弹出强化", !!upgradeOffer);
    update(UPGRADE_TIME + 0.2);
    ok("超时自动随机选择并继续", upgradeOffer === null && wave === 3, "wave=" + wave);
  }

  /* ================= 5. 主循环健壮性 ================= */
  console.log("\n=== 5. 主循环异常兜底 ===");
  {
    clearField();
    frameError = null;
    const boom = { get x() { throw new Error("模拟单帧崩溃"); } };
    // 制造一次真实的帧内异常：临时塞一只畸形的僵尸
    const bad = makeZombie("walker", players[0].x + 100, -1);
    Object.defineProperty(bad, "w", { get() { throw new Error("模拟单帧崩溃"); } });
    enemies.push(bad);
    const before = runTime;
    step(4);
    ok("帧内异常被捕获而不抛出", frameError !== null, frameError && frameError.message);
    ok("异常后主循环继续调度（不再永久冻结）", rafQueue.length > 0, "raf=" + rafQueue.length);
    ok("异常后时间仍在推进", runTime > before, "Δ=" + (runTime - before).toFixed(3));
    enemies.length = 0; frameError = null;
    step(3);
    ok("移除问题对象后恢复正常", frameError === null && rafQueue.length > 0);
    void boom;
  }

  const fail = results.filter(r => !r.pass);
  console.log("\n" + "=".repeat(52));
  console.log(`  通过 ${results.length - fail.length} / ${results.length}`);
  if (fail.length) { console.log("  失败项:"); fail.forEach(f => console.log("    - " + f.name + (f.extra !== undefined ? "  [" + f.extra + "]" : ""))); }
  console.log("=".repeat(52) + "\n");
  process.exit(fail.length ? 1 : 0);
})().catch(e => { console.error("\n驱动异常:", e); process.exit(2); });
