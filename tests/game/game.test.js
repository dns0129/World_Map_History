// The game's rules, board and AI (game/*.js): node --test tests/game (also run by tests/test_game.py).
// The last test plays a real map date and runs only when the map data has been fetched (scripts/data_release.py).
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { buildGraph, labelPoint, inGeom } from "../../game/geometry.js";
import * as R from "../../game/rules.js";
import { aiTurn } from "../../game/ai.js";
import { MapData } from "../../game/data.js";
import { nodeIO, DATA } from "./node_io.js";

const square = (x, y, s = 1) => [[[[x, y], [x + s, y], [x + s, y + s], [x, y + s], [x, y]]]];

test("borders and straits", () => {
  // 0 | 1 side by side; 2 across a 0.5° strait from 1; 3 far out at sea
  const G = buildGraph([square(0, 0), square(1, 0), square(2.5, 0), square(20, 20)]);
  assert.deepEqual([...G.adj[0]], [1]);
  assert.deepEqual([...G.adj[1]].sort(), [0]);
  assert.deepEqual([...G.sea[1]], [2]);
  assert.deepEqual([...G.sea[0]], []);       // 0 reaches 2 only past 1's coast: no strait over land
  assert.equal(G.adj[3].length + G.sea[3].length, 0);
});

test("label point inside a concave outline", () => {
  const u = [[[[0, 0], [3, 0], [3, 3], [2, 3], [2, 1], [1, 1], [1, 3], [0, 3], [0, 0]]]];
  const [x, y] = labelPoint(u);
  assert.ok(inGeom(x, y, u));
});

// a strip of five provinces: 0 1 2 belong to A, 3 4 to B; 4 is B's capital
function strip(opts = {}) {
  const geoms = [0, 1, 2, 3, 4].map((i) => square(i, 0));
  const graph = buildGraph(geoms);
  const sd = {
    snapshot: opts.snap || "1950-01-01", title_zh: "test", feature: [0, 1, 2, 3, 4], country: [0, 0, 0, 1, 1], pop: [1e6, 1e6, 1e6, 1e6, 2e6], area: [1e4, 1e4, 1e4, 1e4, 1e4],
    countries: [["A", "甲国", "A", "#c00", 2, 0, 0, 3, 0, []], ["B", "乙国", "B", "#00c", 2, 0, 0, 2, 0, []]],
    luts: { unit_name_zh: ["甲国", "乙国"], sovereign_name_zh: ["甲国", "乙国"] },
    rows: { unit_name_zh: [0, 0, 0, 1, 1], sovereign_name_zh: [0, 0, 0, 1, 1] },
    cities: [["乙京", 4.5, 0.5, 1, 0, "首都：乙国", null, null]],
  };
  const eco = { years: [1950], world: [3000], unit: { "甲国": [3000], "乙国": [3000] }, iso: {} };
  const board = R.buildBoard(sd, geoms, graph, ["一", "二", "三", "四", "五"], eco);
  const state = R.newGame(sd, board, { player: 0, seed: 1 });
  return { board, state };
}

test("scenario: capitals, cores, armies at peace", () => {
  const { board, state } = strip();
  assert.equal(state.countries[1].capital, 4);
  assert.deepEqual([...state.core], [0, 0, 0, 1, 1]);
  assert.equal(R.atWar(state, 0, 1), false);
  assert.ok(state.countries[0].gold > 0);
});

test("orders go through own land only and attack only at war", () => {
  const { board, state } = strip();
  state.army.fill(0); state.army[0] = 10;
  assert.deepEqual(R.findPath(state, board, 0, 0, 2), [0, 1, 2]);
  assert.equal(R.findPath(state, board, 0, 0, 3), null);       // B is at peace with A
  R.declareWar(state, 0, 1);
  assert.deepEqual(R.findPath(state, board, 0, 0, 3), [0, 1, 2, 3]);
  assert.equal(R.findPath(state, board, 0, 0, 4), null);       // beyond the first enemy province
});

test("a march of several turns, then a battle and the capital's fall", () => {
  const { board, state } = strip();
  state.army.fill(0); state.army[0] = 20; state.army[3] = 2;
  R.declareWar(state, 0, 1);
  R.order(state, board, 0, 0, 2, 20);
  R.endTurn(state, board, () => {});
  assert.equal(state.army[2], 20);                              // two provinces a turn
  R.order(state, board, 0, 2, 3, 20);
  R.endTurn(state, board, () => {});
  assert.equal(state.owner[3], 0);                              // 20 against 2 behind no fort
  assert.ok(state.army[3] > 10 && state.army[3] <= 20);
  assert.equal(state.owner[4], 1);
  R.order(state, board, 0, 3, 4, state.army[3]);
  R.endTurn(state, board, () => {});
  assert.equal(state.owner[4], 0);
  assert.equal(state.countries[1].alive, false);
  assert.ok(state.log.some((l) => l.text.includes("灭亡")));
});

