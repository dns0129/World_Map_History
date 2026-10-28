// The computer's countries. Each turn, before the orders are carried out, every country other than the player's:
// makes peace in wars that are lost or stuck, now and then attacks a much weaker neighbour, spends its money
// (divisions in war, investment and technology in peace), and moves its divisions: attacks where its fronts are
// stronger than the enemy's provinces next to them, sends the interior's divisions towards the fronts, and evens
// out its fronts by the threat each faces.

import {
  RULES, rng, allied, relation, enemiesOf, alliesOf, exits, quality, declareWar, makePeace, acceptsPeace,
  proposeAlliance, recruit, invest, research, investCost, techCost, buildFort, fortCost, provinceIncome, pair, attackFactor, shipping,
} from "./rules.js";

const WAR_CHANCE = 0.004;  // per turn, of a country at peace looking for a war (times the game's aggression)

export function aiTurn(state, board, c, t) {
  const C = state.countries[c]; const mine = t.held[c]; if (!mine.length) return;
  diplomacy(state, board, c, t);
  const foes = new Set(enemiesOf(state, c).filter((e) => state.countries[e].alive));
  for (const D of state.countries) if (D.contested && D.alive) foes.add(D.id);
  const front = military(state, board, c, t, foes);
  spend(state, board, c, t, front, foes);
}

function diplomacy(state, board, c, t) {
  const C = state.countries[c];
  for (const e of enemiesOf(state, c)) {
    if (e === state.player || e < c || !state.countries[e].alive) continue;
    if (acceptsPeace(state, board, c, e) && acceptsPeace(state, board, e, c) && rng(state) < 0.3) makePeace(state, c, e);
  }
  if (enemiesOf(state, c).length) {
    // join forces with those fighting the same enemy
    if (rng(state) < 0.03) for (const e of enemiesOf(state, c)) for (const x of enemiesOf(state, e)) {
      if (x !== c && x !== state.player && !allied(state, c, x) && relation(state, c, x) >= 30) { proposeAlliance(state, board, c, x); return; }
    }
    return;
  }
  if (rng(state) > WAR_CHANCE * state.aggression) return;
  // a neighbour by land, not an ally, at most a third as strong counting its allies
  const near = new Set();
  for (const k of t.held[c]) for (const j of board.adj[k]) { const o = state.owner[j]; if (o !== c) near.add(o); }
  const power = (x) => t.army[x] * quality(state, x) + t.income[x] * 2;
  let best = -1, bestV = 0;
  for (const x of near) {
    const X = state.countries[x];
    if (X.contested || !X.alive || allied(state, c, x) || (state.truce.get(pair(c, x)) || 0) > state.turn || relation(state, c, x) > 20) continue;
    const theirs = power(x) + alliesOf(state, x).reduce((s, y) => s + power(y) * 0.5, 0);
    if (power(c) < 3 * theirs + 5) continue;
    const v = t.pop[x] / (theirs + 1);
    if (v > bestV) { bestV = v; best = x; }
  }
  if (best >= 0) declareWar(state, c, best);
}

const strength = (state, c, k) => {
  const d = state.owner[k], D = state.countries[d];
  return state.army[k] * (D.contested ? 0.5 : quality(state, d)) * (RULES.defence + RULES.fortStep * state.fort[k]);
};

