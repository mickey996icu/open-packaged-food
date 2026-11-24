# OpenPackagedFood（`open-packaged-food` / CLI：`opf`）

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[Contributing](CONTRIBUTING.md) | [贡献指南](CONTRIBUTING.zh-CN.md)** · **[技术规范 (`v0.2`)](spec/SPEC.md)** · **[界面与数据展示规范](docs/DESIGN.md)**

> **🌐 在线数据库检索页与免鉴权静态 API**：[https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> **📦 商品数据主仓**：[mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · **🖼️ 标签图片媒体仓**：[mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · **🧰 工具链、规范与 Agent Skill 仓**：[mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

**以证据为准、零主观评判、为 AI Agent 与开发者打造的全球工业预包装食品开放数据库工具链、技术规范、静态 API 构建器与开箱即用 Agent Skill。**

---

## 为什么需要 OpenPackagedFood？

工业预包装食品看似标签清晰，在进入程序与 AI Agent 计算时却有 4 个顽疾——OPF `v0.2` 从数据结构与编译器层面逐一解决：

1. **拒绝主观健康打分，忠实保留法规修约边界**
   OPF **永远不输出红绿灯健康分**，只忠实记录包装原表（`core` + `attributes`）并通过 Python `Decimal` 确定性编译每 `100g` / `100ml` 的 `normalized` 数值：
   - **明确区分三态数值**：原文直接标示（`reported`）、公式换算（`ƒ derived`，例如每份换算至每 100g 或 kJ/kcal 互算、食盐与钠互算），以及**法规标零修约上界（`< regulatory_upper_bound`）**；
   - 绝不把美标 FDA 单份 `< 0.5g` 反式脂肪/反式脂肪酸或国标 GB 28050 每 100g `≤ 5mg` 钠标 `"0"` 当成精确数学 `0`——系统会自动传播 `<` 上界并挂载 `REGULATORY_ZERO_ROUNDING_ARTIFACT` 标记。
2. **杜绝 AI 提取幻觉：配料表 100% 单调无损还原校验**
   OCR 或大模型解析配料表时最容易漏字或脑补配料。OPF 采用**无字符偏移配料语法树（Span-Free `ingredients_tree`）**，CI 强制校验树节点从左到右还原是否与原文 `attributes.ingredients_text` 严格单调对齐——**多一字、漏一字直接拒绝合入**；同时不依赖易碎的字符索引，标点重排不改变 `core_fingerprint`。
3. **正视真实供应链的多产地代工与配方改版**
   同一条形码（GTIN）下常有不同代工厂（如多个 `SC` 生产许可证编号）或新旧减糖改版同时在售：
   - 默认归入 `<market>/default` 轨道，需要时按需拆分为具名 **Track**（如 `CN/plant:SC10600000000001`、`EU/code:A`）；
   - 每个版本拥有永久 26 位 Crockford ULID（`edition_id`），支持 `<edition_id>@<rev>` 精确内容锁定与双向 RFC 6902 `patch` / `reverse_patch` 勘误——补图佐证（`evidence[]`）**零升版（不递增 `rev`）**，改错别字不打断外部引用；重复 PR 通过 `EditionRedirect`（`merged_into`）就地吸收跳转；
   - 构建期依据 `supersedes[]`、仅含 `YYYY-MM` 的 `vintage_month` 与 `[3, 18]` 个月截断窗口自动推导 `active` / `stale` / `superseded` / `discontinued` / `retracted` 生命周期；
   - 当同条码在售版本存在实质差异时，Compact API 返回 **`divergent`** 并故意省略顶层 `normalized` 与 `ingredients_text`，**硬性禁止 Agent 按均值/区间入账**，必须提示用户对照包装（`SC` 证号/产线码/配料数字）选定唯一版本。
4. **三仓物理隔离、零服务器、CDN 抗压防刷**
   JSON 数据（`opf-data`）与 `<= 1000px` 去 EXIF 的内容寻址 WebP 局部标签图（`opf-media`）彻底分离，逻辑 URI（`opf-media://sha256/<hex>`）可随时零成本切换至 R2/S3/CDN；静态数据托管于 GitHub Pages `/v1/` CDN，任何脚本或 AI Agent 单次 HTTP `GET` 即可读取。

---

## 三仓库协作架构

```text
  购买前查库 & 顺手拍照贡献的用户 / AI Agent (Claude Code, Antigravity, Codex, Cursor ...)
         │
         ├── 查库阶段：纯 HTTP GET 查询 GitHub Pages /v1/ 静态接口（零依赖）
         └── 贡献阶段：
               • 第一阶段（开发者纯 Git 主路径）：opf submit -> opf validate -> git push 双仓 PR
               • 可选一键自动化：`uvx --from ... opf pr`（`uvx` + `gh`）
               • 第二阶段（普通用户经由 Agent Relay）：POST <OPF_SUBMIT_URL>/v1/submissions（免 Git/CLI）
         ▼
  ┌──────────────────────────────────────────┐  ① 先合入 Media PR   ┌──────────────────────────────────────────┐
  │       mickey996icu/opf-media             │ ───────────────────▶ │        mickey996icu/opf-data             │
  │  • media/<h0:2>/<h2:4>/<sha256>.webp     │   opf-data CI 运行   │  • products/{gtin|opf}/.../{product}/    │
  │  • 仅收局部文字标签裁剪图 (≤1000px WebP) │   check-media-refs   │    ├── product.json (别名与轨道指引)      │
  │  • CI: opf validate-media (纯标准库)     │   确保图片已存在后再 │    └── editions/<ulid>.json              │
  └────────────────────┬─────────────────────┘   ② 合入 Data PR     └────────────────────┬─────────────────────┘
                       │                                                                 │
                       │  OPF_MEDIA_BASE_URL (GitHub raw / 未来 R2/S3 CDN)                │ 触发 build & deploy
                       └──────────────────────────────▶ ┌────────────────────────────────▼────────────────────────┐
                                                        │  GitHub Pages 静态发布 (mickey996icu.github.io/opf-data) │
                                                        │  • MD3E 7语检索网页、本地扫码与三栏筛选台 (/)         │
                                                        │  • /v1/meta.json · /v1/index/catalog.jsonl              │
                                                        │  • /v1/gtin/{p1}/{p2}/{gtin14}.json (.full.json)        │
                                                        └─────────────────────────────────────────────────────────┘
```

> 工具仓 [`mickey996icu/open-packaged-food`](https://github.com/mickey996icu/open-packaged-food) 在上述三条 CI/Pages 流水线中均以 `v0.2.1` 固定版本被拉取执行，校验/构站路径零第三方运行依赖（`Pillow` 仅在本地生成 WebP 标签图时按需懒加载）。

---

## 如何使用（3 种方式）

### 方式一：网页在线检索、纯静态扫码与复杂条件筛选

直接访问 **[https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)**（面向普通用户的只读检索前端，支持 7 语界面与浅色/深色主题）：

- **纯前端静态扫码**：支持后置摄像头实时扫描、相册选图及手动输入（优先原生 `BarcodeDetector` 并内置离线 `ZXing` 兜底解码与 GS1 Mod-10 校验，不上传图片、不调用外部查码接口）；
- **顶部三栏高级筛选工作台**：支持销售市场（`CN` / `US` / `EU` / `JP` 等多选）、消歧模式 / 证据等级 / 法规 Profile / 品牌多选；
- **安全致敏原多选排除**：同时按真实存在（`contains`）与交叉接触风险（`may_contain`）过滤商品；
- **配料与 INS 添加剂包含/排除 + 零添加快捷筛选**：按配料词根或国际编码（如 `300`、`500(ii)`）正反向检索；
- **百克营养数值规则构建器**：动态组合每 `100g`/`100ml` 的 `≤`、`≥` 或区间 `[A, B]` 条件（严格尊重 `<` 修约上界语义）。

### 方式二：安装 `opf` Agent Skill（购买前查库 + 404 纯粹答疑）

将 [`skills/opf`](skills/opf) 软链或复制到你的 AI 编程助手 Skills 目录，即可在日常买零食/对比配料表时自动先查 `/v1/`；面向普通用户遇到 `404` 拍照时，Agent 只高质量回答购买决策问题，绝不主动推销投稿或输出 `draft.json`（仅在第二阶段配置 `OPF_SUBMIT_URL` 或检测到开发者环境时开放顺手贡献提示）：

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git ~/src/open-packaged-food

# 1) 当前项目通用路径 (.agents/skills)
mkdir -p .agents/skills && ln -s ~/src/open-packaged-food/skills/opf .agents/skills/opf

# 2) 全局 Claude Code / Codex / Antigravity
mkdir -p ~/.claude/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.claude/skills/opf
mkdir -p ~/.codex/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.codex/skills/opf
mkdir -p ~/.gemini/config/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.gemini/config/skills/opf
```

> 默认查询地址：`https://mickey996icu.github.io/opf-data`（可用环境变量 `OPF_BASE_URL` 覆盖）；第一阶段仅开放开发者纯 Git 贡献，普通用户投稿将在第二阶段启用 `OPF_SUBMIT_URL` 后经由 Agent 开放。

### 方式三：开发者纯 Git 双仓协作主路径（及可选 `uvx` 快捷方式）

第一阶段开发者贡献以纯 Git 三仓协作为主路径（详见 [`CONTRIBUTING.zh-CN.md`](CONTRIBUTING.zh-CN.md)）：

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git
git clone https://github.com/mickey996icu/opf-data.git
git clone https://github.com/mickey996icu/opf-media.git

# 1. 本地脱敏压缩 WebP（<=1000px，剥离 EXIF）并生成规范产品/版本 JSON
./open-packaged-food/bin/opf submit \
  --input draft.json \
  --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg \
  --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 \
  --media-out-dir opf-media

# 2. 校验数据仓、媒体仓与跨仓引用（纯标准库，无需安装第三方包）
./open-packaged-food/bin/opf validate opf-data/products
./open-packaged-food/bin/opf validate-media opf-media
./open-packaged-food/bin/opf check-media-refs --media-dir opf-media opf-data/products

# 3. 签名提交并推送双仓分支，点击终端链接创建双 PR（严格先合 opf-media，再合 opf-data）
git -C opf-media switch -c contrib/media-label && git -C opf-media add -A && git -C opf-media commit -s -m "media(label): add cropped label evidence" && git -C opf-media push -u origin HEAD
git -C opf-data switch -c contrib/product-record && git -C opf-data add -A && git -C opf-data commit -s -m "feat(product): add packaged food record" && git -C opf-data push -u origin HEAD
```

**可选一键自动化通道（`uvx` + `gh`）**：已安装 `uvx` 与登录 `gh auth login` 的开发者，也可选用 `opf pr` 替代上述手动建分支推送步骤：

```bash
uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.1 \
  opf pr --input draft.json \
  --photo nutrition_table=crop_nutrition.jpg \
  --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08
```

本地测试与构站预览：

```bash
cd open-packaged-food
python3 -m unittest discover -s tests -v
./bin/opf build \
  --data-dir ../opf-data/products \
  --out-dir /tmp/opf-site \
  --canonical-base "https://mickey996icu.github.io/opf-data" \
  --media-base-url "https://raw.githubusercontent.com/mickey996icu/opf-media/main"
./bin/opf serve --dir /tmp/opf-site
```

---

## 如何贡献商品与维护双仓库 PR 闭环

详细步骤见 **[贡献指南 (`CONTRIBUTING.zh-CN.md`)](CONTRIBUTING.zh-CN.md)**，最小投稿示例见 [`skills/opf/examples/draft.minimal.json`](skills/opf/examples/draft.minimal.json)。

| 步骤 | 命令 / 动作 | 说明 |
| :--- | :--- | :--- |
| **1. 局部裁剪与 WebP 脱敏** | `opf sanitize-media <img...> [--media-root .../opf-media]` | 默认 `exif_transpose` 烘焙方向、等比压至 `≤ 1000px` 无 EXIF/XMP/IPTC 的内容寻址 `.webp`（`--photo` 可直接整合入 `submit`/`pr`）。**严禁上传完整包装正面宣传图**。 |
| **2. 智能入库 / 冲突分流** | `opf submit --input draft.json --out-dir .../products [--photo region=img]` | 按 `(id, track, core_fingerprint)` 自动新建 `rev: 1`、增量 `enrichment`（`rev + 1`）或零升版补图佐证（`corroborated`）；冲突时显式 `--amend` / `--supersede` / `--new-variant`。 |
| **3. 提交双仓分支并创建 PR** | `git switch -c ... && git commit -s && git push`（或可选 `uvx ... opf pr`） | 分别推送 `opf-media` 与 `opf-data` 分支并点击终端链接创建双 PR；若已配置 `uvx` 与 `gh`，也可选用 `opf pr` 一键自动开 PR。 |
| **4. 跨仓合入顺序** | **先合入 `opf-media` PR $\rightarrow$ 后合入 `opf-data` PR** | `opf-data` CI 会运行 `opf check-media-refs` 验证图片已落在 `opf-media main`。 |

- **隐私红线**：`evidence[]` 仅允许 `YYYY-MM` 粒度的 `vintage_month`；严禁 `purchase_date`、`purchase_price`、精确到日的 `production_date`/`expiry_date`/`expiry_estimate` 与 `lot_number`。

---

## 仓库目录结构

```text
open-packaged-food/
├── bin/opf                         # 零依赖 CLI 命令行入口
├── pyproject.toml & setup.py       # Standalone wheel / uvx 资源随包打包构建配置
├── opf/
│   ├── resources.py                # 源码检出与 wheel `_bundled` 资源根目录自动定位
│   ├── ids.py                      # GTIN-14 GS1 校验位、020-029/200-299 拦截、ULID 与 Track 键
│   ├── registries.py               # 词典与全球法规插件加载器（防误报致敏原匹配）
│   ├── ingredients.py              # 确定性配料表解析器与无偏移 AST 单调无损校验器
│   ├── patches.py                  # RFC 6901/6902 双向 JSON Patch 引擎与 @rev 历史重建
│   ├── normalize.py                # 100g/100ml 编译器、修约上界传播、双指纹计算与生命周期
│   ├── validator.py                # JSON Schema v0.2、商品目录 DAG/轨道/补丁与隐私红线校验器
│   ├── media.py                    # WebP ≤1000px 脱敏转码（懒加载 Pillow）+ 纯标准库 `validate-media`
│   ├── builder.py                  # GitHub Pages 静态 API (/v1/) 四态 Compact/Full 与检索页构建器
│   └── cli.py                      # CLI 子命令（submit/pr/validate/validate-media/check-media-refs/build...）
├── web/                            # 中英双语可切换 MD3E 静态数据库检索前端与复杂筛选工作台
├── spec/                           # SPEC.md & schema/*.v0.2.schema.json
├── docs/DESIGN.md                  # 界面、色彩与数据三态展示设计规范
├── profiles/ & dictionaries/       # CN/US/EU/JP 法规插件 + 营养素/INS/致敏原词典
├── skills/opf/                     # HTTP 优先、先答后邀、双通道 Agent Skill 与 draft.minimal.json
└── tests/                          # 自包含单元测试与集成测试套件
```

---

## 开源许可（Licensing）

- **工具链与代码（`opf/`、`bin/`、`web/`、`.github/`）**：[GNU Affero General Public License v3.0 or later (`AGPL-3.0-or-later`)](LICENSE)
- **数据库与商品 JSON（`opf-data`）**：[Open Database License v1.0 (`ODbL-1.0`) / `DbCL-1.0`](LICENSE-DATA)
- **裁剪标签证据图片（`opf-media`）**：[Creative Commons Attribution-ShareAlike 4.0 International (`CC-BY-SA-4.0`)](LICENSE-MEDIA)
