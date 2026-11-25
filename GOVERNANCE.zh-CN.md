# OpenPackagedFood 项目治理与可持续原则

**[English](GOVERNANCE.md) | [简体中文](GOVERNANCE.zh-CN.md)** · **[贡献指南](CONTRIBUTING.zh-CN.md)** · **[ODbL 使用者指南](docs/ODbL-GUIDE.zh-CN.md)** · **[数据局限性说明](docs/DATA-LIMITATIONS.zh-CN.md)** · **[技术规范](spec/SPEC.md)**

OpenPackagedFood (`opf`) 的治理目标明确分为两件事：长期维持公共预包装食品包装转录台账的开放、中立与可追溯性，同时为未来团队化持续维护、勘误与图证整理留出合法、清晰的成本覆盖路径。

---

## 1. 仓库与开源许可分层（REUSE 规范）

| 分层 | 覆盖范围 | 对外发布协议 | 贡献入站规则 |
| :--- | :--- | :--- | :--- |
| **工具链与网页端** | `opf/`、`bin/`、`web/`（不含 `web/vendor/`）、`.github/`、`tests/` | `AGPL-3.0-or-later` | **`Apache-2.0`** + DCO (`Signed-off-by`) |
| **离线扫码依赖库** | `web/vendor/`（ZXing） | `Apache-2.0` | 上游 `Apache-2.0` |
| **规范、词典与规则插件** | `spec/`、`dictionaries/`、`profiles/`、`skills/`、`docs/` | `Apache-2.0` | **`Apache-2.0`** + DCO (`Signed-off-by`) |
| **产品结构化数据库** | `opf-data`（`products/`、`overlays/`） | `ODbL-1.0` / `DbCL-1.0` | `ODbL-1.0` / `DbCL-1.0` + DCO |
| **标签裁剪证据图片** | `opf-media`（`media/`） | `CC-BY-SA-4.0` | `CC-BY-SA-4.0` + DCO |

- **机器可读 REUSE 声明**：仓内每条路径的精确 SPDX 许可已在 [`REUSE.toml`](REUSE.toml) 与 [`LICENSES/`](LICENSES/) 中写明，供 ScanCode / FOSSA / REUSE 等合规工具直接识别。
- **公共数据中立原则**：进入 `opf-data` 的产品 JSON 与 `opf-media` 的裁剪标签图，永久按 `ODbL-1.0` 与 `CC-BY-SA-4.0` 公开维护；维护团队不对第三方社区或公众提交的数据做排他性闭源授权或私下豁免。
- **代码与标准宽松入站**：向 `open-packaged-food` 提交的代码、Schema、词典与地区法规插件，均按 `Apache-2.0` 宽松入站并附带 DCO 原创声明（`git commit -s`），无需额外签署 CLA，也不要求个人维护者在无商业实体阶段公开真实姓名。

---

## 2. 双层 `provenance`、`agreement_ref` 与盲录独立比对规则

每条证据（`evidence[]`）与每次内容修订（`revisions[]`）均必须标注 `provenance` 字段，定稿枚举为：
`maintainer | external_contributor | public_submission | brand_owner | partner`：

1. **CI 门禁权限与防“洗白”不可变规则（`opf check-pr-meta`）**：
   - 外部 PR 新增条目**只能**标注 `external_contributor`。
   - 第二阶段提交中转机器人（Relay Bot）新增条目**只能**标注 `public_submission`。
   - `maintainer`、`brand_owner`、`partner` 三值仅允许维护者账号写入；其中 `brand_owner` 和 `partner` **必须**填写内部协议编号 `agreement_ref`（不公开合同正文）。
   - **既有条目的 `provenance` 不可篡改**：任何人（包括维护者本人）均不得修改已合入条目的 `provenance`；确需勘误更正时，仅维护者账号且在 commit 中附带写明理由的 `Provenance-Correction: <reason>` trailer 方可放行。
2. **`maintainer` 权属边界（《著作权法》第 18 条）**：
   - `maintainer` 仅指维护者本人独立采集/录入的内容；未来设立运营主体后，团队成员仅在**书面约定作品著作权归运营主体**的前提下才可标 `maintainer`（《著作权法》第 18 条规定一般职务作品著作权默认归创作者本人）。由维护者直接导入的政府公开台账，亦标 `maintainer`（信息来源已由 `type: official_registry_import / official_document` 表达）。
3. **基于实物的独立转录（盲录，`transcription: "independent_match"`）**：
   - 团队为已有外部版本补充实拍图走佐证追加流程时，仅新增的 `evidence[]` 为 `maintainer`，原 `revisions[].provenance` 仍保持 `external_contributor`。
   - 只有当团队采用**盲录模式**（工具仅根据新拍实物图独立生成 draft，不读取已有 `core`）完成转录且结果与现行 `core` 完全一致时，由工具自动在对应 `evidence[]` 写入 `"transcription": "independent_match"`（严禁手动填写）；若盲录结果不一致，则走 `errata` 修订并将新修订 `provenance` 标为 `maintainer`。
   - **团队自有子集判定规则**：仅当一条记录当前有效 `core` 的每一个值均来自 `maintainer` 的修订，或被一条带 `"transcription": "independent_match"` 的 `maintainer` 证据所覆盖，且其后没有任何未经团队独立盲录比对的外部补充时，该版本才纳入团队自有子集。
4. **科研与品牌方合作通道（`partner` / `brand_owner`）**：
   - 高校科研团队、第三方机构或品牌方依据书面协议参与数据采集与比对，必须携带 `agreement_ref` 以便后续追溯商业再授权权限边界。

---

## 3. 商业化、责任隔离与注意义务防线

1. **未商业化阶段**：项目未产生任何付费收入前，保持纯开源公益仓库模式运作，不设立人为关闭入口。
2. **第一笔收入前必设有限责任主体**：在任何商业模式上线并产生第一笔实际收入前（包括托管高可用 API SLA、商业 OCR 识别接口及授权回流、自有来源子集商业授权，或面向消费者的付费功能），**必须提前设立独立的有限责任主体**承接运营合同、财务收支与服务责任，将商业风险与开源维护者个人相隔离。如未来运营主体直接运营面向终端用户的商业/消费服务，须在上线前配置相应商业责任保险。
3. **维护方自身的注意义务防线与第三方独立责任**：
   - **如实描述证据形态，不做准确性或安全背书**：维护方在规范与官方 Web 浏览器中仅陈述客观证据形态（如照片份数、提交来源），不将 `verified`/`corroborated` 表述为“已核验”“已验证”或产品安全性保证（详见 [`docs/DATA-LIMITATIONS.zh-CN.md`](docs/DATA-LIMITATIONS.zh-CN.md)）。
   - **维护公开勘误与 `retracted` 撤回机制**：保持公开的 `opf-data` 勘误与生命周期变更通道，对确认误录或存在误导风险的版本及时采用 `lifecycle.state = "retracted"` 从活跃索引隔离；涉及致敏原错漏的勘误报告**优先处理**（不作固定硬性时限承诺）。
   - **第三方责任边界**：下游接入方**自行负责其产品或服务对终端用户的提示义务与合规义务**，OPF 不替第三方设定强制界面规范或产品安全标准。
