/* Browser progress is separate from content approval. Web Locks serialize whole-state writes. */
(function (global) {
  "use strict";
  const KEY = "codebrick-workbench-state-v1";
  const plain = (v) => v && typeof v === "object" && !Array.isArray(v);
  const safeKey = (key) => typeof key === "string" && key.length > 0 && key.length < 240 && !["__proto__", "constructor", "prototype"].includes(key);
  const empty = () => ({ version: 2, reviews: {}, history: {}, notes: {}, noteConflicts: {} });
  const clone = (v) => JSON.parse(JSON.stringify(v));
  function record(item) {
    if (!plain(item) || typeof item.signature !== "string" || !["again", "hard", "good", "easy"].includes(item.rating) || !Number.isFinite(item.due) || item.due < 0) return null;
    return { signature: item.signature, rating: item.rating, due: item.due,
      interval: Number.isFinite(item.interval) ? Math.min(3650, Math.max(0, item.interval)) : 0,
      count: Number.isSafeInteger(item.count) && item.count > 0 ? item.count : 1,
      reviewedAt: Number.isFinite(item.reviewedAt) && item.reviewedAt > 0 ? item.reviewedAt : 0,
      revision: typeof item.revision === "string" ? item.revision : "" };
  }
  function normalize(value) {
    if (!plain(value) || ![1, 2].includes(value.version) || !plain(value.reviews) || !plain(value.notes)) throw new Error("进度文件格式或版本不受支持。");
    for (const key of ["history", "noteConflicts"]) if (Object.hasOwn(value, key) && !plain(value[key])) throw new Error("进度历史格式损坏，已禁止覆盖。");
    const result = empty();
    for (const [id, item] of Object.entries(value.reviews)) { const r = record(item); if (!safeKey(id) || !r) throw new Error("进度含有无效评分，原记录不会被覆盖。"); result.reviews[id] = r; }
    for (const [id, items] of Object.entries(plain(value.history) ? value.history : {})) { if (!safeKey(id) || !Array.isArray(items) || items.some((item) => !record(item))) throw new Error("评分历史格式损坏，已禁止覆盖。"); result.history[id] = items.map(record); }
    for (const [id, text] of Object.entries(value.notes)) { if (!safeKey(id) || typeof text !== "string") throw new Error("笔记格式损坏，已禁止覆盖。"); result.notes[id] = text; }
    for (const [id, texts] of Object.entries(plain(value.noteConflicts) ? value.noteConflicts : {})) { if (!safeKey(id) || !Array.isArray(texts) || texts.some((t) => typeof t !== "string")) throw new Error("冲突笔记格式损坏，已禁止覆盖。"); result.noteConflicts[id] = [...new Set(texts)]; }
    return result;
  }
  function archive(state, id, item) {
    if (!item) return;
    const values = state.history[id] || (state.history[id] = []);
    if (!values.some((v) => JSON.stringify(v) === JSON.stringify(item))) values.push(clone(item));
  }
  function noteConflict(state, id, text) {
    if (text === state.notes[id]) return;
    const values = state.noteConflicts[id] || (state.noteConflicts[id] = []);
    if (!values.includes(text)) values.push(text);
  }
  function merge(primary, incoming) {
    const out = normalize(primary), other = normalize(incoming);
    for (const [id, item] of Object.entries(other.reviews)) {
      const before = out.reviews[id];
      if (!before) out.reviews[id] = item;
      else if (before.signature === item.signature && item.reviewedAt > before.reviewedAt) { archive(out, id, before); out.reviews[id] = item; }
      else if (JSON.stringify(before) !== JSON.stringify(item)) archive(out, id, item);
    }
    for (const [id, values] of Object.entries(other.history)) for (const item of values) archive(out, id, item);
    for (const [id, text] of Object.entries(other.notes)) { if (!Object.hasOwn(out.notes, id)) out.notes[id] = text; else if (out.notes[id] !== text) noteConflict(out, id, text); }
    for (const [id, texts] of Object.entries(other.noteConflicts)) for (const text of texts) noteConflict(out, id, text);
    return out;
  }
  function reviewed(state, id, signature) {
    const active = state.reviews[id];
    const options = [active, ...(state.history[id] || [])].filter((item) => item && item.signature === signature);
    return options.reduce((best, item) => !best || item.reviewedAt > best.reviewedAt ? item : best, null);
  }
  class Store {
    constructor(storage, locks, onChange = () => {}) { this.storage = storage; this.locks = locks; this.onChange = onChange; this.state = empty(); this.blocked = false; this.raw = null; this.failure = ""; this.unsaved = false; this.serial = 0; this.writer = global.crypto?.randomUUID?.() || Math.random().toString(36).slice(2); }
    read() { const raw = this.storage.getItem(KEY); return raw === null ? empty() : normalize(JSON.parse(raw)); }
    load() { try { this.state = this.read(); } catch (e) { this.blocked = true; try { this.raw = this.storage.getItem(KEY); } catch {} this.failure = "原进度无法读取，已禁止覆盖。请下载原始记录，再恢复备份或明确重置。"; } return this.state; }
    async change(operation) {
      if (this.blocked) throw new Error(this.failure);
      if (!this.locks?.request) throw new Error("此浏览器不支持跨页写锁，已禁止写入。请使用当前版 Chrome/Edge，或先导出本次记录。");
      return this.locks.request(KEY, async () => {
        let disk;
        try { disk = this.read(); } catch (e) { this.blocked = true; try { this.raw = this.storage.getItem(KEY); } catch {} this.failure = "存储在其他页面中损坏，已禁止覆盖；请下载原始记录。"; this.onChange(); throw new Error(this.failure); }
        const next = this.unsaved ? merge(disk, this.state) : disk;
        const result = operation(next);
        this.state = next;
        try { this.storage.setItem(KEY, JSON.stringify(next)); this.unsaved = false; this.failure = ""; }
        catch (e) { this.unsaved = true; this.failure = "浏览器存储失败，当前更改仍在内存中。请立即备份后再关闭。"; this.onChange(); throw new Error(this.failure); }
        this.onChange(); return result;
      });
    }
    sync() { if (this.blocked) return; try { const disk = this.read(); this.state = this.unsaved ? merge(disk, this.state) : disk; this.onChange(); } catch { this.blocked = true; try { this.raw = this.storage.getItem(KEY); } catch {} this.failure = "其他页面的进度无法读取，已禁止覆盖；请下载原始记录。"; this.onChange(); } }
    note(id, text, base) { if (!safeKey(id) || typeof text !== "string") return Promise.reject(new Error("笔记格式无效。")); return this.change((state) => { const before = state.notes[id] || ""; if (before !== base && before !== text) { noteConflict(state, id, text); return { conflict: true, text: before }; } state.notes[id] = text; return { conflict: false, text }; }); }
    rate(id, signature, rating, now = Date.now()) { if (!safeKey(id) || !["again", "hard", "good", "easy"].includes(rating)) return Promise.reject(new Error("评分格式无效。")); return this.change((state) => { const old = reviewed(state, id, signature), before = old?.interval || 0;
      const interval = rating === "again" ? 10 / 1440 : rating === "hard" ? 1 : rating === "good" ? Math.min(3650, Math.max(3, before * 2)) : Math.min(3650, Math.max(7, before * 3));
      const previous = state.reviews[id]; if (previous && previous.signature !== signature) archive(state, id, previous);
      state.reviews[id] = { signature, rating, interval, due: now + interval * 86400000, count: (old?.count || 0) + 1, reviewedAt: now, revision: this.writer + ":" + (++this.serial) }; }); }
    restore(value) { const imported = normalize(value); return this.change((state) => { const merged = merge(state, imported); for (const key of Object.keys(state)) delete state[key]; Object.assign(state, merged); }); }
    async reset() { if (!this.locks?.request) throw new Error("当前浏览器无法取得跨页写锁，不能重置。"); return this.locks.request(KEY, () => { this.storage.setItem(KEY, JSON.stringify(empty())); this.state = empty(); this.blocked = false; this.failure = ""; this.onChange(); }); }
  }
  const api = { KEY, Store, empty, normalize, merge, reviewed };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else global.CodebrickProgress = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
