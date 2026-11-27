"use strict";
// OpenPackagedFood Static Database Explorer (v0.3 · Zero-CLS Bootstrap, Doc Cache & Windowed List)
// Reads /v1/ static API endpoints and /locales/*.json dictionaries; escapes all community-supplied strings.

const $ = (s) => document.querySelector(s);
const esc = (v) =>
  String(v ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
const title = (brand, name) => (String(name).startsWith(brand) ? name : `${brand} · ${name}`);
const rel = (p) => String(p).replace(/^\//, "");

function resolveMediaRef(ref) {
  if (!ref) return null;
  if (/^(https?:\/\/|media\/)/.test(ref)) return ref;
  const m = /^opf-media:\/\/sha256\/([a-f0-9]{64})$/.exec(ref);
  const base = typeof META !== "undefined" && META && META.media_base_url;
  if (!m || !base) return null;
  const h = m[1];
  return `${base.replace(/\/+$/, "")}/media/${h.slice(0, 2)}/${h.slice(2, 4)}/${h}.webp`;
}

const SEAL_SVGS = {
  corroborated: '<rect x="6" y="3" width="15" height="12" rx="1.5"/><rect x="3" y="8" width="15" height="12" rx="1.5"/><circle cx="10.5" cy="14" r="2.6"/>',
  verified: '<rect x="3" y="6" width="18" height="13" rx="1.5"/><circle cx="12" cy="12.5" r="3.4"/><path d="M8.5 6l1.4-2h4.2l1.4 2"/>',
  official_registry_imported: '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M7 9h10M7 13h10M7 17h6"/>',
  community_reported: '<circle cx="12" cy="12" r="8" stroke-dasharray="3 2.5"/>',
};

const LIST_CHUNK_SIZE = 40;
const HAS_DOM = typeof document !== "undefined" && typeof window !== "undefined";
const urlParams = new URLSearchParams(typeof location !== "undefined" ? location.search : "");
if (HAS_DOM && (urlParams.get("theme") === "dark" || urlParams.get("theme") === "light")) {
  document.documentElement.setAttribute("data-theme", urlParams.get("theme"));
}

let LOCALE_MANIFEST = {
  default_locale: "en",
  fallback_locale: "en",
  locales: [
    { code: "zh-CN", label: "简体中文", short: "中文", region: "CN", dir: "ltr" },
    { code: "en", label: "English", short: "EN", region: "US/EU", dir: "ltr" },
    { code: "ja", label: "日本語", short: "日本語", region: "JP", dir: "ltr" },
    { code: "ko", label: "한국어", short: "한국어", region: "KR", dir: "ltr" },
    { code: "de", label: "Deutsch", short: "DE", region: "EU", dir: "ltr" },
    { code: "fr", label: "Français", short: "FR", region: "EU", dir: "ltr" },
    { code: "es", label: "Español", short: "ES", region: "EU", dir: "ltr" },
    { code: "it", label: "Italiano", short: "IT", region: "EU", dir: "ltr" },
  ],
};
const LOCALE_CACHE = {};
const PRODUCT_DOC_CACHE = new Map();
let LANG = "en";
let META = null;
let CATALOG = [];
let workbenchOpen = urlParams.get("wb") === "1";

let currentId = null;
let currentItem = null;
let currentCompact = null;
let currentFull = null;
let selectedEditionId = null;
let redirectedFromId = null;

let activeFilteredItems = [];
let renderedListCount = 0;
let listObserver = null;

function withDataRev(p) {
  const base = rel(p);
  const ver = META && (META.opf_data_commit || META.generated_at);
  if (!ver || !base.startsWith("v1/") || base === "v1/meta.json" || base === "v1/bootstrap.json" || base.includes("?")) {
    return base;
  }
  return `${base}?v=${encodeURIComponent(ver)}`;
}

async function getJSON(p, init) {
  const r = await fetch(withDataRev(p), init);
  if (!r.ok) throw new Error(`${r.status} ${p}`);
  return r.json();
}

function resolveKey(obj, keyPath) {
  return String(keyPath)
    .split(".")
    .reduce((acc, part) => (acc && acc[part] !== undefined ? acc[part] : undefined), obj);
}

function t(keyPath, params = null) {
  let val = resolveKey(LOCALE_CACHE[LANG], keyPath);
  if (val === undefined) val = resolveKey(LOCALE_CACHE[LOCALE_MANIFEST.fallback_locale], keyPath);
  if (val === undefined) return keyPath;
  if (typeof val === "string" && params) {
    return val.replace(/\{(\w+)\}/g, (_, k) => (params[k] !== undefined ? String(params[k]) : ""));
  }
  return val;
}

async function ensureLocaleLoaded(code) {
  if (LOCALE_CACHE[code]) return LOCALE_CACHE[code];
  const pf = HAS_DOM && window.__OPF_PREFETCH__;
  if (pf && pf.lang === code && pf.locale) {
    const preloaded = await pf.locale;
    if (preloaded) {
      LOCALE_CACHE[code] = preloaded;
      return preloaded;
    }
  }
  if (pf && code === "en" && pf.fallback) {
    const preloadedEn = await pf.fallback;
    if (preloadedEn) {
      LOCALE_CACHE[code] = preloadedEn;
      return preloadedEn;
    }
  }
  LOCALE_CACHE[code] = await getJSON(`locales/${code}.json`);
  return LOCALE_CACHE[code];
}

function matchSupportedLocale(rawTag, manifest) {
  if (!rawTag) return null;
  const tag = String(rawTag).trim().toLowerCase();
  if (!tag) return null;
  const list = (manifest && manifest.locales) || [];
  const exact = list.find((l) => l.code.toLowerCase() === tag);
  if (exact) return exact.code;
  const base = tag.split(/[-_]/)[0];
  if (base === "zh") {
    const zh = list.find((l) => l.code.toLowerCase().startsWith("zh"));
    if (zh) return zh.code;
  }
  const prefixHit = list.find((l) => l.code.toLowerCase().split("-")[0] === base);
  return prefixHit ? prefixHit.code : null;
}

function detectPreferredLocale(manifest) {
  const fromUrl = matchSupportedLocale(urlParams.get("lang"), manifest);
  if (fromUrl) return fromUrl;
  const fromStorage = matchSupportedLocale(localStorage.getItem("opf_lang"), manifest);
  if (fromStorage) return fromStorage;
  const navLangs =
    Array.isArray(navigator.languages) && navigator.languages.length
      ? navigator.languages
      : navigator.language
        ? [navigator.language]
        : [];
  for (const candidate of navLangs) {
    const matched = matchSupportedLocale(candidate, manifest);
    if (matched) return matched;
  }
  return (manifest && (manifest.fallback_locale || manifest.default_locale)) || "en";
}

function renderSeal(level) {
  if (!level) return "";
  return `<span class="seal ${esc(level)}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${
    SEAL_SVGS[level] || ""
  }</svg><span>${esc(t(`seals.${level}.label`))}</span></span>`;
}

function renderResolutionBadge(resolution, shortForm = false) {
  if (!resolution) return "";
  const text = shortForm ? t(`resolutions.${resolution}.short`) : t(`resolutions.${resolution}.label`);
  return `<span class="res-badge res-${esc(resolution)}"><span>${esc(text)}</span></span>`;
}

function renderStatusBadge(status) {
  if (!status) return "";
  return `<span class="status-badge status-${esc(status)}"><span>${esc(t(`statuses.${status}`))}</span></span>`;
}

function renderRevPill(rev) {
  if (rev === undefined || rev === null) return "";
  return `<span class="rev-pill mono"><span>rev ${esc(rev)}</span></span>`;
}

function pickLocalizedText(localizedArr) {
  if (!Array.isArray(localizedArr) || !localizedArr.length) return "";
  const targetPrefix = LANG.split("-")[0].toLowerCase();
  const exact = localizedArr.find((x) => x.lang === LANG);
  if (exact) return exact.text;
  if (targetPrefix === "zh") {
    const zh = localizedArr.find((x) => x.lang === "zh-Hans" || x.lang === "zh-CN" || x.lang === "zh-Hant");
    if (zh) return zh.text;
  }
  const hit = localizedArr.find((x) => x.lang && x.lang.toLowerCase().startsWith(targetPrefix));
  return hit ? hit.text : localizedArr[0].text;
}

function pickLocalizedProductName(item, attrs) {
  const targetPrefix = LANG.split("-")[0].toLowerCase();
  if (item && item.names) {
    if (item.names[LANG]) return item.names[LANG];
    if (targetPrefix === "zh" && (item.names["zh-Hans"] || item.names["zh-CN"] || item.names["zh-Hant"])) {
      return item.names["zh-Hans"] || item.names["zh-CN"] || item.names["zh-Hant"];
    }
    const prefixKey = Object.keys(item.names).find((k) => k.toLowerCase().startsWith(targetPrefix));
    if (prefixKey) return item.names[prefixKey];
  }
  if (attrs && Array.isArray(attrs.product_name)) {
    const fromAttr = pickLocalizedText(attrs.product_name);
    if (fromAttr) return fromAttr;
    if (Array.isArray(attrs.translations)) {
      const trHit = attrs.translations.find(
        (tr) => tr.field === "product_name" && tr.lang && tr.lang.toLowerCase().startsWith(targetPrefix)
      );
      if (trHit) return trHit.text;
    }
  }
  return item ? item.name : "";
}

function parseLocationHash() {
  const raw = location.hash.replace(/^#/, "");
  if (!raw) return { productId: null, editionId: null, rev: null };
  const decoded = decodeURIComponent(raw);
  const atIdx = decoded.indexOf("@");
  if (atIdx === -1) return { productId: decoded, editionId: null, rev: null };
  const productId = decoded.slice(0, atIdx);
  const rest = decoded.slice(atIdx + 1);
  const revIdx = rest.indexOf("@");
  if (revIdx === -1) return { productId, editionId: rest || null, rev: null };
  return { productId, editionId: rest.slice(0, revIdx) || null, rev: rest.slice(revIdx + 1) || null };
}

async function copyTextWithFeedback(btn, text, origLabel) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
    const labelEl = btn.querySelector("span") || btn;
    labelEl.textContent = t("detail.copiedFeedback");
    setTimeout(() => {
      if (btn.isConnected) labelEl.textContent = origLabel;
    }, 1400);
  } catch (_) {}
}

let detailRenderer = null;
let workbenchController = null;
let scannerController = null;

function getDetailRenderer() {
  if (detailRenderer) return detailRenderer;
  const api =
    (typeof globalThis !== "undefined" && globalThis.OPFDetail) ||
    (typeof require === "function" ? require("./detail.js") : null);
  if (!api) return null;
  detailRenderer = api.createDetailRenderer({
    $,
    t,
    esc,
    title,
    rel,
    renderSeal,
    renderResolutionBadge,
    renderStatusBadge,
    renderRevPill,
    pickLocalizedText,
    pickLocalizedProductName,
    resolveMediaRef,
    copyTextWithFeedback,
    getState: () => ({ selectedEditionId, redirectedFromId }),
    onSelectEdition: (item, compact, full, targetId) => {
      let resolvedId = targetId;
      if (full.edition_redirects && full.edition_redirects[resolvedId]) {
        redirectedFromId = resolvedId;
        resolvedId = full.edition_redirects[resolvedId];
      } else {
        redirectedFromId = null;
      }
      selectedEditionId = resolvedId;
      history.replaceState(null, "", `#${encodeURIComponent(item.id)}@${encodeURIComponent(resolvedId)}`);
      detailRenderer.renderCatalogCard(item, compact, full);
    },
    onReturnOverview: (item, compact, full) => {
      selectedEditionId = null;
      redirectedFromId = null;
      history.replaceState(null, "", `#${encodeURIComponent(item.id)}`);
      detailRenderer.renderCatalogCard(item, compact, full);
    },
    onMobileBack: () => {
      $("#workspace").dataset.mobileView = "list";
      history.replaceState(null, "", location.pathname + location.search);
    },
  });
  return detailRenderer;
}

function formatTActiveText(obj, full, shortMode = false) {
  const dr = getDetailRenderer();
  return dr ? dr.formatTActiveText(obj, full, shortMode) : "";
}

function getWorkbenchController() {
  if (workbenchController) return workbenchController;
  const api =
    (typeof globalThis !== "undefined" && globalThis.OPFWorkbench) ||
    (typeof require === "function" ? require("./workbench.js") : null);
  if (!api) return null;
  const dr = getDetailRenderer();
  workbenchController = api.createWorkbenchController({
    $,
    t,
    esc,
    translateNutrient: (k) => (dr ? dr.translateNutrient(k) : k),
    getCatalog: () => CATALOG,
    isWorkbenchOpen: () => workbenchOpen,
    setWorkbenchOpen: (v) => { workbenchOpen = Boolean(v); },
    onFilterChange: (autoSelect) => renderList(autoSelect),
  });
  return workbenchController;
}

function getScannerController() {
  if (scannerController) return scannerController;
  const api =
    typeof globalThis !== "undefined" && globalThis.OPFScanner
      ? globalThis.OPFScanner
      : typeof require === "function"
        ? require("./scanner.js")
        : null;
  if (!api || typeof api.createScannerController !== "function") return null;
  scannerController = api.createScannerController({
    t,
    esc,
    rel,
    copyTextWithFeedback,
    getCatalog: () => CATALOG,
    applySearchQuery: (queryText, autoSelect = false) => {
      const wb = getWorkbenchController();
      if (wb) wb.setSearchText(queryText, autoSelect);
    },
    selectCatalogItem: (item, switchMobileToDetail) => selectCard(item, switchMobileToDetail),
  });
  return scannerController;
}

function renderLegendSheet() {
  const sealCards = ["corroborated", "verified", "official_registry_imported", "community_reported"]
    .map((lv) => `<div class="legend-card"><div>${renderSeal(lv)}</div><p>${esc(t(`seals.${lv}.desc`))}</p></div>`)
    .join("");
  const target = $("#legend-sheet-body") || $("#legend-sheet");
  if (!target) return;
  target.innerHTML = `
    <div class="legend-grid">${sealCards}</div>
    <div class="state-legend" style="margin-top:12px;">
      <span><b class="mono">18.6 g</b> — ${esc(t("detail.legendReported"))}</span>
      <span><b class="mono val-derived"><span class="num">260.8</span> kcal<sup class="fn-mark">ƒ</sup></b> — ${esc(t("detail.legendDerived"))}</span>
      <span><b class="mono val-bound">&lt; 1.79 g</b> — ${esc(t("detail.legendBound"))}</span>
    </div>`;
}

function applyStaticChrome() {
  const curMeta = LOCALE_MANIFEST.locales.find((l) => l.code === LANG) || { code: LANG, dir: "ltr" };
  document.documentElement.lang = curMeta.code;
  document.documentElement.dir = curMeta.dir || t("meta.dir") || "ltr";
  document.title = t("app.pageTitle");

  document.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => { el.innerHTML = t(el.dataset.i18nHtml); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(el.dataset.i18nPlaceholder); });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => { el.title = t(el.dataset.i18nTitle); });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((el) => { el.setAttribute("aria-label", t(el.dataset.i18nAriaLabel)); });

  const langSelect = $("#lang-select");
  if (langSelect) {
    const expectedCodes = (LOCALE_MANIFEST.locales || []).map((l) => l.code).join("|");
    if (langSelect.dataset.codes !== expectedCodes) {
      langSelect.innerHTML = (LOCALE_MANIFEST.locales || [])
        .map((l) => `<option value="${esc(l.code)}">${esc(l.label)}${l.region ? ` (${esc(l.region)})` : ""}</option>`)
        .join("");
      langSelect.dataset.codes = expectedCodes;
    }
    langSelect.value = LANG;
  }
  renderLegendSheet();
}

