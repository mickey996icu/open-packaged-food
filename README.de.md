# OpenPackagedFood (`opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Mitwirken](CONTRIBUTING.md)** · **[Spezifikation](spec/SPEC.md)** · **[Design](docs/DESIGN.md)**

> 🌐 **Web-Suche & lokaler Scanner**: [https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> 📦 **Daten**: [mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · 🖼️ **Medien**: [mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · 🧰 **Werkzeuge & Skill**: [mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

Wer schon einmal eine Ernährungs-App gebaut oder einer KI das Foto einer Snack-Rückseite zum Prüfen gegeben hat, kennt die stillen Tücken im Kleingedruckten.

Auf der Packung steht „0g Transfette“, und das Modell versichert arglos, alles sei makellos – dabei darf laut US-Recht alles unter 0,5 g pro Portion auf Null abgerundet werden, und ähnliche Freigrenzen gelten auch anderswo für Natrium. Bei langen Zutatenlisten überliest eine KI schnell einen Zusatzstoff oder dichtet Wörter hinzu, die gar nicht auf der Verpackung standen. Und im Supermarktregal kommt noch etwas hinzu: Zwei Flaschen mit exakt demselben Strichcode stammen womöglich aus verschiedenen Lohnabfüllungen, oder eine alte Rezeptur und eine zuckerreduzierte Neufassung stehen nebeneinander. Die meisten Lebensmitteldatenbanken machen es sich einfach und überschreiben eine Version mit der anderen oder bilden schlicht den Durchschnitt.

Wer den exakten Wortlaut auf dem Etikett abgleichen, gesetzliche Abrundungsgrenzen (<) sauber von echter Null trennen oder Rezepturänderungen über Werke und Revisionen hinweg nachvollziehen möchte, verliert mit einem „ungefähr richtig“ genau diese Details.

**OpenPackagedFood (OPF)** entstand aus einem einfachen Wunsch: Ordnung in diese unklare Buchführung zu bringen. Das Projekt verteilt keine Ampel-Gesundheitsnoten – was gesund ist, entscheiden der Mensch, der isst, und sein Arzt. Mir geht es nur darum, das auf der Verpackung Gedruckte getreu festzuhalten, damit Programme und KI-Assistenten auf festem Boden rechnen können.

---

## Vier einfache Grundsätze

- **Eine gedruckte „0“ ist keine mathematische Null**
  Werte, die gesetzlich auf Null abgerundet werden dürfen, bleiben ausdrücklich als Obergrenze (`<`) markiert und werden nicht mit echtem Nullgehalt verwechselt. Alle Umrechnungen auf 100 g oder 100 ml erfolgen exakt.
- **Zutatenlisten werden Zeichen für Zeichen geprüft**
  Zerlegte Zutaten müssen sich lückenlos von links nach rechts wieder exakt zum abgedruckten Originaltext zusammensetzen lassen. Fehlt ein Buchstabe oder schleicht sich ein Satzzeichen ein, weist die Prüfung den Eintrag ab – ohne Raum für Vermutungen.
- **Gleicher Strichcode, verschiedene Werke oder Rezepturen bleiben getrennt**
  Teilen sich mehrere Herstellerwerke oder Rezepturanpassungen denselben Barcode, behält jede Ausführung ihren eigenen Eintrag. Unterscheiden sich aktuelle Varianten tatsächlich, gibt die kompakte API keine irreführenden Durchschnittswerte zurück, sondern bittet um einen kurzen Blick auf die Packung in der Hand.
- **Daten, Bilder und Werkzeuge liegen getrennt und werden statisch ausgeliefert**
  Produktdaten, beschnittene Textausschnitte der Etiketten und die CLI-Werkzeuge liegen in drei getrennten Git-Repositories und erscheinen als statische Dateien über GitHub Pages. Ein Skript oder KI-Assistent braucht nur eine einzige schlichte HTTP-Abfrage – ohne API-Schlüssel und ohne eigenen Server.

---

## Schnellstart

### 1. Direkt im Supermarkt scannen

Öffnen Sie den **[Web-Explorer](https://mickey996icu.github.io/opf-data/)**, richten Sie die Rückkamera auf den Strichcode oder wählen Sie ein Foto aus der Galerie. Die Erkennung läuft vollständig lokal im Browser (bevorzugt über `BarcodeDetector` und auf anderen Browsern automatisch über die eingebundene Offline-Bibliothek `ZXing`) – ohne Bildupload und ohne fremde Abfragedienste.

Für besondere Ernährungsbedürfnisse lassen sich oben Marktregeln, sichere Allergene und Kreuzkontaminations-Hinweise getrennt, einzelne Zusatzstoffnummern oder eigene Nährwertgrenzen je 100 g/100 ml filtern.

### 2. Den Skill für Ihren KI-Assistenten einbinden

Verknüpfen Sie `skills/opf` im Skill-Verzeichnis Ihres KI-Werkzeugs. Fragen Sie ihn nach einem Foto eines Produkts, schaut er zuerst in den statischen `/v1/`-Einträgen nach; ist das Produkt noch nicht verzeichnet, wertet er sachlich das vorliegende Foto aus, ohne zu Beiträgen zu drängen.

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git ~/src/open-packaged-food

# Passenden Pfad wählen
mkdir -p .agents/skills && ln -s ~/src/open-packaged-food/skills/opf .agents/skills/opf
mkdir -p ~/.claude/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.claude/skills/opf
mkdir -p ~/.codex/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.codex/skills/opf
mkdir -p ~/.gemini/config/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.gemini/config/skills/opf
```

### 3. Foto aufnehmen und einen PR einreichen

Prüfung und statischer Build nutzen ausschließlich die Python-Standardbibliothek (`Pillow` wird nur geladen, wenn lokal WebP-Ausschnitte komprimiert werden).

```bash
# 1. EXIF-Daten entfernen, Textausschnitte erzeugen und normiertes JSON schreiben
./open-packaged-food/bin/opf submit \
  --input draft.json \
  --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg \
  --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 \
  --media-out-dir opf-media

# 2. Daten, Bilder und Querverweise lokal prüfen
./open-packaged-food/bin/opf validate opf-data/products
./open-packaged-food/bin/opf validate-media opf-media
./open-packaged-food/bin/opf check-media-refs --media-dir opf-media opf-data/products
```

Legen Sie anschließend jeweils einen Branch in `opf-media` und `opf-data` an und öffnen Sie beide PRs (mit `uvx` und `gh` genügt auch `uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.5 opf pr ...`). Wichtig ist die Reihenfolge: **immer zuerst den `opf-media`-PR mergen, danach den `opf-data`-PR**, damit die Prüfung die Bilder bereits auf `main` findet.

Zwei klare Grenzen bleiben unverrückbar:
- **Nur zugeschnittene Textfelder einreichen** (Nährwerttabelle, Zutatenliste, Herstellerblock, Barcode) – niemals die gestaltete Vorderseite der Verpackung;
- **Daten nur monatsgenau angeben (`YYYY-MM`)** – keine tagesgenauen Herstellungs-, Ablauf- oder Kaufdaten und keine Chargennummern.

---

## Zusammenspiel der drei Repositories

```text
  Abfrage: Nutzer / KI ──(HTTP GET)──▶ GitHub Pages Statische API & Suche (/v1/, /)
                                                    ▲
                                                    │ automatischer Build & Deploy
  Beitrag: opf submit ──▶ opf-media (WebP-Ausschnitte) ──(① zuerst mergen)──▶ opf-data (Produkt-JSON)
```

<details>
<summary>Repository-Aufbau und lokale Vorschau</summary>

```text
open-packaged-food/
├── bin/opf                    # CLI-Einstiegspunkt
├── opf/                       # Prüfung, Zutatenabgleich, Umrechnung, Bildbereinigung & Build
├── web/                       # 7-sprachiger Web-Explorer, Offline-Scanner & Filter
├── spec/                      # Spezifikation und JSON-Schemas
├── docs/DESIGN.md             # Oberflächen- und Darstellungsregeln
├── profiles/ & dictionaries/  # CN/US/EU/JP-Regeln sowie Nährstoff-, Zusatzstoff- und Allergenlisten
├── skills/opf/                # Einsatzbereiter Agent-Skill und Minimalvorlage
└── tests/                     # Unit- und Integrationstests
```

```bash
cd open-packaged-food
python3 -m unittest discover -s tests -v
./bin/opf serve --data-dir ../opf-data/products
```

</details>

---

## Lizenzen (REUSE-Schichten)

- **Werkzeuge & Web-Explorer (`opf/`, `bin/`, `web/` außer `web/vendor/`, `.github/`, `tests/`)**: [`AGPL-3.0-or-later`](LICENSE) nach außen (**[`Apache-2.0`](LICENSES/Apache-2.0.txt) permissiv eingehend** für Beiträge + DCO `git commit -s`, siehe [`CONTRIBUTING.md`](CONTRIBUTING.md))
- **Spezifikationen, Schemas, Wörterbücher, Regelprofile, Skills, Docs & Vendor (`spec/`, `dictionaries/`, `profiles/`, `skills/`, `docs/`, `web/vendor/`)**: [`Apache-2.0`](LICENSES/Apache-2.0.txt) (direkte Integration ohne Copyleft-Weitergabe)
- **Datenbank & Produkt-JSON (`opf-data`)**: [`ODbL-1.0`](LICENSE-DATA) / `DbCL-1.0` (Leitfaden: [`docs/ODbL-GUIDE.md`](docs/ODbL-GUIDE.md))
- **Zugeschnittene Etikett-Nachweise (`opf-media`)**: [`CC-BY-SA-4.0`](LICENSE-MEDIA)
- Maschinenlesbare SPDX-Deklarationen je Pfad in [`REUSE.toml`](REUSE.toml) und [`LICENSES/`](LICENSES/); Governance-Regeln in [`GOVERNANCE.md`](GOVERNANCE.md).
