# 新公共知识图谱：阶段 1 交付与维护

日期：2026-10-12。状态：公共内容、页面和阶段 1 验收完成，等待内容审阅。

后续交付：阶段 2 已加入教学关联预览，当前共 67 个节点；最新数量、入口及隔离约定见[阶段 2 说明](public-knowledge-graph-stage2.md)。下面的验收数量保留阶段 1 口径。

预览入口：<http://127.0.0.1:8779/knowledge-next/>。节点目录：<http://127.0.0.1:8779/knowledge-next/nodes/>。

依据：[本体设计](public-knowledge-graph-ontology-design.md)、[替换计划](public-knowledge-graph-replacement-plan.md)。预览仍使用固定本地服务 8779；数据库未清理、未迁移，旧图谱及题页入口未切换。

## 1. 交付范围

| 类型 | 数量 |
| --- | ---: |
| 教材／章／节 | 1／1／3 |
| 知识点／技能／方法 | 13／20／13 |
| 题型／判断规则 | 9／2 |
| 合计 | **62** |

每个知识点、技能、方法、题型和判断规则都有独立详情页、正文、出处、关联入口；标题下方按「关系 + 对方类型」分区列出全部关联（如知识点的前置知识、后续知识、应用它的技能、考查它的题型），每个区用对方类型的颜色单独成行；知识点的每个条目卡片再列出用到这一条的技能。图解资源可在 `catalog.json` 里用 `after` 指定放在哪个条目之后；知识点、技能、方法可维护 `pitfalls`（错误做法、为什么错、正确做法、相关节点），渲染为「易错」区。新图谱暂不按同名旧节点开放刷题；新小题原稿在阶段 3 接入。教材、章、节的详情地址只做跳转，分别转到总览页、章图谱页和带 `scope` 的章图谱页。数学对象都有说明或题例；知识条目、操作、方法步骤、规则分支均有稳定锚点。现有题页作为例题链接并启用关联预览，补充练习直接保留题目与出处。

图谱提供章节、知识关系、解题关系三个视图。知识关系视图也显示“题型 → 涉及 → 知识点”。支持别名搜索、类型和关系筛选、缩放平移、键盘选择、跨节展开、手机端折叠面板以及 URL 恢复。跨节展开的对象标记为“相关内容”，不改变所属节。

方法详情按原稿生成有序路径、条件调用和分支。图谱概览合并重复调用边，详情页保留每次调用及其位置。当前内容用于教学展示，不作为自动题型识别或可执行 Plan。

## 2. 文件与维护入口

| 文件 | 职责 |
| --- | --- |
| `site/data/knowledge-next/nodes/<id>.json` | 每个节点的唯一正文及关联原稿 |
| `site/data/knowledge-next/catalog.json` | 数量校验、默认范围、明确的图解资源及旧链接映射 |
| `site/assets/knowledge-next/model.mjs` | 类型、关系校验、派生边、范围与导航状态 |
| `site/assets/knowledge-next/layout.mjs` | SVG 分层布局，支持混合关系图中的环 |
| `site/assets/knowledge-next/graph.mjs` | 图谱交互 |
| `site/assets/knowledge-next/search-focus.mjs` | 首页与章节图谱共用的搜索焦点管理 |
| `site/assets/knowledge-next/detail.mjs` | 详情页上下文及图解加载适配 |
| `site/assets/knowledge-next/resource-links.mjs` | 图解关联链接转换 |
| `site/assets/knowledge-next/knowledge.css` | 共享页面样式 |
| `tools/lib/public-knowledge-html.mjs` | 静态模板与本地 KaTeX 渲染 |
| `tools/build-public-knowledge-graph.mjs` | 校验及构建入口 |
| `site/knowledge-next/` | 生成产物，不手工修改 |

在仓库根目录运行：

```sh
node tools/build-public-knowledge-graph.mjs
node tools/build-public-knowledge-graph.mjs --check
node --test tools/tests/public-knowledge-graph.test.mjs
```

原稿更新后先构建，再执行检查。`--check` 只读，发现缺页、过期产物、多余页面、非法关系、无效资源或题例链接时失败。生成器只管理 `site/knowledge-next/`，不改写 `site/knowledge/`。当前生成 66 个详情页、全高中总览页（`/knowledge-next/`）、每个已录入或部分录入章的图谱页（`/knowledge-next/chapters/<章>/`）、列表页、3D 页、图数据、产物清单及版本化资源文件，共 85 个文件。旧的 `/knowledge-next/?scope=…&node=…` 链接由总览页按节点归属章重定向到对应章页面。

浏览器模块与样式整体复制到内容哈希目录，连同相对模块引用一起更新缓存地址。公式在构建时用仓库 KaTeX 生成，页面不依赖外部 CDN。

### 原稿约定

- `kind` 必须明确填写八类类型之一，不根据 ID 前缀推断。
- 节的 `members` 保存 `contains`／`extends`；章只包含节，教材只包含章。数组顺序决定目录顺序。
- 知识点的 `prerequisites` 写前置知识 ID；派生箭头从前置知识指向当前知识。
- 题型的 `knowledge` 保存涉及知识；`methods` 保存直接候选方法；`rules` 保存选法规则。
- 技能的 `basis` 引用知识点或 `知识点ID#条目ID`。暂不补初中知识节点的操作依据写在技能正文。
- 方法的 `steps` 是唯一有序路径。每步可有 `calls: [{ref, when?}]` 或 `rule`；调用技能、子方法及进入规则的边由此生成。
- 规则的 `branches` 保存条件和目标。子类为 `method_selection` 或 `step_selection`；规则不连接知识点。
- 反向关联、方法可能使用的知识清单和章的内容范围由程序汇总。
- 公式文本用 `$…$` 或 `$$…$$`。所有成立条件与可达性写清；基本不等式的公式条件和求最值条件分别陈述。

