# OpenPackagedFood (`open-packaged-food` / CLI: `opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Contributing](CONTRIBUTING.md) | [贡献指南](CONTRIBUTING.zh-CN.md)** · **[Specifica (`v0.2`)](spec/SPEC.md)** · **[Specifica UI (`DESIGN.md`)](docs/DESIGN.md)**

> **🌐 Web Explorer e API statica**: [https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> **📦 Database prodotti (`opf-data`)**: [mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · **🖼️ Archivio etichette (`opf-media`)**: [mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · **🧰 Strumenti e Agent Skill**: [mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

**Toolkit open source, basato su prove e privo di giudizi soggettivi per il database aperto degli alimenti preconfezionati (`opf` v0.2): specifica formale, validatore in Python 3.12 pure stdlib, compilatore API statica `/v1/` e Agent Skill.**

---

## Funzionalità principali

- **Fedeltà all'etichetta e limiti normativi (`<`)**: Distingue rigorosamente valori dichiarati, conversioni deterministiche per `100g`/`100ml` (`ƒ`) e limiti normativi di arrotondamento a zero (`< regulatory_upper_bound`).
- **Verifica senza perdita degli ingredienti**: Allineamento deterministico tra `core.ingredients_tree` e `attributes.ingredients_text` con riconoscimento di classi funzionali, allergeni e numeri E / INS (es. `Emulsionante: lecitine (soia)`).
- **4 giurisdizioni e 7 lingue**: `CN` (`zh-Hans` / `zh-CN`), `US` (`en`), `JP` (`ja`) ed `EU` (`en`, `de`, `fr`, `es`, `it`).
- **Privacy e soli ritagli funzionali**: Ammessi esclusivamente ritagli testuali funzionali (7 valori `region`) in WebP senza EXIF/XMP (`<= 1000px`); vietate foto complete del fronte confezione (`front_of_pack`), prezzi o date esatte di acquisto/lotto.
- **Scanner statico nel browser**: Lettura locale tramite fotocamera posteriore, foto o inserimento manuale (`BarcodeDetector` + cifra di controllo GS1 Mod-10) senza caricamento immagini né API esterne.

---

## Avvio rapido (Fase 1: flusso Git puro per sviluppatori)

> Il Web Explorer offre consultazione in sola lettura e scansione locale per i consumatori; l'invio via Agenti aprirà nella Fase 2 (`OPF_SUBMIT_URL`). La Fase 1 è aperta solo ai contributi sviluppatore tramite Git puro:

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git
git clone https://github.com/mickey996icu/opf-data.git
git clone https://github.com/mickey996icu/opf-media.git

./open-packaged-food/bin/opf submit --input draft.json --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 --media-out-dir opf-media
./open-packaged-food/bin/opf validate opf-data/products
```

- Esegui `git commit -s` e `git push` su entrambi i repository e **eseguire il merge prima sulla PR `opf-media`** e successivamente quella su `opf-data` (`opf check-media-refs`).
- **Automazione opzionale (`uvx` + `gh`)**: `uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.0 opf pr ...` resta disponibile come scorciatoia opzionale. Dettagli in [README.md](README.md) e [CONTRIBUTING.md](CONTRIBUTING.md).
