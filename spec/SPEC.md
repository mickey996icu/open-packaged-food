# OpenPackagedFood Specification (v0.2)

> **Status**: Draft M0 | **Schema Version**: `0.2` | **CI Tooling Pin**: `v0.2.3` | **License**: Code AGPL-3.0-or-later, Data ODbL-1.0, Label Media CC-BY-SA-4.0

## 1. Scope & Core Principles

1. **Evidence First, Zero Judgment**: OpenPackagedFood (`opf`) records verifiable facts printed on industrial packaged food labels and official regulatory registries. It never outputs subjective health scores, dietary recommendations, or guessed values.
2. **Three-Way Separation of Concerns**:
   - **Physical Identity (`Edition` + `core`)**: A permanent ULID (`edition_id`) representing one physical package specification, anchored by canonical structured values (`core`) rather than OCR-sensitive raw strings or rule-dependent normalized outputs.
   - **Epistemic Knowledge (`attributes` + `revisions[]` + `evidence[]`)**: What contributors currently know about that package (verbatim texts, SC licenses, origin, packaging codes) maintained via a content-revision log (`@rev`), paired with an append-only `evidence[]` set from which `evidence_level` is derived at build time.
   - **Spatiotemporal Lifecycle (`Track` + `supersedes` + Build-Time Status)**: Multi-origin / multi-market coexistence across parallel tracks combined with deterministic build-time status derivation (`active`, `stale`, `superseded`, `discontinued`, `retracted`) so historical editions retire naturally without manual status churn.
3. **Dual-Layer Nutrition Representation**:
   - `core.nutrition_declared`: Faithful structured transcription of printed nutrition values in the package's declared basis (e.g., per serving `28g` or per `100g`) and units (`kJ` or `kcal`, `sodium` or `salt`).
   - `normalized`: Deterministically compiled `100g` or `100ml` standard profile computed by `opf normalize` using exact decimal arithmetic and jurisdiction-specific `regulatory_profile` rules.
4. **Verifiable Lossless Ingredient AST**: Every edition pairs canonical span-free `core.ingredients_tree` nodes with verbatim `attributes.ingredients_text`, enforced by a deterministic monotonic round-trip check in CI so punctuation/full-width errata in raw text never alter `core` while hallucinated or dropped ingredients fail validation.

---

## 2. Primary Identifier (`id`)

Each product record has a globally unique canonical `id`:

### 2.1 First-Class Identifier: `gtin:<14-digit-gtin>`
- Standard GS1 barcodes (GTIN-8, GTIN-12/UPC-A, GTIN-13/EAN-13, GTIN-14) are left-padded with zeros to 14 digits.
- Example: `0000000000017` $\rightarrow$ `gtin:00000000000017`.
- **Validation Rules**:
  - Must match `^gtin:[0-9]{14}$`.
  - Must pass the standard GS1 Mod-10 check digit algorithm.
  - **Restricted In-Store Prefixes**: Barcodes whose underlying GTIN-13 starts with `020`–`029` or `200`–`299` (GS1 variable-measure / retailer internal codes) MUST NOT be registered as global `gtin:` records; they must use the `opf:` namespace.

### 2.2 Second-Class Identifier: `opf:<brand-slug>/<product-slug>/<spec-slug>`
- Used for retailer private-label, fresh pre-packaged, or regional industrial foods that lack a globally unique GS1 GTIN (or use in-store variable-weight barcodes).
- **Slug Rules**:
  - Each segment must match `^[a-z0-9]+(-[a-z0-9]+)*$`.
  - `<spec-slug>` encodes the canonical net content or pack specification (e.g., `80g`, `500g-6pcs`, `750ml`).
- Example: `opf:demo-deli/black-pepper-patty/80g`.

---

## 3. Canonical Nutrient Identifiers & Canonical Row Order

All `core.nutrition_declared.rows` and `normalized.nutrients` use canonical nutrient IDs from `dictionaries/nutrients.json`. On disk, `core.nutrition_declared.rows` MUST be persisted in the exact canonical order below (when both `kJ` and `kcal` are declared for `energy`, `kJ` precedes `kcal`; duplicate `(nutrient, unit)` pairs are forbidden and rejected by `opf validate`):

| Order | Nutrient ID | Dimension | Standard Normalized Unit | Notes |
| :---: | :--- | :--- | :--- | :--- |
| 1 | `energy` | Energy | `kcal` & `kJ` (`energy_kj`, `energy_kcal`) | Converted via $1\text{ kcal} = 4.184\text{ kJ}$; `kJ` row before `kcal` row |
| 2 | `protein` | Mass | `g` | |
| 3 | `fat_total` | Mass | `g` | Total fat / lipid |
| 4 | `fat_saturated` | Mass | `g` | Saturated fatty acids |
| 5 | `fat_trans` | Mass | `g` | Trans fatty acids |
| 6 | `fat_monounsaturated` | Mass | `g` | Monounsaturated fatty acids |
| 7 | `fat_polyunsaturated` | Mass | `g` | Polyunsaturated fatty acids |
| 8 | `cholesterol` | Mass | `mg` | |
| 9 | `carbs_available` | Mass | `g` | Available carbohydrates (default in CN, EU, AU/NZ) |
| 10 | `carbs_total` | Mass | `g` | Total carbohydrates including fiber (default in US, CA) |
| 11 | `sugars_total` | Mass | `g` | Total sugars |
| 12 | `sugars_added` | Mass | `g` | Added sugars |
| 13 | `sugar_alcohols` | Mass | `g` | Polyols / erythritol / xylitol |
| 14 | `dietary_fiber` | Mass | `g` | Total dietary fiber |
| 15 | `sodium` | Mass | `mg` | Default in CN, US |
| 16 | `salt_equivalent` | Mass | `g` | Default in EU, UK, JP ($\text{salt\_g} = \text{sodium\_g} \times 2.5$) |
| 17 | `calcium` | Mass | `mg` | |
| 18 | `iron` | Mass | `mg` | |
| 19 | `potassium` | Mass | `mg` | |
| 20 | `vitamin_a` | Mass | `ug` | Micrograms RAE/RE |
| 21 | `vitamin_c` | Mass | `mg` | |
| 22 | `vitamin_d` | Mass | `ug` | |

*(Any additional nutrients registered in `dictionaries/nutrients.json` follow in dictionary order.)*

