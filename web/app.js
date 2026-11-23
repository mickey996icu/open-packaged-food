"use strict";
// OpenPackagedFood Static Database Explorer (v0.2 · Material 3 Expressive + Filter Workbench)
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

// Resolve evidence media references; opf-media://sha256/<hex> requires meta.media_base_url.
function resolveMediaRef(ref) {
  if (!ref) return null;
  if (/^(https?:\/\/|media\/)/.test(ref)) return ref;
  const m = /^opf-media:\/\/sha256\/([a-f0-9]{64})$/.exec(ref);
  const base = typeof META !== "undefined" && META && META.media_base_url;
  if (!m || !base) return null;
  const h = m[1];
  return `${base.replace(/\/+$/, "")}/media/${h.slice(0, 2)}/${h.slice(2, 4)}/${h}.webp`;
}

// Inline SVG icons (100% offline, zero external icon font dependencies)
const CHIP_CHECK_SVG =
  '<svg class="chip-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.2 4.2L19 7.5"/></svg>';

// Shape-distinguished Evidence Level Badges
const SEAL_SVGS = {
  corroborated: '<circle cx="12" cy="12" r="9.5"/><circle cx="12" cy="12" r="6.2"/><path d="M9.2 12.2l1.9 1.9 3.8-4"/>',
  verified: '<circle cx="12" cy="12" r="9"/><path d="M8 12.2l2.6 2.6L16 9.4"/>',
  official_registry_imported: '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M7 9h10M7 13h10M7 17h6"/>',
  community_reported: '<circle cx="12" cy="12" r="8" stroke-dasharray="3 2.5"/>',
};

const NUTRIENT_ORDER = [
  "energy_kj",
  "energy_kcal",
  "protein",
  "fat_total",
  "fat_saturated",
  "fat_trans",
  "fat_monounsaturated",
  "fat_polyunsaturated",
  "cholesterol",
  "carbs_available",
  "carbs_total",
  "sugars_total",
  "sugars_added",
  "sugar_alcohols",
  "dietary_fiber",
  "sodium",
  "salt_equivalent",
  "calcium",
  "iron",
  "potassium",
  "vitamin_a",
  "vitamin_c",
  "vitamin_d",
];

const NUTRIENT_DEFAULT_UNITS = {
  energy_kcal: "kcal",
  energy_kj: "kJ",
  protein: "g",
  fat_total: "g",
  fat_saturated: "g",
  fat_trans: "g",
  fat_monounsaturated: "g",
  fat_polyunsaturated: "g",
  cholesterol: "mg",
  carbs_available: "g",
  carbs_total: "g",
  sugars_total: "g",
  sugars_added: "g",
  sugar_alcohols: "g",
  dietary_fiber: "g",
  sodium: "mg",
  salt_equivalent: "g",
  calcium: "mg",
  iron: "mg",
  potassium: "mg",
  vitamin_a: "ug",
  vitamin_c: "mg",
  vitamin_d: "ug",
};

const RULE_NUTRIENT_OPTIONS = [
  "energy_kcal",
  "energy_kj",
  "protein",
  "fat_total",
  "fat_saturated",
  "carbs_available",
  "carbs_total",
  "sugars_total",
  "sugars_added",
  "dietary_fiber",
  "sodium",
  "salt_equivalent",
  "calcium",
  "vitamin_d",
];

const RESOLUTION_ORDER = ["single", "uniform", "divergent", "inactive"];
const EVIDENCE_ORDER = [
  "corroborated",
  "verified",
  "official_registry_imported",
  "community_reported",
];

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
    { code: "de", label: "Deutsch", short: "DE", region: "EU", dir: "ltr" },
    { code: "fr", label: "Français", short: "FR", region: "EU", dir: "ltr" },
    { code: "es", label: "Español", short: "ES", region: "EU", dir: "ltr" },
    { code: "it", label: "Italiano", short: "IT", region: "EU", dir: "ltr" },
  ],
};
const LOCALE_CACHE = {};
let LANG = "en";

let META = null;
let CATALOG = [];
let nextRuleUid = 1;
let filter = {
  text: "",
  markets: [],
  resolutions: [],
  levels: [],
  profiles: [],
  namespaces: [],
  brands: [],
  excludeAllergens: [],
  includeIngredients: [],
  excludeIngredients: [],
  zeroAdditives: false,
  zeroCalorie: false,
  nutrientRules: [],
  sort: "default",
};
let workbenchOpen = urlParams.get("wb") === "1";

let currentId = null;
let currentItem = null;
let currentCompact = null;
let currentFull = null;
let selectedEditionId = null;
let redirectedFromId = null;

async function getJSON(p) {
  const r = await fetch(rel(p));
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
  if (val === undefined) {
    val = resolveKey(LOCALE_CACHE[LOCALE_MANIFEST.fallback_locale], keyPath);
  }
  if (val === undefined) {
    return keyPath;
  }
  if (typeof val === "string" && params) {
    return val.replace(/\{(\w+)\}/g, (_, k) => (params[k] !== undefined ? String(params[k]) : ""));
  }
  return val;
}

async function ensureLocaleLoaded(code) {
  if (!LOCALE_CACHE[code]) {
    LOCALE_CACHE[code] = await getJSON(`locales/${code}.json`);
  }
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

  const navLangs = Array.isArray(navigator.languages) && navigator.languages.length
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

async function initI18n() {
  try {
    LOCALE_MANIFEST = await getJSON("locales/index.json");
  } catch (_) {
    // Use default manifest fallback if index.json cannot be fetched
  }
  LANG = detectPreferredLocale(LOCALE_MANIFEST);
  await Promise.all([
    ensureLocaleLoaded(LANG),
    ensureLocaleLoaded(LOCALE_MANIFEST.fallback_locale || "en"),
  ]);
}

function renderSeal(level) {
  if (!level) return "";
  const label = t(`seals.${level}.label`);
  const svgBody = SEAL_SVGS[level] || "";
  return `<span class="seal ${esc(level)}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${svgBody}</svg>${esc(label)}</span>`;
}

function renderResolutionBadge(resolution, shortForm = false) {
  if (!resolution) return "";
  const text = shortForm
    ? t(`resolutions.${resolution}.short`)
    : t(`resolutions.${resolution}.label`);
  return `<span class="res-badge res-${esc(resolution)}">${esc(text)}</span>`;
}

function renderStatusBadge(status) {
  if (!status) return "";
  return `<span class="status-badge status-${esc(status)}">${esc(t(`statuses.${status}`))}</span>`;
}

function renderRevPill(rev) {
  if (rev === undefined || rev === null) return "";
  return `<span class="rev-pill mono">rev ${esc(rev)}</span>`;
}

function pickLocalizedText(localizedArr) {
  if (!Array.isArray(localizedArr) || !localizedArr.length) return "";
  const targetPrefix = LANG.split("-")[0].toLowerCase();
  const exact = localizedArr.find((x) => x.lang === LANG);
  if (exact) return exact.text;
  if (targetPrefix === "zh") {
    const zh = localizedArr.find((x) => x.lang === "zh-Hans" || x.lang === "zh-CN");
    if (zh) return zh.text;
  }
  const hit = localizedArr.find((x) => x.lang && x.lang.toLowerCase().startsWith(targetPrefix));
  return hit ? hit.text : localizedArr[0].text;
}

function pickLocalizedProductName(item, attrs) {
  const targetPrefix = LANG.split("-")[0].toLowerCase();
  if (item && item.names) {
    if (item.names[LANG]) return item.names[LANG];
    if (targetPrefix === "zh" && (item.names["zh-Hans"] || item.names["zh-CN"])) {
      return item.names["zh-Hans"] || item.names["zh-CN"];
    }
    const prefixKey = Object.keys(item.names).find((k) => k.toLowerCase().startsWith(targetPrefix));
    if (prefixKey) return item.names[prefixKey];
  }
  if (attrs && Array.isArray(attrs.product_name)) {
    const fromAttr = pickLocalizedText(attrs.product_name);
    if (fromAttr) return fromAttr;
    if (Array.isArray(attrs.translations)) {
      const trHit = attrs.translations.find(
        (tr) =>
          tr.field === "product_name" &&
          tr.lang &&
          tr.lang.toLowerCase().startsWith(targetPrefix)
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
  return {
    productId,
    editionId: rest.slice(0, revIdx) || null,
    rev: rest.slice(revIdx + 1) || null,
  };
}

function formatNetContent(items) {
  if (!Array.isArray(items) || !items.length) return "—";
  return items
    .map((nc) => {
      const q = nc.qualifier && nc.qualifier !== "=" ? nc.qualifier : "";
      return `${q}${nc.value}${nc.unit}`;
    })
    .join(" / ");
}

function renderLegendSheet() {
  const sealCards = ["corroborated", "verified", "official_registry_imported", "community_reported"]
    .map(
      (lv) => `<div class="legend-card">
        <div>${renderSeal(lv)}</div>
        <p>${esc(t(`seals.${lv}.desc`))}</p>
      </div>`
    )
    .join("");
  const target = $("#legend-sheet-body") || $("#legend-sheet");
  target.innerHTML = `
    <div class="legend-grid">${sealCards}</div>
    <div class="state-legend" style="margin-top:12px;">
      <span><b class="mono">18.6 g</b> — ${esc(t("detail.legendReported"))}</span>
      <span><b class="mono val-derived"><span class="num">260.8</span> kcal<sup class="fn-mark">ƒ</sup></b> — ${esc(t("detail.legendDerived"))}</span>
      <span><b class="mono val-bound">&lt; 1.79 g</b> — ${esc(t("detail.legendBound"))}</span>
    </div>`;
}

function applyStaticChrome() {
  const curMeta = LOCALE_MANIFEST.locales.find((l) => l.code === LANG) || {
    code: LANG,
    dir: "ltr",
  };
  document.documentElement.lang = curMeta.code;
  document.documentElement.dir = curMeta.dir || t("meta.dir") || "ltr";
  document.title = t("app.pageTitle");

  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-html]").forEach((el) => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
  });
  document.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
    el.setAttribute("aria-label", t(el.dataset.i18nAriaLabel));
  });

  const langSelect = $("#lang-select");
  if (langSelect) {
    const expectedCodes = (LOCALE_MANIFEST.locales || []).map((l) => l.code).join("|");
    if (langSelect.dataset.codes !== expectedCodes) {
      langSelect.innerHTML = (LOCALE_MANIFEST.locales || [])
        .map(
          (l) =>
            `<option value="${esc(l.code)}">${esc(l.label)}${l.region ? ` (${esc(l.region)})` : ""}</option>`
        )
        .join("");
      langSelect.dataset.codes = expectedCodes;
    }
    langSelect.value = LANG;
  }
  renderLegendSheet();
}

function toggleArrayVal(arr, val) {
  return arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val];
}

function isRuleActive(rule) {
  if (!rule) return false;
  if (rule.op === "range") {
    return (
      (rule.minVal !== "" && rule.minVal !== undefined && !Number.isNaN(Number(rule.minVal))) ||
      (rule.maxVal !== "" && rule.maxVal !== undefined && !Number.isNaN(Number(rule.maxVal)))
    );
  }
  return rule.val !== "" && rule.val !== undefined && !Number.isNaN(Number(rule.val));
}

function countAdvancedFilters() {
  return (
    filter.resolutions.length +
    filter.levels.length +
    filter.profiles.length +
    filter.namespaces.length +
    filter.brands.length +
    filter.excludeAllergens.length +
    filter.includeIngredients.length +
    filter.excludeIngredients.length +
    (filter.zeroAdditives ? 1 : 0) +
    (filter.zeroCalorie ? 1 : 0) +
    filter.nutrientRules.filter(isRuleActive).length
  );
}

function countAllActiveFilters() {
  return (
    (filter.text.trim() ? 1 : 0) +
    filter.markets.length +
    countAdvancedFilters()
  );
}

function resetAllFilters() {
  filter = {
    text: "",
    markets: [],
    resolutions: [],
    levels: [],
    profiles: [],
    namespaces: [],
    brands: [],
    excludeAllergens: [],
    includeIngredients: [],
    excludeIngredients: [],
    zeroAdditives: false,
    zeroCalorie: false,
    nutrientRules: [],
    sort: "default",
  };
  const qEl = $("#q");
  if (qEl) qEl.value = "";
  renderWorkbenchControls();
  renderList(true);
}

function getNutrientUnitForRule(nutrientKey) {
  return NUTRIENT_DEFAULT_UNITS[nutrientKey] || "g";
}

function addNutrientRule(nutrient = "protein", op = "ge", val = "", minVal = "", maxVal = "") {
  filter.nutrientRules.push({
    id: `r${nextRuleUid++}`,
    nutrient,
    op,
    val: val === "" ? "" : String(val),
    minVal: minVal === "" ? "" : String(minVal),
    maxVal: maxVal === "" ? "" : String(maxVal),
  });
  renderWorkbenchControls();
  renderList(true);
}

function formatRuleChipLabel(rule) {
  const nLabel = translateNutrient(rule.nutrient);
  const unit = getNutrientUnitForRule(rule.nutrient);
  if (rule.op === "le") return `${nLabel} ≤ ${rule.val}${unit}`;
  if (rule.op === "ge") return `${nLabel} ≥ ${rule.val}${unit}`;
  const lo = rule.minVal !== "" ? rule.minVal : "0";
  const hi = rule.maxVal !== "" ? rule.maxVal : "∞";
  return `${nLabel}: ${lo}–${hi}${unit}`;
}

