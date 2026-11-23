# OpenPackagedFood (`open-packaged-food` / CLI: `opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Contributing](CONTRIBUTING.md) | [贡献指南](CONTRIBUTING.zh-CN.md)** · **[Especificación (`v0.2`)](spec/SPEC.md)** · **[Diseño UI (`DESIGN.md`)](docs/DESIGN.md)**

> **🌐 Explorador Web y API estática**: [https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> **📦 Base de datos (`opf-data`)**: [mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · **🖼️ Imágenes de etiquetas (`opf-media`)**: [mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · **🧰 Herramientas y Skill IA**: [mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

**Conjunto de herramientas abiertas para alimentos envasados industriales basado en evidencia y libre de juicios subjetivos (`opf` v0.2): especificación formal, validador en Python 3.12 sin dependencias de ejecución, generador de API estática `/v1/` y Skill para Agentes de IA.**

---

## Características principales

- **Fidelidad al etiquetado y cotas reglamentarias (`<`)**: Separa explícitamente los valores declarados, las conversiones deterministas por `100g`/`100ml` (`ƒ`) y los límites de redondeo legal a cero (`< regulatory_upper_bound`).
- **Árbol de ingredientes verificado sin pérdidas**: Alineación monótona entre `core.ingredients_tree` y `attributes.ingredients_text`, con soporte de clases funcionales, alérgenos y números E / INS (p. ej. `Emulgente: lecitinas (soja)`).
- **4 jurisdicciones y 7 idiomas**: `CN` (`zh-Hans` / `zh-CN`), `US` (`en`), `JP` (`ja`) y `EU` (`en`, `de`, `fr`, `es`, `it`).
- **Privacidad y solo recortes funcionales**: Solo se admiten recortes de áreas textuales funcionales (7 valores `region`) en WebP sin metadatos EXIF/XMP (`<= 1000px`); quedan prohibidas las portadas frontales completas (`front_of_pack`), precios o fechas exactas de compra/caducidad.

- **Escáner estático en el navegador**: Lectura local mediante cámara trasera, foto local o entrada manual (`BarcodeDetector` + dígito de control GS1 Mod-10) sin subir imágenes ni consultar APIs externas.

---

## Inicio rápido (Fase 1: flujo Git puro para desarrolladores)

> El explorador web ofrece consulta de solo lectura y escaneo local para usuarios finales; el envío mediante Agentes abrirá en la Fase 2 (`OPF_SUBMIT_URL`). La Fase 1 admite únicamente contribuciones de desarrolladores por Git puro:

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git
git clone https://github.com/mickey996icu/opf-data.git
git clone https://github.com/mickey996icu/opf-media.git

./open-packaged-food/bin/opf submit --input draft.json --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 --media-out-dir opf-media
./open-packaged-food/bin/opf validate opf-data/products
```

- Haz `git commit -s` y `git push` en ambos repositorios y **fusione primero la PR de `opf-media`**, después la PR de `opf-data` (`opf check-media-refs`).
- **Automatización opcional (`uvx` + `gh`)**: `uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.0 opf pr ...` sigue disponible como atajo opcional. Más detalles en [README.md](README.md) y [CONTRIBUTING.md](CONTRIBUTING.md).