---

## 4. Value Representation & Upper-Bound Preservation

1. **Decimal Strings Only**: All quantities (`value`, `nrv_pct`) are stored as exact canonical decimal strings (`"0"`, `"260.8"`, `"3.75"`), without redundant trailing zeros after a decimal point, and never as IEEE-754 floats.
2. **Qualifiers**:
   - `exact` (default when `qualifier` is omitted; `"="` is normalized to omitted in `core`)
   - `"<"` (strictly less than, e.g., regulatory zero-rounding upper bound)
   - `"<="` (less than or equal to, e.g., `"≤3%"`)
   - `">"` / `">="` (greater than / greater than or equal to, e.g., `"≥280mg/kg"`)
   - `"~"` (approximate)
   - `"trace"` (trace amount declared on label)
3. **Regulatory Zero-Rounding Propagation**:
   - Under `US/FDA-NLEA` (`zero_thresholds_per_serving`), a declared `0` for `energy` (< 5 kcal/serving) or `fat_trans` (< 0.5 g/serving) is a legal rounding artifact when per-serving weight is small.
   - Under `CN/GB28050-2011`, `CN/GB28050-2025`, `EU/1169-2011`, and `JP/CAA-2015` (`zero_thresholds_per_100`), a declared `0` on the label represents any value $\le$ the statutory "0" threshold (e.g., $\le 17\text{ kJ}$, $\le 0.5\text{ g}$ protein/fat/carbs, $\le 5\text{ mg}$ sodium in CN; $\le 0.01\text{ g}$ salt in EU).
   - `core.nutrition_declared` preserves the verbatim printed `"0"`, while `opf normalize` outputs `qualifier: "<"` and `basis: "regulatory_upper_bound"` in `normalized.nutrients` and records `REGULATORY_ZERO_ROUNDING_ARTIFACT` in `quality_flags`.
4. **Dual `kJ` and `kcal` Declarations**:
   - When only `kJ` or only `kcal` is declared, the other is cross-derived via $1\text{ kcal} = 4.184\text{ kJ}$ with `basis: "derived"`.
   - When both `kJ` and `kcal` are printed on the label, both are preserved in `normalized.nutrients` as `reported` (or `derived` if scaled from per-serving), and their ratio is checked against $4.184$ (emitting `ENERGY_KJ_KCAL_DECLARED_MISMATCH` if relative discrepancy exceeds $5\%$).
5. **NRV% / %DV Cross-Check**:
   - When `nrv_pct` is present on a declared row, `opf normalize` compares it against the profile's `nrv_reference` values and emits `NRV_PCT_DECLARED_MISMATCH` in `quality_flags` if the absolute difference exceeds $2.5\%$.

---

## 5. Ingredient Semantic AST & Lossless Round-Trip Verification

To prevent OCR punctuation noise from mutating `core` while preserving strict anti-hallucination verification:

1. **Span-Free Canonical AST in `core.ingredients_tree`**:
   - Grouped and sorted lexicographically by `lang` (BCP-47 tag matching `attributes.ingredients_text`).
   - Within each `lang`, `nodes` preserve the exact printed descending weight order on the package.
   - Each recursive `SemanticIngredientNode` contains only structured semantic properties:
     - `name`: Ingredient name string (trimmed, Unicode NFKC-normalized in fingerprint computation).
     - `qualifier`: Optional declared quantitative qualifier (e.g., `"≥4g/L"`, `"≥95%"`).
     - `functional_class`: Optional additive class prefix (e.g., `"抗氧化剂"`, `"Acidity regulator"`).
     - `ins`: Optional Codex Alimentarius INS code (e.g., `"300"`, `"500(ii)"`).
     - `is_additive`: Optional boolean (`true` for additives after `／` in JP labels or matched INS additives).
     - `allergens`: Optional sorted array of canonical allergen IDs (e.g., `["soy", "wheat"]`).
     - `children`: Optional nested array of child ingredient nodes (compound ingredients).
   - Character offsets (`span`) are **not** stored in `core.ingredients_tree`. Fixing a full-width/half-width comma or whitespace typo in `attributes.ingredients_text` requires only an `attributes` revision without touching `core`.
2. **Deterministic Monotonic Round-Trip Check**:
   - During `opf validate` and `opf build`, the validator walks `core.ingredients_tree[lang].nodes` in pre-order against `attributes.ingredients_text[lang].text` from `cursor = 0`:
     1. After skipping optional profile-allowed header prefixes (e.g., `"配料："`, `"Ingredients:"`) and structural characters (delimiters, brackets, whitespace), each expected token (`functional_class`, `name`, `children`, `qualifier`) MUST match monotonically at `cursor`.
     2. Every character between matched tokens and after the final token MUST belong to the profile's `ALLOWED_STRUCTURAL_CHARS`, and all brackets in `raw_text` MUST be balanced.
     3. Any uncaptured character or token mismatch fails CI validation. Build outputs (`.full.json`) may emit computed `[start, end)` spans for UI highlighting.

---

## 6. Official Registry Identifiers (`registry`)

| Registry ID | Jurisdiction | Target Field | Description |
| :--- | :--- | :--- | :--- |
| `CN/SAMR-SC` | China | `attributes.parties[].license` | 国家市场监督管理总局食品生产许可（SC）查询 |
| `CN/SAMR-FOOD-CHECK` | China | `id`, `attributes.parties` | 国家/省级市场监管食品安全监督抽检公布系统 |
| `CN/CFSA-GB` | China | `attributes.product_standard` | 食品安全国家标准数据检索平台（GB） |
| `CN/NHC-Q-STD` | China | `attributes.product_standard` | 省级卫健委食品安全企业标准备案（Q/） |
| `CN/ANCC-GDS` | China | `id` (GTIN) | 中国物品编码中心 / 中国商品信息服务平台 |
| `CN/SAMR-SPECIAL-FOOD` | China | `registration_no` | 特殊食品信息查询平台（保健食品/婴配粉/特医） |
| `US/USDA-FDC` | United States | Product / GTIN | USDA FoodData Central Branded Foods (CC0) |
| `JP/CAA-FFC` | Japan | Notification No | 日本消费者厅机能性表示食品届出数据库 |

---

## 7. Repository & Static API Layout (`/v1/`)

### 7.1 Source Repository Layout (`opf-data/products/`)

