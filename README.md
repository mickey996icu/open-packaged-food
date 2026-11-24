# OpenPackagedFood (`opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Contributing](CONTRIBUTING.md)** · **[Specification](spec/SPEC.md)** · **[Design](docs/DESIGN.md)**

> 🌐 **Web Explorer & Local Scanner**: [https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> 📦 **Data**: [mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · 🖼️ **Media**: [mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · 🧰 **Tooling & Skill**: [mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

Anyone who has built a nutrition tracker or asked an AI assistant to read the back of a snack bag has likely run into the same quiet pitfalls.

The label says "0g trans fat", and the AI cheerfully tells you it is clean—forgetting that US rules let manufacturers round anything under 0.5g per serving down to zero, just as China's rules allow trace sodium to be printed as 0. Reading long ingredient lists, models also tend to skip an additive or invent a word that was never printed. Walk down a supermarket aisle and it gets trickier: two bottles sharing the exact same barcode may come from different contract plants, or belong to an old sugary batch and a new reduced-sugar recipe sitting side by side. Most food databases take the easy way out, overwriting one with the other or averaging them together.

When you are counting allergens, tracking clinical nutrition, or logging daily intake, "close enough" is not good enough.

I started **OpenPackagedFood (OPF)** for a simple reason: to straighten out this muddled ledger. OPF does not hand out traffic-light health scores—deciding what is healthy belongs to the person eating and their doctor. I simply want to record what is actually printed on the package, word for word, so software and AI agents have reliable facts to work with.

---

## Four Ground Rules

- **A printed "0" is not treated as mathematical zero**
  Values rounded down by local regulations are stored as upper bounds (`<`) rather than true zeros. Every per-100g or per-100ml conversion uses exact arithmetic so nothing drifts.
- **Ingredient lists are checked character by character**
  Parsed ingredients must reconstruct back into the exact printed string from left to right. Drop one character or slip in an extra punctuation mark, and validation refuses the entry—leaving no room for AI guesswork.
- **Same barcode, different plants or recipes stay separate**
  When multiple contract factories or reformulations share a barcode, each keeps its own record instead of overwriting history. When live variants genuinely differ, the API holds back top-level nutrients and asks you to glance at the package in your hand rather than offering a misleading average.
- **Data, images, and tools live apart, served statically**
  Product JSON, cropped text-only label images, and CLI tooling live in three separate Git repositories and publish as static files on GitHub Pages. A script or AI agent needs only a single plain HTTP request—no API keys and no backend server to maintain.

---

## Getting Started

### 1. Scan in the Supermarket

Open the **[Web Explorer](https://mickey996icu.github.io/opf-data/)**, point your phone's rear camera at a barcode, or choose a photo from your library. Decoding runs entirely inside your browser (using native `BarcodeDetector` when supported, and seamlessly falling back to the bundled offline `ZXing` decoder everywhere else)—no images are uploaded and no external lookup services are called.

If you shop with strict dietary needs, use the three-column filter bar at the top to filter by market regulation, exclude confirmed vs. trace allergens separately, rule out specific additive codes, or set custom nutrient thresholds per 100g/100ml.

### 2. Give Your AI Coding Assistant the Skill

Link `skills/opf` into your assistant's skills directory. Ask it about a snack photo and it will check the static `/v1/` records first; if the item is not in the database yet, it simply reads the photo in front of it and answers your question without nagging you to contribute.

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git ~/src/open-packaged-food

# Pick the path for your tool
mkdir -p .agents/skills && ln -s ~/src/open-packaged-food/skills/opf .agents/skills/opf
mkdir -p ~/.claude/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.claude/skills/opf
mkdir -p ~/.codex/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.codex/skills/opf
mkdir -p ~/.gemini/config/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.gemini/config/skills/opf
```

### 3. Snap a Photo and Open a PR

Validation and static-site generation rely solely on Python's standard library (`Pillow` is loaded only when stripping and encoding label images locally).

```bash
# 1. Strip EXIF metadata into cropped WebP images and generate normalized JSON
./open-packaged-food/bin/opf submit \
  --input draft.json \
  --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg \
  --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 \
  --media-out-dir opf-media

# 2. Validate records, images, and cross-repo references locally
./open-packaged-food/bin/opf validate opf-data/products
./open-packaged-food/bin/opf validate-media opf-media
./open-packaged-food/bin/opf check-media-refs --media-dir opf-media opf-data/products
```

Push branches and open PRs on `opf-media` and `opf-data` (or run `uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.1 opf pr ...` if you have `uvx` and `gh` ready). Keep the order straight: **merge `opf-media` first, then `opf-data`**, so CI finds the images already on `main`.

Two lines we do not cross:
- **Crop only factual text panels** (nutrition table, ingredients box, manufacturer block, barcode)—never upload full front-of-pack cover artwork;
- **Record dates only to the month (`YYYY-MM`)**—never include day-exact production dates, expiry dates, receipt timestamps, or lot numbers.

---

## How the Three Repositories Fit Together

```text
  Lookup: User / AI Agent ──(HTTP GET)──▶ GitHub Pages static API & explorer (/v1/, /)
                                                    ▲
                                                    │ automated build & deploy
  Submit: opf submit ──▶ opf-media (cropped WebP) ──(① merge first)──▶ opf-data (product JSON)
```

<details>
<summary>Repository layout and local preview commands</summary>

```text
open-packaged-food/
├── bin/opf                    # CLI entrypoint
├── opf/                       # Validation, ingredient matching, unit conversion, media stripping & site builder
├── web/                       # 7-language static explorer, offline scanner & filter workbench
├── spec/                      # Formal specification and JSON Schemas
├── docs/DESIGN.md             # UI and data-display conventions
├── profiles/ & dictionaries/  # CN/US/EU/JP regulatory rules and nutrient/additive/allergen dictionaries
├── skills/opf/                # Ready-to-use Agent Skill and minimal draft template
└── tests/                     # Unit and integration test suite
```

```bash
cd open-packaged-food
python3 -m unittest discover -s tests -v
./bin/opf serve --data-dir ../opf-data/products
```

</details>

---

## Licensing

- **Tooling & Web Explorer (`opf/`, `bin/`, `web/`, `.github/`)**: [AGPL-3.0-or-later](LICENSE)
- **Database & Product JSON (`opf-data`)**: [ODbL-1.0](LICENSE-DATA) / `DbCL-1.0`
- **Cropped Label Evidence Media (`opf-media`)**: [CC-BY-SA-4.0](LICENSE-MEDIA)