function updateWorkbenchChromeAndStrip() {
  const qClear = $("#q-clear");
  if (qClear) qClear.hidden = !filter.text;

  const panel = $("#filter-panel");
  const toggleBtn = $("#wb-toggle");
  const advCount = countAdvancedFilters();
  if (panel) panel.hidden = !workbenchOpen;
  if (toggleBtn) {
    toggleBtn.setAttribute("aria-expanded", String(workbenchOpen));
    toggleBtn.textContent = advCount
      ? `${t("search.wbToggle")} (${advCount})`
      : t("search.wbToggle");
  }

  const tags = [];
  if (filter.text.trim()) {
    tags.push({ kind: "text", val: "", label: t("search.tagQuery", { val: filter.text.trim() }), excl: false });
  }
  filter.markets.forEach((m) =>
    tags.push({ kind: "market", val: m, label: t("search.tagMarket", { val: m }), excl: false })
  );
  filter.resolutions.forEach((r) =>
    tags.push({ kind: "resolution", val: r, label: t("search.tagResolution", { val: t(`resolutions.${r}.short`) }), excl: false })
  );
  filter.levels.forEach((lv) =>
    tags.push({ kind: "level", val: lv, label: t("search.tagEvidence", { val: t(`seals.${lv}.label`) }), excl: false })
  );
  filter.profiles.forEach((pr) =>
    tags.push({ kind: "profile", val: pr, label: t("search.tagProfile", { val: pr }), excl: false })
  );
  filter.namespaces.forEach((ns) =>
    tags.push({ kind: "namespace", val: ns, label: t("search.tagNamespace", { val: ns.toUpperCase() }), excl: false })
  );
  filter.brands.forEach((bslug) => {
    const found = CATALOG.find((i) => (i.brand_slug || i.brand) === bslug);
    tags.push({ kind: "brand", val: bslug, label: t("search.tagBrand", { val: found ? found.brand : bslug }), excl: false });
  });
  filter.excludeAllergens.forEach((alg) => {
    const tr = t(`allergens.${alg}`);
    tags.push({
      kind: "exclAllergen",
      val: alg,
      label: t("search.tagExclAllergen", { val: tr !== `allergens.${alg}` ? tr : alg }),
      excl: true,
    });
  });
  filter.includeIngredients.forEach((term) =>
    tags.push({ kind: "inclIng", val: term, label: t("search.tagInclIng", { val: term }), excl: false })
  );
  filter.excludeIngredients.forEach((term) =>
    tags.push({ kind: "exclIng", val: term, label: t("search.tagExclIng", { val: term }), excl: true })
  );
  if (filter.zeroAdditives) {
    tags.push({ kind: "zeroAdd", val: "1", label: t("search.zeroAdditivesChip"), excl: false });
  }
  if (filter.zeroCalorie) {
    tags.push({ kind: "zeroCal", val: "1", label: t("search.zeroCalorieChip"), excl: false });
  }
  filter.nutrientRules.filter(isRuleActive).forEach((rule) =>
    tags.push({ kind: "rule", val: rule.id, label: formatRuleChipLabel(rule), excl: false })
  );

  const strip = $("#active-filters-strip");
  const tagsWrap = $("#active-filter-tags");
  if (strip && tagsWrap) {
    strip.hidden = tags.length === 0;
    tagsWrap.innerHTML = tags
      .map(
        (tg) =>
          `<button type="button" class="active-tag${tg.excl ? " exclude" : ""}" data-remove-kind="${esc(tg.kind)}" data-remove-val="${esc(tg.val)}"><span>${esc(tg.label)}</span> <span aria-hidden="true">×</span></button>`
      )
      .join("");
  }
}

function makeFilterChip({ attrName, attrVal, label, active, extraClass = "" }) {
  const cls = ["chip", "filter-chip", extraClass].filter(Boolean).join(" ");
  return `<button type="button" class="${cls}" data-${attrName}="${esc(attrVal)}" aria-pressed="${active}">${
    active ? CHIP_CHECK_SVG : ""
  }<span>${esc(label)}</span></button>`;
}

function renderWorkbenchControls() {
  // Sort dropdown
  const sortEl = $("#sort-select");
  if (sortEl) {
    const sortOptions = [
      ["default", t("search.sortDefault")],
      ["kcal_asc", t("search.sortKcalAsc")],
      ["kcal_desc", t("search.sortKcalDesc")],
      ["protein_desc", t("search.sortProteinDesc")],
      ["sodium_asc", t("search.sortSodiumAsc")],
      ["brand_asc", t("search.sortBrandAsc")],
    ];
    sortEl.innerHTML = sortOptions
      .map(
        ([val, lbl]) =>
          `<option value="${esc(val)}"${filter.sort === val ? " selected" : ""}>${esc(lbl)}</option>`
      )
      .join("");
  }

  // Gather dynamic facet counts from CATALOG
  const marketCounts = {};
  const resCounts = {};
  const levelCounts = {};
  const profileCounts = {};
  const nsCounts = {};
  const brandsMap = {};
  const allergenSet = new Set();
  let zeroAdditivesCount = 0;
  let zeroCalorieCount = 0;

  CATALOG.forEach((item) => {
    (item.markets || []).forEach((m) => {
      marketCounts[m] = (marketCounts[m] || 0) + 1;
    });
    if (item.resolution) resCounts[item.resolution] = (resCounts[item.resolution] || 0) + 1;
    if (item.evidence_level) levelCounts[item.evidence_level] = (levelCounts[item.evidence_level] || 0) + 1;
    (item.profiles || []).forEach((p) => {
      profileCounts[p] = (profileCounts[p] || 0) + 1;
    });
    if (item.namespace) nsCounts[item.namespace] = (nsCounts[item.namespace] || 0) + 1;
    if (item.brand_slug || item.brand) {
      const slug = item.brand_slug || item.brand;
      if (!brandsMap[slug]) brandsMap[slug] = { slug, name: item.brand, count: 0 };
      brandsMap[slug].count += 1;
    }
    (item.allergens_contains || []).forEach((a) => allergenSet.add(a));
    (item.allergens_may_contain || []).forEach((a) => allergenSet.add(a));
    if ((item.additives_count ?? 0) === 0) zeroAdditivesCount += 1;
    const ek = item.nutrients_100 && item.nutrients_100.energy_kcal;
    if (ek && !ek.partial && ek.max <= 5) zeroCalorieCount += 1;
  });

  // Layer 1: Multi-select Markets row
  const marketEntries = Object.entries(marketCounts).sort(
    (a, b) => b[1] - a[1] || a[0].localeCompare(b[0])
  );
  const marketRow = $("#market-filters");
  if (marketRow) {
    marketRow.innerHTML =
      makeFilterChip({
        attrName: "market",
        attrVal: "",
        label: `${t("search.allMarkets")} (${CATALOG.length})`,
        active: filter.markets.length === 0,
      }) +
      marketEntries
        .map(([mkt, cnt]) =>
          makeFilterChip({
            attrName: "market",
            attrVal: mkt,
            label: `${mkt} (${cnt})`,
            active: filter.markets.includes(mkt),
          })
        )
        .join("");
  }

  // Layer 2 Col 1: Status, Compliance & Brand (multi-select)
  const colFacets = $("#wb-col-facets");
  if (colFacets) {
    const presentRes = RESOLUTION_ORDER.filter((r) => resCounts[r]);
    const resHtml =
      makeFilterChip({
        attrName: "resolution",
        attrVal: "",
        label: t("search.allResolutions"),
        active: filter.resolutions.length === 0,
      }) +
      presentRes
        .map((r) =>
          makeFilterChip({
            attrName: "resolution",
            attrVal: r,
            label: `${t(`resolutions.${r}.short`)} (${resCounts[r]})`,
            active: filter.resolutions.includes(r),
          })
        )
        .join("");

    const levelKeys = [
      ...EVIDENCE_ORDER.filter((lv) => levelCounts[lv]),
      ...Object.keys(levelCounts).filter((lv) => !EVIDENCE_ORDER.includes(lv)),
    ];
    const levelHtml =
      makeFilterChip({
        attrName: "level",
        attrVal: "",
        label: t("search.allEvidence"),
        active: filter.levels.length === 0,
      }) +
      levelKeys
        .map((lv) =>
          makeFilterChip({
            attrName: "level",
            attrVal: lv,
            label: `${t(`seals.${lv}.label`)} (${levelCounts[lv]})`,
            active: filter.levels.includes(lv),
          })
        )
        .join("");

    const profileKeys = Object.keys(profileCounts).sort();
    const nsKeys = ["gtin", "opf"].filter((ns) => nsCounts[ns]);
    const profileHtml = [
      ...profileKeys.map((pr) =>
        makeFilterChip({
          attrName: "profile",
          attrVal: pr,
          label: `${pr.split("/")[0]}/${pr.split("/")[1].split("-")[0]} (${profileCounts[pr]})`,
          active: filter.profiles.includes(pr),
        })
      ),
      ...nsKeys.map((ns) =>
        makeFilterChip({
          attrName: "namespace",
          attrVal: ns,
          label: `${ns.toUpperCase()} (${nsCounts[ns]})`,
          active: filter.namespaces.includes(ns),
        })
      ),
    ].join("");

    const brandList = Object.values(brandsMap).sort(
      (a, b) => b.count - a.count || a.name.localeCompare(b.name)
    );
    const brandHtml = brandList
      .map((b) =>
        makeFilterChip({
          attrName: "brand",
          attrVal: b.slug,
          label: `${b.name} (${b.count})`,
          active: filter.brands.includes(b.slug),
        })
      )
      .join("");

    colFacets.innerHTML = `
      <div class="wb-col-title">${esc(t("search.colFacets"))}</div>
      <div>
        <div class="filter-group-head"><span class="filter-group-title">${esc(t("search.groupResolution"))}</span></div>
        <div class="filter-chip-row">${resHtml}</div>
      </div>
      <div>
        <div class="filter-group-head"><span class="filter-group-title">${esc(t("search.groupEvidence"))}</span></div>
        <div class="filter-chip-row">${levelHtml}</div>
      </div>
      <div>
        <div class="filter-group-head"><span class="filter-group-title">${esc(t("search.groupProfile"))}</span></div>
        <div class="filter-chip-row">${profileHtml}</div>
      </div>
      <div>
        <div class="filter-group-head"><span class="filter-group-title">${esc(t("search.groupBrand"))}</span></div>
        <div class="filter-chip-row">${brandHtml}</div>
      </div>`;
  }

  // Layer 2 Col 2: Allergens, Ingredients & Additives Logic
  const colIng = $("#wb-col-ingredients");
  if (colIng) {
    const sortedAllergens = [...allergenSet].sort();
    const allergensHtml = sortedAllergens
      .map((code) => {
        const lbl = t(`allergens.${code}`);
        return makeFilterChip({
          attrName: "exclude-allergen",
          attrVal: code,
          label: lbl !== `allergens.${code}` ? lbl : code,
          active: filter.excludeAllergens.includes(code),
          extraClass: "exclude-chip",
        });
      })
      .join("");

    const incTagsHtml = filter.includeIngredients
      .map(
        (term) =>
          `<button type="button" class="active-tag" data-rm-inc-ing="${esc(term)}"><span>+ ${esc(term)}</span> <span aria-hidden="true">×</span></button>`
      )
      .join("");
    const excTagsHtml = filter.excludeIngredients
      .map(
        (term) =>
          `<button type="button" class="active-tag exclude" data-rm-exc-ing="${esc(term)}"><span>− ${esc(term)}</span> <span aria-hidden="true">×</span></button>`
      )
      .join("");

    colIng.innerHTML = `
      <div class="wb-col-title">${esc(t("search.colIngredients"))}</div>
      ${
        sortedAllergens.length
          ? `<div>
              <div class="filter-group-head"><span class="filter-group-title">${esc(t("search.groupExcludeAllergens"))}</span></div>
              <p class="filter-group-hint">${esc(t("search.excludeAllergensHint"))}</p>
              <div class="filter-chip-row">${allergensHtml}</div>
            </div>`
          : ""
      }
      <div>
        <div class="filter-group-head"><span class="filter-group-title">${esc(t("search.mustIncludeLabel"))}</span></div>
        <div class="tag-input-row">
          <input type="text" class="wb-input" id="inc-ing-input" placeholder="${esc(t("search.mustIncludePlaceholder"))}" />
          <button type="button" class="chip" id="inc-ing-add">${esc(t("search.addTagBtn"))}</button>
        </div>
        ${incTagsHtml ? `<div class="filter-chip-row" style="margin-top:6px;">${incTagsHtml}</div>` : ""}
      </div>
      <div>
        <div class="filter-group-head"><span class="filter-group-title">${esc(t("search.mustExcludeLabel"))}</span></div>
        <div class="tag-input-row">
          <input type="text" class="wb-input" id="exc-ing-input" placeholder="${esc(t("search.mustExcludePlaceholder"))}" />
          <button type="button" class="chip" id="exc-ing-add">${esc(t("search.addTagBtn"))}</button>
        </div>
        ${excTagsHtml ? `<div class="filter-chip-row" style="margin-top:6px;">${excTagsHtml}</div>` : ""}
      </div>
      <div>
        <div class="filter-group-head"><span class="filter-group-title">${esc(t("search.groupFeatures"))}</span></div>
        <div class="filter-chip-row">
          <button type="button" class="chip filter-chip" data-trait="zero-additives" aria-pressed="${filter.zeroAdditives}">${
            filter.zeroAdditives ? CHIP_CHECK_SVG : ""
          }<span>${esc(t("search.zeroAdditivesChip"))} (${esc(zeroAdditivesCount)})</span></button>
          <button type="button" class="chip filter-chip" data-trait="zero-calorie" aria-pressed="${filter.zeroCalorie}">${
            filter.zeroCalorie ? CHIP_CHECK_SVG : ""
          }<span>${esc(t("search.zeroCalorieChip"))} (${esc(zeroCalorieCount)})</span></button>
        </div>
      </div>`;
  }

  // Layer 2 Col 3: Dynamic Nutrient Value Rule Builder (per 100g/100ml)
  const colNut = $("#wb-col-nutrients");
  if (colNut) {
    const presetsHtml = `
      <div class="filter-chip-row">
        <button type="button" class="chip filter-chip" data-preset="high_protein">${esc(t("search.presetHighProtein"))}</button>
        <button type="button" class="chip filter-chip" data-preset="low_sodium">${esc(t("search.presetLowSodium"))}</button>
        <button type="button" class="chip filter-chip" data-preset="low_sugar">${esc(t("search.presetLowSugar"))}</button>
        <button type="button" class="chip filter-chip" data-preset="low_fat">${esc(t("search.presetLowFat"))}</button>
      </div>`;

    const rulesHtml = filter.nutrientRules
      .map((rule) => {
        const nutOpts = RULE_NUTRIENT_OPTIONS.map(
          (nk) => `<option value="${esc(nk)}"${rule.nutrient === nk ? " selected" : ""}>${esc(translateNutrient(nk))}</option>`
        ).join("");
        const opOpts = [
          ["le", t("search.opLe")],
          ["ge", t("search.opGe")],
          ["range", t("search.opRange")],
        ]
          .map(
            ([opv, opl]) => `<option value="${esc(opv)}"${rule.op === opv ? " selected" : ""}>${esc(opl)}</option>`
          )
          .join("");
        const unit = getNutrientUnitForRule(rule.nutrient);
        const inputsHtml =
          rule.op === "range"
            ? `<input type="number" min="0" step="any" class="wb-input num-input rule-min" value="${esc(rule.minVal)}" placeholder="${esc(t("search.minPlaceholder"))}" />
               <span aria-hidden="true">~</span>
               <input type="number" min="0" step="any" class="wb-input num-input rule-max" value="${esc(rule.maxVal)}" placeholder="${esc(t("search.maxPlaceholder"))}" />`
            : `<input type="number" min="0" step="any" class="wb-input num-input rule-val" value="${esc(rule.val)}" placeholder="${esc(t("search.valPlaceholder"))}" />`;
        return `<div class="n-rule-row" data-rule-id="${esc(rule.id)}">
          <select class="md3-select rule-nutrient" aria-label="${esc(t("detail.colNutrient"))}">${nutOpts}</select>
          <select class="md3-select rule-op">${opOpts}</select>
          ${inputsHtml}
          <span class="rule-unit">${esc(unit)}</span>
          <button type="button" class="icon-clear-btn remove-rule-btn" title="${esc(t("search.removeRuleTitle"))}" aria-label="${esc(t("search.removeRuleTitle"))}">×</button>
        </div>`;
      })
      .join("");

    colNut.innerHTML = `
      <div class="wb-col-title">${esc(t("search.colNutrients"))}</div>
      <div>
        <div class="filter-group-head"><span class="filter-group-title">${esc(t("search.presetsLabel"))}</span></div>
        ${presetsHtml}
      </div>
      <div class="nutrient-rules-list" id="nutrient-rules-list">${rulesHtml}</div>
      <div>
        <button type="button" class="chip" id="add-nutrient-rule-btn">${esc(t("search.addNutrientRule"))}</button>
      </div>`;
  }

  updateWorkbenchChromeAndStrip();
}

