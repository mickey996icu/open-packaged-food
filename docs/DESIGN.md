# OpenPackagedFood 界面与数据展示设计规范

> 状态：**v0.2 · MD3 Expressive (MD3E · 复杂筛选控制台版)** | 适用范围：M0 网页（CLI、文档与 RTL 语言支持纳入 M1） | 基础：Material 3 Expressive 令牌与零主观评判多维检索架构

## 1. 定位

OpenPackagedFood 是一个**收录客观包装事实的开放数据库**，不是饮食打分或推荐引擎。视觉风格保持克制、清晰、可查证，不附加情绪化暗示。

| 界面展示概念 | opf v0.2 数据字段 | 说明 |
|---|---|---|
| 商品 ID (Product ID) | `id` (`gtin:…` / `opf:…`) | 标准 14 位 GS1 条形码或三段式商品标识（支持一键复制） |
| 核心事实层 (Core) | `core` | 法规标准、净含量、结构化营养标示与无 `span` 语义配料树（锁定 `core_fingerprint`） |
| 可补充属性层 (Attributes) | `attributes` | 原文文本、产地、生产/委托方（SC 证号）、执行标准、包材号与修订记录 |
| 百克标准值 (Normalized) | `normalized` | 每 100g / 100ml 确定性换算值与单件折算值 |
| 版本与轨道 (Edition & Track) | `edition_id` (ULID) + `rev` 胶囊 + `track` | 物理包装规格永久标识、不折行修订版本胶囊与市场/供应链轨道 |
| 解析模式 (Resolution) | `resolution` (`single \| uniform \| divergent \| inactive`) | Compact API 顶层多变体消歧与停产态判别 |
| 复杂筛选控制台索引 | `catalog.jsonl` (`markets`, `profiles`, `namespace`, `brand_slug`, `allergens_contains`, `allergens_may_contain`, `additives_ins`, `additives_count`, `ingredients_tokens`, `nutrients_100`) | 零额外 HTTP 请求支撑分面多选、配料/INS 包含与排除、严格 `<`/上界与 `partial` 感知的动态营养素数值条件 |
| 证据与溯源 (Evidence) | `evidence[]`、`revisions[]` | 裁剪标签照片哈希（`cropped_sha256`）、官方公开登记与 RFC 6902 正反向修订链 |
| 证据形态 (Evidence Level) | `evidence_level` | 构建期派生（仅反映提交形式，不表示核对与安全担保）：仅有文字报告，无照片 / 来自官方公开信息 / 有 1 份标签照片 / 有 2 个以上账号上传过标签照片 |
| 质量标记 (Quality Flags) | `quality_flags` | 法规标零修约上界、碳水口径差异、NRV% 偏差提示 |

## 2. 原则

1. **事实先于装饰**：无插画、无评分条、无渐变。
2. **不做判断，也不暗示判断**：颜色不承载食品好坏含义（不用绿表示健康、红表示不健康）。
3. **不确定性必须看得见**：数值的三种状态有固定且不依赖颜色的表达，黑白打印或色觉障碍下依然清晰可辨；营养素筛选严格遵守修约上界与 `partial` 语义。
4. **证据随处可达**：任意换算数值（含顶部 KPI 磁贴与完整表格）都能点击查看推导公式，并追溯到证据形态、法规标准与包装版本。
5. **全球通用**：不依赖具有单一文化偏向的褒贬色；M0 支持中英双语切换及 CJK / 拉丁排版，M1 纳入阿拉伯语 / 希伯来语等 RTL 逻辑属性支持。
6. **数据安全转义**：社区提交的字符串在前端渲染前一律执行 HTML 转义。

## 3. 色彩（Material 3 Expressive 5 级 Surface 阶梯 · 锁定调色板）

色彩只表达**色阶容器嵌套（Tonal Surface Containment）与交互选中状态**，**严格锁定浅色暖石纸白 + 深岩蓝黑夜色 + 深海蓝 Primary + 石板靛蓝 Secondary 配色体系**，绝不使用红 / 绿 / 黄褒贬色（仅 `error` 保留给接口或校验错误）。

| 角色 | 浅色模式 | 深色模式 | 用途 |
|---|---|---|---|
| `surface-dim` | `#DFD9CC` | `#0F1116` | 最暗基底参照阶 |
| `surface` | `#F8f5ee` | `#13161D` | 页面画布背景 |
| `surface-container-lowest` | `#FFFFFF` | `#0D0F14` | 详情分区白卡、控制台内嵌卡片、列表项与激活分段胶囊 |
| `surface-container-low` | `#F2EEE4` | `#1A1E27` | 紧凑 Bento 统计条、筛选控制台底座、左侧目录与详情主面板底色 |
| `surface-container` | `#ECE6D9` | `#202530` | 分段胶囊槽、公式展开块、数值条件行与警告条 |
| `surface-container-high` | `#E4DDCE` | `#2A303D` | 卡片悬停反馈底色 |
| `surface-container-highest` | `#DCD4C3` | `#353B4A` | 次级高亮/清空按钮悬停反馈 |
| `on-surface` | `#1B1F2A` | `#E4E6EE` | 主文本、2px 标题分隔粗线 |
| `on-surface-variant` | `#4A4F5C` | `#B5BAC8` | 次要标签与字段注释 |
| `outline` | `#7A7F8C` | `#8B90A0` | 证据形态徽章及上界底纹边界 |
| `outline-variant` | `#CFCABD` | `#3A3F4C` | 低对比度内部分割辅助 |
| `primary` | `#2B4C7E` | `#A9C4F5` | 主强调色、证据形态徽章、选中指示 |
| `on-primary` | `#FFFFFF` | `#0B2347` | 主强调反白文字 |
| `primary-container` | `#D6E3FF` | `#1F3A66` | 选中商品列表项与筛选激活胶囊底色 |
| `on-primary-container` | `#001B3E` | `#D6E3FF` | 选中容器文字 |
| `secondary` | `#4C5D78` | `#B4C6E4` | 石板靛蓝辅助强调 |
| `secondary-container` | `#D8E3F8` | `#33445E` | 致敏原/配料排除激活胶囊、`rev N` 胶囊与重置按钮 |
| `on-secondary-container` | `#0D1C32` | `#D8E3F8` | 次级容器文字 |
| `error` | `#B3261E` | `#F2B8B5` | 仅用于接口或校验报错 |