test("a strong defence repels the attack", () => {
  const { board, state } = strip();
  state.army.fill(0); state.army[2] = 5; state.army[3] = 20; state.fort[3] = 2;
  R.declareWar(state, 0, 1);
  R.order(state, board, 0, 2, 3, 5);
  R.endTurn(state, board, () => {});
  assert.equal(state.owner[3], 1);
  assert.ok(state.army[2] < 5);
});

test("economy: income, recruiting, upkeep", () => {
  const { board, state } = strip();
  const C = state.countries[0]; C.gold = 30; C.manpower = 4;
  assert.equal(R.recruit(state, board, 0, 1, 50), 4);          // limited by manpower
  assert.equal(C.gold, 30 - 4 * R.RULES.recruitGold);
  assert.equal(R.recruit(state, board, 0, 3, 1), 0);           // not in a foreign province
  const inc = R.income(state, board, 0), army = R.armyOf(state, 0), gold = C.gold;
  R.endTurn(state, board, () => {});
  assert.ok(Math.abs(C.gold - (gold + inc - army * R.RULES.upkeep)) < 1e-6);
});

test("peace, truce and alliances", () => {
  const { board, state } = strip();
  R.declareWar(state, 0, 1);
  state.wars.get(R.pair(0, 1)).since = -10;
  state.owner[3] = 0;                                           // A holds a third of B's people
  assert.equal(R.acceptsPeace(state, board, 1, 0), true);
  assert.equal(R.acceptsPeace(state, board, 0, 1), false);      // the winner keeps fighting
  R.makePeace(state, 0, 1);
  assert.equal(R.declareWar(state, 0, 1), false);               // truce
  state.rel.set(R.pair(0, 1), 80);
  assert.equal(R.proposeAlliance(state, board, 0, 1), true);
  assert.equal(R.allied(state, 0, 1), true);
});

test("the wars of a date", () => {
  const C = (id, key, bloc, lon) => ({ id, key, bloc, contested: false, capLon: lon, capLat: 35 });
  const cs = [C(0, "200", 0, 0), C(1, "740", 1, 139), C(2, "710", 0, 106), C(3, "255", 1, 13), C(4, "365", 0, 37)];
  const has = (d, a, b) => d.wars.some(([x, y]) => (x === a && y === b) || (x === b && y === a));
  const d39 = R.initialDiplomacy("1939-09-01", cs);
  assert.ok(has(d39, 0, 3) && has(d39, 1, 2));
  assert.ok(!has(d39, 0, 1) && !has(d39, 2, 3));               // Europe and China are separate wars before Pearl Harbor
  const d42 = R.initialDiplomacy("1942-11-01", cs);
  assert.ok(has(d42, 0, 1) && has(d42, 2, 3) && has(d42, 3, 4));
  assert.ok(!has(d42, 1, 4));                                   // the Soviet-Japanese neutrality pact
  assert.equal(R.initialDiplomacy("1953-07-27", cs).wars.length, 0);
});

test("save and load", () => {
  const { board, state } = strip();
  R.declareWar(state, 0, 1); state.allies.add(R.pair(0, 1)); state.army[1] = 7;
  const back = R.load(R.save(state));
  assert.deepEqual([...back.army], [...state.army]);
  assert.ok(back.wars.has(R.pair(0, 1)) && back.allies.has(R.pair(0, 1)));
  assert.ok(back.owner instanceof Int16Array);
});

const haveData = existsSync(`${DATA}/snap-1942-11-01.json`);
test("a year on the map of 1942-11-01", { skip: !haveData && "map data not fetched" }, async () => {
  const eco = JSON.parse(readFileSync(new URL("../../game/economy.json", import.meta.url)));
  const md = new MapData(DATA, nodeIO);
  const sd = await md.loadSnap("1942-11-01"); const geoms = md.featureGeoms(sd);
  const names = sd.feature.map((_, k) => md.provinceName(sd, k));
  const board = R.buildBoard(sd, geoms, buildGraph(geoms), names, eco);
  const state = R.newGame(sd, board, { player: -1, seed: 3 });
  const byName = (n) => state.countries.find((c) => c.name === n).id;
  const [de, uk, su, jp] = ["德国", "英国", "苏联", "日本"].map(byName);
  assert.ok(R.atWar(state, de, su) && R.atWar(state, jp, uk) && !R.atWar(state, jp, su));
  assert.equal(names[state.countries[de].capital], "Freistaat Preußen");
  const strait = (a, b) => board.sea[names.indexOf(a)].includes(names.indexOf(b));
  assert.ok(strait("Pas-de-Calais", "England and Wales"));
  for (let i = 0; i < 12; i++) R.endTurn(state, board, aiTurn);
  assert.equal(state.year, 1943); assert.equal(state.month, 11);
  for (let k = 0; k < board.P; k++) { assert.ok(state.army[k] >= 0); assert.ok(state.countries[state.owner[k]].alive || state.countries[state.owner[k]].contested); }
  for (const c of state.countries) assert.ok(Number.isFinite(c.gold) && c.gold >= 0);
});