function renderStats(meta) {
  const mktCount = Object.keys(meta.counts_by_market || {}).length;
  $("#stats").innerHTML = `
    <span class="stat-inline-item">${esc(t("stats.total"))} <b>${esc(meta.total_products)}</b></span>
    <span class="stat-sep" aria-hidden="true">·</span>
    <span class="stat-inline-item">${esc(t("stats.markets"))} <b>${esc(mktCount)}</b></span>
    <span class="stat-sep" aria-hidden="true">·</span>
    <span class="stat-inline-item">${esc(t("stats.schema"))} <b>v${esc(meta.opf_schema)}</b></span>`;
}

function renderEmptyCatalogCard() {
  $("#workspace").dataset.mobileView = "detail";
  const guideUrl = "https://github.com/mickey996icu/open-packaged-food/blob/main/CONTRIBUTING.md";
  $("#detail").innerHTML = `
    <div class="empty-catalog-guide">
      <div class="card-topbar">
        <div class="call-number-block">
          <span class="cn-label">${esc(t("detail.productIdLabel"))}</span>
          <strong>opf:database/status/v0.3</strong>
        </div>
      </div>
      <hr class="title-rule" />
      <h3>${esc(t("empty.title"))}</h3>
      <p class="lead" style="margin-bottom:16px;">${esc(t("empty.lead"))}</p>
      <div class="subcard">
        <b>${esc(t("empty.step1Title"))}</b>
        <p style="margin:6px 0 0;color:var(--md-on-surface-variant);">${esc(t("empty.step1Desc"))}</p>
      </div>
      <div class="subcard" style="margin-top:12px;">
        <b>${esc(t("empty.step2Title"))}</b>
        <p style="margin:6px 0 0;color:var(--md-on-surface-variant);">${esc(t("empty.step2Desc"))}</p>
      </div>
      <p class="empty-dev-link">
        ${esc(t("empty.devNotePrefix"))}<a href="${esc(guideUrl)}" target="_blank" rel="noopener">${esc(t("empty.devGuideLink"))}</a>
      </p>
    </div>`;
}

