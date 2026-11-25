# OpenPackagedFood (`opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Contributing](CONTRIBUTING.md)** · **[技術仕様](spec/SPEC.md)** · **[設計指針](docs/DESIGN.md)**

> 🌐 **オンライン検索・ローカルスキャン**：[https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> 📦 **商品データ**：[mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · 🖼️ **ラベル画像**：[mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · 🧰 **ツール・Skill**：[mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

スーパーで何気なくお菓子の袋を裏返してみると、小さな文字で原材料名と栄養成分表示がびっしり並んでいます。食事管理アプリを作ったことがある方や、AI にラベルの写真を渡して確認を頼んだことがある方なら、似たようなもどかしさを覚えたことがあるはずです。

包装に「トランス脂肪酸 0g」と印字されていれば、AI は安心して食べられると答えます。しかし食品表示の決まりを少しでも知っていれば、米国の基準では 1 食あたり 0.5g 未満を 0 と表示してよく、日本の基準や中国の基準でも極微量のナトリウムなどを 0 と記すことが許されていると気づきます。長い原材料一覧を読み取らせると、AI が添加物をいくつか見落としたり、袋に書かれていない言葉まで書き足してしまったりすることも珍しくありません。

売り場の実情はさらにやっかいです。同じバーコードが印字された飲み物でも、裏を返せば製造工場が二か所、三か所と分かれていたり、旧来の甘い配合と糖質控えめの新配合が同じ棚に並んでいたりします。従来の食品データベースの多くは手間を省くために、新しい情報で古い記録を上書きするか、大ざっぱに平均値を取って済ませてきました。

アレルゲンを避けたいときや、医療上の栄養管理、毎日の正確な記録をつけたいときには、こうした「だいたい合っていればよい」というデータは頼りになりません。

私が **OpenPackagedFood (OPF)** を作った理由は、ごく素朴なものです。この曖昧になりがちな記録を、きちんと整理したかっただけです。信号機のような健康スコアはつけません。体に良いか悪いかを判断するのは、食べる本人とお医者さんの役目です。パッケージに書かれている文字をそのまま書き留め、プログラムや AI アシスタントが計算に使える根拠データとして残しておきたいだけです。

---

## 守っている四つの約束

- **印字された「0」を、数学上の 0 として扱わない**
  法令で 0 表示の丸めが認められている数値は、「上限値未満（`<`）」として明確に残し、本当に含まれないゼロと混同しません。100g・100ml あたりの換算も正確な計算で行います。
- **原材料表示は一字一句たがわず照合する**
  分解した原材料データは、元の文字列へ左から右へそのまま復元し、パッケージ原文と照らし合わせます。句読点が一つ多かったり一文字抜けていたりすれば検証で弾かれ、AI が推測で補う余地を残しません。
- **同じバーコードでも、工場や配合が違えば別に残す**
  製造所や配合が異なる版が現れても、互いを上書きせず独立した記録として残します。販売中の品に実質的な違いがある場合は、平均値でごまかさず、手元の包装を自分の目で確かめるよう促します。
- **データ・画像・ツールを分け、静的に配信する**
  商品 JSON、個人情報を削ぎ落とした文字部分の切り抜き画像、検証用ツールを三つの Git リポジトリに分けて管理し、GitHub Pages 上で静的ファイルとして公開しています。API キーも専用のバックエンドサーバーも要らず、通常の HTTP GET リクエストひとつで取得できます。

---

## さっそく使ってみる

### 1. お店でそのままブラウザスキャン

**[オンライン検索ページ](https://mickey996icu.github.io/opf-data/)** を開き、スマートフォンの背面カメラをバーコードに向けるか、写真フォルダから画像を選びます。読み取り処理はすべてブラウザのローカル環境で完結し（ネイティブ `BarcodeDetector` が使える端末はそれを優先し、非対応ブラウザでは同梱のオフライン `ZXing` へ自動で切り替わります）、画像が外部へ送信されることはありません。

食事制限がある場合は、上部のフィルターから販売国の基準、確定アレルゲンとコンタミネーション（微量混入のおそれ）の個別除外、添加物コード、栄養素ごとの条件を組み合わせて絞り込めます。

### 2. AI アシスタントに Skill を組み込む

リポジトリ内の `skills/opf` を普段使っている AI ツールのスキルディレクトリへリンクします。お菓子の写真を撮って尋ねると、まず静的 `/v1/` エンドポイントを確認してから答えを返します。まだ未収録の新しい商品であれば、目の前の写真から読み取れる事実だけを率直に答え、登録を催促するような画面は出しません。

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git ~/src/open-packaged-food

# お使いのツールに合わせて実行してください
mkdir -p .agents/skills && ln -s ~/src/open-packaged-food/skills/opf .agents/skills/opf
mkdir -p ~/.claude/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.claude/skills/opf
mkdir -p ~/.codex/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.codex/skills/opf
mkdir -p ~/.gemini/config/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.gemini/config/skills/opf
```

### 3. 写真を撮り、PR を送って記録を補う

検証と静的サイト生成はすべて Python 標準ライブラリのみで動作し、追加パッケージは不要です（ローカルで WebP 画像を圧縮するときだけ必要に応じて `Pillow` を読み込みます）。

```bash
# 1. EXIF を消去してラベル文字部を切り抜き、正規化 JSON を生成
./open-packaged-food/bin/opf submit \
  --input draft.json \
  --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg \
  --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 \
  --media-out-dir opf-media

# 2. データ・画像・リポジトリ間参照をローカル検証
./open-packaged-food/bin/opf validate opf-data/products
./open-packaged-food/bin/opf validate-media opf-media
./open-packaged-food/bin/opf check-media-refs --media-dir opf-media opf-data/products
```

検証が通ったら `opf-media` と `opf-data` にそれぞれブランチを切って PR を送ります（`uvx` と `gh` が使える環境なら `uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.3 opf pr ...` でまとめて実行できます）。マージは**必ず画像倉（`opf-media`）を先、データ倉（`opf-data`）を後**にしてください。画像がメインブランチに入る前にデータ側をマージしようとすると CI が停止します。

投稿前に二つの点だけご留意ください：
- **文字表示の切り抜き部分だけを送る**（栄養成分表、原材料枠、製造者欄、バーコード周辺）。商品表面のパッケージデザイン全体の写真は著作権配慮のため投稿しないでください。
- **日付は年月（`YYYY-MM`）までにとどめる**。日単位の製造年月日、賞味期限、購入日やロット番号はプライバシー保護のため検証機がすべて拒否します。

---

## 三つのリポジトリの連携

```text
  検索：ユーザー / AI ──(HTTP GET)──▶ GitHub Pages 静的 API・Web 検索 (/v1/, /)
                                                ▲
                                                │ 自動ビルド・公開
  投稿：opf submit ──▶ opf-media (切り抜き WebP) ──(① 先にマージ)──▶ opf-data (商品 JSON)
```

<details>
<summary>ディレクトリ構成とローカルプレビュー手順</summary>

```text
open-packaged-food/
├── bin/opf                    # CLI エントリーポイント
├── opf/                       # 検証、原材料照合、単位換算、画像サニタイズ、サイト生成
├── web/                       # 多言語 Web エクスプローラー・ローカルスキャナー・フィルター
├── spec/                      # 仕様書と JSON スキーマ
├── docs/DESIGN.md             # 画面とデータ表示の設計ルール
├── profiles/ & dictionaries/  # CN/US/EU/JP 表示基準と栄養素・添加物・アレルゲン辞書
├── skills/opf/                # AI Agent Skill と最小テンプレート
└── tests/                     # ユニット・統合テスト群
```

```bash
cd open-packaged-food
python3 -m unittest discover -s tests -v
./bin/opf serve --data-dir ../opf-data/products
```

</details>

---

## ライセンス

- **ツール・Web エクスプローラー（`opf/`・`bin/`・`web/`・`.github/`）**：[AGPL-3.0-or-later](LICENSE)
- **データベース・商品 JSON（`opf-data`）**：[ODbL-1.0](LICENSE-DATA) / `DbCL-1.0`
- **切り抜きラベル証拠画像（`opf-media`）**：[CC-BY-SA-4.0](LICENSE-MEDIA)
