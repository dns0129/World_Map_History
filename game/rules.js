// The rules of the game: a scenario from a map date, the economy, armies and battles, diplomacy and the turn.
// Pure logic without the page, so that tests/game can play whole games in Node.
//
// One province of the game is one feature of the map date: a province of the time, or a piece of one cut by a
// border or front line. It starts with the date's actual controller, population and (from game/economy.json) GDP
// per capita; its core owner is the country the province belongs to de jure (sovereign_name_zh), where that
// country is on the map, else its controller. One army unit is a division. One turn is a month.

import { labelPoint, bbox, locate } from "./geometry.js";

export const RULES = {
  income: 0.1,           // gold per turn per billion dollars of annual GDP
  occupiedIncome: 0.5,   // share of a province's income its controller draws when it is not his core
  econStep: 0.25,        // income added by each level of investment
  econMax: 5,
  manpower: 1e-7,        // divisions per turn per inhabitant of the core provinces
  manpowerCap: 12,       // turns of manpower that can be stored
  recruitGold: 3,        // a division: gold and one division of manpower
  upkeep: 0.15,          // gold per division per turn
  fortMax: 3,
  fortStep: 0.3,         // defence added by each fort level
  defence: 1.25,         // the defender's advantage
  straitAttack: 0.7,     // strength of an attack across a strait
  seaAttack: 0.5,        // strength of a landing from a sea lane
  laneRange: 55,         // the longest sea lane between two ports (degrees of arc, about 6100 km)
  shipping: 0.1,         // divisions a country can carry over the sea lanes per turn: 2 plus this times its income
  speed: 2,              // provinces an army crosses per turn in its own country
  techStep: 0.1,         // quality added by each level of technology
  truce: 12,             // turns after a peace before the two can fight again
  capitulate: 0.25,      // a country that has lost its capital and holds less than this share of its people gives up
};

// ------------------------------------------------------------------ random numbers (saved with the game)
export function rng(state) {
  let t = (state.seed = (state.seed + 0x6d2b79f5) >>> 0);
  t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}

export const pair = (a, b) => a < b ? a * 4096 + b : b * 4096 + a;

// ------------------------------------------------------------------ the wars of each date
// Opposite camps (bloc 0 and 1 of the map) fight where the date is in a war; before Pearl Harbor the war in China
// and the war in Europe are separate, and Japan and the Soviet Union keep their neutrality pact until August 1945.
// Other wars are listed by the countries' map keys.
const BLOC_WAR = (s) => s === "1900-08-14" || (s >= "1914-08-04" && s <= "1917-04-06") || (s >= "1937-07-07" && s <= "1945-05-01");
const EXTRA_WARS = [
  { from: "1934-10-16", to: "1934-10-16", a: ["710"], b: ["-2"] },                       // the Long March
  { from: "1946-06-26", to: "1949-10-01", a: ["710"], b: ["-2", "PRC"] },                // the civil war in China
  { from: "1947-08-15", to: "1949-10-01", a: ["210"], b: ["850"] },                      // Indonesian war of independence
  { from: "1947-08-15", to: "1949-10-01", a: ["220"], b: ["816"] },                      // the Indochina war
  { from: "2026", to: "2026", a: ["M:RUS"], b: ["M:UKR"] },                              // Russia and Ukraine
];
const SOVIET = new Set(["365", "712"]);  // the Soviet Union and Mongolia
const NO_ALLIANCES = new Set(["1934-10-16"]);  // the 1934 camps are League members and non-members, no alliances

