"use strict";
// OpenPackagedFood M3 Expressive Detail Renderer (v3.1 — Emphasized Typography, Hero Bento & Tonal Tags)

(function (root, factory) {
  const api = factory();
  root.OPFDetail = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : window, function () {
  const TAB_CHECK_SVG =
    '<svg class="tab-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.2 4.2L19 7.5"/></svg>';

  const NUTRIENT_ORDER = [
    "energy_kj", "energy_kcal", "protein", "fat_total", "fat_saturated", "fat_trans",
    "fat_monounsaturated", "fat_polyunsaturated", "cholesterol", "carbs_available",
    "carbs_total", "sugars_total", "sugars_added", "sugar_alcohols", "dietary_fiber",
    "sodium", "salt_equivalent", "calcium", "iron", "potassium", "vitamin_a",
    "vitamin_c", "vitamin_d",
  ];
  const FAT_SUBS = new Set(["fat_saturated", "fat_trans", "fat_monounsaturated", "fat_polyunsaturated"]);
  const CARB_SUBS = new Set(["sugars_total", "sugars_added", "sugar_alcohols", "dietary_fiber"]);

  function formatNetContent(items) {
    if (!Array.isArray(items) || !items.length) return "";
    return items
      .map((nc) => `${nc.qualifier && nc.qualifier !== "=" ? nc.qualifier : ""}${nc.value}${nc.unit}`)
      .join(" / ");
  }

  function formatOrigin(origin) {
    if (!origin) return "";
    const parts = [];
    if (origin.country) parts.push(origin.country);
    if (origin.region) parts.push(origin.region);
    if (origin.raw_text && origin.raw_text !== origin.region) parts.push(`(${origin.raw_text})`);
    return parts.join(" · ");
  }

  function splitBrandHeadline(brand, dispName) {
    const b = String(brand || "").trim();
    const n = String(dispName || "").trim();
    if (!b) return { brand: "", headline: n };
    if (n.startsWith(b)) {
      const stripped = n.slice(b.length).replace(/^[\s·•-]+/, "").trim();
      return { brand: b, headline: stripped || n };
    }
    return { brand: b, headline: n };
  }

  function resolveTActiveBasis(obj, full) {
    if (obj && (obj.t_active_basis === "vintage_month" || obj.t_active_basis === "earliest_reported_at")) {
      return obj.t_active_basis;
    }
    const eid = obj && obj.edition_id;
    const ed =
      (obj && Array.isArray(obj.evidence) && obj) ||
      (full && Array.isArray(full.editions) && full.editions.find((x) => x.edition_id === eid)) ||
      null;
    if (ed && Array.isArray(ed.evidence)) {
      return ed.evidence.some((ev) => ev && ev.vintage_month) ? "vintage_month" : "earliest_reported_at";
    }
    return "earliest_reported_at";
  }

  function buildFormulaForCell(key, entry, ed, isPerUnit) {
    if (!entry || entry.basis === "reported") return "";
    const core = ed.core;
    if (!core || !core.nutrition_declared) return "";
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
      return `ƒ carbs_available = ${norm.nutrients.carbs_total.value} g − ${norm.nutrients.dietary_fiber.value} g = ${entry.value} g/${norm.basis}`;
    }

    const declRow = rows.find((r) => r.nutrient === key || (key.startsWith("energy_") && r.nutrient === "energy"));
    if (declRow) {
      return `ƒ ${key} = ${declRow.value} ${declRow.unit} × (100 ÷ ${panelBasis.value}${panelBasis.unit}) = ${entry.qualifier || ""}${entry.value} ${entry.unit}/${norm.basis}`;
    }
    return `ƒ ${key}: ${entry.qualifier || ""}${entry.value} ${entry.unit}`;
  }

  function createDetailRenderer(ctx) {
    const { $, t, esc, rel, renderSeal, renderResolutionBadge, renderStatusBadge, renderRevPill,
      pickLocalizedText, pickLocalizedProductName, resolveMediaRef, copyTextWithFeedback,
      getState, onSelectEdition, onReturnOverview, onMobileBack } = ctx;

    function renderApiView(item, compact) {
      return `<div class="detail-sections">${renderSectionCard(
        t("detail.tabApi"),
        `<div class="endpoint-bar"><span class="method">GET</span><a href="${esc(rel(item.compact_url))}" target="_blank" rel="noopener">${esc(item.compact_url)}</a></div>
         <div class="endpoint-bar"><span class="method">GET</span><a href="${esc(rel(item.full_url))}" target="_blank" rel="noopener">${esc(item.full_url)}</a></div>
         <pre class="json-view"><code>${esc(JSON.stringify(compact, null, 2))}</code></pre>`,
        `<button type="button" class="icon-copy-btn copy-json-btn"><span>${esc(t("detail.copyJsonBtn"))}</span></button>`
      )}</div>`;
    }

    function translateNutrient(key) {
      const label = t(`nutrients.${key}`);
      return label !== `nutrients.${key}` ? label : key;
    }

    function formatTActiveText(obj, full, shortMode = false) {
      const ym = (obj && obj.t_active) || "";
      if (!ym) return "";
      const basis = resolveTActiveBasis(obj, full);
      if (basis === "vintage_month") {
        return t(shortMode ? "detail.tActiveVintageShort" : "detail.tActiveVintage", { ym });
      }
      return t(shortMode ? "detail.tActiveReportedShort" : "detail.tActiveReported", { ym });
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

    function renderNutritionKpiStrip(ed) {
      const nutrients = (ed.normalized && ed.normalized.nutrients) || {};
      const carbsKey = nutrients.carbs_available ? "carbs_available" : "carbs_total";
      const kpiSpecs = [
        ["energy_kcal", t("detail.kpiEnergy"), true],
        ["protein", t("detail.kpiProtein"), false],
        ["fat_total", t("detail.kpiFat"), false],
        [carbsKey, nutrients.carbs_available ? t("detail.kpiCarbsAvail") : t("detail.kpiCarbsTotal"), false],
        ["sodium", t("detail.kpiSodium"), false],
      ];
      return `<div class="kpi-strip">${kpiSpecs
        .map(([key, label, isHero]) => {
          const entry = nutrients[key];
          return `<div class="kpi-tile${isHero ? " kpi-hero" : ""}"><span class="kpi-label">${esc(label)}</span><div class="kpi-value">${
            entry ? renderValueInner(key, entry, ed, false) : "—"
          }</div></div>`;
        })
        .join("")}</div>`;
    }

    function formatSpecialIndicatorValueHtml(s) {
      if (!s) return "";
      const unitHtml = s.unit ? `<span class="kpi-unit">${esc(s.unit)}</span>` : "";
      if (s.tolerance !== undefined && s.tolerance !== null && s.tolerance !== "") {
        return `${esc(s.value)}±${esc(s.tolerance)}${unitHtml}`;
      }
      if (s.value_max !== undefined && s.value_max !== null && s.value_max !== "") {
        return `${esc(s.value)}–${esc(s.value_max)}${unitHtml}`;
      }
      const q = s.qualifier && s.qualifier !== "=" ? s.qualifier : "";
      return `${esc(q)}${esc(s.value)}${unitHtml}`;
    }

    function formatSpecialIndicator(s) {
      if (!s) return "";
      const unitSuffix = s.unit ? ` ${s.unit}` : "";
      if (s.tolerance !== undefined && s.tolerance !== null && s.tolerance !== "") {
        return `${s.name} ${s.value}±${s.tolerance}${unitSuffix}`;
      }
      if (s.value_max !== undefined && s.value_max !== null && s.value_max !== "") {
        return `${s.name} ${s.value}–${s.value_max}${unitSuffix}`;
      }
      const q = s.qualifier && s.qualifier !== "=" ? s.qualifier : "";
      return `${s.name} ${q}${s.value}${unitSuffix}`;
    }

    function translateExemptionCategory(cat) {
      if (!cat) return "";
      const key = `nutritionExemptions.${cat}`;
      const label = t(key);
      return label !== key ? label : cat;
    }

    function renderNutritionSection(ed) {
      if (!ed.core || !ed.core.nutrition_declared) {
        const ex = (ed.core && ed.core.nutrition_exemption) || {};
        const inds = (ed.core && ed.core.special_indicators) || [];
        const hasMeta = Boolean(ex.legal_basis || ex.note);
        return `
          <div class="exemption-panel">
            <div class="exemption-head">
              <b>${esc(t("detail.nutritionExemptTitle"))}</b>
              ${ex.category ? `<span class="exemption-cat-pill">${esc(translateExemptionCategory(ex.category))}</span>` : ""}
            </div>
            <p class="exemption-desc">${esc(t("detail.nutritionExemptDesc"))}</p>
            ${
              hasMeta
                ? `<div class="exemption-meta">
                    ${ex.legal_basis ? `<span>${esc(t("detail.nutritionExemptBasisLabel"))}: <span class="mono">${esc(ex.legal_basis)}</span></span>` : ""}
                    ${ex.note ? `<span>${esc(ex.note)}</span>` : ""}
                  </div>`
                : ""
            }
          </div>
          ${
            inds.length
              ? `<div class="indicator-block"><span class="section-label">${esc(t("detail.metaSpecialIndicators"))}</span><div class="kpi-strip">${inds
                  .map((s) => `<div class="kpi-tile"><span class="kpi-label">${esc(s.name)}</span><div class="kpi-value">${formatSpecialIndicatorValueHtml(s)}</div></div>`)
                  .join("")}</div></div>`
              : ""
          }`;
      }
      const norm = ed.normalized;
      const nutrients = norm.nutrients || {};
      const pu = norm.per_unit;
      const orderedKeys = [
        ...NUTRIENT_ORDER.filter((k) => nutrients[k]),
        ...Object.keys(nutrients).filter((k) => !NUTRIENT_ORDER.includes(k)).sort(),
      ];
      const hasFat = Boolean(nutrients.fat_total);
      const hasCarb = Boolean(nutrients.carbs_total || nutrients.carbs_available);
      const rows = orderedKeys
        .map((k) => {
          const isSub = (hasFat && FAT_SUBS.has(k)) || (hasCarb && CARB_SUBS.has(k));
          return `<tr><td class="n-name${isSub ? " n-sub" : ""}">${esc(translateNutrient(k))}</td>${renderValueState(k, nutrients[k], ed, false)}${pu ? renderValueState(k, pu.nutrients[k], ed, true) : ""}</tr>`;
        })
        .join("");
      const puUnitText = pu ? pu.unit_amount.label || pu.unit_amount.value + pu.unit_amount.unit : "";
      const hasDerivedOrBound = orderedKeys.some((k) => nutrients[k] && nutrients[k].basis !== "reported") || Boolean(pu);

      return `
        ${renderNutritionKpiStrip(ed)}
        <div class="table-wrap">
          <table class="nutrient-table">
            <thead><tr><th><span>${esc(t("detail.colNutrient"))}</span></th><th><span>${esc(t("detail.colPerBasis", { basis: norm.basis }))}</span></th>${pu ? `<th><span>${esc(t("detail.colPerUnit", { unit: puUnitText }))}</span></th>` : ""}</tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <div class="formula-inspector" id="formula-inspector" hidden></div>
        ${hasDerivedOrBound ? `<div class="state-legend"><span>${esc(t("detail.legendDerived"))}</span><span>${esc(t("detail.legendBound"))}</span></div>` : ""}`;
    }

    function renderIngredientTree(nodes) {
      return `<ul class="ing-tree">${(nodes || [])
        .map(
          (n) => `<li>
            ${n.functional_class ? `<span class="meta-tag"><span>${esc(n.functional_class)}</span></span>` : ""}
            <span>${esc(n.name)}</span>
            ${n.qualifier ? `<span class="mono" style="font-size:0.86rem;color:var(--md-on-surface-variant);">(${esc(n.qualifier)})</span>` : ""}
            ${n.ins ? `<span class="meta-tag"><span>INS ${esc(n.ins)}</span></span>` : ""}
            ${n.children ? renderIngredientTree(n.children) : ""}
          </li>`
        )
        .join("")}</ul>`;
    }

    function formatAllergenLabel(code) {
      const translated = t(`allergens.${code}`);
      return translated !== `allergens.${code}` ? translated : code;
    }

    function renderIngredientHighlights(norm) {
      const alg = norm.allergens || {};
      const decl = alg.declared_contains || (!alg.inferred_from_ingredients ? alg.contains || [] : []);
      const inferred = (alg.inferred_from_ingredients || []).filter((x) => !(decl || []).includes(x));
      const may = alg.may_contain || [];
      const insList = norm.additives_ins || [];

      const rows = [];
      if (decl && decl.length) {
        rows.push(`<div class="summary-kv-row"><span class="summary-kv-label">${esc(t("detail.allergenDeclared"))}</span><span>${esc(decl.map(formatAllergenLabel).join(" · "))}</span></div>`);
      }
      if (inferred.length) {
        rows.push(`<div class="summary-kv-row"><span class="summary-kv-label">${esc(t("detail.allergenInferred"))}</span><span>${esc(inferred.map(formatAllergenLabel).join(" · "))}</span></div>`);
      }
      if (may.length) {
        rows.push(`<div class="summary-kv-row"><span class="summary-kv-label">${esc(t("detail.allergenMayContain"))}</span><span>${esc(may.map(formatAllergenLabel).join(" · "))}</span></div>`);
      }
      if (insList.length) {
        rows.push(`<div class="summary-kv-row"><span class="summary-kv-label">${esc(t("detail.additivePrefix"))}</span><div class="chip-cluster">${insList.map((c) => `<span class="meta-tag"><span>INS ${esc(c)}</span></span>`).join("")}</div></div>`);
      }
      return rows.length ? `<div class="summary-kv-list">${rows.join("")}</div>` : "";
    }

    function formatPartyRole(role) {
      const translated = t(`roles.${role}`);
      return translated !== `roles.${role}` ? translated : role;
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
              <span class="meta-tag"><span>${esc(eItem.track)}</span></span>
              <span>${esc(formatTActiveText(eItem, full, true))}</span>
            </span>
            <span style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
              ${renderStatusBadge(eItem.status)}
              ${isSameCore && full.editions.length > 1 ? `<span class="meta-tag"><span>${esc(t("detail.sameCoreBadge"))}</span></span>` : ""}
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

    function bindDetailEvents(item, compact, full, views) {
      const backBtn = $("#mobile-back-btn");
      if (backBtn) backBtn.onclick = () => onMobileBack();

      const overviewBtn = $("#return-overview-btn");
      if (overviewBtn) overviewBtn.onclick = () => onReturnOverview(item, compact, full);

      const tabs = $(".card-tabs");
      if (tabs) {
        tabs.onclick = (e) => {
          const b = e.target.closest(".card-tab");
          if (!b) return;
          document.querySelectorAll(".card-tab").forEach((tabEl) => tabEl.setAttribute("aria-selected", String(tabEl === b)));
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
          if (box) {
            box.hidden = false;
            box.innerHTML = `<span class="ink-formula">${esc(traceBtn.dataset.formula)}</span>`;
          }
          return;
        }
        const selectEdBtn = e.target.closest("[data-select-edition]");
        if (selectEdBtn && selectEdBtn.dataset.selectEdition) {
          onSelectEdition(item, compact, full, selectEdBtn.dataset.selectEdition);
          return;
        }
        const openExhibit = (btn, scrollInto) => {
          const stage = $("#ev-preview-stage");
          if (!stage || !btn) return;
          const isSameOpen = !stage.hidden && stage.dataset.activeSrc === btn.dataset.mediaSrc && !scrollInto;
          document.querySelectorAll(".preview-media-btn").forEach((b) => b.setAttribute("aria-pressed", "false"));
          if (isSameOpen) {
            stage.hidden = true;
            stage.dataset.activeSrc = "";
          } else {
            btn.setAttribute("aria-pressed", "true");
            stage.dataset.activeSrc = btn.dataset.mediaSrc;
            const capText = [btn.dataset.mediaSha ? `SHA-256 · ${btn.dataset.mediaSha}` : "", btn.dataset.mediaMeta || ""].filter(Boolean).join(" · ");
            stage.innerHTML = `<figure class="exhibit-mount"><a class="exhibit-img-link" href="${esc(btn.dataset.mediaSrc)}" target="_blank" rel="noopener"><img class="evidence-preview-img" decoding="sync" src="${esc(btn.dataset.mediaSrc)}" alt="${esc(t("detail.evidenceAlt"))}" /></a><figcaption class="exhibit-caption mono"><span>${esc(capText)}</span><a href="${esc(btn.dataset.mediaSrc)}" target="_blank" rel="noopener">WebP ↗</a></figcaption></figure>`;
            stage.hidden = false;
            if (scrollInto && typeof stage.scrollIntoView === "function") stage.scrollIntoView({ behavior: "smooth", block: "nearest" });
          }
        };
        if (e.target.closest("[data-open-evidence]")) {
          const tab0 = $("#tab-0");
          if (tab0 && tab0.getAttribute("aria-selected") !== "true") tab0.click();
          openExhibit(document.querySelector(".preview-media-btn"), true);
          return;
        }
        const mediaBtn = e.target.closest(".preview-media-btn");
        if (mediaBtn && mediaBtn.dataset.mediaSrc) openExhibit(mediaBtn, false);
      };
    }

    function renderDivergentOverview(item, compact, full) {
      const { redirectedFromId } = getState();
      const disamb = compact.disambiguation || { mode: "mixed", tracks_guide: [] };
      const common = compact.common_summary || {};
      const guideByTrack = {};
      (disamb.tracks_guide || []).forEach((g) => { guideByTrack[g.track] = g; });

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
          const vNet = formatNetContent(v.net_content);
          return `<div class="variant-card">
            <div>
              <div class="variant-card-head">
                <b>${esc(v.track)}</b>
                ${renderSeal(v.evidence_level)}
              </div>
              <div class="variant-card-meta">
                ${vNet ? `<span class="meta-tag"><span>${esc(vNet)}</span></span>` : ""}
                <span class="meta-tag"><span>${esc(formatTActiveText(v, full, true))}</span></span>
                ${v.packaging_code ? `<span class="meta-tag"><span>${esc(v.packaging_code)}</span></span>` : ""}
                ${v.quality_grade ? `<span class="meta-tag"><span>${esc(v.quality_grade)}</span></span>` : ""}
              </div>
              ${originStr ? `<p class="variant-card-desc">${esc(t("detail.metaOrigin"))}: ${esc(originStr)}</p>` : ""}
              ${(v.special_indicators || []).length ? `<p class="variant-card-desc mono">${esc(v.special_indicators.map(formatSpecialIndicator).join(" · "))}</p>` : ""}
              ${partiesLine ? `<p class="variant-card-desc">${esc(partiesLine)}</p>` : ""}
              ${discText ? `<p class="variant-card-desc">${esc(discText)}</p>` : ""}
            </div>
            <button type="button" class="chip variant-pick-btn" data-select-edition="${esc(v.edition_id)}"><span>${esc(t("detail.selectVariantBtn"))}</span></button>
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
            ? ` <span class="meta-tag"><span>${esc(t("detail.partialDeclared", { declared: r.declared_in_variants, total: r.total_variants }))}</span></span>`
            : "";
          return `<tr><td class="n-name">${esc(translateNutrient(k))}${partialTag}</td><td class="n-val">${esc(valText)} <span class="unit">${esc(r.unit)}</span></td></tr>`;
        })
        .join("");

      const algUnion = common.allergens_union || { contains: [], may_contain: [] };
      const containsText = (algUnion.contains || []).length ? algUnion.contains.map(formatAllergenLabel).join(" · ") : t("detail.noneDeclared");
      const mayText = (algUnion.may_contain || []).length ? algUnion.may_contain.map(formatAllergenLabel).join(" · ") : t("detail.noneDeclared");

      const diffChips = (common.differing_fields || [])
        .map((f) => {
          const lbl = t(`diffFields.${f}`);
          return `<span class="meta-tag"><span>${esc(lbl !== `diffFields.${f}` ? lbl : f)}</span></span>`;
        })
        .join(" ");

      const viewOverview = `<div class="detail-sections">
        ${renderSectionCard(
          t("detail.divergentOverviewTitle"),
          `<p class="lead" style="margin-bottom:12px;">${esc(t("detail.divergentOverviewLead"))}</p>
           ${disambInstr ? `<div class="archival-banner"><span>${esc(disambInstr)}</span></div>` : ""}
           <div class="variant-grid">${variantCards}</div>`
        )}
        ${renderSectionCard(
          t("detail.commonSummaryTitle"),
          `${diffChips ? `<div style="margin-bottom:12px;"><span class="section-label">${esc(t("detail.differingFieldsLabel"))}</span><div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">${diffChips}</div></div>` : ""}
           <div class="archival-banner emphasis"><span>${esc(t("detail.rangeWarningBanner"))}</span></div>
           ${
             common.basis === "mixed"
               ? `<div class="archival-banner"><span>${esc(t("detail.mixedBasisNotice"))}</span></div>`
               : rangeKeys.length === 0
                 ? `<div class="archival-banner"><span>${esc(t("detail.allVariantsExemptNotice"))}</span></div>`
                 : `<div class="table-wrap"><table class="nutrient-table"><thead><tr><th><span>${esc(t("detail.colNutrient"))}</span></th><th><span>${esc(t("detail.colRangePerBasis", { basis: common.basis }))}</span></th></tr></thead><tbody>${rangeRows}</tbody></table></div>`
           }
           <div class="allergen-union-grid">
             <div class="allergen-union-box"><span class="section-label">${esc(t("detail.allergenUnionContains"))}</span><div>${esc(containsText)}</div></div>
             <div class="allergen-union-box"><span class="section-label">${esc(t("detail.allergenUnionMayContain"))}</span><div>${esc(mayText)}</div></div>
           </div>`
        )}
      </div>`;

      const views = [viewOverview, renderApiView(item, compact)];
      const dispName = pickLocalizedProductName(item);
      const { brand: bEyebrow, headline } = splitBrandHeadline(compact.brand, dispName);
      const activeCount = (compact.active_edition_ids || []).length;
      const commonNet = formatNetContent(common.net_content_values);

      $("#detail").innerHTML = `
        <div class="mobile-back-bar"><button type="button" class="chip" id="mobile-back-btn"><span class="ink-ui">${esc(t("detail.backToCatalog"))}</span></button></div>
        ${redirectedFromId ? `<div class="archival-banner emphasis"><span>${esc(t("detail.redirectNotice", { from: redirectedFromId, to: compact.active_edition_ids[0] || item.id }))}</span></div>` : ""}
        <div class="card-topbar">
          <div class="call-number-block">
            <strong>${esc(item.id)}</strong>
            <button type="button" class="icon-copy-btn copy-id-btn" data-copy-text="${esc(item.id)}"><span>${esc(t("detail.copyIdBtn"))}</span></button>
            ${renderResolutionBadge(compact.resolution, true)}
          </div>
          ${renderSeal(compact.evidence_summary && compact.evidence_summary.highest_active)}
        </div>
        <hr class="title-rule" />
        <div class="card-title-block">
          ${bEyebrow ? `<span class="brand-eyebrow">${esc(bEyebrow)}</span>` : ""}
          <h2>${esc(headline)}</h2>
          <div class="card-imprint">
            ${commonNet ? `<span>${esc(t("detail.netContentLabel"))} <b>${esc(commonNet)}</b></span><span class="imprint-dot" aria-hidden="true">·</span>` : ""}
            <span>${esc(t("search.activeEditionsCount", { count: activeCount }))}</span>
          </div>
        </div>
        <div class="card-tabs" role="tablist">
          <button type="button" class="card-tab" role="tab" id="tab-0" aria-controls="card-body" aria-selected="true" data-tab="0">${TAB_CHECK_SVG}<span>${esc(t("detail.tabOverview"))}</span></button>
          <button type="button" class="card-tab" role="tab" id="tab-1" aria-controls="card-body" aria-selected="false" data-tab="1">${TAB_CHECK_SVG}<span>${esc(t("detail.tabApi"))}</span></button>
        </div>
        <div id="card-body" role="tabpanel" aria-labelledby="tab-0">${views[0]}</div>`;

      bindDetailEvents(item, compact, full, views);
    }

    function resolveDefaultEdition(compact, full, selectedEditionId) {
      if (selectedEditionId) {
        const hit = full.editions.find((e) => e.edition_id === selectedEditionId);
        if (hit) return hit;
      }
      const activeIds = compact.active_edition_ids || [];
      if (activeIds.length) {
        const hit = full.editions.find((e) => e.edition_id === activeIds[activeIds.length - 1]);
        if (hit) return hit;
      }
      const nonRetracted = full.editions.filter((e) => e.status !== "retracted");
      return (nonRetracted.length ? nonRetracted : full.editions).at(-1);
    }

    function renderCatalogCard(item, compact, full) {
      const { selectedEditionId, redirectedFromId } = getState();
      if (compact.resolution === "divergent" && !selectedEditionId) {
        renderDivergentOverview(item, compact, full);
        return;
      }

      const ed = resolveDefaultEdition(compact, full, selectedEditionId);
      const core = ed.core;
      const attrs = ed.attributes;
      const norm = ed.normalized;
      const dispName = pickLocalizedProductName(item, attrs);
      const { brand: bEyebrow, headline } = splitBrandHeadline(attrs.brand, dispName);
      const isUnifiedUniform = compact.resolution === "uniform" && !selectedEditionId;

      const declSet = new Set(((core.nutrition_declared && core.nutrition_declared.rows) || []).map((r) => r.nutrient));
      const declaredRows = core.nutrition_declared
        ? (core.nutrition_declared.rows || [])
            .map((r) => {
              const isSub = (declSet.has("fat_total") && FAT_SUBS.has(r.nutrient)) || ((declSet.has("carbs_total") || declSet.has("carbs_available")) && CARB_SUBS.has(r.nutrient));
              return `<tr><td class="n-name${isSub ? " n-sub" : ""}">${esc(translateNutrient(r.nutrient))}</td><td class="n-val"><span class="num">${esc((r.qualifier && r.qualifier !== "=" ? r.qualifier + " " : "") + r.value)}</span><span class="unit">${esc(r.unit)}</span></td><td class="n-val">${r.nrv_pct !== undefined ? esc(r.nrv_pct) + "%" : "—"}</td></tr>`;
            })
            .join("")
        : "";

      const treesToRender = ed.ingredients_tree_annotated || core.ingredients_tree || [];
      const multiLangIng = (attrs.ingredients_text || []).length > 1;
      const ingredientsBody = `
        ${(attrs.ingredients_text || [])
          .map(
            (tItem) =>
              `<div class="verbatim-box"><span class="verbatim-ink">${esc(tItem.text)}</span>${multiLangIng ? ` <span class="meta-tag"><span>${esc(tItem.lang)}</span></span>` : ""}</div>`
          )
          .join("")}
        ${attrs.allergens_raw_text ? `<div class="verbatim-box" style="font-size:0.98rem;color:var(--md-on-surface-variant);"><span class="verbatim-ink">${esc(attrs.allergens_raw_text)}</span></div>` : ""}
        ${renderIngredientHighlights(norm)}
        ${
          treesToRender.length
            ? `<details class="clean-fold">
                <summary><span>${esc(t("detail.ingTreeToggle"))}</span></summary>
                <div class="fold-body">${treesToRender.map((tItem) => renderIngredientTree(tItem.nodes)).join("")}</div>
              </details>`
            : ""
        }`;

      const partiesList = isUnifiedUniform && Array.isArray(compact.parties_summary) ? compact.parties_summary : attrs.parties || [];
      const originsList = isUnifiedUniform && Array.isArray(compact.origins_summary) ? compact.origins_summary : attrs.origin ? [attrs.origin] : [];
      const originDisplay = originsList.map(formatOrigin).filter(Boolean).join(" / ");
      const specialInds = isUnifiedUniform && Array.isArray(compact.special_indicators) ? compact.special_indicators : core.special_indicators || [];
      const qualityGradeDisplay = (isUnifiedUniform && compact.quality_grade) || attrs.quality_grade || "";

      const partiesRowsHtml = partiesList
        .map(
          (p) =>
            `<dt>${esc(formatPartyRole(p.role))}</dt><dd>${esc(p.name)}${p.plant_code ? ` <span class="meta-tag"><span>${esc(p.plant_code)}</span></span>` : ""}${p.license ? ` <span class="mono" style="font-size:0.88rem;color:var(--md-on-surface-variant);">(${esc(p.license)})</span>` : ""}</dd>`
        )
        .join("");

      const photoEvidences = (ed.evidence || [])
        .map((ev, idx) => {
          const rawSha = ev.cropped_sha256 || (ev.media_ref && (ev.media_ref.split("/").pop() || "")) || "";
          const shortSha = rawSha.length >= 20 ? `${rawSha.slice(0, 10)}…${rawSha.slice(-8)}` : rawSha;
          const meta = [ev.region, ev.vintage_month || ev.reported_at].filter(Boolean).join(" · ");
          return { ev, idx, src: resolveMediaRef(ev.media_ref), shortSha, meta };
        })
        .filter((x) => Boolean(x.src));
      const photoGalleryHtml = photoEvidences.length
        ? `<div class="photo-actions-row">${photoEvidences
            .map(
              ({ src, shortSha, meta }, i) =>
                `<button type="button" class="chip micro preview-media-btn" aria-pressed="false" data-media-src="${esc(src)}" data-media-sha="${esc(shortSha)}" data-media-meta="${esc(meta)}"><span>${esc(t("detail.previewCrop"))}${photoEvidences.length > 1 ? ` ${i + 1}` : ""}</span></button>`
            )
            .join("")}</div><div class="photo-preview-stage" id="ev-preview-stage" hidden></div>`
        : "";

      const complianceBody = `
        <dl class="meta-dl">
          <dt>${esc(t("detail.metaProfile"))}</dt><dd class="mono">${esc(core.regulatory_profile)}</dd>
          ${originDisplay ? `<dt>${esc(t("detail.metaOrigin"))}</dt><dd>${esc(originDisplay)}</dd>` : ""}
          ${attrs.product_standard ? `<dt>${esc(t("detail.metaStandard"))}</dt><dd class="mono">${esc(attrs.product_standard.join(" · "))}</dd>` : ""}
          ${attrs.declared_category ? `<dt>${esc(t("detail.metaCategory"))}</dt><dd>${esc(attrs.declared_category)}</dd>` : ""}
          ${qualityGradeDisplay ? `<dt>${esc(t("detail.metaQualityGrade"))}</dt><dd>${esc(qualityGradeDisplay)}</dd>` : ""}
          ${attrs.shelf_life ? `<dt>${esc(t("detail.metaShelfLife"))}</dt><dd>${esc(attrs.shelf_life.value)} ${esc(attrs.shelf_life.unit)}</dd>` : ""}
          ${attrs.storage_text ? `<dt>${esc(t("detail.metaStorage"))}</dt><dd>${esc(attrs.storage_text)}</dd>` : ""}
          ${attrs.usage_text ? `<dt>${esc(t("detail.metaUsage"))}</dt><dd>${esc(attrs.usage_text)}</dd>` : ""}
          ${(attrs.claims_text || []).length ? `<dt>${esc(t("detail.metaClaims"))}</dt><dd>${esc(attrs.claims_text.join(" · "))}</dd>` : ""}
          ${specialInds.length ? `<dt>${esc(t("detail.metaSpecialIndicators"))}</dt><dd class="mono">${esc(specialInds.map(formatSpecialIndicator).join(" · "))}</dd>` : ""}
          ${partiesRowsHtml}
        </dl>
        ${photoGalleryHtml}`;

      const revisionsHtml = (ed.revisions || [])
        .map((r) => {
          const pathsSummary = (r.patch || []).map((op) => `${op.op} ${op.path}`).join(", ");
          return `<div class="revision-item">
            <div class="ulid-head mono">
              ${renderRevPill(r.rev)}
              <span>${esc(t(`revisionKinds.${r.kind}`))} · ${esc(r.author)} · ${esc(r.created_at)}</span>
            </div>
            ${r.reason ? `<div style="margin-top:4px;">${esc(r.reason)}</div>` : ""}
            ${pathsSummary ? `<div class="mono" style="margin-top:4px;font-size:0.84rem;color:var(--md-on-surface-variant);">${esc(pathsSummary)}</div>` : ""}
          </div>`;
        })
        .join("");

      const supersedesChips = [
        ...(ed.supersedes || []).map((sid) => `<button type="button" class="chip mono micro jump-chip" data-select-edition="${esc(sid)}"><span>${esc(t("detail.supersedesPrefix"))}: ${esc(sid)}</span></button>`),
        ...(ed.superseded_by || []).map((sid) => `<button type="button" class="chip mono micro jump-chip" data-select-edition="${esc(sid)}"><span>${esc(t("detail.supersededByPrefix"))}: ${esc(sid)}</span></button>`),
      ].join(" ");

      const flagsHtml = (ed.quality_flags || []).length
        ? `<div style="margin-top:12px;">${ed.quality_flags.map((f) => `<div class="note-item"><b>${esc(f.code)}</b> (${esc(f.field)}) — ${esc(f.detail)}</div>`).join("")}</div>`
        : "";

      const editionsCountHint = full.editions && full.editions.length > 1 ? ` (${full.editions.length})` : "";
      const provenanceFold = `<details class="clean-fold" style="margin-top:24px;">
        <summary><span>${esc(t("detail.railProvenance"))}${esc(editionsCountHint)}</span></summary>
        <div class="fold-body">
          <div class="edition-timeline">${renderEditionTimelineHtml(full, ed.edition_id)}</div>
          ${supersedesChips ? `<div class="chip-cluster" style="margin-bottom:8px;">${supersedesChips}</div>` : ""}
          ${ed.lifecycle ? `<div class="archival-banner">${esc(t("detail.lifecycleOverridePrefix"))}: <b class="mono">${esc(ed.lifecycle.state)}</b> — ${esc(ed.lifecycle.reason)}</div>` : ""}
          <div class="chip-cluster" style="margin-bottom:8px;">
            <span class="meta-tag"><span>${esc(t("detail.coreFpPrefix"))}: ${esc(ed.core_fingerprint.slice(0, 22))}…</span></span>
            <span class="meta-tag"><span>${esc(t("detail.labelFpPrefix"))}: ${esc(ed.label_fingerprint.slice(0, 22))}…</span></span>
          </div>
          ${revisionsHtml ? `<div class="revision-list">${revisionsHtml}</div>` : ""}
          ${flagsHtml}
        </div>
      </details>`;

      const viewMain = `<div class="detail-sections">
        ${renderSectionCard(t("detail.railNormalized"), renderNutritionSection(ed), `<span class="meta-tag"><span>${esc(norm.basis)}</span></span>`)}
        ${renderSectionCard(t("detail.railIngredients"), ingredientsBody)}
        ${renderSectionCard(t("detail.railCompliance"), complianceBody)}
        ${provenanceFold}
      </div>`;

      const basisLabelSuffix = attrs.serving_size_label ? " / " + attrs.serving_size_label : "";
      const declaredSectionBody = core.nutrition_declared
        ? `<p class="lead" style="margin-bottom:12px;">${esc(
            t("detail.declaredIntro", { value: core.nutrition_declared.basis.value, unit: core.nutrition_declared.basis.unit, labelSuffix: basisLabelSuffix })
          )}</p>
           <div class="table-wrap"><table class="nutrient-table"><thead><tr><th><span>${esc(t("detail.colNutrient"))}</span></th><th><span>${esc(t("detail.declaredColVal"))}</span></th><th><span>${esc(t("detail.declaredColNrv"))}</span></th></tr></thead><tbody>${declaredRows}</tbody></table></div>`
        : renderNutritionSection(ed);
      const viewDeclared = `<div class="detail-sections">${renderSectionCard(t("detail.tabDeclared"), declaredSectionBody)}</div>`;

      const views = [viewMain, viewDeclared, renderApiView(item, compact)];
      let topBanners = "";
      if (redirectedFromId) {
        topBanners += `<div class="archival-banner emphasis"><span>${esc(t("detail.redirectNotice", { from: redirectedFromId, to: ed.edition_id }))}</span></div>`;
      }
      if (compact.resolution === "divergent") {
        topBanners += `<div class="mode-switch-bar">
          <button type="button" class="chip" id="return-overview-btn"><span>${esc(t("detail.returnToDivergentOverview"))}</span></button>
          <span class="meta-tag"><span>${esc(ed.track)}</span></span>
        </div>`;
      } else if (compact.resolution === "uniform") {
        topBanners += `<div class="archival-banner"><span>${esc(t("detail.uniformBanner", { count: (compact.active_edition_ids || []).length }))}</span>${
          selectedEditionId ? ` <button type="button" class="chip micro" id="return-overview-btn" style="margin-left:8px;"><span>${esc(t("detail.returnToUniformOverview"))}</span></button>` : ""
        }</div>`;
      } else if (compact.resolution === "inactive") {
        topBanners += `<div class="archival-banner"><span>${esc(t("detail.inactiveBanner"))}</span></div>`;
      }

      const netStr = formatNetContent(core.net_content);
      $("#detail").innerHTML = `
        <div class="mobile-back-bar"><button type="button" class="chip" id="mobile-back-btn"><span class="ink-ui">${esc(t("detail.backToCatalog"))}</span></button></div>
        ${topBanners}
        <div class="card-topbar">
          <div class="call-number-block">
            <strong>${esc(item.id)}</strong>
            <button type="button" class="icon-copy-btn copy-id-btn" data-copy-text="${esc(item.id)}"><span>${esc(t("detail.copyIdBtn"))}</span></button>
            ${ed.status !== "active" ? renderStatusBadge(ed.status) : ""}
          </div>
          ${photoEvidences.length ? `<button type="button" class="seal-trigger" data-open-evidence="1">${renderSeal(ed.evidence_level)}</button>` : renderSeal(ed.evidence_level)}
        </div>
        <hr class="title-rule" />
        <div class="card-title-block">
          ${bEyebrow ? `<span class="brand-eyebrow">${esc(bEyebrow)}</span>` : ""}
          <h2>${esc(headline)}</h2>
          <div class="card-imprint">
            ${netStr ? `<span class="imprint-item">${esc(t("detail.netContentLabel"))} <b>${esc(netStr)}</b></span><span class="imprint-dot" aria-hidden="true">·</span>` : ""}
            <span class="imprint-item">${esc(core.regulatory_profile)}</span>
            <span class="imprint-dot" aria-hidden="true">·</span>
            <span class="imprint-item">${esc(formatTActiveText(ed, full, true))}</span>
          </div>
        </div>
        <div class="card-tabs" role="tablist">
          <button type="button" class="card-tab" role="tab" id="tab-0" aria-controls="card-body" aria-selected="true" data-tab="0">${TAB_CHECK_SVG}<span>${esc(t("detail.tabNormalized"))}</span></button>
          <button type="button" class="card-tab" role="tab" id="tab-1" aria-controls="card-body" aria-selected="false" data-tab="1">${TAB_CHECK_SVG}<span>${esc(t("detail.tabDeclared"))}</span></button>
          <button type="button" class="card-tab" role="tab" id="tab-2" aria-controls="card-body" aria-selected="false" data-tab="2">${TAB_CHECK_SVG}<span>${esc(t("detail.tabApi"))}</span></button>
        </div>
        <div id="card-body" role="tabpanel" aria-labelledby="tab-0">${views[0]}</div>`;

      bindDetailEvents(item, compact, full, views);
    }

    return {
      translateNutrient,
      formatTActiveText,
      renderCatalogCard,
      renderDivergentOverview,
    };
  }

  return { createDetailRenderer };
});
