// The game's page: the map (MapLibre, the relief of the historical map), the start sheet, the figures of the
// player's country, the province and country sheets with their actions, diplomacy, the log and saving.

import { MapData } from "./data.js";
import { buildGraph } from "./geometry.js";
import * as R from "./rules.js";
import { aiTurn } from "./ai.js";

const DATA = "../ww2/maps/data";
const SAVE = "civ-demo-save-v1";
const AGGRESSION = [["温和", 0.3], ["正常", 1], ["好战", 2.5]];
const md = new MapData(DATA);
const $ = (id) => document.getElementById(id);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const fmt = (n) => n >= 1e8 ? (n / 1e8).toFixed(2) + " 亿" : n >= 1e4 ? (n / 1e4).toFixed(n >= 1e6 ? 0 : 1) + " 万" : String(Math.round(n));
const num = (n) => Math.round(n).toLocaleString();
const signed = (n) => (n >= 0 ? "+" : "−") + Math.abs(Math.round(n)).toLocaleString();
const store = {
  get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); return true; } catch (e) { return false; } },
  del(k) { try { localStorage.removeItem(k); } catch (e) {} },
};
const shortName = (n) => (n || "").split(/[（(]/)[0];

let map;
const G = { index: null, eco: null, snap: null, sd: null, board: null, state: null, phase: "start", sel: -1, view: "overview",
  viewCountry: -1, move: null, moveMode: false, mode: "political", painted: [], hover: null, pick: -1, aggression: 1, busy: false,
  marks: { sel: [], reach: [], csel: [] }, filter: "" };
const P = () => G.state.player;

// ------------------------------------------------------------------ relief tiles and glyphs (as the map page)
const sheets = new Map();
function sheet(name) {
  if (sheets.has(name)) { const p = sheets.get(name); sheets.delete(name); sheets.set(name, p); return p; }
  const p = fetch(`${DATA}/relief/${name}.webp`).then((r) => { if (!r.ok) throw new Error(name); return r.blob(); })
    .then((b) => createImageBitmap(b, { premultiplyAlpha: "none", colorSpaceConversion: "none" }));
  p.catch(() => sheets.delete(name));
  sheets.set(name, p);
  while (sheets.size > 24) sheets.delete(sheets.keys().next().value);
  return p;
}
const canvas = (w, h) => typeof OffscreenCanvas !== "undefined" ? new OffscreenCanvas(w, h) : Object.assign(document.createElement("canvas"), { width: w, height: h });
const toPng = async (c) => (c.convertToBlob ? await c.convertToBlob({ type: "image/png" }) : await new Promise((r) => c.toBlob(r, "image/png"))).arrayBuffer();
function registerProtocols() {
  maplibregl.addProtocol("relief", async (params) => {
    const [, set, z, x, y] = /^relief:\/\/(\w)\/(\d+)\/(\d+)\/(\d+)/.exec(params.url).map((v, i) => i > 1 ? +v : v);
    const per = 8, i = Math.floor(x / per), j = Math.floor(y / per);
    const bmp = await sheet(`${set}${z}_${i}_${j}`);
    const c = canvas(256, 256); const g = c.getContext("2d"); g.imageSmoothingEnabled = false;
    g.drawImage(bmp, (x - i * per) * 256, (y - j * per) * 256, 256, 256, 0, 0, 256, 256);
    return { data: await toPng(c) };
  });
  // Chinese characters are drawn by the browser (localIdeographFontFamily); digits and Latin from data/glyphs/sans
  maplibregl.addProtocol("glyph", async (params) => {
    const range = /\/(\d+-\d+)$/.exec(params.url)[1];
    try { return { data: await md.io.bin(`${DATA}/glyphs/sans/${range}.pbf`) }; } catch (e) { return { data: new ArrayBuffer(0) }; }
  });
}

// ------------------------------------------------------------------ map
function icon(w, h, draw) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; const g = c.getContext("2d"); draw(g); return g.getImageData(0, 0, w, h);
}
function initMap() {
  map = new maplibregl.Map({ container: "map", center: [40, 30], zoom: 1.7, minZoom: 1, maxZoom: 9, attributionControl: false,
    renderWorldCopies: false, localIdeographFontFamily: "'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif", dragRotate: false, pitchWithRotate: false,
    style: { version: 8, glyphs: "glyph://{fontstack}/{range}", sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#cfe0ea" } }] } });
  map.touchZoomRotate.disableRotation();
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
  return new Promise((ok) => map.on("load", ok));
}
const empty = () => ({ type: "FeatureCollection", features: [] });
function addLayers() {
  // a star for capitals, an arrow head for orders
  map.addImage("star", icon(26, 26, (g) => {
    g.beginPath(); for (let i = 0; i < 10; i++) { const r = i % 2 ? 5 : 12, a = -Math.PI / 2 + i * Math.PI / 5; g.lineTo(13 + r * Math.cos(a), 13 + r * Math.sin(a)); }
    g.closePath(); g.fillStyle = "#ffd34d"; g.strokeStyle = "#5a3b00"; g.lineWidth = 2; g.fill(); g.stroke();
  }), { pixelRatio: 2 });
  map.addImage("arrow", icon(24, 24, (g) => { g.beginPath(); g.moveTo(22, 12); g.lineTo(4, 3); g.lineTo(8, 12); g.lineTo(4, 21); g.closePath(); g.fillStyle = "#fff"; g.fill(); }),
    { sdf: true, pixelRatio: 2 });
  map.addSource("relief", { type: "raster", tiles: ["relief://r/{z}/{x}/{y}"], tileSize: 256, minzoom: 0, maxzoom: 5 });
  map.addSource("shade", { type: "raster", tiles: ["relief://s/{z}/{x}/{y}"], tileSize: 256, minzoom: 0, maxzoom: 5 });
  for (const s of ["prov", "armies", "orders", "caps", "names", "lanes", "hydro"]) map.addSource(s, { type: "geojson", data: empty(), ...(s === "prov" ? { tolerance: 0.1 } : {}) });
  map.addLayer({ id: "relief", type: "raster", source: "relief", paint: { "raster-fade-duration": 0 } });
  map.addLayer({ id: "prov-fill", type: "fill", source: "prov", paint: { "fill-color": ["to-color", ["coalesce", ["feature-state", "c"], "#d0ccc0"]],
    "fill-opacity": ["case", ["boolean", ["feature-state", "cs"], false], 0.86, 0.68] } });
  map.addLayer({ id: "shade", type: "raster", source: "shade", paint: { "raster-fade-duration": 0, "raster-opacity": 0.55 } });
  map.addLayer({ id: "hydro-fill", type: "fill", source: "hydro", filter: ["==", ["get", "k"], "l"], paint: { "fill-color": "#b2d3ea" } });
  map.addLayer({ id: "hydro-line", type: "line", source: "hydro", filter: ["all", ["==", ["get", "k"], "r"], ["<=", ["get", "r"], 6]],
    paint: { "line-color": "#2b7cc4", "line-opacity": ["interpolate", ["linear"], ["zoom"], 1, 0.35, 4, 0.8], "line-width": ["interpolate", ["linear"], ["zoom"], 1, 0.4, 6, 1.6] } });
  map.addLayer({ id: "prov-line", type: "line", source: "prov", paint: { "line-color": "#27302c",
    "line-opacity": ["interpolate", ["linear"], ["zoom"], 1, 0.18, 4, 0.35, 7, 0.55], "line-width": ["interpolate", ["linear"], ["zoom"], 1, 0.3, 6, 0.9] } });
  map.addLayer({ id: "csel-line", type: "line", source: "prov", paint: { "line-color": "#141a18", "line-width": 1.3,
    "line-opacity": ["case", ["boolean", ["feature-state", "cs"], false], 0.9, 0] } });
  map.addLayer({ id: "reach-line", type: "line", source: "prov", paint: {
    "line-color": ["match", ["coalesce", ["feature-state", "r"], 0], 1, "#ffffff", 2, "#ff6a4d", 3, "#9fd3ff", "#000000"],
    "line-width": 2.2, "line-opacity": ["case", [">", ["coalesce", ["feature-state", "r"], 0], 0], 0.95, 0] } });
  map.addLayer({ id: "hover-line", type: "line", source: "prov", paint: { "line-color": "#111", "line-width": ["case", ["boolean", ["feature-state", "hov"], false], 1.6, 0] } });
  map.addLayer({ id: "sel-line", type: "line", source: "prov", paint: { "line-color": "#ffd34d", "line-width": ["case", ["boolean", ["feature-state", "sel"], false], 3.2, 0] } });
  map.addLayer({ id: "lanes", type: "line", source: "lanes", paint: { "line-color": "#1f5f99", "line-width": 1.4, "line-dasharray": [2, 3], "line-opacity": 0.75 } });
  map.addLayer({ id: "orders", type: "line", source: "orders", layout: { "line-cap": "round" },
    paint: { "line-color": ["match", ["get", "a"], 1, "#d63c2f", "#1f63b5"], "line-width": 3, "line-opacity": 0.9 } });
  map.addLayer({ id: "orders-head", type: "symbol", source: "orders", layout: { "symbol-placement": "line-center", "icon-image": "arrow",
    "icon-size": 1, "icon-allow-overlap": true, "icon-ignore-placement": true, "icon-rotation-alignment": "map" },
    paint: { "icon-color": ["match", ["get", "a"], 1, "#d63c2f", "#1f63b5"] } });
  map.addLayer({ id: "names", type: "symbol", source: "names", layout: {
    "text-field": ["get", "n"], "text-font": ["sans Medium"], "text-size": zoomStops((w, s) => ["min", 34, ["*", w, s]]),
    "text-letter-spacing": 0.12, "text-max-width": 40, "text-allow-overlap": true, "text-ignore-placement": true },
    paint: { "text-color": "#1d2421", "text-halo-color": "rgba(255,255,255,0.55)", "text-halo-width": 1.2,
      "text-opacity": zoomStops((w, s) => ["case", [">=", ["*", w, s], 11], 0.62, 0]) } });
  map.addLayer({ id: "caps", type: "symbol", source: "caps", layout: { "icon-image": "star", "icon-size": ["interpolate", ["linear"], ["zoom"], 1, 0.6, 5, 1],
    "icon-allow-overlap": true, "icon-offset": [0, -22], "symbol-sort-key": ["get", "s"] }, minzoom: 2.2 });
  // division counts, on a halo in the colour of the owner's relation to the player
  map.addLayer({ id: "armies", type: "symbol", source: "armies", layout: {
    "text-field": ["get", "t"], "text-font": ["sans Medium"], "text-size": ["interpolate", ["linear"], ["zoom"], 1, 10, 5, 12.5],
    "symbol-sort-key": ["-", 0, ["get", "n"]], "text-padding": 0 },
    paint: { "text-halo-color": ["match", ["get", "r"], 0, "#1b2220", 1, "#2a6fc4", 2, "#b8322a", "rgba(250,250,246,0.95)"],
      "text-color": ["match", ["get", "r"], 3, "#1b2220", "#ffffff"], "text-halo-width": 3.2, "text-halo-blur": 0.3 } });
}
// a layout or paint value per zoom level from the label's width property w: f(w, 2^zoom)
function zoomStops(f) { const e = ["interpolate", ["linear"], ["zoom"]]; for (let z = 0; z <= 9; z++) e.push(z, f(["get", "w"], 2 ** z)); return e; }

function provFeatures(geoms) {
  return { type: "FeatureCollection", features: geoms.map((g, k) => ({ type: "Feature", id: k, geometry: { type: "MultiPolygon", coordinates: g }, properties: {} })) };
}

// ------------------------------------------------------------------ colours
const DIPLO = { self: "#2e9e5b", ally: "#3f86d8", war: "#d9483b", truce: "#e2a63b", none: "#c9c4b5", contested: "#8f8b82" };
const ARMY_RAMP = [[0, "#ecebe5"], [1, "#fde3c7"], [6, "#fbc08a"], [21, "#f28c4b"], [51, "#d9542a"], [151, "#9c2d12"]];
function colorOf(k) {
  const st = G.state, o = st.owner[k], O = st.countries[o];
  if (G.mode === "army" && G.phase === "play") { let c = ARMY_RAMP[0][1]; for (const [v, col] of ARMY_RAMP) if (st.army[k] >= v) c = col; return c; }
  if (G.mode === "diplo" && G.phase === "play") return DIPLO[relKind(o)];
  return O.contested ? DIPLO.contested : O.color;
}
function relKind(c) {
  const st = G.state, p = P();
  if (st.countries[c].contested) return "contested";
  if (c === p) return "self";
  if (R.atWar(st, p, c)) return "war";
  if (R.allied(st, p, c)) return "ally";
  if ((st.truce.get(R.pair(p, c)) || 0) > st.turn) return "truce";
  return "none";
}
function paint() {
  const st = G.state; if (!st) return;
  for (let k = 0; k < G.board.P; k++) {
    const c = colorOf(k);
    if (G.painted[k] !== c) { G.painted[k] = c; map.setFeatureState({ source: "prov", id: k }, { c }); }
  }
}

function setMark(kind, ids, value) {
  for (const k of G.marks[kind] || []) map.setFeatureState({ source: "prov", id: k }, { [kind === "csel" ? "cs" : kind === "reach" ? "r" : "sel"]: kind === "reach" ? 0 : false });
  G.marks[kind] = ids;
  for (const [i, k] of ids.entries()) map.setFeatureState({ source: "prov", id: k }, { [kind === "csel" ? "cs" : kind === "reach" ? "r" : "sel"]: Array.isArray(value) ? value[i] : value });
}
function markSelection() {
  const st = G.state, b = G.board;
  const k = G.sel;
  setMark("sel", k >= 0 ? [k] : [], true);
  const country = G.phase === "start" ? G.pick : G.view === "country" ? G.viewCountry : k >= 0 ? st.owner[k] : -1;
  const cs = []; if (country >= 0) for (let j = 0; j < b.P; j++) if (st.owner[j] === country) cs.push(j);
  setMark("csel", cs, true);
  const reach = [], kinds = [], lanes = [];
  if (G.phase === "play" && k >= 0 && st.owner[k] === P()) {
    for (const [j, kind] of R.exits(b, k)) {
      if (kind === 2) { lanes.push(j); continue; }
      reach.push(j); kinds.push(R.isEnemy(st, P(), st.owner[j]) ? 2 : kind === 1 ? 3 : 1);
    }
  }
  setMark("reach", reach, kinds);
  map.getSource("lanes").setData({ type: "FeatureCollection", features: lanes.map((j) => ({ type: "Feature", properties: {},
    geometry: { type: "LineString", coordinates: [b.labels[k], b.labels[j]] } })) });
}

// ------------------------------------------------------------------ the symbols of a turn: divisions, orders, capitals, names
function drawSymbols() {
  const st = G.state, b = G.board; const p = G.phase === "play" ? P() : -1;
  const armies = [];
  for (let k = 0; k < b.P; k++) {
    const n = st.army[k]; if (n <= 0) continue;
    const o = st.owner[k]; const r = p < 0 ? 3 : o === p ? 0 : R.allied(st, p, o) ? 1 : R.atWar(st, p, o) ? 2 : 3;
    armies.push({ type: "Feature", properties: { n, t: n >= 10000 ? Math.round(n / 1000) + "k" : String(n), r }, geometry: { type: "Point", coordinates: b.labels[k] } });
  }
  map.getSource("armies").setData({ type: "FeatureCollection", features: armies });
  const orders = p < 0 ? [] : st.orders.filter((o) => o.owner === p).map((o) => ({ type: "Feature",
    properties: { a: R.isEnemy(st, p, st.owner[o.to]) ? 1 : 0 }, geometry: { type: "LineString", coordinates: [b.labels[o.from], b.labels[o.to]] } }));
  if (G.move) orders.push({ type: "Feature", properties: { a: R.isEnemy(st, p, st.owner[G.move.to]) ? 1 : 0 },
    geometry: { type: "LineString", coordinates: [b.labels[G.move.from], b.labels[G.move.to]] } });
  map.getSource("orders").setData({ type: "FeatureCollection", features: orders });
  map.getSource("caps").setData({ type: "FeatureCollection", features: st.countries.filter((c) => c.alive && !c.contested && c.capital >= 0 && st.owner[c.capital] === c.id)
    .map((c) => ({ type: "Feature", properties: { s: -c.startPop }, geometry: { type: "Point", coordinates: b.labels[c.capital] } })) });
  map.getSource("names").setData(countryNames());
}
// each country's name over the largest connected stretch of its land, sized to fit it
function countryNames() {
  const st = G.state, b = G.board; const seen = new Uint8Array(b.P); const best = new Map();
  for (let k = 0; k < b.P; k++) {
    if (seen[k]) continue; const c = st.owner[k]; seen[k] = 1;
    const ks = [k]; for (let i = 0; i < ks.length; i++) for (const j of b.adj[ks[i]]) if (!seen[j] && st.owner[j] === c) { seen[j] = 1; ks.push(j); }
    if (st.countries[c].contested) continue;
    let a = 0; for (const j of ks) a += b.area[j];
    const g = best.get(c); if (!g || a > g.a) best.set(c, { a, ks });
  }
  const feats = [];
  for (const [c, { a, ks }] of best) {
    let x = 0, y = 0, x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const j of ks) { const w = b.area[j] + 1; x += b.labels[j][0] * w; y += b.labels[j][1] * w; const bb = b.boxes[j];
      x0 = Math.min(x0, bb[0]); x1 = Math.max(x1, bb[2]); y0 = Math.min(y0, bb[1]); y1 = Math.max(y1, bb[3]); }
    const tot = ks.reduce((s, j) => s + b.area[j] + 1, 0); x /= tot; y /= tot;
    let at = ks[0], bd = Infinity; for (const j of ks) { const d = (b.labels[j][0] - x) ** 2 + (b.labels[j][1] - y) ** 2; if (d < bd) { bd = d; at = j; } }
    const name = shortName(st.countries[c].name); const n = [...name].length || 1;
    const W = Math.min(x1 - x0, 2.2 * (y1 - y0) / Math.cos(y * Math.PI / 180), 200);
    feats.push({ type: "Feature", properties: { n: name, a, w: 1.42 * 0.62 * W / n }, geometry: { type: "Point", coordinates: [(b.labels[at][0] + x) / 2, (b.labels[at][1] + y) / 2] } });
  }
  return { type: "FeatureCollection", features: feats };
}

function refresh() { paint(); drawSymbols(); markSelection(); hud(); }

// ------------------------------------------------------------------ loading a date
async function loadScenario(snap, saved) {
  $("loading").hidden = false; $("loading").textContent = "正在载入地图断面与省份轮廓…";
  await new Promise((r) => setTimeout(r, 30));
  const sd = await md.loadSnap(snap);
  $("loading").textContent = "正在生成棋盘（邻接省份、海峡与海路）…";
  await new Promise((r) => setTimeout(r, 30));
  const geoms = md.featureGeoms(sd);
  const graph = buildGraph(geoms);
  const names = sd.feature.map((_, k) => md.provinceName(sd, k));
  G.sd = sd; G.snap = snap; G.board = R.buildBoard(sd, geoms, graph, names, G.eco);
  G.state = saved || R.newGame(sd, G.board, { player: -1, aggression: G.aggression, seed: (Date.now() % 1e9) >>> 0 });
  G.sel = -1; G.move = null; G.moveMode = false; G.view = "overview"; G.pick = -1; G.painted = [];
  for (const kind of Object.keys(G.marks)) G.marks[kind] = [];
  map.removeFeatureState({ source: "prov" });
  map.getSource("prov").setData(provFeatures(geoms));
  $("mapLink").href = `../ww2/maps/#${snap}/control`;
  refresh();
  await new Promise((r) => map.once("idle", r));
  $("loading").hidden = true;
}

// ------------------------------------------------------------------ the start sheet
function renderStart() {
  const side = $("side"); side.replaceChildren();
  side.append(el("h2", null, "选择历史断面与国家"));
  side.append(el("p", "lede", "每个断面都是历史地图上的一天：当日的省级区划、实际控制者、阵营与人口。选一个断面，再选一个国家，像《文明时代 2》那样逐月经营、调兵、外交与征战。"));
  const saved = store.get(SAVE);
  if (saved) {
    try {
      const s = JSON.parse(saved); const c = s.countries[s.player];
      const b = el("button", "btn primary", `继续存档：${shortName(c.name)} · ${s.year} 年 ${s.month} 月`); b.type = "button";
      b.onclick = () => continueGame(saved); side.append(b);
    } catch (e) { store.del(SAVE); }
  }
  const sec = el("div", "stack"); sec.append(el("h3", null, "① 历史断面"));
  const list = el("ul", "list scen");
  for (const s of G.index.snapshots) {
    const li = el("li"); const b = el("button"); b.type = "button"; if (s.snapshot === G.snap) b.className = "cur";
    b.append(el("span", "d", s.snapshot === "2026" ? "2026" : s.snapshot.replace(/-/g, ".")), el("span", "nm", s.title_zh));
    b.onclick = async () => { if (s.snapshot !== G.snap) { await loadScenario(s.snapshot); renderSide(); } };
    li.append(b); list.append(li);
  }
  sec.append(list); side.append(sec);
  queueMicrotask(() => { const cur = list.querySelector(".cur"); if (cur) list.scrollTop = cur.offsetTop - list.offsetTop - 60; });
  if (!G.state) return;
  const st = G.state, b = G.board, t = R.tally(st, b);
  const sec2 = el("div", "stack"); sec2.append(el("h3", null, "② 国家（也可直接点击地图）"));
  const q = el("input", "search"); q.type = "search"; q.placeholder = "查找国家，如 德国、中华民国、日本"; q.value = G.filter;
  const ul = el("ul", "list picklist");
  const fill = () => {
    ul.replaceChildren();
    const rows = st.countries.filter((c) => c.alive && !c.contested && (!G.filter || c.name.includes(G.filter) || (c.en || "").toLowerCase().includes(G.filter.toLowerCase())))
      .sort((a, z) => t.pop[z.id] - t.pop[a.id]).slice(0, 80);
    for (const c of rows) {
      const li = el("li"); const bt = el("button"); bt.type = "button"; if (c.id === G.pick) bt.className = "cur";
      const f = el("span", "flag"); f.style.background = c.color;
      bt.append(f, el("span", "nm", c.name), el("span", "num", fmt(t.pop[c.id])));
      bt.onclick = () => { pickCountry(c.id, true); }; li.append(bt); ul.append(li);
    }
  };
  q.oninput = () => { G.filter = q.value.trim(); fill(); };
  fill(); sec2.append(q, ul); side.append(sec2);
  if (G.pick >= 0) {
    const c = st.countries[G.pick];
    const box = el("div", "stack");
    const tt = el("div", "title"); const f = el("span", "flag"); f.style.background = c.color; tt.append(f, el("h2", null, c.name)); box.append(tt);
    box.append(kv([["人口", fmt(t.pop[c.id])], ["省份", t.held[c.id].length], ["首都", c.capital >= 0 ? b.names[c.capital] : "—"],
      ["军队", num(t.army[c.id]) + " 师"], ["收入", `${num(t.income[c.id])} 金 / 回合`], ["战力", R.quality(st, c.id).toFixed(2)]]));
    const foes = R.enemiesOf(st, c.id), friends = R.alliesOf(st, c.id);
    box.append(el("p", "lede", foes.length ? `交战：${foes.map((x) => shortName(st.countries[x].name)).slice(0, 12).join("、")}${foes.length > 12 ? " 等" : ""}` : "当日未处于战争中。"));
    if (friends.length) box.append(el("p", "hint", `同盟：${friends.map((x) => shortName(st.countries[x].name)).slice(0, 14).join("、")}${friends.length > 14 ? " 等" : ""}`));
    side.append(box);
  }
  const opt = el("div", "row"); opt.append(el("h3", null, "电脑国家"));
  const seg = el("div", "seg");
  for (const [label, v] of AGGRESSION) {
    const bt = el("button", null, label); bt.type = "button"; bt.setAttribute("aria-pressed", String(G.aggression === v));
    bt.onclick = () => { G.aggression = v; st.aggression = v; renderSide(); }; seg.append(bt);
  }
  opt.append(seg); side.append(opt);
  const go = el("button", "btn primary big", G.pick >= 0 ? `以 ${shortName(st.countries[G.pick].name)} 开始` : "请先选择国家"); go.type = "button";
  go.disabled = G.pick < 0; go.onclick = () => startGame(G.pick); side.append(go);
}
function pickCountry(c, fly) {
  G.pick = c; markSelection(); renderSide();
  if (fly) flyToCountry(c);
}
function flyToCountry(c) {
  const st = G.state, b = G.board; const cap = st.countries[c].capital;
  if (cap >= 0) map.flyTo({ center: b.labels[cap], zoom: Math.max(3, Math.min(map.getZoom(), 4.2)), duration: 900 });
}

function startGame(c) {
  const st = G.state; st.player = c; st.aggression = G.aggression; G.phase = "play"; G.sel = -1; G.view = "overview";
  st.log.push({ turn: 0, text: `${st.year} 年 ${st.month} 月：你开始执掌 ${st.countries[c].name}`, who: [c] });
  ["me", "stats", "tools", "mapmode", "logbox"].forEach((id) => { $(id).hidden = false; });
  autosave(); refresh(); renderSide(); renderLog(); flyToCountry(c);
  toast(matchMedia("(pointer: coarse)").matches ? "点击省份选择；本国有驻军的省份可按“选择目标…”，再点目标省份调兵或进攻。"
    : "左键选择省份；选中本国有驻军的省份后，右键点击目标省份调兵或进攻。回车结束回合。");
}
async function continueGame(text) {
  const saved = R.load(text);
  await loadScenario(saved.snap, saved);
  G.phase = "play"; G.aggression = saved.aggression;
  ["me", "stats", "tools", "mapmode", "logbox"].forEach((id) => { $(id).hidden = false; });
  refresh(); renderSide(); renderLog(); flyToCountry(saved.player);
}
function autosave() { if (G.phase === "play" && !G.state.over) store.set(SAVE, R.save(G.state)); }

// ------------------------------------------------------------------ figures along the top
function hud() {
  if (G.phase !== "play") return;
  const st = G.state, b = G.board, p = P(), C = st.countries[p], t = R.tally(st, b);
  $("meFlag").style.background = C.color; $("meName").textContent = shortName(C.name);
  $("sDate").textContent = `${st.year} 年 ${st.month} 月 · 第 ${st.turn + 1} 回合`;
  const net = t.income[p] - t.army[p] * R.RULES.upkeep;
  $("sGold").textContent = num(C.gold); $("sGoldD").textContent = signed(net); $("sGoldD").className = "d " + (net >= 0 ? "up" : "down");
  $("sMan").textContent = num(C.manpower); $("sManD").textContent = "+" + R.manpowerGain(st, b, p).toFixed(1); $("sManD").className = "d up";
  $("sArmy").textContent = num(t.army[p]);
  $("sProv").textContent = `${t.held[p].length} 省 · ${fmt(t.pop[p])}`;
  $("sQ").textContent = R.quality(st, p).toFixed(2) + (C.tech ? ` · 科技 ${C.tech}` : "");
  $("bEnd").disabled = G.busy || !!st.over;
}

// ------------------------------------------------------------------ side sheet
function kv(rows) {
  const dl = el("dl", "kv");
  for (const [k, v] of rows) { if (v == null) continue; dl.append(el("dt", null, k)); const dd = el("dd"); if (v instanceof Node) dd.append(v); else dd.textContent = String(v); dl.append(dd); }
  return dl;
}
function flagName(c, onclick) {
  const st = G.state; const s = el("span", "title");
  const f = el("span", "flag"); f.style.background = st.countries[c].color;
  const n = onclick ? el("button", "link", st.countries[c].name) : el("span", null, st.countries[c].name);
  if (onclick) { n.type = "button"; n.onclick = onclick; }
  s.append(f, n); return s;
}
function relChip(c) {
  const k = relKind(c);
  const text = { self: "本国", war: "交战", ally: "同盟", truce: `停战至第 ${(G.state.truce.get(R.pair(P(), c)) || 0) + 1} 回合`, none: "和平", contested: "交战区" }[k];
  return el("span", "chip " + ({ self: "self", war: "war", ally: "ally", truce: "truce" }[k] || ""), text);
}
function button(text, onclick, cls = "btn", disabled = false, title = "") {
  const b = el("button", cls, text); b.type = "button"; b.onclick = onclick; b.disabled = disabled; if (title) b.title = title; return b;
}
function renderSide() {
  if (G.phase === "start") return renderStart();
  const side = $("side"); side.replaceChildren(); side.scrollTop = 0;
  if (G.move) renderMove(side);
  else if (G.view === "country" && G.viewCountry >= 0) renderCountry(side, G.viewCountry);
  else if (G.sel >= 0) renderProvince(side, G.sel);
  else renderOverview(side);
}

function renderOverview(side) {
  const st = G.state, b = G.board, p = P(), t = R.tally(st, b);
  side.append(flagName(p));
  side.append(el("p", "lede", `${st.year} 年 ${st.month} 月。${b.title || ""}`));
  const foes = R.enemiesOf(st, p).filter((x) => st.countries[x].alive);
  const sec = el("div", "stack"); sec.append(el("h3", null, foes.length ? `交战国（${foes.length}）` : "当前和平"));
  if (foes.length) sec.append(countryList(foes.sort((a, z) => t.pop[z] - t.pop[a]), (x) => `战争分数 ${(R.warScore(st, b, p, x) * 100).toFixed(0)}`));
  side.append(sec);
  const front = t.held[p].filter((k) => R.neighbours(b, k).some((j) => R.isEnemy(st, p, st.owner[j])));
  if (front.length) {
    const s2 = el("div", "stack"); s2.append(el("h3", null, `前线省份（${front.length}）`));
    const ul = el("ul", "list");
    for (const k of front.sort((a, z) => st.army[z] - st.army[a]).slice(0, 12)) {
      const li = el("li"); const bt = el("button"); bt.type = "button"; const f = el("span", "flag"); f.style.background = st.countries[p].color;
      bt.append(f, el("span", "nm", b.names[k]), el("span", "num", `${st.army[k]} 师`)); bt.onclick = () => select(k, true); li.append(bt); ul.append(li);
    }
    s2.append(ul); side.append(s2);
  }
  side.append(el("p", "hint", "左键点击省份查看与建设；选中本国有驻军的省份后，右键点击目标省份调兵（相邻敌省即进攻，远处的本国省份按回合行军）。白色描边为可直达的陆上邻省、浅蓝为海峡、红色为可进攻的敌省，虚线为港口之间的海路。"));
  side.append(button("国家概况与科技", () => showCountry(p)));
}
function countryList(ids, meta) {
  const st = G.state; const ul = el("ul", "list");
  for (const x of ids) {
    const li = el("li"); const bt = el("button"); bt.type = "button"; const f = el("span", "flag"); f.style.background = st.countries[x].color;
    bt.append(f, el("span", "nm", st.countries[x].name), el("span", "num", meta ? meta(x) : "")); bt.onclick = () => showCountry(x); li.append(bt); ul.append(li);
  }
  return ul;
}

function renderProvince(side, k) {
  const st = G.state, b = G.board, p = P(); const o = st.owner[k]; const O = st.countries[o]; const mine = o === p;
  const head = el("div", "stack");
  const top = el("div", "row"); top.style.justifyContent = "space-between";
  top.append(el("h2", null, b.names[k]), button("×", () => { select(-1); }, "close"));
  head.append(top);
  const who = el("div", "row"); who.append(flagName(o, O.contested ? null : () => showCountry(o)), relChip(o));
  if (st.core[k] !== o && !st.countries[st.core[k]].contested) who.append(el("span", "chip", `被占领（核心：${shortName(st.countries[st.core[k]].name)}）`));
  if (O.capital === k) who.append(el("span", "chip", "首都"));
  head.append(who); side.append(head);
  const cities = b.cities.filter((c) => c.k === k).map((c) => c.n);
  side.append(kv([["人口", fmt(b.pop[k])], ["面积", num(b.area[k]) + " km²"], ["人均 GDP", "$" + num(b.gdppc[k])],
    ["税收", `${R.provinceIncome(st, b, k).toFixed(1)} 金 / 回合`], ["经济", `${st.econ[k]} / ${R.RULES.econMax} 级`], ["要塞", `${st.fort[k]} / ${R.RULES.fortMax} 级`],
    ["驻军", `${st.army[k]} 师${O.contested ? "" : `（战力 ${R.quality(st, o).toFixed(2)}）`}`], ["城市", cities.length ? cities.slice(0, 6).join("、") : null],
    ["交通", [b.adj[k].length ? `${b.adj[k].length} 个陆上邻省` : "无陆上邻省", b.sea[k].length ? `${b.sea[k].length} 条海峡` : null, b.lanes[k].length ? `港口（${b.lanes[k].length} 条海路）` : null].filter(Boolean).join(" · ")]]));
  if (mine) {
    const C = st.countries[p];
    const sec = el("div", "stack"); sec.append(el("h3", null, "招募军队"));
    const max = Math.max(0, Math.min(Math.floor(C.gold / R.RULES.recruitGold), Math.floor(C.manpower)));
    if (max > 0) {
      const sl = el("div", "slider"); const r = el("input"); r.type = "range"; r.min = 1; r.max = max; r.value = Math.min(max, Math.max(1, Math.round(max / 4)));
      const out = el("output"); const bt = button("", () => { const n = R.recruit(st, b, p, k, +r.value); if (n) { toast(`在 ${b.names[k]} 招募了 ${n} 个师`); update(); } }, "btn primary");
      const set = () => { out.textContent = `${r.value} 师`; bt.textContent = `招募（${r.value * R.RULES.recruitGold} 金、${r.value} 人力）`; };
      r.oninput = set; set(); sl.append(r, out); sec.append(sl, bt);
    } else sec.append(el("p", "hint", `金币或人力不足（每师 ${R.RULES.recruitGold} 金、1 人力）。`));
    side.append(sec);
    const s2 = el("div", "stack"); s2.append(el("h3", null, "建设"));
    const row = el("div", "row");
    const ic = R.investCost(st, b, k), fc = R.fortCost(st, k);
    row.append(button(`投资经济（${ic} 金）`, () => { if (R.invest(st, b, p, k)) { toast(`${b.names[k]} 经济升至 ${st.econ[k]} 级`); update(); } },
      "btn", st.econ[k] >= R.RULES.econMax || C.gold < ic, `每级 +${R.RULES.econStep * 100}% 税收`));
    row.append(button(`建造要塞（${fc} 金）`, () => { if (R.buildFort(st, p, k)) { toast(`${b.names[k]} 要塞升至 ${st.fort[k]} 级`); update(); } },
      "btn", st.fort[k] >= R.RULES.fortMax || C.gold < fc, `每级 +${R.RULES.fortStep * 100}% 防御`));
    s2.append(row); side.append(s2);
    const s3 = el("div", "stack"); s3.append(el("h3", null, "调兵"));
    const queued = st.orders.filter((x) => x.owner === p && x.from === k);
    if (st.army[k] > 0) {
      s3.append(el("p", "hint", "右键点击目标省份；或按下面的按钮，再在地图上左键点选目标。"));
      const row3 = el("div", "row");
      row3.append(button(G.moveMode ? "取消选择目标" : "选择目标…", () => { G.moveMode = !G.moveMode; renderSide(); }, G.moveMode ? "btn primary" : "btn"));
      const f = nearestFront(k);
      if (f >= 0 && f !== k) row3.append(button("全部调往最近前线", () => {
        const x = R.order(st, b, p, k, f, st.army[k]); if (x) toast(`已下令：${x.n} 师 → ${b.names[f]}`); update();
      }, "btn", false, b.names[f]));
      s3.append(row3);
    } else s3.append(el("p", "hint", "此省没有驻军。"));
    for (const x of queued) {
      const row2 = el("div", "row"); row2.append(el("span", null, `→ ${b.names[x.to]}：${x.n} 师`),
        button("撤销", () => { st.orders = st.orders.filter((y) => y !== x); update(); }, "btn")); s3.append(row2);
    }
    side.append(s3);
  } else if (!O.contested) {
    const row = el("div", "row"); row.append(button(`查看 ${shortName(O.name)}`, () => showCountry(o)));
    side.append(row);
    if (R.atWar(st, p, o)) side.append(el("p", "hint", "选中相邻的本国省份后右键点击此省即可进攻。守军享有 25% 防御加成，每级要塞再加 30%。"));
  } else side.append(el("p", "hint", "交战区：不属于任何一方，任何国家都可以直接进入占领。"));
}

// the nearest province of the player's own (through his own land and sea ways) that borders an enemy
function nearestFront(from) {
  const st = G.state, b = G.board, p = P();
  const front = (k) => R.neighbours(b, k).some((j) => R.isEnemy(st, p, st.owner[j]));
  const seen = new Set([from]); let q = [from];
  while (q.length) {
    const next = [];
    for (const k of q) { if (front(k)) return k; for (const [j] of R.exits(b, k)) if (!seen.has(j) && st.owner[j] === p) { seen.add(j); next.push(j); } }
    q = next;
  }
  return -1;
}

function showCountry(c) { G.view = "country"; G.viewCountry = c; G.move = null; G.moveMode = false; markSelection(); renderSide(); }

function renderCountry(side, c) {
  const st = G.state, b = G.board, p = P(), C = st.countries[c], t = R.tally(st, b);
  const top = el("div", "row"); top.style.justifyContent = "space-between";
  top.append(flagName(c), button("×", () => { G.view = "overview"; G.viewCountry = -1; markSelection(); renderSide(); }, "close"));
  side.append(top);
  const chips = el("div", "row"); chips.append(relChip(c)); if (c !== p) chips.append(el("span", "chip", `关系 ${R.relation(st, p, c)}`));
  if (!C.alive) chips.append(el("span", "chip war", "已灭亡"));
  side.append(chips);
  side.append(kv([["首都", C.capital >= 0 && st.owner[C.capital] === c ? b.names[C.capital] : "—"], ["人口", fmt(t.pop[c])], ["省份", t.held[c].length],
    ["收入", `${num(t.income[c])} 金 / 回合`], ["军队", `${num(t.army[c])} 师`], ["战力", `${R.quality(st, c).toFixed(2)}${C.tech ? `（科技 ${C.tech} 级）` : ""}`],
    ["金币", c === p ? num(C.gold) : null]]));
  if (!C.alive) return;
  const acts = el("div", "row");
  if (c === p) {
    const cost = R.techCost(st, b, p);
    acts.append(button(`研究军事科技（${num(cost)} 金）`, () => { if (R.research(st, b, p)) { toast(`科技升至 ${C.tech} 级：战力 ${R.quality(st, p).toFixed(2)}`); update(); } },
      "btn primary", C.gold < cost, `每级 +${R.RULES.techStep * 100}% 军队战力`));
  } else {
    const war = R.atWar(st, p, c), ally = R.allied(st, p, c), truce = (st.truce.get(R.pair(p, c)) || 0) > st.turn;
    if (war) {
      const ws = R.warScore(st, b, p, c);
      acts.append(button(`求和（战争分数 ${(ws * 100).toFixed(0)}）`, () => {
        if (R.acceptsPeace(st, b, c, p)) { R.makePeace(st, p, c); toast(`${C.name} 接受了和平：双方保持现有控制区`); }
        else toast(`${C.name} 拒绝和谈。对方战况越不利越愿意议和，开局时已在进行的战争更难结束。`);
        update();
      }, "btn"));
    } else {
      acts.append(button("宣战", () => confirmWar(c), "btn danger", truce, truce ? "停战期内不能宣战" : ""));
      if (ally) acts.append(button("解除同盟", () => { R.breakAlliance(st, p, c); update(); }));
      else acts.append(button("提议结盟", () => {
        if (R.proposeAlliance(st, b, p, c)) toast(`${C.name} 同意结盟`); else toast(`${C.name} 拒绝结盟（关系需达 70，或达 40 且有共同敌人）`);
        update();
      }));
      acts.append(button(`改善关系（${R.relCost} 金）`, () => { if (R.improveRelations(st, p, c)) update(); }, "btn", st.countries[p].gold < R.relCost));
    }
  }
  side.append(acts);
  const foes = R.enemiesOf(st, c).filter((x) => st.countries[x].alive), friends = R.alliesOf(st, c);
  if (foes.length) { const s = el("div", "stack"); s.append(el("h3", null, `交战（${foes.length}）`)); s.append(countryList(foes, c === p ? (x) => `战争分数 ${(R.warScore(st, b, p, x) * 100).toFixed(0)}` : null)); side.append(s); }
  if (friends.length) { const s = el("div", "stack"); s.append(el("h3", null, `同盟（${friends.length}）`)); s.append(countryList(friends)); side.append(s); }
  side.append(button("定位到首都", () => flyToCountry(c)));
}
function confirmWar(c) {
  const st = G.state, p = P(), C = st.countries[c];
  const joins = R.alliesOf(st, c).filter((x) => x !== p && !R.atWar(st, x, p) && !R.allied(st, x, p));
  modal(`向 ${C.name} 宣战？`, (card) => {
    card.append(el("p", "lede", joins.length ? `对方的盟友会参战：${joins.map((x) => shortName(st.countries[x].name)).join("、")}。` : "对方没有会参战的盟友。"));
    const mine = R.alliesOf(st, p).filter((x) => R.relation(st, x, p) > 50);
    if (mine.length) card.append(el("p", "hint", `你的盟友中关系在 50 以上的（${mine.map((x) => shortName(st.countries[x].name)).slice(0, 10).join("、")}）有六成可能随你参战。`));
    const row = el("div", "row");
    row.append(button("宣战", () => { R.declareWar(st, p, c); closeModal(); update(); }, "btn primary"), button("取消", closeModal));
    card.append(row);
  });
}

// ------------------------------------------------------------------ orders
function beginMove(from, to) {
  const st = G.state, b = G.board, p = P();
  if (st.owner[from] !== p || st.army[from] <= 0 || from === to) return;
  G.move = { from, to }; G.moveMode = false; renderSide(); drawSymbols();
}
function renderMove(side) {
  const st = G.state, b = G.board, p = P(); const { from, to } = G.move; const o = st.owner[to];
  side.append(el("h2", null, "调兵"));
  side.append(el("p", "lede", `${b.names[from]} → ${b.names[to]}`));
  const path = R.findPath(st, b, p, from, to);
  const cancel = () => { G.move = null; renderSide(); drawSymbols(); };
  if (!path) {
    if (o !== p && !R.atWar(st, p, o)) {
      side.append(el("p", "lede", `${b.names[to]} 属于 ${st.countries[o].name}，与之未处于战争状态，不能进入。`));
      const row = el("div", "row"); row.append(button(`查看 ${shortName(st.countries[o].name)}`, () => { G.move = null; showCountry(o); }), button("取消", cancel));
      side.append(row);
    } else {
      side.append(el("p", "lede", "无法到达：行军只能经过本国领土（陆路、海峡或港口之间的海路），最后一步进入目标。"));
      side.append(button("取消", cancel));
    }
    return;
  }
  const steps = path.length - 1; const enemy = R.isEnemy(st, p, o);
  const kinds = []; for (let i = 0; i + 1 < path.length; i++) kinds.push(b.adj[path[i]].includes(path[i + 1]) ? 0 : b.sea[path[i]].includes(path[i + 1]) ? 1 : 2);
  const last = kinds[kinds.length - 1];
  side.append(kv([["路程", `${steps} 步${kinds.includes(2) ? "（含海路）" : kinds.includes(1) ? "（含海峡）" : ""}`],
    ["预计", steps <= R.RULES.speed && !kinds.slice(0, -1).some((x) => x) ? "本回合抵达" : `约 ${Math.max(1, Math.ceil(steps / R.RULES.speed)) + kinds.filter((x) => x).length} 回合`],
    ["目标", `${st.countries[o].name}${enemy ? ` · 守军 ${st.army[to]} 师` : ""}`]]));
  const max = st.army[from];
  const sl = el("div", "slider"); const r = el("input"); r.type = "range"; r.min = 1; r.max = max; r.value = max; const out = el("output");
  const odds = el("p", "hint");
  const set = () => {
    out.textContent = `${r.value} 师`;
    if (!enemy) { odds.textContent = ""; return; }
    const A = +r.value * R.quality(st, p) * R.attackFactor(last);
    const D = st.army[to] * (st.countries[o].contested ? 0.5 : R.quality(st, o)) * (R.RULES.defence + R.RULES.fortStep * st.fort[to]);
    odds.textContent = !st.army[to] ? "守军为零：抵达即占领。" : `进攻力 ${A.toFixed(0)} 对 防守力 ${D.toFixed(0)}（含地利${st.fort[to] ? "与要塞" : ""}${last ? "；登陆作战打折" : ""}）——${A > D * 1.1 ? "胜算较大" : A > D * 0.9 ? "胜负难料" : "胜算很小"}。`;
  };
  r.oninput = set; set(); sl.append(r, out); side.append(sl, odds);
  if (kinds.includes(2)) side.append(el("p", "hint", `海运运力每回合 ${R.shipping(R.income(st, b, p))} 个师（2 + 收入的十分之一），超出的部分留在港口下回合再走。`));
  const row = el("div", "row");
  row.append(button(enemy ? "下令进攻" : "下令调动", () => {
    const x = R.order(st, b, p, from, to, +r.value); G.move = null;
    if (x) toast(`已下令：${x.n} 师 ${b.names[from]} → ${b.names[to]}（结束回合时执行）`);
    renderSide(); drawSymbols();
  }, "btn primary"), button("取消", cancel));
  side.append(row);
}

// ------------------------------------------------------------------ selection
function select(k, fly) {
  G.sel = k; G.view = k >= 0 ? "province" : "overview"; G.viewCountry = -1; G.move = null; G.moveMode = false;
  markSelection(); renderSide();
  if (fly && k >= 0) map.flyTo({ center: G.board.labels[k], zoom: Math.max(map.getZoom(), 4.5), duration: 700 });
}
function onMapClick(k) {
  if (G.phase === "start") { if (k >= 0 && !G.state.countries[G.state.owner[k]].contested) pickCountry(G.state.owner[k], false); return; }
  if (G.moveMode && G.sel >= 0 && k >= 0) return beginMove(G.sel, k);
  select(k);
}
function onRightClick(k) {
  if (G.phase !== "play" || G.sel < 0 || k < 0) return;
  const st = G.state; if (st.owner[G.sel] === P() && st.army[G.sel] > 0) beginMove(G.sel, k);
}
function update() { refresh(); renderSide(); renderLog(); autosave(); }

// ------------------------------------------------------------------ the turn
async function endTurn() {
  if (G.busy || G.phase !== "play" || G.state.over) return;
  G.busy = true; $("bEnd").disabled = true; $("bEnd").textContent = "结算中…";
  await new Promise((r) => setTimeout(r, 20));
  const st = G.state, b = G.board, p = P();
  const before = Int16Array.from(st.owner), logFrom = st.log.length;
  try { R.endTurn(st, b, aiTurn); } catch (e) { console.error(e); toast("结算出错：" + e.message); }
  let won = 0, lost = 0; for (let k = 0; k < b.P; k++) { if (before[k] !== p && st.owner[k] === p) won++; else if (before[k] === p && st.owner[k] !== p) lost++; }
  G.move = null; G.moveMode = false;
  if (G.view === "country" && !st.countries[G.viewCountry].alive) G.view = "overview";
  G.busy = false; $("bEnd").textContent = "结束回合";
  update();
  const news = st.log.slice(logFrom).filter((l) => l.who.includes(p) && /宣战|和约|投降|灭亡|同盟/.test(l.text)).map((l) => l.text);
  toast([`${st.year} 年 ${st.month} 月`, won ? `占领 ${won} 省` : null, lost ? `失去 ${lost} 省` : null, ...news.slice(0, 2)].filter(Boolean).join(" · "));
  if (st.over) gameOver(st.over.won);
}
function gameOver(won) {
  store.del(SAVE);
  const st = G.state;
  modal(won ? "胜利！" : "国家灭亡", (card) => {
    card.append(el("p", "lede", won ? `${st.countries[P()].name} 控制了世界一半以上的人口（${st.year} 年 ${st.month} 月，第 ${st.turn} 回合）。` : `${st.countries[P()].name} 已经灭亡。`));
    const row = el("div", "row");
    if (won) row.append(button("继续游戏", () => { st.over = null; st.won = true; closeModal(); hud(); }, "btn"));
    row.append(button("重新开始", () => location.reload(), "btn primary"));
    card.append(row);
  });
}

// ------------------------------------------------------------------ log, toast, modals
function renderLog() {
  const st = G.state, p = P(); const ul = $("log"); ul.replaceChildren();
  const rows = st.log.filter((l) => l.who.includes(p) || /宣战|投降|和约|灭亡/.test(l.text)).slice(-60).reverse();
  for (const l of rows) { const li = el("li", l.who.includes(p) ? "mine" : ""); li.append(el("span", "t", `T${l.turn + 1}`), document.createTextNode(l.text)); ul.append(li); }
}
let toastTimer = 0;
function toast(text) { const t = $("toast"); t.textContent = text; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 4200); }
function modal(title, fill) {
  const card = $("card"); card.replaceChildren();
  const h = el("header"); h.append(el("h2", null, title), button("×", closeModal, "close")); card.append(h);
  fill(card); $("modal").hidden = false;
}
function closeModal() { $("modal").hidden = true; }

function showDiplomacy() {
  const st = G.state, b = G.board, p = P(), t = R.tally(st, b);
  modal("外交", (card) => {
    const q = el("input", "search"); q.type = "search"; q.placeholder = "查找国家";
    const table = el("table", "t"); card.append(q, table);
    const fill = () => {
      table.replaceChildren();
      const hr = el("tr"); for (const h of ["国家", "关系", "状态", "人口", "军队", ""]) hr.append(el("th", h === "人口" || h === "军队" || h === "关系" ? "n" : "", h)); table.append(hr);
      const rows = st.countries.filter((c) => c.alive && !c.contested && c.id !== p && (!q.value || c.name.includes(q.value.trim())))
        .sort((a, z) => (relKind(z.id) === "war") - (relKind(a.id) === "war") || (relKind(z.id) === "ally") - (relKind(a.id) === "ally") || t.pop[z.id] - t.pop[a.id]).slice(0, 120);
      for (const c of rows) {
        const tr = el("tr"); const td = el("td"); td.append(flagName(c.id, () => { closeModal(); showCountry(c.id); })); tr.append(td);
        tr.append(el("td", "n", String(R.relation(st, p, c.id)))); const s = el("td"); s.append(relChip(c.id)); tr.append(s);
        tr.append(el("td", "n", fmt(t.pop[c.id])), el("td", "n", num(t.army[c.id])));
        const a = el("td"); a.append(button("详情", () => { closeModal(); showCountry(c.id); })); tr.append(a);
        table.append(tr);
      }
    };
    q.oninput = fill; fill();
  });
}
function showRanking() {
  const st = G.state, b = G.board, p = P(), t = R.tally(st, b); const world = t.pop.reduce((a, z) => a + z, 0);
  modal("列国排行", (card) => {
    const table = el("table", "t");
    const hr = el("tr"); for (const h of ["#", "国家", "人口", "占世界", "省份", "收入", "军队", "战力"]) hr.append(el("th", h === "国家" || h === "#" ? "" : "n", h)); table.append(hr);
    const rows = st.countries.filter((c) => c.alive && !c.contested).sort((a, z) => t.pop[z.id] - t.pop[a.id]);
    let i = 0;
    for (const c of rows) {
      i++; if (i > 30 && c.id !== p) continue;
      const tr = el("tr", c.id === p ? "mine" : ""); tr.append(el("td", null, String(i)));
      const td = el("td"); td.append(flagName(c.id, () => { closeModal(); showCountry(c.id); })); tr.append(td);
      tr.append(el("td", "n", fmt(t.pop[c.id])), el("td", "n", (t.pop[c.id] / world * 100).toFixed(1) + "%"), el("td", "n", String(t.held[c.id].length)),
        el("td", "n", num(t.income[c.id])), el("td", "n", num(t.army[c.id])), el("td", "n", R.quality(st, c.id).toFixed(2)));
      table.append(tr);
    }
    card.append(el("p", "hint", "控制世界一半人口即获胜。"), table);
  });
}
function showHelp() {
  modal("玩法", (card) => {
    const items = [
      ["地图", "每个省份就是历史地图该断面上的一块省级区划（被国界或战线切开的省份按块计）。开局的控制者、人口、阵营都取自当日的历史数据；人均 GDP 取自 1900–2000 逐年数据库（2026 年沿用 2000 年的数值）。"],
      ["回合", "一回合为一个月。你下达的命令在点击“结束回合”时与电脑国家的命令一起执行，随后结算收入、维持费和人力。"],
      ["经济", `省份税收 = 人口 × 人均 GDP × ${R.RULES.income}/10 亿 ×（1 + 工业城市 12%、港口 6%）×（1 + 每级经济 ${R.RULES.econStep * 100}%）；占领的非核心省份只得一半。每个师每回合维持费 ${R.RULES.upkeep} 金，金币为负时军队会逐步解散。`],
      ["人力", "每回合按本国核心省份人口补充（占领区按四分之一计），最多储存 12 回合。招募一个师消耗 3 金和 1 人力。"],
      ["军队", "选中本国有驻军的省份，右键点击目标省份：本国省份即调动（每回合最多走 2 个省，海峡或海路一次走完一回合），相邻的敌国省份即进攻。行军只能经过本国领土。"],
      ["战斗", `进攻力 = 师数 × 战力；防守力 = 师数 × 战力 ×（${R.RULES.defence} + 每级要塞 ${R.RULES.fortStep}）。进攻方大于防守方则攻占，守军余部退往相邻的本国省份。越过海峡进攻打 ${R.RULES.straitAttack * 10} 折，港口之间的海路登陆打 ${R.RULES.seaAttack * 10} 折，海运运力每回合 2 + 收入的十分之一个师。战力由人均 GDP 决定，科技每级再加 10%。`],
      ["首都", "首都失守后迁往人口最多的省份；若此时只剩不到开局四分之一的人口，该国投降，余下领土归攻占首都的国家。"],
      ["外交", "可以宣战、求和、结盟、解除同盟、花金币改善关系。被宣战的国家其盟友会自动参战。和约按现有控制区划界，之后 12 回合停战。对方战况越不利越愿意议和；开局时已在进行的战争（如二战）更难结束。"],
      ["胜利", "控制世界一半人口即获胜；国家灭亡则失败。游戏每回合自动存档在本机浏览器。"],
      ["快捷键", "回车：结束回合；Esc：取消选择。"],
    ];
    for (const [h, t] of items) { const s = el("div", "stack"); s.append(el("h3", null, h), el("p", "lede", t)); card.append(s); }
  });
}
function showMenu() {
  modal("菜单", (card) => {
    const col = el("div", "stack");
    col.append(button("保存游戏", () => { toast(store.set(SAVE, R.save(G.state)) ? "已保存在本机浏览器" : "保存失败（浏览器禁止了本地存储）"); closeModal(); }));
    col.append(button("查看本断面的历史地图", () => { location.href = `../ww2/maps/#${G.snap}/control`; }));
    col.append(button("重新选择断面与国家", () => { if (confirm("放弃当前游戏、重新开始？（存档会保留，直到新游戏开始）")) location.reload(); }));
    col.append(button("删除存档", () => { store.del(SAVE); toast("存档已删除"); closeModal(); }, "btn danger"));
    col.append(button("返回首页", () => { location.href = "../index.html"; }));
    card.append(col);
  });
}

// ------------------------------------------------------------------ wiring
function wire() {
  const hit = (e) => { const f = map.queryRenderedFeatures(e.point, { layers: ["prov-fill"] })[0]; return f ? f.id : -1; };
  map.on("click", (e) => onMapClick(hit(e)));
  map.on("contextmenu", (e) => { e.preventDefault && e.preventDefault(); onRightClick(hit(e)); });
  map.on("mousemove", "prov-fill", (e) => {
    const f = e.features[0]; if (!f) return; map.getCanvas().style.cursor = G.moveMode ? "crosshair" : "pointer";
    if (G.hover !== null && G.hover !== f.id) map.setFeatureState({ source: "prov", id: G.hover }, { hov: false });
    if (G.hover !== f.id) { G.hover = f.id; map.setFeatureState({ source: "prov", id: f.id }, { hov: true }); }
    const st = G.state, b = G.board, k = f.id, o = st.owner[k]; const tip = $("tip"); tip.replaceChildren();
    tip.append(el("b", null, b.names[k]), el("div", null, `${st.countries[o].name}${st.army[k] ? ` · ${st.army[k]} 师` : ""}`));
    if (G.phase === "play" && G.sel >= 0 && st.owner[G.sel] === P() && st.army[G.sel] > 0 && k !== G.sel) tip.append(el("div", "hint", R.isEnemy(st, P(), o) ? "右键：进攻" : o === P() ? "右键：调兵到此" : ""));
    const r = map.getContainer().getBoundingClientRect();
    tip.style.left = Math.min(e.point.x + 14, r.width - 270) + "px"; tip.style.top = (e.point.y + 14) + "px"; tip.hidden = false;
  });
  map.on("mouseleave", "prov-fill", () => { map.getCanvas().style.cursor = ""; $("tip").hidden = true;
    if (G.hover !== null) map.setFeatureState({ source: "prov", id: G.hover }, { hov: false }); G.hover = null; });
  $("bEnd").onclick = endTurn;
  $("bDiplo").onclick = showDiplomacy; $("bRank").onclick = showRanking; $("bHelp").onclick = showHelp; $("bMenu").onclick = showMenu;
  $("me").onclick = () => showCountry(P());
  $("modal").onclick = (e) => { if (e.target === $("modal")) closeModal(); };
  $("logToggle").onclick = () => { const c = $("logbox").classList.toggle("collapsed"); $("logToggle").textContent = c ? "+" : "–"; };
  for (const b of document.querySelectorAll("[data-mode]")) b.onclick = () => {
    G.mode = b.dataset.mode; for (const x of document.querySelectorAll("[data-mode]")) x.setAttribute("aria-pressed", String(x === b)); paint();
  };
  document.addEventListener("keydown", (e) => {
    if (e.target.closest && e.target.closest("input, textarea, select")) return;
    if (e.key === "Escape") { if (!$("modal").hidden) closeModal(); else if (G.move || G.moveMode) { G.move = null; G.moveMode = false; renderSide(); drawSymbols(); } else if (G.phase === "play") select(-1); }
    if (e.key === "Enter" && $("modal").hidden && G.phase === "play") { e.preventDefault(); endTurn(); }
  });
}

async function boot() {
  registerProtocols();
  const [index, eco] = await Promise.all([md.index(), fetch("economy.json").then((r) => r.json()), md.loadAdmin()]);
  G.index = index; G.eco = eco;
  await initMap(); addLayers(); wire();
  md.hydro().then((h) => map.getSource("hydro").setData(h)).catch(() => {});
  const start = decodeURIComponent((location.hash || "").slice(1));
  const snap = index.snapshots.some((s) => s.snapshot === start) ? start : "1939-09-01";
  await loadScenario(snap);
  renderSide();
  // a link to another date (game/#1914-08-04) while choosing
  window.addEventListener("hashchange", async () => {
    const s = decodeURIComponent(location.hash.slice(1));
    if (G.phase === "start" && s !== G.snap && index.snapshots.some((x) => x.snapshot === s)) { await loadScenario(s); renderSide(); }
  });
}
function fail(e) {
  console.error(e); const m = e && e.message ? e.message : String(e);
  $("loading").hidden = false;
  $("loading").textContent = "载入失败：" + m + (/ 404|fetch/i.test(m) ? "。地图数据需先用 python3 scripts/data_release.py fetch ww2-maps-data.tar.gz 下载，并通过本地网页服务器打开（见 README）。" : "");
}
if (window.maplibregl) boot().catch(fail);
else {
  const s = document.createElement("script"); s.src = "https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/4.7.1/maplibre-gl.js";
  s.onload = () => boot().catch(fail); s.onerror = () => fail(new Error("MapLibre 载入失败")); document.head.append(s);
}