function renderEmptyFilterResultHtml() {
  return `<div class="empty-state">
    <p><b>${esc(t("search.emptySearch"))}</b></p>
    <p>${esc(t("search.emptyFilterLead"))}</p>
    <button type="button" class="chip reset-chip reset-all-filters-trigger">${esc(t("search.clearAllFilters"))}</button>
  </div>`;
}

function renderEntryCardHtml(i) {
  const dispName = pickLocalizedProductName(i);
  const brandStr = String(i.brand || "").trim();
  const cleanName =
    brandStr && String(dispName).startsWith(brandStr)
      ? String(dispName).slice(brandStr.length).replace(/^[\s·•-]+/, "") || dispName
      : dispName;
  const kcalDisplay =
    i.energy_kcal_100 !== null && i.energy_kcal_100 !== undefined
      ? `${i.energy_kcal_100} kcal/${i.basis}`
      : i.nutrition_exempt
        ? t("search.nutritionExemptShort")
        : "";
  const mkts = (i.markets || []).join("/");
  const metaParts = [i.net_content, kcalDisplay, mkts].filter(Boolean);
  return `<button type="button" class="index-entry" data-id="${esc(i.id)}" aria-current="${i.id === currentId}">
    ${brandStr ? `<span class="entry-brand">${esc(brandStr)}</span>` : ""}
    <div class="entry-title">${esc(cleanName)}</div>
    <div class="imprint">
      <span>${esc(metaParts.join(" · "))}</span>
      ${i.resolution === "divergent" ? renderResolutionBadge("divergent", true) : ""}
    </div>
  </button>`;
}

