// Map data of the game: the same files as the historical map (ww2/maps/data, format in scripts/mapdata.py),
// read here without the map page. Works in the browser and, with another `io`, in Node (tests/game).

// geo-<date>.bin: per outline a list of polygons, each a list of rings of [lon, lat]; zigzag-varint deltas of 1/1000°
export function decodeGeo(buf) {
  const b = new Uint8Array(buf); let i = 0; const out = [];
  const v = () => { let r = 0, s = 0, c; do { c = b[i++]; r += (c & 0x7f) * 2 ** s; s += 7; } while (c & 0x80); return r; };
  const z = () => { const n = v(); return (n % 2) ? -(n + 1) / 2 : n / 2; };
  while (i < b.length) {
    const np = v(); const polys = []; let px = 0, py = 0;
    for (let p = 0; p < np; p++) {
      const nr = v(); const rings = [];
      for (let r = 0; r < nr; r++) {
        const n = v(); const ring = new Array(n + 1);
        for (let k = 0; k < n; k++) { px += z(); py += z(); ring[k] = [px / 1000, py / 1000]; }
        ring[n] = ring[0]; rings.push(ring);
      }
      polys.push(rings);
    }
    out.push(polys);
  }
  return out;
}

// Browser io: plain fetch; the .bin files are gzip-compressed
async function inflate(buf) {
  if (typeof DecompressionStream === "undefined") {  // older browsers: pako from the CDN, loaded only then
    if (!globalThis.pako) await new Promise((ok, no) => { const sc = document.createElement("script");
      sc.src = "https://cdnjs.cloudflare.com/ajax/libs/pako/2.1.0/pako.min.js"; sc.onload = ok; sc.onerror = no; document.head.append(sc); });
    return globalThis.pako.ungzip(new Uint8Array(buf)).buffer;
  }
  return new Response(new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer();
}
export const browserIO = {
  async json(u) { const r = await fetch(u); if (!r.ok) throw new Error(u + " " + r.status); return r.json(); },
  async bin(u) {
    const r = await fetch(u); if (!r.ok) throw new Error(u + " " + r.status);
    const buf = await r.arrayBuffer(); const b = new Uint8Array(buf, 0, 2);
    return b[0] === 0x1f && b[1] === 0x8b ? inflate(buf) : buf;
  },
};

export class MapData {
  constructor(base, io = browserIO) { this.base = base; this.io = io; this.geo = []; this.adminGeo = []; this.snaps = {}; this.admin = null; }
  async index() { return this.io.json(`${this.base}/index.json`); }
  async loadAdmin() {
    if (!this.admin) this.admin = JSON.parse(new TextDecoder().decode(await this.io.bin(`${this.base}/admin.bin`)));
    return this.admin;
  }
  async hydro() { return JSON.parse(new TextDecoder().decode(await this.io.bin(`${this.base}/hydro.bin`))); }
  // the snapshot's rows and outlines, in the order ww2_webmap.py wrote them (as the map page's fetchSnap)
  async loadSnap(snap) {
    if (this.snaps[snap]) return this.snaps[snap];
    await this.loadAdmin();
    const [sd, buf] = await Promise.all([this.io.json(`${this.base}/snap-${snap}.json`), this.io.bin(`${this.base}/geo-${snap}.bin`)]);
    // an added date ships only the division outlines its base date's file lacks: the base date comes first
    if (sd.admin_base && sd.admin_base !== snap) await this.loadSnap(sd.admin_base);
    const recs = decodeGeo(buf); let i = 0;
    for (const a of (sd.admin_geo || sd.admin_active)) this.adminGeo[a] = recs[i++];
    for (const f of sd.geo_feature) this.geo[f] = recs[i++];
    i += sd.units_active.length;  // political-unit and control-area outlines: not used by the game
    this.snaps[snap] = sd;
    return sd;
  }
  // the outline of every map feature (province piece) of a snapshot: a cut piece has its own, a whole province its division's
  featureGeoms(sd) { return sd.feature.map((f) => this.geo[f] || this.adminGeo[this.admin.feature_admin[f]]); }
  adminCol(name, ai) { const c = this.admin.cols[name]; return c.lut[c.idx[ai]]; }
  provinceName(sd, k) {
    const ai = this.admin.feature_admin[sd.feature[k]];
    const n = this.adminCol("name_zh", ai) || this.adminCol("name", ai) || this.adminCol("name_en", ai);
    return n || sd.luts.unit_name_zh[sd.rows.unit_name_zh[k]] || "—";
  }
}
