"use strict";
// OpenPackagedFood Catalog Card & Divergent Variant Detail Renderer

(function (root, factory) {
  const api = factory();
  root.OPFDetail = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : window, function () {
  const NUTRIENT_ORDER = [
    "energy_kj", "energy_kcal", "protein", "fat_total", "fat_saturated", "fat_trans",
    "fat_monounsaturated", "fat_polyunsaturated", "cholesterol", "carbs_available",
    "carbs_total", "sugars_total", "sugars_added", "sugar_alcohols", "dietary_fiber",
    "sodium", "salt_equivalent", "calcium", "iron", "potassium", "vitamin_a",
    "vitamin_c", "vitamin_d",
  ];

  function formatNetContent(items) {
    if (!Array.isArray(items) || !items.length) return "—";
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
      return `ƒ carbs_available = ${norm.nutrients.carbs_total.value} g (total carbs) − ${norm.nutrients.dietary_fiber.value} g (fiber) = ${entry.value} g/${norm.basis}`;
    }

    const declRow = rows.find((r) => r.nutrient === key || (key.startsWith("energy_") && r.nutrient === "energy"));
    if (declRow) {
      return `ƒ ${key} = ${declRow.value} ${declRow.unit} × (100 ÷ ${panelBasis.value}${panelBasis.unit}) = ${entry.qualifier || ""}${entry.value} ${entry.unit}/${norm.basis}`;
    }
    return `ƒ ${key}: ${entry.qualifier || ""}${entry.value} ${entry.unit}`;
  }

  function createDetailRenderer(ctx) {
    const {
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
      getState,
      onSelectEdition,
      onReturnOverview,
      onMobileBack,
    } = ctx;

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
        ["energy_kcal", t("detail.kpiEnergy")],
        ["protein", t("detail.kpiProtein")],
        ["fat_total", t("detail.kpiFat")],
        [carbsKey, nutrients.carbs_available ? t("detail.kpiCarbsAvail") : t("detail.kpiCarbsTotal")],
        ["sodium", t("detail.kpiSodium")],
      ];
      return `<div class="kpi-strip">${kpiSpecs
        .map(([key, label]) => {
          const entry = nutrients[key];
          return `<div class="kpi-tile"><span class="kpi-label">${esc(label)}</span><div class="kpi-value">${
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
      return label !== key ? `${label} (${cat})` : cat;
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
                    ${ex.legal_basis ? `<span><b>${esc(t("detail.nutritionExemptBasisLabel"))}:</b> <span class="mono">${esc(ex.legal_basis)}</span></span>` : ""}
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
      const rows = orderedKeys
        .map((k) => `<tr>
          <td class="n-name"><b>${esc(translateNutrient(k))}</b><small>${esc(k)}</small></td>
          ${renderValueState(k, nutrients[k], ed, false)}
          ${pu ? renderValueState(k, pu.nutrients[k], ed, true) : ""}
        </tr>`)
        .join("");
      const puUnitText = pu ? pu.unit_amount.label || pu.unit_amount.value + pu.unit_amount.unit : "";

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
              <span class="chip mono" title="${esc(formatTActiveText(eItem, full, false))}">${esc(formatTActiveText(eItem, full, true))}</span>
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
          if (box) box.textContent = traceBtn.dataset.formula;
          return;
        }
        const selectEdBtn = e.target.closest("[data-select-edition]");
        if (selectEdBtn && selectEdBtn.dataset.selectEdition) {
          onSelectEdition(item, compact, full, selectEdBtn.dataset.selectEdition);
          return;
        }
        const mediaBtn = e.target.closest(".preview-media-btn");
        if (mediaBtn && mediaBtn.dataset.targetId) {
          const holder = document.getElementById(mediaBtn.dataset.targetId);
          if (holder) {
            if (holder.hidden) {
              holder.innerHTML = `<img class="evidence-preview-img" loading="lazy" decoding="async" src="${esc(mediaBtn.dataset.mediaSrc)}" alt="${esc(t("detail.evidenceAlt"))}" />`;
              holder.hidden = false;
            } else {
              holder.hidden = true;
            }
          }
        }
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
          return `<div class="variant-card">
            <div>
              <div class="variant-card-head">
                <span class="ulid-head mono"><span class="ulid-code">${esc(v.edition_id)}</span> ${renderRevPill(v.rev)}</span>
                ${renderSeal(v.evidence_level)}
              </div>
              <div class="variant-card-meta">
                <span class="chip mono">${esc(v.track)}</span>
                <span class="chip mono">${esc(formatNetContent(v.net_content))}</span>
                <span class="chip mono" title="${esc(formatTActiveText(v, full, false))}">${esc(formatTActiveText(v, full, true))}</span>
                ${v.packaging_code ? `<span class="chip mono">${esc(v.packaging_code)}</span>` : ""}
                ${v.quality_grade ? `<span class="chip mono">${esc(v.quality_grade)}</span>` : ""}
              </div>
              ${originStr ? `<p class="variant-card-desc">${esc(t("detail.metaOrigin"))}: ${esc(originStr)}</p>` : ""}
              ${(v.special_indicators || []).length ? `<p class="variant-card-desc mono">${esc(t("detail.metaSpecialIndicators"))}: ${esc(v.special_indicators.map(formatSpecialIndicator).join(" · "))}</p>` : ""}
              ${partiesLine ? `<p class="variant-card-desc">${esc(partiesLine)}</p>` : ""}
              ${discText ? `<p class="variant-card-desc">${esc(discText)}</p>` : ""}
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
          return `<tr><td class="n-name"><b>${esc(translateNutrient(k))}</b><small>${esc(k)}</small>${partialTag}</td><td class="n-val">${esc(valText)} <span class="unit">${esc(r.unit)}</span></td></tr>`;
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
           <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;"><span class="chip mono">${esc(t(`disambiguationModes.${disamb.mode}`))}</span></div>
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
               : rangeKeys.length === 0
                 ? `<div class="archival-banner">${esc(t("detail.allVariantsExemptNotice"))}</div>`
                 : `<div class="table-wrap"><table class="nutrient-table"><thead><tr><th>${esc(t("detail.colNutrient"))}</th><th>${esc(t("detail.colRangePerBasis", { basis: common.basis }))}</th></tr></thead><tbody>${rangeRows}</tbody></table></div>`
           }
           <div class="allergen-union-grid">
             <div class="allergen-union-box"><span class="section-label">${esc(t("detail.allergenUnionContains"))}</span><div style="display:flex;gap:6px;flex-wrap:wrap;">${containsChips}</div></div>
             <div class="allergen-union-box"><span class="section-label">${esc(t("detail.allergenUnionMayContain"))}</span><div style="display:flex;gap:6px;flex-wrap:wrap;">${mayChips}</div></div>
           </div>
           ${(common.additives_ins_union || []).length ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:12px;">${common.additives_ins_union.map((c) => `<span class="chip mono">${esc(t("detail.additivePrefix"))} ${esc(c)}</span>`).join("")}</div>` : ""}`
        )}
        ${renderSectionCard(t("detail.railProvenance"), `<div class="edition-timeline">${renderEditionTimelineHtml(full, "")}</div>`)}
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
        <div class="mobile-back-bar"><button type="button" class="chip" id="mobile-back-btn">${esc(t("detail.backToCatalog"))}</button></div>
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
      const isUnifiedUniform = compact.resolution === "uniform" && !selectedEditionId;

      const declaredRows = core.nutrition_declared
        ? (core.nutrition_declared.rows || [])
            .map(
              (r) => `<tr>
            <td class="n-name"><b>${esc(translateNutrient(r.nutrient))}</b><small>${esc(r.nutrient)}</small></td>
            <td class="n-val">${esc((r.qualifier && r.qualifier !== "=" ? r.qualifier + " " : "") + r.value)} <span class="unit">${esc(r.unit)}</span></td>
            <td class="n-val">${r.nrv_pct !== undefined ? esc(r.nrv_pct) + "%" : "—"}</td>
          </tr>`
            )
            .join("")
        : "";

      const treesToRender = ed.ingredients_tree_annotated || core.ingredients_tree || [];
      const partiesList = isUnifiedUniform && Array.isArray(compact.parties_summary) ? compact.parties_summary : attrs.parties || [];
      const originsList = isUnifiedUniform && Array.isArray(compact.origins_summary) ? compact.origins_summary : attrs.origin ? [attrs.origin] : [];
      const originDisplay = originsList.map(formatOrigin).filter(Boolean).join(" / ");

      const revisionsHtml = (ed.revisions || [])
        .map((r) => {
          const pathsSummary = (r.patch || []).map((op) => `${op.op} ${op.path}`).join(", ");
          return `<div class="revision-item">
            <div class="ulid-head mono">
              ${renderRevPill(r.rev)}
              ${r.provenance ? `<span class="chip mono">${esc(r.provenance)}</span>` : ""}
              <span>${esc(t(`revisionKinds.${r.kind}`))} · ${esc(r.author)} · ${esc(r.created_at)}</span>
            </div>
            ${r.reason ? `<div style="margin-top:4px;">${esc(r.reason)}</div>` : ""}
            ${pathsSummary ? `<div class="mono" style="margin-top:4px;font-size:0.74rem;color:var(--md-on-surface-variant);">${esc(t("detail.patchPathsLabel"))}: ${esc(pathsSummary)}</div>` : ""}
          </div>`;
        })
        .join("");

      const supersedesChips = [
        ...(ed.supersedes || []).map((sid) => `<button type="button" class="chip mono jump-chip" data-select-edition="${esc(sid)}">${esc(t("detail.supersedesPrefix"))}: ${esc(sid)}</button>`),
        ...(ed.superseded_by || []).map((sid) => `<button type="button" class="chip mono jump-chip" data-select-edition="${esc(sid)}">${esc(t("detail.supersededByPrefix"))}: ${esc(sid)}</button>`),
      ].join(" ");

      const ingredientsBody = `
        ${(attrs.ingredients_text || []).map((tItem) => `<div class="verbatim-box">${esc(tItem.text)} <span class="chip mono">${esc(tItem.lang)}</span></div>`).join("")}
        <div style="margin-bottom:10px">${treesToRender.map((tItem) => renderIngredientTree(tItem.nodes)).join("")}</div>
        ${attrs.allergens_raw_text ? `<div class="verbatim-box">${esc(t("detail.metaAllergensRaw"))}: ${esc(attrs.allergens_raw_text)}</div>` : ""}
        <div class="chip-cluster">
          ${(norm.additives_ins || []).map((code) => `<span class="chip mono">${esc(t("detail.additivePrefix"))} ${esc(code)}</span>`).join("")}
          ${renderAllergensBadges(norm)}
        </div>`;

      const specialInds = isUnifiedUniform && Array.isArray(compact.special_indicators) ? compact.special_indicators : core.special_indicators || [];
      const qualityGradeDisplay = (isUnifiedUniform && compact.quality_grade) || attrs.quality_grade || "";

      const complianceBody = `
        <dl class="meta-dl">
          <dt>${esc(t("detail.metaProfile"))}</dt><dd class="mono">${esc(core.regulatory_profile)}</dd>
          ${isUnifiedUniform && compact.active_tracks ? `<dt>${esc(t("detail.activeTracksLabel"))}</dt><dd class="mono">${esc(compact.active_tracks.join(" · "))}</dd>` : `<dt>${esc(t("detail.trackLabel"))}</dt><dd class="mono">${esc(ed.track)}</dd>`}
          ${originDisplay ? `<dt>${esc(t("detail.metaOrigin"))}</dt><dd>${esc(originDisplay)}</dd>` : ""}
          ${attrs.product_standard ? `<dt>${esc(t("detail.metaStandard"))}</dt><dd class="mono">${esc(attrs.product_standard.join(" · "))}</dd>` : ""}
          ${attrs.declared_category ? `<dt>${esc(t("detail.metaCategory"))}</dt><dd>${esc(attrs.declared_category)}</dd>` : ""}
          ${qualityGradeDisplay ? `<dt>${esc(t("detail.metaQualityGrade"))}</dt><dd>${esc(qualityGradeDisplay)}</dd>` : ""}
          ${attrs.shelf_life ? `<dt>${esc(t("detail.metaShelfLife"))}</dt><dd class="mono">${esc(attrs.shelf_life.value)} ${esc(attrs.shelf_life.unit)}</dd>` : ""}
          ${attrs.storage_text ? `<dt>${esc(t("detail.metaStorage"))}</dt><dd>${esc(attrs.storage_text)}</dd>` : ""}
          ${attrs.usage_text ? `<dt>${esc(t("detail.metaUsage"))}</dt><dd>${esc(attrs.usage_text)}</dd>` : ""}
          ${attrs.packaging_code ? `<dt>${esc(t("detail.metaPkgCode"))}</dt><dd class="mono">${esc(attrs.packaging_code)}</dd>` : ""}
          ${attrs.lot_code_rule ? `<dt>${esc(t("detail.metaLotRule"))}</dt><dd>${esc(attrs.lot_code_rule)}</dd>` : ""}
          ${(attrs.claims_text || []).length ? `<dt>${esc(t("detail.metaClaims"))}</dt><dd>${esc(attrs.claims_text.join(" · "))}</dd>` : ""}
          ${specialInds.length ? `<dt>${esc(t("detail.metaSpecialIndicators"))}</dt><dd class="mono">${esc(specialInds.map(formatSpecialIndicator).join(" · "))}</dd>` : ""}
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
        ${supersedesChips ? `<div class="chip-cluster" style="margin-bottom:8px;">${supersedesChips}</div>` : ""}
        ${ed.lifecycle ? `<div class="archival-banner">${esc(t("detail.lifecycleOverridePrefix"))}: <b class="mono">${esc(ed.lifecycle.state)}</b>${ed.lifecycle.effective_month ? ` (${esc(ed.lifecycle.effective_month)})` : ""} — ${esc(ed.lifecycle.reason)}</div>` : ""}
        <div class="chip-cluster" style="margin-bottom:8px;">
          <span class="chip mono">${esc(t("detail.coreFpPrefix"))}: ${esc(ed.core_fingerprint.slice(0, 26))}…</span>
          <span class="chip mono">${esc(t("detail.labelFpPrefix"))}: ${esc(ed.label_fingerprint.slice(0, 26))}…</span>
        </div>
        ${revisionsHtml ? `<div class="section-label" style="margin-top:8px;">${esc(t("detail.revisionsTitle"))}</div><div class="revision-list">${revisionsHtml}</div>` : ""}
        ${(ed.evidence || [])
          .map((ev, idx) => {
            const mediaSrc = resolveMediaRef(ev.media_ref);
            const pubSha = ev.cropped_sha256 || ev.snapshot_sha256;
            return `<div class="subcard mono">
              <b>${esc(ev.evidence_id)}</b> [${esc(ev.type)}${ev.provenance ? ` · ${esc(ev.provenance)}` : ""}]
              ${ev.region ? `region=${esc(ev.region)}` : ""}
              ${ev.registry ? `registry=${esc(ev.registry)} (${esc(ev.query || "")})` : ""}
              ${pubSha ? `sha256=${esc(pubSha.slice(0, 16))}…` : ""}
              ${ev.vault_raw_sha256 ? `vault=${esc(ev.vault_raw_sha256.slice(0, 12))}…` : ""}
              ${ev.specimen_id ? `${esc(t("detail.specimenLabel"))}=${esc(ev.specimen_id)}` : ""}
              ${ev.vintage_month ? `${esc(t("detail.vintageLabel"))}=${esc(ev.vintage_month)}` : ""}
              ${ev.artwork_note ? `· ${esc(ev.artwork_note)}` : ""}
              · ${esc(ev.contributor || "")} (${esc(t("detail.reportedAtLabel"))}: ${esc(ev.reported_at || "")})
              ${
                mediaSrc
                  ? ` <button type="button" class="chip mono preview-media-btn" data-media-src="${esc(mediaSrc)}" data-target-id="ev-img-${idx}">${esc(t("detail.previewCrop"))}</button><div id="ev-img-${idx}" hidden></div>`
                  : ""
              }
            </div>`;
          })
          .join("")}`;

      const notesBody = (ed.quality_flags || []).length
        ? ed.quality_flags.map((f) => `<div class="note-item"><b>${esc(f.code)}</b> (${esc(f.field)}) — ${esc(f.detail)}</div>`).join("")
        : `<span class="mono" style="font-size:0.82rem;color:var(--md-on-surface-variant)">${esc(t("detail.noNotes"))}</span>`;

      const viewMain = `<div class="detail-sections">
        ${renderSectionCard(t("detail.railNormalized"), renderNutritionSection(ed), `<span class="chip mono">${esc(norm.basis)}</span>`)}
        ${renderSectionCard(t("detail.railIngredients"), ingredientsBody)}
        ${renderSectionCard(t("detail.railCompliance"), complianceBody)}
        ${renderSectionCard(t("detail.railProvenance"), provenanceBody)}
        ${renderSectionCard(t("detail.railNotes"), notesBody)}
      </div>`;

      const basisLabelSuffix = attrs.serving_size_label ? " / " + attrs.serving_size_label : "";
      const declaredSectionBody = core.nutrition_declared
        ? `<p class="lead" style="margin-bottom:12px;">${esc(
            t("detail.declaredIntro", { value: core.nutrition_declared.basis.value, unit: core.nutrition_declared.basis.unit, labelSuffix: basisLabelSuffix })
          )}</p>
           <div class="table-wrap"><table class="nutrient-table"><thead><tr><th>${esc(t("detail.declaredColId"))}</th><th>${esc(t("detail.declaredColVal"))}</th><th>${esc(t("detail.declaredColNrv"))}</th></tr></thead><tbody>${declaredRows}</tbody></table></div>`
        : renderNutritionSection(ed);
      const viewDeclared = `<div class="detail-sections">${renderSectionCard(t("detail.tabDeclared"), declaredSectionBody)}</div>`;

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
          selectedEditionId ? ` <button type="button" class="chip" id="return-overview-btn" style="margin-left:8px;">${esc(t("detail.returnToUniformOverview"))}</button>` : ""
        }</div>`;
      } else if (compact.resolution === "inactive") {
        topBanners += `<div class="archival-banner">${esc(t("detail.inactiveBanner"))}</div>`;
      }

      $("#detail").innerHTML = `
        <div class="mobile-back-bar"><button type="button" class="chip" id="mobile-back-btn">${esc(t("detail.backToCatalog"))}</button></div>
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
            <span class="imprint-item">${esc(formatTActiveText(ed, full, false))}</span>
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

    return {
      translateNutrient,
      formatTActiveText,
      renderCatalogCard,
      renderDivergentOverview,
    };
  }

  return { createDetailRenderer };
});
