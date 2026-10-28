// The game board drawn from the outlines: which provinces border each other, which face each other across a
// strait, a label point inside each, and which province holds a point (capitals, ports).
//
// Borders: every outline is traced on a grid of CELL degrees; two provinces whose outlines pass through the same
// cell share a border. The outlines are simplified one by one (scripts/mapdata.py, 0.008°), so the two sides of
// a border lie a little apart, far less than a cell.
// Straits: see seaLinks.

const CELL = 0.05;
const NX = Math.round(360 / CELL), NY = Math.round(180 / CELL);
const FID = 16384;  // feature ids below this

function cellOf(x, y) {
  let ix = Math.floor((x + 180) / CELL); ix = ((ix % NX) + NX) % NX;
  let iy = Math.floor((y + 90) / CELL); iy = Math.max(0, Math.min(NY - 1, iy));
  return ix * NY + iy;
}

export function buildGraph(geoms) {
  const n = geoms.length;
  if (n >= FID) throw new Error("too many map features");
  let buf = new Float64Array(1 << 20), len = 0;
  const push = (v) => { if (len === buf.length) { const b = new Float64Array(buf.length * 2); b.set(buf); buf = b; } buf[len++] = v; };
  for (let k = 0; k < n; k++) {
    let last = -1;
    for (const poly of geoms[k] || []) for (const ring of poly) {
      for (let i = 0; i + 1 < ring.length; i++) {
        const [x0, y0] = ring[i], [x1, y1] = ring[i + 1];
        const steps = Math.max(1, Math.ceil(Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0)) / (CELL / 2)));
        if (steps > 20000) continue;  // a ring crossing the antimeridian the long way
        for (let s = 0; s < steps; s++) {
          const t = s / steps; const c = cellOf(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t);
          if (c !== last) { push(c * FID + k); last = c; }
        }
      }
    }
  }
  const all = buf.subarray(0, len).sort();
  // unique cells and, per cell, whether more than one province passes through it
  const shared = new Map();  // a * FID + b -> cells in common
  const cells = [], owner = [];  // owner: the province, or -1 when several
  for (let i = 0; i < len;) {
    const c = Math.floor(all[i] / FID); let j = i; const ids = [];
    while (j < len && Math.floor(all[j] / FID) === c) { const k = all[j] - c * FID; if (ids[ids.length - 1] !== k) ids.push(k); j++; }
    cells.push(c); owner.push(ids.length === 1 ? ids[0] : -1);
    for (let a = 0; a < ids.length; a++) for (let b = a + 1; b < ids.length; b++) {
      const key = Math.min(ids[a], ids[b]) * FID + Math.max(ids[a], ids[b]); shared.set(key, (shared.get(key) || 0) + 1);
    }
    i = j;
  }
  const adj = Array.from({ length: n }, () => new Set());
  for (const key of shared.keys()) { const a = Math.floor(key / FID), b = key % FID; adj[a].add(b); adj[b].add(a); }

  const sea = seaLinks(geoms, adj);
  return { adj: adj.map((s) => Int32Array.from(s)), sea: sea.map((s) => Int32Array.from(s)) };
}

