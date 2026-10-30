// Node io for game/data.js: the map data files from disk
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";

export const DATA = new URL("../../ww2/maps/data", import.meta.url).pathname;
export const nodeIO = {
  async json(p) { return JSON.parse(readFileSync(p, "utf8")); },
  async bin(p) { const b = readFileSync(p); const u = b[0] === 0x1f && b[1] === 0x8b ? gunzipSync(b) : b; return u.buffer.slice(u.byteOffset, u.byteOffset + u.byteLength); },
};
