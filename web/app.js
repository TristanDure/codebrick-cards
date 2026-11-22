(() => {
  "use strict";

  const DATA_URL = "../data/cards/cards.json";
  const ARTICLES_URL = "../data/articles.json";
  const COVERAGE_URL = "../data/reports/coverage.json";
  const KNOWLEDGE_UNITS_URL = "../data/knowledge-units.json";
  const STORAGE_KEY = "codebrick-cards-v1";
  const CACHE_DB_NAME = "codebrick-cards-cache-v1";
  const MAX_IMPORT_BYTES = 32 * 1024 * 1024;
  const MAX_UNIT_REVIEW_IMPORT_BYTES = 64 * 1024 * 1024;
  const UNIT_REVIEW_SCHEMA = "codebrick-knowledge-unit-review-ledger";
  const UNIT_REVIEW_SOURCE_FIELDS = ["sourceId", "articleTitle", "articleUrl", "sectionIndex", "sectionHeadingPath", "sectionAnchor", "blockIndex", "unitIndex", "tag", "text", "href", "title", "src", "alt", "cardIds", "status", "bodySha256", "presentInCurrentSource", "machineMappingStatus"];
  const UNIT_REVIEW_LEDGER_FIELDS = [...UNIT_REVIEW_SOURCE_FIELDS, "reviewerDecision"];
  const UNIT_REVIEW_RECORD_FIELDS = ["decision", "reason", "reviewer", "examPoints", "acceptedCardIds", "reviewedAt", "sourceHash", "textHash"];
  const VIEWS = { today: "今日复习", library: "正式卡库", inbox: "候选卡", sources: "来源浏览", unitReview: "知识单元审核" };
  const SUBJECTS = { os: "操作系统", co: "计算机组成原理", cn: "计算机网络", ds: "数据结构" };
  const UNIT_REVIEW_PAGE_SIZE = 30;
  const UNIT_REVIEW_DECISIONS = new Set(["accepted", "rejected", "needs-more-evidence"]);
  const GENERIC_CARD_QUESTION = /^(?:回忆「.+」的核心定义、机制与易错点。|请解释「.+」本部分的关键概念、条件、过程与结论。)(?:（第\s*\d+\s*\/\s*\d+\s*部分）)?$/;
  const APPROVED_STATUSES = new Set(["approved", "learning", "paused", "active", "published"]);
  const HIDDEN_STATUSES = new Set(["archived", "deleted", "rejected"]);
  const REMOTE_METADATA_FIELDS = [
    "sourceId", "articlePath", "articleTitle", "articleUrl", "sectionAnchor", "sectionLevel",
    "part", "partCount", "origin", "generatorVersion", "sourceHash", "generatedQuestion",
    "generatedAnswer", "previousAnswer", "suggestedQuestion", "suggestedAnswer", "reviewReason", "sectionHeadingPath", "sectionIndex", "sectionKey",
    "knowledgeUnitIds", "cardType", "examPoints", "provenance", "auditFlags",
    "sourceSectionRemoved", "sourceArticleMissing"
  ];
  const ICON = {
    cards: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v17H6.5A2.5 2.5 0 0 1 4 17.5z"/><path d="M4 17.5A2.5 2.5 0 0 1 6.5 15H20"/></svg>',
    check: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>',
    clock: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    spark: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z"/><path d="m19 15 .8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8L19 15Z"/></svg>',
    edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5 4 4M4 20l4.2-.8L19 8.4 15.6 5 4.8 15.8z"/></svg>'
  };
  const byId = (id) => document.getElementById(id);
  const escapeHTML = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
  const statusOf = (card) => String(card.status || "pending").trim().toLowerCase().replace(/\s+/g, "_");
  const isArchived = (card) => HIDDEN_STATUSES.has(statusOf(card));
  const isApproved = (card) => APPROVED_STATUSES.has(statusOf(card));
  const dataList = (value) => value == null ? [] : (Array.isArray(value) ? value : typeof value === "string" ? value.split(/[\n,，]/) : [value]).filter((item) => item != null && String(item).trim() !== "");
  const auditSnapshot = (card) => JSON.stringify(card.auditFlags ?? []);
  const hasUnreviewedAuditFlags = (card) => card.auditFlags.length > 0 && card.reviewedAuditFlags !== auditSnapshot(card);
  const hasPlaceholderAnswer = (card) => !card.answer.trim() || /^(原文内容未能可靠提取|内容未能可靠提取|待人工核对|占位内容|placeholder\b)(?:[。.!！\s]|$)/i.test(card.answer.trim());
  const hasUnreviewedReason = (card) => Boolean(card.reviewReason) && card.reviewedReviewReason !== String(card.reviewReason);
  const hasUnreviewedSourceChange = (card) => Boolean(card.sourceSectionRemoved || card.sourceArticleMissing) && card.reviewedSourceVersion !== sourceReviewVersion(card);
  const needsExplicitReview = (card) => hasUnreviewedReason(card) || hasUnreviewedAuditFlags(card) || hasUnreviewedSourceChange(card);
  const approvalBlockReason = (card) => {
    if (!card) return "找不到这张卡片。";
    if (needsExplicitReview(card)) return "来源或审核标记尚未确认；请先完成人工核对。";
    if (hasPlaceholderAnswer(card)) return "请先补充并核实答案，再批准这张卡片。";
    const unitBlock = knowledgeUnitBlockReason(card);
    if (unitBlock) return unitBlock;
    return "";
  };
  const unitIdsOf = (card) => [...new Set([...dataList(card?.knowledgeUnitIds), ...dataList(card?.provenance?.knowledgeUnitIds)].map((id) => String(id).trim()).filter(Boolean))];
  const isConcreteUnitCard = (unit, card) => Boolean(
    card && unit && unit.presentInCurrentSource !== false &&
    dataList(unit.cardIds).map(String).includes(String(card.id)) &&
    unitIdsOf(card).includes(String(unit.knowledgeUnitId)) &&
    !isArchived(card) && card.question.trim() && card.answer.trim() &&
    !hasPlaceholderAnswer(card) && !GENERIC_CARD_QUESTION.test(card.question.trim())
  );
  const knowledgeUnitBlockReason = (card) => {
    const ids = unitIdsOf(card);
    if (!ids.length) return "卡片没有关联知识单元；请先补齐来源映射后再批准或学习。";
    if (knowledgeAuditState !== "ready") return knowledgeAuditState === "error" ? "知识单元审核数据不可用；关联卡片已暂时阻断。" : "知识单元审核数据尚未加载；关联卡片暂不进入复习。";
    const unpassed = ids.filter((id) => {
      const unit = knowledgeUnitsById.get(id);
      const record = knowledgeReviewValidity.get(id);
      return !unit || unit.presentInCurrentSource === false || record?.decision !== "accepted" || !record.acceptedCardIds.includes(String(card.id));
    });
    return unpassed.length ? `关联知识单元有 ${unpassed.length} 项尚未通过当前来源审核。` : "";
  };
  const canApproveCard = (card) => !approvalBlockReason(card);
  const isStudyEligible = (card) => isApproved(card) && canApproveCard(card);
  const isPending = (card) => !isStudyEligible(card) && !isArchived(card);
  const tagsOf = (tags) => {
    const values = Array.isArray(tags) ? tags : typeof tags === "string" ? tags.split(",") : [];
    return [...new Set(values.map((tag) => String(tag).trim()).filter(Boolean))];
  };
  const normalizeCard = (card) => {
    if (!card || typeof card !== "object" || Array.isArray(card)) return null;
    const id = String(card.id ?? "").trim();
    const question = String(card.question ?? card.front ?? "").trim();
    if (!id || !question) return null;
    return {
      ...card,
      id,
      sourceId: String(card.sourceId ?? ""),
      articlePath: String(card.articlePath ?? ""),
      articleTitle: String(card.articleTitle ?? ""),
      articleUrl: String(card.articleUrl ?? ""),
      section: String(card.section ?? ""),
      sectionAnchor: String(card.sectionAnchor ?? ""),
      question,
      answer: String(card.answer ?? card.back ?? ""),
      evidence: String(card.evidence ?? ""),
      knowledgeUnitIds: dataList(card.knowledgeUnitIds),
      cardType: String(card.cardType ?? ""),
      examPoints: dataList(card.examPoints),
      provenance: card.provenance ?? null,
      auditFlags: dataList(card.auditFlags),
      tags: tagsOf(card.tags),
      status: String(card.status || "pending"),
      origin: String(card.origin ?? "")
    };
  };
  const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const normalizeProgress = (value) => {
    const result = Object.create(null);
    if (!isRecord(value)) return result;
    for (const [id, item] of Object.entries(value)) {
      if (!isRecord(item) || ["__proto__", "prototype", "constructor"].includes(id)) continue;
      const timestamp = (candidate) => typeof candidate === "string" && Number.isFinite(Date.parse(candidate)) ? candidate : null;
      result[id] = {
        reviews: Number.isSafeInteger(item.reviews) && item.reviews > 0 ? item.reviews : 0,
        lapses: Number.isSafeInteger(item.lapses) && item.lapses > 0 ? item.lapses : 0,
        intervalDays: Number.isFinite(item.intervalDays) && item.intervalDays > 0 ? Math.min(item.intervalDays, 36_500) : 0,
        dueAt: timestamp(item.dueAt),
        lastReviewed: timestamp(item.lastReviewed),
        lastRating: ["again", "hard", "good", "easy"].includes(item.lastRating) ? item.lastRating : null
      };
    }
    return result;
  };
  const normalizeKnowledgeUnitReviews = (value) => {
    const result = Object.create(null);
    if (!isRecord(value)) return result;
    for (const [id, item] of Object.entries(value)) {
      if (!id.trim() || ["__proto__", "prototype", "constructor"].includes(id) || !isRecord(item)) continue;
      const decision = item.decision === "needs-more" ? "needs-more-evidence" : item.decision;
      if (!UNIT_REVIEW_DECISIONS.has(decision)) continue;
      result[id] = {
        decision,
        reason: String(item.reason ?? "").slice(0, 4000),
        reviewer: String(item.reviewer ?? "").slice(0, 240),
        examPoints: dataList(item.examPoints).map((point) => String(point).trim()).filter(Boolean),
        acceptedCardIds: [...new Set(dataList(item.acceptedCardIds).map((cardId) => String(cardId).trim()).filter(Boolean))],
        reviewedAt: typeof item.reviewedAt === "string" && Number.isFinite(Date.parse(item.reviewedAt)) ? item.reviewedAt : "",
        sourceHash: /^[a-f0-9]{64}$/i.test(String(item.sourceHash ?? "")) ? String(item.sourceHash).toLowerCase() : "",
        textHash: /^[a-f0-9]{64}$/i.test(String(item.textHash ?? "")) ? String(item.textHash).toLowerCase() : ""
      };
    }
    return result;
  };
  const isCompleteKnowledgeDecision = (record) => Boolean(record && UNIT_REVIEW_DECISIONS.has(record.decision) && record.reason.trim() && record.reviewer.trim() && (record.decision !== "accepted" || record.examPoints.length && record.acceptedCardIds.length));
  const knowledgeUnitReviewLedgerSignature = (value) => JSON.stringify(Object.entries(normalizeKnowledgeUnitReviews(value)).sort(([left], [right]) => left.localeCompare(right)).map(([id, record]) => [id, ...UNIT_REVIEW_RECORD_FIELDS.map((field) => record[field])]));
  async function persistedKnowledgeUnitReviewsMatch(expected) {
    const signature = knowledgeUnitReviewLedgerSignature(expected);
    try {
      const saved = normalizeSaved(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null"));
      if (knowledgeUnitReviewLedgerSignature(saved.knowledgeUnitReviews) === signature) return "localStorage";
    } catch {}
    try {
      const saved = normalizeSaved(await readStudyStateCache());
      if (knowledgeUnitReviewLedgerSignature(saved.knowledgeUnitReviews) === signature) return "IndexedDB";
    } catch {}
    return "";
  }
  const unitReviewSourceSnapshot = (unit) => UNIT_REVIEW_SOURCE_FIELDS.map((field) => {
    if (field === "cardIds") return [...new Set(dataList(unit?.[field]).map(String))].sort();
    if (field === "presentInCurrentSource") return unit?.[field] !== false;
    return String(unit?.[field] ?? "");
  });
  const unitReviewLedgerSnapshot = (unit) => UNIT_REVIEW_LEDGER_FIELDS.map((field) => {
    if (field === "cardIds") return [...new Set(dataList(unit?.[field]).map(String))].sort();
    if (field === "presentInCurrentSource") return unit?.[field] !== false;
    return String(unit?.[field] ?? "");
  });
  const sameUnitSource = (left, right) => JSON.stringify(unitReviewLedgerSnapshot(left)) === JSON.stringify(unitReviewLedgerSnapshot(right));
  const sourceReviewVersion = (card) => JSON.stringify([
    String(card.sourceHash || ""), String(card.suggestedQuestion || ""), String(card.suggestedAnswer || ""),
    Boolean(card.sourceSectionRemoved), Boolean(card.sourceArticleMissing)
  ]);
  const localDateKey = (date = new Date()) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  const structuredText = (value) => {
    if (value == null || value === "") return "";
    if (["string", "number", "boolean"].includes(typeof value)) return String(value);
    if (Array.isArray(value)) return value.map(structuredText).filter(Boolean).join("\n");
    if (isRecord(value)) return Object.entries(value).filter(([key]) => !["__proto__", "prototype", "constructor"].includes(key)).map(([key, item]) => key + ": " + structuredText(item)).filter((line) => !line.endsWith(": ")).join("\n");
    return "";
  };
  const evidenceText = (card) => {
    if (isRecord(card.provenance)) for (const key of ["sourceParagraph", "excerpt", "quote", "paragraph", "text", "evidence"]) if (typeof card.provenance[key] === "string" && card.provenance[key].trim()) return card.provenance[key].trim();
    return card.evidence.trim();
  };
  const sourceReviewLabel = (reason) => ({ "source-extraction-incomplete": "来源正文提取不完整", "source-section-removed": "来源章节已变更", "source-article-missing": "来源文章缺失" })[String(reason || "")] || String(reason || "");
  const validUrl = (value) => {
    try {
      const url = new URL(value);
      return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
    } catch { return ""; }
  };

  let cards = [];
  let progress = {};
  let knowledgeUnitReviews = Object.create(null);
  const knowledgeUnitSavesInFlight = new Set();
  let knowledgeReviewValidity = new Map();
  let knowledgeUnits = [];
  let knowledgeUnitsById = new Map();
  let knowledgeAuditState = "idle";
  let knowledgeAuditError = "";
  let knowledgeAuditPromise = null;
  let knowledgeHashUnavailable = false;
  let unitReviewSubject = "all";
  let unitReviewStatus = "unpassed";
  let unitReviewPage = 0;
  let focusedKnowledgeUnitId = "";
  let articleCatalog = [];
  let sourceSubject = "all";
  let selectedSubject = "all";
  let selectedArticleKey = "";
  let selectedSource = null;
  let sourceLoadState = "idle";
  let sourceLoadKey = "";
  let articleLoadState = "idle";
  let articleLoadError = "";
  let selectedSectionAnchor = "";
  let sourceCardsIndexFor = null;
  let sourceCardsIndex = new Map();
  let remoteBaseCards = new Map();
  const requestedView = window.location.hash.slice(1);
  let view = VIEWS[requestedView] ? requestedView : "today";
  let statusFilter = "all";
  let tagFilter = "all";
  let search = "";
  let flippedId = "";
  let studyTargetId = "";
  let toastTimer;

  function normalizeSaved(saved) {
    if (!saved || ![1, 2, 3].includes(saved.version)) return { cards: [], overrides: [], progress: {}, knowledgeUnitReviews: Object.create(null), settings: {}, savedAt: "" };
    if (saved.version >= 2) {
      const localCards = [];
      const overrides = [];
      for (const entry of Array.isArray(saved.cards) ? saved.cards : []) {
        if (!isRecord(entry)) continue;
        if (entry.kind === "local") { const card = normalizeCard(entry.card); if (card) localCards.push(card); }
        else if (entry.kind === "override" && typeof entry.id === "string" && isRecord(entry.values)) overrides.push({ id: entry.id, values: entry.values });
      }
      return { cards: localCards, overrides, progress: normalizeProgress(saved.progress), knowledgeUnitReviews: normalizeKnowledgeUnitReviews(saved.knowledgeUnitReviews), settings: isRecord(saved.settings) ? saved.settings : {}, savedAt: String(saved.savedAt || "") };
    }
    return { cards: Array.isArray(saved.cards) ? saved.cards.map(normalizeCard).filter(Boolean) : [], overrides: [], progress: normalizeProgress(saved.progress), knowledgeUnitReviews: normalizeKnowledgeUnitReviews(saved.knowledgeUnitReviews), settings: {}, savedAt: String(saved.savedAt || "") };
  }

  function readSaved() {
    try { return normalizeSaved(JSON.parse(localStorage.getItem(STORAGE_KEY) || "null")); }
    catch { return normalizeSaved(null); }
  }

  async function readBestSaved() {
    const local = readSaved();
    let cachedRaw = null;
    try { cachedRaw = await readStudyStateCache(); } catch {}
    const cached = normalizeSaved(cachedRaw);
    const localTime = Date.parse(local.savedAt || "") || 0;
    const cachedTime = Date.parse(cached.savedAt || "") || 0;
    if (cachedRaw && cachedTime > localTime) {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(cachedRaw)); } catch {}
      return cached;
    }
    return local;
  }

  function openCardCache() {
    if (!window.indexedDB) return Promise.reject(new Error("IndexedDB is unavailable."));
    return new Promise((resolve, reject) => {
      const request = window.indexedDB.open(CACHE_DB_NAME, 1);
      request.addEventListener("upgradeneeded", () => {
        if (!request.result.objectStoreNames.contains("snapshots")) request.result.createObjectStore("snapshots");
      });
      request.addEventListener("success", () => resolve(request.result), { once: true });
      request.addEventListener("error", () => reject(request.error || new Error("Could not open the offline card cache.")), { once: true });
      request.addEventListener("blocked", () => reject(new Error("The offline card cache is blocked.")), { once: true });
    });
  }

  async function writeCardCache(remoteCards) {
    const database = await openCardCache();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction("snapshots", "readwrite");
      transaction.objectStore("snapshots").put({ version: 1, cards: remoteCards }, "cards");
      transaction.addEventListener("complete", () => { database.close(); resolve(); }, { once: true });
      transaction.addEventListener("error", () => { database.close(); reject(transaction.error || new Error("Could not save the offline card cache.")); }, { once: true });
      transaction.addEventListener("abort", () => { database.close(); reject(transaction.error || new Error("Could not save the offline card cache.")); }, { once: true });
    });
  }

  function writeStudyStateCache(state) {
    return openCardCache().then((database) => new Promise((resolve, reject) => {
      const transaction = database.transaction("snapshots", "readwrite");
      transaction.objectStore("snapshots").put(state, "study-state");
      transaction.addEventListener("complete", () => { database.close(); resolve(); }, { once: true });
      transaction.addEventListener("error", () => { database.close(); reject(transaction.error || new Error("Could not save the study backup.")); }, { once: true });
      transaction.addEventListener("abort", () => { database.close(); reject(transaction.error || new Error("Could not save the study backup.")); }, { once: true });
    }));
  }

  function readStudyStateCache() {
    return openCardCache().then((database) => new Promise((resolve, reject) => {
      const transaction = database.transaction("snapshots", "readonly");
      const request = transaction.objectStore("snapshots").get("study-state");
      let result;
      request.addEventListener("success", () => { result = request.result; }, { once: true });
      transaction.addEventListener("complete", () => { database.close(); resolve(result); }, { once: true });
      transaction.addEventListener("error", () => { database.close(); reject(transaction.error || new Error("Could not read the study backup.")); }, { once: true });
      transaction.addEventListener("abort", () => { database.close(); reject(transaction.error || new Error("Could not read the study backup.")); }, { once: true });
    }));
  }

  async function readCardCache() {
    const database = await openCardCache();
    return new Promise((resolve, reject) => {
      const transaction = database.transaction("snapshots", "readonly");
      const request = transaction.objectStore("snapshots").get("cards");
      let result;
      request.addEventListener("success", () => { result = request.result; }, { once: true });
      transaction.addEventListener("complete", () => { database.close(); resolve(result); }, { once: true });
      transaction.addEventListener("error", () => { database.close(); reject(transaction.error || new Error("Could not read the offline card cache.")); }, { once: true });
      transaction.addEventListener("abort", () => { database.close(); reject(transaction.error || new Error("Could not read the offline card cache.")); }, { once: true });
    });
  }

  let persistenceQueue = Promise.resolve();
  function save() {
    try {
      const savedCards = [];
      for (const card of cards) {
        const remote = remoteBaseCards.get(card.id);
        if (!remote) { savedCards.push({ kind: "local", card }); continue; }
        const values = Object.create(null);
        for (const field of Object.keys(card)) {
          if (["id", "__proto__", "prototype", "constructor"].includes(field) || REMOTE_METADATA_FIELDS.includes(field)) continue;
          if (JSON.stringify(card[field]) !== JSON.stringify(remote[field])) values[field] = card[field];
        }
        if (Object.keys(values).length) savedCards.push({ kind: "override", id: card.id, values });
      }
      const envelope = { version: 3, savedAt: new Date().toISOString(), cards: savedCards, progress, knowledgeUnitReviews, settings: { sourceSubject } };
      let localSaved = true;
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(envelope)); } catch { localSaved = false; }
      persistenceQueue = persistenceQueue.catch(() => {}).then(() => writeStudyStateCache(envelope));
      persistenceQueue.then(() => { if (!localSaved) byId("storageStatus").textContent = "学习记录已保存到本机数据库"; }).catch(() => {
        if (!localSaved) { byId("storageStatus").textContent = "保存失败，请立即导出备份"; showNotice("浏览器本地存储空间不足，数据库备份也未成功。请先导出备份。", true); }
      });
      byId("storageStatus").textContent = localSaved ? "已自动保存（含本机数据库备份）" : "正在写入本机数据库…";
      return true;
    } catch {
      byId("storageStatus").textContent = "保存失败，请立即导出备份";
      showNotice("本机无法保存更改。请导出备份并检查浏览器存储空间。", true);
      return false;
    }
  }

  async function sha256Text(value) {
    if (!window.crypto?.subtle || !window.TextEncoder) throw new Error("本机浏览器不支持 SHA-256 正文校验；审核结论未保存。");
    const bytes = new TextEncoder().encode(String(value ?? ""));
    const digest = await window.crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  async function knowledgeUnitSourceHash(unit) {
    if (!window.crypto?.subtle || !window.TextEncoder) throw new Error("This browser cannot verify knowledge-unit sources. No review was saved.");
    const bytes = new TextEncoder().encode(JSON.stringify(unitReviewSourceSnapshot(unit)));
    const digest = await window.crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  async function validateSavedKnowledgeReviews() {
    const valid = new Map();
    const entries = Object.entries(knowledgeUnitReviews).filter(([id, record]) => knowledgeUnitsById.has(id) && isCompleteKnowledgeDecision(record) && /^[a-f0-9]{64}$/.test(record.sourceHash));
    knowledgeHashUnavailable = false;
    for (let start = 0; start < entries.length; start += 64) {
      const batch = entries.slice(start, start + 64);
      await Promise.all(batch.map(async ([id, record]) => {
        try {
          const unit = knowledgeUnitsById.get(id);
          const validCardIds = record.acceptedCardIds.filter((cardId) => isConcreteUnitCard(unit, cards.find((card) => card.id === cardId)));
          const allClaimedCardsValid = validCardIds.length === record.acceptedCardIds.length;
          if (allClaimedCardsValid && await knowledgeUnitSourceHash(unit) === record.sourceHash && await sha256Text(unit.text) === record.textHash) valid.set(id, record);
        } catch { knowledgeHashUnavailable = true; }
      }));
      if (start + 64 < entries.length) await new Promise((resolve) => window.setTimeout(resolve, 0));
    }
    knowledgeReviewValidity = valid;
  }

  async function ensureKnowledgeAuditLoaded(force = false) {
    if (!force && knowledgeAuditState === "ready") return true;
    if (!force && knowledgeAuditPromise) return knowledgeAuditPromise;
    knowledgeAuditState = "loading";
    knowledgeAuditError = "";
    knowledgeAuditPromise = (async () => {
      const [coverageResponse, unitsResponse] = await Promise.all([
        fetch(new URL(COVERAGE_URL, window.location.href), { cache: "no-cache" }),
        fetch(new URL(KNOWLEDGE_UNITS_URL, window.location.href), { cache: "no-cache" })
      ]);
      if (!coverageResponse.ok || !unitsResponse.ok) throw new Error("Coverage or current knowledge-unit ledger could not be loaded.");
      const [coverage, unitFile] = await Promise.all([coverageResponse.json(), unitsResponse.json()]);
      const coverageLedger = coverage?.knowledgeUnitLedger;
      if (coverage?.version !== 2 || unitFile?.version !== 2 || coverageLedger?.version !== 2 || !Array.isArray(coverage?.knowledgeUnits) || !Array.isArray(coverageLedger.units) || !Array.isArray(unitFile?.units)) throw new Error("Coverage and knowledge-unit ledger schema/version disagree; approval and study remain blocked.");

      const currentById = new Map();
      for (const unit of coverage.knowledgeUnits) {
        const id = String(unit?.knowledgeUnitId ?? "");
        if (!id || currentById.has(id) || unit.presentInCurrentSource === false) throw new Error("Coverage contains an invalid, duplicate, or retired current knowledge-unit ID.");
        currentById.set(id, unit);
      }
      const ledgerById = new Map();
      const nextUnits = [];
      const nextById = new Map();
      for (const raw of unitFile.units) {
        const id = String(raw?.knowledgeUnitId ?? "");
        if (!/^[a-f0-9]{16}$/.test(id) || ledgerById.has(id) || typeof raw.presentInCurrentSource !== "boolean") throw new Error("The current knowledge-unit ledger contains an invalid or duplicate ID/source state.");
        ledgerById.set(id, raw);
        if (raw.presentInCurrentSource !== false) {
          const audited = currentById.get(id);
          if (!audited || !sameUnitSource(raw, audited)) throw new Error("Coverage and current ledger source fields, locator, mapping, or IDs disagree; approval and study remain blocked.");
        }
        const unit = { ...raw, text: String(raw.text ?? ""), cardIds: dataList(raw.cardIds).map(String), coverageStatus: String(raw.status ?? "unknown") };
        nextUnits.push(unit);
        nextById.set(id, unit);
      }
      if (currentById.size !== nextUnits.filter((unit) => unit.presentInCurrentSource !== false).length || [...currentById.keys()].some((id) => !ledgerById.has(id))) throw new Error("Coverage and current-source ledger ID sets disagree; approval and study remain blocked.");

      const coverageHistory = new Map();
      for (const unit of coverageLedger.units) {
        const id = String(unit?.knowledgeUnitId ?? "");
        if (!id || coverageHistory.has(id)) throw new Error("Coverage's retained ledger contains an invalid or duplicate ID.");
        coverageHistory.set(id, unit);
      }
      if (coverageHistory.size !== ledgerById.size || [...ledgerById].some(([id, unit]) => !coverageHistory.has(id) || !sameUnitSource(unit, coverageHistory.get(id)))) throw new Error("Coverage's retained current/retired ledger disagrees with the current ledger; approval and study remain blocked.");

      const activeUnits = nextUnits.filter((unit) => unit.presentInCurrentSource !== false);
      const mapped = activeUnits.filter((unit) => dataList(unit.cardIds).length).length;
      const retiredCount = nextUnits.length - activeUnits.length;
      const countMatches = (object, key, expected) => Number.isSafeInteger(object?.[key]) && object[key] === expected;
      for (const [object, name] of [[coverage, "coverage"], [coverageLedger, "coverage's ledger"], [unitFile, "current ledger"]]) {
        if (!countMatches(object, "knowledgeUnitCount", activeUnits.length) || !countMatches(object, "mappedKnowledgeUnitCount", mapped) || !countMatches(object, "unmappedKnowledgeUnitCount", activeUnits.length - mapped)) throw new Error(`${name} summary counts disagree with the current knowledge-unit rows; approval and study remain blocked.`);
      }
      if (!countMatches(coverage, "retiredKnowledgeUnitCount", retiredCount)) throw new Error("Coverage's retired-unit count disagrees with the retained ledger.");
      const decisionCounts = activeUnits.reduce((counts, unit) => { const rawDecision = String(unit.reviewerDecision ?? "pending"); const decision = rawDecision === "needs-more" ? "needs-more-evidence" : rawDecision; counts[decision] = (counts[decision] || 0) + 1; return counts; }, Object.create(null));
      if (!countMatches(coverage, "humanAcceptedKnowledgeUnitCount", decisionCounts.accepted || 0) || !countMatches(coverage, "reviewedKnowledgeUnitCount", decisionCounts.accepted || 0) || !countMatches(coverage, "humanRejectedKnowledgeUnitCount", decisionCounts.rejected || 0) || !countMatches(coverage, "staleKnowledgeUnitReviewCount", decisionCounts.stale || 0) || !countMatches(coverage, "pendingKnowledgeUnitReviewCount", (decisionCounts.pending || 0) + (decisionCounts["needs-more-evidence"] || 0) + (decisionCounts[""] || 0))) throw new Error("Coverage's human-review totals disagree with the current ledger; approval and study remain blocked.");

      knowledgeUnits = nextUnits;
      knowledgeUnitsById = nextById;
      await validateSavedKnowledgeReviews();
      knowledgeAuditState = "ready";
      return true;
    })().catch((error) => {
      knowledgeAuditState = "error";
      knowledgeUnits = [];
      knowledgeUnitsById = new Map();
      knowledgeReviewValidity = new Map();
      knowledgeHashUnavailable = false;
      knowledgeAuditError = error instanceof Error ? error.message : "Knowledge-unit review data is unavailable.";
      return false;
    }).finally(() => {
      knowledgeAuditPromise = null;
      if (view === "unitReview") render();
    });
    return knowledgeAuditPromise;
  }

  function getKnowledgeDecisionState(unit) {
    const record = knowledgeUnitReviews[unit.knowledgeUnitId];
    if (!record) return "pending";
    if (!knowledgeUnitsById.has(unit.knowledgeUnitId)) return knowledgeHashUnavailable ? "unverified" : "stale";
    if (!knowledgeReviewValidity.has(unit.knowledgeUnitId)) return knowledgeHashUnavailable ? "unverified" : "stale";
    return record.decision;
  }

  function getProgress(id) {
    const value = progress[id];
    return value && typeof value === "object" ? value : { reviews: 0, lapses: 0, intervalDays: 0, dueAt: null, lastReviewed: null };
  }

  const approvedCards = () => cards.filter(isStudyEligible);
  const pendingCards = () => cards.filter(isPending);
  function dueCards() {
    const now = Date.now();
    return approvedCards().filter((card) => {
      if (statusOf(card) === "paused") return false;
      const due = Date.parse(getProgress(card.id).dueAt || "");
      return !due || due <= now;
    }).sort((a, b) => (Date.parse(getProgress(a.id).dueAt || "") || 0) - (Date.parse(getProgress(b.id).dueAt || "") || 0));
  }

  function reviewedToday() {
    const today = localDateKey();
    return approvedCards().filter((card) => {
      const timestamp = Date.parse(getProgress(card.id).lastReviewed || "");
      return Number.isFinite(timestamp) && localDateKey(new Date(timestamp)) === today;
    }).length;
  }

  function matchesSearch(card, term) {
    if (!term) return true;
    const text = [card.question, card.answer, evidenceText(card), card.articleTitle, card.section, card.cardType, card.knowledgeUnitIds.map(structuredText).join(" "), card.examPoints.map(structuredText).join(" "), card.tags.join(" ")].join(" ").toLocaleLowerCase();
    return text.includes(term);
  }

  function showNotice(message, error = false) {
    const notice = byId("noticeBar");
    notice.textContent = message;
    notice.className = `notice-bar${error ? " error" : ""}`;
    window.clearTimeout(showNotice.timer);
    showNotice.timer = window.setTimeout(() => notice.classList.add("is-hidden"), 9000);
  }

  function toast(message) {
    const element = byId("toast");
    element.textContent = message;
    element.classList.add("is-visible");
    window.clearTimeout(toastTimer);
    toastTimer = window.setTimeout(() => element.classList.remove("is-visible"), 2600);
  }

  function renderIntro() {
    const content = {
      today: ["今日复习，稳步积累。", "先回忆，再核对；只有通过审核的卡片才会进入正式复习。"],
      library: ["已通过审核的卡片。", "在这里复习和整理已确认可用的知识卡。"],
      inbox: ["候选卡审核与浏览。", "候选卡不会自动进入正式复习，可按来源逐章检查。"],
      sources: ["按来源逐章浏览。", "核对原文段落、章节关联与待审核提示；原始 HTML 仅解析为安全文本。"],
      unitReview: ["知识单元人工审核。", "浏览完整来源语料，核对原文与定位后逐项记录结论。筛选只影响当前列表，不代表全库或章节已完成审核。"]
    }[view];
    const studyAction = view !== "today" && view !== "unitReview" ? '<button class="button button-primary" type="button" data-view="today">开始复习 ' + ICON.clock + "</button>" : "";
    byId("pageIntro").innerHTML = `<div><h1>${escapeHTML(content[0])}</h1><p>${escapeHTML(content[1])}</p></div><div class="page-intro-actions"><span class="intro-date"><strong>${new Intl.DateTimeFormat("zh-CN", { weekday: "long", month: "long", day: "numeric" }).format(new Date())}</strong></span>${studyAction}</div>`;
    byId("contextPage").textContent = VIEWS[view];
  }

  function statCard(icon, tone, label, value, caption) {
    return `<article class="stat-card"><div class="stat-top"><span>${label}</span><span class="stat-icon ${tone}">${icon}</span></div><div class="stat-bottom"><strong class="stat-value">${value}</strong><span class="stat-caption">${caption}</span></div></article>`;
  }

  function renderStats() {
    const due = dueCards().length;
    const studied = reviewedToday();
    const library = approvedCards().length;
    const inbox = pendingCards().length;
    if (view === "today") byId("statsGrid").innerHTML = statCard(ICON.clock, "green", "待复习", due, "张已通过审核的卡") + statCard(ICON.check, "blue", "今日已复习", studied, "张卡片") + statCard(ICON.cards, "amber", "正式卡库", library, "张已批准卡");
    else if (view === "library") byId("statsGrid").innerHTML = statCard(ICON.cards, "green", "正式复习卡", library, "张已批准卡") + statCard(ICON.clock, "blue", "今日待复习", due, "张到期卡") + statCard(ICON.spark, "amber", "今日已复习", studied, "张卡片");
    else if (view === "inbox") byId("statsGrid").innerHTML = statCard(ICON.cards, "amber", "候选待审核", inbox, "张不会自动进入复习") + statCard(ICON.check, "green", "正式复习卡", library, "张已批准卡") + statCard(ICON.spark, "blue", "今日已复习", studied, "张卡片");
    else if (view === "unitReview") {
      const active = knowledgeUnits.filter((unit) => unit.presentInCurrentSource !== false);
      const accepted = active.filter((unit) => unitDecisionIsCurrent(unit, knowledgeReviewValidity.get(unit.knowledgeUnitId))).length;
      const stale = active.filter((unit) => ["stale", "unverified"].includes(getKnowledgeDecisionState(unit))).length;
      byId("statsGrid").innerHTML = statCard(ICON.cards, "blue", "当前来源单元", active.length.toLocaleString(), "全量；不受筛选影响") + statCard(ICON.check, "green", "有效验收", accepted.toLocaleString(), "已核验来源与 408 映射") + statCard(ICON.clock, "amber", "待处理 / 过期", Math.max(0, active.length - accepted).toLocaleString(), `${stale.toLocaleString()} 项来源已变更或无法验证`);
    } else byId("statsGrid").innerHTML = statCard(ICON.cards, "green", "来源文章", articleCatalog.length, "篇目录记录") + statCard(ICON.clock, "blue", "卡片章节", new Set(cards.map((card) => [card.sourceId, card.articlePath, card.sectionAnchor || card.section].join("|"))).size, "个已登记章节") + statCard(ICON.spark, "amber", "待审核卡", inbox, "张尚未放行");
  }

  function renderFilters() {
    const items = view === "library" ? approvedCards() : pendingCards();
    if (view === "unitReview") { renderKnowledgeUnitReviewFilters(); return; }
    if (view === "sources") { renderSourceFilters(); return; }
    if (view === "today") {
      byId("filterRow").innerHTML = `<div class="filter-start"><span class="filter-label">今日仅复习已通过审核的卡片</span></div><span class="result-count">已复习 ${reviewedToday()} 张</span>`;
      return;
    }
    if (view === "inbox" && !items.length) {
      byId("filterRow").innerHTML = '<div class="filter-start"><span class="filter-label">候选卡可浏览和审核，但不会自动进入正式复习。</span></div><span class="result-count">当前没有候选卡</span>';
      return;
    }
    const tags = [...new Set(items.flatMap((card) => card.tags))].sort((a, b) => a.localeCompare(b));
    const status = view === "library" ? '<select id="statusFilter" class="filter-select" aria-label="按学习状态筛选"><option value="all">全部状态</option><option value="learning">学习中</option><option value="new">未开始</option><option value="paused">已暂停</option></select>' : "";
    const topic = tags.length ? `<select id="tagFilter" class="filter-select" aria-label="按主题筛选"><option value="all">全部主题</option>${tags.map((tag) => `<option value="${escapeHTML(tag)}">${escapeHTML(tag)}</option>`).join("")}</select>` : "";
    byId("filterRow").innerHTML = `<div class="filter-start"><span class="filter-label">${view === "library" ? "浏览正式卡库" : "候选卡浏览与审核"}</span>${status}${topic}</div><span class="result-count" id="resultCount"></span>`;
    if (byId("statusFilter")) byId("statusFilter").value = statusFilter;
    if (byId("tagFilter")) byId("tagFilter").value = tagFilter;
  }

  const UNIT_REVIEW_STATE_LABELS = { pending: "待审核", accepted: "已接受", rejected: "已拒绝", "needs-more-evidence": "需补充证据", stale: "过期 · 来源已变更", unverified: "无法验证", retired: "已退役" };

  function renderKnowledgeUnitReviewFilters() {
    const subjectOptions = Object.entries(SUBJECTS).map(([id, title]) => `<option value="${id}">${escapeHTML(title)}</option>`).join("");
    byId("filterRow").innerHTML = `<div class="filter-start"><label class="filter-label" for="unitReviewSubject">科目</label><select id="unitReviewSubject" class="filter-select" aria-label="按科目筛选知识单元"><option value="all">全部科目</option>${subjectOptions}</select><label class="filter-label" for="unitReviewStatus">审核状态</label><select id="unitReviewStatus" class="filter-select" aria-label="按审核状态筛选知识单元"><option value="unpassed">待审核 / 未接受</option><option value="all">全部单元（含已退役）</option><option value="pending">待审核</option><option value="accepted">当前已接受</option><option value="rejected">已拒绝</option><option value="needs-more-evidence">需补充证据</option><option value="stale">过期 / 无法验证</option><option value="retired">已退役历史</option></select><button class="button button-secondary" type="button" data-action="refresh-unit-review"${knowledgeAuditState === "loading" ? " disabled" : ""}>重新核验来源</button><button class="button button-secondary" type="button" data-action="export-unit-reviews">导出审核台账</button><button class="button button-secondary" type="button" data-action="import-unit-reviews">导入审核台账</button></div><span class="result-count" id="unitReviewResultCount"></span>`;
    byId("unitReviewSubject").value = unitReviewSubject;
    byId("unitReviewStatus").value = unitReviewStatus;
  }

  function knowledgeUnitSearchText(unit) {
    const record = knowledgeUnitReviews[unit.knowledgeUnitId];
    return [unit.knowledgeUnitId, unit.sourceId, SUBJECTS[unit.sourceId] || "", unit.articleTitle, unit.articleUrl, unit.sectionIndex, unit.sectionHeadingPath, unit.sectionAnchor, unit.blockIndex, unit.unitIndex, unit.tag, unit.text, unit.href, unit.title, unit.src, unit.alt, dataList(unit.cardIds).join(" "), unit.status, record?.decision, record?.reason, record?.reviewer, dataList(record?.examPoints).join(" ")].join(" ").toLocaleLowerCase();
  }

  function renderKnowledgeUnitReview() {
    if (knowledgeAuditState === "idle" || knowledgeAuditState === "loading") {
      if (knowledgeAuditState === "idle") void ensureKnowledgeAuditLoaded();
      byId("viewContent").innerHTML = emptyMarkup("正在加载完整知识单元台账", "正在核对全量 coverage 报告与来源台账；核验完成前不会允许审核、批准或学习。", "");
      return;
    }
    if (knowledgeAuditState === "error") {
      byId("viewContent").innerHTML = `<section class="unit-review-alert" role="alert"><h2>知识单元审核已安全阻断</h2><p>${escapeHTML(knowledgeAuditError || "无法验证 coverage 报告与当前来源台账。")}</p><button class="button button-secondary" type="button" data-action="retry-unit-review">重新核验来源</button></section>`;
      byId("unitReviewResultCount").textContent = "台账不可用";
      return;
    }

    const current = knowledgeUnits.filter((unit) => unitReviewSubject === "all" || unit.sourceId === unitReviewSubject);
    const statusOfUnit = (unit) => getKnowledgeDecisionState(unit);
    const filtered = current.filter((unit) => {
      const retired = unit.presentInCurrentSource === false;
      const state = retired ? "retired" : statusOfUnit(unit);
      const statusMatches = unitReviewStatus === "all" || (unitReviewStatus === "unpassed" ? !retired && state !== "accepted" : unitReviewStatus === "stale" ? state === "stale" || state === "unverified" : unitReviewStatus === "retired" ? retired : state === unitReviewStatus);
      const query = search.trim().toLocaleLowerCase();
      return statusMatches && (!query || knowledgeUnitSearchText(unit).includes(query));
    });
    const pageCount = Math.max(1, Math.ceil(filtered.length / UNIT_REVIEW_PAGE_SIZE));
    unitReviewPage = Math.min(unitReviewPage, pageCount - 1);
    const start = unitReviewPage * UNIT_REVIEW_PAGE_SIZE;
    const page = filtered.slice(start, start + UNIT_REVIEW_PAGE_SIZE);
    byId("unitReviewResultCount").textContent = `${filtered.length.toLocaleString()} 条匹配 · 所选科目 ${current.length.toLocaleString()} 项`;
    const cardsById = new Map(cards.map((card) => [card.id, card]));
    const rows = page.map((unit) => {
      const id = String(unit.knowledgeUnitId);
      const record = knowledgeUnitReviews[id];
      const retired = unit.presentInCurrentSource === false;
      const state = retired ? "retired" : statusOfUnit(unit);
      const baseUrl = validUrl(String(unit.articleUrl || ""));
      const href = baseUrl ? `${baseUrl.split("#", 1)[0]}${unit.sectionAnchor ? `#${encodeURIComponent(String(unit.sectionAnchor))}` : ""}` : "";
      const locator = [unit.sectionIndex ? `章节 ${unit.sectionIndex}` : "", unit.sectionHeadingPath, unit.blockIndex ? `区块 ${unit.blockIndex}` : "", unit.unitIndex ? `单元 ${unit.unitIndex}` : "", unit.tag ? `<${unit.tag}>` : ""].filter(Boolean).join(" · ");
      const sourceLink = href ? `<a class="unit-source-link" href="${escapeHTML(href)}" target="_blank" rel="noopener noreferrer">打开原文对应章节 ↗</a>` : `<span class="unit-source-link is-unavailable">来源链接不可用</span>`;
      const attrs = [["href", unit.href], ["title", unit.title], ["src", unit.src], ["alt", unit.alt]].filter(([, value]) => String(value || "").trim());
      const sourceAttrs = attrs.map(([name, value]) => name === "href" || name === "src" ? `<div><strong>${name}</strong> ${validUrl(String(value)) ? `<a href="${escapeHTML(validUrl(String(value)))}" target="_blank" rel="noopener noreferrer">${escapeHTML(value)}</a>` : escapeHTML(value)}</div>` : `<div><strong>${name}</strong> ${escapeHTML(value)}</div>`).join("");
      const image = validUrl(String(unit.src || "")) ? `<img class="unit-source-image" src="${escapeHTML(validUrl(String(unit.src)))}" alt="${escapeHTML(unit.alt || "来源图片")}" loading="lazy" referrerpolicy="no-referrer">` : "";
      const related = dataList(unit.cardIds).map((cardId) => cardsById.get(String(cardId))).filter(Boolean).map((card) => `<button type="button" class="unit-related-card" data-action="details" data-id="${escapeHTML(card.id)}">${escapeHTML(card.question || card.id)}</button>`).join("");
      const history = record ? `<details class="unit-review-history"><summary>已保存的决定：${escapeHTML(record.decision === "needs-more" ? "needs-more-evidence" : record.decision)} · ${escapeHTML(record.reviewer || "审核人未记录")} · ${escapeHTML(record.reviewedAt || "日期未记录")}</summary><p>${escapeHTML(record.reason || "未记录理由。")}</p>${record.examPoints.length ? `<p><strong>408 考点映射：</strong>${escapeHTML(record.examPoints.join(" · "))}</p>` : ""}${!knowledgeReviewValidity.has(id) && !retired ? `<p class="unit-stale-note">此结论作为历史记录保留，但因当前来源字段已变化或无法核验，不再对当前来源生效。</p>` : ""}</details>` : "";
      const decisionForm = retired ? `<p class="unit-retired-note">来源中已不存在此单元。历史结论仍保留，但不能用于批准当前卡片。</p>` : `<form class="unit-review-form" data-unit-review-id="${escapeHTML(id)}"><label class="unit-field"><span>审核人 <em>必填</em></span><input name="reviewer" maxlength="240" autocomplete="name" required placeholder="审核人姓名"></label><label class="unit-field unit-reason-field"><span>审核理由 <em>必填</em></span><textarea name="reason" rows="2" maxlength="4000" required placeholder="说明对来源、准确性、原子性和适用性的审核判断"></textarea></label><label class="unit-field unit-points-field"><span>408 考点映射 <em>接受时必填</em></span><input name="examPoints" maxlength="2400" placeholder="填写考点编号或名称；多项用逗号分隔"><small>需由审核人明确填写；考点映射本身不替代考纲或真题核验。</small></label><label class="unit-field"><span>对应原子卡片 <em>接受时至少选一张</em></span><select name="acceptedCardIds" multiple size="4">${dataList(unit.cardIds).map((cardId) => cardsById.get(String(cardId))).filter((card) => isConcreteUnitCard(unit, card)).map((card) => `<option value="${escapeHTML(card.id)}">${escapeHTML(card.question)} · ${escapeHTML(card.id)}</option>`).join("")}</select><small>只列出本单元实际关联、题面非模板且答案非占位的卡片；按住 Ctrl / ⌘ 可多选。</small></label><div class="unit-decision-actions"><button type="button" class="button button-primary" data-action="save-unit-review" data-decision="accepted" data-id="${escapeHTML(id)}">接受</button><button type="button" class="button button-secondary" data-action="save-unit-review" data-decision="rejected" data-id="${escapeHTML(id)}">拒绝</button><button type="button" class="button button-secondary" data-action="save-unit-review" data-decision="needs-more-evidence" data-id="${escapeHTML(id)}">需补充证据</button></div></form>`;
      return `<article class="unit-review-card" id="unit-${escapeHTML(id)}"><header class="unit-review-card-header"><div><span class="unit-subject">${escapeHTML(SUBJECTS[unit.sourceId] || unit.sourceId || "未知科目")}</span><h2>${escapeHTML(unit.articleTitle || "未命名来源")}</h2><code>${escapeHTML(id)}</code></div><span class="unit-review-badge state-${escapeHTML(state === "needs-more" ? "needs-more-evidence" : state)}">${escapeHTML(UNIT_REVIEW_STATE_LABELS[state] || state)}</span></header><div class="unit-locator"><strong>${escapeHTML(locator || "章节定位不可用")}</strong><span>${sourceLink}</span></div><div class="unit-original-text"><h3>来源原文摘录</h3><p>${escapeHTML(String(unit.text || "").trim() || "未提取到可读正文；请先核对原文，不要直接接受。")}</p>${image}${sourceAttrs ? `<details class="unit-source-attributes"><summary>来源链接与媒体属性</summary>${sourceAttrs}</details>` : ""}</div>${related ? `<div class="unit-related"><strong>关联候选卡</strong>${related}</div>` : `<p class="unit-retired-note">未记录关联候选卡 ID。</p>`}${history}${decisionForm}</article>`;
    }).join("");
    const pageButtons = [];
    const firstPage = Math.max(0, Math.min(unitReviewPage - 2, pageCount - 5));
    for (let pageIndex = firstPage; pageIndex < Math.min(pageCount, firstPage + 5); pageIndex++) pageButtons.push(`<button type="button" class="unit-page-button${pageIndex === unitReviewPage ? " is-current" : ""}" data-action="unit-review-page" data-page="${pageIndex}" aria-label="第 ${pageIndex + 1} 页"${pageIndex === unitReviewPage ? ' aria-current="page"' : ""}>${pageIndex + 1}</button>`);
    const pagination = filtered.length ? `<nav class="unit-pagination" aria-label="知识单元审核分页"><button class="button button-secondary" type="button" data-action="unit-review-page" data-page="0"${unitReviewPage === 0 ? " disabled" : ""}>首页</button><button class="button button-secondary" type="button" data-action="unit-review-page" data-page="${Math.max(0, unitReviewPage - 1)}"${unitReviewPage === 0 ? " disabled" : ""}>上一页</button>${pageButtons.join("")}<span>第 ${unitReviewPage + 1} / ${pageCount.toLocaleString()} 页</span><button class="button button-secondary" type="button" data-action="unit-review-page" data-page="${Math.min(pageCount - 1, unitReviewPage + 1)}"${unitReviewPage >= pageCount - 1 ? " disabled" : ""}>下一页</button><button class="button button-secondary" type="button" data-action="unit-review-page" data-page="${pageCount - 1}"${unitReviewPage >= pageCount - 1 ? " disabled" : ""}>末页</button></nav>` : "";
    const fullCount = knowledgeUnits.filter((unit) => unit.presentInCurrentSource !== false).length;
    byId("viewContent").innerHTML = `<aside class="unit-review-scope"><strong>当前来源全量：${fullCount.toLocaleString()} 个知识单元</strong><span>搜索及科目、状态筛选仅缩小当前列表，不表示章节或全库已完成审核。已退役结论仍保留在历史台账中。</span></aside>${page.length ? `<div class="unit-review-list">${rows}</div>${pagination}` : emptyMarkup("没有匹配的知识单元", "请调整科目、状态或搜索词。筛选结果不是审核完成报告。", "")}`;
  }

  function downloadJson(filename, value) {
    const blob = new Blob([JSON.stringify(value, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function exportKnowledgeUnitReviews() {
    const records = Object.entries(knowledgeUnitReviews).sort(([left], [right]) => left.localeCompare(right)).map(([knowledgeUnitId, record]) => ({ knowledgeUnitId, ...record }));
    downloadJson(`codebrick-knowledge-unit-reviews-${localDateKey()}.json`, { schema: UNIT_REVIEW_SCHEMA, version: 2, exportedAt: new Date().toISOString(), records });
    toast(`已导出 ${records.length.toLocaleString()} 条审核台账（含已退役历史记录）。`);
  }

  function validateKnowledgeUnitReviewExport(value) {
    if (!isRecord(value) || Object.keys(value).sort().join("|") !== ["exportedAt", "records", "schema", "version"].sort().join("|") || value.schema !== UNIT_REVIEW_SCHEMA || ![1, 2].includes(value.version) || typeof value.exportedAt !== "string" || !Number.isFinite(Date.parse(value.exportedAt)) || !Array.isArray(value.records)) throw new Error("台账格式不正确；请选择本应用导出的知识单元审核 JSON（schema version 1）。");
    const result = Object.create(null);
    for (const raw of value.records) {
      if (!isRecord(raw) || typeof raw.knowledgeUnitId !== "string" || !/^[a-f0-9]{16}$/.test(raw.knowledgeUnitId) || Object.prototype.hasOwnProperty.call(result, raw.knowledgeUnitId)) throw new Error("审核台账含有未知字段、重复 ID 或格式错误的知识单元 ID；未导入任何内容。");
      const rawFields = Object.keys(raw).sort().join("|");
      const currentFields = ["knowledgeUnitId", ...UNIT_REVIEW_RECORD_FIELDS].sort().join("|");
      const legacyV1Fields = ["knowledgeUnitId", ...UNIT_REVIEW_RECORD_FIELDS.filter((field) => field !== "acceptedCardIds")].sort().join("|");
      if (rawFields !== currentFields && !(value.version === 1 && rawFields === legacyV1Fields)) throw new Error("审核台账含有未知字段或字段不完整；未导入任何内容。");
      const record = { decision: raw.decision === "needs-more" ? "needs-more-evidence" : raw.decision, reason: raw.reason, reviewer: raw.reviewer, examPoints: raw.examPoints, acceptedCardIds: raw.acceptedCardIds ?? [], reviewedAt: raw.reviewedAt, sourceHash: raw.sourceHash, textHash: raw.textHash };
      if (!UNIT_REVIEW_DECISIONS.has(record.decision) || typeof record.reason !== "string" || !record.reason.trim() || record.reason.length > 4000 || typeof record.reviewer !== "string" || !record.reviewer.trim() || record.reviewer.length > 240 || !Array.isArray(record.examPoints) || record.examPoints.some((point) => typeof point !== "string" || !point.trim() || point.length > 2400) || !Array.isArray(record.acceptedCardIds) || record.acceptedCardIds.some((cardId) => typeof cardId !== "string" || !/^[a-f0-9]{16}$/.test(cardId)) || (record.decision === "accepted" && (!record.examPoints.length || !record.acceptedCardIds.length)) || typeof record.reviewedAt !== "string" || !Number.isFinite(Date.parse(record.reviewedAt)) || !/^[a-f0-9]{64}$/.test(record.sourceHash) || !/^[a-f0-9]{64}$/.test(record.textHash)) throw new Error(`知识单元 ${raw.knowledgeUnitId} 的审核记录不完整或字段无效；未导入任何内容。`);
      result[raw.knowledgeUnitId] = { ...record, examPoints: [...new Set(record.examPoints.map((point) => point.trim()))], acceptedCardIds: [...new Set(record.acceptedCardIds)] };
    }
    return result;
  }

  async function importKnowledgeUnitReviews(file) {
    const input = byId("unitReviewImportFile");
    try {
      if (file.size > MAX_UNIT_REVIEW_IMPORT_BYTES) throw new Error("审核台账文件超过 64 MiB 安全上限。");
      if (!await ensureKnowledgeAuditLoaded()) throw new Error("当前来源审核数据不可用，台账未导入。");
      const incoming = validateKnowledgeUnitReviewExport(JSON.parse(await file.text()));
      const next = Object.assign(Object.create(null), knowledgeUnitReviews);
      let added = 0;
      for (const [id, record] of Object.entries(incoming)) {
        if (Object.prototype.hasOwnProperty.call(next, id)) {
          if (JSON.stringify(next[id]) !== JSON.stringify(record)) throw new Error(`单元 ${id} 与本机已有决定冲突；本次导入已整体取消。`);
          continue;
        }
        next[id] = record;
        added++;
      }
      if (!added) { toast("导入台账与本机完整记录完全一致；无需更改。"); return; }
      const previous = knowledgeUnitReviews;
      knowledgeUnitReviews = next;
      save();
      await persistenceQueue.catch(() => {});
      const persistedBackend = await persistedKnowledgeUnitReviewsMatch(next);
      if (!persistedBackend) {
        knowledgeUnitReviews = previous;
        save();
        throw new Error("浏览器本机存储不可用，台账未更改。请检查空间后重试。");
      }
      await validateSavedKnowledgeReviews();
      render();
      toast(`审核台账已安全合并：新增 ${added.toLocaleString()} 条，保留本机及退役历史记录。`);
      if (Object.keys(incoming).length > added) showNotice("本机已有记录已保留；过期来源决定会作为历史记录保留，不会放行学习。", false);
    } catch (error) {
      showNotice(error instanceof Error ? error.message : "审核台账无法导入；本机记录未更改。", true);
    } finally { input.value = ""; }
  }

  async function saveKnowledgeUnitDecision(id, decision) {
    const key = String(id);
    if (knowledgeUnitSavesInFlight.has(key)) return;
    knowledgeUnitSavesInFlight.add(key);
    try { await persistKnowledgeUnitDecision(key, decision); }
    finally { knowledgeUnitSavesInFlight.delete(key); }
  }

  async function persistKnowledgeUnitDecision(id, decision) {
    const unit = knowledgeUnitsById.get(String(id));
    const form = document.querySelector(`[data-unit-review-id="${CSS.escape(String(id))}"]`);
    if (!unit || unit.presentInCurrentSource === false || !form || !UNIT_REVIEW_DECISIONS.has(decision)) { toast("此单元不是当前可审核来源记录；没有保存决定。"); return; }
    const reviewer = String(form.elements.namedItem("reviewer")?.value || "").trim();
    const reason = String(form.elements.namedItem("reason")?.value || "").trim();
    const examPoints = [...new Set(String(form.elements.namedItem("examPoints")?.value || "").split(/[\n,，;；]+/).map((point) => point.trim()).filter(Boolean))];
    if (!form.reportValidity()) return;
    if (!reviewer || !reason || reviewer.length > 240 || reason.length > 4000 || (decision === "accepted" && !examPoints.length)) { toast(decision === "accepted" ? "接受结论必须填写审核人、审核理由和至少一个 408 考点映射。" : "请填写审核人和审核理由。"); return; }
    if (!await ensureKnowledgeAuditLoaded() || !knowledgeUnitsById.has(String(id)) || knowledgeUnitsById.get(String(id)).presentInCurrentSource === false) { toast("无法再次核验当前来源；决定未保存。"); return; }
    if (!sameUnitSource(unit, knowledgeUnitsById.get(String(id)))) { render(); toast("来源定位或内容自打开此页后已变化；请先重新查看当前原文，再提交决定。"); return; }
    try {
      const currentUnit = knowledgeUnitsById.get(String(id));
      const [sourceHash, textHash] = await Promise.all([knowledgeUnitSourceHash(currentUnit), sha256Text(currentUnit.text)]);
      const acceptedCardIds = [...new Set([...form.elements.namedItem("acceptedCardIds")?.selectedOptions || []].map((option) => option.value))];
      if (decision === "accepted") {
        if (!acceptedCardIds.length || acceptedCardIds.some((cardId) => !/^[a-f0-9]{16}$/.test(cardId) || !isConcreteUnitCard(currentUnit, cards.find((card) => card.id === cardId)))) { toast("接受必须至少绑定一张属于此知识单元的有效原子卡片，不能绑定模板题或占位答案。"); return; }
      }
      const record = { decision, reason, reviewer, examPoints: decision === "accepted" ? examPoints : [], acceptedCardIds: decision === "accepted" ? acceptedCardIds : [], reviewedAt: new Date().toISOString(), sourceHash, textHash };
      const previous = knowledgeUnitReviews;
      knowledgeUnitReviews = Object.assign(Object.create(null), previous, { [id]: record });
      save();
      await persistenceQueue.catch(() => {});
      const persistedBackend = await persistedKnowledgeUnitReviewsMatch(knowledgeUnitReviews);
      if (!persistedBackend) { knowledgeUnitReviews = previous; save(); toast("本机完整审核台账未能验证；审核决定已回滚。"); return; }
      knowledgeReviewValidity.set(id, record);
      render();
      toast("审核决定已保存到本机台账。");
    } catch (error) { toast(error instanceof Error ? error.message : "来源校验失败；没有保存审核决定。"); }
  }

  function renderTags(tags) { return tags.slice(0, 4).map((tag) => `<span class="tag">${escapeHTML(tag)}</span>`).join(""); }

  function sourceMarkup(card) {
    const title = card.articleTitle || card.section || "Source notes";
    const url = validUrl(card.articleUrl);
    return url ? `<a class="card-source" href="${escapeHTML(url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(title)} ↗</a>` : `<span class="card-source">${escapeHTML(title)}</span>`;
  }

  function emptyMarkup(title, copy, action = "") {
    let button = "";
    if (action === "import") button = '<button class="button button-secondary" type="button" data-action="import">Import cards ' + ICON.cards + "</button>";
    if (action === "inbox") button = '<button class="button button-primary" type="button" data-view="inbox">Review your inbox →</button>';
    return `<div class="empty-state"><div><span class="empty-illustration">${ICON.spark}</span><h2>${title}</h2><p>${copy}</p>${button ? `<div class="empty-actions">${button}</div>` : ""}</div></div>`;
  }

  function cleanArticleTitle(title) {
    return String(title || "未命名文章").replace(/\s*Permalink to [\s\S]*$/i, "").trim();
  }

  function articleUrlKey(value) {
    try {
      const url = new URL(value);
      if (!/^https?:$/.test(url.protocol)) return "";
      url.hash = "";
      url.search = "";
      url.pathname = url.pathname.replace(/\/$/, "").replace(/\.html$/i, "");
      return url.href;
    } catch { return ""; }
  }

  function reviewBadges(card) {
    const result = card.auditFlags.map(structuredText).filter(Boolean);
    if (card.reviewReason) result.unshift(sourceReviewLabel(card.reviewReason));
    if (card.sourceSectionRemoved) result.push(sourceReviewLabel("source-section-removed"));
    if (card.sourceArticleMissing) result.push(sourceReviewLabel("source-article-missing"));
    return [...new Set(result)];
  }

  function cardFieldsMarkup(card, compact = false) {
    const fields = [
      ["卡片类型", card.cardType], ["知识单元 ID", card.knowledgeUnitIds],
      ["408 考点", card.examPoints], ["来源溯源", card.provenance]
    ].map(([label, value]) => [label, structuredText(value)]).filter(([, value]) => value);
    const badges = reviewBadges(card);
    const body = fields.map(([label, value]) => `<div class="detail-copy"><strong>${escapeHTML(label)}</strong><br>${escapeHTML(value)}</div>`).join("");
    const audit = badges.length ? `<section class="detail-section source-update"><h3>审核提示</h3><ul class="review-flag-list">${badges.map((flag) => `<li>${escapeHTML(flag)}</li>`).join("")}</ul><p class="review-gate-note">${needsExplicitReview(card) ? "尚未完成审核确认，不会进入正式复习。" : "当前审核提示已确认。"}</p></section>` : "";
    if (compact) return `${fields.length ? `<div class="card-data-chips">${fields.slice(0, 3).map(([label, value]) => `<span class="data-chip"><strong>${escapeHTML(label)}</strong>${escapeHTML(value.slice(0, 100))}</span>`).join("")}</div>` : ""}${audit}`;
    return `${fields.length ? `<section class="detail-section card-structured-fields"><h3>知识点与来源溯源</h3>${body}</section>` : ""}${audit}`;
  }

  function cardEvidenceMarkup(card, compact = false) {
    const evidence = evidenceText(card);
    if (!evidence) return "";
    return compact
      ? `<div class="study-evidence"><strong>来源证据段落</strong><p>${escapeHTML(evidence)}</p></div>`
      : `<section class="detail-section"><h3>来源证据段落</h3><div class="detail-evidence">${escapeHTML(evidence)}</div></section>`;
  }

  function articlePathKey(sourceId, value) {
    const path = String(value || "").replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
    if (!path) return "";
    const prefix = `${sourceId}-blog/`;
    const blogIndex = path.indexOf(prefix);
    const relativePath = (blogIndex >= 0 ? path.slice(blogIndex + prefix.length) : path).replace(/\.html$/i, "");
    return `${sourceId}|${relativePath}`.toLocaleLowerCase();
  }

  function indexSourceCards() {
    if (sourceCardsIndexFor === cards) return sourceCardsIndex;
    sourceCardsIndexFor = cards;
    sourceCardsIndex = new Map();
    for (const card of cards) {
      const keys = [articleUrlKey(card.articleUrl), articlePathKey(card.sourceId, card.articlePath)].filter(Boolean);
      for (const key of new Set(keys)) {
        if (!sourceCardsIndex.has(key)) sourceCardsIndex.set(key, []);
        sourceCardsIndex.get(key).push(card);
      }
    }
    return sourceCardsIndex;
  }

  function sourceArticleCards(article) {
    const index = indexSourceCards();
    const urlKey = articleUrlKey(article.url);
    let path = "";
    try { path = new URL(article.url).pathname; } catch {}
    const pathKey = articlePathKey(article.sourceId, path);
    const byUrl = urlKey ? index.get(urlKey) || [] : [];
    const byPath = pathKey ? index.get(pathKey) || [] : [];
    return [...new Set([...byUrl, ...byPath])];
  }

  function selectSourceArticle(key) {
    if (selectedArticleKey === key) return;
    selectedArticleKey = key;
    selectedSectionAnchor = "";
    selectedSource = null;
    sourceLoadState = "idle";
    sourceLoadKey = key;
  }

  function renderSourceFilters() {
    const counts = Object.fromEntries(Object.keys(SUBJECTS).map((subject) => [subject, articleCatalog.filter((article) => article.sourceId === subject).length]));
    const articles = visibleArticles();
    if (!articles.some((article) => articleUrlKey(article.url) === selectedArticleKey)) selectSourceArticle(articles[0] ? articleUrlKey(articles[0].url) : "");
    const options = articles.map((article) => `<option value="${escapeHTML(articleUrlKey(article.url))}">${escapeHTML(SUBJECTS[article.sourceId] || article.sourceId)} · ${escapeHTML(article.title)}</option>`).join("");
    const subjectOptions = Object.entries(SUBJECTS).map(([id, title]) => `<option value="${id}">${escapeHTML(title)} (${counts[id] || 0})</option>`).join("");
    byId("filterRow").innerHTML = `<div class="filter-start"><label class="filter-label" for="sourceSubject">浏览科目</label><select id="sourceSubject" class="filter-select" aria-label="按科目筛选来源文章"><option value="all">全部科目 (${articleCatalog.length})</option>${subjectOptions}</select><label class="filter-label" for="sourceArticleSelect">选择文章</label><select id="sourceArticleSelect" class="filter-select" aria-label="选择要浏览的文章"${articles.length ? "" : " disabled"}>${options || '<option value="">暂无可用文章</option>'}</select></div><span class="result-count">${articles.length} / ${articleCatalog.length} 篇文章</span>`;
    byId("sourceSubject").value = sourceSubject;
    byId("sourceArticleSelect").value = selectedArticleKey;
  }

  function visibleArticles() {
    const term = search.trim().toLocaleLowerCase();
    return articleCatalog.filter((article) => {
      if (sourceSubject !== "all" && article.sourceId !== sourceSubject) return false;
      if (!term) return true;
      const cardText = sourceArticleCards(article).map((card) => `${card.question} ${card.answer} ${card.section} ${card.tags.join(" ")}`).join(" ");
      const loadedText = selectedSource?.key === articleUrlKey(article.url)
        ? selectedSource.sections.map((section) => `${section.title} ${section.fragments.join(" ")}`).join(" ") : "";
      return `${article.title} ${article.sourceId} ${article.url} ${cardText} ${loadedText}`.toLocaleLowerCase().includes(term);
    });
  }

  function parseSourceSections(html, articleTitle) {
    const parsed = new DOMParser().parseFromString(String(html || ""), "text/html");
    const root = parsed.querySelector("#VPContent .vp-doc, #VPContent .content, .VPDoc .vp-doc, .vp-doc") || parsed.body;
    root.querySelectorAll("script, style, nav, footer, aside, .header-anchor, .exam-topic, .article-footer, .blog-comments-embed, .VPDocFooter").forEach((node) => node.remove());
    const headings = [...root.querySelectorAll("h1, h2, h3, h4, h5, h6")];
    const allBlocks = [...root.querySelectorAll("p, li, blockquote, pre, table, figcaption")];
    const headingLevel = (node) => Number(node.tagName.slice(1)) || 6;
    const textOf = (node) => {
      const copy = node.cloneNode(true);
      if (node.matches("li")) copy.querySelectorAll("ul, ol").forEach((nested) => nested.remove());
      return String(copy.textContent || "").replace(/[\u200b\u200c\u200d\ufeff]/g, "").replace(/\s+/g, " ").trim();
    };
    const fragmentsBetween = (heading, boundary) => allBlocks.filter((block) => {
      if (block.matches("p") && block.closest("li, blockquote")) return false;
      if (block.matches("li") && block.querySelector(":scope > ul li, :scope > ol li")) return true;
      const afterStart = Boolean(heading.compareDocumentPosition(block) & 4);
      const beforeEnd = !boundary || Boolean(boundary.compareDocumentPosition(block) & 2);
      return afterStart && beforeEnd;
    }).map(textOf).filter((text, index, all) => text.length > 1 && all.indexOf(text) === index);

    if (!headings.length) {
      const fragments = [...new Set(allBlocks.map(textOf).filter((text) => text.length > 1))];
      return [{ id: "article-content", title: articleTitle || "文章正文", level: 2, fragments }];
    }
    return headings.map((heading, index) => {
      const level = headingLevel(heading);
      const boundary = headings[index + 1] || null;
      const title = textOf(heading) || `章节 ${index + 1}`;
      return { id: String(heading.id || `source-section-${index + 1}`), title, level, fragments: fragmentsBetween(heading, boundary) };
    });
  }

  function loadSourceArticle(article) {
    const key = articleUrlKey(article.url);
    if (!key || sourceLoadKey === key && ["loading", "ready", "error"].includes(sourceLoadState)) return;
    selectedSource = null;
    sourceLoadKey = key;
    sourceLoadState = "loading";
    const cachePath = String(article.cache || "");
    if (!/^\.cache\/html\/[a-z0-9_-]+\/[a-z0-9_-]+\.html$/i.test(cachePath)) {
      sourceLoadState = "error";
      render();
      return;
    }
    const cacheUrl = new URL(`../${cachePath}`, window.location.href);
    if (cacheUrl.origin !== window.location.origin) {
      sourceLoadState = "error";
      render();
      return;
    }
    fetch(cacheUrl, { cache: "no-cache" }).then((response) => {
      if (!response.ok) throw new Error(`Source request failed (${response.status}).`);
      return response.text();
    }).then((html) => {
      if (selectedArticleKey !== key) return;
      selectedSource = { key, sections: parseSourceSections(html, article.title) };
      sourceLoadState = "ready";
      render();
    }).catch(() => {
      if (selectedArticleKey !== key) return;
      selectedSource = null;
      sourceLoadState = "error";
      render();
    });
  }

  function normalizedSectionName(value) {
    return String(value || "").normalize("NFKC").toLocaleLowerCase().replace(/[\s\p{P}\p{S}]+/gu, "");
  }

  function sourceSectionCards(article, section, articleCards = sourceArticleCards(article)) {
    const anchor = String(section.id || "");
    const heading = normalizedSectionName(section.title);
    return articleCards.filter((card) => {
      let cardAnchor = String(card.sectionAnchor || "");
      try { cardAnchor = decodeURIComponent(cardAnchor); } catch {}
      return Boolean(anchor && cardAnchor === anchor) || Boolean(heading && normalizedSectionName(card.section) === heading);
    });
  }

  function sourceCardMarkup(card) {
    const blocked = approvalBlockReason(card);
    const badge = isStudyEligible(card) ? '<span class="status-badge">已审核 · 正式卡</span>' : `<span class="status-badge pending">${blocked ? "待人工核验" : "候选卡"}</span>`;
    const gate = blocked ? `<p class="review-gate-note">${escapeHTML(blocked)} 不会进入正式复习。</p>` : "";
    return `<article class="library-card inbox-card"><div class="card-meta"><span class="card-section">${escapeHTML(card.section || card.articleTitle || "来源章节")}</span>${badge}</div><button class="card-question text-action-reset" type="button" data-action="details" data-id="${escapeHTML(card.id)}">${escapeHTML(card.question)}</button><div class="card-tags">${renderTags(card.tags)}</div>${gate}<div class="card-footer">${cardEvidenceMarkup(card, true)}<button class="button button-secondary" type="button" data-action="details" data-id="${escapeHTML(card.id)}">查看卡片与审核信息 →</button></div></article>`;
  }

  function renderSources() {
    if (articleLoadState === "loading" || articleLoadState === "idle") {
      byId("resultCount").textContent = "正在读取文章目录…";
      byId("viewContent").innerHTML = emptyMarkup("正在加载来源目录", "文章目录读取后，可按科目和文章查看章节、原文片段及关联卡片。");
      return;
    }
    if (articleLoadState === "error") {
      byId("resultCount").textContent = "目录不可用";
      byId("viewContent").innerHTML = emptyMarkup("暂时无法读取来源目录", "请确认本地文章目录文件可访问后刷新页面。");
      return;
    }
    const articles = visibleArticles();
    const article = articles.find((item) => articleUrlKey(item.url) === selectedArticleKey) || articles[0];
    if (!article) {
      byId("resultCount").textContent = "0 篇文章";
      byId("viewContent").innerHTML = emptyMarkup("没有匹配的文章", "调整搜索词或切换科目；来源搜索也会匹配关联卡片内容。");
      return;
    }
    const key = articleUrlKey(article.url);
    if (selectedArticleKey !== key) selectSourceArticle(key);
    const articleSelect = byId("sourceArticleSelect");
    if (articleSelect) articleSelect.value = key;
    const linkedCards = sourceArticleCards(article);
    const studyReady = linkedCards.filter(isStudyEligible).length;
    const pending = linkedCards.length - studyReady;
    const originalUrl = validUrl(article.url);
    const header = `<section class="detail-section"><div class="card-meta"><span class="eyebrow">${escapeHTML(SUBJECTS[article.sourceId] || article.sourceId)} · 来源文章</span><span class="status-badge pending">${linkedCards.length} 张关联卡</span></div><h2>${escapeHTML(cleanArticleTitle(article.title))}</h2><p class="detail-copy">${linkedCards.length} 张关联卡中，${studyReady} 张已通过审核，${pending} 张仍待核验；待核验内容不会进入正式复习。</p><p class="review-gate-note">以下是本地 HTML 快照中自动提取的文本片段，仅用于来源核对，不代表知识点已人工确认或完整覆盖。</p>${originalUrl ? `<p><a class="card-source" href="${escapeHTML(originalUrl)}" target="_blank" rel="noopener noreferrer">打开原始文章 ↗</a></p>` : ""}</section>`;

    if (sourceLoadKey !== key || sourceLoadState === "idle") loadSourceArticle(article);
    if (sourceLoadState === "loading" || sourceLoadState === "idle") {
      byId("resultCount").textContent = `${linkedCards.length} 张关联卡 · 正在读取正文`;
      byId("viewContent").innerHTML = `${header}<section class="detail-section"><p class="detail-copy">正在从本地 HTML 快照提取章节与文本片段…</p></section>`;
      return;
    }
    if (sourceLoadState === "error" || !selectedSource || selectedSource.key !== key) {
      byId("resultCount").textContent = `${linkedCards.length} 张关联卡 · 正文不可用`;
      byId("viewContent").innerHTML = `${header}<section class="detail-section source-update"><h3>本地正文快照不可用</h3><p class="detail-copy">无法安全读取这篇文章的本地 HTML 快照。仍可打开原文链接，并通过文章下方的关联卡查看已有内容。</p><button class="button button-secondary" type="button" data-action="retry-source">重试读取</button></section><section class="detail-section"><h3>关联卡片</h3>${linkedCards.length ? `<div class="library-grid">${linkedCards.map(sourceCardMarkup).join("")}</div>` : '<p class="detail-copy">此文章暂时没有关联卡片。</p>'}</section>`;
      return;
    }

    const sections = selectedSource.sections;
    const term = search.trim().toLocaleLowerCase();
    const titleMatches = !term || article.title.toLocaleLowerCase().includes(term);
    const visibleSections = sections.map((section, index) => {
      const sectionCards = sourceSectionCards(article, section, linkedCards);
      const cardMatches = sectionCards.filter((card) => !term || matchesSearch(card, term));
      const headingMatches = titleMatches || !term || section.title.toLocaleLowerCase().includes(term);
      const matchingFragments = section.fragments.filter((fragment) => headingMatches || !term || fragment.toLocaleLowerCase().includes(term) || cardMatches.length > 0);
      if (term && !headingMatches && !matchingFragments.length && !cardMatches.length) return null;
      const cardsToShow = term && !headingMatches ? cardMatches : sectionCards;
      const fragmentsMarkup = matchingFragments.length
        ? `<div class="detail-section"><h4>来源文本片段 · ${matchingFragments.length}</h4>${matchingFragments.map((fragment, fragmentIndex) => `<blockquote class="detail-evidence"><span class="eyebrow">片段 ${fragmentIndex + 1}</span><p>${escapeHTML(fragment)}</p></blockquote>`).join("")}</div>`
        : '<p class="detail-copy">本章未提取到可显示的文本片段（可能含图片、公式或交互内容）。</p>';
      const cardsMarkup = cardsToShow.length
        ? `<div class="detail-section"><h4>本章关联卡片 · ${cardsToShow.length}</h4><div class="library-grid">${cardsToShow.map(sourceCardMarkup).join("")}</div></div>`
        : '<p class="detail-copy">本章暂未找到关联卡片。</p>';
      const isOpen = selectedSectionAnchor ? selectedSectionAnchor === section.id : index === 0;
      return { section, index, sectionCards, matchingFragments, cardsToShow, markup: `<details class="detail-section" id="source-section-${index}"${isOpen ? " open" : ""}><summary><strong>${escapeHTML(section.title)}</strong><span class="card-section">${section.fragments.length} 个片段 · ${sectionCards.length} 张关联卡</span></summary>${fragmentsMarkup}${cardsMarkup}</details>` };
    }).filter(Boolean);
    const chapterNavigation = visibleSections.length
      ? `<nav class="filter-row" aria-label="文章章节">${visibleSections.map(({ section, index }) => `<button class="button button-secondary" type="button" data-action="select-source-section" data-section-index="${index}" data-anchor="${escapeHTML(section.id)}">${escapeHTML(section.title)}</button>`).join("")}</nav>`
      : '<p class="detail-copy">没有与当前搜索匹配的章节。</p>';
    const sectionMarkup = visibleSections.map((item) => item.markup).join("");
    byId("resultCount").textContent = `${sections.length} 个章节 · ${linkedCards.length} 张关联卡`;
    byId("viewContent").innerHTML = `${header}<section class="detail-section"><h3>文章章节</h3>${chapterNavigation}</section><div class="library-grid">${sectionMarkup}</div>`;
  }

  function renderLibrary() {
    const all = approvedCards();
    const term = search.trim().toLowerCase();
    const filtered = all.filter((card) => {
      const study = getProgress(card.id);
      const cardStatus = statusOf(card);
      const status = statusFilter === "all" || statusFilter === "learning" && cardStatus !== "paused" && (study.reviews > 0 || cardStatus === "learning") || statusFilter === "new" && !study.reviews && cardStatus !== "paused" || statusFilter === "paused" && cardStatus === "paused";
      const tag = tagFilter === "all" || card.tags.includes(tagFilter);
      return status && tag && matchesSearch(card, term);
    });
    byId("resultCount").textContent = `${filtered.length} ${filtered.length === 1 ? "card" : "cards"}`;
    if (!filtered.length) {
      byId("viewContent").innerHTML = emptyMarkup("Nothing in this view just yet", all.length ? "No cards match those filters. Try another search or topic." : "Approved cards will live here, ready whenever you want to revisit them.", all.length ? "" : "import");
      return;
    }
    byId("viewContent").innerHTML = `<div class="library-grid">${filtered.map((card) => {
      const learning = getProgress(card.id).reviews > 0 || statusOf(card) === "learning";
      const label = statusOf(card) === "paused" ? "Paused" : learning ? "Learning" : "New";
      const badge = label === "Paused" ? " archived" : "";
      return `<article class="library-card"><div class="card-meta"><span class="card-section">${escapeHTML(card.section || card.articleTitle || "Untitled section")}</span><span class="status-badge${badge}">${label}</span></div><button class="card-question text-action-reset" type="button" data-action="details" data-id="${escapeHTML(card.id)}">${escapeHTML(card.question)}</button><div class="card-tags">${renderTags(card.tags)}</div><div class="card-footer">${sourceMarkup(card)}<button class="text-action" type="button" data-action="details" data-id="${escapeHTML(card.id)}">View answer →</button></div></article>`;
    }).join("")}</div>`;
  }

  function renderInbox() {
    const all = pendingCards();
    const term = search.trim().toLowerCase();
    const filtered = all.filter((card) => (tagFilter === "all" || card.tags.includes(tagFilter)) && matchesSearch(card, term));
    if (!filtered.length) {
      const title = all.length ? "No matching cards" : search ? "No matching cards" : cards.length ? "Your inbox is clear" : "Start with a few good ideas";
      const copy = all.length || search ? "Try another search or topic to find a card in your inbox." : cards.length ? "You have reviewed every card so far. New imports will land here." : "Import a version 1 JSON card collection. Cards will appear here for a quick edit and approval.";
      byId("viewContent").innerHTML = emptyMarkup(title, copy, cards.length ? "" : "import");
      if (byId("resultCount")) byId("resultCount").textContent = "0 cards";
      return;
    }
    byId("resultCount").textContent = `${filtered.length} ${filtered.length === 1 ? "card" : "cards"}`;
    const banner = `<div class="inbox-summary">${ICON.spark}<span><strong>${all.length} ${all.length === 1 ? "card is" : "cards are"} waiting for review.</strong> Cards with unresolved source or audit flags require an explicit check before approval.</span></div>`;
    const grid = filtered.map((card) => {
      const blocked = approvalBlockReason(card);
      const flags = reviewBadges(card);
      const warning = blocked ? `<div class="source-review-warning"><strong>需人工核验</strong><p>${escapeHTML(blocked)}</p>${flags.length ? `<ul class="review-flag-list">${flags.map((flag) => `<li>${escapeHTML(flag)}</li>`).join("")}</ul>` : ""}</div>` : "";
      const approveAction = canApproveCard(card) ? `<button class="button button-primary" type="button" data-action="approve" data-id="${escapeHTML(card.id)}">${ICON.check} Approve</button>` : "";
      return `<article class="library-card inbox-card"><div class="card-meta"><span class="card-section">${escapeHTML(card.section || card.articleTitle || "Untitled section")}</span><span class="status-badge pending">${blocked ? "需人工核验" : "Needs review"}</span></div>${warning}<button class="card-question text-action-reset" type="button" data-action="details" data-id="${escapeHTML(card.id)}">${escapeHTML(card.question)}</button><div class="card-tags">${renderTags(card.tags)}</div><div class="card-footer">${sourceMarkup(card)}<span class="inbox-actions"><button class="button button-secondary" type="button" data-action="edit" data-id="${escapeHTML(card.id)}">${ICON.edit} Edit</button>${approveAction}<button class="button button-quiet" type="button" data-action="ignore" data-id="${escapeHTML(card.id)}" aria-label="Ignore this card">Ignore</button></span></div></article>`;
    }).join("");
    byId("viewContent").innerHTML = `${banner}<div class="library-grid">${grid}</div>`;
  }

  function renderToday() {
    const allDue = dueCards();
    const requestedCard = studyTargetId ? approvedCards().find((item) => item.id === studyTargetId) : null;
    if (studyTargetId && !requestedCard) studyTargetId = "";
    const term = search.trim().toLocaleLowerCase();
    const due = allDue.filter((card) => matchesSearch(card, term));
    const queue = requestedCard && matchesSearch(requestedCard, term)
      ? [requestedCard, ...due.filter((card) => card.id !== requestedCard.id)]
      : due;
    if (!queue.length) {
      flippedId = "";
      if (term) {
        byId("viewContent").innerHTML = emptyMarkup("No matching cards due", "Try a different search. Other cards will appear here when they are due.");
        return;
      }
      if (approvedCards().length) {
        const action = pendingCards().length ? "inbox" : "";
        byId("viewContent").innerHTML = `${emptyMarkup("You are all caught up for today", "Your next review will be ready when these ideas are due. A little consistency goes a long way.", action)}<div class="page-footer" style="margin-top:15px">${reviewedToday() ? `Nice work. You reviewed ${reviewedToday()} ${reviewedToday() === 1 ? "card" : "cards"} today.` : "Take a moment to enjoy the progress."}</div>`;
      } else {
        byId("viewContent").innerHTML = emptyMarkup("Your next good idea starts here", "Import a JSON card collection, review your inbox, then come back here to study.", cards.length ? "inbox" : "import");
      }
      return;
    }

    const card = queue.find((item) => item.id === flippedId) || queue[0];
    const study = getProgress(card.id);
    const flipped = flippedId === card.id;
    const reviewed = reviewedToday();
    const total = reviewed + due.length;
    const percent = total ? Math.round(reviewed / total * 100) : 0;
    const answer = flipped ? `<div class="study-answer"><strong>Answer</strong>${escapeHTML(card.answer || "Add an answer to this card from your library or inbox.")}</div>${card.evidence ? `<div class="study-evidence">${escapeHTML(card.evidence)}</div>` : ""}` : "";
    const ratings = [["again", "Again", "1 min"], ["hard", "Hard", "6 hours"], ["good", "Good", "1 day"], ["easy", "Easy", "3 days"]];
    const actions = flipped ? `<div class="rating-row" aria-label="Rate this card">${ratings.map(([rating, title, interval]) => `<button class="rating-button ${rating}" type="button" data-action="rate" data-rating="${rating}" data-id="${escapeHTML(card.id)}"><strong>${title}</strong><small>${interval}</small></button>`).join("")}</div><p class="keyboard-hint">Rate recall with <kbd>1</kbd> Again · <kbd>2</kbd> Hard · <kbd>3</kbd> Good · <kbd>4</kbd> Easy</p>` : `<button class="reveal-button" type="button" data-action="reveal" data-id="${escapeHTML(card.id)}">Reveal the answer <span aria-hidden="true">↗</span></button>`;
    const source = validUrl(card.articleUrl);
    const title = card.articleTitle || card.section || "Original source";
    const sourceCard = `<section class="source-card"><div class="side-card-heading">Original source <span>↗</span></div>${source ? `<a class="source-title" href="${escapeHTML(source)}" target="_blank" rel="noopener noreferrer">${escapeHTML(title)}</a>` : `<span class="source-title">${escapeHTML(title)}</span>`}${card.section ? `<span class="source-url">${escapeHTML(card.section)}</span>` : ""}</section>`;
    byId("viewContent").innerHTML = `<div class="review-layout"><article class="study-card"><div class="study-meta"><span class="eyebrow">${study.reviews ? "DAILY REVIEW" : "FIRST LOOK"}</span><div class="study-tags">${renderTags(card.tags)}</div></div><p class="study-question">${escapeHTML(card.question)}</p>${answer}<div class="study-actions">${actions}</div></article><aside class="study-sidebar"><section class="progress-card"><div class="side-card-heading">Today's progress <span>${reviewed}/${total}</span></div><div class="progress-numbers"><strong>${reviewed}</strong><span>reviewed today</span></div><div class="progress-track" role="progressbar" aria-label="Today's review progress" aria-valuenow="${percent}" aria-valuemin="0" aria-valuemax="100"><div class="progress-fill" style="width:${percent}%"></div></div><p class="progress-caption">${due.length} ${due.length === 1 ? "card is" : "cards are"} ready to learn.</p></section>${sourceCard}<div class="tip-card"><span class="tip-spark">✳</span><div><strong>Think, then reveal</strong><p>Give yourself a moment to recall before checking the answer.</p></div></div></aside></div>`;
  }

  function render() {
    renderIntro();
    renderStats();
    renderFilters();
    if (view === "today") renderToday();
    else if (view === "library") renderLibrary();
    else if (view === "inbox") renderInbox();
    else if (view === "unitReview") renderKnowledgeUnitReview();
    else renderSources();
    byId("todayNavCount").textContent = String(dueCards().length);
    byId("libraryNavCount").textContent = String(approvedCards().length);
    byId("inboxNavCount").textContent = String(pendingCards().length);
    byId("globalSearch").placeholder = view === "unitReview" ? "搜索正文、定位、来源或审核记录…" : view === "sources" ? "搜索文章、章节或知识点…" : `搜索${view === "today" ? "复习卡" : view === "library" ? "正式卡库" : "候选卡"}…`;
    document.querySelectorAll(".nav-link[data-view]").forEach((item) => item.classList.toggle("is-active", item.dataset.view === view));
  }

  function switchView(next, fromHash = false, studyCardId = null) {
    if (!VIEWS[next]) return;
    const changed = view !== next;
    view = next;
    if (changed) {
      statusFilter = "all";
      tagFilter = "all";
      unitReviewPage = 0;
      search = "";
      flippedId = "";
      byId("globalSearch").value = "";
    }
    if (changed) studyTargetId = "";
    else if (!fromHash && studyCardId === null) studyTargetId = "";
    if (studyCardId !== null) studyTargetId = studyCardId;
    if (!fromHash && window.location.hash !== `#${next}`) window.location.hash = next;
    byId("sidebar").classList.remove("is-open");
    byId("mobileMenuButton").setAttribute("aria-expanded", "false");
    if (!changed && fromHash) return;
    render();
  }

  function saveOrRollback(rollback) {
    if (save()) return true;
    rollback();
    render();
    return false;
  }

  function mergeRemoteCards(remoteCards, saved) {
    remoteBaseCards = new Map(remoteCards.map((card) => [card.id, card]));
    const merged = new Map(remoteCards.map((card) => [card.id, card]));
    for (const localCard of saved.cards) {
      const remoteCard = merged.get(localCard.id);
      if (!remoteCard) { merged.set(localCard.id, localCard); continue; }
      const sourceChanged = Boolean(remoteCard.sourceHash && localCard.sourceHash && remoteCard.sourceHash !== localCard.sourceHash);
      const sourceNeedsReview = ["needs_review", "needs-review"].includes(statusOf(remoteCard)) || Boolean(remoteCard.sourceSectionRemoved || remoteCard.sourceArticleMissing) || sourceChanged;
      const needsReview = sourceNeedsReview && localCard.reviewedSourceVersion !== sourceReviewVersion(remoteCard);
      const combined = { ...localCard, ...remoteCard };
      for (const field of REMOTE_METADATA_FIELDS) {
        if (Object.prototype.hasOwnProperty.call(remoteCard, field)) combined[field] = remoteCard[field];
        else if (["previousAnswer", "suggestedQuestion", "suggestedAnswer", "sourceSectionRemoved", "sourceArticleMissing"].includes(field)) delete combined[field];
      }
      const questionIsGenerated = Boolean(localCard.generatedQuestion) && localCard.question === localCard.generatedQuestion;
      const answerIsGenerated = Boolean(localCard.generatedAnswer) && localCard.answer === localCard.generatedAnswer;
      combined.question = !sourceNeedsReview && questionIsGenerated ? remoteCard.question : localCard.question;
      combined.answer = !sourceNeedsReview && answerIsGenerated ? remoteCard.answer : localCard.answer;
      combined.evidence = !sourceNeedsReview && localCard.evidence === localCard.generatedAnswer ? remoteCard.evidence : localCard.evidence;
      combined.tags = localCard.tags;
      if (!sourceChanged) combined.section = localCard.section;
      combined.status = needsReview ? remoteCard.status : localCard.status;
      if (localCard.reviewedSourceVersion !== undefined) combined.reviewedSourceVersion = localCard.reviewedSourceVersion;
      else delete combined.reviewedSourceVersion;
      merged.set(localCard.id, normalizeCard(combined));
    }
    for (const { id, values, removed = [] } of saved.overrides) {
      const remoteCard = merged.get(id);
      if (!remoteCard) continue;
      const patch = Object.create(null);
      for (const field of Object.keys(values)) if (!["__proto__", "prototype", "constructor"].includes(field)) patch[field] = values[field];
      const next = { ...remoteCard };
      for (const field of removed) if (typeof field === "string" && !["__proto__", "prototype", "constructor"].includes(field)) delete next[field];
      Object.assign(next, patch);
      const sourceNeedsReview = ["needs_review", "needs-review"].includes(statusOf(remoteCard)) || Boolean(remoteCard.sourceSectionRemoved || remoteCard.sourceArticleMissing);
      const reviewedCurrentSource = values.reviewedSourceVersion === sourceReviewVersion(remoteCard);
      if (sourceNeedsReview && !reviewedCurrentSource && values.status !== "rejected") next.status = remoteCard.status;
      merged.set(id, normalizeCard(next));
    }
    return [...merged.values()];
  }

  function approve(id) {
    const card = cards.find((item) => item.id === id);
    if (!card || !isPending(card)) return;
    const blocked = approvalBlockReason(card);
    if (blocked) { toast(blocked); return; }
    const previousStatus = card.status;
    const previousReviewVersion = card.reviewedSourceVersion;
    card.status = "approved";
    card.reviewedSourceVersion = sourceReviewVersion(card);
    if (!saveOrRollback(() => {
      card.status = previousStatus;
      if (previousReviewVersion === undefined) delete card.reviewedSourceVersion;
      else card.reviewedSourceVersion = previousReviewVersion;
    })) return;
    toast("Approved. Your new card is ready to study.");
    render();
  }

  function ignoreCard(id) {
    const card = cards.find((item) => item.id === id);
    if (!card || !isPending(card)) return;
    const previousStatus = card.status;
    card.status = "rejected";
    if (!saveOrRollback(() => { card.status = previousStatus; })) return;
    toast("Card ignored. It remains in your exported backup.");
    render();
  }

  function editCard(id) {
    const card = cards.find((item) => item.id === id);
    if (!card) return;
    const requiresSourceReview = card.reviewReason === "source-extraction-incomplete";
    const requiresAcknowledgement = needsExplicitReview(card);
    byId("editCardId").value = card.id;
    byId("editQuestion").value = card.question;
    byId("editAnswer").value = card.answer;
    byId("editEvidence").value = card.evidence;
    byId("editSection").value = card.section;
    byId("editTags").value = card.tags.join(", ");
    byId("editEyebrow").textContent = isPending(card) ? "INBOX CARD" : "YOUR LIBRARY";
    byId("editDialogTitle").textContent = isPending(card) ? "Make this card yours" : "Edit card";
    byId("saveApproveButton").classList.toggle("is-hidden", !isPending(card));
    byId("sourceReviewConfirm").classList.toggle("is-hidden", !requiresAcknowledgement);
    byId("sourceReviewConfirm").querySelector("span").textContent = requiresSourceReview
      ? "我已打开原文、替换不可靠内容，并逐项核实下列来源/审核提示："
      : "我已逐项阅读并核实下列来源/审核提示，确认编辑后的卡片内容可靠：";
    byId("sourceReviewChecked").checked = false;
    byId("editDialog").showModal();
    byId("editQuestion").focus();
  }

  function showDetails(id) {
    const card = cards.find((item) => item.id === id);
    if (!card) return;
    const pending = isPending(card);
    const requiresSourceReview = card.reviewReason === "source-extraction-incomplete";
    const source = validUrl(card.articleUrl);
    const sourceAction = source ? `<a class="button button-secondary" href="${escapeHTML(source)}" target="_blank" rel="noopener noreferrer">Open source ↗</a>` : "";
    const blockReason = approvalBlockReason(card);
    const primary = pending ? blockReason ? `<span class="review-gate-note" role="status">${escapeHTML(blockReason)}</span>` : `<button class="button button-primary" type="button" data-action="approve" data-id="${escapeHTML(id)}">${ICON.check} Approve</button>` : `<button class="button button-primary" type="button" data-action="study-card" data-id="${escapeHTML(id)}">Study this card ${ICON.clock}</button>`;
    const ignore = pending ? `<button class="button button-quiet" type="button" data-action="ignore" data-id="${escapeHTML(id)}">Ignore</button>` : "";
    const status = pending ? '<span class="status-badge pending">Needs review</span>' : '<span class="status-badge">In your library</span>';
    byId("detailBody").innerHTML = `<div class="modal-heading"><div><p class="eyebrow">${pending ? "WAITING FOR REVIEW" : escapeHTML(card.section || card.articleTitle || "YOUR LIBRARY")}</p><h2 id="detailTitle">Card details</h2></div><button class="icon-button modal-close" type="button" data-action="close-details" aria-label="Close">x</button></div><div class="detail-meta">${renderTags(card.tags)}${status}</div>${requiresSourceReview ? `<section class="detail-section source-update"><h3>Source check required</h3><p class="detail-copy">The original content could not be reliably extracted. Open the source, verify this section, and replace the placeholder before approval.</p></section>` : ""}${pending && (card.suggestedAnswer || card.suggestedQuestion || card.sourceSectionRemoved || card.sourceArticleMissing) ? `<section class="detail-section source-update"><h3>Source update · review before approving</h3>${card.sourceSectionRemoved || card.sourceArticleMissing ? `<p class="detail-copy">The original source section is no longer available.</p>` : ""}${card.suggestedQuestion ? `<p class="detail-copy"><strong>Suggested question</strong><br>${escapeHTML(card.suggestedQuestion)}</p>` : ""}${card.suggestedAnswer ? `<p class="detail-copy"><strong>Suggested answer</strong><br>${escapeHTML(card.suggestedAnswer)}</p>` : ""}${card.previousAnswer ? `<details><summary>Previous answer</summary><p class="detail-copy">${escapeHTML(card.previousAnswer)}</p></details>` : ""}</section>` : ""}<section class="detail-section"><h3>Question</h3><p class="detail-copy">${escapeHTML(card.question)}</p></section><section class="detail-section"><h3>Answer</h3><p class="detail-copy">${escapeHTML(card.answer || "No answer has been added yet.")}</p></section>${cardEvidenceMarkup(card)}${cardFieldsMarkup(card)}<div class="modal-footer">${sourceAction}<span class="spacer"></span>${ignore}<button class="button button-secondary" type="button" data-action="edit" data-id="${escapeHTML(id)}">${ICON.edit} Edit card</button>${primary}</div>`;
    byId("detailDialog").showModal();
  }

  function rate(id, rating) {
    const card = cards.find((item) => item.id === id);
    if (!card || !isStudyEligible(card) || !["again", "hard", "good", "easy"].includes(rating)) return;
    const previous = getProgress(id);
    const days = { again: 1 / 1440, hard: Math.max(0.25, (previous.intervalDays || 0) * 1.2), good: previous.intervalDays ? Math.max(1, previous.intervalDays * 2) : 1, easy: previous.intervalDays ? Math.max(3, previous.intervalDays * 2.5) : 3 }[rating];
    const hadProgress = Object.prototype.hasOwnProperty.call(progress, id);
    const previousProgress = progress[id];
    progress[id] = {
      dueAt: new Date(Date.now() + days * 86_400_000).toISOString(),
      intervalDays: days,
      reviews: (previous.reviews || 0) + 1,
      lapses: (previous.lapses || 0) + Number(rating === "again"),
      lastReviewed: new Date().toISOString(),
      lastRating: rating
    };
    if (!saveOrRollback(() => {
      if (hadProgress) progress[id] = previousProgress;
      else delete progress[id];
    })) return;
    flippedId = "";
    studyTargetId = "";
    render();
    toast(rating === "again" ? "We will come back to that one shortly." : dueCards().length ? "Nice work. Keep the momentum going." : "Great session. You are all caught up!");
  }

  function importCards() { byId("importFile").click(); }

  function readImport(file) {
    if (file.size > MAX_IMPORT_BYTES) {
      showNotice("This file is too large to import safely. Split it into smaller JSON collections and try again.", true);
      byId("importFile").value = "";
      return;
    }
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      try {
        const json = JSON.parse(String(reader.result));
        const incoming = Array.isArray(json) ? json : json?.version === 1 && Array.isArray(json.cards) ? json.cards : null;
        if (!incoming) throw new Error("Expected a version 1 card collection with a cards array.");
        const isBackup = !Array.isArray(json) && isRecord(json.progress);
        const nextCards = [...cards];
        const nextProgress = normalizeProgress(progress);
        const seen = new Set();
        let added = 0;
        let updated = 0;
        let skipped = 0;
        incoming.forEach((raw) => {
          const card = normalizeCard(raw);
          if (!card || seen.has(card.id)) return;
          seen.add(card.id);
          const existingIndex = nextCards.findIndex((item) => item.id === card.id);
          if (!isBackup) {
            if (existingIndex >= 0) { skipped++; return; }
            card.status = "pending";
          }
          if (!card.origin) card.origin = "import";
          if (existingIndex >= 0) { nextCards[existingIndex] = card; updated++; }
          else { nextCards.push(card); added++; }
        });
        if (!added && !updated) {
          if (skipped) { toast("No new cards imported; matching IDs were already in your collection."); return; }
          throw new Error("No valid cards found. Each card must have an id and question.");
        }
        if (isBackup) Object.assign(nextProgress, normalizeProgress(json.progress));
        const previousCards = cards;
        const previousProgress = progress;
        cards = nextCards;
        progress = nextProgress;
        if (!saveOrRollback(() => { cards = previousCards; progress = previousProgress; })) return;
        switchView("inbox");
        const summary = [`${added} added`, updated ? `${updated} restored` : "", skipped ? `${skipped} already present` : ""].filter(Boolean).join(", ");
        toast(isBackup ? `Backup imported: ${summary}.` : `Imported ${added} ${added === 1 ? "card" : "cards"} to your inbox.${skipped ? ` Skipped ${skipped} existing.` : ""}`);
      } catch (error) {
        showNotice(`Could not import this file. ${error instanceof Error ? error.message : "Check the card JSON."}`, true);
      } finally { byId("importFile").value = ""; }
    });
    reader.addEventListener("error", () => { showNotice("Could not read this file. Please try another JSON file.", true); byId("importFile").value = ""; });
    reader.readAsText(file);
  }

  function exportCards() {
    const blob = new Blob([JSON.stringify({ version: 1, exportedAt: new Date().toISOString(), cards, progress }, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `codebrick-cards-${localDateKey()}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast(`Exported ${cards.length} ${cards.length === 1 ? "card" : "cards"}.`);
  }

  function handleAction(target) {
    const { action, id, view: destination } = target.dataset;
    if (target.dataset.view) { switchView(target.dataset.view); return; }
    if (action === "view") switchView(destination);
    else if (action === "import") importCards();
    else if (action === "export") exportCards();
    else if (action === "reveal") { flippedId = id; render(); }
    else if (action === "rate") rate(id, target.dataset.rating);
    else if (action === "approve") { if (byId("detailDialog").open) byId("detailDialog").close(); approve(id); }
    else if (action === "ignore") { if (byId("detailDialog").open) byId("detailDialog").close(); ignoreCard(id); }
    else if (action === "edit") { if (byId("detailDialog").open) byId("detailDialog").close(); editCard(id); }
    else if (action === "details") showDetails(id);
    else if (action === "select-source-section") {
      selectedSectionAnchor = target.dataset.anchor || "";
      render();
      byId(`source-section-${target.dataset.sectionIndex}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    } else if (action === "retry-source") {
      sourceLoadState = "idle";
      sourceLoadKey = "";
      render();
    } else if (action === "refresh-unit-review") {
      if (knowledgeAuditState === "loading") return;
      const refresh = ensureKnowledgeAuditLoaded(true);
      render();
      void refresh.then((ready) => { if (ready) toast("来源、章节定位及完整 coverage 台账已重新核验。"); });
    } else if (action === "retry-unit-review") {
      void ensureKnowledgeAuditLoaded(true).then(render);
    } else if (action === "unit-review-page") {
      const page = Number(target.dataset.page);
      if (Number.isSafeInteger(page) && page >= 0) { unitReviewPage = page; render(); }
    } else if (action === "export-unit-reviews") {
      exportKnowledgeUnitReviews();
    } else if (action === "import-unit-reviews") {
      byId("unitReviewImportFile").click();
    } else if (action === "save-unit-review") {
      void saveKnowledgeUnitDecision(id, target.dataset.decision);
    } else if (action === "close-edit") byId("editDialog").close();
    else if (action === "close-details") byId("detailDialog").close();
    else if (action === "study-card") { byId("detailDialog").close(); switchView("today", false, id); }
  }

  function setupEvents() {
    document.addEventListener("click", (event) => {
      const target = event.target.closest("[data-action], [data-view]");
      if (target) handleAction(target);
    });
    byId("globalSearch").addEventListener("input", (event) => { search = event.target.value; if (view === "unitReview") unitReviewPage = 0; flippedId = ""; studyTargetId = ""; render(); });
    byId("filterRow").addEventListener("change", (event) => {
      if (event.target.id === "statusFilter") statusFilter = event.target.value;
      if (event.target.id === "tagFilter") tagFilter = event.target.value;
      if (event.target.id === "unitReviewSubject") { unitReviewSubject = event.target.value; unitReviewPage = 0; }
      if (event.target.id === "unitReviewStatus") { unitReviewStatus = event.target.value; unitReviewPage = 0; }
      if (event.target.id === "sourceSubject") {
        sourceSubject = event.target.value;
        selectedArticleKey = "";
        selectedSectionAnchor = "";
        save();
      }
      if (event.target.id === "sourceArticleSelect") {
        selectSourceArticle(event.target.value);
      }
      render();
    });
    byId("importFile").addEventListener("change", (event) => { if (event.target.files?.[0]) readImport(event.target.files[0]); });
    byId("unitReviewImportFile").addEventListener("change", (event) => {
      const file = event.target.files?.[0];
      if (file) void importKnowledgeUnitReviews(file);
    });
    byId("editForm").addEventListener("submit", (event) => {
      event.preventDefault();
      if (!event.currentTarget.reportValidity()) return;
      const cardIndex = cards.findIndex((item) => item.id === byId("editCardId").value);
      const card = cards[cardIndex];
      if (!card) return;
      const approveAfterSave = event.submitter?.value === "approve";
      const candidate = {
        ...card,
        question: byId("editQuestion").value.trim(),
        answer: byId("editAnswer").value.trim(),
        evidence: byId("editEvidence").value.trim(),
        section: byId("editSection").value.trim(),
        tags: tagsOf(byId("editTags").value)
      };
      if (approveAfterSave) {
        if (needsExplicitReview(card) && !byId("sourceReviewChecked").checked) {
          toast("请先打开来源并逐项确认审核提示，再批准这张卡片。");
          byId("sourceReviewChecked").focus();
          return;
        }
        if (needsExplicitReview(card)) {
          if (card.reviewReason) candidate.reviewedReviewReason = String(card.reviewReason);
          if (card.auditFlags.length) candidate.reviewedAuditFlags = auditSnapshot(card);
          if (card.sourceSectionRemoved || card.sourceArticleMissing) candidate.reviewedSourceVersion = sourceReviewVersion(card);
        }
        const blocked = approvalBlockReason(candidate);
        if (blocked) { toast(blocked); return; }
      }
      const previous = { ...card, tags: [...card.tags] };
      card.question = candidate.question;
      card.answer = candidate.answer;
      card.evidence = candidate.evidence;
      card.section = candidate.section;
      card.tags = candidate.tags;
      if (approveAfterSave) {
        card.status = "approved";
        if (candidate.reviewedReviewReason !== undefined) card.reviewedReviewReason = candidate.reviewedReviewReason;
        if (candidate.reviewedAuditFlags !== undefined) card.reviewedAuditFlags = candidate.reviewedAuditFlags;
        if (candidate.reviewedSourceVersion !== undefined) card.reviewedSourceVersion = candidate.reviewedSourceVersion;
      }
      const saved = saveOrRollback(() => { cards[cardIndex] = previous; });
      if (saved) {
        byId("editDialog").close();
        toast(approveAfterSave ? "Saved and approved. Ready to study!" : "Your changes have been saved.");
      }
      render();
    });
    byId("mobileMenuButton").addEventListener("click", () => {
      const open = byId("sidebar").classList.toggle("is-open");
      byId("mobileMenuButton").setAttribute("aria-expanded", String(open));
    });
    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        byId("globalSearch").focus();
      }
      if (view === "today" && flippedId && /^[1-4]$/.test(event.key) && !byId("editDialog").open && !byId("detailDialog").open && !["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) {
        if (flippedId) rate(flippedId, ["again", "hard", "good", "easy"][Number(event.key) - 1]);
      }
      if (event.key === "Escape") {
        byId("sidebar").classList.remove("is-open");
        byId("mobileMenuButton").setAttribute("aria-expanded", "false");
      }
    });
    for (const dialog of [byId("editDialog"), byId("detailDialog")]) dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
    window.addEventListener("hashchange", () => {
      const next = window.location.hash.slice(1);
      if (VIEWS[next]) switchView(next, true);
    });
  }

  async function loadArticles() {
    articleLoadState = "loading";
    try {
      const response = await fetch(new URL(ARTICLES_URL, window.location.href), { cache: "no-cache" });
      if (!response.ok) throw new Error(`Article catalog request failed (${response.status}).`);
      const data = await response.json();
      if (data?.version !== 1 || !Array.isArray(data.articles)) throw new Error("Expected a version 1 article catalog.");
      articleCatalog = data.articles.map((article) => {
        if (!isRecord(article) || !Object.prototype.hasOwnProperty.call(SUBJECTS, String(article.sourceId || ""))) return null;
        const url = validUrl(String(article.url || ""));
        const title = cleanArticleTitle(String(article.title || ""));
        if (!url || !title) return null;
        return { ...article, sourceId: String(article.sourceId), title, url, cache: String(article.cache || "") };
      }).filter(Boolean).sort((a, b) => a.sourceId.localeCompare(b.sourceId) || a.title.localeCompare(b.title, "zh-CN"));
      articleLoadState = "ready";
      if (view === "sources") render();
    } catch {
      articleCatalog = [];
      articleLoadState = "error";
      if (view === "sources") render();
    }
  }

  async function loadCards() {
    const saved = await readBestSaved();
    progress = saved.progress;
    knowledgeUnitReviews = saved.knowledgeUnitReviews;
    sourceSubject = Object.prototype.hasOwnProperty.call(SUBJECTS, saved.settings.sourceSubject) ? saved.settings.sourceSubject : "all";
    try {
      const response = await fetch(new URL(DATA_URL, window.location.href), { cache: "no-cache" });
      if (!response.ok) throw new Error(`Card data request failed (${response.status}).`);
      const data = await response.json();
      if (data?.version !== 1 || !Array.isArray(data.cards)) throw new Error("Expected a version 1 card collection.");
      const remoteCards = data.cards.map(normalizeCard).filter(Boolean);
      if (data.cards.length && !remoteCards.length) throw new Error("The card collection has no valid cards.");
      cards = mergeRemoteCards(remoteCards, saved);
      await writeCardCache(remoteCards).catch(() => {});
      byId("storageStatus").textContent = "Changes saved automatically";
      save();
    } catch {
      try {
        const cached = await readCardCache();
        const cachedCards = Array.isArray(cached?.cards) ? cached.cards.map(normalizeCard).filter(Boolean) : [];
        if (cachedCards.length || cached?.cards?.length === 0) {
          cards = mergeRemoteCards(cachedCards, saved);
          byId("storageStatus").textContent = "Using cached device copy";
          showNotice("The shared card file could not be reached, so the last cached card collection is open.");
          return;
        }
        throw new Error("No cached card collection.");
      } catch {
        cards = saved.cards;
        remoteBaseCards = new Map();
        byId("storageStatus").textContent = saved.cards.length ? "Using saved device copy" : "Ready for your first import";
        const message = saved.cards.length ? "The shared card file could not be reached, so your saved device copy is open." : location.protocol === "file:" ? "Serve this page over HTTP to load ../data/cards/cards.json. Import cards to start offline." : "No shared card collection was found. Import a version 1 JSON file to get started.";
        showNotice(message);
      }
    }
  }

  async function initialize() {
    setupEvents();
    render();
    await Promise.all([loadCards(), loadArticles(), ensureKnowledgeAuditLoaded()]);
    if (knowledgeAuditState === "ready") await validateSavedKnowledgeReviews();
    render();
    if ("serviceWorker" in navigator && ["http:", "https:"].includes(location.protocol)) navigator.serviceWorker.register("./sw.js").catch(() => {});
  }

  initialize();
})();