function appendNextListChunk() {
  const listEl = $("#list");
  if (!listEl || renderedListCount >= activeFilteredItems.length) return;
  const sentinel = $("#list-sentinel");
  if (sentinel) sentinel.remove();
  const nextSlice = activeFilteredItems.slice(renderedListCount, renderedListCount + LIST_CHUNK_SIZE);
  renderedListCount += nextSlice.length;
  listEl.insertAdjacentHTML("beforeend", nextSlice.map(renderEntryCardHtml).join(""));
  if (renderedListCount < activeFilteredItems.length) {
    listEl.insertAdjacentHTML("beforeend", '<div class="list-sentinel" id="list-sentinel" aria-hidden="true">…</div>');
    observeListSentinel();
  }
}

function observeListSentinel() {
  if (typeof IntersectionObserver !== "function") return;
  if (!listObserver) {
    listObserver = new IntersectionObserver(
      (entries) => {
        if (entries.some((en) => en.isIntersecting)) appendNextListChunk();
      },
      { root: null, rootMargin: "280px" }
    );
  }
  listObserver.disconnect();
  const sentinel = $("#list-sentinel");
  if (sentinel) listObserver.observe(sentinel);
}

function renderList(autoSelect = true, initialEditionId = null) {
  const countEl = $("#results-count");
  if (CATALOG.length === 0) {
    if (countEl) countEl.textContent = t("search.resultsSummary", { shown: 0, total: 0 });
    $("#list").innerHTML = `<div class="empty-state">${esc(t("search.emptyCatalogDrawer"))}</div>`;
    renderEmptyCatalogCard();
    return;
  }

  const wb = getWorkbenchController();
  const hit = wb ? wb.getFilteredAndSortedCatalog() : CATALOG;
  activeFilteredItems = hit;
  if (countEl) countEl.textContent = t("search.resultsSummary", { shown: hit.length, total: CATALOG.length });

  if (!hit.length) {
    renderedListCount = 0;
    $("#list").innerHTML = renderEmptyFilterResultHtml();
    if (autoSelect) $("#detail").innerHTML = renderEmptyFilterResultHtml();
    return;
  }

  const selectedIdx = currentId ? hit.findIndex((i) => i.id === currentId) : 0;
  const initialLimit = Math.min(hit.length, Math.max(LIST_CHUNK_SIZE, selectedIdx + 12));
  renderedListCount = initialLimit;
  const sentinelHtml =
    renderedListCount < hit.length ? '<div class="list-sentinel" id="list-sentinel" aria-hidden="true">…</div>' : "";
  $("#list").innerHTML = hit.slice(0, initialLimit).map(renderEntryCardHtml).join("") + sentinelHtml;
  if (sentinelHtml) observeListSentinel();

  if (autoSelect) {
    const target = (selectedIdx >= 0 && hit[selectedIdx]) || hit[0];
    const edToPass = target.id === currentId ? initialEditionId : null;
    selectCard(target, false, edToPass);
  }
}