export function initialDiplomacy(snap, countries) {
  const wars = [], allies = [];
  const real = countries.filter((c) => !c.contested);
  const asian = (c) => c.capLon > 60 && c.capLat > -12;
  for (const a of real) for (const b of real) {
    if (a.id >= b.id) continue;
    if (a.bloc <= 1 && a.bloc === b.bloc && !NO_ALLIANCES.has(snap)) allies.push([a.id, b.id]);
    if (!BLOC_WAR(snap) || a.bloc > 1 || b.bloc > 1 || a.bloc === b.bloc) continue;
    if (snap >= "1937" && snap < "1941-12-07" && asian(a) !== asian(b)) continue;
    if (snap >= "1937" && ((SOVIET.has(a.key) && asian(b)) || (SOVIET.has(b.key) && asian(a)))) continue;
    wars.push([a.id, b.id]);
  }
  const byKey = new Map(real.map((c) => [c.key, c.id]));
  for (const w of EXTRA_WARS) {
    if (snap < w.from || snap > w.to) continue;
    for (const ka of w.a) for (const kb of w.b) if (byKey.has(ka) && byKey.has(kb)) wars.push([byKey.get(ka), byKey.get(kb)]);
  }
  return { wars, allies };
}

// ------------------------------------------------------------------ the scenario
const L = (sd, c, k) => sd.luts[c][sd.rows[c][k]];
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function gdpPerCapita(eco, snap) {
  const year = snap === "2026" ? 2000 : +snap.slice(0, 4);
  let yi = 0; for (let i = 0; i < eco.years.length; i++) if (eco.years[i] <= year) yi = i;
  const near = (arr) => { if (!arr) return 0; for (let d = 0; d < arr.length; d++) for (const i of [yi - d, yi + d]) if (arr[i] > 0) return arr[i]; return 0; };
  return { world: eco.world[yi], unit: (name) => near(eco.unit[name]), iso: (code) => near(eco.iso[code]) };
}

// board: the static map of the game (graph, labels, names); state: everything that changes and is saved
export function buildBoard(sd, geoms, graph, names, eco) {
  const P = sd.feature.length;
  const labels = geoms.map(labelPoint), boxes = geoms.map(bbox);
  const g = gdpPerCapita(eco, sd.snapshot);
  const gdppc = new Float64Array(P);
  for (let k = 0; k < P; k++) {
    const key = sd.countries[sd.country[k]][0];
    gdppc[k] = g.unit(L(sd, "unit_name_zh", k)) || g.unit(L(sd, "sovereign_name_zh", k))
      || (key.startsWith("M:") ? g.iso(key.slice(2)) : 0) || g.world * 0.6;
  }
  // cities: capitals by the country named in their role ("首都：德国"), ports and industry for the income
  const cityOf = new Int32Array((sd.cities || []).length).fill(-1);
  const bonus = new Float64Array(P), capitals = [], cityList = [];
  const isPort = new Uint8Array(P);
  (sd.cities || []).forEach(([n, x, y, f, , role], i) => {
    const k = locate(x, y, geoms, boxes, labels, 0.6); cityOf[i] = k; if (k < 0) return;
    cityList.push({ n, x, y, f, k });
    if (f & 4) bonus[k] += 0.12;
    if (f & 8) { bonus[k] += 0.06; isPort[k] = 1; }
    const m = /^首都：(.+)$/.exec(role || ""); if (m) capitals.push([m[1], k]);
  });
  const ports = []; for (let k = 0; k < P; k++) if (isPort[k]) ports.push(k);
  // sea lanes: between ports up to RULES.laneRange apart (great circle)
  const rad = Math.PI / 180, lanes = Array.from({ length: P }, () => []);
  for (const a of ports) for (const b of ports) {
    if (a >= b) continue;
    const [x1, y1] = labels[a], [x2, y2] = labels[b];
    const c = Math.sin(y1 * rad) * Math.sin(y2 * rad) + Math.cos(y1 * rad) * Math.cos(y2 * rad) * Math.cos((x2 - x1) * rad);
    if (Math.acos(Math.min(1, Math.max(-1, c))) / rad <= RULES.laneRange) { lanes[a].push(b); lanes[b].push(a); }
  }
  return { snap: sd.snapshot, title: sd.title_zh, P, adj: graph.adj, sea: graph.sea, lanes, labels, boxes, names, gdppc, bonus, isPort, ports,
    pop: Float64Array.from(sd.pop), area: Float64Array.from(sd.area), cities: cityList, capitals, worldGdppc: g.world };
}

