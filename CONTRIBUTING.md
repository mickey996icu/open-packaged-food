# Contributing to OpenPackagedFood (`opf`)

**[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)** · **[Live Explorer & API](https://mickey996icu.github.io/opf-data/)** · **[`opf-data` Repository](https://github.com/mickey996icu/opf-data)** · **[`opf-media` Repository](https://github.com/mickey996icu/opf-media)**

Thank you for contributing to **OpenPackagedFood (`opf` v0.3)**—an evidence-first, zero-judgment open database for global industrial packaged foods.

> **Contributor Scope (Phase 1 vs. Phase 2)**:
> - **Everyday Consumers**: Use the [Web Explorer](https://mickey996icu.github.io/opf-data/) for read-only lookup and client-side barcode/QR scanning, or install [`skills/opf`](skills/opf) in an AI Agent for label analysis. Everyday end-user submission opens in **Phase 2** once `OPF_SUBMIT_URL` HTTP Relay is deployed.
> - **Developers & Maintainers (Phase 1 Open Now)**: Contributions currently go through the developer **pure-Git dual-PR workflow** (or dictionary/profile PRs in `open-packaged-food`). GitHub Issues are reserved exclusively for bug reports, data errata, and official registry import proposals.

---

## Path 1: Developer Pure-Git Dual-PR Workflow (Primary Path)

### 1. Capture Functional Label Regions Only (Never Cover Artwork)
Photograph only crisp factual label areas:
- **Nutrition Panel** (`nutrition_table`): Full nutrient values, basis (`per 100g`/`100ml`/serving), `%DV` / `NRV%`;
- **Ingredients List** (`ingredients_box`): Complete verbatim ingredients text and percentage qualifiers;
- **Allergen / Manufacturer & Standards Block** (`allergen_statement`, `manufacturer_block`): Standard code (`GB/T ...`), co-packers, plant codes, licenses (`SC...`), and coarse `YYYY-MM` production month;
- **Barcode & Net Content** (`barcode_net_content`): GTIN and net weight/volume.
> Never upload full front-of-pack cover artwork—limiting crops to factual text regions minimizes copyright surface and keeps OCR legible.

### 2. Clone, Generate, Validate & Push Dual PRs
You can prepare `draft.json` starting from [`skills/opf/examples/draft.minimal.json`](skills/opf/examples/draft.minimal.json) (or generate it with an AI Agent running [`skills/opf`](skills/opf)).

1. **Clone the three repositories** (fork `opf-media` and `opf-data` under your GitHub account first if pushing from a fork):
   ```bash
   git clone https://github.com/mickey996icu/open-packaged-food.git
   git clone https://github.com/mickey996icu/opf-data.git
   git clone https://github.com/mickey996icu/opf-media.git
   ```
2. **Transcode label crops & generate product/edition JSON** (`<= 1000px` EXIF-free content-addressed WebP + normalized edition):
   ```bash
   ./open-packaged-food/bin/opf submit \
     --input draft.json \
     --out-dir opf-data/products \
     --photo nutrition_table=crop_nutrition.jpg \
     --photo ingredients_box=crop_ingredients.jpg \
     --vintage-month 2026-08 \
     --media-out-dir opf-media
   ```
   - On attribute conflicts or reformulations, re-run with `--amend <ulid>`, `--supersede <ulid>`, or `--new-variant --track CN/plant:SC...`.
3. **Run local validation across data and media** (pure Python 3.12 stdlib):
   ```bash
   ./open-packaged-food/bin/opf validate opf-data/products
   ./open-packaged-food/bin/opf validate-media opf-media
   ./open-packaged-food/bin/opf check-media-refs --media-dir opf-media opf-data/products
   ./open-packaged-food/bin/opf audit --media-dir opf-media opf-data/products
   ```
4. **Commit with DCO (`git commit -s`), push both branches, and click the terminal PR links**:
   ```bash
   git -C opf-media switch -c contrib/media-label && git -C opf-media add -A && git -C opf-media commit -s -m "media(label): add cropped label evidence" && git -C opf-media push -u origin HEAD
   git -C opf-data switch -c contrib/product-record && git -C opf-data add -A && git -C opf-data commit -s -m "feat(product): add packaged food record" && git -C opf-data push -u origin HEAD
   ```
5. **Mandatory Dual-PR Merge Order**: Always merge the **`opf-media` PR FIRST** so `opf-data` CI (`opf check-media-refs`) passes before merging the **`opf-data` PR SECOND**.

### Optional One-Step Automation (`uvx` + `gh` / Phase 2 HTTP Relay)
- **Optional Developer Shortcut (`uvx` + `gh`)**: Developers who prefer zero pre-cloning and already have `uvx` + authenticated `gh` (`gh auth login`) can optionally automate transcoding, sparse shallow forks, and dual-PR creation in one command:
  ```bash
  uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.3.4 \
    opf pr --input draft.json \
    --photo nutrition_table=crop_nutrition.jpg \
    --photo ingredients_box=crop_ingredients.jpg \
    --vintage-month 2026-08
  ```
- **Phase 2 Agent HTTP Relay (`OPF_SUBMIT_URL`)**: Once `OPF_SUBMIT_URL` is deployed in Phase 2, Agents will also submit via `POST <OPF_SUBMIT_URL>/v1/submissions` for everyday users without Git or CLI.

---

## Path 2: Contribute Regulatory Profiles & Dictionaries

Spot an unmapped food additive or want to expand support for a new jurisdiction? Edit the JSON dictionaries and open a PR against [`mickey996icu/open-packaged-food`](https://github.com/mickey996icu/open-packaged-food):

- **Food Additives (Codex INS / E-numbers / GB 2760)**: [`dictionaries/additives_ins.json`](dictionaries/additives_ins.json)
- **Allergens & Exclusion Keywords**: [`dictionaries/allergens.json`](dictionaries/allergens.json)
- **Jurisdiction Regulatory Profiles**: [`profiles/`](profiles/)

Run the test suite to verify (Python 3.12+):
```bash
python3 -m unittest discover -s tests -v
```

---

## 🛡️ Privacy & Data Integrity Rules

1. **Coarse `vintage_month` Allowed — No Personal or Day-Level Batch Fields**:
   - Never include `purchase_date`, `purchase_price`, or day-precision `production_date`, `expiry_date`, `expiry_estimate`, or serial `lot_number` in public OPF records. `opf validate` automatically rejects these fields.
   - **Allowed & encouraged**: Coarse month-level `vintage_month` (`YYYY-MM`, e.g. `"2026-08"`) in `evidence[]` to derive market active/stale windows cleanly without leaking individual batch timestamps.
   - **Do include public package facts**: `shelf_life` duration (e.g. `12 month`), `storage_text`, `packaging_code`, and printed `lot_code_rule` + non-default `TrackDefinition` discriminators when plants/lines differ.
2. **ROI Cropping, WebP Transcoding & Authenticity**:
   - Only crop factual text label regions; transcode with `--photo` or `opf sanitize-media` (`<= 1000px`, EXIF/XMP/IPTC stripped), group multi-panel shots of the same physical package under `specimen_id`, and never fabricate unverified hashes.
3. **No Guessing or Machine Translation**:
   - Leave unprinted nutrients omitted—never fill missing values with `0` or category averages.
   - `attributes` only stores languages actually printed on the package; human-verified translations go in `translations` (`source: "contributor_translated"`).
4. **Developer Certificate of Origin (DCO) & REUSE Licensing (`Apache-2.0` Inbound)**:
   - Exact per-path SPDX coverage is declared in [`REUSE.toml`](REUSE.toml) and [`LICENSES/`](LICENSES/). Core tooling (`opf/`, `bin/`, `web/` excl. `web/vendor/`) is distributed outbound under **[AGPL-3.0-or-later](LICENSE)**, while **by submitting code, schema, dictionary, profile, skill, or doc contributions to `open-packaged-food` with a `Signed-off-by` line (`git commit -s`), you provide them under the outbound license of their path and additionally license them to every recipient under [`Apache-2.0`](LICENSES/Apache-2.0.txt)**, with no separate CLA required. `spec/`, `dictionaries/`, `profiles/`, `skills/`, `docs/`, and `web/vendor/` (ZXing) are also distributed under **`Apache-2.0`**.
   - Contributions to `opf-data` follow **[ODbL-1.0](LICENSE-DATA)** and label crops in `opf-media` follow **[CC BY-SA 4.0](LICENSE-MEDIA)**. See [`GOVERNANCE.md`](GOVERNANCE.md) and [`docs/ODbL-GUIDE.md`](docs/ODbL-GUIDE.md) for boundaries.
5. **Dual-Layer `provenance` & Anti-Spoofing Gate**:
   - External PRs creating `evidence[]` or `revisions[]` entries default to `provenance: "external_contributor"`; Phase 2 relay submissions use `"public_submission"`.
   - CI (`opf check-pr-meta`) rejects external PRs attempting to write `maintainer`, `brand_owner`, `partner`, or `transcription: "independent_match"`, and blocks altering existing entries' `provenance` without an authorized maintainer `Provenance-Correction: <reason>` trailer.
