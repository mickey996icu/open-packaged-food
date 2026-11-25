# OPF ODbL & Licensing User Guide (For Integrators & Commercial Apps)

**[English](ODbL-GUIDE.md) | [简体中文](ODbL-GUIDE.zh-CN.md)** · **[Governance](../GOVERNANCE.md)** · **[Data Limitations](DATA-LIMITATIONS.md)** · **[Specification](../spec/SPEC.md)**

OpenPackagedFood (`opf`) aims to make food label facts easy and legally predictable for nutrition trackers, grocery apps, researchers, AI assistants, and internal enterprise systems to consume. This guide clarifies how our open licenses work in practice.

> **Disclaimer & Responsibility**: This guide provides practical engineering and licensing orientation only and does **not** constitute formal legal advice. **Integrators remain solely responsible for their own product disclosures and compliance obligations toward end users.** For factual dataset boundaries and known limitations, see the separate [Data Limitations & Usage Notes](DATA-LIMITATIONS.md) (which impose no extra conditions beyond `ODbL-1.0`).

---

## 1. License Map at a Glance (REUSE-Annotated)

- **Connecting via HTTP API or JSON Schemas / Dictionaries / Profiles (`Apache-2.0`)**:
  - Reading the static JSON endpoints (`/v1/...`) over HTTP does not trigger `AGPL-3.0-or-later`.
  - Incorporating `spec/schema/*.json`, `dictionaries/*.json` (nutrients, INS additives, allergens), `profiles/*`, `skills/opf`, or docs into proprietary backend or mobile apps is governed by **`Apache-2.0`**—permissive, with no copyleft propagation.
- **Self-Hosting or Modifying the Explorer/CLI Tooling (`AGPL-3.0-or-later` / `Apache-2.0` inbound)**:
  - Modifying `opf/`, `bin/`, or `web/` (excluding the `Apache-2.0` ZXing library under `web/vendor/`) and serving the modified program over a network requires sharing the source code of that modified program under `AGPL-3.0-or-later`. Independent proprietary services communicating with OPF endpoints over HTTP or reading static JSON remain unaffected.
- **Product Database (`opf-data`, `ODbL-1.0` / `DbCL-1.0`) & Label Media (`opf-media`, `CC-BY-SA-4.0`)**:
  - Public records in `opf-data` are licensed under **ODbL-1.0**; cropped label photos in `opf-media` are licensed under **CC-BY-SA-4.0**.

---

## 2. Common Integration Scenarios Under ODbL-1.0

### Scenario A: Internal `SKU ↔ GTIN` Mapping & Collective Databases (ODbL §4.5)
- **Typical case**: A retailer, meal-logging app, or internal nutrition system maps its private SKUs or warehouse codes to OPF `gtin:` identifiers, or places an unmodified OPF dataset alongside separate private business tables inside a larger system.
- **How ODbL treats this**:
  1. Purely internal use—without publicly conveying or publicly using a Derived Database—generally does not trigger ODbL public Share-Alike obligations.
  2. Under the **Collective Database** rule (ODbL Section 4.5), storing an independent, unmodified OPF database alongside separate private databases—where the mapping table stores only `GTIN` and internal SKU IDs without extracting/reusing substantial parts of OPF content into a merged database—**usually** does not constitute a Derived Database or extend Share-Alike obligations to the private database.
- **Important clarification on exemptions**: Because `opf-data` contains third-party contributions under `ODbL-1.0`, OPF maintainers do **not** sell or grant special exemptions to bypass ODbL Section 4 when an integrator's public product genuinely creates and publicly uses a Derived Database.

### Scenario B: Public Produced Works & Derived Databases (ODbL §4.3 & §4.6)
- **Attribution (§4.3)**: Provide clear attribution to OpenPackagedFood (`opf-data`) and link to `ODbL-1.0`.
- **Mandatory Produced-Work Offer (§4.6)**: Under ODbL Section 4.6, if you create and publicly use a **Produced Work** (such as a consumer app UI, report, model output, or visualization) generated from a **Derived Database**, you **must** make available to recipients (under ODbL-1.0) either:
  1. The full machine-readable Derived Database itself; **or**
  2. A machine-readable file containing all the alterations made to the original database (or the algorithm used to compute those changes) so recipients can reconstruct the Derived Database.
- **Cropped Label Images (`opf-media`)**: Any public redistribution or bundling of label WebP images must comply with `CC-BY-SA-4.0`.
- **Informational Technical Boundaries**: For objective details and non-binding recommendations regarding `<` rounding bounds, `divergent` variants, `evidence_level` meanings, and `t_active` semantics, refer to [Data Limitations & Usage Notes](DATA-LIMITATIONS.md).
