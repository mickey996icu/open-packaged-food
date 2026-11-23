# OpenPackagedFood (`open-packaged-food` / CLI: `opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Contributing](CONTRIBUTING.md) | [贡献指南](CONTRIBUTING.zh-CN.md)** · **[Spezifikation (`v0.2`)](spec/SPEC.md)** · **[UI-Design (`DESIGN.md`)](docs/DESIGN.md)**

> **🌐 Online Web-Explorer & Statische API**: [https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> **📦 Produktdatenbank (`opf-data`)**: [mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · **🖼️ Etikett-Medienspeicher (`opf-media`)**: [mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · **🧰 Tooling, Spezifikation & Agent Skill**: [mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

**Evidenzbasierte, wertfreie offene Datenbank-Toolchain für industriell verpackte Lebensmittel mit formaler v0.2-Spezifikation, rein auf der Python-3.12-Standardbibliothek basierendem Validator/Builder und fertigem AI-Agent-Skill.**

---

## Kernfunktionen

- **Strikte Trennung von Deklaration, Umrechnung (`ƒ`) & Rundungsobergrenzen (`<`)**: Keine subjektiven Gesundheits-Scores; exakte `Decimal`-Normierung auf `100g`/`100ml` inklusive gesetzlicher Null-Rundungsschwellen (`< regulatory_upper_bound`).
- **Verlustfreie Zutatenbaum-Prüfung**: Deterministischer Links-nach-Rechts-Abgleich zwischen `core.ingredients_tree` und `attributes.ingredients_text` mit EU-Allergen-, E-/INS-Nummern- und Funktionsklassen-Erkennung (z. B. `Emulgator: Lecithine (Soja)`).
- **4 Rechtsräume & 7 UI-/Wörterbuch-Sprachen**: `CN` (`zh-Hans` / `zh-CN`), `US` (`en`), `JP` (`ja`) sowie `EU` (`en`, `de`, `fr`, `es`, `it`).
- **Datenschutz & Funktions-Zuschnitte**: Zugelassen sind ausschließlich zugeschnittene Textbereiche (7 definierte `region`-Werte) als EXIF-/XMP-freie WebP-Dateien (`<= 1000px`). Vorderseiten-Coverfotos (`front_of_pack`), Kaufdaten, Preise oder tagesgenaue Chargendaten werden strikt abgelehnt.

- **Rein statischer Barcode-Scanner im Browser**: Lokale Erkennung per Kamera, Foto oder Eingabe (`BarcodeDetector` + GS1 Mod-10) ohne Bild-Upload oder externe APIs.

---

## Schnellstart (Phase 1: Reiner Git-Entwickler-Workflow)

> Der Web-Explorer dient Endnutzern zur reinen Lese- und Scan-Abfrage; allgemeine Agent-Einreichungen folgen erst in Phase 2 (`OPF_SUBMIT_URL`). Phase 1 steht ausschließlich Entwicklern über reine Git-PRs offen:

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git
git clone https://github.com/mickey996icu/opf-data.git
git clone https://github.com/mickey996icu/opf-media.git

./open-packaged-food/bin/opf submit --input draft.json --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 --media-out-dir opf-media
./open-packaged-food/bin/opf validate opf-data/products
```

- Beide Branches mit `git commit -s` & `git push` einreichen und bei gekoppelten PRs **immer zuerst den `opf-media`-PR mergen**, danach den `opf-data`-PR (`opf check-media-refs`).
- **Optionale Ein-Schritt-Automatisierung (`uvx` + `gh`)**: `uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.0 opf pr ...` steht optional zur Verfügung. Details in [README.md](README.md) und [CONTRIBUTING.md](CONTRIBUTING.md).