function itemMatchesIngTerm(item, rawTerm) {
  const q = rawTerm.trim().toLowerCase();
  if (!q) return true;
  const toks = item.ingredients_tokens || [];
  if (toks.some((tok) => tok.includes(q))) return true;
  const insList = item.additives_ins || [];
  const bare = q.replace(/^(ins|e)\s*/i, "");
  return insList.some(
    (code) => code.toLowerCase() === q || code.toLowerCase() === bare
  );
}

function evaluateNutrientRule(item, rule) {
  if (!isRuleActive(rule)) return true;
  const nMap = item.nutrients_100 || {};
  const n = nMap[rule.nutrient];
  if (!n || n.partial) return false;

  if (rule.op === "le") {
    const x = Number(rule.val);
    return n.max <= x;
  }
  if (rule.op === "ge") {
    const x = Number(rule.val);
    if (n.has_upper_bound) return false;
    return n.min >= x;
  }
  // range [A, B]
  const hasMin = rule.minVal !== "" && rule.minVal !== undefined && !Number.isNaN(Number(rule.minVal));
  const hasMax = rule.maxVal !== "" && rule.maxVal !== undefined && !Number.isNaN(Number(rule.maxVal));
  const a = hasMin ? Number(rule.minVal) : 0;
  const b = hasMax ? Number(rule.maxVal) : Number.POSITIVE_INFINITY;
  if (hasMin && hasMax && a > b) return false;
  const loOk = !hasMin || a === 0 ? true : !n.has_upper_bound && n.min >= a;
  const hiOk = !hasMax || n.max <= b;
  return loOk && hiOk;
}

function getFilteredAndSortedCatalog() {
  const q = filter.text.trim().toLowerCase();

  const filtered = CATALOG.filter((i) => {
    if (filter.markets.length && !(i.markets || []).some((m) => filter.markets.includes(m))) {
      return false;
    }
    if (filter.resolutions.length && !filter.resolutions.includes(i.resolution)) return false;
    if (filter.levels.length && !filter.levels.includes(i.evidence_level)) return false;
    if (filter.profiles.length && !(i.profiles || []).some((p) => filter.profiles.includes(p))) {
      return false;
    }
    if (filter.namespaces.length && !filter.namespaces.includes(i.namespace)) return false;
    if (filter.brands.length && !filter.brands.includes(i.brand_slug || i.brand)) return false;

    if (filter.excludeAllergens.length) {
      const hitContain = i.allergens_contains || [];
      const hitMay = i.allergens_may_contain || [];
      if (filter.excludeAllergens.some((alg) => hitContain.includes(alg) || hitMay.includes(alg))) {
        return false;
      }
    }

    if (filter.includeIngredients.length) {
      if (!filter.includeIngredients.every((term) => itemMatchesIngTerm(i, term))) return false;
    }
    if (filter.excludeIngredients.length) {
      if (filter.excludeIngredients.some((term) => itemMatchesIngTerm(i, term))) return false;
    }

    if (filter.zeroAdditives && (i.additives_count ?? 0) !== 0) return false;
    if (filter.zeroCalorie) {
      const ek = i.nutrients_100 && i.nutrients_100.energy_kcal;
      if (!ek || ek.partial || ek.max > 5) return false;
    }

    if (filter.nutrientRules.length) {
      if (!filter.nutrientRules.every((rule) => evaluateNutrientRule(i, rule))) return false;
    }

    if (!q) return true;
    const allNames = i.names ? Object.values(i.names) : [i.name];
    const allBrandNames = Array.isArray(i.brand_names)
      ? i.brand_names
      : i.brand_names
        ? Object.values(i.brand_names)
        : [];
    return [
      i.id,
      ...allNames,
      i.brand,
      ...allBrandNames,
      i.brand_slug || "",
      ...(i.aliases || []),
      ...(i.ingredients_tokens || []),
      ...(i.additives_ins || []),
    ]
      .join(" ")
      .toLowerCase()
      .includes(q);
  });

  const sorted = [...filtered];
  if (filter.sort === "kcal_asc") {
    sorted.sort((a, b) => {
      const ka = typeof a.energy_kcal_num === "number" ? a.energy_kcal_num : Number.POSITIVE_INFINITY;
      const kb = typeof b.energy_kcal_num === "number" ? b.energy_kcal_num : Number.POSITIVE_INFINITY;
      return ka - kb || a.id.localeCompare(b.id);
    });
  } else if (filter.sort === "kcal_desc") {
    sorted.sort((a, b) => {
      const ka = typeof a.energy_kcal_num === "number" ? a.energy_kcal_num : Number.NEGATIVE_INFINITY;
      const kb = typeof b.energy_kcal_num === "number" ? b.energy_kcal_num : Number.NEGATIVE_INFINITY;
      return kb - ka || a.id.localeCompare(b.id);
    });
  } else if (filter.sort === "protein_desc") {
    sorted.sort((a, b) => {
      const pa = a.nutrients_100 && a.nutrients_100.protein && !a.nutrients_100.protein.partial ? a.nutrients_100.protein.min : -1;
      const pb = b.nutrients_100 && b.nutrients_100.protein && !b.nutrients_100.protein.partial ? b.nutrients_100.protein.min : -1;
      return pb - pa || a.id.localeCompare(b.id);
    });
  } else if (filter.sort === "sodium_asc") {
    sorted.sort((a, b) => {
      const sa = a.nutrients_100 && a.nutrients_100.sodium && !a.nutrients_100.sodium.partial ? a.nutrients_100.sodium.max : Number.POSITIVE_INFINITY;
      const sb = b.nutrients_100 && b.nutrients_100.sodium && !b.nutrients_100.sodium.partial ? b.nutrients_100.sodium.max : Number.POSITIVE_INFINITY;
      return sa - sb || a.id.localeCompare(b.id);
    });
  } else if (filter.sort === "brand_asc") {
    sorted.sort((a, b) => {
      const cmp = String(a.brand || "").localeCompare(String(b.brand || ""));
      return cmp !== 0 ? cmp : a.id.localeCompare(b.id);
    });
  } else {
    sorted.sort((a, b) => a.id.localeCompare(b.id));
  }
  return sorted;
}

function submitIngredientTagInput(kind) {
  const inputEl = kind === "inc" ? $("#inc-ing-input") : $("#exc-ing-input");
  if (!inputEl) return;
  const val = inputEl.value.trim();
  if (!val) return;
  const list = kind === "inc" ? filter.includeIngredients : filter.excludeIngredients;
  if (!list.some((x) => x.toLowerCase() === val.toLowerCase())) {
    if (kind === "inc") filter.includeIngredients.push(val);
    else filter.excludeIngredients.push(val);
  }
  renderWorkbenchControls();
  renderList(true);
}

