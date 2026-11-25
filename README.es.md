# OpenPackagedFood (`opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Contribuir](CONTRIBUTING.md)** · **[Especificación](spec/SPEC.md)** · **[Diseño](docs/DESIGN.md)**

> 🌐 **Consulta web y escáner local**: [https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> 📦 **Datos**: [mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · 🖼️ **Imágenes**: [mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · 🧰 **Herramientas y Skill**: [mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

Quien haya programado una aplicación de nutrición o pedido a una IA que lea el reverso de un paquete habrá tropezado casi siempre con los mismos escollos silenciosos.

El envase dice «0 g de grasas trans» y el modelo afirma sin dudar que está limpio, pasando por alto que las normas de EE. UU. permiten redondear a cero cualquier cantidad inferior a 0,5 g por ración, igual que otras normativas permiten imprimir 0 para trazas de sodio. Al leer listas largas de ingredientes, también es común que la IA omita algún aditivo o añada palabras que no estaban en la etiqueta. Y en el estante del supermercado la realidad se complica: dos botellas con idéntico código de barras pueden venir de fábricas distintas, o mezclar una receta antigua alta en azúcar con otra nueva reducida. Por comodidad, casi todas las bases de datos sobrescriben una con otra o calculan un promedio.

Cuando se necesita cotejar la lista literal de ingredientes, distinguir los límites reglamentarios de redondeo (<) del cero matemático o seguir la trazabilidad entre fábricas y revisiones, un «más o menos» borra justo los detalles que importan.

Empecé **OpenPackagedFood (OPF)** por un motivo sencillo: poner en claro esas cuentas confusas. OPF no reparte notas ni semáforos de salud; decidir qué es sano corresponde a quien come y a su médico. Solo pretendo anotar lo que está impreso letra por letra en el envase, para que programas y asistentes de IA trabajen sobre hechos firmes.

---

## Cuatro reglas sencillas

- **Un «0» impreso no equivale a un cero matemático**
  Los valores redondeados a cero por norma legal se guardan como límites superiores (`<`), sin confundirse nunca con ausencia real. Todas las conversiones a 100 g o 100 ml se calculan con exactitud.
- **Los ingredientes se comprueban carácter por carácter**
  Los ingredientes analizados deben reconstruirse exactamente en el mismo orden que el texto original del paquete. Si falta una letra o sobra un signo de puntuación, la validación rechaza el registro sin dar pie a suposiciones de la IA.
- **Mismo código de barras, distintas plantas o recetas van por separado**
  Cuando varias fábricas o cambios de fórmula comparten código, cada variante conserva su propio historial sin pisarse. Si las versiones en venta difieren de verdad, la API omite los valores generales y pide mirar un momento la etiqueta del envase en mano en vez de dar un promedio engañoso.
- **Datos, imágenes y herramientas en repositorios separados, servidos en estático**
  Los JSON de producto, los recortes de texto de etiquetas y las herramientas CLI viven en tres repositorios Git distintos y se publican en GitHub Pages. Un script o agente de IA solo necesita una petición HTTP normal: sin claves de API ni servidor que mantener.

---

## Cómo empezar

### 1. Escanear en el supermercado

Abra el **[explorador web](https://mickey996icu.github.io/opf-data/)**, apunte la cámara trasera hacia el código de barras o elija una foto de su galería. La lectura se realiza íntegramente en su navegador (usando `BarcodeDetector` nativo si está disponible y cambiando automáticamente al decodificador sin conexión `ZXing` incluido en el resto de navegadores): no se suben fotos ni se consultan servicios externos.

Si cuida alergias o nutrientes concretos, los filtros superiores permiten filtrar por mercado, excluir por separado alérgenos confirmados y posibles trazas, descartar aditivos por código o fijar umbrales por cada 100 g/100 ml.

### 2. Añadir la Skill a su asistente de IA

Enlace `skills/opf` en la carpeta de skills de su asistente. Al preguntarle por la foto de un alimento, consultará primero los registros estáticos `/v1/`; si el producto aún no figura, leerá directamente la imagen para responder con objetividad sin insistir en que envíe datos.

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git ~/src/open-packaged-food

# Elija la ruta de su herramienta
mkdir -p .agents/skills && ln -s ~/src/open-packaged-food/skills/opf .agents/skills/opf
mkdir -p ~/.claude/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.claude/skills/opf
mkdir -p ~/.codex/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.codex/skills/opf
mkdir -p ~/.gemini/config/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.gemini/config/skills/opf
```

### 3. Hacer una foto y abrir un PR

Tanto la validación como la compilación del sitio usan solo la biblioteca estándar de Python (`Pillow` únicamente se carga al limpiar y comprimir imágenes WebP localmente).

```bash
# 1. Eliminar metadatos EXIF, recortar en WebP y generar el JSON normalizado
./open-packaged-food/bin/opf submit \
  --input draft.json \
  --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg \
  --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 \
  --media-out-dir opf-media

# 2. Validar localmente datos, imágenes y referencias cruzadas
./open-packaged-food/bin/opf validate opf-data/products
./open-packaged-food/bin/opf validate-media opf-media
./open-packaged-food/bin/opf check-media-refs --media-dir opf-media opf-data/products
```

Suba una rama y abra PRs en `opf-media` y `opf-data` (o use `uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.5 opf pr ...` si ya tiene `uvx` y `gh`). Respete el orden: **fusione primero el PR de `opf-media` y después el de `opf-data`**, para que la CI encuentre las imágenes ya en `main`.

Dos límites que no cruzamos:
- **Envíe solo recortes de texto informativo** (tabla nutricional, ingredientes, fabricante, código de barras), nunca el diseño completo frontal del envase;
- **Indique fechas solo por mes (`YYYY-MM`)**, sin incluir fechas exactas de fabricación, caducidad, tickets de compra ni números de lote.

---

## Cómo colaboran los tres repositorios

```text
  Consulta: Usuario / IA ──(HTTP GET)──▶ API estática y buscador en GitHub Pages (/v1/, /)
                                                    ▲
                                                    │ compilación y despliegue automático
  Envío:    opf submit ──▶ opf-media (WebP recortados) ──(① fusionar primero)──▶ opf-data (JSON)
```

<details>
<summary>Estructura del repositorio y vista previa local</summary>

```text
open-packaged-food/
├── bin/opf                    # Punto de entrada CLI
├── opf/                       # Validación, cotejo de ingredientes, conversiones, limpieza de imagen y build
├── web/                       # Explorador en 7 idiomas, escáner sin conexión y filtros
├── spec/                      # Especificación y esquemas JSON
├── docs/DESIGN.md             # Convenciones de interfaz y presentación de datos
├── profiles/ & dictionaries/  # Reglas CN/US/EU/JP y diccionarios de nutrientes, aditivos y alérgenos
├── skills/opf/                # Agent Skill listo para usar y plantilla mínima
└── tests/                     # Pruebas unitarias y de integración
```

```bash
cd open-packaged-food
python3 -m unittest discover -s tests -v
./bin/opf serve --data-dir ../opf-data/products
```

</details>

---

## Licencias (capas REUSE)

- **Herramientas y explorador web (`opf/`, `bin/`, `web/` excl. `web/vendor/`, `.github/`, `tests/`)**: [`AGPL-3.0-or-later`](LICENSE) en salida (**[`Apache-2.0`](LICENSES/Apache-2.0.txt) permisiva en entrada** + DCO `git commit -s`, ver [`CONTRIBUTING.md`](CONTRIBUTING.md))
- **Especificaciones, esquemas, diccionarios, perfiles, skills, docs y vendor (`spec/`, `dictionaries/`, `profiles/`, `skills/`, `docs/`, `web/vendor/`)**: [`Apache-2.0`](LICENSES/Apache-2.0.txt) (integración directa sin propagación copyleft)
- **Base de datos y JSON de productos (`opf-data`)**: [`ODbL-1.0`](LICENSE-DATA) / `DbCL-1.0` (guía: [`docs/ODbL-GUIDE.md`](docs/ODbL-GUIDE.md))
- **Recortes de etiquetas (`opf-media`)**: [`CC-BY-SA-4.0`](LICENSE-MEDIA)
- Declaraciones SPDX legibles por máquina en [`REUSE.toml`](REUSE.toml) y [`LICENSES/`](LICENSES/); gobernanza en [`GOVERNANCE.md`](GOVERNANCE.md).