function fetchProductDocsCached(item) {
  if (PRODUCT_DOC_CACHE.has(item.id)) return PRODUCT_DOC_CACHE.get(item.id);
  const req = Promise.all([getJSON(item.compact_url), getJSON(item.full_url)])
    .then(([compact, full]) => ({ compact, full }))
    .catch((err) => {
      PRODUCT_DOC_CACHE.delete(item.id);
      throw err;
    });
  PRODUCT_DOC_CACHE.set(item.id, req);
  return req;
}

async function selectCard(item, switchMobileToDetail = false, requestedEditionId = null) {
  const prevId = currentId;
  currentId = item.id;
  selectedEditionId = requestedEditionId || null;
  redirectedFromId = null;

  if (switchMobileToDetail) {
    $("#workspace").dataset.mobileView = "detail";
    const hashTarget = selectedEditionId
      ? `#${encodeURIComponent(item.id)}@${encodeURIComponent(selectedEditionId)}`
      : `#${encodeURIComponent(item.id)}`;
    history.replaceState(null, "", hashTarget);
  } else if (!location.hash) {
    history.replaceState(null, "", `#${encodeURIComponent(item.id)}`);
  }

  if (prevId && prevId !== item.id) {
    const prevBtn = document.querySelector(`.index-entry[data-id="${CSS.escape ? CSS.escape(prevId) : prevId}"]`);
    if (prevBtn) prevBtn.setAttribute("aria-current", "false");
  }
  const nextBtn = document.querySelector(`.index-entry[data-id="${CSS.escape ? CSS.escape(item.id) : item.id}"]`);
  if (nextBtn) nextBtn.setAttribute("aria-current", "true");

  try {
    const { compact, full } = await fetchProductDocsCached(item);
    if (currentId !== item.id) return;
    currentItem = item;
    currentCompact = compact;
    currentFull = full;

    if (selectedEditionId && full.edition_redirects && full.edition_redirects[selectedEditionId]) {
      redirectedFromId = selectedEditionId;
      selectedEditionId = full.edition_redirects[selectedEditionId];
      history.replaceState(null, "", `#${encodeURIComponent(item.id)}@${encodeURIComponent(selectedEditionId)}`);
    }

    const dr = getDetailRenderer();
    if (dr) dr.renderCatalogCard(item, compact, full);
  } catch (e) {
    $("#detail").innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
  }
}

