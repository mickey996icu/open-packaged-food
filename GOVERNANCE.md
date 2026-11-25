# OpenPackagedFood Governance & Sustainability Principles

**[English](GOVERNANCE.md) | [简体中文](GOVERNANCE.zh-CN.md)** · **[Contributing](CONTRIBUTING.md)** · **[ODbL User Guide](docs/ODbL-GUIDE.md)** · **[Data Limitations](docs/DATA-LIMITATIONS.md)** · **[Specification](spec/SPEC.md)**

OpenPackagedFood (`opf`) is maintained with two parallel goals: keeping the shared packaged-food label-transcription ledger open, neutral, and traceable over the long term, and leaving a clean, lawful sustainability path to fund ongoing curation and errata maintenance.

---

## 1. Repository & Licensing Boundaries (REUSE Compliant)

| Layer | Scope | Outbound License | Inbound Contribution Rule |
| :--- | :--- | :--- | :--- |
| **Tooling & Explorer** | `opf/`, `bin/`, `web/` (excl. `web/vendor/`), `.github/`, `tests/` | `AGPL-3.0-or-later` | **`Apache-2.0`** + DCO (`Signed-off-by`) |
| **Bundled ZXing Vendor** | `web/vendor/` | `Apache-2.0` | Upstream `Apache-2.0` |
| **Spec, Rules & Dictionaries** | `spec/`, `dictionaries/`, `profiles/`, `skills/`, `docs/` | `Apache-2.0` | **`Apache-2.0`** + DCO (`Signed-off-by`) |
| **Product Database** | `opf-data` (`products/`, `overlays/`) | `ODbL-1.0` / `DbCL-1.0` | `ODbL-1.0` / `DbCL-1.0` + DCO |
| **Label Crop Media** | `opf-media` (`media/`) | `CC-BY-SA-4.0` | `CC-BY-SA-4.0` + DCO |

- **Machine-Readable REUSE Manifest**: Exact per-path SPDX coverage is declared in [`REUSE.toml`](REUSE.toml) with license texts in [`LICENSES/`](LICENSES/).
- **Public Data Neutrality**: Community-contributed product JSON in `opf-data` and label crops in `opf-media` remain permanently open under `ODbL-1.0` and `CC-BY-SA-4.0`. Maintainers do not grant proprietary exemptions over third-party community records.
- **Permissive Inbound for Code & Standards**: Contributions to `open-packaged-food` enter under `Apache-2.0` alongside DCO (`git commit -s`), avoiding contributor-specific CLA bottlenecks while allowing maintainers and downstream integrators to build clean components around the standard.

---

## 2. Dual-Layer `provenance`, `agreement_ref`, and Blind Re-Transcription Rules

Every `evidence[]` artifact and every `revisions[]` structured transcription entry carries a mandatory `provenance` tag (`maintainer | external_contributor | public_submission | brand_owner | partner`):

1. **Creator & Role Enforcement in CI (`opf check-pr-meta`)**:
   - External PRs may only create entries tagged `external_contributor`.
   - Phase 2 submission relay bots may only create entries tagged `public_submission`.
   - `maintainer`, `brand_owner`, and `partner` tags may only be introduced by authorized maintainer accounts; `brand_owner` and `partner` additionally require an internal `agreement_ref` identifier pointing to written terms.
   - **Immutability Against Retroactive Relabeling**: Existing entries' `provenance` tags may **not** be altered by anyone (including maintainers) unless an authorized maintainer provides an explicit `Provenance-Correction: <reason>` Git commit trailer.
2. **Scope of `maintainer` & Copyright Ownership (PRC Copyright Law Art. 18)**:
   - `maintainer` applies strictly to independent capture or transcription by the project maintainer—or personnel of a future operating entity **only where written agreements assign work copyright to that entity** (under Article 18 of the PRC Copyright Law, copyright in general works for hire defaults to the individual employee absent written agreement or statutory assignment).
3. **Blind Re-Transcription Based on Physical-Package Evidence (`transcription: "independent_match"`)**:
   - Corroborating an existing `external_contributor` edition with a maintainer photo appends only to `evidence[]` and leaves `revisions[0].provenance` as `external_contributor`.
   - A corroborating `evidence[]` item only counts toward structured data independence when maintainers perform an **independent transcription from physical-package evidence (blind re-transcription)** without inspecting the existing `core` JSON, and tooling records `transcription: "independent_match"` (forbidden for manual entry).
   - **Maintainer-Origin Subset Criterion**: A record's current `core` belongs to a clean maintainer-origin subset only when every active value derives from `maintainer` revisions or is covered by a `transcription: "independent_match"` evidence item, with no subsequent unverified external modifications.
4. **Research & Brand Partner Channel (`partner`, `brand_owner`)**:
   - Universities, research partners, and brand owners may contribute records under bilateral agreements referenced via `agreement_ref`.

---

## 3. Commercial Sustainability, Liability Isolation & Duty-of-Care Baseline

1. **Pre-Revenue Stage**: Before any commercial revenue occurs, all repositories operate purely as a public open-source project without personal legal-entity exposure or private monetization locks.
2. **Pre-Revenue Requirement for a Limited-Liability Entity**: Prior to accepting the first paid revenue—such as managed API SLAs, commercial label-OCR pipelines, optional contract-backed fact feedback, proprietary maintainer-only sub-datasets, or consumer-facing subscription features—commercial operations **must** be placed under an independent limited-liability legal entity separated from personal contributor assets. Should a future operating entity directly provide consumer-facing commercial products, appropriate commercial liability insurance must be arranged prior to launch.
3. **Maintainer Duty-of-Care Baseline & Downstream Responsibility**:
   - **Descriptive Evidence Labels Without Accuracy Claims**: Official OPF specifications and the built-in Web Explorer describe `evidence_level` purely by submission form (e.g., number of photo-submitting accounts or public registry source) and `t_active` by actual derivation basis—never claiming human verification or product safety (see [`docs/DATA-LIMITATIONS.md`](docs/DATA-LIMITATIONS.md)).
   - **Public Errata & `retracted` Isolation**: OPF maintains public `opf-data` errata reporting and uses `lifecycle.state = "retracted"` to isolate erroneous or misleading editions from active outputs; allergen- and ingredient-related errata reports are **prioritized** without fixed turnaround SLA promises.
   - **Integrator Responsibility**: Downstream integrators remain **solely responsible** for their own product UX, safety notices, and legal compliance toward end users; OPF does not prescribe binding product design standards for third parties.