function initControls() {
  $("#theme-toggle").onclick = () => {
    const root = document.documentElement;
    const cur = root.getAttribute("data-theme");
    const isDark =
      cur === "dark" ||
      (!cur && window.matchMedia("(prefers-color-scheme: dark)").matches);
    root.setAttribute("data-theme", isDark ? "light" : "dark");
  };

  const langSelectEl = $("#lang-select");
  if (langSelectEl) {
    langSelectEl.addEventListener("change", async (e) => {
      const chosen = matchSupportedLocale(e.target.value, LOCALE_MANIFEST) || "en";
      LANG = chosen;
      localStorage.setItem("opf_lang", LANG);
      try {
        const u = new URL(location.href);
        u.searchParams.set("lang", LANG);
        history.replaceState(null, "", `${u.pathname}${u.search}${u.hash}`);
      } catch (_) {
        // Ignore history restriction on file:// or sandboxed origins
      }
      await ensureLocaleLoaded(LANG);
      applyStaticChrome();
      updateScannerChromeText();
      if (META) renderStats(META);
      renderWorkbenchControls();
      renderList(false);
      if (currentItem && currentCompact && currentFull) {
        renderCatalogCard(currentItem, currentCompact, currentFull);
      }
    });
  }

  $("#legend-toggle").onclick = () => {
    const sheet = $("#legend-sheet");
    sheet.hidden = !sheet.hidden;
    $("#legend-toggle").setAttribute("aria-pressed", String(!sheet.hidden));
  };

  $("#q").addEventListener("input", (e) => {
    filter.text = e.target.value;
    updateWorkbenchChromeAndStrip();
    renderList(true);
  });

  $("#q-clear").addEventListener("click", () => {
    filter.text = "";
    $("#q").value = "";
    $("#q").focus();
    updateWorkbenchChromeAndStrip();
    renderList(true);
  });

  $("#sort-select").addEventListener("change", (e) => {
    filter.sort = e.target.value;
    renderList(true);
  });

  $("#wb-toggle").addEventListener("click", () => {
    workbenchOpen = !workbenchOpen;
    updateWorkbenchChromeAndStrip();
  });

  $("#reset-filters-btn").addEventListener("click", resetAllFilters);

  $("#market-filters").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-market]");
    if (!b) return;
    const val = b.dataset.market;
    filter.markets = val === "" ? [] : toggleArrayVal(filter.markets, val);
    renderWorkbenchControls();
    renderList(true);
  });

  $("#filter-panel").addEventListener("click", (e) => {
    const resBtn = e.target.closest("button[data-resolution]");
    if (resBtn) {
      const v = resBtn.dataset.resolution;
      filter.resolutions = v === "" ? [] : toggleArrayVal(filter.resolutions, v);
      renderWorkbenchControls();
      renderList(true);
      return;
    }
    const lvBtn = e.target.closest("button[data-level]");
    if (lvBtn) {
      const v = lvBtn.dataset.level;
      filter.levels = v === "" ? [] : toggleArrayVal(filter.levels, v);
      renderWorkbenchControls();
      renderList(true);
      return;
    }
    const profBtn = e.target.closest("button[data-profile]");
    if (profBtn) {
      filter.profiles = toggleArrayVal(filter.profiles, profBtn.dataset.profile);
      renderWorkbenchControls();
      renderList(true);
      return;
    }
    const nsBtn = e.target.closest("button[data-namespace]");
    if (nsBtn) {
      filter.namespaces = toggleArrayVal(filter.namespaces, nsBtn.dataset.namespace);
      renderWorkbenchControls();
      renderList(true);
      return;
    }
    const brandBtn = e.target.closest("button[data-brand]");
    if (brandBtn) {
      filter.brands = toggleArrayVal(filter.brands, brandBtn.dataset.brand);
      renderWorkbenchControls();
      renderList(true);
      return;
    }
    const algBtn = e.target.closest("button[data-exclude-allergen]");
    if (algBtn) {
      filter.excludeAllergens = toggleArrayVal(
        filter.excludeAllergens,
        algBtn.dataset.excludeAllergen
      );
      renderWorkbenchControls();
      renderList(true);
      return;
    }
    const traitBtn = e.target.closest("button[data-trait]");
    if (traitBtn) {
      if (traitBtn.dataset.trait === "zero-additives") filter.zeroAdditives = !filter.zeroAdditives;
      if (traitBtn.dataset.trait === "zero-calorie") filter.zeroCalorie = !filter.zeroCalorie;
      renderWorkbenchControls();
      renderList(true);
      return;
    }
    if (e.target.closest("#inc-ing-add")) {
      submitIngredientTagInput("inc");
      return;
    }
    if (e.target.closest("#exc-ing-add")) {
      submitIngredientTagInput("exc");
      return;
    }
    const rmInc = e.target.closest("[data-rm-inc-ing]");
    if (rmInc) {
      filter.includeIngredients = filter.includeIngredients.filter(
        (x) => x !== rmInc.dataset.rmIncIng
      );
      renderWorkbenchControls();
      renderList(true);
      return;
    }
    const rmExc = e.target.closest("[data-rm-exc-ing]");
    if (rmExc) {
      filter.excludeIngredients = filter.excludeIngredients.filter(
        (x) => x !== rmExc.dataset.rmExcIng
      );
      renderWorkbenchControls();
      renderList(true);
      return;
    }
    const presetBtn = e.target.closest("button[data-preset]");
    if (presetBtn) {
      const p = presetBtn.dataset.preset;
      if (p === "high_protein") addNutrientRule("protein", "ge", "10");
      else if (p === "low_sodium") addNutrientRule("sodium", "le", "120");
      else if (p === "low_sugar") addNutrientRule("sugars_total", "le", "5");
      else if (p === "low_fat") addNutrientRule("fat_total", "le", "3");
      return;
    }
    if (e.target.closest("#add-nutrient-rule-btn")) {
      addNutrientRule("protein", "ge", "");
      return;
    }
    const rmRule = e.target.closest(".remove-rule-btn");
    if (rmRule) {
      const row = rmRule.closest(".n-rule-row");
      if (row) {
        filter.nutrientRules = filter.nutrientRules.filter((r) => r.id !== row.dataset.ruleId);
        renderWorkbenchControls();
        renderList(true);
      }
    }
  });

  $("#filter-panel").addEventListener("change", (e) => {
    const row = e.target.closest(".n-rule-row");
    if (!row) return;
    const rule = filter.nutrientRules.find((r) => r.id === row.dataset.ruleId);
    if (!rule) return;
    if (e.target.classList.contains("rule-nutrient")) {
      rule.nutrient = e.target.value;
      renderWorkbenchControls();
      renderList(true);
    } else if (e.target.classList.contains("rule-op")) {
      rule.op = e.target.value;
      renderWorkbenchControls();
      renderList(true);
    }
  });

  $("#filter-panel").addEventListener("input", (e) => {
    const row = e.target.closest(".n-rule-row");
    if (!row) return;
    const rule = filter.nutrientRules.find((r) => r.id === row.dataset.ruleId);
    if (!rule) return;
    if (e.target.classList.contains("rule-val")) rule.val = e.target.value;
    else if (e.target.classList.contains("rule-min")) rule.minVal = e.target.value;
    else if (e.target.classList.contains("rule-max")) rule.maxVal = e.target.value;
    // Live filter without re-rendering rule DOM so input focus & cursor stay untouched
    updateWorkbenchChromeAndStrip();
    renderList(true);
  });

  $("#filter-panel").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.id === "inc-ing-input") {
      e.preventDefault();
      submitIngredientTagInput("inc");
    } else if (e.key === "Enter" && e.target.id === "exc-ing-input") {
      e.preventDefault();
      submitIngredientTagInput("exc");
    }
  });

  $("#active-filter-tags").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-remove-kind]");
    if (!btn) return;
    const kind = btn.dataset.removeKind;
    const val = btn.dataset.removeVal;
    if (kind === "text") {
      filter.text = "";
      if ($("#q")) $("#q").value = "";
    } else if (kind === "market") filter.markets = filter.markets.filter((x) => x !== val);
    else if (kind === "resolution") filter.resolutions = filter.resolutions.filter((x) => x !== val);
    else if (kind === "level") filter.levels = filter.levels.filter((x) => x !== val);
    else if (kind === "profile") filter.profiles = filter.profiles.filter((x) => x !== val);
    else if (kind === "namespace") filter.namespaces = filter.namespaces.filter((x) => x !== val);
    else if (kind === "brand") filter.brands = filter.brands.filter((x) => x !== val);
    else if (kind === "exclAllergen") filter.excludeAllergens = filter.excludeAllergens.filter((x) => x !== val);
    else if (kind === "inclIng") filter.includeIngredients = filter.includeIngredients.filter((x) => x !== val);
    else if (kind === "exclIng") filter.excludeIngredients = filter.excludeIngredients.filter((x) => x !== val);
    else if (kind === "zeroAdd") filter.zeroAdditives = false;
    else if (kind === "zeroCal") filter.zeroCalorie = false;
    else if (kind === "rule") filter.nutrientRules = filter.nutrientRules.filter((r) => r.id !== val);

    renderWorkbenchControls();
    renderList(true);
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest(".reset-all-filters-trigger")) {
      resetAllFilters();
    }
  });

  window.addEventListener("hashchange", () => {
    const parsed = parseLocationHash();
    if (!parsed.productId) return;
    const hit = CATALOG.find((i) => i.id === parsed.productId);
    if (hit) {
      selectCard(hit, true, parsed.editionId);
    }
  });

  window.addEventListener("keydown", (e) => {
    const scanModal = $("#scan-modal");
    if (e.key === "Escape" && scanModal && !scanModal.hidden) {
      e.preventDefault();
      closeScannerModal();
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
      const cards = [...document.querySelectorAll(".index-entry")];
      if (!cards.length) return;
      e.preventDefault();
      const idx = cards.findIndex((c) => c.dataset.id === currentId);
      const nextIdx =
        e.key === "ArrowDown"
          ? Math.min(cards.length - 1, idx + 1)
          : Math.max(0, idx - 1);
      const item = CATALOG.find((i) => i.id === cards[nextIdx].dataset.id);
      if (item) selectCard(item, true);
    }
  });

  $("#list").addEventListener("click", (e) => {
    const b = e.target.closest(".index-entry");
    if (!b) return;
    const item = CATALOG.find((i) => i.id === b.dataset.id);
    if (item) selectCard(item, true, null);
  });

  initScannerControls();
}

async function init() {
  await initI18n();
  applyStaticChrome();
  initControls();
  try {
    META = await getJSON("v1/meta.json");
    const schemaFooter = $("#footer-schema");
    if (schemaFooter && META.opf_schema) {
      schemaFooter.textContent = `OpenPackagedFood Schema v${META.opf_schema}`;
    }
    const text = await (await fetch("v1/index/catalog.jsonl")).text();
    CATALOG = text.split("\n").filter(Boolean).map((l) => JSON.parse(l));
    renderStats(META);
    renderWorkbenchControls();
    const parsedHash = parseLocationHash();
    if (parsedHash.productId && CATALOG.some((i) => i.id === parsedHash.productId)) {
      currentId = parsedHash.productId;
      selectedEditionId = parsedHash.editionId;
      $("#workspace").dataset.mobileView = "detail";
    }
    if (CATALOG.length === 0 || urlParams.get("legend") === "1") {
      $("#legend-sheet").hidden = false;
      $("#legend-toggle").setAttribute("aria-pressed", "true");
    }
    renderList(true, parsedHash.editionId);
  } catch (e) {
    $("#detail").innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
  }
}

function renderStats(meta) {
  const lv = meta.counts_by_evidence_level || {};
  const verifiedCount = (lv.verified || 0) + (lv.corroborated || 0);
  const marketEntries = Object.entries(meta.counts_by_market || {}).sort(
    (a, b) => b[1] - a[1] || a[0].localeCompare(b[0])
  );
  const marketPillsHtml = marketEntries.length
    ? `<div class="stat-badges">${marketEntries
        .map(
          ([mkt, cnt]) =>
            `<span class="stat-pill">${esc(mkt)} <em>${esc(cnt)}</em></span>`
        )
        .join("")}</div>`
    : `<span class="val">—</span>`;

  $("#stats").innerHTML = `
    <div class="stat-cell">
      <span class="label">${esc(t("stats.total"))}</span>
      <span class="val">${esc(meta.total_products)}</span>
    </div>
    <div class="stat-cell">
      <span class="label">${esc(t("stats.verified"))}</span>
      <span class="val">${esc(verifiedCount)}</span>
    </div>
    <div class="stat-cell">
      <span class="label">${esc(t("stats.markets"))}</span>
      ${marketPillsHtml}
    </div>
    <div class="stat-cell">
      <span class="label">${esc(t("stats.schema"))}</span>
      <span class="val">v${esc(meta.opf_schema)}</span>
    </div>`;
}

function renderEmptyCatalogCard() {
  $("#workspace").dataset.mobileView = "detail";
  const guideUrl = "https://github.com/mickey996icu/open-packaged-food/blob/main/CONTRIBUTING.md";
  $("#detail").innerHTML = `
    <div class="empty-catalog-guide">
      <div class="card-topbar">
        <div class="call-number-block">
          <span class="cn-label">${esc(t("detail.productIdLabel"))}</span>
          <strong>opf:database/status/v0.2</strong>
        </div>
        ${renderSeal("verified")}
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

function renderList(autoSelect = true, initialEditionId = null) {
  const countEl = $("#results-count");
  if (CATALOG.length === 0) {
    if (countEl) countEl.textContent = t("search.resultsSummary", { shown: 0, total: 0 });
    $("#list").innerHTML = `<div class="empty-state">${esc(t("search.emptyCatalogDrawer"))}</div>`;
    renderEmptyCatalogCard();
    return;
  }

  const hit = getFilteredAndSortedCatalog();
  if (countEl) {
    countEl.textContent = t("search.resultsSummary", {
      shown: hit.length,
      total: CATALOG.length,
    });
  }

  $("#list").innerHTML = hit.length
    ? hit
        .map((i) => {
          const dispName = pickLocalizedProductName(i);
          const hasMixedEv =
            i.lowest_active_evidence_level &&
            i.lowest_active_evidence_level !== i.evidence_level;
          const mixedTip = hasMixedEv
            ? t("search.mixedEvidenceTitle", {
                high: t(`seals.${i.evidence_level}.label`),
                low: t(`seals.${i.lowest_active_evidence_level}.label`),
              })
            : "";
          const kcalDisplay =
            i.energy_kcal_100 !== null && i.energy_kcal_100 !== undefined
              ? `${i.energy_kcal_100} kcal/${i.basis}`
              : "—";
          const mkts = (i.markets || []).join("/");
          return `
    <button type="button" class="index-entry" data-id="${esc(i.id)}" aria-current="${i.id === currentId}">
      <div class="entry-top">
        <span class="entry-brand">${esc(i.brand)}${mkts ? ` · ${esc(mkts)}` : ""}</span>
        <span style="display:flex;gap:4px;align-items:center;flex-wrap:wrap;justify-content:flex-end;">
          ${renderSeal(i.evidence_level)}
          ${hasMixedEv ? `<span class="chip mono micro" title="${esc(mixedTip)}">${esc(t("search.mixedEvidenceShort"))}</span>` : ""}
        </span>
      </div>
      <div class="entry-title">${esc(dispName)}</div>
      <div class="entry-id">${esc(i.id)}</div>
      <div class="imprint">
        ${renderResolutionBadge(i.resolution, true)}
        <span>${esc(i.net_content || "—")}</span>
        <span>${esc(kcalDisplay)}</span>
        ${(i.additives_count ?? 0) === 0 ? `<span class="chip mono micro">${esc(t("search.zeroAdditivesShort"))}</span>` : ""}
      </div>
    </button>`;
        })
        .join("")
    : renderEmptyFilterResultHtml();

  if (autoSelect) {
    if (hit.length) {
      const target = hit.find((i) => i.id === currentId) || hit[0];
      const edToPass = target.id === currentId ? initialEditionId : null;
      selectCard(target, false, edToPass);
    } else {
      $("#detail").innerHTML = renderEmptyFilterResultHtml();
    }
  }
}

async function selectCard(item, switchMobileToDetail = false, requestedEditionId = null) {
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

  document
    .querySelectorAll(".index-entry")
    .forEach((c) => c.setAttribute("aria-current", c.dataset.id === item.id));

  try {
    const [compact, full] = await Promise.all([
      getJSON(item.compact_url),
      getJSON(item.full_url),
    ]);
    if (currentId !== item.id) return;
    currentItem = item;
    currentCompact = compact;
    currentFull = full;

    if (
      selectedEditionId &&
      full.edition_redirects &&
      full.edition_redirects[selectedEditionId]
    ) {
      redirectedFromId = selectedEditionId;
      selectedEditionId = full.edition_redirects[selectedEditionId];
      history.replaceState(
        null,
        "",
        `#${encodeURIComponent(item.id)}@${encodeURIComponent(selectedEditionId)}`
      );
    }

    renderCatalogCard(item, compact, full);
  } catch (e) {
    $("#detail").innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
  }
}

