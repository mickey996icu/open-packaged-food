# OpenPackagedFood (`open-packaged-food` / CLI : `opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Contributing](CONTRIBUTING.md) | [贡献指南](CONTRIBUTING.zh-CN.md)** · **[Spécification (`v0.2`)](spec/SPEC.md)** · **[Spécification UI (`DESIGN.md`)](docs/DESIGN.md)**

> **🌐 Explorateur Web & API statique**: [https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> **📦 Base produits (`opf-data`)**: [mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · **🖼️ Médias d'étiquettes (`opf-media`)**: [mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · **🧰 Outillage, Spec & Skill IA**: [mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

**Boîte à outils open source, factuelle et sans score subjectif pour les produits alimentaires préemballés (`opf` v0.2) : spécification formelle, validateur pur stdlib Python 3.12, générateur d'API statique `/v1/` et Agent Skill prêt à l'emploi.**

---

## Principes et fonctionnalités clés

- **Vérité d'étiquette & bornes réglementaires (`<`)** : Distinction stricte entre valeurs imprimées, conversions déterministes pour `100g`/`100ml` (`ƒ`) et bornes supérieures d'arrondi à zéro (`< regulatory_upper_bound`).
- **Arbre d'ingrédients vérifié sans perte** : Alignement monotone déterministe entre `core.ingredients_tree` et `attributes.ingredients_text` avec détection des allergènes et numéros E / INS (ex. `Émulsifiant : lécithines (soja)`).
- **4 juridictions et 7 langues** : `CN` (`zh-Hans` / `zh-CN`), `US` (`en`), `JP` (`ja`) et `EU` (`en`, `de`, `fr`, `es`, `it`).
- **Confidentialité et recadrages fonctionnels uniquement** : Seuls les recadrages de zones textuelles (7 valeurs `region`) encodés en WebP sans EXIF/XMP (`<= 1000px`) sont acceptés — jamais de visuel complet de face avant ni de dates d'achat/prix/numéros de lot exacts.

- **Scanner de codes-barres purement statique** : Détection locale dans le navigateur (caméra, photo ou saisie) via `BarcodeDetector` et clé GS1 Mod-10, sans envoi d'image ni API externe.

---

## Démarrage rapide (Phase 1 : flux Git pur pour développeurs)

> L'explorateur web offre une consultation en lecture seule et le scan local pour le grand public ; la contribution grand public ouvrira en Phase 2 via `OPF_SUBMIT_URL`. En Phase 1, seules les contributions développeurs en Git pur sont ouvertes :

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git
git clone https://github.com/mickey996icu/opf-data.git
git clone https://github.com/mickey996icu/opf-media.git

./open-packaged-food/bin/opf submit --input draft.json --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 --media-out-dir opf-media
./open-packaged-food/bin/opf validate opf-data/products
```

- Poussez les deux branches (`git commit -s` puis `git push`) et **fusionnez toujours la PR `opf-media` EN PREMIER**, puis la PR `opf-data` (`opf check-media-refs`).
- **Automatisation optionnelle (`uvx` + `gh`)** : `uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.0 opf pr ...` reste disponible en raccourci optionnel. Détails dans [README.md](README.md) et [CONTRIBUTING.md](CONTRIBUTING.md).