节点和内部条目 ID 发布后保持稳定。修改名称、别名或正文不改 ID。新增内容时同步更新 `expectedCounts`，通过节引用或规则引用纳入范围。

## 3. 旧身份与图解

新建且不属于旧图谱登记表的图解模块与样式放在 `site/assets/explain/resources/`，由新图谱的 `catalog.json` 引用。旧 `knowledge/`、`method/` 目录继续与旧节点登记表对应，保留原有完整性校验。

含义相同的 21 个旧节点沿用 ID，类型按新本体登记。例如 `method-complete-square` 为“配方”技能，`method-square-extremum` 为独立的“配方求最值法”；`quadratic-inequality-solve` 保留完整解法身份，新的知识点使用 `quadratic-inequality`。`quadratic-interval-extremum` 登记为求值技能。

以下为阶段 1 的内容对应示例；逐题、逐步骤的迁移以阶段 2 的 `migration.json` 及专题原稿为准，不迁移学习成绩：

| 原对象 | 新内容位置 |
| --- | --- |
| `homogeneous-expression` | `method-homogeneous#degree` |
| `symmetric-polynomial` | `method-sum-product#identities` |
| `extremum-transfer` | `function-range-extrema#quantified`；执行转换另用技能 `skill-quantified-range` |
| `endpoint-attainability` | `function-range-extrema#attainability` |
| `case-merge` | 按当前方法关联合并或条件步骤，不能统一替换成一个节点 |
| `method-reciprocal` | `skill-inequality-transform#reciprocal` |

图解资源身份与节点身份分开。旧图解按「拆开合并」迁入：旧模块新增 `figure()` 导出，只渲染新页没有的图（滑块演示、数轴、抛物线、方框圆圈模板）；资源登记 `"part": "figure"` 后只嵌入这一部分，并用 `after` 放在最相关的知识条目、技能操作或方法步骤之下。旧模块的核心句、「解题三步」与新页条目重复，不再嵌入；易错对比、补充规则和例子改写进节点 JSON 的 `pitfalls`、`entries`／`operations` 和 `examples`。旧页面仍调用 `render()`，输出保持不变。

目前 18 个节点挂载 `part: figure` 的资源（不等式性质、二次函数性质、函数单调性、基本不等式、二次不等式解法、二次函数区间最值，以及 2.2、2.3 的各项技能与方法），另有三个整块嵌入的资源：

| 资源 | 挂载节点 | 教学边界 |
| --- | --- | --- |
| `square-area` | 平方的非负性 | 面积演示用正边长；代数结论适用于实数；含倒数时补充非零条件 |
| `linear-range` | 一次函数及常函数 | 包含斜率为零、闭区间和开区间边界 |
| `reciprocal-range` | 对勾函数 `y=x+k/x` | 当前图解取 `k>0`、`x≠0` |

资源地址、样式作用域、适用条件和关联链接均显式配置，不经过旧图谱加载器。图解 HTML 和公式预先生成；交互模块失败时仍能阅读正文、公式及链接，并可原页重试。资源标题和各类条目标题会进入目录、锚点与无障碍标签，只写纯文本，数学用 Unicode（如 `Δ ≤ 0`），校验会拒绝含 `$` 的标题。

## 4. 验收结果

| 范围 | 结果 |
| --- | --- |
| 新图谱测试 | Node 测试 17 项通过；覆盖节点数量、关系端点、条目引用、必要前置无环、五条重点教学链路、重复调用、跨节范围、URL、安全返回地址、模板、资源映射与构建边界，以及切换视图清理不兼容筛选、手机与桌面完整适应画布 |
| 构建 | 可重复生成；`--check` 通过，测试能够检出缺失、过期和遗留页面及失效引用 |
| 旧产物 | `node tools/build-knowledge-pages.mjs --check` 通过，27 个旧详情页保持一致 |
| 旧定向回归 | `test_knowledge_graph.py`、`test_quadratic_graph.py` 共 19 项通过 |
| 桌面与手机 | 62 个详情页分别检查；390×844 手机视口下无整页横向溢出，公式无 KaTeX 错误，正文与入口可用 |
| 导航与交互 | 搜索、两类筛选、缩放平移、键盘选择、跨节展开、详情页跳转、前进后退及返回定位通过 |
| 图解 | 21 个资源成功挂载，可交互的图操作控件正常；面积图解和一次函数图解的数值随控件改变；关联指向新节点 |
| 故障恢复 | 实际模拟图谱 JSON 503、图解模块 503，目录与正文仍可用；解除故障后原页重试成功 |
| 接口隔离 | 新模块无学习记录、刷题或掌握状态接口调用；故障验收请求日志中也无这些请求或旧图谱加载器请求 |

旧定向回归命令（`server/` 下）：

```sh
uv run pytest -q tests/tutor_demo/test_knowledge_graph.py tests/tutor_demo/test_quadratic_graph.py
```

本阶段完成 1A、1B、1C。后续仍按替换计划进行题目关联迁移、数据库及发布适配、正式入口切换；个人图谱评估与可执行求解另行设计。