function initControls() {
  $("#theme-toggle").onclick = () => {
    const root = document.documentElement;
    const cur = root.getAttribute("data-theme");
    const isDark = cur === "dark" || (!cur && window.matchMedia("(prefers-color-scheme: dark)").matches);
    root.setAttribute("data-theme", isDark ? "light" : "dark");
    if (typeof window.__OPF_SYNC_PAPER__ === "function") window.__OPF_SYNC_PAPER__();
  };

  const langSelectEl = $("#lang-select");
  if (langSelectEl) {
    langSelectEl.addEventListener("change", async (e) => {
      LANG = matchSupportedLocale(e.target.value, LOCALE_MANIFEST) || "en";
      localStorage.setItem("opf_lang", LANG);
      try {
        const u = new URL(location.href);
        u.searchParams.set("lang", LANG);
        history.replaceState(null, "", `${u.pathname}${u.search}${u.hash}`);
      } catch (_) {}
      await ensureLocaleLoaded(LANG);
      applyStaticChrome();
      const sc = getScannerController();
      if (sc) sc.updateChromeText();
      if (META) renderStats(META);
      const wb = getWorkbenchController();
      if (wb) wb.renderWorkbenchControls();
      renderList(false);
      const dr = getDetailRenderer();
      if (dr && currentItem && currentCompact && currentFull) {
        dr.renderCatalogCard(currentItem, currentCompact, currentFull);
      }
    });
  }

  $("#legend-toggle").onclick = () => {
    const sheet = $("#legend-sheet");
    sheet.hidden = !sheet.hidden;
    $("#legend-toggle").setAttribute("aria-pressed", String(!sheet.hidden));
  };

  const wb = getWorkbenchController();
  if (wb) wb.bindEvents();

  document.addEventListener("click", (e) => {
    if (e.target.closest(".reset-all-filters-trigger") && wb) wb.resetAllFilters();
  });

  window.addEventListener("hashchange", () => {
    const parsed = parseLocationHash();
    if (!parsed.productId) return;
    const hit = CATALOG.find((i) => i.id === parsed.productId);
    if (hit) selectCard(hit, true, parsed.editionId);
  });

  window.addEventListener("keydown", (e) => {
    const scanModal = $("#scan-modal");
    if (e.key === "Escape" && scanModal && !scanModal.hidden) {
      e.preventDefault();
      const sc = getScannerController();
      if (sc) sc.closeModal();
      return;
    }
    if (scanModal && !scanModal.hidden) return;
    const tag = document.activeElement ? document.activeElement.tagName : "";
    const inField = tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA";
    if (e.key === "/" && !inField) {
      e.preventDefault();
      $("#q").focus();
      $("#q").select();
    } else if ((e.key === "ArrowDown" || e.key === "ArrowUp") && !inField) {
      if (!activeFilteredItems.length) return;
      e.preventDefault();
      const idx = activeFilteredItems.findIndex((i) => i.id === currentId);
      const nextIdx = e.key === "ArrowDown" ? Math.min(activeFilteredItems.length - 1, idx + 1) : Math.max(0, idx - 1);
      if (nextIdx >= renderedListCount) appendNextListChunk();
      const item = activeFilteredItems[nextIdx];
      if (item) selectCard(item, true);
    }
  });

  const listEl = $("#list");
  listEl.addEventListener("click", (e) => {
    const b = e.target.closest(".index-entry");
    if (!b) return;
    const item = CATALOG.find((i) => i.id === b.dataset.id);
    if (item) selectCard(item, true, null);
  });
  const prefetchFromEvent = (e) => {
    const b = e.target.closest && e.target.closest(".index-entry");
    if (!b || !b.dataset.id || PRODUCT_DOC_CACHE.has(b.dataset.id)) return;
    const item = CATALOG.find((i) => i.id === b.dataset.id);
    if (item) fetchProductDocsCached(item).catch(() => {});
  };
  listEl.addEventListener("pointerenter", prefetchFromEvent, true);
  listEl.addEventListener("focusin", prefetchFromEvent);

  const sc = getScannerController();
  if (sc) sc.init();
}