function buildFormulaForCell(key, entry, ed, isPerUnit) {
  if (!entry || entry.basis === "reported") return "";
  const core = ed.core;
  const norm = ed.normalized;
  const panelBasis = core.nutrition_declared.basis;
  const rows = core.nutrition_declared.rows || [];
  const profileId = core.regulatory_profile || "";

  if (isPerUnit && norm.per_unit) {
    const ua = norm.per_unit.unit_amount;
    const baseEntry = norm.nutrients[key];
    if (baseEntry) {
      const q = entry.qualifier && entry.qualifier !== "=" ? entry.qualifier + " " : "";
      return `ƒ ${key} (per ${ua.value}${ua.unit}) = ${baseEntry.qualifier || ""}${baseEntry.value} ${baseEntry.unit}/${norm.basis} × (${ua.value}${ua.unit} ÷ 100) = ${q}${entry.value} ${entry.unit}`;
    }
  }

  if (entry.basis === "regulatory_upper_bound") {
    const qf = (ed.quality_flags || []).find(
      (f) => f.code === "REGULATORY_ZERO_ROUNDING_ARTIFACT" && f.field === key
    );
    if (qf) return `< ${key}: ${qf.detail}`;
  }

  if (key === "energy_kcal") {
    const kjRow = rows.find((r) => r.nutrient === "energy" && r.unit === "kJ");
    const kjNorm = norm.nutrients.energy_kj;
    if (kjRow && kjNorm) {
      return `ƒ energy_kcal = ${kjNorm.qualifier || ""}${kjNorm.value} kJ ÷ 4.184 = ${entry.qualifier || ""}${entry.value} kcal/${norm.basis}`;
    }
  }
  if (key === "energy_kj") {
    const kcalRow = rows.find((r) => r.nutrient === "energy" && r.unit === "kcal");
    const kcalNorm = norm.nutrients.energy_kcal;
    if (kcalRow && kcalNorm) {
      return `ƒ energy_kj = ${kcalNorm.qualifier || ""}${kcalNorm.value} kcal × 4.184 = ${entry.qualifier || ""}${entry.value} kJ/${norm.basis}`;
    }
  }
  if (key === "salt_equivalent" && norm.nutrients.sodium) {
    const na = norm.nutrients.sodium;
    const ratio = profileId.startsWith("JP/") ? "2.54" : "2.5";
    return `ƒ salt_equivalent = (${na.qualifier || ""}${na.value} mg sodium ÷ 1000) × ${ratio} = ${entry.qualifier || ""}${entry.value} g/${norm.basis}`;
  }
  if (key === "sodium" && norm.nutrients.salt_equivalent) {
    const s = norm.nutrients.salt_equivalent;
    const ratio = profileId.startsWith("JP/") ? "2.54" : "2.5";
    return `ƒ sodium = (${s.qualifier || ""}${s.value} g salt ÷ ${ratio}) × 1000 = ${entry.qualifier || ""}${entry.value} mg/${norm.basis}`;
  }
  if (key === "carbs_available" && norm.nutrients.carbs_total && norm.nutrients.dietary_fiber) {
    return `ƒ carbs_available = ${norm.nutrients.carbs_total.value} g (total carbs) − ${norm.nutrients.dietary_fiber.value} g (fiber) = ${entry.value} g/${norm.basis}`;
  }

  const declRow = rows.find(
    (r) => r.nutrient === key || (key.startsWith("energy_") && r.nutrient === "energy")
  );
  if (declRow) {
    return `ƒ ${key} = ${declRow.value} ${declRow.unit} × (100 ÷ ${panelBasis.value}${panelBasis.unit}) = ${entry.qualifier || ""}${entry.value} ${entry.unit}/${norm.basis}`;
  }
  return `ƒ ${key}: ${entry.qualifier || ""}${entry.value} ${entry.unit}`;
}

function renderValueInner(key, entry, ed, isPerUnit = false) {
  if (!entry) return "—";
  const q = entry.qualifier && entry.qualifier !== "=" ? entry.qualifier + " " : "";
  const rawNum = `${q}${entry.value}`;
  const formula = buildFormulaForCell(key, entry, ed, isPerUnit);

  if (entry.basis === "regulatory_upper_bound") {
    return `<button type="button" class="trace-btn val-bound" data-formula="${esc(formula)}" title="${esc(formula)}"><span class="num">${esc(rawNum)}</span><span class="unit">${esc(entry.unit)}</span></button>`;
  }
  if (entry.basis === "derived") {
    return `<button type="button" class="trace-btn val-derived" data-formula="${esc(formula)}" title="${esc(formula)}"><span class="num">${esc(rawNum)}</span><span class="unit">${esc(entry.unit)}</span><sup class="fn-mark">ƒ</sup></button>`;
  }
  return `<span class="val-reported"><span class="num">${esc(rawNum)}</span><span class="unit">${esc(entry.unit)}</span></span>`;
}

function renderValueState(key, entry, ed, isPerUnit = false) {
  if (!entry) return `<td class="n-val">—</td>`;
  return `<td class="n-val">${renderValueInner(key, entry, ed, isPerUnit)}</td>`;
}

function translateNutrient(key) {
  const label = t(`nutrients.${key}`);
  return label !== `nutrients.${key}` ? label : key;
}

function renderNutritionKpiStrip(ed) {
  const nutrients = (ed.normalized && ed.normalized.nutrients) || {};
  const carbsKey = nutrients.carbs_available ? "carbs_available" : "carbs_total";
  const kpiSpecs = [
    ["energy_kcal", t("detail.kpiEnergy")],
    ["protein", t("detail.kpiProtein")],
    ["fat_total", t("detail.kpiFat")],
    [carbsKey, nutrients.carbs_available ? t("detail.kpiCarbsAvail") : t("detail.kpiCarbsTotal")],
    ["sodium", t("detail.kpiSodium")],
  ];
  return `<div class="kpi-strip">${kpiSpecs
    .map(([key, label]) => {
      const entry = nutrients[key];
      const inner = entry ? renderValueInner(key, entry, ed, false) : "—";
      return `<div class="kpi-tile">
        <span class="kpi-label">${esc(label)}</span>
        <div class="kpi-value">${inner}</div>
      </div>`;
    })
    .join("")}</div>`;
}

function renderNutritionSection(ed) {
  const norm = ed.normalized;
  const nutrients = norm.nutrients || {};
  const pu = norm.per_unit;
  const orderedKeys = [
    ...NUTRIENT_ORDER.filter((k) => nutrients[k]),
    ...Object.keys(nutrients).filter((k) => !NUTRIENT_ORDER.includes(k)).sort(),
  ];
  const rows = orderedKeys
    .map((k) => {
      const label = translateNutrient(k);
      const n = nutrients[k];
      return `<tr>
        <td class="n-name"><b>${esc(label)}</b><small>${esc(k)}</small></td>
        ${renderValueState(k, n, ed, false)}
        ${pu ? renderValueState(k, pu.nutrients[k], ed, true) : ""}
      </tr>`;
    })
    .join("");
  const puUnitText = pu
    ? pu.unit_amount.label || pu.unit_amount.value + pu.unit_amount.unit
    : "";

  return `
    ${renderNutritionKpiStrip(ed)}
    <div class="table-wrap">
      <table class="nutrient-table">
        <thead>
          <tr>
            <th>${esc(t("detail.colNutrient"))}</th>
            <th>${esc(t("detail.colPerBasis", { basis: norm.basis }))}</th>
            ${pu ? `<th>${esc(t("detail.colPerUnit", { unit: puUnitText }))}</th>` : ""}
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
    <div class="formula-inspector" id="formula-inspector">${esc(t("detail.formulaPrompt"))}</div>
    <div class="state-legend">
      <span>${esc(t("detail.legendReported"))}</span>
      <span>${esc(t("detail.legendDerived"))}</span>
      <span>${esc(t("detail.legendBound"))}</span>
    </div>`;
}

function renderIngredientTree(nodes) {
  return `<ul class="ing-tree">${(nodes || [])
    .map(
      (n) => `<li>
        ${n.functional_class ? `<span class="chip mono">${esc(n.functional_class)}</span> ` : ""}
        <b>${esc(n.name)}</b>
        ${n.qualifier ? `<span class="chip mono">${esc(n.qualifier)}</span>` : ""}
        ${n.ins ? `<span class="chip mono">INS ${esc(n.ins)}</span>` : ""}
        ${Array.isArray(n.span) && n.span.length === 2 ? `<span class="ing-span">[${esc(n.span[0])}..${esc(n.span[1])}]</span>` : ""}
        ${n.children ? renderIngredientTree(n.children) : ""}
      </li>`
    )
    .join("")}</ul>`;
}

function formatAllergenCode(code) {
  const translated = t(`allergens.${code}`);
  return translated !== `allergens.${code}` ? `${translated} (${code})` : code;
}

function renderAllergensBadges(norm) {
  const alg = norm.allergens || {};
  const decl = alg.declared_contains || [];
  const inferred = (alg.inferred_from_ingredients || []).filter((x) => !decl.includes(x));
  const may = alg.may_contain || [];
  const fallback = !alg.declared_contains && !alg.inferred_from_ingredients ? alg.contains || [] : [];

  return [
    ...decl.map((a) => `<span class="chip mono">${esc(t("detail.allergenDeclared"))}: ${esc(formatAllergenCode(a))}</span>`),
    ...inferred.map((a) => `<span class="chip mono">${esc(t("detail.allergenInferred"))}: ${esc(formatAllergenCode(a))}</span>`),
    ...fallback.map((a) => `<span class="chip mono">${esc(t("detail.allergenDeclared"))}: ${esc(formatAllergenCode(a))}</span>`),
    ...may.map((a) => `<span class="chip mono">${esc(t("detail.allergenMayContain"))}: ${esc(formatAllergenCode(a))}</span>`),
  ].join("");
}

function formatPartyRole(role) {
  const translated = t(`roles.${role}`);
  return translated !== `roles.${role}` ? translated : role;
}

function formatOrigin(origin) {
  if (!origin) return "";
  const parts = [];
  if (origin.country) parts.push(origin.country);
  if (origin.region) parts.push(origin.region);
  if (origin.raw_text && origin.raw_text !== origin.region) parts.push(`(${origin.raw_text})`);
  return parts.join(" · ");
}

function renderEditionTimelineHtml(full, activeEditionId) {
  return (full.editions || [])
    .map((eItem) => {
      const refEd = full.editions.find((x) => x.edition_id === activeEditionId);
      const isSameCore = refEd && eItem.core_fingerprint === refEd.core_fingerprint;
      return `<button type="button" class="edition-step" data-select-edition="${esc(eItem.edition_id)}" aria-current="${eItem.edition_id === activeEditionId}">
        <span class="ulid-head mono">
          <span class="ulid-code">${esc(eItem.edition_id)}</span>
          ${renderRevPill(eItem.rev)}
          <span class="chip mono">${esc(eItem.track)}</span>
          <span class="chip mono">${esc(eItem.t_active)}</span>
        </span>
        <span style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
          ${renderStatusBadge(eItem.status)}
          ${isSameCore && full.editions.length > 1 ? `<span class="chip mono">${esc(t("detail.sameCoreBadge"))}</span>` : ""}
          ${renderSeal(eItem.evidence_level)}
        </span>
      </button>`;
    })
    .join("");
}

function renderSectionCard(labelText, bodyHtml, extraHeaderHtml = "") {
  return `<section class="section-card">
    <div class="section-card-head">
      <span class="section-label">${esc(labelText)}</span>
      ${extraHeaderHtml}
    </div>
    ${bodyHtml}
  </section>`;
}

