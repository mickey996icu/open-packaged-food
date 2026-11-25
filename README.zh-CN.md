# OpenPackagedFood (`opf`)

**[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | [Deutsch](README.de.md) | [Français](README.fr.md) | [Español](README.es.md) | [Italiano](README.it.md)** · **[贡献指南](CONTRIBUTING.zh-CN.md)** · **[技术规范](spec/SPEC.md)** · **[设计规范](docs/DESIGN.md)**

> 🌐 **在线查库与纯本地扫码**：[https://mickey996icu.github.io/opf-data/](https://mickey996icu.github.io/opf-data/)
>
> 📦 **商品数据仓**：[mickey996icu/opf-data](https://github.com/mickey996icu/opf-data) · 🖼️ **标签图片仓**：[mickey996icu/opf-media](https://github.com/mickey996icu/opf-media) · 🧰 **工具与 Skill 仓**：[mickey996icu/open-packaged-food](https://github.com/mickey996icu/open-packaged-food)

平时逛超市，拿起一袋零食翻到背面，配料表和营养表密密麻麻印着一大片。若是做过健康管理软件，或拍张照让 AI 帮着看配料，多半遇到过几件令人无奈的事。

包装上印着“0 反式脂肪”，AI 看一眼便说可以放心吃。可稍微懂点食品法规的人都知道，美国允许每份低于 0.5 克直接抹零，国标对极微量的钠也有类似宽限。AI 照着字面念，读长配料表时还常会漏掉几个添加剂，或者添上包装原本没有的词。更现实的是货架上的情形：同一款饮料，条形码分毫不差，背后却可能是两三家不同的代工厂，甚至老配方与减糖新配方正摆在同一排货架上卖。市面上的食品库为了省事，往往拿一版盖掉另一版，或者直接算个平均值。

真要用来记饮食账、防过敏、做临床营养，碰到这种“差不多就行”的数据，实在是靠不住的。

我写 **OpenPackagedFood (OPF)**，想法很简单，就是想把这笔糊涂账理清。我不做“红绿灯健康打分”——健康与否，留给吃东西的人和医生自己去判断。我只是想把食品包装上的白纸黑字如实记下来，整理成程序和 AI 助手能直接拿来算账的证据库。

---

## 只守四条规矩

- **写着“0”的，不冒充数学上的 0**
  按法规允许抹零的数值，系统会明确标成“低于某上限（`<`）”，不和“真没有”混为一谈。每百克、每百毫升的换算一律采用精确计算，避免精度偏差。
- **配料表逐字比对，容不得删改**
  拆解后的配料必须能按原本顺序还原成字符串，和包装上的文字逐字核对。多一个标点、少一个字，校验都会拦下，不给 AI 留“自由发挥”的余地。
- **同码不同厂，各自立档**
  同一条形码下只要出现不同代工厂或新旧配方，各自独立存为一版，彼此不覆盖。在售版本真有差异时，接口宁可停下来请人低头看一眼手里的包装，也不拿平均值凑数。
- **数据、图片、工具分仓存放，纯静态访问**
  产品数据、脱敏裁剪后的标签图与命令行工具各归其仓，编译后直接挂在 GitHub Pages 上。脚本或 AI 助手发一次普通的网页请求就能读取，不需要申请密钥，也不依赖额外的后台服务器。

---

## 马上用起来

### 1. 逛超市时直接网页扫码

打开 **[在线检索台](https://mickey996icu.github.io/opf-data/)**，手机后置摄像头对准条码就能扫，也可以从相册选图。解码全在你的浏览器本地完成（支持原生识别接口的设备优先使用原生，不支持的设备自动改用内置离线解码库），图片不上传，也不经过任何第三方查码服务。

平时买东西有所忌口的，可以用顶部的三栏筛选器：按国家市场筛选，把“明确含有”和“可能含微量”的致敏原分开排除，按添加剂编码过滤，或者自定一套“每百克蛋白质 ≥ X、钠 ≤ Y”的条件。

### 2. 给你的 AI 编程助手装上 Skill

把仓库里的 `skills/opf` 软链到常用工具的技能目录。以后拍张零食问它能不能吃，它会先查静态接口再作答；碰到库里还没有的新品，它只老实帮你分析照片里的内容，不会弹出窗口催你投稿。

```bash
git clone https://github.com/mickey996icu/open-packaged-food.git ~/src/open-packaged-food

# 按平时用的工具挑一行执行
mkdir -p .agents/skills && ln -s ~/src/open-packaged-food/skills/opf .agents/skills/opf
mkdir -p ~/.claude/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.claude/skills/opf
mkdir -p ~/.codex/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.codex/skills/opf
mkdir -p ~/.gemini/config/skills && ln -s ~/src/open-packaged-food/skills/opf ~/.gemini/config/skills/opf
```

### 3. 顺手拍张照，提个 PR 补全数据库

校验和构站代码全由 Python 标准库写成，不依赖第三方包（仅在本地压缩 WebP 图片时按需加载 `Pillow`）。

```bash
# 1. 本地脱敏切图，生成标准产品与版本记录
./open-packaged-food/bin/opf submit \
  --input draft.json \
  --out-dir opf-data/products \
  --photo nutrition_table=crop_nutrition.jpg \
  --photo ingredients_box=crop_ingredients.jpg \
  --vintage-month 2026-08 \
  --media-out-dir opf-media

# 2. 跑一遍本地校验，确保数据、图片与跨仓引用无误
./open-packaged-food/bin/opf validate opf-data/products
./open-packaged-food/bin/opf validate-media opf-media
./open-packaged-food/bin/opf check-media-refs --media-dir opf-media opf-data/products
```

接着把 `opf-media` 和 `opf-data` 分别推分支提 PR 就行（若装了 `uvx` 和 `gh`，也可运行 `uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.2.3 opf pr ...` 一步完成）。请注意顺序：**先合入图片仓（`opf-media`），再合入数据仓（`opf-data`）**，CI 会拦截图片还没进主分支的数据提交。

投稿前有两条规矩别踩：
- **只传局部文字裁剪图**（营养表、配料框、厂家与条码区），不要上传完整包装正面宣传图，免得惹上版权纠纷；
- **时间只记到月份（`YYYY-MM`）**，不要填精确到日的生产日期、保质期、购买小票或生产批号，校验器见到就会拦下，以防泄露个人行踪。

---

## 三个仓库怎么配合

```text
  查库：用户 / AI 助手 ──(HTTP GET)──▶ GitHub Pages 静态接口与检索页 (/v1/, /)
                                                    ▲
                                                    │ 自动构建上线
  投稿：opf submit ──▶ opf-media (局部脱敏图) ──(① 先合入)──▶ opf-data (产品 JSON)
```

<details>
<summary>点开查看完整目录结构与本地预览命令</summary>

```text
open-packaged-food/
├── bin/opf                    # 命令行入口
├── opf/                       # 校验、配料表比对、数值换算、图片脱敏与构站工具
├── web/                       # 多语网页端、离线扫码与条件筛选界面
├── spec/                      # 数据格式规范与 JSON Schema
├── docs/DESIGN.md             # 界面与数据展示约定
├── profiles/ & dictionaries/  # CN/US/EU/JP 法规标准、营养素、添加剂与致敏原词典
├── skills/opf/                # 开箱即用的 AI Agent Skill 与最小投稿模板
└── tests/                     # 单元测试与集成测试
```

```bash
cd open-packaged-food
python3 -m unittest discover -s tests -v
./bin/opf serve --data-dir ../opf-data/products
```

</details>

---

## 开源协议

- **工具链与网页端（`opf/`、`bin/`、`web/`、`.github/`）**：[AGPL-3.0-or-later](LICENSE)
- **数据库与商品 JSON（`opf-data`）**：[ODbL-1.0](LICENSE-DATA) / `DbCL-1.0`
- **裁剪标签证据图片（`opf-media`）**：[CC-BY-SA-4.0](LICENSE-MEDIA)