To eliminate Git merge conflicts across concurrent PRs, each product is stored as a directory with one lightweight `product.json` and per-edition `<edition_id>.json` files:

```text
products/
├── gtin/{p1}/{p2}/{gtin14}/
│   ├── product.json                        # Product ID, aliases, non-default track discriminators
│   └── editions/
│       ├── 01J8Z4K9M2N3P4Q5R6S7T8V9W0.json # EditionRecord (core, attributes, revisions[], evidence[])
│       └── 01J9A2B3C4D5E6F7G8H9J0K1M2.json # EditionRecord or EditionRedirect ({merged_into})
└── opf/{brand}/{product}/{spec}/
    ├── product.json
    └── editions/
        └── 01J8Z4K9M2N3P4Q5R6S7T8V9W0.json
```

### 7.2 Compiled Static API Endpoints (`opf build`)

- `/v1/meta.json`: Schema version (`"0.2"`), tool/data commits, `media_base_url`, counts by derived evidence level and market.
- `/v1/gtin/{p1}/{p2}/{gtin14}.json`: Compact Agent endpoint (`p1 = gtin14[1:4]`, `p2 = gtin14[4:7]`). Reports `resolution` (`single | uniform | divergent | inactive`), `evidence_summary`, `edition_redirects`, and either unified nutrition/ingredients (`single` / `uniform`) or per-variant diffs and disambiguation instructions (`divergent`).
- `/v1/gtin/{p1}/{p2}/{gtin14}.full.json`: Assembled full product document containing `product.json` metadata, `edition_redirects`, all live/historical editions with build-derived `status` and `evidence_level`, computed `superseded_by` reverse edges, `revisions[]`, and `evidence[]`.
- `/v1/opf/{brand}/{product}/{spec}.json` & `.full.json`: Equivalent endpoints for `opf:` identifiers.
- `/v1/index/brands.json` & `/v1/index/brand/{brand_slug}.json`: Brand directory and per-brand product summaries.
- `/v1/index/catalog.jsonl`: Line-delimited JSON catalog for local search and Web Explorer indexing.

---

## 8. Tracks, Editions, Revisions & Lifecycle Resolution

### 8.1 Entity Hierarchy & Permanent Reference Invariants

```text
Product (id: gtin:... | opf:...)           [product.json: id, aliases, non-default track discriminators]
 └─ Track (market/default | market/axis:…) [declared on each Edition]
     └─ Edition (edition_id: ULID)         [editions/<ulid>.json]
         ├─ core            Structured identity payload (declared nutrition, semantic ingredient AST, allergens, net_content)
         ├─ attributes      Enrichable/amendable label facts (raw texts, origin, parties/SC, standard, packaging_code)
         ├─ normalized      Deterministically compiled 100g/100ml profile (derived at current rev)
         ├─ supersedes[]    Explicit outgoing edges to older edition ULIDs replaced by this edition
         ├─ lifecycle?      Optional explicit retracted / discontinued administrative override
         ├─ revisions[]     Content-only RFC 6902 JSON Patch log + reverse_patch + monotonic rev (1..N)
         └─ evidence[]      Append-only content-addressed / ULID-keyed evidence items (drives derived evidence_level)
```

