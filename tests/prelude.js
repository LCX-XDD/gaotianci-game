// Node 无头测试：打桩 DOM / Canvas / fetch，真实驱动游戏循环
// 固定随机种子 —— 让整条测试对游戏内 RNG(刷怪/精英/暴击)完全可复现
let __seed = 0x9e3779b9;
Math.random = function () {
  __seed |= 0; __seed = (__seed + 0x6D2B79F5) | 0;
  let t = Math.imul(__seed ^ (__seed >>> 15), 1 | __seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};

const winListeners = {}, docListeners = {}, rafQueue = [];

function makeCtx() {
  const grad = { addColorStop() {} };
  const t = { createLinearGradient: () => grad, createRadialGradient: () => grad,
              measureText: () => ({ width: 10 }) };
  return new Proxy(t, {
    get(o, k) { return k in o ? o[k] : () => {}; },
    set(o, k, v) { o[k] = v; return true; },
  });
}
const canvasStub = {
  width: 1280, height: 720,
  getContext: () => makeCtx(),
  addEventListener() {},
  getBoundingClientRect: () => ({ left: 0, top: 0, width: 1280, height: 720 }),
};
const _ls = {};
globalThis.localStorage = {
  getItem: k => (k in _ls ? _ls[k] : null),
  setItem: (k, v) => { _ls[k] = String(v); },
  removeItem: k => { delete _ls[k]; },
};
globalThis.document = {
  getElementById: id => (id === "game" ? canvasStub : null),
  addEventListener: (t, f) => { (docListeners[t] = docListeners[t] || []).push(f); },
  hidden: false, fullscreenElement: null,
  documentElement: { requestFullscreen: () => Promise.resolve() },
  exitFullscreen: () => Promise.resolve(),
};
globalThis.window = globalThis;
globalThis.addEventListener = (t, f) => { (winListeners[t] = winListeners[t] || []).push(f); };
globalThis.prompt = () => "测试代号";
globalThis.requestAnimationFrame = cb => { rafQueue.push(cb); return rafQueue.length; };

const fetchCalls = [];
function fakeProfile() {
  const defs = [
    { id: "first_blood", name: "初次猎杀", icon: "🩸", tier: "bronze", desc: "一局内击杀至少 1 只僵尸", unlocked: true, unlocked_at: "2026-09-14T20:00:00+08:00" },
    { id: "slayer_100", name: "百人斩", icon: "⚔️", tier: "silver", desc: "单局击杀 100 只僵尸", unlocked: false, unlocked_at: null },
    { id: "score_50k", name: "传　说", icon: "🏆", tier: "platinum", desc: "单局得分达到 50000", unlocked: false, unlocked_at: null },
  ];
  return { name: "测试代号", best_score: 9000, best_kills: 120, best_wave: 3, best_map_name: "城市街区",
    total_score: 22000, total_kills: 300, total_runs: 4, total_time: 900, created_at: "2026-09-01T00:00:00+08:00",
    unlocked_weapons: ["pistol", "smg"], achievements: defs, achievement_count: 1 };
}
globalThis.fetch = (url, opts) => {
  fetchCalls.push({ url, body: opts && opts.body ? JSON.parse(opts.body) : null });
  let data;
  if (url.startsWith("/api/leaderboard")) data = { sort: "score", entries: [
    { id: 1, name: "老张", score: 52300, kills: 410, wave: 5, map_name: "极地冰原", duration: 380, player_count: 2, max_weapon_level: 15, created_at: "2026-09-13" },
    { id: 2, name: "测试代号", score: 9000, kills: 120, wave: 3, map_name: "城市街区", duration: 200, player_count: 1, max_weapon_level: 7, created_at: "2026-09-14" },
  ] };
  else if (url.startsWith("/api/profile")) data = fakeProfile();
  else if (url.startsWith("/api/run")) data = { ok: true, run_id: 7, rank: 3, personal_best: true,
    new_achievements: [
      { id: "first_blood", name: "初次猎杀", icon: "🩸", tier: "bronze", desc: "一局内击杀至少 1 只僵尸" },
      { id: "king_slayer", name: "弑　王", icon: "👑", tier: "gold", desc: "击杀僵尸王" },
    ], profile: fakeProfile() };
  else if (url.startsWith("/api/heartbeat")) data = { ok: true, saved: true };
  else data = { ok: false, error: "unknown" };
  return Promise.resolve({ json: () => Promise.resolve(data) });
};
globalThis.window.addEventListener = globalThis.addEventListener;
