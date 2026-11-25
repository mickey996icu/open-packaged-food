# OpenPackagedFood (`opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Contribuire](CONTRIBUTING.md)** · **[Specifica](spec/SPEC.md)** · **[Design](docs/DESIGN.md)**

> 🌐 **Ricerca online e scansione locale**: [https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> 📦 **Dati**: [mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · 🖼️ **Immagini**: [mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · 🧰 **Strumenti e Skill**: [mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

Chiunque abbia sviluppato un'app per il diario alimentare o chiesto a un'IA di leggere il retro di una confezione si è probabilmente imbattuto negli stessi piccoli trabocchetti.

Sulla busta c'è scritto «0 g di grassi trans» e il modello assicura subito che è un prodotto pulito, dimenticando che negli Stati Uniti la legge consente di arrotondare a zero qualsiasi valore sotto 0,5 g per porzione, e regole simili permettono di stampare 0 per tracce di sodio altrove. Leggendo elenchi lunghi di ingredienti, poi, l'IA salta facilmente un additivo o aggiunge parole mai esistite sull'etichetta. Sugli scaffali la realtà è ancora più sfaccettata: due bottiglie con lo stesso identico codice a barre possono provenire da stabilimenti terzisti diversi, oppure mescolare una vecchia ricetta zuccherata e una nuova formula ridotta in zuccheri. Per comodità, quasi tutte le banche dati sovrascrivono una versione con l'altra o fanno una media.

Quando occorre confrontare alla lettera gli ingredienti stampati, distinguere i limiti legali di arrotondamento (<) dallo zero matematico o ricostruire la tracciabilità tra stabilimenti e revisioni, un «più o meno» cancella proprio i dettagli essenziali.

Ho creato **OpenPackagedFood (OPF)** per una ragione semplice: mettere in ordine questi conti confusi. Non assegna voti o semafori sulla salute — decidere cosa sia salutare spetta a chi mangia e al proprio medico. Voglio soltanto trascrivere ciò che è stampato nero su bianco sulla confezione, così che programmi e assistenti IA possano contare su dati certi.

---

## Quattro regole chiare

- **Uno «0» stampato non è uno zero matematico**
  I valori arrotondati a zero per tolleranza normativa vengono registrati come limiti superiori (`<`), senza mai confonderli con una vera assenza. Ogni conversione su 100 g o 100 ml è calcolata con esattezza.
- **Gli ingredienti si confrontano carattere per carattere**
  Gli ingredienti strutturati devono potersi ricomporre esattamente nell'ordine del testo degli ingredienti trascritto (ciò protegge l'analisi, ma non rileva errori di trascrizione dell'etichetta). Se manca una lettera o compare un segno di punteggiatura in più, la validazione respinge la scheda senza lasciare spazio a ipotesi dell'IA.
- **Stesso codice a barre, stabilimenti o ricette diverse restano separati**
  Quando più produttori o versioni condividono lo stesso codice, ogni variante mantiene una scheda propria senza sovrascriversi. Se le varianti in commercio differiscono davvero, l'API trattiene i valori generali e invita a dare un'occhiata all'etichetta che si ha in mano invece di proporre una media fuorviante.
- **Dati, immagini e strumenti separati, pubblicati in forma statica**
  I file JSON dei prodotti, i ritagli testuali delle etichette e gli strumenti a riga di comando vivono in tre repository Git distinti e vengono serviti come file statici su GitHub Pages. A uno script o a un agente IA basta una normale richiesta HTTP, senza chiavi API né server da gestire.

---

## Per iniziare

### 1. Scansionare al supermercato

Aprite **[l'esploratore web](https://mickey996icu.github.io/opf-data/)**, inquadrate il codice a barre con la fotocamera posteriore o scegliete una foto dalla galleria. La decodifica avviene interamente nel vostro browser (usando `BarcodeDetector` nativo dove supportato, e passando automaticamente al decoder offline `ZXing` integrato su tutti gli altri browser) — nessuna foto viene caricata online.

Per esigenze alimentari specifiche, i filtri in alto permettono di scegliere il mercato, escludere gli allergeni che l'etichetta dichiara come «contiene» o «può contenere» (solo in base al testo stampato; verificare la confezione in mano), filtrare per codice additivo o fissare soglie per 100 g/100 ml.

### 2. Aggiungere la Skill al proprio assistente IA

Collegate `skills/opf` nella cartella delle skill del vostro assistente. Mostrandogli la foto di un prodotto, consulterà prima gli endpoint statici `/v1/`; se il prodotto non è ancora in archivio, leggerà semplicemente la foto davanti a sé per rispondere in modo obiettivo senza insistere perché inviate dati.

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git ~/src/open-packaged-food

# Scegliete il percorso adatto al vostro strumento
mkdir -p .agents/skills && ln -s ~/src/open-packaged-food/skills/opf .agents/skills/opf
mkdir -p ~/.claude/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.claude/skills/opf
mkdir -p ~/.codex/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.codex/skills/opf
mkdir -p ~/.gemini/config/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.gemini/config/skills/opf
```

### 3. Scattare una foto e aprire una PR

Sia la validazione sia la compilazione del sito usano esclusivamente la libreria standard di Python (`Pillow` viene caricato solo per ripulire e comprimere localmente le immagini WebP).

```bash
# 1. Rimuovere i metadati EXIF, salvare i ritagli WebP e generare il JSON normalizzato
./open-packaged-food/bin/opf submit \
  --input draft.json \
  --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg \
  --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 \
  --media-out-dir opf-media

# 2. Verificare in locale dati, immagini e riferimenti incrociati
./open-packaged-food/bin/opf validate opf-data/products
./open-packaged-food/bin/opf validate-media opf-media
./open-packaged-food/bin/opf check-media-refs --media-dir opf-media opf-data/products
```

Create quindi un branch e aprite le PR su `opf-media` e `opf-data` (oppure usate `uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.6 opf pr ...` se avete `uvx` e `gh`). Rispettate l'ordine: **eseguite sempre il merge prima sulla PR di `opf-media` e poi su quella di `opf-data`**, così la CI troverà le immagini già su `main`.

Due confini da non oltrepassare:
- **Inviate solo ritagli delle parti testuali** (tabella nutrizionale, elenco ingredienti, produttore, codice a barre), mai il fronte grafico completo della confezione;
- **Registrate le date solo fino al mese (`YYYY-MM`)**, senza inserire date esatte di produzione, scadenza, scontrini d'acquisto o numeri di lotto.

---

## Come collaborano i tre repository

```text
  Consultazione: Utente / IA ──(HTTP GET)──▶ API statica ed esploratore GitHub Pages (/v1/, /)
                                                    ▲
                                                    │ build e pubblicazione automatiche
  Invio:         opf submit ──▶ opf-media (WebP ritagliati) ──(① merge prima)──▶ opf-data (JSON)
```

<details>
<summary>Struttura del repository e anteprima locale</summary>

```text
open-packaged-food/
├── bin/opf                    # Punto di ingresso CLI
├── opf/                       # Validazione, controllo ingredienti, conversioni, pulizia immagini e build
├── web/                       # Esploratore in 7 lingue, scanner offline e filtri
├── spec/                      # Specifica e schemi JSON
├── docs/DESIGN.md             # Regole di interfaccia e visualizzazione dati
├── profiles/ & dictionaries/  # Regole CN/US/EU/JP e dizionari di nutrienti, additivi e allergeni
├── skills/opf/                # Agent Skill pronto all'uso e modello minimo
└── tests/                     # Suite di test unitari e di integrazione
```

```bash
cd open-packaged-food
python3 -m unittest discover -s tests -v
./bin/opf serve --data-dir ../opf-data/products
```

</details>

---

## Licenze (strati REUSE)

- **Strumenti ed esploratore web (`opf/`, `bin/`, `web/` escl. `web/vendor/`, `.github/`, `tests/`)**: [`AGPL-3.0-or-later`](LICENSE) in uscita (**[`Apache-2.0`](LICENSES/Apache-2.0.txt) permissiva in ingresso** + DCO `git commit -s`, vedi [`CONTRIBUTING.md`](CONTRIBUTING.md))
- **Specifiche, schemi, dizionari, profili, skill, docs e vendor (`spec/`, `dictionaries/`, `profiles/`, `skills/`, `docs/`, `web/vendor/`)**: [`Apache-2.0`](LICENSES/Apache-2.0.txt) (integrazione diretta senza propagazione copyleft)
- **Database e JSON dei prodotti (`opf-data`)**: [`ODbL-1.0`](LICENSE-DATA) / `DbCL-1.0` (guida: [`docs/ODbL-GUIDE.md`](docs/ODbL-GUIDE.md))
- **Ritagli delle etichette (`opf-media`)**: [`CC-BY-SA-4.0`](LICENSE-MEDIA)
- Dichiarazioni SPDX complete in [`REUSE.toml`](REUSE.toml) e [`LICENSES/`](LICENSES/); governance in [`GOVERNANCE.md`](GOVERNANCE.md).
