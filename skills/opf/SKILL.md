---
name: opf
description: Queries, verifies, disambiguates, and contributes industrial packaged food records via OpenPackagedFood (opf v0.3) static HTTP endpoints, Phase 2 HTTP Relay (`OPF_SUBMIT_URL`), and developer pure-Git / CLI workflows. Activate this skill whenever a user asks about packaged food nutrition, ingredients, INS/E-number additives, allergens, co-packer SC/plant codes, pre-purchase food comparisons, or packaging label extraction.
---

# OpenPackagedFood (`opf` v0.3) Agent Skill

> **Core Invariant**: Evidence first, zero judgment. Answer the user's question thoroughly and objectively **first**; never gate help behind contribution, never fabricate missing numbers, never treat `<` regulatory upper bounds as exact `0`, never log intake from `divergent` ranges, never call records "verified" or "safe", and never emit subjective health scores.

- **Tooling & CLI Repository**: `https://github.com/mickey996icu/open-packaged-food`
- **Product Database Repository**: `https://github.com/mickey996icu/opf-data`
- **Cropped Label Media Repository**: `https://github.com/mickey996icu/opf-media`

### Regional Jurisdictions & Languages Matrix

| Jurisdiction / Market | Regulatory Profile | Data Language Tags (`lang`) | Web UI Locale |
| :--- | :--- | :--- | :--- |
| **CN** (China Mainland) | `CN/GB28050-2011` / `CN/GB28050-2025` | `zh-Hans` | `zh-CN` (简体中文) |
| **HK** (Hong Kong SAR) | `HK/CFS-132W` | `zh-Hant`, `en` | `zh-CN`, `en` |
| **SG** (Singapore) | `SG/SFA-FR` | `en`, `zh-Hans`, `ms` | `en`, `zh-CN` |
| **MY** (Malaysia) | `MY/MOH-R18B` | `ms`, `en`, `zh-Hans` | `en`, `zh-CN` |
| **KR** (South Korea) | `KR/MFDS-2024` | `ko` | `ko` (한국어) |
| **AU / NZ** (Australia & New Zealand) | `AU/FSANZ-1.2.8` *(use `track: "AU/default"` or `"NZ/default"`)* | `en` | `en` (English) |
| **US** (United States) | `US/FDA-NLEA` | `en` | `en` (English) |
| **JP** (Japan) | `JP/CAA-2015` | `ja` | `ja` (日本語) |
| **EU / UK** | `EU/1169-2011` | `en`, `de`, `fr`, `es`, `it` *(plus any EU BCP-47 tag printed verbatim)* | `en`, `de`, `fr`, `es`, `it` |

---

## Step 1 — Query OPF First via Pure HTTP (Zero CLI Required)

- **Default Base URL**: `<OPF_BASE_URL>` = `https://mickey996icu.github.io/opf-data` (override when `OPF_BASE_URL` env var points to a mirror or local `./bin/opf serve`).
- **Always query read-only HTTP first before asking the user for photos**:
  1. **Barcode known (GTIN-8 / GTIN-12 / GTIN-13 / GTIN-14)**:
     - Left-pad with zeros to 14 digits (`gtin14`, e.g. `0000000000017` -> `00000000000017`).
     - Shards: `p1 = gtin14[1:4]` (`000`), `p2 = gtin14[4:7]` (`000`).
     - Fetch Compact doc (1 `GET`): `GET <OPF_BASE_URL>/v1/gtin/{p1}/{p2}/{gtin14}.json`.
  2. **Brand / product name / shopping comparison** (e.g. `"Does Demo Tea Lab Jasmine Tea have sodium?"`, `"示例茶坊和某款无糖茶哪个钠低？"`):
     - **Preferred scalable path (whenever a brand name is known)**:
       1. Fetch `GET <OPF_BASE_URL>/v1/index/brands.json` first (tiny brand directory containing `brand_slug`, primary `brand`, multilingual `brand_names`, `count`, and `index_url`).
       2. Match the brand across `brand` or `brand_names`, then fetch **only** that brand's product index `GET <OPF_BASE_URL>/v1/index/brand/{brand_slug}.json`, and select the matching `compact_url`.
     - **Fallback path (only when the brand is unknown or doing cross-brand nutrient/additive comparisons)**:
       - Fetch `GET <OPF_BASE_URL>/v1/index/catalog.jsonl` as a fallback (lightweight line-per-product index containing localized `names`, `brand`, `brand_names`, `resolution`, `nutrients_100`, `additives_ins`, `allergens_contains`, `compact_url`), noting it scales linearly with total catalog size—so always prefer `brands.json` -> `brand/{brand_slug}.json` first whenever a brand is mentioned.
     - Fetch the selected product's `compact_url` (or `full_url` when needing raw `core.nutrition_declared`, `evidence[]`, UI spans, or `<edition_id>@<rev>` history).