function renderDivergentOverview(item, compact, full) {
  const disamb = compact.disambiguation || { mode: "mixed", tracks_guide: [] };
  const common = compact.common_summary || {};
  const guideByTrack = {};
  (disamb.tracks_guide || []).forEach((g) => {
    guideByTrack[g.track] = g;
  });

  const disambInstr = pickLocalizedText(disamb.instructions);
  const variantCards = (compact.variants || [])
    .map((v) => {
      const guide = guideByTrack[v.track];
      const discText =
        (guide && guide.discriminator && pickLocalizedText(guide.discriminator.instructions)) ||
        (guide && pickLocalizedText(guide.instructions)) ||
        "";
      const partiesLine = (v.parties_summary || [])
        .map((p) => `${formatPartyRole(p.role)}: ${p.name}${p.license ? " (" + p.license + ")" : ""}`)
        .join(" · ");
      const originStr = formatOrigin(v.origin);
      return `<div class="variant-card">
        <div>
          <div class="variant-card-head">
            <span class="ulid-head mono"><span class="ulid-code">${esc(v.edition_id)}</span> ${renderRevPill(v.rev)}</span>
            ${renderSeal(v.evidence_level)}
          </div>
          <div class="variant-card-meta" style="margin-top:8px;">
            <span class="chip mono">${esc(v.track)}</span>
            <span class="chip mono">${esc(formatNetContent(v.net_content))}</span>
            <span class="chip mono">${esc(v.t_active)}</span>
            ${v.packaging_code ? `<span class="chip mono">${esc(v.packaging_code)}</span>` : ""}
          </div>
          ${originStr ? `<p class="variant-card-desc" style="margin-top:8px;">${esc(t("detail.metaOrigin"))}: ${esc(originStr)}</p>` : ""}
          ${partiesLine ? `<p class="variant-card-desc" style="margin-top:4px;">${esc(partiesLine)}</p>` : ""}
          ${discText ? `<p class="variant-card-desc" style="margin-top:6px;">${esc(discText)}</p>` : ""}
        </div>
        <button type="button" class="chip variant-pick-btn" data-select-edition="${esc(v.edition_id)}">${esc(t("detail.selectVariantBtn"))}</button>
      </div>`;
    })
    .join("");

  const ranges = common.nutrient_ranges_not_for_logging || {};
  const rangeKeys = [
    ...NUTRIENT_ORDER.filter((k) => ranges[k]),
    ...Object.keys(ranges).filter((k) => !NUTRIENT_ORDER.includes(k)).sort(),
  ];
  const rangeRows = rangeKeys
    .map((k) => {
      const r = ranges[k];
      const lo = `${r.min_qualifier && r.min_qualifier !== "=" ? r.min_qualifier + " " : ""}${r.min}`;
      const hi = `${r.max_qualifier && r.max_qualifier !== "=" ? r.max_qualifier + " " : ""}${r.max}`;
      const valText = lo === hi ? lo : `${lo} – ${hi}`;
      const partialTag = r.partial
        ? ` <span class="chip mono">${esc(t("detail.partialDeclared", { declared: r.declared_in_variants, total: r.total_variants }))}</span>`
        : "";
      return `<tr>
        <td class="n-name"><b>${esc(translateNutrient(k))}</b><small>${esc(k)}</small>${partialTag}</td>
        <td class="n-val">${esc(valText)} <span class="unit">${esc(r.unit)}</span></td>
      </tr>`;
    })
    .join("");

  const algUnion = common.allergens_union || { contains: [], may_contain: [] };
  const containsChips = (algUnion.contains || []).length
    ? algUnion.contains.map((a) => `<span class="chip mono">${esc(formatAllergenCode(a))}</span>`).join(" ")
    : `<span class="mono" style="font-size:0.8rem;color:var(--md-on-surface-variant)">${esc(t("detail.noneDeclared"))}</span>`;
  const mayChips = (algUnion.may_contain || []).length
    ? algUnion.may_contain.map((a) => `<span class="chip mono">${esc(formatAllergenCode(a))}</span>`).join(" ")
    : `<span class="mono" style="font-size:0.8rem;color:var(--md-on-surface-variant)">${esc(t("detail.noneDeclared"))}</span>`;

  const diffChips = (common.differing_fields || [])
    .map((f) => {
      const lbl = t(`diffFields.${f}`);
      return `<span class="chip mono">${esc(lbl !== `diffFields.${f}` ? lbl : f)}</span>`;
    })
    .join(" ");

  const viewOverview = `<div class="detail-sections">
    ${renderSectionCard(
      t("detail.divergentOverviewTitle"),
      `<p class="lead" style="margin-bottom:10px;">${esc(t("detail.divergentOverviewLead"))}</p>
       <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">
         <span class="chip mono">${esc(t(`disambiguationModes.${disamb.mode}`))}</span>
       </div>
       ${disambInstr ? `<div class="archival-banner">${esc(disambInstr)}</div>` : ""}
       <div class="variant-grid">${variantCards}</div>`
    )}
    ${renderSectionCard(
      t("detail.commonSummaryTitle"),
      `${diffChips ? `<div style="margin-bottom:12px;"><span class="section-label">${esc(t("detail.differingFieldsLabel"))}</span><div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;">${diffChips}</div></div>` : ""}
       <div class="archival-banner emphasis">${esc(t("detail.rangeWarningBanner"))}</div>
       ${
         common.basis === "mixed"
           ? `<div class="archival-banner">${esc(t("detail.mixedBasisNotice"))}</div>`
           : `<div class="table-wrap"><table class="nutrient-table">
               <thead>
                 <tr>
                   <th>${esc(t("detail.colNutrient"))}</th>
                   <th>${esc(t("detail.colRangePerBasis", { basis: common.basis }))}</th>
                 </tr>
               </thead>
               <tbody>${rangeRows}</tbody>
             </table></div>`
       }
       <div class="allergen-union-grid">
         <div class="allergen-union-box">
           <span class="section-label">${esc(t("detail.allergenUnionContains"))}</span>
           <div style="display:flex;gap:6px;flex-wrap:wrap;">${containsChips}</div>
         </div>
         <div class="allergen-union-box">
           <span class="section-label">${esc(t("detail.allergenUnionMayContain"))}</span>
           <div style="display:flex;gap:6px;flex-wrap:wrap;">${mayChips}</div>
         </div>
       </div>
       ${
         (common.additives_ins_union || []).length
           ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:12px;">
               ${common.additives_ins_union.map((c) => `<span class="chip mono">${esc(t("detail.additivePrefix"))} ${esc(c)}</span>`).join("")}
             </div>`
           : ""
       }`
    )}
    ${renderSectionCard(
      t("detail.railProvenance"),
      `<div class="edition-timeline">${renderEditionTimelineHtml(full, "")}</div>`
    )}
  </div>`;

  const viewApi = `<div class="detail-sections">
    ${renderSectionCard(
      t("detail.tabApi"),
      `<div class="endpoint-bar"><span class="method">GET</span><a href="${esc(rel(item.compact_url))}" target="_blank" rel="noopener">${esc(item.compact_url)}</a><span>${esc(t("detail.apiCompactDesc"))}</span></div>
       <div class="endpoint-bar"><span class="method">GET</span><a href="${esc(rel(item.full_url))}" target="_blank" rel="noopener">${esc(item.full_url)}</a><span>${esc(t("detail.apiFullDesc"))}</span></div>
       <pre class="json-view">${esc(JSON.stringify(compact, null, 2))}</pre>`,
      `<button type="button" class="icon-copy-btn copy-json-btn">${esc(t("detail.copyJsonBtn"))}</button>`
    )}
  </div>`;

  const views = [viewOverview, viewApi];
  const dispName = pickLocalizedProductName(item);
  const activeCount = (compact.active_edition_ids || []).length;

  $("#detail").innerHTML = `
    <div class="mobile-back-bar">
      <button type="button" class="chip" id="mobile-back-btn">${esc(t("detail.backToCatalog"))}</button>
    </div>
    ${redirectedFromId ? `<div class="archival-banner emphasis">${esc(t("detail.redirectNotice", { from: redirectedFromId, to: compact.active_edition_ids[0] || item.id }))}</div>` : ""}
    <div class="card-topbar">
      <div class="call-number-block">
        <span class="cn-label">${esc(t("detail.productIdLabel"))}</span>
        <strong>${esc(item.id)}</strong>
        <button type="button" class="icon-copy-btn copy-id-btn" data-copy-text="${esc(item.id)}">${esc(t("detail.copyIdBtn"))}</button>
        ${renderResolutionBadge(compact.resolution)}
      </div>
      ${renderSeal(compact.evidence_summary && compact.evidence_summary.highest_active)}
    </div>
    <hr class="title-rule" />
    <div class="card-title-block">
      <h2>${esc(title(compact.brand, dispName))}</h2>
      <div class="card-imprint">
        <span>${esc(t("detail.netContentLabel"))} ${esc(formatNetContent(common.net_content_values))}</span>
        <span>${esc(t("search.activeEditionsCount", { count: activeCount }))}</span>
        <span>${esc(t(`disambiguationModes.${disamb.mode}`))}</span>
      </div>
    </div>
    <div class="card-tabs" role="tablist">
      <button type="button" class="card-tab" role="tab" id="tab-0" aria-controls="card-body" aria-selected="true" data-tab="0">${esc(t("detail.tabOverview"))}</button>
      <button type="button" class="card-tab" role="tab" id="tab-1" aria-controls="card-body" aria-selected="false" data-tab="1">${esc(t("detail.tabApi"))}</button>
    </div>
    <div id="card-body" role="tabpanel" aria-labelledby="tab-0">${views[0]}</div>`;

  bindDetailEvents(item, compact, full, views);
}

function resolveDefaultEdition(compact, full) {
  if (selectedEditionId) {
    const hit = full.editions.find((e) => e.edition_id === selectedEditionId);
    if (hit) return hit;
  }
  const activeIds = compact.active_edition_ids || [];
  if (activeIds.length) {
    const targetId = activeIds[activeIds.length - 1];
    const hit = full.editions.find((e) => e.edition_id === targetId);
    if (hit) return hit;
  }
  const nonRetracted = full.editions.filter((e) => e.status !== "retracted");
  return (nonRetracted.length ? nonRetracted : full.editions).at(-1);
}

function renderCatalogCard(item, compact, full) {
  if (compact.resolution === "divergent" && !selectedEditionId) {
    renderDivergentOverview(item, compact, full);
    return;
  }

  const ed = resolveDefaultEdition(compact, full);
  const core = ed.core;
  const attrs = ed.attributes;
  const norm = ed.normalized;
  const dispName = pickLocalizedProductName(item, attrs);
  const isUnifiedUniform = compact.resolution === "uniform" && !selectedEditionId;

  const declaredRows = (core.nutrition_declared.rows || [])
    .map(
      (r) => `<tr>
        <td class="n-name"><b>${esc(translateNutrient(r.nutrient))}</b><small>${esc(r.nutrient)}</small></td>
        <td class="n-val">${esc((r.qualifier && r.qualifier !== "=" ? r.qualifier + " " : "") + r.value)} <span class="unit">${esc(r.unit)}</span></td>
        <td class="n-val">${r.nrv_pct !== undefined ? esc(r.nrv_pct) + "%" : "—"}</td>
      </tr>`
    )
    .join("");

  const treesToRender = ed.ingredients_tree_annotated || core.ingredients_tree || [];

  const partiesList =
    isUnifiedUniform && Array.isArray(compact.parties_summary)
      ? compact.parties_summary
      : attrs.parties || [];
  const originsList =
    isUnifiedUniform && Array.isArray(compact.origins_summary)
      ? compact.origins_summary
      : attrs.origin
        ? [attrs.origin]
        : [];
  const originDisplay = originsList.map(formatOrigin).filter(Boolean).join(" / ");

  const revisionsHtml = (ed.revisions || [])
    .map((r) => {
      const pathsSummary = (r.patch || []).map((op) => `${op.op} ${op.path}`).join(", ");
      const kindLabel = t(`revisionKinds.${r.kind}`);
      return `<div class="revision-item">
        <div class="ulid-head mono">
          ${renderRevPill(r.rev)}
          <span>${esc(kindLabel)} · ${esc(r.author)} · ${esc(r.created_at)}</span>
        </div>
        ${r.reason ? `<div style="margin-top:4px;">${esc(r.reason)}</div>` : ""}
        ${pathsSummary ? `<div class="mono" style="margin-top:4px;font-size:0.74rem;color:var(--md-on-surface-variant);">${esc(t("detail.patchPathsLabel"))}: ${esc(pathsSummary)}</div>` : ""}
      </div>`;
    })
    .join("");

  const supersedesChips = [
    ...(ed.supersedes || []).map(
      (sid) =>
        `<button type="button" class="chip mono jump-chip" data-select-edition="${esc(sid)}">${esc(t("detail.supersedesPrefix"))}: ${esc(sid)}</button>`
    ),
    ...(ed.superseded_by || []).map(
      (sid) =>
        `<button type="button" class="chip mono jump-chip" data-select-edition="${esc(sid)}">${esc(t("detail.supersededByPrefix"))}: ${esc(sid)}</button>`
    ),
  ].join(" ");

  const ingredientsBody = `
    ${(attrs.ingredients_text || [])
      .map(
        (tItem) =>
          `<div class="verbatim-box">${esc(tItem.text)} <span class="chip mono">${esc(tItem.lang)}</span></div>`
      )
      .join("")}
    <div style="margin-bottom:10px">${treesToRender
      .map((tItem) => renderIngredientTree(tItem.nodes))
      .join("")}</div>
    ${attrs.allergens_raw_text ? `<div class="verbatim-box">${esc(t("detail.metaAllergensRaw"))}: ${esc(attrs.allergens_raw_text)}</div>` : ""}
    <div style="display:flex; gap:6px; flex-wrap:wrap;">
      ${(norm.additives_ins || [])
        .map((code) => `<span class="chip mono">${esc(t("detail.additivePrefix"))} ${esc(code)}</span>`)
        .join("")}
      ${renderAllergensBadges(norm)}
    </div>`;

  const complianceBody = `
    <dl class="meta-dl">
      <dt>${esc(t("detail.metaProfile"))}</dt><dd class="mono">${esc(core.regulatory_profile)}</dd>
      ${isUnifiedUniform && compact.active_tracks ? `<dt>${esc(t("detail.activeTracksLabel"))}</dt><dd class="mono">${esc(compact.active_tracks.join(" · "))}</dd>` : `<dt>${esc(t("detail.trackLabel"))}</dt><dd class="mono">${esc(ed.track)}</dd>`}
      ${originDisplay ? `<dt>${esc(t("detail.metaOrigin"))}</dt><dd>${esc(originDisplay)}</dd>` : ""}
      ${attrs.product_standard ? `<dt>${esc(t("detail.metaStandard"))}</dt><dd class="mono">${esc(attrs.product_standard.join(" · "))}</dd>` : ""}
      ${attrs.declared_category ? `<dt>${esc(t("detail.metaCategory"))}</dt><dd>${esc(attrs.declared_category)}</dd>` : ""}
      ${attrs.shelf_life ? `<dt>${esc(t("detail.metaShelfLife"))}</dt><dd class="mono">${esc(attrs.shelf_life.value)} ${esc(attrs.shelf_life.unit)}</dd>` : ""}
      ${attrs.storage_text ? `<dt>${esc(t("detail.metaStorage"))}</dt><dd>${esc(attrs.storage_text)}</dd>` : ""}
      ${attrs.usage_text ? `<dt>${esc(t("detail.metaUsage"))}</dt><dd>${esc(attrs.usage_text)}</dd>` : ""}
      ${attrs.packaging_code ? `<dt>${esc(t("detail.metaPkgCode"))}</dt><dd class="mono">${esc(attrs.packaging_code)}</dd>` : ""}
      ${attrs.lot_code_rule ? `<dt>${esc(t("detail.metaLotRule"))}</dt><dd>${esc(attrs.lot_code_rule)}</dd>` : ""}
      ${(attrs.claims_text || []).length ? `<dt>${esc(t("detail.metaClaims"))}</dt><dd>${esc(attrs.claims_text.join(" · "))}</dd>` : ""}
      ${(attrs.special_indicators || []).length ? `<dt>${esc(t("detail.metaSpecialIndicators"))}</dt><dd class="mono">${esc(attrs.special_indicators.map((s) => `${s.name} ${s.qualifier || ""}${s.value}${s.unit}`).join(" · "))}</dd>` : ""}
    </dl>
    ${partiesList
      .map(
        (p) => `<div class="subcard">
          <b>${esc(p.name)}</b>
          <span class="chip mono">${esc(formatPartyRole(p.role))}</span>
          ${p.plant_code ? `<span class="chip mono">${esc(t("detail.plantCodePrefix"))} ${esc(p.plant_code)}</span>` : ""}
          ${p.license ? `<span class="chip mono">${esc(p.license)}</span>` : ""}
        </div>`
      )
      .join("")}`;

  const provenanceBody = `
    <div class="edition-timeline">${renderEditionTimelineHtml(full, ed.edition_id)}</div>
    ${supersedesChips ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">${supersedesChips}</div>` : ""}
    ${ed.lifecycle ? `<div class="archival-banner">${esc(t("detail.lifecycleOverridePrefix"))}: <b class="mono">${esc(ed.lifecycle.state)}</b>${ed.lifecycle.effective_month ? ` (${esc(ed.lifecycle.effective_month)})` : ""} — ${esc(ed.lifecycle.reason)}</div>` : ""}
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px;">
      <span class="chip mono">${esc(t("detail.coreFpPrefix"))}: ${esc(ed.core_fingerprint.slice(0, 26))}…</span>
      <span class="chip mono">${esc(t("detail.labelFpPrefix"))}: ${esc(ed.label_fingerprint.slice(0, 26))}…</span>
    </div>
    ${revisionsHtml ? `<div class="section-label" style="margin-top:8px;">${esc(t("detail.revisionsTitle"))}</div><div class="revision-list">${revisionsHtml}</div>` : ""}
    ${(ed.evidence || [])
      .map((ev, idx) => {
        const mediaSrc = resolveMediaRef(ev.media_ref);
        const canPreview = !!mediaSrc;
        const pubSha = ev.cropped_sha256 || ev.snapshot_sha256;
        return `<div class="subcard mono">
          <b>${esc(ev.evidence_id)}</b> [${esc(ev.type)}]
          ${ev.region ? `region=${esc(ev.region)}` : ""}
          ${ev.registry ? `registry=${esc(ev.registry)} (${esc(ev.query || "")})` : ""}
          ${pubSha ? `sha256=${esc(pubSha.slice(0, 16))}…` : ""}
          ${ev.vault_raw_sha256 ? `vault=${esc(ev.vault_raw_sha256.slice(0, 12))}…` : ""}
          ${ev.specimen_id ? `${esc(t("detail.specimenLabel"))}=${esc(ev.specimen_id)}` : ""}
          ${ev.vintage_month ? `${esc(t("detail.vintageLabel"))}=${esc(ev.vintage_month)}` : ""}
          ${ev.artwork_note ? `· ${esc(ev.artwork_note)}` : ""}
          · ${esc(ev.contributor || "")} (${esc(t("detail.reportedAtLabel"))}: ${esc(ev.reported_at || "")})
          ${
            canPreview
              ? ` <button type="button" class="chip mono preview-media-btn" data-media-src="${esc(mediaSrc)}" data-target-id="ev-img-${idx}">${esc(t("detail.previewCrop"))}</button>
                 <div id="ev-img-${idx}" hidden></div>`
              : ""
          }
        </div>`;
      })
      .join("")}`;

  const notesBody = (ed.quality_flags || []).length
    ? ed.quality_flags
        .map(
          (f) =>
            `<div class="note-item"><b>${esc(f.code)}</b> (${esc(f.field)}) — ${esc(f.detail)}</div>`
        )
        .join("")
    : `<span class="mono" style="font-size:0.82rem;color:var(--md-on-surface-variant)">${esc(t("detail.noNotes"))}</span>`;

  const viewMain = `<div class="detail-sections">
    ${renderSectionCard(t("detail.railNormalized"), renderNutritionSection(ed), `<span class="chip mono">${esc(norm.basis)}</span>`)}
    ${renderSectionCard(t("detail.railIngredients"), ingredientsBody)}
    ${renderSectionCard(t("detail.railCompliance"), complianceBody)}
    ${renderSectionCard(t("detail.railProvenance"), provenanceBody)}
    ${renderSectionCard(t("detail.railNotes"), notesBody)}
  </div>`;

  const declBasis = core.nutrition_declared.basis;
  const basisLabelSuffix = attrs.serving_size_label ? " / " + attrs.serving_size_label : "";
  const viewDeclared = `<div class="detail-sections">
    ${renderSectionCard(
      t("detail.tabDeclared"),
      `<p class="lead" style="margin-bottom:12px;">${esc(
         t("detail.declaredIntro", {
           value: declBasis.value,
           unit: declBasis.unit,
           labelSuffix: basisLabelSuffix,
         })
       )}</p>
       <div class="table-wrap">
         <table class="nutrient-table">
           <thead><tr><th>${esc(t("detail.declaredColId"))}</th><th>${esc(t("detail.declaredColVal"))}</th><th>${esc(t("detail.declaredColNrv"))}</th></tr></thead>
           <tbody>${declaredRows}</tbody>
         </table>
       </div>`
    )}
  </div>`;

  const viewApi = `<div class="detail-sections">
    ${renderSectionCard(
      t("detail.tabApi"),
      `<div class="endpoint-bar"><span class="method">GET</span><a href="${esc(rel(item.compact_url))}" target="_blank" rel="noopener">${esc(item.compact_url)}</a><span>${esc(t("detail.apiCompactDesc"))}</span></div>
       <div class="endpoint-bar"><span class="method">GET</span><a href="${esc(rel(item.full_url))}" target="_blank" rel="noopener">${esc(item.full_url)}</a><span>${esc(t("detail.apiFullDesc"))}</span></div>
       <pre class="json-view">${esc(JSON.stringify(compact, null, 2))}</pre>`,
      `<button type="button" class="icon-copy-btn copy-json-btn">${esc(t("detail.copyJsonBtn"))}</button>`
    )}
  </div>`;

  const views = [viewMain, viewDeclared, viewApi];

  let topBanners = "";
  if (redirectedFromId) {
    topBanners += `<div class="archival-banner emphasis">${esc(t("detail.redirectNotice", { from: redirectedFromId, to: ed.edition_id }))}</div>`;
  }
  if (compact.resolution === "divergent") {
    topBanners += `<div class="mode-switch-bar">
      <button type="button" class="chip" id="return-overview-btn">${esc(t("detail.returnToDivergentOverview"))}</button>
      <span class="ulid-head mono"><span class="ulid-code">${esc(ed.edition_id)}</span> ${renderRevPill(ed.rev)} <span class="chip mono">${esc(ed.track)}</span></span>
    </div>`;
  } else if (compact.resolution === "uniform") {
    topBanners += `<div class="archival-banner">${esc(t("detail.uniformBanner", { count: (compact.active_edition_ids || []).length }))}${
      selectedEditionId
        ? ` <button type="button" class="chip" id="return-overview-btn" style="margin-left:8px;">${esc(t("detail.returnToUniformOverview"))}</button>`
        : ""
    }</div>`;
  } else if (compact.resolution === "inactive") {
    topBanners += `<div class="archival-banner">${esc(t("detail.inactiveBanner"))}</div>`;
  }

  $("#detail").innerHTML = `
    <div class="mobile-back-bar">
      <button type="button" class="chip" id="mobile-back-btn">${esc(t("detail.backToCatalog"))}</button>
    </div>
    ${topBanners}
    <div class="card-topbar">
      <div class="call-number-block">
        <span class="cn-label">${esc(t("detail.productIdLabel"))}</span>
        <strong>${esc(item.id)}</strong>
        <button type="button" class="icon-copy-btn copy-id-btn" data-copy-text="${esc(item.id)}">${esc(t("detail.copyIdBtn"))}</button>
        ${renderResolutionBadge(compact.resolution)}
        ${renderStatusBadge(ed.status)}
      </div>
      ${renderSeal(ed.evidence_level)}
    </div>
    <hr class="title-rule" />
    <div class="card-title-block">
      <h2>${esc(title(attrs.brand, dispName))}</h2>
      <div class="card-imprint">
        <span class="imprint-item">${esc(t("detail.netContentLabel"))} ${esc(formatNetContent(core.net_content))}</span>
        <span class="imprint-item">${esc(t("detail.profileLabel"))} ${esc(core.regulatory_profile)}</span>
        <span class="imprint-item"><span class="ulid-head">${esc(t("detail.editionLabel"))} <span class="ulid-code">${esc(ed.edition_id)}</span> ${renderRevPill(ed.rev)}</span></span>
        <span class="imprint-item">${esc(t("detail.trackLabel"))} ${esc(ed.track)}</span>
        <span class="imprint-item">${esc(t("detail.tActiveLabel"))} ${esc(ed.t_active)}</span>
      </div>
    </div>
    <div class="card-tabs" role="tablist">
      <button type="button" class="card-tab" role="tab" id="tab-0" aria-controls="card-body" aria-selected="true" data-tab="0">${esc(t("detail.tabNormalized"))}</button>
      <button type="button" class="card-tab" role="tab" id="tab-1" aria-controls="card-body" aria-selected="false" data-tab="1">${esc(t("detail.tabDeclared"))}</button>
      <button type="button" class="card-tab" role="tab" id="tab-2" aria-controls="card-body" aria-selected="false" data-tab="2">${esc(t("detail.tabApi"))}</button>
    </div>
    <div id="card-body" role="tabpanel" aria-labelledby="tab-0">${views[0]}</div>`;

  bindDetailEvents(item, compact, full, views);
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
    btn.textContent = t("detail.copiedFeedback");
    setTimeout(() => {
      if (btn.isConnected) btn.textContent = origLabel;
    }, 1400);
  } catch (_) {
    // Ignore clipboard failure in restricted contexts
  }
}

function bindDetailEvents(item, compact, full, views) {
  const backBtn = $("#mobile-back-btn");
  if (backBtn) {
    backBtn.onclick = () => {
      $("#workspace").dataset.mobileView = "list";
      history.replaceState(null, "", location.pathname + location.search);
    };
  }

  const overviewBtn = $("#return-overview-btn");
  if (overviewBtn) {
    overviewBtn.onclick = () => {
      selectedEditionId = null;
      redirectedFromId = null;
      history.replaceState(null, "", `#${encodeURIComponent(item.id)}`);
      renderCatalogCard(item, compact, full);
    };
  }

  const tabs = $(".card-tabs");
  if (tabs) {
    tabs.onclick = (e) => {
      const b = e.target.closest(".card-tab");
      if (!b) return;
      document
        .querySelectorAll(".card-tab")
        .forEach((tabEl) => tabEl.setAttribute("aria-selected", String(tabEl === b)));
      const panel = $("#card-body");
      panel.setAttribute("aria-labelledby", b.id);
      panel.innerHTML = views[Number(b.dataset.tab)];
    };
  }

  $("#detail").onclick = (e) => {
    const copyIdBtn = e.target.closest(".copy-id-btn");
    if (copyIdBtn && copyIdBtn.dataset.copyText) {
      copyTextWithFeedback(copyIdBtn, copyIdBtn.dataset.copyText, t("detail.copyIdBtn"));
      return;
    }

    const copyJsonBtn = e.target.closest(".copy-json-btn");
    if (copyJsonBtn) {
      copyTextWithFeedback(copyJsonBtn, JSON.stringify(compact, null, 2), t("detail.copyJsonBtn"));
      return;
    }

    const traceBtn = e.target.closest(".trace-btn");
    if (traceBtn && traceBtn.dataset.formula) {
      const box = $("#formula-inspector");
      if (box) box.textContent = traceBtn.dataset.formula;
      return;
    }

    const selectEdBtn = e.target.closest("[data-select-edition]");
    if (selectEdBtn && selectEdBtn.dataset.selectEdition) {
      let targetId = selectEdBtn.dataset.selectEdition;
      if (full.edition_redirects && full.edition_redirects[targetId]) {
        redirectedFromId = targetId;
        targetId = full.edition_redirects[targetId];
      } else {
        redirectedFromId = null;
      }
      selectedEditionId = targetId;
      history.replaceState(
        null,
        "",
        `#${encodeURIComponent(item.id)}@${encodeURIComponent(targetId)}`
      );
      renderCatalogCard(item, compact, full);
      return;
    }

    const mediaBtn = e.target.closest(".preview-media-btn");
    if (mediaBtn && mediaBtn.dataset.targetId) {
      const holder = document.getElementById(mediaBtn.dataset.targetId);
      if (holder) {
        if (holder.hidden) {
          holder.innerHTML = `<img class="evidence-preview-img" src="${esc(mediaBtn.dataset.mediaSrc)}" alt="${esc(t("detail.evidenceAlt"))}" />`;
          holder.hidden = false;
        } else {
          holder.hidden = true;
        }
      }
    }
  };
}