**Core Invariants**:
1. **Permanent Reference Stability**: Once published, an `edition_id` (26-character Crockford Base32 ULID, matching `^[0-7][0-9A-HJKMNP-TV-Z]{25}$`) NEVER disappears. Errata increment `rev` in place; duplicate editions absorbed during PR consolidation remain on disk as `EditionRedirect` stubs (`{"merged_into": "<target_ulid>"}`).
2. **Exact Scope of `<edition_id>@<rev>`**:
   - External systems (such as personal dietary trackers or downstream apps) cite `<edition_id>` (resolving through any `merged_into` redirect to the target edition's latest `rev`) or `<edition_id>@<rev>`.
   - **`@rev` locks strictly the patchable content surface (`/core`, `/attributes`, `/track`, `/supersedes`, `/lifecycle`)**. It does **not** snapshot `evidence[]` or build-derived `evidence_level` / `status`. Appending corroborating photos to `evidence[]` never increments `rev`.

---

### 8.2 `core` vs. `attributes`, Canonical Ordering & Derived Fingerprints

`core` contains **only canonicalized structured values**—never raw OCR strings and never `normalized` outputs (so upgrading conversion/rounding rules in `opf normalize` never shifts `core_fingerprint`):

| Layer | Fields | On-Disk Canonical Order & Role |
| :--- | :--- | :--- |
| `core` | `regulatory_profile`, `net_content` (`{qualifier?, value, unit}[]`), `serving_size` (`{qualifier?, value, unit}`), `nutrition_declared` (`basis` + `rows`), `ingredients_tree` (span-free semantic AST), `allergens_declared` (`{contains, may_contain}` canonical IDs) | `nutrition_declared.rows` MUST follow §3 canonical nutrient order; `ingredients_tree` MUST be sorted by `lang` (with `nodes` in printed weight order); `allergens_declared` lists MUST be sorted & unique. `opf validate` rejects non-canonical order. |
| `attributes` | `product_name`, `brand`, `category`, `declared_category`, `net_content_label`, `serving_size_label`, `ingredients_text` (raw verbatim strings), `allergens_raw_text`, `origin` (`{country?, region?, raw_text?}`), `parties[]` (`role`, `name`, `address`, `plant_code`, `license`), `product_standard[]`, `packaging_code`, `lot_code_rule`, `shelf_life`, `storage_text`, `usage_text`, `special_indicators[]`, `claims_text[]`, `in_store_barcodes[]`, `translations[]` | Enrichable and amendable via `revisions[]` without creating a new Edition when non-conflicting. |

**Two Derived Fingerprints** (recomputed deterministically at current `rev` by `opf normalize`; verified by `opf validate`; never used as primary keys):
1. `core_fingerprint` (`sha256:<64-hex>`): Canonical JSON SHA-256 over NFKC-normalized `core`.
2. `label_fingerprint` (`sha256:<64-hex>`): Canonical JSON SHA-256 over `core_fingerprint` + order-normalized `attributes.parties` (`role`, `name`, `plant_code`, `license`) + `attributes.origin` (`country`, `region`) + sorted `attributes.product_standard` + `attributes.packaging_code`.

---

### 8.3 Tracks & Lazy Splitting (`track`)

Contributors are **not** required to declare supply-chain tracks up front:

1. **Default Track (`<market>/default`)**:
   - Every market starts with a single track (e.g., `CN/default`, `US/default`, `HK/default`, `JP/default`).
   - **Unified Multi-Plant Labels Stay on `<market>/default`**: A single physical label that prints multiple co-packers / SC numbers (e.g., plants A and B selected by lot-code prefix) is **one Edition**; as long as no competing concurrent print run exists in that market, it MUST remain on `<market>/default`.
2. **When to Split a Track**:
   - Tracks are split **only** when $\ge 2$ distinct editions coexist concurrently in the same market (e.g., a South China single-plant label `SC144...` vs. an East China single-plant label `SC133...`, or concurrent regional recipes) **and** a concrete observable discriminator distinguishes them on the package.
   - If a distinguishing rule cannot yet be written, both editions MUST remain on `<market>/default` (surfacing `unsplit_ambiguity` in Compact API) rather than inventing an unverifiable track key.
3. **Track Key Grammar & Set-Valued Discriminators**:
   - Single-value axis: `<market>/<axis>:<val>` (e.g., `CN/plant:SC10600000000001`, `CN/code:N`, `CN/origin:NZ`).
   - Multi-value set axis (when a multi-plant print run coexists alongside another distinct print run): `<market>/<axis>:{<v1>,<v2>,...}` with strictly unique, lexicographically sorted members—e.g., `CN/plant:{SC111,SC222}` vs. `CN/plant:SC333`.
   - Compound axes join in alphabetical axis order with `+`: e.g., `CN/origin:NZ+plant:SC111`.
4. **CI Track Documentation Rule**: Whenever any live Edition uses a non-default `track` (`!= "<market>/default"`), `product.json` MUST contain a matching entry in `tracks[]` documenting `discriminator.method` and localized `instructions`.

---

### 8.4 Revisions (`revisions[]`), Corroboration & Conflict Routing

Every `EditionRecord` stores the **materialized content state at latest `rev`** alongside `revisions[]` (`rev = 1 .. N`).

#### Patch Mechanics, Canonical Ordering & Tool-Generated `reverse_patch`
1. **Sequential Application**: Let $S_k$ be the patchable content projection `{core, attributes, track, supersedes, lifecycle}` at revision $k$. Revisions apply sequentially:
   $$S_1 \xrightarrow{\text{patch}_2} S_2 \xrightarrow{\text{patch}_3} \cdots \xrightarrow{\text{patch}_N} S_N \quad\text{and}\quad S_N \xrightarrow{\text{reverse\_patch}_N} S_{N-1} \xrightarrow{\text{reverse\_patch}_{N-1}} \cdots \xrightarrow{\text{reverse\_patch}_2} S_1$$
   Array indices in `patch_k` / `reverse_patch_k` (such as `/core/nutrition_declared/rows/4/value`) are evaluated relative to $S_{k-1}$ and $S_k$ respectively, and **every intermediate state $S_k$ MUST preserve §3/§8.2 canonical array ordering**.
2. **No Hand-Written `reverse_patch`**: `reverse_patch` MUST be deterministically generated by `opf` tooling as the exact minimal inverse of `patch_k` applied to $S_{k-1}$. CI (`opf validate`) reconstructs $S_{k-1}$ via `reverse_patch_k`, recomputes the canonical inverse patch from $(S_{k-1}, \text{patch}_k)$, and **rejects** any hand-written, non-minimal, or non-invertible `reverse_patch`.

#### Disjoint Revision Kinds (`kind`) & Dedicated Operations
`rev` increments **only** when the patchable content surface changes:

| `kind` | Allowed Patch Paths | CLI Entrypoint & Semantics |
| :--- | :--- | :--- |
| `initial` | `patch: []` (`rev == 1` only) | `opf submit`: Initial creation of the Edition on `<market>/default` (or an already-documented `--track`). |
| `enrichment` | `/attributes/...` only (`add` missing fields / append `translations`) | `opf submit`: Automatic non-conflicting enrichment of missing `attributes`. MUST NOT touch `/core` or `/track`. |
| `errata` | `/core/...` or `/attributes/...` | `opf submit --amend <ulid>`: Fixes a transcription error on `<ulid>`. MUST NOT touch `/track` or `/lifecycle`. |
| `retrack` | `/track` **only** | `opf retrack <ulid> --track <track>`: Dedicated track-assignment operation (separated from `submit`). Target non-default `<track>` MUST be documented in `product.json`. |
| `lifecycle` | `/supersedes` or `/lifecycle` **only** | `opf lifecycle`: Records explicit `supersedes` links or `retracted` / `discontinued` overrides. |

- **Corroboration Does NOT Increment `rev`**: When a contributor submits additional `label_photo` or `registry_check` evidence confirming an existing Edition without altering content, `opf submit` appends the new item(s) to `evidence[]` (`evidence[]` is strictly append-only) and leaves `rev` and `revisions[]` unchanged.
- **Attribute Conflict Routing**: When `core_fingerprint` matches an existing Edition on the same track, but a non-empty incoming attribute conflicts with an existing non-empty value (e.g., `SC133...` vs `SC144...`), `opf submit` aborts automatic merging and prompts for explicit intent:
  1. `--amend <ulid>` (`errata` fixing a prior typo);
  2. `--supersede <ulid>` (creates a new Edition ULID on the same track with `supersedes: ["<ulid>"]`, e.g., plant relocation); or
  3. `--new-variant [--track <track>]` (creates a concurrent Edition ULID, paired with `opf retrack` + `product.json` discriminator if split across single-factory print runs).
- **Post-Errata Fingerprint Collision $\rightarrow$ Consolidate (§8.5)**: If an `errata` revision on `/core/...` causes the amended Edition's `core_fingerprint` to match another live Edition on the same `(id, track)` (meaning the two editions only appeared distinct due to the prior typo), tooling MUST route into the §8.5 consolidation workflow (`merged_into`) rather than failing with a duplicate-fingerprint error (unless `attributes` still conflict, in which case the contributor selects `--supersede` or `retrack`).

#### Example: Single-Factory Print Run (`editions/01J8Z4K9M2N3P4Q5R6S7T8V9W0.json`)

Below, Alice initially submits a bottle on `CN/default` (`rev 1`), enriches its back-panel `SC` license while staying on `CN/default` (`rev 2`), later retracks it to `CN/plant:SC10600000000001` via `opf retrack` (`rev 3`) after a concurrent second single-factory print run (`CN/plant:SC10600000000002`) is added to `product.json`, fixes a sodium OCR typo (`rev 4`), and later receives a corroborating photo from Bob in `evidence[]` **without** incrementing `rev` beyond `4`:

```json
{
  "opf_schema": "0.2",
  "id": "gtin:00000000000017",
  "edition_id": "01J8Z4K9M2N3P4Q5R6S7T8V9W0",
  "rev": 4,
  "track": "CN/plant:SC10600000000001",
  "supersedes": [],
  "core_fingerprint": "sha256:4a8d9b2c1e0f3a5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b",
  "label_fingerprint": "sha256:9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c3b2a1f0e9d8c7b6a5f4e3d2c1b0a9f8e",
  "core": {
    "regulatory_profile": "CN/GB28050-2011",
    "net_content": [{ "value": "900", "unit": "ml" }],
    "nutrition_declared": {
      "basis": { "value": "100", "unit": "ml" },
      "rows": [
        { "nutrient": "energy", "value": "0", "unit": "kJ", "nrv_pct": "0" },
        { "nutrient": "protein", "value": "0", "unit": "g", "nrv_pct": "0" },
        { "nutrient": "fat_total", "value": "0", "unit": "g", "nrv_pct": "0" },
        { "nutrient": "carbs_available", "value": "0", "unit": "g", "nrv_pct": "0" },
        { "nutrient": "sodium", "value": "18", "unit": "mg", "nrv_pct": "1" }
      ]
    },
    "ingredients_tree": [
      {
        "lang": "zh-Hans",
        "nodes": [
          { "name": "水" },
          { "name": "茉莉花茶", "qualifier": "≥4g/L", "children": [{ "name": "绿茶茶坯" }] },
          { "name": "维生素C", "ins": "300", "is_additive": true },
          { "name": "碳酸氢钠", "ins": "500(ii)", "is_additive": true }
        ]
      }
    ],
    "allergens_declared": { "contains": [], "may_contain": [] }
  },
  "attributes": {
    "product_name": [{ "lang": "zh-Hans", "text": "无糖茉莉清茶" }],
    "brand": "示例茶坊",
    "declared_category": "原味茶饮料",
    "ingredients_text": [
      { "lang": "zh-Hans", "text": "配料：水、茉莉花茶（绿茶茶坯）（≥4g/L）、维生素C、碳酸氢钠" }
    ],
    "product_standard": ["GB/T 21733"],
    "shelf_life": { "value": "9", "unit": "month" },
    "packaging_code": "SMP-900-A1",
    "parties": [
      { "role": "commissioner", "name": "示例茶坊饮品有限公司" },
      { "role": "manufacturer", "name": "示例饮品一厂", "license": "SC10600000000001" }
    ]
  },
  "normalized": { "...": "compiled by opf normalize" },
  "quality_flags": [],
  "evidence": [
    {
      "evidence_id": "sha256:a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
      "type": "label_photo",
      "region": "nutrition_table",
      "cropped_sha256": "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
      "media_ref": "opf-media://sha256/a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90",
      "contributor": "github:alice",
      "reported_at": "2026-02-14",
      "vintage_month": "2026-01"
    },
    {
      "evidence_id": "sha256:b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1",
      "type": "label_photo",
      "region": "manufacturer_block",
      "cropped_sha256": "b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1",
      "media_ref": "opf-media://sha256/b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1",
      "contributor": "github:alice",
      "reported_at": "2026-02-15",
      "vintage_month": "2026-01"
    },
    {
      "evidence_id": "sha256:c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2",
      "type": "label_photo",
      "region": "full_back_label",
      "cropped_sha256": "c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2",
      "media_ref": "opf-media://sha256/c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2",
      "contributor": "github:bob",
      "reported_at": "2026-04-10",
      "vintage_month": "2026-03"
    }
  ],
  "revisions": [
    {
      "rev": 1,
      "kind": "initial",
      "created_at": "2026-02-14T10:15:00Z",
      "author": "github:alice",
      "evidence_refs": ["sha256:a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"],
      "patch": []
    },
    {
      "rev": 2,
      "kind": "enrichment",
      "created_at": "2026-02-15T09:20:00Z",
      "author": "github:alice",
      "evidence_refs": ["sha256:b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1"],
      "reason": "Add back-panel single-factory SC license, packaging code, and shelf life",
      "patch": [
        { "op": "add", "path": "/attributes/packaging_code", "value": "SMP-900-A1" },
        { "op": "add", "path": "/attributes/shelf_life", "value": { "value": "9", "unit": "month" } },
        {
          "op": "add",
          "path": "/attributes/parties",
          "value": [
            { "role": "commissioner", "name": "示例茶坊饮品有限公司" },
            { "role": "manufacturer", "name": "示例饮品一厂", "license": "SC10600000000001" }
          ]
        }
      ],
      "reverse_patch": [
        { "op": "remove", "path": "/attributes/parties" },
        { "op": "remove", "path": "/attributes/shelf_life" },
        { "op": "remove", "path": "/attributes/packaging_code" }
      ]
    },
    {
      "rev": 3,
      "kind": "retrack",
      "created_at": "2026-03-02T08:40:00Z",
      "author": "github:maintainer",
      "evidence_refs": ["sha256:b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90a1"],
      "reason": "Split from CN/default after concurrent second single-plant edition (SC10600000000002) was added",
      "patch": [
        { "op": "replace", "path": "/track", "value": "CN/plant:SC10600000000001" }
      ],
      "reverse_patch": [
        { "op": "replace", "path": "/track", "value": "CN/default" }
      ]
    },
    {
      "rev": 4,
      "kind": "errata",
      "created_at": "2026-03-05T12:00:00Z",
      "author": "github:alice",
      "evidence_refs": ["sha256:a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"],
      "reason": "Fix sodium transcription typo (16mg -> 18mg) verified against nutrition crop",
      "patch": [
        { "op": "replace", "path": "/core/nutrition_declared/rows/4/value", "value": "18" }
      ],
      "reverse_patch": [
        { "op": "replace", "path": "/core/nutrition_declared/rows/4/value", "value": "16" }
      ]
    }
  ]
}
```

---

### 8.5 Concurrent PR Deduplication, Collision-Free Evidence IDs & Redirects (`merged_into`)

When two contributors concurrently open PRs for the same package, or when an `errata` revision fixes a typo so two editions on the same `(id, track)` converge to the same `core_fingerprint`:

1. **Collision-Free `evidence_id` for Safe Merging**:
   - Every `label_photo` item MUST use content-addressed `"evidence_id": "sha256:<cropped_sha256>"`.
   - Non-photo evidence items (`community_report`, `registry_check`, `official_document`, `official_registry_import`) MUST use `"sha256:<snapshot_sha256>"` (when a snapshot hash exists) or `"ev:<ulid>"` (`ev:` + 26-char ULID).
   - Sequential local IDs (such as `"ev-01"`) are forbidden, guaranteeing zero ID collisions when migrating `evidence[]` between merged editions.
2. **CI Duplicate `core_fingerprint` Check**:
   - Within the same `(id, track)`, two non-redirect, **non-retracted** editions MUST NOT share an identical `core_fingerprint` unless linked by `supersedes` (`retracted` editions are excluded from duplicate detection).
3. **Consolidation via `EditionRedirect`**:
   - The duplicate Edition's `evidence[]` (deduplicated by `evidence_id`) and non-conflicting `attributes` are merged into the surviving canonical ULID, and the absorbed file `editions/<absorbed_ulid>.json` is replaced—never deleted—with a redirect stub:
     ```json
     {
       "opf_schema": "0.2",
       "id": "gtin:00000000000017",
       "edition_id": "01J9A2B3C4D5E6F7G8H9J0K1M2",
       "merged_into": "01J8Z4K9M2N3P4Q5R6S7T8V9W0",
       "merged_into_rev": 2,
       "merged_at": "2026-03-03",
       "reason": "Duplicate concurrent submission of identical edition"
     }
     ```
   - Redirect chains MUST NOT contain cycles and MUST point directly to a live `EditionRecord` in the same product directory (chain length = 1).

---

### 8.6 `supersedes` Graph & Deterministic Build-Time Derivation (`status` & `evidence_level`)

Edition files store **neither `status` nor `evidence_level`**. Both are derived deterministically by `opf build`.

#### Build-Time `evidence_level` Derivation
For each `EditionRecord` $E$, let $P(E)$ be the set of distinct non-empty `contributor` identifiers across `evidence[]` items with `type == "label_photo"`, valid `cropped_sha256`, and `media_ref`:
1. `corroborated`: $|P(E)| \ge 2$.
2. `verified`: $|P(E)| = 1$.
3. `official_registry_imported`: $|P(E)| = 0$ and $\exists e \in E.\text{evidence}$ with `type` in `{"official_registry_import", "official_document"}`.
4. `community_reported`: otherwise.

#### `supersedes` Graph & `lifecycle` Constraints
- Replacement edges are recorded on the **newer** Edition file as `"supersedes": ["<older_ulid>", ...]` (sorted, unique ULIDs), supporting 1-to-1, N-to-1, and 1-to-N transitions across a DAG (no self-loops, no cycles).
- **Retracted Isolation**: An edition with `lifecycle.state == "retracted"` MUST NOT appear in any edition's `supersedes[]`, MUST NOT carry non-empty `supersedes[]`, and is excluded from duplicate checks and active resolution.
- **Discontinued Exit for Track Heads**: Because a track's latest edition ($E_{\text{head}}$) never auto-decays to `stale`, **`lifecycle.state = "discontinued"` (backed by verifiable evidence in `evidence_refs`) is the sole mechanism by which a track head exits `active` status** (preventing wholly discontinued products from appearing in-market forever).

#### `vintage_month` vs. `reported_at` & Effective Market Timestamp (`t_active`)
To prevent old pantry stock photographed years later from refreshing a retired edition back to `active`:
- Every evidence item records `reported_at` (`YYYY-MM` or `YYYY-MM-DD`) and optional coarse `vintage_month` (`YYYY-MM`, derived from package production month or `expiry_month - shelf_life`; exact lot timestamps remain forbidden).
- For any Edition $E$, let $V(E) = \{ e.\text{vintage\_month} \mid e \in E.\text{evidence},\ e.\text{vintage\_month is present} \}$ and $R(E) = \{ e.\text{reported\_at}[0..7] \mid e \in E.\text{evidence} \}$:
  $$t_{\text{active}}(E) = \begin{cases} \max V(E) & \text{if } V(E) \neq \emptyset \\ \min R(E) & \text{if } V(E) = \emptyset \end{cases}$$
  When `vintage_month` exists, **only `vintage_month` governs active market presence**; when absent on all evidence items, $t_{\text{active}}(E)$ stays pinned to the earliest `reported_at` month $\min R(E)$, so un-dated `reported_at` uploads prove only historical existence and can **never** re-activate a `stale` edition.

#### Build-Time `status` Precedence (`opf build`)
1. `retracted`: `E.lifecycle.state == "retracted"`.
2. `discontinued`: `E.lifecycle.state == "discontinued"`.
3. `superseded`: $\exists E' \text{ (non-retracted)}$ in the same product with $E.\text{edition\_id} \in E'.\text{supersedes}$ (`opf build` emits `superseded_by: [E'.edition_id, ...]`).
4. `stale`: Among remaining candidates on the same `track`, let $E_{\text{head}}$ maximize $(t_{\text{active}}, \text{regulatory\_standard\_year}, \text{packaging\_code})$ and let:
   $$N(E) = \operatorname{clamp}\big(\text{months}(E.\text{attributes.shelf\_life}),\ 3,\ 18\big) \quad (\text{default } 12 \text{ if } \text{shelf\_life} \text{ is absent})$$
   If $\text{months\_between}\big(t_{\text{active}}(E),\ t_{\text{active}}(E_{\text{head}})\big) \ge N(E)$, then $E$ is derived as `stale`.
5. `active`: All remaining editions on every track.

---

### 8.7 Compact API Resolution (`single | uniform | divergent | inactive`)

Let $A$ be the set of editions with derived status `active` across all tracks of a product:

1. **Per-Edition vs. Summary Evidence Level (`evidence_summary`)**:
   - Top-level Compact API emits `evidence_summary: { "highest_active": ..., "lowest_active": ..., "by_edition": { ... } }` so a newly submitted `community_reported` variant never demotes a `corroborated` product in catalog rankings while keeping unverified variants visible.
2. **Top-Level `resolution` Modes**:
   - `"single"` ($|A| = 1$): One active edition. Top-level `normalized`, `ingredients_text`, `net_content`, `regulatory_profile`, `origin_summary`, and `parties_summary` are populated directly.
   - `"uniform"` ($|A| \ge 2$, $|\{E.\text{core\_fingerprint} \mid E \in A\}| = 1$): Multiple active tracks share the **identical `core`**. Top-level `normalized`, `ingredients_text`, and `net_content` are populated normally, while `origins_summary` and `parties_summary` report the deduplicated union across active tracks.
   - `"divergent"` ($|A| \ge 2$, $|\{E.\text{core\_fingerprint} \mid E \in A\}| \ge 2$): Active editions differ in `core`. Top-level **`normalized` and `ingredients_text` are omitted**; instead, `common_summary`, `disambiguation`, and `variants[]` are emitted:
     - **`nutrient_ranges_not_for_logging`**: Min/max bounds across active variants that declare each nutrient. If a nutrient is declared on only a subset of active variants, `"partial": true` MUST be set (`"declared_in_variants"` < total active variants). **Agents MUST NOT use `nutrient_ranges_not_for_logging` (min, max, or midpoint) to log dietary intake; Agents MUST disambiguate with the user and select a concrete `edition_id` from `variants[]` first.**
     - **`allergens_union` Separation Rule**: `contains` ($\bigcup_{E \in A} E.\text{normalized.allergens.contains}$) and `may_contain` ($\bigcup_{E \in A} E.\text{normalized.allergens.may\_contain} \setminus \text{contains}$) MUST be aggregated **separately**—a Precautionary Allergen Labeling (`may_contain`) entry on one variant MUST NEVER be promoted into `contains`, and MUST NEVER be dropped.
   - `"inactive"` ($|A| = 0$, e.g., all track heads marked `discontinued`): Top-level `normalized` is omitted; `editions_summary` lists historical editions.

#### Example: Compact API (`/v1/gtin/000/000/00000000000116.json`) in `divergent` Mode

```json
{
  "opf_schema": "0.2",
  "id": "gtin:00000000000116",
  "resolution": "divergent",
  "active_edition_ids": [
    "01J8Z8AA11BB22CC33DD44EE55",
    "01J8Z9FF66GG77HH88JJ99KK00"
  ],
  "edition_redirects": {
    "01J8Z8ZZ00YY11XX22WW33VV44": "01J8Z8AA11BB22CC33DD44EE55"
  },
  "evidence_summary": {
    "highest_active": "corroborated",
    "lowest_active": "verified",
    "by_edition": {
      "01J8Z8AA11BB22CC33DD44EE55": "corroborated",
      "01J8Z9FF66GG77HH88JJ99KK00": "verified"
    }
  },
  "brand": "示例乳业",
  "product_name": [{ "lang": "zh-Hans", "text": "调制乳饮料" }],
  "common_summary": {
    "basis": "100ml",
    "net_content_values": [{ "value": "250", "unit": "ml" }],
    "nutrient_ranges_not_for_logging": {
      "energy_kcal": { "min": "65", "max": "72.2", "unit": "kcal" },
      "protein": { "min": "3.2", "max": "3.6", "unit": "g" },
      "fat_total": { "min": "3.8", "max": "4.4", "unit": "g" },
      "carbs_available": { "min": "4.8", "max": "5", "unit": "g" },
      "sodium": { "min": "55", "max": "68", "unit": "mg" },
      "calcium": { "min": "125", "max": "125", "unit": "mg", "partial": true, "declared_in_variants": 1, "total_variants": 2 }
    },
    "allergens_union": {
      "contains": ["milk"],
      "may_contain": ["soy"]
    },
    "additives_ins_union": ["407", "471"],
    "differing_fields": ["nutrients", "ingredients", "allergens.may_contain", "origin", "parties"]
  },
  "disambiguation": {
    "mode": "by_track",
    "tracks_guide": [
      {
        "track": "CN/plant:SC10500000000001",
        "market": "CN",
        "edition_id": "01J8Z8AA11BB22CC33DD44EE55",
        "discriminator": {
          "method": "sc_license",
          "field": "attributes.parties[].license",
          "instructions": [
            { "lang": "zh-Hans", "text": "华北单厂印版：背面生产商仅印示例乳业一厂（SC10500000000001），标示含钙 125mg/100ml" },
            { "lang": "en", "text": "North Zone single-plant label: prints only Plant A (SC10500000000001), declares calcium 125mg/100ml" }
          ]
        }
      },
      {
        "track": "CN/plant:SC10500000000002",
        "market": "CN",
        "edition_id": "01J8Z9FF66GG77HH88JJ99KK00",
        "discriminator": {
          "method": "sc_license",
          "field": "attributes.parties[].license",
          "instructions": [
            { "lang": "zh-Hans", "text": "华南单厂印版：背面生产商仅印示例乳业二厂（SC10500000000002），未标示钙，产线提示可能含有大豆制品" },
            { "lang": "en", "text": "South Zone single-plant label: prints only Plant B (SC10500000000002), no calcium row, shared line may contain soy" }
          ]
        }
      }
    ]
  },
  "variants": [
    {
      "edition_id": "01J8Z8AA11BB22CC33DD44EE55",
      "rev": 2,
      "track": "CN/plant:SC10500000000001",
      "evidence_level": "corroborated",
      "regulatory_profile": "CN/GB28050-2011",
      "core_fingerprint": "sha256:1111111111111111111111111111111111111111111111111111111111111111",
      "label_fingerprint": "sha256:2222222222222222222222222222222222222222222222222222222222222222",
      "t_active": "2026-09",
      "net_content": [{ "value": "250", "unit": "ml" }],
      "origin": { "country": "CN", "region": "华北示例区" },
      "parties_summary": [
        { "role": "manufacturer", "name": "示例乳业一厂", "license": "SC10500000000001" }
      ],
      "product_standard": ["Q/SLRY 0002S"],
      "normalized": {
        "basis": "100ml",
        "nutrients": {
          "energy_kj": { "value": "302", "unit": "kJ", "basis": "reported" },
          "energy_kcal": { "value": "72.2", "unit": "kcal", "basis": "derived" },
          "protein": { "value": "3.6", "unit": "g", "basis": "reported" },
          "fat_total": { "value": "4.4", "unit": "g", "basis": "reported" },
          "carbs_available": { "value": "5", "unit": "g", "basis": "reported" },
          "sodium": { "value": "55", "unit": "mg", "basis": "reported" },
          "salt_equivalent": { "value": "0.14", "unit": "g", "basis": "derived" },
          "calcium": { "value": "125", "unit": "mg", "basis": "reported" }
        },
        "additives_ins": [],
        "allergens": {
          "contains": ["milk"],
          "declared_contains": ["milk"],
          "inferred_from_ingredients": ["milk"],
          "may_contain": []
        }
      },
      "ingredients_text": [{ "lang": "zh-Hans", "text": "配料：生牛乳、碳酸钙、维生素D" }],
      "quality_flags": [
        { "code": "SALT_DERIVED_FROM_SODIUM", "field": "salt_equivalent", "detail": "Derived from sodium using ratio 2.5" }
      ]
    },
    {
      "edition_id": "01J8Z9FF66GG77HH88JJ99KK00",
      "rev": 1,
      "track": "CN/plant:SC10500000000002",
      "evidence_level": "verified",
      "regulatory_profile": "CN/GB28050-2011",
      "core_fingerprint": "sha256:3333333333333333333333333333333333333333333333333333333333333333",
      "label_fingerprint": "sha256:4444444444444444444444444444444444444444444444444444444444444444",
      "t_active": "2026-10",
      "net_content": [{ "value": "250", "unit": "ml" }],
      "origin": { "country": "CN", "region": "华南示例区" },
      "parties_summary": [
        { "role": "manufacturer", "name": "示例乳业二厂", "license": "SC10500000000002" }
      ],
      "product_standard": ["Q/SLRY 0002S"],
      "normalized": {
        "basis": "100ml",
        "nutrients": {
          "energy_kj": { "value": "272", "unit": "kJ", "basis": "reported" },
          "energy_kcal": { "value": "65", "unit": "kcal", "basis": "derived" },
          "protein": { "value": "3.2", "unit": "g", "basis": "reported" },
          "fat_total": { "value": "3.8", "unit": "g", "basis": "reported" },
          "carbs_available": { "value": "4.8", "unit": "g", "basis": "reported" },
          "sodium": { "value": "68", "unit": "mg", "basis": "reported" },
          "salt_equivalent": { "value": "0.17", "unit": "g", "basis": "derived" }
        },
        "additives_ins": ["407", "471"],
        "allergens": {
          "contains": ["milk"],
          "declared_contains": ["milk"],
          "inferred_from_ingredients": ["milk"],
          "may_contain": ["soy"]
        }
      },
      "ingredients_text": [
        { "lang": "zh-Hans", "text": "配料：生牛乳、单，双甘油脂肪酸酯、卡拉胶、维生素D" }
      ],
      "quality_flags": [
        { "code": "SALT_DERIVED_FROM_SODIUM", "field": "salt_equivalent", "detail": "Derived from sodium using ratio 2.5" }
      ]
    }
  ],
  "editions_summary": [
    {
      "edition_id": "01J8Z8AA11BB22CC33DD44EE55",
      "rev": 2,
      "track": "CN/plant:SC10500000000001",
      "status": "active",
      "t_active": "2026-09",
      "evidence_level": "corroborated",
      "core_fingerprint": "sha256:1111111111111111111111111111111111111111111111111111111111111111"
    },
    {
      "edition_id": "01J8Z9FF66GG77HH88JJ99KK00",
      "rev": 1,
      "track": "CN/plant:SC10500000000002",
      "status": "active",
      "t_active": "2026-10",
      "evidence_level": "verified",
      "core_fingerprint": "sha256:3333333333333333333333333333333333333333333333333333333333333333"
    }
  ],
  "full_url": "/v1/gtin/000/000/00000000000116.full.json"
}
```

---

## 9. Evidence Media (Three-Layer Content-Addressed Vault)

| Layer | Holds | Published? |
| :--- | :--- | :--- |
| L0 private vault | Uncropped originals (exact lot codes, all faces, burst frames) | No |
| L1 public media host | EXIF-stripped WebP crops (`<= 1000px`) of functional text-only label regions (no front cover art) | Yes |
| L2 `opf-data` git repo | Hashes, content-addressed / ULID `evidence_id` handles, coarse `vintage_month`, and references only (no image binaries) | Yes |

Canonical `region` enum (7 functional values; front-of-pack cover artwork such as `front_of_pack` or `front_thumb` is strictly prohibited to avoid packaging copyright issues):
- `nutrition_table`, `ingredients_box`, `allergen_statement`, `manufacturer_block`, `barcode_net_content`, `full_back_label`, `other`.

`label_photo` evidence fields:
- `evidence_id`: Content-addressed `"sha256:<cropped_sha256>"` for `label_photo` items (or `"sha256:<snapshot_sha256>"` / `"ev:<ulid>"` for non-photo items), collision-free across merged editions.
- `cropped_sha256`: 64-hex SHA-256 of the public EXIF-stripped cropped image.
- `vault_raw_sha256`: Optional 64-hex SHA-256 of the private original in L0, serving as a proof-of-existence anchor.
- `media_ref`: `http(s)://…`, `media/…`, or location-independent `opf-media://sha256/<64-hex>` (whose `<64-hex>` must match `cropped_sha256`).
- `reported_at`: Contributor observation/submission date (`YYYY-MM` or `YYYY-MM-DD`).
- `vintage_month`: Optional coarse package production/vintage month (`YYYY-MM`); exact batch dates (`YYYY-MM-DD`), lot serial numbers, purchase dates, and prices are strictly forbidden in `opf-data`.
- `specimen_id`: Optional specimen grouping tag (`^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`) linking multiple cropped photos captured from the same physical package in one submission.
- `artwork_note`: Optional note for artwork-only variants (e.g., `"2026 Spring Festival limited pack"`) whose printed text and `core` are unchanged.

`opf-media://sha256/<hex>` resolves to `{media_base_url}/media/<hex[0:2]>/<hex[2:4]>/<hex>.webp`. `media_base_url` is deployment config (`opf build --media-base-url …`, published in `/v1/meta.json`), so repository data never embeds a host name.