### 1.1 Mandatory Interpretation Rules
1. **Dispatch by Compact `resolution`**:
   - `"single"`: Use top-level `normalized`, `ingredients_text`, `quality_flags`, `active_tracks`, and `evidence_summary.highest_active`.
   - `"uniform"`: Multiple tracks share an identical `core_fingerprint`; top-level `normalized` and `ingredients_text` apply to every track in `active_tracks`; show `origins_summary` / `parties_summary`.
   - `"divergent"`: Top-level `normalized` and `ingredients_text` are **intentionally omitted**. **HARD PROHIBITION**: **Never log intake or state exact nutrient values from `common_summary.nutrient_ranges_not_for_logging`** (`min`, `max`, or midpoint). Ask the user to check the physical package against `disambiguation.tracks_guide[]` (`SC` code, plant code, net content, printed numbers) to choose one `edition_id` from `variants[]`. When previewing ranges beforehand, check `"partial": true` (`declared_in_variants < total_variants` != `0`) and keep `allergens_union.contains` separate from `may_contain`.
   - `"inactive"`: `active_edition_ids` is `[]` (no current market edition); warn the user and inspect `editions_summary` / `.full.json` for archival facts.
2. **Follow `edition_redirects` & `@<rev>` semantics**: Follow `edition_redirects[old_ulid]` if present. Remember `<edition_id>@<rev>` locks `/core`, `/attributes`, `/track`, `/supersedes`, and `/lifecycle` only (adding `evidence[]` never bumps `rev`).
3. **Describe `evidence_level`, `t_active`, & `<` upper bounds factually (NEVER claim "verified" or "safe")**:
   - State `evidence_level` strictly by **what evidence exists**—**NEVER** output words like *"verified"*, *"certified"*, *"已核验"*, *"已验证"*, or imply transcription was manually checked against photos or that the product is safe:
     - `corroborated` -> *"label photos from 2 or more accounts"* / *"有 2 个以上账号上传过标签照片"*
     - `verified` -> *"1 label photo submitted"* / *"有 1 份标签照片"* (does NOT prove transcription matches the photo)
     - `official_registry_imported` -> *"From public official registry"* / *"来自官方公开信息"*
     - `community_reported` -> *"Text report only (no photo)"* / *"仅有文字报告，无照片"*
   - Describe `t_active` using `t_active_basis` (or presence of `vintage_month`): *"Latest package vintage seen: YYYY-MM (formulation may have changed since)"* when `vintage_month` exists; otherwise *"Earliest reported: YYYY-MM"*.
   - Report `{"qualifier": "<", "basis": "regulatory_upper_bound", ...}` explicitly as **`< value unit` (regulatory rounding upper bound)**, never exact `0`. Surface `quality_flags` clearly.
   - When `nutrition_exemption` is present (and `normalized.nutrients` is `{}` / `NUTRITION_LABEL_EXEMPT` in `quality_flags`), explain that the product is **legally exempt from mandatory nutrition labeling** and prints no nutrition table (never treat `{}` as `0 kcal`); surface `special_indicators` (e.g. mineral ions, pH, tea polyphenols) and `quality_grade` if present.
   - **Mandatory Allergen & Safety Caveat**: Whenever answering any query involving allergens (whether from OPF database records or photo reading), **ALWAYS** include an explicit reminder in the user's language that OPF records cover printed label text only (excluding unprinted cross-contact or shared-line risks, and formulations may vary by batch/plant): *"一切以手头实物包装实际印刷为准"* / *"Always check and rely on the physical package in hand."*

