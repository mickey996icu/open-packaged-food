# OpenPackagedFood Data Limitations & Usage Notes

**[English](DATA-LIMITATIONS.md) | [简体中文](DATA-LIMITATIONS.zh-CN.md)** · **[Governance](../GOVERNANCE.md)** · **[ODbL Guide](ODbL-GUIDE.md)** · **[Specification](../spec/SPEC.md)**

This document describes what the OpenPackagedFood (`opf-data`) public dataset **is, is not**, and its known factual and technical limitations.

> **Scope & Responsibility Notices**:
> 1. Nothing in this document adds extra conditions or restrictions beyond **`ODbL-1.0`**.
> 2. **OPF data carries no warranty of product safety, accuracy, or fitness for any specific person or dietary need.**
> 3. **Downstream integrators remain solely responsible for their own user disclosures, UX design, and legal compliance.** Any presentation recommendations below are purely informational.

---

## 1. What the Dataset Is — and Is Not

1. **Package Text Transcription Only (No Unprinted Cross-Contact or Shared-Line Data)**:
   - Records in `opf-data` transcribe text visibly printed on product labels or published in public official food registries.
   - OPF does **not** capture unprinted factory cross-contact, shared-equipment residue, or temporary supply substitutions, and performs no chemical or laboratory testing.
2. **Presence of Photos Does Not Mean Values Were Verified**:
   - Existing `evidence_level` values indicate **what form of source material was submitted**, not accuracy or safety:
     - `corroborated`: *2 or more contributor accounts submitted label photos* (accounts may not be distinct real individuals, and structured JSON fields have not necessarily been checked against the photos).
     - `verified`: *1 label photo submission with content hash* (does **not** confirm that transcribed numbers/text match the photo).
     - `official_registry_imported`: *Imported from a public official registry*.
     - `community_reported`: *Text report only, without label photos*.
   - Only when future tooling writes `"transcription": "independent_match"` from a blind re-transcription pass does evidence indicate an independent match between transcription and label photos—and even then, it reflects only what was printed on that package, **not** that the product is safe.
3. **Formulations May Differ Across Plants or Over Time Under One Barcode**:
   - Multiple contract plants (`track`) or legacy/updated formulations may share the same GTIN barcode.
   - `t_active` summarizes observed record timing and does **not** mean a product is currently sold or within shelf life:
     - When `vintage_month` exists (`t_active_basis == "vintage_month"`), it shows the **latest package vintage seen (formulation may have changed since)**.
     - When no evidence item carries `vintage_month` (`t_active_basis == "earliest_reported_at"`), it falls back to `min reported_at`, meaning **earliest reported month**, not latest.
4. **Regulatory Rounding Bounds (`<`) and Divergent Variants**:
   - Nutrient entries flagged `basis: "regulatory_upper_bound"` represent regulatory zero-rounding thresholds (`< X`), not mathematical zero.
   - Under `"resolution": "divergent"`, summary nutrient ranges only summarize cross-variant spread and do not describe any single physical package in hand.
5. **Community and OCR Errors Can Occur**:
   - Although schema, lossless ingredient round-trip, and arithmetic checks apply at submission time, manual transcription mistakes and vision/OCR errors can still occur.

---

## 2. Informational Recommendations for Downstream Integrators

To avoid creating a misleading impression of verification or safety, integrators are **advised** (at their own discretion and responsibility) to:

- **Describe `evidence_level` by evidence form rather than accuracy claims**: We recommend descriptive labels such as *"2+ contributors submitted photos"*, *"1 label photo submitted"*, *"Public official registry"*, and *"Text report only (no photo)"*, and **recommend avoiding** terms such as *"verified"*, *"certified"*, or *"checked"*.
- **Distinguish `t_active` bases accurately**: When `t_active_basis == "vintage_month"`, recommend displaying *"Latest package vintage seen: YYYY-MM (formulation may have changed since)"*; when `t_active_basis == "earliest_reported_at"`, recommend displaying *"Earliest reported: YYYY-MM"*.
- **Preserve `<` upper bounds and `divergent` disambiguation**: Keep regulatory `<` upper bounds distinct from `0`, and prompt users to match their physical package (`track` / plant / SC code) when variants diverge.
- **Remind users to check the physical label**: Recommend displaying a clear notice: **"Always verify against the physical package in hand."**

---

## 3. Public Errata, Retraction (`retracted`), and Triage

- **Public Errata Channel**: Anyone can report field mistakes, request supply-chain track splits (`retrack`), or request lifecycle updates via the [`opf-data` Data Errata & Lifecycle issue form](https://github.com/mickey996icu/opf-data/issues/new?template=data_errata.yml) or by submitting a pull request.
- **Isolation via `retracted`**: When an edition contains serious errors, questionable sourcing, or misleading risks, maintainers use `lifecycle.state = "retracted"` to isolate it from active editions and normal Compact API outputs while preserving the audit record.
- **Prioritized Allergen & Ingredient Reports**: Errata reports involving omitted or misstated allergens or ingredients are **handled with priority** (without fixed response-time SLA guarantees).