// Pure-static barcode & QR parser (GS1 Mod-10 validation + OPF routing)
const BARCODE_FORMATS = [
  "ean_13",
  "ean_8",
  "upc_a",
  "upc_e",
  "code_128",
  "qr_code",
  "data_matrix",
];
const OPF_ID_RE = /^opf:([a-z0-9]+(?:-[a-z0-9]+)*)\/([a-z0-9]+(?:-[a-z0-9]+)*)\/([a-z0-9]+(?:-[a-z0-9]+)*)$/i;
const GTIN_LENGTHS = new Set([8, 12, 13, 14]);

function isValidGs1CheckDigit(digits) {
  if (typeof digits !== "string" || !/^\d+$/.test(digits) || !GTIN_LENGTHS.has(digits.length)) {
    return false;
  }
  if (/^0+$/.test(digits)) return false;
  const body = digits.slice(0, -1);
  const check = Number(digits[digits.length - 1]);
  let total = 0;
  for (let i = 0; i < body.length; i += 1) {
    total += Number(body[body.length - 1 - i]) * (i % 2 === 0 ? 3 : 1);
  }
  return check === (10 - (total % 10)) % 10;
}

function buildGtinApiPath(gtin14) {
  return `v1/gtin/${gtin14.slice(1, 4)}/${gtin14.slice(4, 7)}/${gtin14}.json`;
}

function buildOpfApiPath(opfId) {
  const m = OPF_ID_RE.exec(opfId);
  if (!m) return null;
  return `v1/opf/${m[1].toLowerCase()}/${m[2].toLowerCase()}/${m[3].toLowerCase()}.json`;
}

function classifyGtinCandidate(digits, rawText) {
  if (!isValidGs1CheckDigit(digits)) {
    return { kind: "invalid_gtin", raw: rawText, digits, valid: false };
  }
  const gtin14 = digits.padStart(14, "0");
  return {
    kind: "gtin",
    raw: rawText,
    digits,
    gtin14,
    id: `gtin:${gtin14}`,
    apiPath: buildGtinApiPath(gtin14),
    valid: true,
  };
}

function extractOpfFromUrl(url) {
  const cleanPath = url.pathname.replace(/\.(?:full\.)?json$/i, "");
  const m = /\/v1\/opf\/([a-z0-9-]+)\/([a-z0-9-]+)\/([a-z0-9-]+)$/i.exec(cleanPath);
  if (!m) return null;
  const id = `opf:${m[1].toLowerCase()}/${m[2].toLowerCase()}/${m[3].toLowerCase()}`;
  return OPF_ID_RE.test(id) ? id : null;
}

function extractDigitsFromUrl(url) {
  const dlMatch = /(?:^|\/)01\/(\d{8,14})(?:\/|$)/.exec(url.pathname);
  if (dlMatch) return dlMatch[1];

  const paramNames = ["gtin", "ean", "barcode", "code"];
  for (const [k, v] of url.searchParams.entries()) {
    if (!paramNames.includes(k.toLowerCase())) continue;
    const cleaned = v.trim().replace(/^gtin:/i, "");
    if (/^\d{8,14}$/.test(cleaned)) return cleaned;
  }

  const segments = url.pathname.split("/").filter(Boolean);
  for (let i = segments.length - 1; i >= 0; i -= 1) {
    const seg = segments[i].replace(/\.(?:full\.)?json$/i, "");
    if (/^\d{8,14}$/.test(seg)) return seg;
  }
  return null;
}

