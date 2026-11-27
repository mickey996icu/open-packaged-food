"use strict";
// OpenPackagedFood Filter Workbench Module (Multi-facet filtering, nutrient rules & sorting)

(function (root, factory) {
  const api = factory();
  root.OPFWorkbench = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : window, function () {
  const CHIP_CHECK_SVG =
    '<svg class="chip-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.2 4.2L19 7.5"/></svg>';

  const NUTRIENT_DEFAULT_UNITS = {
    energy_kcal: "kcal", energy_kj: "kJ", protein: "g", fat_total: "g", fat_saturated: "g",
    fat_trans: "g", fat_monounsaturated: "g", fat_polyunsaturated: "g", cholesterol: "mg",
    carbs_available: "g", carbs_total: "g", sugars_total: "g", sugars_added: "g",
    sugar_alcohols: "g", dietary_fiber: "g", sodium: "mg", salt_equivalent: "g",
    calcium: "mg", iron: "mg", potassium: "mg", vitamin_a: "ug", vitamin_c: "mg", vitamin_d: "ug",
  };

  const RULE_NUTRIENT_OPTIONS = [
    "energy_kcal", "energy_kj", "protein", "fat_total", "fat_saturated", "carbs_available",
    "carbs_total", "sugars_total", "sugars_added", "dietary_fiber", "sodium",
    "salt_equivalent", "calcium", "vitamin_d",
  ];

  const RESOLUTION_ORDER = ["single", "uniform", "divergent", "inactive"];
  const EVIDENCE_ORDER = [
    "corroborated",
    "verified",
    "official_registry_imported",
    "community_reported",
  ];

  function createEmptyFilter() {
    return {
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

  function itemMatchesIngTerm(item, rawTerm) {
    const q = rawTerm.trim().toLowerCase();
    if (!q) return true;
    const toks = item.ingredients_tokens || [];
    if (toks.some((tok) => tok.includes(q))) return true;
    const insList = item.additives_ins || [];
    const bare = q.replace(/^(ins|e)\s*/i, "");
    return insList.some((code) => code.toLowerCase() === q || code.toLowerCase() === bare);
  }

  function evaluateNutrientRule(item, rule) {
    if (!isRuleActive(rule)) return true;
    const nMap = item.nutrients_100 || {};
    const n = nMap[rule.nutrient];
    if (!n || n.partial) return false;
    if (rule.op === "le") return n.max <= Number(rule.val);
    if (rule.op === "ge") return !n.has_upper_bound && n.min >= Number(rule.val);

    const hasMin = rule.minVal !== "" && rule.minVal !== undefined && !Number.isNaN(Number(rule.minVal));
    const hasMax = rule.maxVal !== "" && rule.maxVal !== undefined && !Number.isNaN(Number(rule.maxVal));
    const a = hasMin ? Number(rule.minVal) : 0;
    const b = hasMax ? Number(rule.maxVal) : Number.POSITIVE_INFINITY;
    if (hasMin && hasMax && a > b) return false;
    const loOk = !hasMin || a === 0 ? true : !n.has_upper_bound && n.min >= a;
    const hiOk = !hasMax || n.max <= b;
    return loOk && hiOk;
  }

  function createWorkbenchController(ctx) {
    const { $, t, esc, translateNutrient, getCatalog, isWorkbenchOpen, setWorkbenchOpen, onFilterChange } = ctx;
    let filter = createEmptyFilter();
    let nextRuleUid = 1;
    let searchRafId = 0;

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

    function getNutrientUnitForRule(nutrientKey) {
      return NUTRIENT_DEFAULT_UNITS[nutrientKey] || "g";
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

    function makeFilterChip({ attrName, attrVal, label, count, active, extraClass = "" }) {
      const cls = ["chip", "filter-chip", extraClass].filter(Boolean).join(" ");
      const countHtml = count !== undefined ? `<span class="chip-count">${esc(count)}</span>` : "";
      return `<button type="button" class="${cls}" data-${attrName}="${esc(attrVal)}" aria-pressed="${active}">${
        active ? CHIP_CHECK_SVG : ""
      }<span>${esc(label)}</span>${countHtml}</button>`;
    }

    function updateWorkbenchChromeAndStrip() {
      const catalog = getCatalog();
      const qClear = $("#q-clear");
      if (qClear) qClear.hidden = !filter.text;

      const panel = $("#filter-panel");
      const toggleBtn = $("#wb-toggle");
      const wbOpen = isWorkbenchOpen();
      const advCount = countAdvancedFilters();
      if (panel) panel.hidden = !wbOpen;
      if (toggleBtn) {
        toggleBtn.setAttribute("aria-expanded", String(wbOpen));
        toggleBtn.innerHTML = `<span class="ink-ui">${esc(advCount ? `${t("search.wbToggle")} (${advCount})` : t("search.wbToggle"))}</span>`;
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
        const found = catalog.find((i) => (i.brand_slug || i.brand) === bslug);
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
      if (filter.zeroAdditives) tags.push({ kind: "zeroAdd", val: "1", label: t("search.zeroAdditivesChip"), excl: false });
      if (filter.zeroCalorie) tags.push({ kind: "zeroCal", val: "1", label: t("search.zeroCalorieChip"), excl: false });
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

    function renderWorkbenchControls() {
      const catalog = getCatalog();
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
          .map(([val, lbl]) => `<option value="${esc(val)}"${filter.sort === val ? " selected" : ""}>${esc(lbl)}</option>`)
          .join("");
      }

      const marketCounts = {};
      const resCounts = {};
      const levelCounts = {};
      const profileCounts = {};
      const nsCounts = {};
      const brandsMap = {};
      const allergenSet = new Set();
      let zeroAdditivesCount = 0;
      let zeroCalorieCount = 0;

      catalog.forEach((item) => {
        (item.markets || []).forEach((m) => { marketCounts[m] = (marketCounts[m] || 0) + 1; });
        if (item.resolution) resCounts[item.resolution] = (resCounts[item.resolution] || 0) + 1;
        if (item.evidence_level) levelCounts[item.evidence_level] = (levelCounts[item.evidence_level] || 0) + 1;
        (item.profiles || []).forEach((p) => { profileCounts[p] = (profileCounts[p] || 0) + 1; });
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

      const marketEntries = Object.entries(marketCounts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
      const marketRow = $("#market-filters");
      if (marketRow) {
        marketRow.innerHTML =
          makeFilterChip({
            attrName: "market",
            attrVal: "",
            label: t("search.allMarkets"),
            count: catalog.length,
            active: filter.markets.length === 0,
          }) +
          marketEntries
            .map(([mkt, cnt]) =>
              makeFilterChip({
                attrName: "market",
                attrVal: mkt,
                label: mkt,
                count: cnt,
                active: filter.markets.includes(mkt),
              })
            )
            .join("");
      }

      const colFacets = $("#wb-col-facets");
      if (colFacets) {
        const presentRes = RESOLUTION_ORDER.filter((r) => resCounts[r]);
        const resHtml =
          makeFilterChip({ attrName: "resolution", attrVal: "", label: t("search.allResolutions"), active: filter.resolutions.length === 0 }) +
          presentRes
            .map((r) =>
              makeFilterChip({
                attrName: "resolution",
                attrVal: r,
                label: t(`resolutions.${r}.short`),
                count: resCounts[r],
                active: filter.resolutions.includes(r),
              })
            )
            .join("");

        const levelKeys = [
          ...EVIDENCE_ORDER.filter((lv) => levelCounts[lv]),
          ...Object.keys(levelCounts).filter((lv) => !EVIDENCE_ORDER.includes(lv)),
        ];
        const levelHtml =
          makeFilterChip({ attrName: "level", attrVal: "", label: t("search.allEvidence"), active: filter.levels.length === 0 }) +
          levelKeys
            .map((lv) =>
              makeFilterChip({
                attrName: "level",
                attrVal: lv,
                label: t(`seals.${lv}.label`),
                count: levelCounts[lv],
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
              label: pr,
              count: profileCounts[pr],
              active: filter.profiles.includes(pr),
            })
          ),
          ...nsKeys.map((ns) =>
            makeFilterChip({
              attrName: "namespace",
              attrVal: ns,
              label: ns.toUpperCase(),
              count: nsCounts[ns],
              active: filter.namespaces.includes(ns),
            })
          ),
        ].join("");

        const brandHtml = Object.values(brandsMap)
          .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name))
          .map((b) =>
            makeFilterChip({
              attrName: "brand",
              attrVal: b.slug,
              label: b.name,
              count: b.count,
              active: filter.brands.includes(b.slug),
            })
          )
          .join("");

        colFacets.innerHTML = `
          <div class="wb-col-title">${esc(t("search.colFacets"))}</div>
          <div><div class="filter-group-head"><span class="filter-group-title">${esc(t("search.groupResolution"))}</span></div><div class="filter-chip-row">${resHtml}</div></div>
          <div><div class="filter-group-head"><span class="filter-group-title">${esc(t("search.groupEvidence"))}</span></div><div class="filter-chip-row">${levelHtml}</div></div>
          <div><div class="filter-group-head"><span class="filter-group-title">${esc(t("search.groupProfile"))}</span></div><div class="filter-chip-row">${profileHtml}</div></div>
          <div><div class="filter-group-head"><span class="filter-group-title">${esc(t("search.groupBrand"))}</span></div><div class="filter-chip-row">${brandHtml}</div></div>`;
      }

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
          .map((term) => `<button type="button" class="active-tag" data-rm-inc-ing="${esc(term)}"><span>+ ${esc(term)}</span> <span aria-hidden="true">×</span></button>`)
          .join("");
        const excTagsHtml = filter.excludeIngredients
          .map((term) => `<button type="button" class="active-tag exclude" data-rm-exc-ing="${esc(term)}"><span>− ${esc(term)}</span> <span aria-hidden="true">×</span></button>`)
          .join("");

        colIng.innerHTML = `
          <div class="wb-col-title">${esc(t("search.colIngredients"))}</div>
          ${
            sortedAllergens.length
              ? `<div><div class="filter-group-head"><span class="filter-group-title">${esc(t("search.groupExcludeAllergens"))}</span></div><p class="filter-group-hint">${esc(t("search.excludeAllergensHint"))}</p><div class="filter-chip-row">${allergensHtml}</div></div>`
              : ""
          }
          <div>
            <div class="filter-group-head"><span class="filter-group-title">${esc(t("search.mustIncludeLabel"))}</span></div>
            <div class="tag-input-row"><input type="text" class="wb-input" id="inc-ing-input" placeholder="${esc(t("search.mustIncludePlaceholder"))}" /><button type="button" class="chip" id="inc-ing-add">${esc(t("search.addTagBtn"))}</button></div>
            ${incTagsHtml ? `<div class="filter-chip-row" style="margin-top:6px;">${incTagsHtml}</div>` : ""}
          </div>
          <div>
            <div class="filter-group-head"><span class="filter-group-title">${esc(t("search.mustExcludeLabel"))}</span></div>
            <div class="tag-input-row"><input type="text" class="wb-input" id="exc-ing-input" placeholder="${esc(t("search.mustExcludePlaceholder"))}" /><button type="button" class="chip" id="exc-ing-add">${esc(t("search.addTagBtn"))}</button></div>
            ${excTagsHtml ? `<div class="filter-chip-row" style="margin-top:6px;">${excTagsHtml}</div>` : ""}
          </div>
          <div>
            <div class="filter-group-head"><span class="filter-group-title">${esc(t("search.groupFeatures"))}</span></div>
            <div class="filter-chip-row">
              ${makeFilterChip({ attrName: "trait", attrVal: "zero-additives", label: t("search.zeroAdditivesChip"), count: zeroAdditivesCount, active: filter.zeroAdditives })}
              ${makeFilterChip({ attrName: "trait", attrVal: "zero-calorie", label: t("search.zeroCalorieChip"), count: zeroCalorieCount, active: filter.zeroCalorie })}
            </div>
          </div>`;
      }

      const colNut = $("#wb-col-nutrients");
      if (colNut) {
        const presetsHtml = `<div class="filter-chip-row">
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
              .map(([opv, opl]) => `<option value="${esc(opv)}"${rule.op === opv ? " selected" : ""}>${esc(opl)}</option>`)
              .join("");
            const unit = getNutrientUnitForRule(rule.nutrient);
            const inputsHtml =
              rule.op === "range"
                ? `<input type="number" min="0" step="any" class="wb-input num-input rule-min" value="${esc(rule.minVal)}" placeholder="${esc(t("search.minPlaceholder"))}" /><span aria-hidden="true">~</span><input type="number" min="0" step="any" class="wb-input num-input rule-max" value="${esc(rule.maxVal)}" placeholder="${esc(t("search.maxPlaceholder"))}" />`
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
          <div><div class="filter-group-head"><span class="filter-group-title">${esc(t("search.presetsLabel"))}</span></div>${presetsHtml}</div>
          <div class="nutrient-rules-list" id="nutrient-rules-list">${rulesHtml}</div>
          <div><button type="button" class="chip" id="add-nutrient-rule-btn">${esc(t("search.addNutrientRule"))}</button></div>`;
      }

      updateWorkbenchChromeAndStrip();
    }

    function getFilteredAndSortedCatalog() {
      const catalog = getCatalog();
      const q = filter.text.trim().toLowerCase();
      const filtered = catalog.filter((i) => {
        if (filter.markets.length && !(i.markets || []).some((m) => filter.markets.includes(m))) return false;
        if (filter.resolutions.length && !filter.resolutions.includes(i.resolution)) return false;
        if (filter.levels.length && !filter.levels.includes(i.evidence_level)) return false;
        if (filter.profiles.length && !(i.profiles || []).some((p) => filter.profiles.includes(p))) return false;
        if (filter.namespaces.length && !filter.namespaces.includes(i.namespace)) return false;
        if (filter.brands.length && !filter.brands.includes(i.brand_slug || i.brand)) return false;
        if (filter.excludeAllergens.length) {
          const hitContain = i.allergens_contains || [];
          const hitMay = i.allergens_may_contain || [];
          if (filter.excludeAllergens.some((alg) => hitContain.includes(alg) || hitMay.includes(alg))) return false;
        }
        if (filter.includeIngredients.length && !filter.includeIngredients.every((term) => itemMatchesIngTerm(i, term))) return false;
        if (filter.excludeIngredients.length && filter.excludeIngredients.some((term) => itemMatchesIngTerm(i, term))) return false;
        if (filter.zeroAdditives && (i.additives_count ?? 0) !== 0) return false;
        if (filter.zeroCalorie) {
          const ek = i.nutrients_100 && i.nutrients_100.energy_kcal;
          if (!ek || ek.partial || ek.max > 5) return false;
        }
        if (filter.nutrientRules.length && !filter.nutrientRules.every((rule) => evaluateNutrientRule(i, rule))) return false;
        if (!q) return true;
        const allNames = i.names ? Object.values(i.names) : [i.name];
        const allBrandNames = Array.isArray(i.brand_names) ? i.brand_names : i.brand_names ? Object.values(i.brand_names) : [];
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
        sorted.sort((a, b) => String(a.brand || "").localeCompare(String(b.brand || "")) || a.id.localeCompare(b.id));
      } else {
        sorted.sort((a, b) => a.id.localeCompare(b.id));
      }
      return sorted;
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
      onFilterChange(true);
    }

    function submitIngredientTagInput(kind) {
      const inputEl = kind === "inc" ? $("#inc-ing-input") : $("#exc-ing-input");
      if (!inputEl) return;
      const val = inputEl.value.trim();
      if (!val) return;
      const list = kind === "inc" ? filter.includeIngredients : filter.excludeIngredients;
      if (!list.some((x) => x.toLowerCase() === val.toLowerCase())) list.push(val);
      renderWorkbenchControls();
      onFilterChange(true);
    }

    function resetAllFilters() {
      filter = createEmptyFilter();
      const qEl = $("#q");
      if (qEl) qEl.value = "";
      renderWorkbenchControls();
      onFilterChange(true);
    }

    function setSearchText(queryText, autoSelect = false) {
      filter.text = queryText;
      const qEl = $("#q");
      if (qEl) qEl.value = queryText;
      updateWorkbenchChromeAndStrip();
      onFilterChange(autoSelect);
    }

    function bindEvents() {
      $("#q").addEventListener("input", (e) => {
        filter.text = e.target.value;
        updateWorkbenchChromeAndStrip();
        if (typeof requestAnimationFrame === "function") {
          if (searchRafId) cancelAnimationFrame(searchRafId);
          searchRafId = requestAnimationFrame(() => {
            searchRafId = 0;
            onFilterChange(true);
          });
        } else {
          onFilterChange(true);
        }
      });

      $("#q-clear").addEventListener("click", () => {
        filter.text = "";
        $("#q").value = "";
        $("#q").focus();
        updateWorkbenchChromeAndStrip();
        onFilterChange(true);
      });

      $("#sort-select").addEventListener("change", (e) => {
        filter.sort = e.target.value;
        onFilterChange(true);
      });

      $("#wb-toggle").addEventListener("click", () => {
        setWorkbenchOpen(!isWorkbenchOpen());
        updateWorkbenchChromeAndStrip();
      });

      $("#reset-filters-btn").addEventListener("click", resetAllFilters);

      $("#market-filters").addEventListener("click", (e) => {
        const b = e.target.closest("button[data-market]");
        if (!b) return;
        filter.markets = b.dataset.market === "" ? [] : toggleArrayVal(filter.markets, b.dataset.market);
        renderWorkbenchControls();
        onFilterChange(true);
      });

      $("#filter-panel").addEventListener("click", (e) => {
        const resBtn = e.target.closest("button[data-resolution]");
        if (resBtn) {
          filter.resolutions = resBtn.dataset.resolution === "" ? [] : toggleArrayVal(filter.resolutions, resBtn.dataset.resolution);
          renderWorkbenchControls();
          onFilterChange(true);
          return;
        }
        const lvBtn = e.target.closest("button[data-level]");
        if (lvBtn) {
          filter.levels = lvBtn.dataset.level === "" ? [] : toggleArrayVal(filter.levels, lvBtn.dataset.level);
          renderWorkbenchControls();
          onFilterChange(true);
          return;
        }
        const profBtn = e.target.closest("button[data-profile]");
        if (profBtn) {
          filter.profiles = toggleArrayVal(filter.profiles, profBtn.dataset.profile);
          renderWorkbenchControls();
          onFilterChange(true);
          return;
        }
        const nsBtn = e.target.closest("button[data-namespace]");
        if (nsBtn) {
          filter.namespaces = toggleArrayVal(filter.namespaces, nsBtn.dataset.namespace);
          renderWorkbenchControls();
          onFilterChange(true);
          return;
        }
        const brandBtn = e.target.closest("button[data-brand]");
        if (brandBtn) {
          filter.brands = toggleArrayVal(filter.brands, brandBtn.dataset.brand);
          renderWorkbenchControls();
          onFilterChange(true);
          return;
        }
        const algBtn = e.target.closest("button[data-exclude-allergen]");
        if (algBtn) {
          filter.excludeAllergens = toggleArrayVal(filter.excludeAllergens, algBtn.dataset.excludeAllergen);
          renderWorkbenchControls();
          onFilterChange(true);
          return;
        }
        const traitBtn = e.target.closest("button[data-trait]");
        if (traitBtn) {
          if (traitBtn.dataset.trait === "zero-additives") filter.zeroAdditives = !filter.zeroAdditives;
          if (traitBtn.dataset.trait === "zero-calorie") filter.zeroCalorie = !filter.zeroCalorie;
          renderWorkbenchControls();
          onFilterChange(true);
          return;
        }
        if (e.target.closest("#inc-ing-add")) return submitIngredientTagInput("inc");
        if (e.target.closest("#exc-ing-add")) return submitIngredientTagInput("exc");
        const rmInc = e.target.closest("[data-rm-inc-ing]");
        if (rmInc) {
          filter.includeIngredients = filter.includeIngredients.filter((x) => x !== rmInc.dataset.rmIncIng);
          renderWorkbenchControls();
          onFilterChange(true);
          return;
        }
        const rmExc = e.target.closest("[data-rm-exc-ing]");
        if (rmExc) {
          filter.excludeIngredients = filter.excludeIngredients.filter((x) => x !== rmExc.dataset.rmExcIng);
          renderWorkbenchControls();
          onFilterChange(true);
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
        if (e.target.closest("#add-nutrient-rule-btn")) return addNutrientRule("protein", "ge", "");
        const rmRule = e.target.closest(".remove-rule-btn");
        if (rmRule) {
          const row = rmRule.closest(".n-rule-row");
          if (row) {
            filter.nutrientRules = filter.nutrientRules.filter((r) => r.id !== row.dataset.ruleId);
            renderWorkbenchControls();
            onFilterChange(true);
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
          onFilterChange(true);
        } else if (e.target.classList.contains("rule-op")) {
          rule.op = e.target.value;
          renderWorkbenchControls();
          onFilterChange(true);
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
        updateWorkbenchChromeAndStrip();
        onFilterChange(true);
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
        onFilterChange(true);
      });
    }

    return {
      getFilter: () => filter,
      setSearchText,
      resetAllFilters,
      renderWorkbenchControls,
      updateWorkbenchChromeAndStrip,
      getFilteredAndSortedCatalog,
      bindEvents,
    };
  }

  return { createWorkbenchController };
});
