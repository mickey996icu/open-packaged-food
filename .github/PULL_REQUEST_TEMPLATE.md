## 变更类型 / Change Type

- [ ] 🍱 新增商品 / New product (`new-product`)
- [ ] 🔄 现有商品新包装/新配方版本 / New edition (`new-edition`)
- [ ] ✏️ 现有版本字段补全或勘误 / Attribute enrichment or errata (`enrichment / errata`)
- [ ] 📚 法规插件 / 添加剂词典 / 工具链更新 / Spec, profile, or tooling update (`spec / tooling`)

## 自检清单 / Pre-Merge Checklist

- [ ] **本地校验 / Validation**：已运行 `opf validate` 且全部通过（GS1 校验位、配料树无损还原 round-trip 校验、确定性百克换算与 `@rev` 双向补丁一致）。 / Passed `opf validate` (GS1 check digit, lossless ingredient round-trip, deterministic normalization, bidirectional patch replay).
- [ ] **双仓媒体门禁与顺序 / Media Gate & Merge Order**：已确认 `opf check-media-refs` 无孤立 `opf-media://` 引用；若同时伴随媒体 PR，**先合入 `opf-media` PR，再合入 `opf-data` PR**。 / Confirmed `opf check-media-refs` passes; if a companion `opf-media` PR exists, **merge `opf-media` FIRST**, then **`opf-data` SECOND**.
- [ ] **功能裁剪与隐私门禁 / Functional-Crop & Privacy Gate**：仅上传功能性标签文字裁剪图（7 类标准 `region`，严禁整盒正面封面大图），且 JSON 与图片均**不包含**购买日期、价格、精确到日的生产/到期批号、人脸、手部或订单小票。 / Cropped functional label regions only (no full front-of-pack cover art; zero purchase dates, prices, day-precision lot/expiry dates, faces, fingers, or receipts).
- [ ] **原创与许可声明 / DCO & Open Licenses (REUSE)**：本人以 DCO（`git commit -s`）向 `open-packaged-food` 提交的代码、Schema、词典、法规插件、Skill 与文档，除依所在路径的出站许可提供外，同时依 **`Apache-2.0`** 授权给任何接收者，对外工具链遵循 `AGPL-3.0-or-later`、`spec/`/`dictionaries/`/`profiles/`/`skills/`/`docs/` 与 `web/vendor/` 遵循 `Apache-2.0`（见 [`REUSE.toml`](REUSE.toml)）；向 `opf-data` 提交数据遵循 `ODbL-1.0`，向 `opf-media` 提交图片遵循 `CC BY-SA 4.0`。 / Confirm DCO: I provide my contributions to `open-packaged-food` under their path's outbound license and additionally license them to every recipient under `Apache-2.0` (outbound tooling `AGPL-3.0-or-later`, specs/dictionaries/profiles/skills/docs/vendor `Apache-2.0` per `REUSE.toml`); `opf-data` under `ODbL-1.0`; `opf-media` under `CC BY-SA 4.0`.
- [ ] **双层来源标注与防洗白 / Provenance Compliance**：涉及产品 JSON 时，外部 PR 新增条目仅标记 `provenance: "external_contributor"`，且未擅自改动既有条目的 `provenance`。 / If touching product JSON, new entries use `provenance: "external_contributor"` and existing `provenance` tags remain unaltered.
