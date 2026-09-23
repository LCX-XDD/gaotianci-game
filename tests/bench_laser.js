/* ---------------- 激光枪性能基准 ---------------- */
/* 目的：量化"捡到激光枪就卡"的性能开销来源。 */

const kd_ = winListeners["keydown"] || [], ku_ = winListeners["keyup"] || [];
const tap = c => { kd_.forEach(f => f({ code: c, preventDefault() {} })); ku_.forEach(f => f({ code: c })); };
let vt = 0;
function step(frames, ms = 16.7) {
  for (let i = 0; i < frames; i++) {
    const cbs = rafQueue.splice(0, rafQueue.length);
    vt += ms;
    for (const cb of cbs) cb(vt);
  }
}

const perf = (label, fn, n) => {
  fn(); // 预热
  const t0 = process.hrtime.bigint();
  for (let i = 0; i < n; i++) fn();
  const ms = Number(process.hrtime.bigint() - t0) / 1e6;
  return { label, n, total: ms, per: ms / n };
};

step(3);
setPlayerName("基准");
tap("Enter"); step(2);

// 构造最坏场景：60 只僵尸全部排在玩家正前方
function fillEnemies(count) {
  enemies.length = 0;
  for (let i = 0; i < count; i++) {
    const e = makeZombie("walker", 300 + i * 15, -1);
    e.hp = e.maxHp = 1e9; // 不死，避免 splice 干扰测量
    enemies.push(e);
  }
}
function shootN(weapon, lv, n) {
  const p = players[0];
  p.guns = ["pistol", weapon];
  p.gunIdx = 1;
  p.wlv[weapon] = { lv, xp: 0 };
  fillEnemies(60);
  beams.length = 0;
  return perf(weapon + " Lv" + lv, () => { p.shootCd = 0; playerShoot(p); }, n);
}

const rows = [];
rows.push(shootN("pistol", 1, 2000));
rows.push(shootN("smg", 1, 2000));
rows.push(shootN("laser", 1, 2000));
rows.push(shootN("laser", 5, 2000));
rows.push(shootN("laser", 10, 2000));
rows.push(shootN("laser", 15, 2000));

console.log("\n每帧预算 16.7ms；下面是一次开火（单发）的耗时：");
console.log("  武器           次数      总耗时      单次");
for (const r of rows) {
  console.log("  " + r.label.padEnd(14) + String(r.n).padEnd(9) +
    (r.total.toFixed(1) + "ms").padEnd(12) + r.per.toFixed(4) + "ms");
}

// laserHits 是纯采样循环，单独压一下
fillEnemies(60);
const cx = 200, cy = 500, ex = 1150, ey = 500;
const hit = perf("laserHits x60", () => { for (const e of enemies) laserHits(e, cx, cy, ex, ey); }, 2000);
console.log("\n  laserHits 遍历 60 只僵尸: " + hit.per.toFixed(4) + "ms/次");

process.exit(0);