function parseScannedCode(rawText) {
  const text = String(rawText ?? "").trim();
  if (!text) return { kind: "empty", raw: "", valid: false };

  const opfMatch = OPF_ID_RE.exec(text);
  if (opfMatch) {
    const id = `opf:${opfMatch[1].toLowerCase()}/${opfMatch[2].toLowerCase()}/${opfMatch[3].toLowerCase()}`;
    return { kind: "opf", raw: text, id, apiPath: buildOpfApiPath(id), valid: true };
  }

  const gtinPrefMatch = /^gtin:\s*(\d+)$/i.exec(text);
  if (gtinPrefMatch) {
    return classifyGtinCandidate(gtinPrefMatch[1], text);
  }

  if (/^\d{8,14}$/.test(text)) {
    return classifyGtinCandidate(text, text);
  }

  if (/^https?:\/\//i.test(text)) {
    try {
      const url = new URL(text);
      const opfFromUrl = extractOpfFromUrl(url);
      if (opfFromUrl) {
        return { kind: "opf", raw: text, id: opfFromUrl, apiPath: buildOpfApiPath(opfFromUrl), valid: true };
      }
      const digits = extractDigitsFromUrl(url);
      if (digits) return classifyGtinCandidate(digits, text);
    } catch (_) {
      // Treat malformed URL as plain search text
    }
  }

  return { kind: "text", raw: text, query: text, valid: false };
}

const scannerState = {
  stream: null,
  rafId: null,
  timerId: null,
  token: 0,
  detectBusy: false,
  lastFocused: null,
};

function updateScannerChromeText() {
  const toggleBtn = $("#scan-camera-toggle");
  if (toggleBtn) {
    const active = Boolean(scannerState.stream);
    toggleBtn.textContent = t(active ? "scanner.stopCameraBtn" : "scanner.startCameraBtn");
    toggleBtn.setAttribute("aria-pressed", String(active));
  }
}

function setScanStatus(message, tone = "info") {
  const el = $("#scan-status");
  if (!el) return;
  if (!message) {
    el.hidden = true;
    el.textContent = "";
    delete el.dataset.tone;
    return;
  }
  el.hidden = false;
  el.dataset.tone = tone;
  el.textContent = message;
}

function setScanResult(html = "") {
  const el = $("#scan-result");
  if (!el) return;
  if (!html) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  el.hidden = false;
  el.innerHTML = html;
}

function stopTracksOnStream(stream) {
  if (!stream || typeof stream.getTracks !== "function") return;
  for (const track of stream.getTracks()) {
    try {
      track.stop();
    } catch (_) {
      // Ignore already-stopped track errors
    }
  }
}

function stopScannerCamera() {
  scannerState.token += 1;
  scannerState.detectBusy = false;
  if (scannerState.rafId !== null && typeof cancelAnimationFrame === "function") {
    cancelAnimationFrame(scannerState.rafId);
  }
  scannerState.rafId = null;
  if (scannerState.timerId !== null) {
    clearTimeout(scannerState.timerId);
  }
  scannerState.timerId = null;

  stopTracksOnStream(scannerState.stream);
  scannerState.stream = null;

  const videoEl = $("#scan-video");
  if (videoEl) {
    if (videoEl.srcObject && videoEl.srcObject !== scannerState.stream) {
      stopTracksOnStream(videoEl.srcObject);
    }
    if (typeof videoEl.pause === "function") videoEl.pause();
    videoEl.srcObject = null;
  }

  const viewport = $("#scan-viewport");
  if (viewport) viewport.dataset.active = "false";
  updateScannerChromeText();
}

async function createBarcodeDetector() {
  if (typeof window === "undefined" || typeof window.BarcodeDetector !== "function") {
    return null;
  }
  const Detector = window.BarcodeDetector;
  try {
    if (typeof Detector.getSupportedFormats === "function") {
      const supported = await Detector.getSupportedFormats();
      const chosen = BARCODE_FORMATS.filter((fmt) => supported.includes(fmt));
      if (chosen.length) return new Detector({ formats: chosen });
    }
    return new Detector({ formats: BARCODE_FORMATS });
  } catch (_) {
    try {
      return new Detector();
    } catch (__) {
      return null;
    }
  }
}

function applySearchQueryFromScan(queryText, autoSelect = false) {
  filter.text = queryText;
  const qEl = $("#q");
  if (qEl) qEl.value = queryText;
  updateWorkbenchChromeAndStrip();
  renderList(autoSelect);
}

async function processScannedPayload(rawText) {
  const parsed = parseScannedCode(rawText);
  if (parsed.kind === "empty") {
    setScanStatus(t("scanner.emptyInput"), "warn");
    return;
  }
  if (parsed.kind === "invalid_gtin") {
    setScanStatus(t("scanner.invalidCheckDigit", { digits: parsed.digits }), "error");
    setScanResult("");
    return;
  }
  if (parsed.kind === "text") {
    applySearchQueryFromScan(parsed.query, true);
    setScanStatus(t("scanner.plainTextNotice", { text: parsed.query }), "warn");
    setScanResult("");
    return;
  }

  applySearchQueryFromScan(parsed.id, false);
  const exactHit = CATALOG.find(
    (item) => item.id === parsed.id || (Array.isArray(item.aliases) && item.aliases.includes(parsed.id))
  );
  if (exactHit) {
    setScanStatus(t("scanner.hitFound", { id: parsed.id }), "info");
    setScanResult("");
    closeScannerModal();
    await selectCard(exactHit, true);
    return;
  }

  setScanStatus(t("scanner.lookupChecking", { id: parsed.id }), "info");
  try {
    const resp = await fetch(rel(parsed.apiPath));
    if (resp.ok) {
      const doc = await resp.json();
      const targetId = doc && doc.id ? doc.id : parsed.id;
      const catalogMatch = CATALOG.find((item) => item.id === targetId);
      if (catalogMatch) {
        closeScannerModal();
        await selectCard(catalogMatch, true);
        return;
      }
      setScanStatus("", "info");
      setScanResult(`
        <strong>${esc(t("scanner.directHitTitle", { id: targetId }))}</strong>
        <p>${esc(t("scanner.directHitDesc", { path: parsed.apiPath }))}</p>
        <div class="scan-result-code-row">
          <code class="scan-code-pill mono">${esc(targetId)}</code>
          <button type="button" class="chip copy-scan-id-btn" data-copy-text="${esc(targetId)}">${esc(t("scanner.copyCodeBtn"))}</button>
        </div>`);
      return;
    }
  } catch (_) {
    // Treat network/404 failure uniformly as unindexed fallback
  }

  setScanStatus("", "info");
  setScanResult(`
    <strong>${esc(t("scanner.notFoundTitle", { id: parsed.id }))}</strong>
    <p>${esc(t("scanner.notFoundDesc", { path: parsed.apiPath }))}</p>
    <div class="scan-result-code-row">
      <code class="scan-code-pill mono">${esc(parsed.id)}</code>
      <button type="button" class="chip copy-scan-id-btn" data-copy-text="${esc(parsed.id)}">${esc(t("scanner.copyCodeBtn"))}</button>
    </div>`);
}

function scheduleNextVideoScan(detector, videoEl, sessionToken) {
  if (sessionToken !== scannerState.token) return;
  const modal = $("#scan-modal");
  if (!modal || modal.hidden || !scannerState.stream) return;

  scannerState.timerId = setTimeout(() => {
    if (sessionToken !== scannerState.token) return;
    scannerState.rafId = requestAnimationFrame(async () => {
      if (sessionToken !== scannerState.token || scannerState.detectBusy) return;
      if (videoEl.readyState >= 2) {
        scannerState.detectBusy = true;
        try {
          const codes = await detector.detect(videoEl);
          if (sessionToken !== scannerState.token) return;
          const hit = Array.isArray(codes) ? codes.find((c) => c && c.rawValue) : null;
          if (hit) {
            stopScannerCamera();
            await processScannedPayload(hit.rawValue);
            return;
          }
        } catch (err) {
          if (sessionToken !== scannerState.token) return;
          stopScannerCamera();
          setScanStatus(t("scanner.cameraError", { reason: err && err.message ? err.message : "detect" }), "error");
          return;
        } finally {
          scannerState.detectBusy = false;
        }
      }
      scheduleNextVideoScan(detector, videoEl, sessionToken);
    });
  }, 180);
}

async function startScannerCamera() {
  stopScannerCamera();
  const sessionToken = scannerState.token;

  if (typeof window !== "undefined" && window.isSecureContext === false) {
    setScanStatus(t("scanner.insecureContext"), "warn");
    return;
  }
  const detector = await createBarcodeDetector();
  if (!detector) {
    setScanStatus(t("scanner.unsupportedDetector"), "warn");
    return;
  }
  if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
    setScanStatus(t("scanner.cameraPermissionDenied"), "error");
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });
    const modal = $("#scan-modal");
    if (sessionToken !== scannerState.token || !modal || modal.hidden) {
      stopTracksOnStream(stream);
      return;
    }
    scannerState.stream = stream;
    const videoEl = $("#scan-video");
    const viewport = $("#scan-viewport");
    if (videoEl) {
      videoEl.srcObject = stream;
      await videoEl.play();
    }
    if (viewport) viewport.dataset.active = "true";
    updateScannerChromeText();
    setScanStatus(t("scanner.cameraLive"), "info");
    if (videoEl) scheduleNextVideoScan(detector, videoEl, sessionToken);
  } catch (err) {
    stopScannerCamera();
    const name = err && err.name ? err.name : "";
    if (name === "NotAllowedError" || name === "PermissionDeniedError" || name === "NotFoundError") {
      setScanStatus(t("scanner.cameraPermissionDenied"), "error");
    } else {
      setScanStatus(t("scanner.cameraError", { reason: (err && err.message) || name || "error" }), "error");
    }
  }
}

async function handleScanImageFile(file) {
  if (!file) return;
  stopScannerCamera();
  setScanResult("");
  const detector = await createBarcodeDetector();
  if (!detector) {
    setScanStatus(t("scanner.unsupportedDetector"), "warn");
    return;
  }
  setScanStatus(t("scanner.scanningImage"), "info");
  let source = null;
  let objectUrl = null;
  try {
    if (typeof createImageBitmap === "function") {
      source = await createImageBitmap(file);
    } else {
      objectUrl = URL.createObjectURL(file);
      source = await new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error("image load failed"));
        img.src = objectUrl;
      });
    }
    const codes = await detector.detect(source);
    const hit = Array.isArray(codes) ? codes.find((c) => c && c.rawValue) : null;
    if (!hit) {
      setScanStatus(t("scanner.noBarcodeInImage"), "warn");
      return;
    }
    await processScannedPayload(hit.rawValue);
  } catch (err) {
    setScanStatus(t("scanner.imageError", { reason: (err && err.message) || "error" }), "error");
  } finally {
    if (source && typeof source.close === "function") source.close();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }
}

function openScannerModal() {
  const modal = $("#scan-modal");
  if (!modal) return;
  scannerState.lastFocused = document.activeElement;
  modal.hidden = false;
  setScanStatus("", "info");
  setScanResult("");
  updateScannerChromeText();
  if (typeof window !== "undefined" && window.isSecureContext === false) {
    setScanStatus(t("scanner.insecureContext"), "warn");
  } else if (typeof window === "undefined" || typeof window.BarcodeDetector !== "function") {
    setScanStatus(t("scanner.unsupportedDetector"), "warn");
  }
  const manualInput = $("#scan-manual-input");
  if (manualInput) manualInput.focus();
}

function closeScannerModal() {
  stopScannerCamera();
  const modal = $("#scan-modal");
  if (modal) modal.hidden = true;
  if (scannerState.lastFocused && typeof scannerState.lastFocused.focus === "function") {
    scannerState.lastFocused.focus();
  }
  scannerState.lastFocused = null;
}

function initScannerControls() {
  const openBtn = $("#scan-btn");
  const closeBtn = $("#scan-close-btn");
  const backdrop = $("#scan-backdrop");
  const cameraToggle = $("#scan-camera-toggle");
  const fileInput = $("#scan-file");
  const fileLabel = document.querySelector(".scan-file-label");
  const manualForm = $("#scan-manual-form");
  const resultBox = $("#scan-result");

  if (openBtn) openBtn.addEventListener("click", openScannerModal);
  if (closeBtn) closeBtn.addEventListener("click", closeScannerModal);
  if (backdrop) backdrop.addEventListener("click", closeScannerModal);

  if (cameraToggle) {
    cameraToggle.addEventListener("click", () => {
      if (scannerState.stream) stopScannerCamera();
      else startScannerCamera();
    });
  }

  if (fileLabel && fileInput) {
    fileLabel.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        fileInput.click();
      }
    });
  }

  if (fileInput) {
    fileInput.addEventListener("change", async (e) => {
      const f = e.target.files && e.target.files[0];
      await handleScanImageFile(f);
      e.target.value = "";
    });
  }

  if (manualForm) {
    manualForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      stopScannerCamera();
      const inputEl = $("#scan-manual-input");
      await processScannedPayload(inputEl ? inputEl.value : "");
    });
  }

  if (resultBox) {
    resultBox.addEventListener("click", (e) => {
      const copyBtn = e.target.closest(".copy-scan-id-btn");
      if (copyBtn && copyBtn.dataset.copyText) {
        copyTextWithFeedback(copyBtn, copyBtn.dataset.copyText, t("scanner.copyCodeBtn"));
      }
    });
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopScannerCamera();
  });
  window.addEventListener("pagehide", stopScannerCamera);
}

if (HAS_DOM) {
  init();
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    isValidGs1CheckDigit,
    parseScannedCode,
    buildGtinApiPath,
    buildOpfApiPath,
  };
}