export function newGame(sd, board, opts = {}) {
  const P = board.P;
  const countries = sd.countries.map((c, id) => ({ id, key: c[0], name: c[1], en: c[2], color: c[3], bloc: c[4],
    contested: c[0] === "-20", alive: true, gold: 0, manpower: 0, tech: 0, capital: -1, startPop: 0, q0: 1, capLon: 0, capLat: 0 }));
  const byName = new Map(countries.map((c) => [c.name, c.id]));
  const owner = Int16Array.from(sd.country), core = new Int16Array(P);
  for (let k = 0; k < P; k++) { const s = byName.get(L(sd, "sovereign_name_zh", k)); core[k] = s != null && !countries[s].contested ? s : owner[k]; }
  const state = { snap: sd.snapshot, turn: 0, year: 0, month: 0, seed: opts.seed ?? 12345, player: opts.player ?? -1,
    aggression: opts.aggression ?? 1, countries, owner, core, army: new Int32Array(P), econ: new Uint8Array(P), fort: new Uint8Array(P),
    wars: new Map(), allies: new Set(), rel: new Map(), truce: new Map(), orders: [], log: [], over: null };
  const [y, m] = sd.snapshot === "2026" ? [2026, 1] : sd.snapshot.split("-").map(Number);
  state.year = y; state.month = m;
  // capitals: a capital city in the country named as the country, else the most populous of the capitals in it not
  // named for another country ("首都：德国" for 德意志帝国); else its most populous province
  const held = countries.map(() => []);
  for (let k = 0; k < P; k++) held[owner[k]].push(k);
  const short = (n) => n.split(/[（(]/)[0];
  for (const c of countries) {
    const inside = board.capitals.filter(([, k]) => owner[k] === c.id);
    const named = (f) => inside.find(([n]) => f(short(n), short(c.name)));
    let cap = (named((n, m) => n === m) || named((n, m) => m.includes(n) || n.includes(m)) || [])[1];
    if (cap == null) cap = inside.filter(([n]) => !byName.has(n)).map(([, k]) => k).reduce((b, k) => b == null || board.pop[k] > board.pop[b] ? k : b, null);
    if (cap == null) cap = held[c.id].reduce((b, k) => b < 0 || board.pop[k] > board.pop[b] ? k : b, -1);
    c.capital = cap; c.startCapital = cap;
    if (cap >= 0) [c.capLon, c.capLat] = board.labels[cap];
  }
  const d = initialDiplomacy(state.snap, countries);
  for (const [a, b] of d.wars) state.wars.set(pair(a, b), { since: 0, start: true });
  for (const [a, b] of d.allies) state.allies.add(pair(a, b));
  for (const a of countries) for (const b of countries) {
    if (a.id >= b.id) continue;
    const r = state.wars.has(pair(a.id, b.id)) ? -80 : a.bloc <= 1 && b.bloc <= 1 ? (a.bloc === b.bloc ? 60 : -50) : 0;
    if (r) state.rel.set(pair(a.id, b.id), r);
  }
  // quality of the army: GDP per capita against the world's, to the power 0.4
  for (const c of countries) {
    let gdp = 0, pop = 0;
    for (const k of held[c.id]) if (core[k] === c.id) { gdp += board.pop[k] * board.gdppc[k]; pop += board.pop[k]; }
    if (!pop) for (const k of held[c.id]) { gdp += board.pop[k] * board.gdppc[k]; pop += board.pop[k]; }
    c.q0 = pop ? clamp((gdp / pop / board.worldGdppc) ** 0.4, 0.6, 1.8) : 1;
    c.startPop = held[c.id].reduce((s, k) => s + board.pop[k], 0);
    if (!held[c.id].length) c.alive = false;
  }
  // the standing armies: more in a country at war, placed along its fronts and at the capital
  for (const c of countries) {
    if (c.contested || !c.alive) continue;
    let gdp = 0, pop = 0; for (const k of held[c.id]) { gdp += board.pop[k] * board.gdppc[k]; pop += board.pop[k]; }
    const war = atWarAny(state, c.id);
    c.base = Math.round(gdp / 1e9 / 4 + pop / 3e6);
    const total = Math.round(c.base * (war ? 1 : 0.35));
    const w = held[c.id].map((k) => (Math.sqrt(board.pop[k] / 1e4) + 1) * (k === c.capital ? 3 : 1)
      * (neighbours(board, k).some((j) => isEnemy(state, c.id, owner[j])) ? 5 : 1));
    spread(state, held[c.id], w, total);
    c.gold = Math.round(income(state, board, c.id) * 6);
    c.manpower = Math.round(manpowerGain(state, board, c.id) * 6);
  }
  return state;
}

function spread(state, ks, w, total) {
  const sum = w.reduce((a, b) => a + b, 0); if (!sum || total <= 0) return;
  const exact = w.map((v) => v / sum * total); const base = exact.map(Math.floor);
  let left = total - base.reduce((a, b) => a + b, 0);
  const order = exact.map((v, i) => [v - base[i], i]).sort((a, b) => b[0] - a[0]);
  for (let i = 0; i < left; i++) base[order[i % order.length][1]]++;
  ks.forEach((k, i) => { state.army[k] += base[i]; });
}

// ------------------------------------------------------------------ relations
export const atWar = (state, a, b) => a !== b && (state.countries[a].contested || state.countries[b].contested || state.wars.has(pair(a, b)));
export const allied = (state, a, b) => a !== b && state.allies.has(pair(a, b));
export const relation = (state, a, b) => state.rel.get(pair(a, b)) || 0;
export function addRelation(state, a, b, d) { state.rel.set(pair(a, b), clamp(relation(state, a, b) + d, -100, 100)); }
export const isEnemy = (state, a, b) => a !== b && atWar(state, a, b);
export function atWarAny(state, c) { for (const key of state.wars.keys()) if (Math.floor(key / 4096) === c || key % 4096 === c) return true; return false; }
export function enemiesOf(state, c) {
  const out = []; for (const key of state.wars.keys()) { const a = Math.floor(key / 4096), b = key % 4096; if (a === c) out.push(b); else if (b === c) out.push(a); }
  return out;
}
export function alliesOf(state, c) {
  const out = []; for (const key of state.allies) { const a = Math.floor(key / 4096), b = key % 4096; if (a === c) out.push(b); else if (b === c) out.push(a); }
  return out.filter((x) => state.countries[x].alive);
}
export const neighbours = (board, k) => [...board.adj[k], ...board.sea[k]];
// every way out of a province: [province, kind] with kind 0 land, 1 strait, 2 sea lane between ports
export function exits(board, k) {
  const out = []; for (const j of board.adj[k]) out.push([j, 0]); for (const j of board.sea[k]) out.push([j, 1]);
  for (const j of board.lanes[k]) out.push([j, 2]);
  return out;
}

// ------------------------------------------------------------------ economy
export function provinceIncome(state, board, k) {
  const c = state.owner[k];
  const base = board.pop[k] * board.gdppc[k] / 1e9 * RULES.income * (1 + board.bonus[k]) * (1 + RULES.econStep * state.econ[k]);
  return state.core[k] === c ? base : base * RULES.occupiedIncome;
}
export function income(state, board, c) {
  let s = 0; for (let k = 0; k < board.P; k++) if (state.owner[k] === c) s += provinceIncome(state, board, k);
  return s;
}
export function armyOf(state, c) { let s = 0; for (let k = 0; k < state.owner.length; k++) if (state.owner[k] === c) s += state.army[k]; return s; }
export function manpowerGain(state, board, c) {
  let s = 0; for (let k = 0; k < board.P; k++) if (state.owner[k] === c) s += board.pop[k] * (state.core[k] === c ? 1 : 0.25);
  return s * RULES.manpower;
}
export const quality = (state, c) => state.countries[c].q0 * (1 + RULES.techStep * state.countries[c].tech);
export const investCost = (state, board, k) => Math.round(10 + 15 * provinceIncome(state, board, k) * (1 + state.econ[k]));
export const fortCost = (state, k) => 20 * (state.fort[k] + 1);
export const techCost = (state, board, c) => Math.round((state.countries[c].tech + 1) * Math.max(30, 10 * income(state, board, c)));
export const relCost = 10;

export function recruit(state, board, c, k, n) {
  const C = state.countries[c];
  n = Math.min(n, Math.floor(C.gold / RULES.recruitGold), Math.floor(C.manpower));
  if (state.owner[k] !== c || n <= 0) return 0;
  C.gold -= n * RULES.recruitGold; C.manpower -= n; state.army[k] += n;
  return n;
}
export function invest(state, board, c, k) {
  const cost = investCost(state, board, k), C = state.countries[c];
  if (state.owner[k] !== c || state.econ[k] >= RULES.econMax || C.gold < cost) return false;
  C.gold -= cost; state.econ[k]++; return true;
}
export function buildFort(state, c, k) {
  const cost = fortCost(state, k), C = state.countries[c];
  if (state.owner[k] !== c || state.fort[k] >= RULES.fortMax || C.gold < cost) return false;
  C.gold -= cost; state.fort[k]++; return true;
}
export function research(state, board, c) {
  const cost = techCost(state, board, c), C = state.countries[c];
  if (C.gold < cost) return false;
  C.gold -= cost; C.tech++; return true;
}

// ------------------------------------------------------------------ diplomacy
const say = (state, text, who = []) => state.log.push({ turn: state.turn, text, who });
export const nameOf = (state, c) => state.countries[c].name;

export function declareWar(state, a, b, opts = {}) {
  if (a === b || atWar(state, a, b) || !state.countries[a].alive || !state.countries[b].alive) return false;
  if ((state.truce.get(pair(a, b)) || 0) > state.turn) return false;
  if (allied(state, a, b)) state.allies.delete(pair(a, b));
  state.wars.set(pair(a, b), { since: state.turn, start: false });
  state.rel.set(pair(a, b), -90);
  say(state, `${nameOf(state, a)} 向 ${nameOf(state, b)} 宣战`, [a, b]);
  if (opts.calls === false) return true;
  // the defender's allies come to its aid; the attacker's allies join when they are on good terms
  for (const x of alliesOf(state, b)) if (x !== a && !atWar(state, x, a) && !allied(state, x, a)) {
    state.wars.set(pair(x, a), { since: state.turn, start: false }); state.rel.set(pair(x, a), -80);
    say(state, `${nameOf(state, x)} 履行同盟，对 ${nameOf(state, a)} 宣战`, [x, a]);
  }
  for (const x of alliesOf(state, a)) if (x !== b && x !== state.player && !atWar(state, x, b) && !allied(state, x, b)
    && relation(state, x, a) > 50 && rng(state) < 0.6) {
    state.wars.set(pair(x, b), { since: state.turn, start: false }); state.rel.set(pair(x, b), -80);
    say(state, `${nameOf(state, x)} 应盟友 ${nameOf(state, a)} 之邀，对 ${nameOf(state, b)} 宣战`, [x, b]);
  }
  return true;
}

export function makePeace(state, a, b) {
  if (!state.wars.delete(pair(a, b))) return false;
  state.truce.set(pair(a, b), state.turn + RULES.truce);
  state.rel.set(pair(a, b), Math.max(relation(state, a, b), -30));
  state.orders = state.orders.filter((o) => !((o.owner === a && state.owner[o.to] === b) || (o.owner === b && state.owner[o.to] === a)));
  say(state, `${nameOf(state, a)} 与 ${nameOf(state, b)} 签订和约（各守现有控制区）`, [a, b]);
  return true;
}

// the war seen from a: the people of b's core a holds less the people of a's core b holds, against the smaller
// country's people at the start (-1 to 1)
export function warScore(state, board, a, b) {
  let gain = 0, loss = 0;
  for (let k = 0; k < board.P; k++) {
    if (state.owner[k] === a && state.core[k] === b) gain += board.pop[k];
    else if (state.owner[k] === b && state.core[k] === a) loss += board.pop[k];
  }
  const base = Math.max(1, Math.min(state.countries[a].startPop, state.countries[b].startPop));
  return clamp((gain - loss) / base, -1, 1);
}
// whether an AI country c agrees to make peace with x
export function acceptsPeace(state, board, c, x) {
  const w = state.wars.get(pair(c, x)); if (!w) return false;
  const ws = warScore(state, board, c, x), turns = state.turn - w.since;
  if (state.countries[x].contested) return false;
  if (ws < -0.3) return true;                                  // losing badly
  if (w.start) return ws < -0.12 && turns > 6;                 // the wars of the date are fought out
  if (turns < 4) return false;
  return ws < 0.08 || (ws < 0.3 && turns > 18);
}
export function acceptsAlliance(state, board, c, x) {
  if (atWar(state, c, x) || allied(state, c, x)) return false;
  const r = relation(state, c, x);
  const common = enemiesOf(state, x).some((e) => atWar(state, c, e));
  return r >= 70 || (r >= 40 && common);
}
export function proposeAlliance(state, board, a, b) {
  if (!acceptsAlliance(state, board, b, a)) return false;
  state.allies.add(pair(a, b)); addRelation(state, a, b, 10);
  say(state, `${nameOf(state, a)} 与 ${nameOf(state, b)} 结为同盟`, [a, b]);
  return true;
}
export function breakAlliance(state, a, b) {
  if (!state.allies.delete(pair(a, b))) return false;
  addRelation(state, a, b, -40);
  say(state, `${nameOf(state, a)} 解除了与 ${nameOf(state, b)} 的同盟`, [a, b]);
  return true;
}
export function improveRelations(state, a, b) {
  const C = state.countries[a]; if (C.gold < relCost || atWar(state, a, b)) return false;
  C.gold -= relCost; addRelation(state, a, b, 12); return true;
}

// ------------------------------------------------------------------ movement and battle
// the way from k to `to`: through the owner's own provinces, the last step into the target. Sea steps (straits and
// sea lanes between ports) end the turn's movement.
export function findPath(state, board, c, from, to) {
  if (from === to) return [from];
  const prev = new Map([[from, -1]]); let q = [from];
  while (q.length) {
    const next = [];
    for (const k of q) for (const [j] of exits(board, k)) {
      if (prev.has(j)) continue;
      if (j === to) { if (!canEnter(state, c, j)) return null; prev.set(j, k); const p = [j]; let x = k; while (x >= 0) { p.push(x); x = prev.get(x); } return p.reverse(); }
      if (state.owner[j] !== c) continue;
      prev.set(j, k); next.push(j);
    }
    q = next;
  }
  return null;
}
export const canEnter = (state, c, k) => state.owner[k] === c || atWar(state, c, state.owner[k]);
export const attackFactor = (kind) => kind === 2 ? RULES.seaAttack : kind === 1 ? RULES.straitAttack : 1;
export const shipping = (income) => Math.round(2 + RULES.shipping * income);
function stepKind(board, a, b) { if (board.adj[a].includes(b)) return 0; if (board.sea[a].includes(b)) return 1; return 2; }

// an order: n divisions of `owner` from `from` towards `to`; kept until they arrive (the player's long marches)
export function order(state, board, c, from, to, n) {
  if (state.owner[from] !== c || n <= 0 || from === to) return null;
  const path = findPath(state, board, c, from, to); if (!path) return null;
  state.orders = state.orders.filter((o) => !(o.owner === c && o.from === from && o.to === to));
  const o = { owner: c, from, to, n: Math.min(n, state.army[from]) }; state.orders.push(o); return o;
}

export function battle(state, board, a, from, to, n, kind) {
  const d = state.owner[to]; const nd = state.army[to];
  const A = n * quality(state, a) * attackFactor(kind) * (0.9 + 0.2 * rng(state));
  const D = nd * (state.countries[d].contested ? 0.5 : quality(state, d)) * (RULES.defence + RULES.fortStep * state.fort[to]) * (0.9 + 0.2 * rng(state));
  if (nd === 0 || A > D) {
    const lossA = nd ? Math.min(n - 1, Math.round(n * clamp(0.35 * D / A, 0.05, 0.9))) : 0;
    const lossD = nd ? Math.round(nd * clamp(0.35 * A / D, 0.25, 1)) : 0;
    let left = nd - lossD;
    if (left > 0) {  // the survivors fall back into a province of their own, if there is one
      const back = board.adj[to].filter((j) => state.owner[j] === d);
      if (back.length) state.army[back[Math.floor(rng(state) * back.length)]] += left; else left = 0;
    }
    capture(state, board, a, to);
    state.army[to] = n - lossA;
    return { won: true, lossA, lossD, d };
  }
  const lossA = Math.round(n * clamp(0.35 * D / A, 0.25, 1)), lossD = Math.min(nd, Math.round(nd * clamp(0.35 * A / D, 0.05, 0.9)));
  state.army[to] = nd - lossD; state.army[from] += n - lossA;
  return { won: false, lossA, lossD, d };
}

function capture(state, board, a, k) {
  const d = state.owner[k]; state.owner[k] = a;
  if (a === state.player || d === state.player) say(state, `${nameOf(state, a)} 攻占 ${board.names[k]}（原属 ${nameOf(state, d)}）`, [a, d]);
  const D = state.countries[d]; if (D.contested) return;
  if (D.capital === k) {
    let held = 0, best = -1;
    for (let j = 0; j < board.P; j++) if (state.owner[j] === d) { held += board.pop[j]; if (best < 0 || board.pop[j] * (state.core[j] === d ? 2 : 1) > board.pop[best] * (state.core[best] === d ? 2 : 1)) best = j; }
    if (best < 0) return;
    if (held < RULES.capitulate * D.startPop) return capitulate(state, board, d, a);
    D.capital = best;
    say(state, `${D.name} 首都 ${board.names[k]} 失守，迁都 ${board.names[best]}`, [d, a]);
  }
}
// the loser's remaining provinces go to the country that took its capital
function capitulate(state, board, d, a) {
  const D = state.countries[d];
  for (let j = 0; j < board.P; j++) if (state.owner[j] === d) { state.owner[j] = a; state.army[j] = Math.floor(state.army[j] / 3); }
  say(state, `${D.name} 失去首都后投降，余下领土归 ${nameOf(state, a)}`, [d, a]);
  eliminate(state, d);
}
function eliminate(state, d) {
  const D = state.countries[d]; if (!D.alive) return;
  D.alive = false;
  for (const key of [...state.wars.keys()]) if (Math.floor(key / 4096) === d || key % 4096 === d) state.wars.delete(key);
  for (const key of [...state.allies]) if (Math.floor(key / 4096) === d || key % 4096 === d) state.allies.delete(key);
  state.orders = state.orders.filter((o) => o.owner !== d);
  if (!D.contested) say(state, `${D.name} 灭亡`, [d]);
}

function runOrders(state, board, t) {
  const orders = state.orders; state.orders = [];
  const ships = state.countries.map((C) => shipping(t.income[C.id]));
  for (let i = orders.length - 1; i > 0; i--) { const j = Math.floor(rng(state) * (i + 1)); [orders[i], orders[j]] = [orders[j], orders[i]]; }
  for (const o of orders) {
    const c = o.owner; if (!state.countries[c].alive || state.owner[o.from] !== c) continue;
    let at = o.from, n = Math.min(o.n, state.army[o.from]); if (n <= 0) continue;
    state.army[at] -= n;
    let steps = RULES.speed, done = false;
    while (steps > 0) {
      const path = findPath(state, board, c, at, o.to);
      if (!path || path.length < 2) { done = true; break; }
      const next = path[1], kind = stepKind(board, at, next);
      if (kind === 2) {  // what the ships can carry this turn; the rest waits in port
        const m = Math.min(n, ships[c]); if (m <= 0) break;
        if (m < n) { state.army[at] += n - m; state.orders.push({ owner: c, from: at, to: o.to, n: n - m }); n = m; }
        ships[c] -= m;
      }
      if (state.owner[next] === c) { at = next; steps = kind ? 0 : steps - 1; if (at === o.to) { done = true; break; } continue; }
      const r = battle(state, board, c, at, next, n, kind);
      if (c === state.player || r.d === state.player) say(state, `${board.names[next]}：${nameOf(state, c)} ${n} 个师进攻 ${nameOf(state, r.d)} ${r.lossD + (r.won ? 0 : state.army[next])} 个师——${r.won ? "攻占" : "被击退"}（损失 ${r.lossA} : ${r.lossD}）`, [c, r.d]);
      n = 0; done = true; break;  // the army has fought: it stays where the battle left it
    }
    if (n > 0) state.army[at] += n;
    if (!done && n > 0) state.orders.push({ owner: c, from: at, to: o.to, n });
  }
}

// ------------------------------------------------------------------ the turn
// per country: its provinces, income, divisions and people, in one pass over the map
export function tally(state, board) {
  const n = state.countries.length;
  const t = { held: Array.from({ length: n }, () => []), income: new Float64Array(n), army: new Float64Array(n), pop: new Float64Array(n) };
  for (let k = 0; k < board.P; k++) {
    const c = state.owner[k]; t.held[c].push(k); t.income[c] += provinceIncome(state, board, k); t.army[c] += state.army[k]; t.pop[c] += board.pop[k];
  }
  return t;
}

export function endTurn(state, board, ai) {
  const t0 = tally(state, board);
  for (const c of state.countries) if (c.alive && !c.contested && c.id !== state.player) ai(state, board, c.id, t0);
  runOrders(state, board, t0);
  // dead countries, money and manpower
  const t = tally(state, board);
  for (const C of state.countries) if (C.alive && !t.held[C.id].length) eliminate(state, C.id);
  for (const C of state.countries) {
    if (!C.alive || C.contested) continue;
    const army = t.army[C.id];
    C.gold += t.income[C.id] - army * RULES.upkeep;
    const gain = manpowerGain(state, board, C.id);
    C.manpower = Math.min(C.manpower + gain, gain * RULES.manpowerCap);
    if (C.gold < 0) {  // unpaid divisions go home
      let cut = Math.ceil(army * 0.03);
      for (let k = 0; k < board.P && cut > 0; k++) if (state.owner[k] === C.id && state.army[k] > 1) { const t = Math.min(cut, Math.ceil(state.army[k] * 0.05)); state.army[k] -= t; cut -= t; }
      C.gold = 0;
    }
  }
  state.turn++; state.month++; if (state.month > 12) { state.month = 1; state.year++; }
  const P = state.player;
  if (P >= 0 && !state.countries[P].alive) state.over = { won: false };
  else if (P >= 0 && !state.over && t.pop[P] / t.pop.reduce((a, b) => a + b, 0) >= 0.5) state.over = { won: true };
}

// ------------------------------------------------------------------ save
export function save(state) {
  return JSON.stringify({ v: 1, ...state, owner: [...state.owner], core: [...state.core], army: [...state.army], econ: [...state.econ], fort: [...state.fort],
    wars: [...state.wars], allies: [...state.allies], rel: [...state.rel], truce: [...state.truce], log: state.log.slice(-200) });
}
export function load(text) {
  const s = JSON.parse(text);
  return { ...s, owner: Int16Array.from(s.owner), core: Int16Array.from(s.core), army: Int32Array.from(s.army), econ: Uint8Array.from(s.econ),
    fort: Uint8Array.from(s.fort), wars: new Map(s.wars), allies: new Set(s.allies), rel: new Map(s.rel), truce: new Map(s.truce) };
}
