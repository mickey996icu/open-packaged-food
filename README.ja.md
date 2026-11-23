# OpenPackagedFood (`open-packaged-food` / CLI: `opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Contributing](CONTRIBUTING.md) | [貢献指南](CONTRIBUTING.zh-CN.md)** · **[技術仕様 (`v0.2`)](spec/SPEC.md)** · **[UI 設計 (`DESIGN.md`)](docs/DESIGN.md)**

> **🌐 オンライン Web データベース・静的 API**: [https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> **📦 商品データ倉 (`opf-data`)**: [mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · **🖼️ ラベル証拠画像倉 (`opf-media`)**: [mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · **🧰 ツール・仕様・Agent Skill (`open-packaged-food`)**: [mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

**根拠第一（Evidence-First）・中立評価（Zero-Judgment）による加工食品オープンデータベースの標準仕様、Python 3.12 標準ライブラリ実装の検証・静的サイトビルダー、および AI Agent Skill。**

---

## 主な設計原則と機能

- **法令丸め上界（`<`）と決定的 100g/100ml 換算（`ƒ`）の厳格分離**: 主観的な健康スコアは一切算出せず、容器表示原文、`Decimal` による厳密な換算値（`ƒ`）、および法令 0 表示丸め上限値（`< regulatory_upper_bound`）を区別して保存します。
- **可逆・単調な原材料ツリー検証**: `core.ingredients_tree` と原文 `attributes.ingredients_text` の左から右への単調一致を CI で強制検証（日本語の `／` 以降添加物分割など 4 法域の表記規則に対応）。
- **4 法域・7 言語対応**: `CN` (`zh-Hans` / `zh-CN`)、`US` (`en`)、`JP` (`ja`)、`EU` (`en`, `de`, `fr`, `es`, `it`) の表示基準プロファイル・アレルゲン・添加物（INS / E 番号）・7 言語 Web UI を標準装備。
- **プライバシー・著作権保護**: 商品ラベルの機能的テキスト領域（7 種 `region`）のみを切り抜き、EXIF / XMP を完全削除（長辺 `<= 1000px` WebP）。表面の商業パッケージ画像や購入日時・価格・精密ロット番号の登録は禁止されています。
- **ブラウザ完結の静的バーコードスキャン**: Web エクスプローラー上でカメラ・画像選択・手入力によるローカルスキャン（`BarcodeDetector` + GS1 Mod-10 検証、外部送信なし）に対応。

---

## クイックスタート（第 1 段階：開発者向け純 Git 主経路）

> 一般ユーザー向けの検索・スキャンは Web UI で完結し、エージェント経由の投稿機能は第 2 段階（`OPF_SUBMIT_URL` HTTP Relay 構成後）で公開されます。第 1 段階は開発者による純 Git デュアル PR のみを受け付けています。

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git
git clone https://github.com/mickey996icu/opf-data.git
git clone https://github.com/mickey996icu/opf-media.git

./open-packaged-food/bin/opf submit --input draft.json --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 --media-out-dir opf-media
./open-packaged-food/bin/opf validate opf-data/products
```

- それぞれブランチを切って `git commit -s`・`git push` し、**必ず `opf-media` PR を先にマージ**し、その後に `opf-data` 側 PR をマージしてください（`opf check-media-refs` 検証のため）。
- **任意のワンステップ自動化 (`uvx` + `gh`)**：`uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.0 opf pr --input draft.json --photo ...` もオプションで利用できます。詳細は [README.md](README.md)・[CONTRIBUTING.md](CONTRIBUTING.md) および [spec/SPEC.md](spec/SPEC.md) をご参照ください。