async function loadBootstrapOrFallback() {
  const pf = HAS_DOM && window.__OPF_PREFETCH__;
  const boot = pf && pf.bootstrap ? await pf.bootstrap : await getJSON("v1/bootstrap.json", { cache: "no-cache" }).catch(() => null);
  if (boot && boot.meta) {
    if (boot.locale_manifest && Array.isArray(boot.locale_manifest.locales)) {
      LOCALE_MANIFEST = boot.locale_manifest;
    }
    META = boot.meta;
    if (boot.initial_product && boot.initial_product.id) {
      PRODUCT_DOC_CACHE.set(
        boot.initial_product.id,
        Promise.resolve({ compact: boot.initial_product.compact, full: boot.initial_product.full })
      );
    }
    if (Array.isArray(boot.catalog)) {
      CATALOG = boot.catalog;
      return;
    }
  } else {
    META = await getJSON("v1/meta.json", { cache: "no-cache" });
  }
  const catResp = await fetch(withDataRev("v1/index/catalog.jsonl"));
  if (!catResp.ok) throw new Error(`${catResp.status} v1/index/catalog.jsonl`);
  const text = await catResp.text();
  CATALOG = text.split("\n").filter(Boolean).map((l) => JSON.parse(l));
}

async function init() {
  LANG = detectPreferredLocale(LOCALE_MANIFEST);
  const fallbackCode = LOCALE_MANIFEST.fallback_locale || "en";
  const localeTasks = [ensureLocaleLoaded(LANG)];
  if (LANG !== fallbackCode) localeTasks.push(ensureLocaleLoaded(fallbackCode));

  initControls();
  if (urlParams.get("legend") === "1") {
    $("#legend-sheet").hidden = false;
    $("#legend-toggle").setAttribute("aria-pressed", "true");
  }

  try {
    const [, bootErr] = await Promise.all([
      Promise.all(localeTasks),
      loadBootstrapOrFallback().then(() => null, (err) => err),
    ]);
    applyStaticChrome();
    if (bootErr) throw bootErr;

    const schemaFooter = $("#footer-schema");
    if (schemaFooter && META.opf_schema) {
      schemaFooter.textContent = `OpenPackagedFood Schema v${META.opf_schema}`;
    }
    renderStats(META);
    const wb = getWorkbenchController();
    if (wb) wb.renderWorkbenchControls();
    const parsedHash = parseLocationHash();
    if (parsedHash.productId && CATALOG.some((i) => i.id === parsedHash.productId)) {
      currentId = parsedHash.productId;
      selectedEditionId = parsedHash.editionId;
      $("#workspace").dataset.mobileView = "detail";
    }
    renderList(true, parsedHash.editionId);
  } catch (e) {
    applyStaticChrome();
    $("#detail").innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
  }
}

if (HAS_DOM) {
  init();
}

if (typeof module !== "undefined" && module.exports) {
  const scannerApi =
    typeof globalThis !== "undefined" && globalThis.OPFScanner
      ? globalThis.OPFScanner
      : require("./scanner.js");
  module.exports = {
    isValidGs1CheckDigit: scannerApi.isValidGs1CheckDigit,
    parseScannedCode: scannerApi.parseScannedCode,
    buildGtinApiPath: scannerApi.buildGtinApiPath,
    buildOpfApiPath: scannerApi.buildOpfApiPath,
  };
}