function military(state, board, c, t, foes) {
  const mine = t.held[c]; const q = quality(state, c);
  if (!foes.size) return [];
  const isFoe = (k) => foes.has(state.owner[k]);
  // threat on each province: the enemy divisions next to it by land or strait
  const threat = new Map(), front = [];
  for (const k of mine) {
    let th = 0, any = false;
    for (const [j, kind] of exits(board, k)) {
      if (!isFoe(j)) continue;
      if (kind < 2) { any = true; th += state.army[j] * quality(state, state.owner[j]) * attackFactor(kind); }
    }
    if (any) { front.push(k); threat.set(k, th); }
  }
  // no front by land: stage at the ports, from where the sea lanes reach the enemy's ports
  let stage = front;
  if (!front.length) stage = mine.filter((k) => board.lanes[k].some((j) => isFoe(j)));
  const keep = (k) => Math.ceil((threat.get(k) || 0) * 0.6 / (q * RULES.defence)) + (k === state.countries[c].capital ? 2 : 0);
  const avail = new Map(); for (const k of mine) avail.set(k, Math.max(0, state.army[k] - keep(k)));

  // attacks: enemy provinces next to the front (or across a sea lane), the most valuable for their defence first
  const targets = new Map();
  for (const k of [...front, ...stage.filter((k) => !threat.has(k))]) for (const [j, kind] of exits(board, k)) {
    if (!isFoe(j)) continue;
    if (!targets.has(j)) targets.set(j, []); targets.get(j).push([k, kind]);
  }
  const plans = []; let cap = shipping(t.income[c]);
  for (const [j, srcs] of targets) {
    const def = strength(state, c, j); const o = state.owner[j];
    const val = board.pop[j] * (state.core[j] === c ? 3 : 1) * (state.countries[o].capital === j ? 3 : 1) + 1e5;
    plans.push([val / (def + 1), j, srcs, def]);
  }
  plans.sort((a, b) => b[0] - a[0]);
  for (const [, j, srcs, def] of plans) {
    srcs.sort((a, b) => a[1] - b[1] || avail.get(b[0]) - avail.get(a[0]));
    const need = def * 1.3 + 0.5;
    let can = 0, ships = 0;
    for (const [k, kind] of srcs) { let a = avail.get(k); if (kind === 2) { a = Math.min(a, cap - ships); ships += a; } can += a * q * attackFactor(kind); }
    if (can < need) continue;
    let sent = 0; const want = def ? need * 1.5 : 0;
    for (const [k, kind] of srcs) {
      const m = q * attackFactor(kind); let a = avail.get(k); if (kind === 2) a = Math.min(a, cap); if (!a) continue;
      let n = def ? Math.min(a, Math.ceil((want - sent) / m)) : Math.min(a, Math.max(1, Math.ceil(a * 0.25)));
      if (n <= 0) continue;
      state.orders.push({ owner: c, from: k, to: j, n }); avail.set(k, avail.get(k) - n); sent += n * m; if (kind === 2) cap -= n;
      if (sent >= want) break;
    }
  }
  // the interior's divisions move one province towards the front
  const dist = new Map(); let q0 = [...stage]; for (const k of stage) dist.set(k, 0);
  while (q0.length) {
    const next = [];
    for (const k of q0) for (const [j] of exits(board, k)) if (state.owner[j] === c && !dist.has(j)) { dist.set(j, dist.get(k) + 1); next.push(j); }
    q0 = next;
  }
  for (const k of mine) {
    const d = dist.get(k); if (!d) continue;
    const garrison = (k === state.countries[c].capital ? 2 : 0) + (board.isPort[k] ? 1 : 0);
    const n = Math.min(avail.get(k), state.army[k] - garrison); if (n <= 0) continue;
    let to = -1; for (const [j] of exits(board, k)) if (dist.get(j) === d - 1 && (to < 0 || (threat.get(j) || 0) > (threat.get(to) || 0))) to = j;
    if (to >= 0) { state.orders.push({ owner: c, from: k, to, n }); avail.set(k, avail.get(k) - n); }
  }
  // even out the front: from quiet front provinces to threatened neighbours
  const total = front.reduce((s, k) => s + state.army[k], 0), th = front.reduce((s, k) => s + threat.get(k) + 1, 0);
  for (const k of front) {
    const want = total * (threat.get(k) + 1) / th; const surplus = Math.min(avail.get(k), Math.floor(state.army[k] - want * 1.3));
    if (surplus <= 0) continue;
    let to = -1, gap = 0;
    for (const j of board.adj[k]) if (threat.has(j) && state.owner[j] === c) {
      const g = total * (threat.get(j) + 1) / th - state.army[j]; if (g > gap) { gap = g; to = j; }
    }
    if (to >= 0) { const n = Math.min(surplus, Math.ceil(gap)); state.orders.push({ owner: c, from: k, to, n }); avail.set(k, avail.get(k) - n); }
  }
  return front;
}

function spend(state, board, c, t, front, foes) {
  const C = state.countries[c]; const inc = t.income[c]; const upkeep = t.army[c] * RULES.upkeep;
  const atWarNow = enemiesOf(state, c).length > 0;
  const reserve = Math.max(5, upkeep * 2);
  if (atWarNow || (foes.size && front.length)) {
    let n = Math.floor(Math.min(C.manpower, (C.gold - reserve) / RULES.recruitGold));
    if (inc - upkeep - n * RULES.upkeep < -inc * 0.2) n = Math.floor((inc * 1.2 - upkeep) / RULES.upkeep);  // what it can keep paying
    if (n > 0) {
      const spots = (front.length ? front : t.held[c]).slice().sort((a, b) => state.army[a] - state.army[b]).slice(0, 4);
      const each = Math.ceil(n / spots.length);
      for (const k of spots) if (n > 0) n -= recruit(state, board, c, k, Math.min(each, n));
    }
    const cap = C.capital;
    if (cap >= 0 && state.owner[cap] === c && state.fort[cap] < 2 && C.gold > fortCost(state, cap) + reserve * 3) buildFort(state, c, cap);
    if (C.gold > techCost(state, board, c) + reserve * 4) research(state, board, c);
    return;
  }
  // at peace: an army of four tenths of the war footing, then the economy
  const target = Math.round((C.base || 0) * 0.4);
  if (t.army[c] < target) {
    let n = Math.floor(Math.min(C.manpower, target - t.army[c], (C.gold - reserve) / RULES.recruitGold));
    const k = C.capital >= 0 && state.owner[C.capital] === c ? C.capital : t.held[c][0];
    if (n > 0) recruit(state, board, c, k, n);
  }
  if (C.gold < reserve * 3) return;
  if (rng(state) < 0.2 && C.gold > techCost(state, board, c) + reserve) { research(state, board, c); return; }
  let best = -1, bv = 0;
  for (const k of t.held[c]) {
    if (state.econ[k] >= RULES.econMax) continue;
    const v = provinceIncome(state, board, k) / investCost(state, board, k); if (v > bv) { bv = v; best = k; }
  }
  if (best >= 0 && C.gold > investCost(state, board, best) + reserve) invest(state, board, c, best);
}
