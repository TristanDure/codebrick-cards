(() => {
  "use strict";
  const Progress = window.CodebrickProgress;
  const KEY = Progress.KEY;
  const BASE = new URL("../data/study/", location.href);
  const SUBJECTS = { os: "操作系统", co: "计算机组成原理", cn: "计算机网络", ds: "数据结构" };
  const byId = (id) => document.getElementById(id);
  let index = null, article = null, current = null, deck = [], at = 0, requestId = 0;
  const store = new Progress.Store({ getItem: (key) => window.localStorage.getItem(key), setItem: (key, value) => window.localStorage.setItem(key, value) }, navigator.locks, storageStatus);
  const noteBases = new Map();
  let ratingPending = false;
  const pendingWrites = new Set();
  const plain = (v) => v && typeof v === "object" && !Array.isArray(v);
  const safeKey = (key) => typeof key === "string" && key.length < 240 && !["__proto__", "constructor", "prototype"].includes(key);
  const stringList = (v) => Array.isArray(v) ? v.filter((s) => typeof s === "string") : [];
  const signature = (card) => JSON.stringify([card.question, card.answer, card.assumptions]);
  const node = (tag, value, className) => { const el = document.createElement(tag); el.textContent = value; if (className) el.className = className; return el; };
  function renderContent(element, value) {
    // Fenced code is rendered with DOM text nodes so card text can never inject markup.
    const text = value || "", fence = /```(?:[\w+-]*)[^\S\r\n]*\r?\n([\s\S]*?)```/g;
    const parts = []; let cursor = 0, match;
    while ((match = fence.exec(text))) {
      if (match.index > cursor) parts.push(document.createTextNode(text.slice(cursor, match.index)));
      parts.push(node("code", match[1], "card-code")); cursor = fence.lastIndex;
    }
    if (cursor < text.length) parts.push(document.createTextNode(text.slice(cursor)));
    element.replaceChildren(...parts);
  }
  function notice(text) { byId("notice").textContent = text; }
  function storageStatus() {
    const message = store.failure || (!navigator.locks?.request ? "此浏览器不支持跨页写锁，写入已禁用；请使用当前版 Chrome/Edge。" : "");
    byId("storageWarning").hidden = !message;
    byId("storageMessage").textContent = message;
    byId("exportRaw").hidden = store.raw === null;
    byId("resetState").hidden = !store.blocked;
    const conflicts = current ? store.state.noteConflicts[current.id] || [] : [];
    byId("noteConflictDetails").hidden = !conflicts.length;
    byId("noteConflicts").replaceChildren(...conflicts.map((text) => node("pre", text)));
  }
  function track(promise) { pendingWrites.add(promise); promise.finally(() => pendingWrites.delete(promise)).catch(() => {}); return promise; }
  async function waitWrites() { await Promise.allSettled([...pendingWrites]); }
  function download(text, name) { const url = URL.createObjectURL(new Blob([text], { type: "application/json" })); const a = node("a", ""); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 2000); }
  const review = (card) => Progress.reviewed(store.state, card.id, signature(card));
  const due = (card) => !review(card) || review(card).due <= Date.now();
  function safeSource(value) {
    try { const u = new URL(value); return u.protocol === "https:" && u.hostname === "www.codebrick.tech" ? u.href : null; } catch { return null; }
  }
  function localUrl(value) {
    if (typeof value !== "string" || !/^snapshots\/[a-f0-9]{20}\/articles\/[a-z]{2}-[a-f0-9]{16}\.json$/.test(value)) throw new Error("文章分片路径无效。");
    return new URL(value, BASE);
  }
  function renderArticles() {
    const subject = byId("subject").value, query = byId("search").value.trim().toLocaleLowerCase();
    const list = byId("articleList"); list.replaceChildren();
    const matches = index.articles.filter((item) => (subject === "all" || item.sourceId === subject) && (item.title + " " + item.url).toLocaleLowerCase().includes(query));
    byId("inventoryCount").textContent = matches.length + " / " + index.articles.length;
    for (const item of matches) {
      const button = node("button", "", "article-button" + (item.id === current?.id ? " active" : ""));
      button.type = "button"; button.append(node("span", item.title));
      button.append(node("small", SUBJECTS[item.sourceId] + " · " + item.summary.sections + " 节 · " + (item.summary.curatedCandidates ? item.summary.curatedCandidates + " 精编 / " : "") + item.summary.atomicCandidates + " 机器候选"));
      button.setAttribute("aria-current", item.id === current?.id ? "true" : "false");
      button.addEventListener("click", () => loadArticle(item)); list.append(button);
    }
    if (!matches.length) list.append(node("p", "没有匹配的文章", "empty"));
  }
  function stats() {
    byId("articleStats").replaceChildren();
    for (const [key, label] of [["sections", "章节"], ["sourceUnits", "提取单元"], ["curatedCandidates", "精编候选"], ["atomicCandidates", "机器候选"], ["emptySections", "空提取节"]]) {
      const el = node("div", "", "stat"); el.append(node("b", current.summary[key]), document.createTextNode(label)); byId("articleStats").append(el);
    }
  }
  function candidates() {
    const unitSection = new Map(article.sections.flatMap((section) => section.units.map((unit) => [unit.id || unit.knowledgeUnitId, section.index])));
    const result = [];
    for (const draft of article.curated) {
      const supplementSections = new Map();
      for (const source of draft.document.metadata?.supplementalSources || []) {
        for (const item of source.items) for (const cardId of item.cardIds) {
          if (!supplementSections.has(cardId)) supplementSections.set(cardId, []);
          supplementSections.get(cardId).push(source.parentSectionIndex);
        }
      }
      for (const card of draft.displayCards || draft.document.cards || []) {
        if (typeof card.id !== "string" || !card.id || typeof card.question !== "string" || !card.question || typeof card.answer !== "string" || !card.answer) throw new Error("精编卡展示格式无效，请重新构建工作台。");
        const ids = card.unitIds || card.knowledgeUnitIds || [];
        result.push({ ...card, id: card.id, pool: "curated", units: ids, sections: [...new Set([...ids.map((id) => unitSection.get(id)).filter(Boolean), ...(supplementSections.get(card.id) || [])])], assumptions: stringList(card.assumptions), sourceNotes: stringList(card.sourceNotes), draft: draft.file });
      }
    }
    for (const card of article.atomicCandidates) result.push({ ...card, pool: "atomic", units: card.knowledgeUnitIds || [], sections: [card.sectionIndex], assumptions: [], sourceNotes: ["自动提取，尚未逐卡语义核验。"], draft: "" });
    return result;
  }
  function rebuildDeck() {
    if (!article) return;
    const section = byId("section").value, pool = byId("pool").value;
    let cards = candidates().filter((card) => (section === "all" || card.sections.includes(Number(section))) && (pool === "all" || card.pool === pool));
    // In combined view, keep hand-composed drafts first. Machine cards remain inspectable,
    // since sharing a source unit does not prove the draft covers all of its knowledge.
    if (byId("dueOnly").checked) cards = cards.filter(due);
    deck = cards; at = 0; renderCard();
  }
  function renderCard() {
    const card = deck[at]; byId("answerBox").hidden = true; byId("flip").hidden = false;
    byId("position").textContent = deck.length ? (at + 1) + " / " + deck.length : "0 / 0";
    byId("previous").disabled = !card || at === 0; byId("next").disabled = !card || at === deck.length - 1;
    byId("flip").disabled = !card;
    renderContent(byId("cardQuestion"), card?.question || "本筛选条件暂无候选卡片");
    renderContent(byId("cardAnswer"), card?.answer || "");
    byId("cardKind").textContent = !card ? "当前筛选无候选" : card.pool === "curated" ? "精编候选 · 未获内容批准" : "机器候选 · 待语义核验";
    byId("cardContext").textContent = card ? card.sections.map((number) => article.sections.find((s) => s.index === number)?.headingPath || "未定位章节").join(" / ") : "可切换章节或候选类型；没有卡片不代表没有知识点。";
    byId("assumptions").textContent = card?.assumptions.length ? "题面条件：" + card.assumptions.join("；") : "";
    byId("sourceNotes").textContent = card ? card.sourceNotes.join("；") : "";
    const record = card ? review(card) : null;
    byId("dueStatus").textContent = !card ? "" : record ? "已复习 " + record.count + " 次 · " + new Date(record.due).toLocaleString("zh-CN") + " 待复习" : "新候选 · 尚无本机复习记录";
    if (article) renderSources();
  }
  function reveal() { if (!deck[at]) return; byId("answerBox").hidden = false; byId("flip").hidden = true; }
  function navigate(offset) { if (!deck.length) return; at = Math.min(deck.length - 1, Math.max(0, at + offset)); renderCard(); }
  async function rate(rating) {
    const card = deck[at], pageVersion = requestId;
    if (!card || byId("answerBox").hidden || ratingPending) return;
    ratingPending = true;
    try {
      await track(store.rate(card.id, signature(card), rating));
      byId("saveStatus").textContent = "复习评分已保存到此浏览器。";
      if (pageVersion !== requestId || deck[at]?.id !== card.id) return;
      if (byId("dueOnly").checked) { deck.splice(at, 1); at = Math.max(0, Math.min(at, deck.length - 1)); renderCard(); }
      else if (at < deck.length - 1) navigate(1); else renderCard();
    } catch (error) { notice(error.message); storageStatus(); }
    finally { ratingPending = false; }
  }
  function renderSources() {
    const selected = byId("section").value, card = deck[at];
    const visible = selected !== "all" ? article.sections.filter((s) => s.index === Number(selected)) : card ? article.sections.filter((s) => card.sections.includes(s.index)) : article.sections;
    const out = byId("sourceUnits"); out.replaceChildren();
    byId("sourceCount").textContent = "（当前 " + visible.length + " 节）";
    for (const section of visible) {
      const group = node("div", "", "source-unit"); group.append(node("h3", section.index + " · " + section.headingPath));
      if (section.emptyExtraction) group.append(node("p", "空提取：需要回原网页补核图表或动态组件。", "issue"));
      for (const draft of article.curated) for (const source of draft.document.metadata?.supplementalSources || []) {
        if (source.parentSectionIndex !== section.index) continue;
        const box = node("details", "", "source-unit");
        box.append(node("summary", "补充来源候选 · " + source.id + " · " + source.items.length + " 项"));
        box.append(node("p", "快照：" + source.snapshotPath + " · SHA-256 " + source.snapshotSha256));
        box.append(node("p", "补充映射不改变静态空提取记录，也不代表独立内容验收通过。", "source-metadata"));
        const url = safeSource(source.url); if (url) { const link = node("a", "读取原来源 ↗"); link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; box.append(link); }
        for (const item of source.items) { box.append(node("h4", item.locator)); if (item.evidencePointer) box.append(node("p", "证据定位：" + item.evidencePointer, "source-metadata")); box.append(node("pre", item.text)); box.append(node("p", "关联卡：" + item.cardIds.join("、"), "source-metadata")); }
        group.append(box);
      }
      for (const unit of section.units) {
        group.append(node("div", (unit.id || unit.knowledgeUnitId || "") + " · " + (unit.tag || ""), "source-metadata"));
        group.append(node("pre", unit.text || "[此单元没有可读正文]"));
      }
      out.append(group);
    }
    const issues = byId("issues"); issues.replaceChildren();
    const selectedSections = new Set(visible.map((section) => section.index));
    const backlog = (article.unitBacklog || []).filter((item) => selectedSections.has(item.sectionIndex));
    const sectionGaps = (article.sectionBacklog || []).filter((item) => selectedSections.has(item.sectionIndex));
    issues.append(node("h3", "当前章节待核：" + backlog.length + " 条单元记录 / " + sectionGaps.length + " 条章节记录"));
    for (const item of sectionGaps) issues.append(node("div", [item.sectionIndex, item.sectionHeadingPath || item.section, item.reason].join(" · "), "issue"));
    for (const item of backlog) {
      const box = node("details", "", "issue");
      box.append(node("summary", [item.sectionIndex, item.unitId || "未提取单元", item.reason].join(" · ")));
      box.append(node("p", item.detail || "需要回原文核对后再制卡。"));
      if (item.evidence) box.append(node("pre", item.evidence));
      const url = safeSource(item.href || item.src || ""); if (url) { const link = node("a", "查看待核来源 ↗"); link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; box.append(link); }
      issues.append(box);
    }
    for (const draft of article.curated) {
      const records = draft.document.issues || [];
      for (const item of records) {
        if (!plain(item)) continue;
        const text = [item.id, item.status, item.message || item.description || item.reason || item.detail, item.resolution || item.resolutionNotes].filter((x) => typeof x === "string").join(" · ");
        issues.append(node("div", text || JSON.stringify(item), "issue"));
      }
    }
    if (!article.curated.length) issues.append(node("p", "本篇尚无全文精编候选，显示机器候选供查缺补漏；尚未完成独立内容评审。", "issue"));
  }
  async function loadArticle(item) {
    const version = ++requestId; current = item; article = null; deck = []; at = 0;
    byId("articleTitle").textContent = item.title; byId("subjectLabel").textContent = SUBJECTS[item.sourceId];
    byId("articleNotes").disabled = true; byId("articleNotes").value = "";
    byId("sourceUnits").replaceChildren(); byId("issues").replaceChildren();
    byId("cardQuestion").textContent = "正在载入这篇文章的候选…";
    byId("flip").disabled = true; byId("previous").disabled = true; byId("next").disabled = true;
    byId("answerBox").hidden = true; byId("assumptions").textContent = ""; byId("cardContext").textContent = "";
    const source = safeSource(item.url); byId("sourceLink").hidden = !source; if (source) byId("sourceLink").href = source;
    renderArticles(); stats();
    try {
      const response = await fetch(localUrl(item.file), { cache: "no-cache" });
      if (!response.ok) throw new Error("文章分片加载失败 (" + response.status + ")。");
      const raw = await response.arrayBuffer();
      if (!crypto.subtle) throw new Error("请通过 localhost 或 HTTPS 打开页面，以验证文章分片完整性。");
      const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", raw))].map((b) => b.toString(16).padStart(2, "0")).join("");
      if (hash !== item.sha256) throw new Error("文章分片与目录版本不一致，请重新构建或刷新。");
      const data = JSON.parse(new TextDecoder().decode(raw));
      if (version !== requestId) return;
      if (data.schema !== "codebrick-article-workspace" || data.version !== 1 || data.contentApproved !== false || data.article?.id !== item.id || !Array.isArray(data.sections) || !Array.isArray(data.atomicCandidates) || !Array.isArray(data.curated)) throw new Error("文章分片格式不正确。");
      article = data;
      byId("section").replaceChildren(new Option("全部章节", "all"));
      for (const section of article.sections) byId("section").append(new Option(section.index + " · " + section.headingPath + (section.emptyExtraction ? " [空提取待核]" : ""), section.index));
      byId("articleNotes").value = store.state.notes[item.id] || ""; noteBases.set(item.id, byId("articleNotes").value); byId("articleNotes").disabled = false;
      byId("saveStatus").textContent = "笔记与复习评分仅保存在此浏览器；换设备请备份、恢复。";
      history.replaceState(null, "", "#" + item.id); rebuildDeck(); notice(index.notice); storageStatus();
    } catch (error) { if (version !== requestId) return; article = null; deck = []; notice(error.message); byId("cardQuestion").textContent = "载入失败，请检查本地服务与构建输出。"; }
  }
  byId("subject").addEventListener("change", () => index && renderArticles());
  byId("search").addEventListener("input", () => index && renderArticles());
  for (const id of ["section", "pool", "dueOnly"]) byId(id).addEventListener("change", rebuildDeck);
  byId("flip").addEventListener("click", reveal);
  byId("previous").addEventListener("click", () => navigate(-1)); byId("next").addEventListener("click", () => navigate(1));
  document.querySelectorAll("[data-rating]").forEach((button) => button.addEventListener("click", () => rate(button.dataset.rating)));
  byId("articleNotes").addEventListener("input", () => {
    if (!article || !current) return;
    const id = current.id, text = byId("articleNotes").value, base = noteBases.get(id) || "";
    // Capture this edit's base before it waits for another page's lock.
    noteBases.set(id, text);
    track(store.note(id, text, base)).then((result) => {
      byId("saveStatus").textContent = result.conflict ? "另一页已修改本篇，两个版本均保留；请在下方合并。" : "笔记已保存到此浏览器。";
      if (result.conflict) noteBases.set(id, result.text);
      storageStatus();
    }).catch((error) => { notice(error.message); storageStatus(); });
  });
  document.addEventListener("keydown", (event) => { if (/INPUT|TEXTAREA|SELECT|BUTTON|SUMMARY/.test(event.target.tagName) || event.target.isContentEditable || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.code === "Space") { event.preventDefault(); reveal(); } else if (event.key === "ArrowRight") navigate(1); else if (event.key === "ArrowLeft") navigate(-1);
  });
  byId("chooseImport").addEventListener("click", () => byId("importState").click());
  byId("exportRaw").addEventListener("click", () => { if (store.raw !== null) download(store.raw, "codebrick-unreadable-original.json"); });
  byId("resetState").addEventListener("click", async () => {
    if (!confirm("将重置此浏览器的工作台记录。请先下载原始记录。确定重置？")) return;
    try { await store.reset(); if (current) { byId("articleNotes").value = ""; noteBases.set(current.id, ""); } rebuildDeck(); storageStatus(); notice("本机记录已明确重置，可以重新恢复备份。"); } catch (error) { notice(error.message); }
  });
  byId("exportState").addEventListener("click", async () => { await waitWrites(); download(JSON.stringify(store.state, null, 2), "codebrick-progress-" + new Date().toISOString().slice(0, 10) + ".json"); });
  byId("importState").addEventListener("change", async (event) => {
    const file = event.target.files?.[0]; if (!file) return;
    try {
      await waitWrites();
      // No arbitrary size ceiling: every file exported here must remain importable.
      await track(store.restore(JSON.parse(await file.text())));
      if (current) { byId("articleNotes").value = store.state.notes[current.id] || ""; noteBases.set(current.id, byId("articleNotes").value); }
      rebuildDeck(); storageStatus(); notice("进度已合并保存；不同内容版本评分与冲突笔记均保留。旧评分不会按复习次数覆盖新评分。");
    } catch (error) { notice("恢复失败：" + error.message); storageStatus(); } finally { event.target.value = ""; }
  });
  window.addEventListener("storage", (event) => {
    if (event.key !== KEY) return;
    store.sync();
    if (current && document.activeElement !== byId("articleNotes")) { byId("articleNotes").value = store.state.notes[current.id] || ""; noteBases.set(current.id, byId("articleNotes").value); }
    storageStatus(); if (article) { const showing = !byId("answerBox").hidden; renderCard(); if (showing) reveal(); }
  });
  async function initialize() {
    store.load(); storageStatus();
    try { const response = await fetch(new URL("index.json", BASE), { cache: "no-cache" }); if (!response.ok) throw new Error("目录未生成，请先运行 python scripts/build_study_workspace.py --apply。"); const value = await response.json();
      if (value.schema !== "codebrick-article-workspace" || value.version !== 1 || value.contentApproved !== false || !Array.isArray(value.articles)) throw new Error("全站目录格式不受支持。");
      index = value; renderArticles(); const target = value.articles.find((item) => item.id === location.hash.slice(1)) || value.articles.find((item) => item.summary.curatedCandidates > 0) || value.articles[0];
      if (target) await loadArticle(target); else notice("目录中没有文章。");
    } catch (error) { notice(error.message); }
  }
  initialize();
})();