---

## Step 2 — Cold-Start `404` Iron Rule & Strict Contribution Gating

If OPF returns HTTP `404` (or the user's product is not yet indexed):

1. **Request Functional Label Crops Only**:
   Ask the user for clear close-up photos of **factual text regions only**:
   - **Nutrition Facts table** (`nutrition_table`),
   - **Ingredients list** (`ingredients_box`),
   - **Allergen / Manufacturer & `SC` plant block** (`allergen_statement`, `manufacturer_block`), and
   - **Barcode / Net content** (`barcode_net_content`).
   **Explicitly instruct the user NOT to upload full front-of-pack cover artwork** (minimizes packaging copyright risk and keeps OCR sharp).

2. **IRON RULE — Answer First Without Gating + Vision & Allergen Caveats**:
   - The moment the user sends photos, **FIRST give a complete, high-value, objective reading of what appears in the photos** (macros per `100g`/`100ml` and per serving, sodium/sugar/fat/protein breakdown, Codex INS / E-number additives printed, declared allergens, `SC`/plant info, regulatory rounding caveats)—**always alongside mandatory accuracy/allergen warnings**:
     - Explicitly state that **AI vision/OCR reading of label photos may contain errors—please verify against the physical package** (*"AI 照片识读可能有误，请对照包装实物原文核对"*).
     - Whenever allergens are discussed, **explicitly attach**: printed text only (no unprinted factory cross-contact or shared-line guarantees), and ***"一切以手头实物包装实际印刷为准" / "Always check and rely on the physical package in hand."***
   - **Never withhold or gate your answer behind uploading data**, and never make the user experience slower or worse than asking a general assistant directly.

3. **Strict Contribution Trigger Gate (Never Disappoint Everyday Users)**:
   Before deciding whether to mention contribution or output `draft.json`, check the environment and user context:
   - **Eligible Condition (either a or b holds)**:
     - **a.** `OPF_SUBMIT_URL` is configured in the environment (Phase 2 HTTP Relay for Agent submission—open to **all** users); **OR**
     - **b.** A **developer environment** is detected (a local `opf-data` Git clone exists in the workspace/environment, OR the user explicitly identifies themselves as a developer/contributor).
   - **Everyday User Environment (`OPF_SUBMIT_URL` is NOT set AND non-developer environment)**:
     - Deliver your complete, objective buying answer and **STOP**.
     - **DO NOT** mention contributing, **DO NOT** invite the user to submit, and **DO NOT** proactively output `draft.json`.
     - **ONLY** if the user **explicitly asks** for structured JSON / `draft.json`, generate and share a valid `draft.json` based on [examples/draft.minimal.json](./examples/draft.minimal.json).
   - **Eligible Environment (`OPF_SUBMIT_URL` set OR developer environment)**:
     After finishing the complete answer, you may append the 1-line opt-in contribution invitation in **the user's own conversation language** (`zh-CN`, `en`, `ja`, `de`, `fr`, `es`, `it`, etc.):
     - **`zh-CN`**: *"顺便我已把刚识别的标签整理成标准档案（仅保留局部功能文字标签图并自动抹除 EXIF 拍摄时间与 GPS 定位），需要顺手贡献到 OpenPackagedFood 公共库帮后面的人省事吗？"*
     - **`en`**: *"By the way, I've structured these label facts into a standard record (keeping only cropped text-panel images with EXIF timestamp/GPS stripped)—would you like me to contribute it to the public OpenPackagedFood database to help future shoppers?"*
     - **`ja`**: *"あわせて、読み取った表示内容を標準データ形式に整理しました（ラベル文字切り抜き画像のみ保持し EXIF 撮影日時・位置情報は自動削除します）。よろしければ OpenPackagedFood 公開データベースへ登録しませんか？"*
     - **`de`**: *"Übrigens habe ich diese Etikettdaten bereits strukturiert (nur zugeschnittene Textbereiche ohne EXIF-Metadaten) — soll ich den Eintrag für andere Einkaufende in OpenPackagedFood beitragen?"*
     - **`fr`**: *"Au passage, j'ai structuré ces mentions d'étiquette (uniquement des recadrages textuels sans métadonnées EXIF) — souhaitez-vous que je les contribue à la base publique OpenPackagedFood ?"*
     - **`es`**: *"Por cierto, ya he estructurado estos datos de la etiqueta (solo recortes de texto funcional sin metadatos EXIF); ¿quieres que los aporte a la base pública OpenPackagedFood?"*
     - **`it`**: *"Tra l'altro ho già strutturato questi dati dell'etichetta (solo ritagli testuali senza metadati EXIF): vuoi che li contribuisca al database pubblico OpenPackagedFood?"*

---

## Step 3 — Submission Channels (Only When Triggered & After Explicit User Consent)

Start from the minimal `v0.3` draft template [examples/draft.minimal.json](./examples/draft.minimal.json) when building the structured payload (`id`, `core`, `attributes`, `evidence`):
- **Statutory Nutrition Panel Exemption (`core.nutrition_declared: null` + `core.nutrition_exemption`)**: When a packaged food (such as packaged drinking water, plain tea leaves/coffee, single-ingredient raw food, salt/vinegar/spices, alcohol, small-surface-area packs, or general unclaimed prepackaged foods in jurisdictions like Singapore where NIP is optional absent nutrition claims) is legally exempt and prints **no** Nutrition Facts table on the package, **NEVER fabricate all-zero nutrient rows**. Set `"nutrition_declared": null` and `"nutrition_exemption": {"category": "packaged_water" | "tea_coffee_herbs" | "single_ingredient_unprocessed" | "salt_vinegar_spices" | "alcoholic_beverage" | "small_daily_intake" | "small_package_area" | "general_unclaimed_exempt", "legal_basis": "..."}`. Record characteristic indicators (e.g. natural water `钙`/`偏硅酸` `>=` bounds, dimensionless `{"name": "pH值(25℃)", "value": "7.3", "tolerance": "0.5"}`, interval `value_max`, `茶多酚`, or `A2β-酪蛋白`) in **`core.special_indicators`** (never in `attributes`), and record standard quality grades (e.g. `"特级"`, `"一级"`) in **`attributes.quality_grade`**.
- **Regulatory Profile Precision (`CN`, `HK`, `SG`, `MY`, `KR`, `AU/NZ`)**: Do **not** blindly copy `CN/GB28050-2011` from the minimal template:
  - **China Mainland (`CN`)**: If the Nutrition Facts table uses the **1+6 mandatory framework** (declaring both **saturated fat (`饱和脂肪`)** and **sugars (`糖`)**) or prints **`儿童青少年应避免过量摄入盐油糖`**, set `core.regulatory_profile` to **`"CN/GB28050-2025"`**; use `"CN/GB28050-2011"` only for legacy 1+4 tables.
  - **Hong Kong (`HK/CFS-132W`)**: Hong Kong Cap. 132W enforces the **1+7 mandatory framework** (`energy`, `protein`, `fat_total`, `fat_saturated`, `fat_trans`, `carbs_available` [or `carbs_total` when explicitly labeled "Total Carbohydrates / 總碳水化合物"], `sugars_total`, `sodium`) with Traditional Chinese (`zh-Hant`) and/or English (`en`) text. When an imported product bears a Hong Kong local compliance over-sticker, record that edition on `track: "HK/default"` with `"regulatory_profile": "HK/CFS-132W"` using the sticker's verbatim product name, ingredients, and 1+7 panel—never splice sticker names onto the foreign base panel or discard the sticker's 1+7 table.
  - **Singapore (`SG/SFA-FR`)**: Use `"SG/SFA-FR"` on `track: "SG/default"` for Singapore-market labels (English / Chinese / Malay). Under SFA Food Regulations, general prepackaged foods without nutrition/health claims (excluding Nutri-Grade C/D beverages and fortified foods) are not required to print an NIP—use `salt_vinegar_spices` (for spice packs) or `general_unclaimed_exempt` when no panel is printed.
  - **Malaysia (`MY/MOH-R18B`)**: Use `"MY/MOH-R18B"` on `track: "MY/default"` for Malaysian domestic labels (Food Regulations 1985 Reg. 18B mandatory 1+5: `energy`, `protein`, `fat_total`, `carbs_available` [or `carbs_total`], `sugars_total`, `sodium`, often alongside Bahasa Malaysia `Ramuan:` ingredients).
  - **South Korea (`KR/MFDS-2024`)**: Use `"KR/MFDS-2024"` on `track: "KR/default"` for Korean MFDS labels (9 mandatory nutrients: `energy`, `sodium`, `carbs_total`, `sugars_total`, `fat_total`, `fat_trans` [`<0.2g` zero bound], `fat_saturated`, `cholesterol`, `protein`, plus Korean statutory allergens including `pork`, `beef`, `chicken`, `peach`, `tomato`, `buckwheat`, `molluscs`, etc.).
  - **Australia & New Zealand (`AU/FSANZ-1.2.8`)**: FSANZ Standard 1.2.8 requires dual columns (`Per Serving` and `Per 100g`/`100mL`) with 1+6 rows (`energy` in `kJ`, `protein`, `fat_total`, `fat_saturated`, `carbs_available` [excluding fibre], `sugars_total`, `sodium` in `mg`; DI reference energy is `8700 kJ`). Transcribe the higher-precision `100g`/`100ml` column into `core.nutrition_declared` (recording `serving_size` alongside), preserve `LESS THAN` bounds as `qualifier: "<"`, and set `track` to `"AU/default"` or `"NZ/default"`.
- **Strictly Evidenced Cropped Text Only (Zero Un-Evidenced Claims & Optional `net_content`)**: Every recorded field (`core.net_content`, `attributes.claims_text`, `brand`, `net_content_label`) **must come strictly from the contributor's own cropped physical-package photos**—**NEVER** upload or crop merchant/e-commerce product graphics into `opf-media`, and **NEVER** guess or copy net weight from external web titles when no net-content crop is present. On bagged foods whose back label omits net weight and no front-corner text crop was taken, leave `"net_content": []` (empty array; whole-pack `per_unit` simply stays omitted while `per 100g`/`100ml` remains exact) and omit `net_content_label`.
- **Per-Serving Panels, Multi-Bracket Qualifiers & `parties[].license` Scope**:
  - When a label declares nutrition per serving (`"basis": {"value": "1", "unit": "serving"}` or `{"value": "56", "unit": "g"}`), always populate `core.serving_size` (`g`/`ml`/`kg`/`l`) so `opf normalize` scales accurately to `100g`/`100ml`.
  - In `core.ingredients_tree`, interval qualifiers (`"20%-25%"`), Roman-numeral INS subcodes (`"481(i)"`, `"160b(ii)"`), and word-bounded connectors (`and`, `dan`, `Mengandungi`, `yang dibenarkan`) are handled natively; join adjacent non-child bracket modifiers on a single ingredient with `"；"` or `"; "` (e.g. `"qualifier": "嫁接；添加量≥60%"`).
  - Reserve `attributes.parties[].license` strictly for **food-safety manufacturing/hygiene/import regulatory licenses** (e.g. China `SC...`, GACC `C...`, Korean MFDS report numbers); corporate/commercial registration suffixes (such as Malaysia SSM `1415058-W` or Singapore UEN) MUST stay verbatim inside `parties[].name` rather than `license`.
- **Multilingual `attributes` & EU Multi-Language Pack Rule**: `attributes.product_name` and `attributes.ingredients_text` are BCP-47 `LocalizedText[]` arrays preserving every language printed verbatim on the package. On multi-language EU labels (e.g., printed in `de`, `fr`, `es`, `it`, and `en`), capture each printed language verbatim as separate entries in `attributes.product_name[]`, `attributes.ingredients_text[]`, and `core.ingredients_tree[]`, whereas non-printed contributor translations (such as translated `"brand"` or `"product_name"` search aliases) belong in `attributes.translations[]` with `"source": "contributor_translated"`.

### 3.1 Privacy & Authenticity Guard (Non-Negotiable)
- **Permitted coarse month**: Only `vintage_month: "YYYY-MM"` (printed production month, or expiry month minus `shelf_life`) may appear in `evidence[]`.
- **Forbidden personal / exact batch fields**: **NEVER** include `purchase_date`, `purchase_price`, or day-precision `production_date`, `expiry_date`, `expiry_estimate`, or serial `lot_number` (keep purchase/pantry logs strictly in local private inventory logs).
- **No front-of-pack cover art & no fabricated hashes**: Never invent `cropped_sha256` or `media_ref` without real cropped, EXIF-stripped WebP images (`<= 1000px`). For text-only or official datasets, use `community_report` or `official_registry_import`.

### 3.2 Channel Selection
Pick the active submission path cleanly:

- **Channel A — HTTP Relay API (Phase 2, preferred for all users when `OPF_SUBMIT_URL` is set)**:
  Requires **zero Git, zero GitHub account, and zero CLI**:
  Send `POST <OPF_SUBMIT_URL>/v1/submissions` (`Content-Type: application/json`) with base64-encoded EXIF-stripped WebP crops (`<= 1000px`) for functional regions only:
  ```json
  {
    "schema_version": "0.3",
    "intent": "auto",
    "target_edition_id": null,
    "draft": { "...": "valid draft.minimal.json payload" },
    "media": [
      {
        "region": "nutrition_table",
        "specimen_id": "sp-1",
        "content_type": "image/webp",
        "sha256": "<64-hex>",
        "data_base64": "<base64 of <=1000px EXIF-stripped WebP>"
      }
    ]
  }
  ```
  (`intent`: `"auto" | "amend" | "supersede" | "new_variant"`). Valid `region` values: `nutrition_table`, `ingredients_box`, `allergen_statement`, `manufacturer_block`, `barcode_net_content`, `full_back_label`, `other` (never full cover art).

- **Channel B — Phase 1 Developer Primary Path (Standard Pure-Git Dual-PR Workflow)**:
  When `OPF_SUBMIT_URL` is not configured and working in a developer environment, follow the standard pure-Git workflow across the three repositories (`open-packaged-food`, `opf-data`, `opf-media`):
  1. Ensure the three repositories are cloned locally (or forked on GitHub and cloned side by side):
     ```bash
     git clone https://github.com/mickey996icu/open-packaged-food.git
     git clone https://github.com/mickey996icu/opf-data.git
     git clone https://github.com/mickey996icu/opf-media.git
     ```
  2. Write `draft.json`, strip/transcode functional label crops into `opf-media`, and generate product/edition files in `opf-data/products` (pass `--amend <ulid>`, `--supersede <ulid>`, or `--new-variant --track <track>` on conflict):
     ```bash
     ./open-packaged-food/bin/opf submit \
       --input draft.json \
       --out-dir opf-data/products \
       --photo nutrition_table=crop_nutrition.jpg \
       --photo ingredients_box=crop_ingredients.jpg \
       --vintage-month YYYY-MM \
       --media-out-dir opf-media
     ```
  3. Validate both repositories locally before pushing:
     ```bash
     ./open-packaged-food/bin/opf validate opf-data/products
     ./open-packaged-food/bin/opf validate-media opf-media
     ./open-packaged-food/bin/opf check-media-refs --media-dir opf-media opf-data/products
     ./open-packaged-food/bin/opf audit --media-dir opf-media opf-data/products
     ```
  4. Commit with DCO (`git commit -s`), push branches in **both** repositories, and open **cross-linked PRs with complete, non-empty descriptions** (when `gh` CLI is authenticated, prefer `./open-packaged-food/bin/opf pr --data-repo opf-data --media-repo opf-media ...` so both PR descriptions are generated and cross-linked automatically; if calling `gh pr create` manually: ① open the `opf-media` PR first with a non-empty description citing the `gtin:` ID and capture its real URL; ② open the `opf-data` PR pasting that exact `opf-media` PR URL; ③ run `gh pr edit` on the `opf-media` PR to backfill the `opf-data` PR URL — **never submit an empty PR description or leave unresolved placeholders like `<MEDIA_PR_URL>` or `填上...链接`, as CI `opf check-pr-meta` rejects them**):
     ```bash
     git -C opf-media switch -c contrib/media-label && git -C opf-media add -A && git -C opf-media commit -s -m "media(label): add cropped label evidence" && git -C opf-media push -u origin HEAD
     git -C opf-data switch -c contrib/product-record && git -C opf-data add -A && git -C opf-data commit -s -m "feat(product): add packaged food record" && git -C opf-data push -u origin HEAD
     ```
  5. **Strict Dual-PR Merge Order**: Always merge the **`opf-media` PR FIRST**, and then merge (or re-run CI and merge) the **`opf-data` PR SECOND** so `opf-data` CI (`opf check-media-refs`) verifies the WebP blobs exist on `opf-media/main`.

- **Optional One-Step Automation (`uvx` + `gh` CLI)**:
  Developers who already have `uvx` and an authenticated `gh` session (`gh auth status`) may optionally use `opf pr` instead of manual `git` branching/pushing:
  ```bash
  uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.3.4 \
    opf pr --input draft.json \
    --photo nutrition_table=crop_nutrition.jpg \
    --photo ingredients_box=crop_ingredients.jpg \
    --vintage-month YYYY-MM
  ```
  This optional shortcut automates WebP transcoding (`<= 1000px`, EXIF-free), validation, sparse shallow forks/checkouts, and opening the cross-linked dual PRs (`opf-media` first, `opf-data` second).
  By default, developer/CLI PRs tag new `evidence[]` and `revisions[]` entries with `"provenance": "external_contributor"`, whereas Phase 2 HTTP Relay (`OPF_SUBMIT_URL`) submissions receive `"public_submission"`; maintainers contributing under written agreements pass `--provenance {maintainer|brand_owner|partner}` and `--agreement-ref <id>`.

- **Graceful Local Fallback**:
  If `OPF_SUBMIT_URL` is unavailable and automated pushing cannot run, do **not** emit scary stack traces or errors—share the validated `draft.json` cleanly and point developers to the pure-Git contributor steps in `https://github.com/mickey996icu/open-packaged-food/blob/main/CONTRIBUTING.md`.

---

## Step 4 — Local Developer / Maintainer CLI Quick Reference

When working inside local checkouts (`./open-packaged-food/bin/opf` or via `uvx`):
- `opf parse-ingredients --lang zh-Hans --profile CN/GB28050-2011 "<text>"` — verify monotonic span-free AST (`--with-spans` for offsets)
- `opf sanitize-media <img...> --media-root opf-media` — transcode to `<= 1000px` EXIF-free content-addressed WebP (`--lossless-only` for legacy raw strip)
- `opf submit --input draft.json --out-dir opf-data/products [--photo region=img] [--media-out-dir opf-media] [--provenance external_contributor|...] [--agreement-ref REF]`
- `opf retrack` / `opf merge` / `opf lifecycle` — manage track splits, duplicate `EditionRedirect` stubs, `discontinued`/`retracted`
- `opf validate opf-data/products` — schema v0.3, GS1, DAG, patch replay, dual-layer `provenance`, `agreement_ref`, and privacy checks (pure stdlib)
- `opf validate-media opf-media` — pure-stdlib WebP dimension/EXIF/SHA-256 verification
- `opf check-media-refs --media-base-url https://raw.githubusercontent.com/mickey996icu/opf-media/main opf-data/products` — CI gate preventing orphan `opf-media://` refs
- `opf audit [--media-dir opf-media] [--strict] [--require-photo] opf-data/products` — deep semantic, SC/address, nutrition, sugar-source, allergen, and low-res WebP audit (`ERROR` / `WARN` / `INFO`)
- `opf check-pr-meta --repo-kind {tooling,data,media} ...` — CI gate verifying non-empty PR descriptions, resolved companion PR links, file scope, DCO sign-offs, and `provenance` anti-spoofing / immutability rules
- `opf build --data-dir ... --out-dir ... --media-base-url ...` & `opf serve` — compile and preview static `/v1/` + Explorer
