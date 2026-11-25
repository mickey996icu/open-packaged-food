# OpenPackagedFood 项目治理与可持续原则

**[English](GOVERNANCE.md) | [简体中文](GOVERNANCE.zh-CN.md)** · **[贡献指南](CONTRIBUTING.zh-CN.md)** · **[ODbL 使用者指南](docs/ODbL-GUIDE.zh-CN.md)** · **[技术规范](spec/SPEC.md)**

OpenPackagedFood (`opf`) 的治理目标明确分为两件事：长期维持公共预包装食品事实库的开放、中立与高准确度，同时为未来团队化的持续数据核验留出合法、清晰的成本覆盖路径。

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

## 2. 双层 `provenance`、`agreement_ref` 与盲录独立核实规则

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
   - **团队自有子集判定规则**：仅当一条记录当前有效 `core` 的每一个值均来自 `maintainer` 的修订，或被一条带 `"transcription": "independent_match"` 的 `maintainer` 证据所覆盖，且其后没有任何未经团队核实的外部补充时，该版本才纳入团队自有子集。
4. **科研与品牌方合作通道（`partner` / `brand_owner`）**：
   - 高校科研团队、第三方检测机构或品牌方依据书面协议参与核验，必须携带 `agreement_ref` 以便后续追溯商业再授权权限边界。

---

## 3. 商业化与责任隔离边界

1. **未商业化阶段**：项目未产生任何付费收入前，保持纯开源公益仓库模式运作，不设立人为关闭入口。
2. **第一笔收入前必设有限责任主体**：在任何商业模式上线并产生第一笔实际收入前（包括托管高可用 API SLA、商业 OCR 识别接口及授权回流、自有来源子集商业授权，或面向消费者的付费功能），**必须提前设立独立的有限责任主体**承接运营合同、财务收支与服务责任，将商业风险与开源维护者个人相隔离。
3. **消费端与致敏原安全展示要求**：依据适用消费者保护与民法规则（例如造成人身损害的免责条款不生免责效力），任何基于 OPF 数据构建的下游消费应用或付费服务，均不得隐瞒 `evidence_level`、`quality_flags`（法规 `<` 修约上界、`divergent` 多版本消歧提示），应明确提示“以手头实物包装印刷为准”，并在高风险服务上线前配置相应的商业责任保险。
