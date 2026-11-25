# 贡献指南 (Contributing to OpenPackagedFood)

**[English](CONTRIBUTING.md) | [简体中文](CONTRIBUTING.zh-CN.md)** · **[在线检索与 API](https://mickey996icu.github.io/opf-data/)** · **[`opf-data` 仓库](https://github.com/mickey996icu/opf-data)** · **[`opf-media` 仓库](https://github.com/mickey996icu/opf-media)**

感谢你参与共建 **OpenPackagedFood (`opf` v0.3)**！我们的目标是打造一个**以证据为准、零主观判断、对 AI Agent 极度友好**的全球工业预包装食品开放数据库。

> **阶段定位与角色边界**：
> - **普通消费者**：请使用[在线检索网页](https://mickey996icu.github.io/opf-data/)进行只读检索与纯静态本地扫码查询，或在 AI Agent 中安装 [`skills/opf`](skills/opf) 辅助识别标签成分。面向普通消费者的无门槛投稿将在**第二阶段**配置 `OPF_SUBMIT_URL` HTTP 中转接口后经由 Agent 开放。
> - **开发者与维护者（第一阶段当前开放）**：新商品数据与标签图片一律通过**纯 Git 双仓 PR 主路径**提交（或向 `open-packaged-food` 提交法规词典/工具链 PR）。三仓 GitHub Issue 仅受理工具 Bug、数据勘误/停产、及官方数据库导入提案，不提供网页拖图提交表单。

---

## 路径一：开发者纯 Git 双仓 PR 协作流程（主路径）

### 1. 拍摄并裁剪局部功能性文字标签（不传整盒正面宣传图）
仅裁剪**局部清晰文字区域**：
- **营养成分表**（`nutrition_table`）：完整营养素数值、计量基准与 NRV%；
- **配料表**（`ingredients_box`）：完整配料及百分比添加量；
- **致敏原 / 厂家与标准区**（`allergen_statement`、`manufacturer_block`）：执行标准（如 `GB/T ...`）、受托代工厂、生产许可证（`SC...`）及粗粒度年月 `YYYY-MM`（或到期年月减保质期推算）；
- **条码与净含量**（`barcode_net_content`）：GTIN 与净含量。
> 切勿上传整盒正面商业美工封面图，以降低版权风险并提高 OCR 精度。

### 2. 克隆三仓、生成脱敏记录、本地校验与推送双 PR
参考 [`skills/opf/examples/draft.minimal.json`](skills/opf/examples/draft.minimal.json) 编写（或使用配置了 [`skills/opf`](skills/opf) 的 AI Agent 生成）`draft.json`：

1. **克隆三个仓库**（外部贡献者请先在 GitHub fork `opf-media` 与 `opf-data` 再克隆）：
   ```bash
   git clone https://github.com/mickey996icu/open-packaged-food.git
   git clone https://github.com/mickey996icu/opf-data.git
   git clone https://github.com/mickey996icu/opf-media.git
   ```
2. **本地脱敏转码并写入商品/版本文件**（自动压成 `≤ 1000px` 无 EXIF/XMP/IPTC 内容寻址 WebP 与结构化 JSON）：
   ```bash
   ./open-packaged-food/bin/opf submit \
     --input draft.json \
     --out-dir opf-data/products \
     --photo nutrition_table=crop_nutrition.jpg \
     --photo ingredients_box=crop_ingredients.jpg \
     --vintage-month 2026-08 \
     --media-out-dir opf-media
   ```
   - 若遇属性冲突或改版，追加 `--amend <ulid>`、`--supersede <ulid>` 或 `--new-variant --track CN/plant:SC...`。
3. **运行纯标准库本地校验与深度审计（数据、媒体、跨仓引用）**：
   ```bash
   ./open-packaged-food/bin/opf validate opf-data/products
   ./open-packaged-food/bin/opf validate-media opf-media
   ./open-packaged-food/bin/opf check-media-refs --media-dir opf-media opf-data/products
   ./open-packaged-food/bin/opf audit --media-dir opf-media opf-data/products
   ```
4. **DCO 签名提交（`git commit -s`）并推送双仓分支，随后点击终端提示的 GitHub 链接创建双 PR**：
   ```bash
   git -C opf-media switch -c contrib/media-label && git -C opf-media add -A && git -C opf-media commit -s -m "media(label): add cropped label evidence" && git -C opf-media push -u origin HEAD
   git -C opf-data switch -c contrib/product-record && git -C opf-data add -A && git -C opf-data commit -s -m "feat(product): add packaged food record" && git -C opf-data push -u origin HEAD
   ```
5. **双 PR 合入顺序（红线）**：请严格先合入 **`opf-media` PR**，待图片进入 `main` 后再合入 **`opf-data` PR**（`opf-data` CI 会自动运行 `opf check-media-refs` 验证外链有效）。

### 可选一键自动化通道（`uvx` + `gh` / 第二阶段 HTTP Relay）
- **可选开发者快捷通道（`uvx` + `gh`）**：若本地已安装 `uvx` 且完成 `gh auth login`，也可选用 `opf pr` 一键完成 WebP 脱敏、稀疏 fork 检出并开出双仓互链 PR：
  ```bash
  uvx --from git+https://github.com/mickey996icu/open-packaged-food@v0.3.1 \
    opf pr --input draft.json \
    --photo nutrition_table=crop_nutrition.jpg \
    --photo ingredients_box=crop_ingredients.jpg \
    --vintage-month 2026-08
  ```
- **第二阶段 HTTP Relay（`OPF_SUBMIT_URL`）**：配置该环境变量后，普通用户可通过 AI Agent 直接走纯 HTTP `POST <OPF_SUBMIT_URL>/v1/submissions` 免 Git 提交。

---

## 路径二：贡献全球法规插件与词典（无需修改核心代码）

发现某个食品添加剂没能自动关联上国际 INS / E-number 编码？或者想补充新的国家/地区法规？只需修改对应的 JSON 字典并向 [`mickey996icu/open-packaged-food`](https://github.com/mickey996icu/open-packaged-food) 提交 PR：

- **补充食品添加剂映射**：编辑 [`dictionaries/additives_ins.json`](dictionaries/additives_ins.json)
- **补充致敏原多语言关键词与防误报排除词**：编辑 [`dictionaries/allergens.json`](dictionaries/allergens.json)
- **新增或完善地区法规插件**：编辑 [`profiles/`](profiles/) 下对应法域的 `profile.json`

修改后运行测试套件确认无误即可（需 Python 3.12+）：
```bash
python3 -m unittest discover -s tests -v
```

---

## 🛡️ 隐私与数据红线（必读）

1. **允许粗粒度 `vintage_month`，严禁个人与精确到日的批次隐私字段**：
   - 严禁在 JSON 中包含购买日期 (`purchase_date`)、购买价格 (`purchase_price`)、精确到日某件实物的生产日期 (`production_date`)、到期日 (`expiry_date`)、到期估算日 (`expiry_estimate`) 或流水批次号 (`lot_number`)。CI 校验器 [`opf validate`](opf/validator.py) 会直接拦截包含上述字段的提交。
   - **允许收录**：`evidence[]` 中**年月粒度**的 `vintage_month`（`YYYY-MM`），用于确定性推导市场活跃/过期窗口而不泄露具体批次。
   - **应该收录的公共事实**：保质期时长（如 `12 month`）、贮存条件、包材版次号、包装明示的喷码解析规则（以及分轨时的 `TrackDefinition` 区分指引）。
2. **局部标签 WebP 脱敏与证据真实性**：
   - 仅保留包装上的功能性文字标签区域（营养表、配料表、厂家与标准信息），使用 `--photo` 或 `opf sanitize-media` 在本地完成方向烘焙、`≤ 1000px` 压缩并剥离全部 `EXIF/XMP/IPTC`；**严禁伪造图片哈希或脱离 `opf-media` 虚构 `media_ref`**。
3. **严禁猜测与机器翻译**：
   - 包装未标示的营养素留空，绝不用 `0` 或同类平均值填补；
   - `attributes` 层只抄录包装上实际印刷的语言文字；仅接受人工校对翻译（标记 `contributor_translated`），不接受未经校对的机器翻译。
4. **开发者原创声明 (DCO) 与 REUSE 许可分层（`Apache-2.0` 宽松入站）**：
   - 本仓库各路径的 SPDX 许可已在 [`REUSE.toml`](REUSE.toml) 与 [`LICENSES/`](LICENSES/) 中声明。`opf/`、`bin/`、`web/` 等工具链对外遵循 **[AGPL-3.0-or-later](LICENSE)**，**您以 `Signed-off-by`（`git commit -s`）向 `open-packaged-food` 提交的代码、Schema、词典、法规规则插件与文档，除依所在路径的出站许可提供外，同时依 [`Apache-2.0`](LICENSES/Apache-2.0.txt) 授权给任何接收者**，无需签署 CLA；`spec/`、`dictionaries/`、`profiles/`、`skills/`、`docs/` 及 `web/vendor/`（ZXing）本身亦以 **`Apache-2.0`** 对外分发。
   - 向 `opf-data` 提交数据遵循 **[ODbL-1.0](LICENSE-DATA)**，向 `opf-media` 提交裁剪标签图遵循 **[CC BY-SA 4.0](LICENSE-MEDIA)**。接入与可持续治理边界见 [`GOVERNANCE.zh-CN.md`](GOVERNANCE.zh-CN.md) 与 [`docs/ODbL-GUIDE.zh-CN.md`](docs/ODbL-GUIDE.zh-CN.md)。
5. **双层 `provenance` 与 CI 防洗白门禁**：
   - 外部 PR 提交的产品证据（`evidence[]`）与修订（`revisions[]`）统一标记 `provenance: "external_contributor"`（CLI 默认值）；免登录提交中转（Phase 2 Relay）标记为 `"public_submission"`。
   - CI 门禁 `opf check-pr-meta` 会拒绝外部 PR 写入 `maintainer`、`brand_owner`、`partner` 或 `transcription: "independent_match"`，并禁止篡改既有条目的 `provenance`（除非授权维护者附带 `Provenance-Correction: <reason>` 提交说明）。
