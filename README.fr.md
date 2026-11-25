# OpenPackagedFood (`opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Contribuer](CONTRIBUTING.md)** · **[Spécification](spec/SPEC.md)** · **[Design](docs/DESIGN.md)**

> 🌐 **Recherche en ligne et scan local** : [https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> 📦 **Données** : [mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · 🖼️ **Images** : [mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · 🧰 **Outils & Skill** : [mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

Quiconque a déjà développé une application de suivi nutritionnel ou demandé à une IA de lire le dos d'un paquet de biscuits s'est sans doute heurté aux mêmes écueils discrets.

L'emballage affiche « 0 g d'acides gras trans », et l'IA vous assure aussitôt que le produit est irréprochable — en oubliant que la réglementation américaine autorise à arrondir à zéro tout ce qui reste sous 0,5 g par portion, tout comme d'autres règles permettent d'inscrire 0 pour des traces de sodium. Devant une longue liste d'ingrédients, un modèle saute facilement un additif ou ajoute un mot qui n'était pas imprimé. Et dans les rayons d'un supermarché, la réalité est encore plus nuancée : deux bouteilles portant exactement le même code-barres peuvent sortir de deux usines sous-traitantes différentes, ou correspondre à une ancienne recette sucrée et à une nouvelle formule allégée vendues côte à côte. Par commodité, la plupart des bases écrasent l'une par l'autre ou font une moyenne.

Pour surveiller des allergies, suivre une nutrition clinique ou tenir des comptes alimentaires sérieux, cet « à-peu-près » ne suffit pas.

J'ai écrit **OpenPackagedFood (OPF)** avec une idée toute simple : remettre au clair ces comptes brouillés. Je ne distribue pas de notes de santé en feux tricolores — juger ce qui est bon pour la santé appartient à celui qui mange et à son médecin. Je cherche seulement à consigner fidèlement ce qui est écrit noir sur blanc sur l'emballage, pour que les logiciels et les assistants IA puissent compter sur des faits sûrs.

---

## Quatre règles simples

- **Un « 0 » imprimé n'est pas un zéro mathématique**
  Les valeurs ramenées à zéro par tolérance réglementaire sont conservées comme bornes supérieures (`<`), sans jamais être confondues avec une absence réelle. Chaque conversion pour 100 g ou 100 ml est calculée avec exactitude.
- **Les ingrédients sont vérifiés caractère par caractère**
  La liste structurée doit pouvoir se recomposer mot pour mot dans l'ordre exact du texte imprimé sur le paquet. Qu'une virgule soit en trop ou qu'une lettre manque, la validation rejette la fiche — sans laisser l'IA improviser.
- **Même code-barres, usines ou recettes distinctes restent séparées**
  Lorsque plusieurs fabricants ou versions de recette se partagent un code-barres, chaque variante garde sa propre fiche. Si des variantes actives diffèrent réellement, l'API retient les valeurs générales et vous invite à jeter un œil à l'étiquette que vous tenez en main plutôt que de servir une moyenne trompeuse.
- **Données, images et outils séparés, publiés en statique**
  Fiches JSON, recadrages textuels d'étiquettes et outils en ligne de commande vivent dans trois dépôts Git distincts, puis sont publiés en fichiers statiques sur GitHub Pages. Un script ou un agent IA n'a besoin que d'une simple requête HTTP — sans clé d'API ni serveur à entretenir.

---

## Pour commencer

### 1. Scanner directement au supermarché

Ouvrez **[l'explorateur web](https://mickey996icu.github.io/opf-data/)**, pointez la caméra arrière sur un code-barres ou choisissez une photo dans votre galerie. Le décodage s'exécute entièrement dans votre navigateur (avec `BarcodeDetector` natif lorsqu'il est disponible, et bascule automatique vers `ZXing` embarqué hors ligne partout ailleurs) — aucune image n'est envoyée sur Internet.

Pour les besoins alimentaires précis, les filtres en haut de page permettent de trier par pays, d'écarter séparément les allergènes avérés et les traces possibles, d'exclure des codes d'additifs ou de fixer des seuils pour 100 g/100 ml.

### 2. Ajouter la Skill à votre assistant IA

Reliez `skills/opf` au dossier des skills de votre assistant. Si vous lui montrez la photo d'un produit, il interrogera d'abord les fiches statiques `/v1/` ; si le produit n'y figure pas encore, il lira simplement l'étiquette sur votre image pour répondre à votre question, sans insister pour vous faire contribuer.

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git ~/src/open-packaged-food

# Choisissez le chemin adapté à votre outil
mkdir -p .agents/skills && ln -s ~/src/open-packaged-food/skills/opf .agents/skills/opf
mkdir -p ~/.claude/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.claude/skills/opf
mkdir -p ~/.codex/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.codex/skills/opf
mkdir -p ~/.gemini/config/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.gemini/config/skills/opf
```

### 3. Prendre une photo et proposer une PR

La validation et la génération du site reposent uniquement sur la bibliothèque standard de Python (`Pillow` n'est chargé que pour nettoyer et encoder localement les images WebP).

```bash
# 1. Supprimer les métadonnées EXIF, produire les recadrages WebP et générer le JSON
./open-packaged-food/bin/opf submit \
  --input draft.json \
  --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg \
  --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 \
  --media-out-dir opf-media

# 2. Vérifier localement les données, les images et leurs références croisées
./open-packaged-food/bin/opf validate opf-data/products
./open-packaged-food/bin/opf validate-media opf-media
./open-packaged-food/bin/opf check-media-refs --media-dir opf-media opf-data/products
```

Poussez ensuite une branche et ouvrez une PR sur `opf-media` et sur `opf-data` (ou exécutez `uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.3 opf pr ...` si `uvx` et `gh` sont installés). Respectez l'ordre : **fusionnez toujours la PR `opf-media` en premier, puis celle d'`opf-data`**, afin que la CI retrouve bien les images sur `main`.

Deux limites à ne pas franchir :
- **N'envoyez que des recadrages des zones de texte** (tableau nutritionnel, liste d'ingrédients, fabricant, code-barres) — jamais la face avant complète du paquet ;
- **Limitez les dates au mois (`YYYY-MM`)** — n'inscrivez jamais de dates exactes de fabrication, de péremption, de ticket de caisse ni de numéro de lot.

---

## Comment les trois dépôts fonctionnent ensemble

```text
  Lecture : Utilisateur / IA ──(HTTP GET)──▶ API statique & explorateur GitHub Pages (/v1/, /)
                                                    ▲
                                                    │ compilation et publication auto
  Envoi :   opf submit ──▶ opf-media (WebP recadrés) ──(① fusionner d'abord)──▶ opf-data (JSON produit)
```

<details>
<summary>Structure du dépôt et aperçu local</summary>

```text
open-packaged-food/
├── bin/opf                    # Point d'entrée CLI
├── opf/                       # Validation, alignement d'ingrédients, conversions, images & build
├── web/                       # Explorateur en 7 langues, scanner hors ligne et filtres
├── spec/                      # Spécification et schémas JSON
├── docs/DESIGN.md             # Règles d'interface et de présentation des données
├── profiles/ & dictionaries/  # Règles CN/US/EU/JP et dictionnaires nutriments/additifs/allergènes
├── skills/opf/                # Agent Skill prêt à l'emploi et modèle minimal
└── tests/                     # Suite de tests unitaires et d'intégration
```

```bash
cd open-packaged-food
python3 -m unittest discover -s tests -v
./bin/opf serve --data-dir ../opf-data/products
```

</details>

---

## Licences (couches REUSE)

- **Outils & explorateur web (`opf/`, `bin/`, `web/` hors `web/vendor/`, `.github/`, `tests/`)** : [`AGPL-3.0-or-later`](LICENSE) en sortie (**[`Apache-2.0`](LICENSES/Apache-2.0.txt) permissif en entrée** pour les contributions + DCO `git commit -s`, voir [`CONTRIBUTING.md`](CONTRIBUTING.md))
- **Spécifications, schémas, dictionnaires, profils, skills, docs & vendor (`spec/`, `dictionaries/`, `profiles/`, `skills/`, `docs/`, `web/vendor/`)** : [`Apache-2.0`](LICENSES/Apache-2.0.txt) (intégration sans propagation copyleft)
- **Base de données & JSON produits (`opf-data`)** : [`ODbL-1.0`](LICENSE-DATA) / `DbCL-1.0` (guide : [`docs/ODbL-GUIDE.md`](docs/ODbL-GUIDE.md))
- **Recadrages d'étiquettes (`opf-media`)** : [`CC-BY-SA-4.0`](LICENSE-MEDIA)
- Déclarations SPDX complètes dans [`REUSE.toml`](REUSE.toml) et [`LICENSES/`](LICENSES/) ; gouvernance dans [`GOVERNANCE.md`](GOVERNANCE.md).