## 4. 字体

- **标题（Serif）**：`"Source Serif 4", "Noto Serif SC", "Songti SC", "STSong", Georgia, serif`，用于页面标题与商品名称。
- **正文 / 界面（Sans）**：`system-ui, -apple-system, "Segoe UI", "PingFang SC", "Noto Sans SC", "Microsoft YaHei", sans-serif`。
- **标识符与数值（Mono）**：`ui-monospace, "JetBrains Mono", "SF Mono", Menlo, Consolas, monospace`，全局开启 `font-variant-numeric: tabular-nums` (`tnum`)。
- **零外部字体请求**：完全离线可用。

## 5. MD3E 形状梯度、形变与弹簧动效

- **Shape Scale**：小标签 `--r-xs: 8px` · 下拉/输入框 `--r-sm: 12px` · 控制台分栏/变体卡片 `--r-md: 16px` · 分区卡片/控制台底座 `--r-lg: 24px` · 目录抽屉与详情主面板 `--r-xl: 28px` · 全胶囊 `--r-full: 999px`。
- **Shape Morphing**：筛选胶囊选中时以弹簧曲线（`--ease-spring`）由 `10px` 形变为 `999px` 并展示内联 SVG `✓`；列表项选中时由 `14px` 形变为 `20px` 并附带 `4px` 左侧强调线；`.card-tabs` 为 MD3E 分段胶囊切换器；`prefers-reduced-motion: reduce` 下自动禁用过渡。

## 6. 宏观首屏结构：紧凑顶栏 + 上方全宽「复杂筛选控制台」+ 下方纯粹双栏工作区

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ [OPF · DATABASE] OpenPackagedFood · 包装印什么，数据库就记什么  [工具按钮]│
├────────────────────────┬────────────────────────┬───────────────────────┤
│ 收录商品            10 │ 覆盖法域      US4 EU3 │ 数据规范         v0.2 │ ← ~52px 内联统计条
├═════════════════════════════════════════════════════════════════════════┤
│ [🔍 搜索条码/品名/配料/INS / ×] [全部法域][CN][US][EU][JP] [高级筛选][排序][显示X/Y] │ ← 第1层主控条
│ ├─ 列1: 状态/证据/法规/品牌多选 ─┬─ 列2: 排除致敏原 & 配料/INS 含/排 ─┬─ 列3: 营养阈值构建 ─┤ ← 第2层三栏展开面板
│ └─ 生效条件: [法域: CN ×] [排除致敏原: 乳 ×] [蛋白质 ≥ 10g ×]   [清除全部条件] │ ← 第3层生效条件条
├───────────────────────────┬─────────────────────────────────────────────┤
│ 商品目录 (380px 粘性独立滚动)│ 右栏：商品 ID [复制ID] [解析态] [证据徽章]   │
│ ┌─ 示例茶坊 · CN ─ [1份照]┐ │ 5格 核心营养速览磁贴 (kcal / 蛋白 / 脂 / 碳 / 钠)│
│ │ 无糖茉莉清茶             │ │ ── Section Card: 完整百克/单件 table-wrap ─ │
│ │ gtin:00000000000017      │ │ ── Section Card: 配料表 + 致敏原 + INS ──── │
│ └────────────────────────┘ │ ── Section Card: 法规 / 证据 / 质量标记 ─── │
│ (首屏稳定可见 5–6 款商品)   │                                             │
└───────────────────────────┴─────────────────────────────────────────────┘
```

### 营养数值条件构建器（`nutrients_100`）严格筛选语义
- **`nutrient <= X`**：要求非 `partial` 且 `item.max <= X`（若标示为 `< 5` 而条件为 `≤ 10`，因 `< 5 ≤ 10` 恒成立则命中；若条件为 `≤ 2`，因真实值可能为 `4`，保守不命中）。
- **`nutrient >= X`**：要求非 `partial`、非 `<`/`<=` 法规修约上界（上界无法保证真实下界），且 `item.min >= X`。
- **`A <= nutrient <= B`**：当 `A > 0` 时要求非上界且 `item.min >= A` 与 `item.max <= B`；当 `A == 0` 时允许 `<` 上界且 `item.max <= B`。
- **同维度多选 OR、跨维度 AND**：如同时选法域 `CN` 与 `JP`，再叠加上界安全数值规则 `钠 ≤ 120 mg` 与 `排除致敏原: 乳及乳制品`，实时组合定位。
