# OpenPackagedFood (`open-packaged-food` / CLI: `opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Contributing](CONTRIBUTING.md) | [贡献指南](CONTRIBUTING.zh-CN.md)** · **[Specification (`v0.2`)](spec/SPEC.md)** · **[UI & Data Display Spec](docs/DESIGN.md)**

> **🌐 Live Web Explorer & Zero-Auth Static API**: [https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> **📦 Product Database Repo**: [mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · **🖼️ Label Media Repo**: [mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · **🧰 Tooling, Spec & Agent Skill Repo**: [mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

**Evidence-first, zero-judgment global industrial packaged food open database toolkit, formal specification, static API builder, and ready-to-use AI Agent Skill.**

---

## Why OpenPackagedFood?

Industrial packaged food labels look structured on paper, yet break down quickly when queried by software or AI Agents. OPF `v0.2` solves four core pain points directly in its schema and deterministic compiler:

1. **Zero Subjective Health Scores — Faithful Regulatory Rounding Semantics**
   OPF **never computes health ratings or traffic lights**. Every record keeps verbatim label declarations (`core` + `attributes`) alongside exact Python `Decimal`-compiled `normalized` values per `100g` / `100ml`:
   - **Three explicit value states**: printed verbatim values (`reported`), deterministic formula conversions (`ƒ derived`, such as serving-to-100g, kJ↔kcal, or salt↔sodium), and **regulatory zero-rounding upper bounds (`< regulatory_upper_bound`)**;
   - Under US FDA rules (`< 0.5g` trans fat/sugars per serving printed as `"0"`) or China GB 28050 (`≤ 5mg` sodium per 100g printed as `"0"`), OPF propagates `<` upper bounds and attaches `REGULATORY_ZERO_ROUNDING_ARTIFACT`—never mistaking regulatory rounding for exact zero.
2. **Zero AI Extraction Hallucinations — 100% Monotonic Lossless Ingredient Verification**
   OCR and LLMs frequently drop or invent words inside long nested ingredient lists. OPF uses a **span-free semantic AST (`core.ingredients_tree`)** verified by strict left-to-right monotonic alignment against verbatim `attributes.ingredients_text`—dropping or fabricating even a single character fails CI immediately, while punctuation restyling preserves `core_fingerprint`.
3. **Real-World Multi-Plant Supply Chains & Reformulations**
   One barcode (GTIN) often spans multiple co-packers (`SC` license codes, plant codes) or overlapping recipe revisions:
   - Editions start on `<market>/default` and split lazily onto named **Tracks** (`CN/plant:SC10600000000001`, `EU/code:A`) only when concurrent differences arise;
   - Permanent 26-character Crockford ULIDs (`edition_id`) support deterministic content locking via `<edition_id>@<rev>` with bidirectional RFC 6902 `patch` / `reverse_patch` revisions—appending photo corroboration (`evidence[]`) **never increments `rev`**, and duplicate PRs consolidate into `EditionRedirect` stubs (`merged_into`);
   - Build-time inference derives `active`, `stale`, `superseded`, `discontinued`, and `retracted` states from `supersedes[]`, coarse `YYYY-MM` `vintage_month`, and `[3, 18]`-month shelf-life bounds;
   - Whenever live coexisting variants differ, Compact API returns **`divergent`** and **intentionally omits top-level `normalized` and `ingredients_text`**, forbidding Agents from logging averages and guiding users to inspect the physical package via `tracks_guide` & `variants[]`.
4. **3-Repository Isolation, Zero Servers, CDN Resilience**
   Product JSON records (`opf-data`) and `<= 1000px` EXIF-free content-addressed WebP label crops (`opf-media`) live in separate repositories, linked only via location-independent URIs (`opf-media://sha256/<hex>`) that migrate effortlessly to R2/S3/CDN without touching any JSON. GitHub Pages serves `/v1/` endpoints statically for single-`GET` lookups.

---

## Three-Repository Architecture

```text
  Pre-Purchase Lookup Users & AI Agents (Claude Code, Antigravity, Codex, Cursor ...)
         │
         ├── Lookup Phase: Pure HTTP GET to GitHub Pages /v1/ static API (zero CLI needed)
         └── Contribution Phase:
               • Phase 1 (Developer Primary Path): Pure-Git dual PR (`opf submit` -> `opf validate` -> `git push`)
               • Optional One-Step Shortcut: `uvx --from ... opf pr` (`uvx` + `gh`)
               • Phase 2 (Everyday Users via Agent Relay): POST <OPF_SUBMIT_URL>/v1/submissions (no Git/CLI)
         ▼
  ┌──────────────────────────────────────────┐  ① Merge Media PR    ┌──────────────────────────────────────────┐
  │       mickey996icu/opf-media             │ ───────────────────▶ │        mickey996icu/opf-data             │
  │  • media/<h0:2>/<h2:4>/<sha256>.webp     │  opf-data CI runs    │  • products/{gtin|opf}/.../{product}/    │
  │  • Text-only label crops (≤1000px WebP)  │  `check-media-refs`  │    ├── product.json (aliases & tracks)   │
  │  • CI: opf validate-media (pure stdlib)  │  before allowing     │    └── editions/<ulid>.json              │
  └────────────────────┬─────────────────────┘  ② Merge Data PR     └────────────────────┬─────────────────────┘
                       │                                                                 │
                       │  OPF_MEDIA_BASE_URL (GitHub raw / R2 / S3 CDN)                  │ GitHub Pages deploy
                       └──────────────────────────────▶ ┌────────────────────────────────▼────────────────────────┐
                                                        │  GitHub Pages Static Deployment (mickey996icu.github.io)│
                                                        │  • 7-Language MD3E Explorer, Scanner & Workbench (/)  │
                                                        │  • /v1/meta.json · /v1/index/catalog.jsonl              │
                                                        │  • /v1/gtin/{p1}/{p2}/{gtin14}.json (.full.json)        │
                                                        └─────────────────────────────────────────────────────────┘
```

> [`mickey996icu/open-packaged-food`](https://github.com/mickey996icu/open-packaged-food) is checked out at pinned release `v0.2.0` across all CI workflows and runs `validate`, `validate-media`, `check-media-refs`, and `build` using **pure Python 3.12 stdlib** (`Pillow` is lazy-imported only for local WebP label transcoding).

---

## How to Use (3 Ways)

### 1. Online Web Explorer, Client-Side Barcode Scanner & Filter Workbench

Visit **[https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)** (read-only 7-language explorer, Light & Dark Material 3 themes):

- **Pure-Static Barcode & QR Scanner**: Scan via rear camera, local photo, or manual entry using native `BarcodeDetector` and GS1 Mod-10 check-digit verification—zero image uploads and zero external lookup APIs;
- **3-Column Filter Workbench**: Multi-select markets (`CN`, `US`, `EU`, `JP`, etc.), compact resolution modes, evidence seals, regulatory profiles, namespaces (`gtin` / `opf`), and brands;
- **Multi-Select Safety Allergen Exclusion**: Safely excludes products declaring either definite ingredients (`contains`) or cross-contact warnings (`may_contain`);
- **Ingredient & Additive (INS / E-number) Tags + Zero-Additive Shortcut**: Filter by required or excluded ingredient terms and additive codes;
- **Per-100g/100ml Nutrient Value Rule Builder**: Combine `≤`, `≥`, and `[min, max]` rules (respecting `<` zero-rounding bounds without false matches).

### 2. Install the `opf` Agent Skill (HTTP-First Lookup + Answer First)

Link or copy [`skills/opf`](skills/opf) into your AI assistant's skills directory for instant pre-purchase food comparisons and plant disambiguation. For everyday users without `OPF_SUBMIT_URL` (Phase 2 HTTP Relay) or a local developer environment, the Agent strictly focuses on answering the buying question objectively without prompting for uploads:

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git ~/src/open-packaged-food

# 1) Project-local standard (.agents/skills)
mkdir -p .agents/skills && ln -s ~/src/open-packaged-food/skills/opf .agents/skills/opf

# 2) Global Claude Code / Codex / Antigravity
mkdir -p ~/.claude/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.claude/skills/opf
mkdir -p ~/.codex/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.codex/skills/opf
mkdir -p ~/.gemini/config/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.gemini/config/skills/opf
```

> Default static endpoint is `https://mickey996icu.github.io/opf-data` (override via `OPF_BASE_URL`). Phase 1 only opens developer Git contributions; everyday end-user submissions open in Phase 2 when `OPF_SUBMIT_URL` is configured.

### 3. Developer Pure-Git Contributor Flow (Primary Path) & Optional `uvx` Shortcut

Phase 1 product submissions use the standard three-repo pure-Git workflow (see [`CONTRIBUTING.md`](CONTRIBUTING.md)):

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git
git clone https://github.com/mickey996icu/opf-data.git
git clone https://github.com/mickey996icu/opf-media.git

# 1. Strip EXIF into <=1000px WebP crops and write normalized product/edition JSON
./open-packaged-food/bin/opf submit \
  --input draft.json \
  --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg \
  --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 \
  --media-out-dir opf-media

# 2. Validate data, media, and cross-repo references (pure Python 3.12 stdlib)
./open-packaged-food/bin/opf validate opf-data/products
./open-packaged-food/bin/opf validate-media opf-media
./open-packaged-food/bin/opf check-media-refs --media-dir opf-media opf-data/products

# 3. Commit (-s) and push branches, then click the terminal PR links (merge opf-media PR FIRST, then opf-data PR)
git -C opf-media switch -c contrib/media-label && git -C opf-media add -A && git -C opf-media commit -s -m "media(label): add cropped label evidence" && git -C opf-media push -u origin HEAD
git -C opf-data switch -c contrib/product-record && git -C opf-data add -A && git -C opf-data commit -s -m "feat(product): add packaged food record" && git -C opf-data push -u origin HEAD
```

**Optional One-Step Automation (`uvx` + `gh`)**: Developers with `uvx` and authenticated `gh` may optionally use `opf pr` instead of manual git branching/pushing:

```bash
uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.0 \
  opf pr --input draft.json \
  --photo nutrition_table=crop_nutrition.jpg \
  --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08
```

For local test suite verification and static site preview:

```bash
cd open-packaged-food
python3 -m unittest discover -s tests -v
./bin/opf build \
  --data-dir ../opf-data/products \
  --out-dir /tmp/opf-site \
  --canonical-base "https://mickey996icu.github.io/opf-data" \
  --media-base-url "https://raw.githubusercontent.com/mickey996icu/opf-media/main"
./bin/opf serve --dir /tmp/opf-site
```

---

## Contributing & Dual-PR Lifecycle

See **[Contributing Guide (`CONTRIBUTING.md`)](CONTRIBUTING.md)** for full details and **[`skills/opf/examples/draft.minimal.json`](skills/opf/examples/draft.minimal.json)** for a ready-to-submit minimal `v0.2` draft template.

| Step | Command / Action | Notes |
| :--- | :--- | :--- |
| **1. Crop & WebP Sanitize** | `opf sanitize-media <img...> [--media-root .../opf-media]` | Runs `exif_transpose`, downscales to `<= 1000px`, strips all EXIF/XMP/IPTC chunks, and emits content-addressed WebP (integrated via `--photo`). **Never upload full front-of-pack cover artwork**. |
| **2. Submit / Route Draft** | `opf submit --input draft.json --out-dir .../products [--photo region=img]` | Matches `(id, track, core_fingerprint)` to create `rev: 1`, auto-enrich (`rev + 1`), or corroborate with **zero `rev` bump** (`corroborated`); pass `--amend`, `--supersede`, or `--new-variant` on conflict. |
| **3. Commit & Push Dual PRs** | `git switch -c ... && git commit -s && git push` (or optional `uvx ... opf pr`) | Push cropped WebP in `opf-media` and normalized JSON in `opf-data`, then open PRs via the terminal links (or use `uvx` + `gh` `opf pr` as an optional one-step shortcut). |
| **4. Dual-PR Merge Order** | **Merge `opf-media` PR FIRST → `opf-data` PR SECOND** | `opf-data` CI runs `opf check-media-refs` to ensure `opf-media://sha256/...` blobs exist on `opf-media main`. |

- **Privacy redline**: Only coarse `YYYY-MM` `vintage_month` is allowed in `evidence[]`; never include `purchase_date`, `purchase_price`, day-precision `production_date`/`expiry_date`/`expiry_estimate`, or `lot_number`.

---

## Repository Layout

```text
open-packaged-food/
├── bin/opf                         # Zero-dependency CLI entrypoint
├── pyproject.toml & setup.py       # Standalone wheel / uvx resource bundling configuration
├── opf/
│   ├── resources.py                # Dual-mode resource root (git checkout vs wheel `_bundled`)
│   ├── ids.py                      # GTIN-14 GS1 check digit, 020-029/200-299 rejection, ULID & Track keys
│   ├── registries.py               # Dictionary & regulatory profile loader (exclusion-safe allergens)
│   ├── ingredients.py              # Deterministic ingredient parser & span-free round-trip verifier
│   ├── patches.py                  # RFC 6901/6902 forward/reverse patch engine & @rev reconstruction
│   ├── normalize.py                # 100g/100ml compiler, upper bounds, core/label fingerprints & lifecycle
│   ├── validator.py                # JSON Schema v0.2, product-dir DAG/track/patch & privacy validator
│   ├── media.py                    # WebP <=1000px transcoding (lazy Pillow) + pure-stdlib `validate-media`
│   ├── builder.py                  # Static API (/v1/) Compact (4 modes) / Full & Web Explorer builder
│   └── cli.py                      # CLI subcommands (submit/pr/validate/validate-media/check-media-refs/build...)
├── web/                            # Bilingual (zh-CN / en) MD3E web explorer & filter workbench
├── spec/                           # SPEC.md & schema/*.v0.2.schema.json
├── docs/DESIGN.md                  # UI, color token & 3-state data display specification
├── profiles/ & dictionaries/       # CN/US/EU/JP regulatory plugins + nutrients/INS/allergens dictionaries
├── skills/opf/                     # HTTP-first, answer-first, dual-channel Agent Skill & draft.minimal.json
└── tests/                          # Self-contained unit & integration test suite
```

---

## Licensing

- **Code & Tooling (`opf/`, `bin/`, `web/`, `.github/`)**: [GNU Affero General Public License v3.0 or later (`AGPL-3.0-or-later`)](LICENSE)
- **Database & Product JSON (`opf-data`)**: [Open Database License v1.0 (`ODbL-1.0`) / `DbCL-1.0`](LICENSE-DATA)
- **Cropped Label Evidence Media (`opf-media`)**: [Creative Commons Attribution-ShareAlike 4.0 International (`CC-BY-SA-4.0`)](LICENSE-MEDIA)