// Straits: the land drawn on a grid of R degrees; from every coast the sea is filled outwards, cell by cell, each
// sea cell going to the nearest province. Two provinces whose fills meet within GAP cells of open water face each
// other across a strait (the way never crosses land). Pairs that border each other or share a neighbour are left out.
const R = 0.1, RX = Math.round(360 / R), RY = Math.round(180 / R), GAP = 20;
function seaLinks(geoms, adj) {
  const n = geoms.length;
  const land = new Int32Array(RX * RY).fill(-1);
  const wrap = (ix) => ((ix % RX) + RX) % RX;
  for (let k = 0; k < n; k++) {
    for (const poly of geoms[k] || []) {
      const [x0, y0, x1, y1] = bbox([poly]);
      const j0 = Math.max(0, Math.floor((y0 + 90) / R)), j1 = Math.min(RY - 1, Math.floor((y1 + 90) / R));
      for (let j = j0; j <= j1; j++) {
        const y = -90 + (j + 0.5) * R; const xs = [];
        for (const r of poly) for (let i = 0; i + 1 < r.length; i++) {
          const [ax, ay] = r[i], [bx, by] = r[i + 1];
          if ((ay > y) !== (by > y)) xs.push(ax + (bx - ax) * (y - ay) / (by - ay));
        }
        xs.sort((p, q) => p - q);
        for (let i = 0; i + 1 < xs.length; i += 2) {
          const a = Math.ceil((xs[i] + 180) / R - 0.5), b = Math.floor((xs[i + 1] + 180) / R - 0.5);
          for (let ix = a; ix <= b; ix++) land[wrap(ix) * RY + j] = k;
        }
      }
      // a polygon too small to cover a cell centre still takes the cell of its first point
      const [px, py] = poly[0][0]; const c = wrap(Math.floor((px + 180) / R)) * RY + Math.max(0, Math.min(RY - 1, Math.floor((py + 90) / R)));
      if (land[c] < 0) land[c] = k;
    }
  }
  // breadth-first fill of the sea from all coasts at once
  const dist = new Uint8Array(RX * RY).fill(255), from = new Int32Array(RX * RY).fill(-1);
  let q = [];
  const nb = (c, f) => { const ix = Math.floor(c / RY), iy = c % RY;
    f(wrap(ix + 1) * RY + iy); f(wrap(ix - 1) * RY + iy); if (iy + 1 < RY) f(c + 1); if (iy > 0) f(c - 1); };
  for (let c = 0; c < land.length; c++) {
    if (land[c] < 0) continue;
    let coast = false; nb(c, (d) => { if (land[d] < 0) coast = true; });
    if (coast) { dist[c] = 0; from[c] = land[c]; q.push(c); }
  }
  const links = new Map();
  const meet = (a, b, d) => { if (a === b) return; const key = Math.min(a, b) * 16384 + Math.max(a, b); if (!links.has(key) || links.get(key) > d) links.set(key, d); };
  for (let d = 0; d < GAP && q.length; d++) {
    const next = [];
    for (const c of q) nb(c, (e) => {
      if (land[e] >= 0) { if (d > 0) meet(from[c], land[e], d + 1); return; }
      if (dist[e] === 255) { dist[e] = d + 1; from[e] = from[c]; next.push(e); }
      else if (from[e] !== from[c]) meet(from[c], from[e], dist[e] + d + 1);
    });
    q = next;
  }
  const sea = Array.from({ length: n }, () => new Set());
  for (const [key, d] of links) {
    const a = Math.floor(key / 16384), b = key % 16384;
    if (d > GAP || adj[a].has(b)) continue;
    let common = false; for (const m of adj[a]) if (adj[b].has(m)) { common = true; break; }
    if (!common) { sea[a].add(b); sea[b].add(a); }
  }
  return sea;
}

// ------------------------------------------------------------------ points
export function ringArea(r) { let a = 0; for (let i = 0; i + 1 < r.length; i++) a += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]; return a / 2; }
function inRing(x, y, r) {
  let inside = false;
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
    const [xi, yi] = r[i], [xj, yj] = r[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
export function inGeom(x, y, polys) {
  for (const rings of polys || []) if (inRing(x, y, rings[0]) && !rings.slice(1).some((h) => inRing(x, y, h))) return true;
  return false;
}
export function bbox(polys) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const rings of polys || []) for (const [x, y] of rings[0]) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  return [x0, y0, x1, y1];
}
// a point well inside the largest polygon: the middle of the widest stretch of a horizontal line through it
export function labelPoint(polys) {
  let best = null, ba = -1;
  for (const rings of polys || []) { const a = Math.abs(ringArea(rings[0])); if (a > ba) { ba = a; best = rings; } }
  if (!best) return [0, 0];
  const [x0, y0, x1, y1] = bbox([best]);
  let pick = [(x0 + x1) / 2, (y0 + y1) / 2], width = -1;
  for (const f of [0.5, 0.35, 0.65, 0.2, 0.8]) {
    const y = y0 + (y1 - y0) * f; const xs = [];
    for (const r of best) for (let i = 0; i + 1 < r.length; i++) {
      const [ax, ay] = r[i], [bx, by] = r[i + 1];
      if ((ay > y) !== (by > y)) xs.push(ax + (bx - ax) * (y - ay) / (by - ay));
    }
    xs.sort((p, q) => p - q);
    for (let i = 0; i + 1 < xs.length; i += 2) if (xs[i + 1] - xs[i] > width * 1.15) { width = xs[i + 1] - xs[i]; pick = [(xs[i] + xs[i + 1]) / 2, y]; }
    if (width > (x1 - x0) * 0.6) break;
  }
  return pick;
}

// the province holding a point, or the nearest one by label point within `near` degrees
export function locate(x, y, geoms, boxes, labels, near = 1.5) {
  for (let k = 0; k < geoms.length; k++) { const b = boxes[k]; if (x >= b[0] && x <= b[2] && y >= b[1] && y <= b[3] && inGeom(x, y, geoms[k])) return k; }
  let best = -1, bd = near * near;
  for (let k = 0; k < labels.length; k++) { const d = (labels[k][0] - x) ** 2 + (labels[k][1] - y) ** 2; if (d < bd) { bd = d; best = k; } }
  return best;
}
