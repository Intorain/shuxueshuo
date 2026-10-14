# 新公共知识图谱：阶段 3 数据库与发布适配

> 本文记录阶段 3 验收基线。当前正式路径、默认学习模式和个人图谱展示见[阶段 4 交付说明](public-knowledge-graph-stage4.md)；`/knowledge-next/` 已成为兼容跳转入口。

日期：2026-10-13。本地已切换到新公共内容及关联，数据库版本为 `0012_drill_updated_at`。本阶段接通节点状态、五题检测、整题证据及登录联调；正式图谱入口替换、全图个人状态、服务器上线、贝叶斯评估和整题掌握评估留到后续阶段。

## 1. 本地入口与模式

日常手动测试继续使用网站 `http://127.0.0.1:8779`、数据库 `127.0.0.1:5432/product` 和原固定数据目录。

| 入口 | 行为 |
| --- | --- |
| `/knowledge-next/` | 公共图谱及正文 |
| `/knowledge-next/topics/basic-inequality/?learning=1` | 基本不等式登录联调入口 |
| `/knowledge-next/topics/quadratic-always/?learning=1` | 一元二次不等式登录联调入口 |
| `/knowledge-next/method-complete-square/?learning=1` | 配方技能状态、五题检测及历史证据 |
| `/1/q01/?knowledge=next` | 不保存记录的关联预览 |
| `/1/q01/?knowledge=next&learning=1` | 新关联、记录器、学习标记和导师联调 |

专题、题页、图谱和详情导航保留联调模式。教材详情转到总览时保留教材进度范围；章、节显示各自范围的汇总。只有明确进入联调模式，才启用个人记录。未登录时提供登录入口。

普通题页不带参数时可点选作答、使用独立导师会话，不按旧关联保存学习记录。普通页不请求图谱版本，只显示一句不保存进度的说明，不提供无效的重试或刷新按钮；新版关联登录模式检查失败时仍可重试。联调入口仅在本机地址显示。`?knowledge=next` 预览不创建轮次、不提交提示或作答、不连接导师。

## 2. 原稿、导出与发布

唯一发布链路为：

```text
新节点、专题、私有小题原稿 + 题页与教师教学契约
                        ↓
共享 Node 校验与结构化导出
                        ↓
Python 发布器（发布锁 + PostgreSQL 事务）
                        ↓
当前公共内容、关联、资源、私有题池和发布版本
```

| 文件或目录 | 职责 |
| --- | --- |
| `site/data/knowledge-next/` | 公共节点、关系来源、专题关联和显式图解资源目录 |
| `server/shuxueshuo_server/learning/drills-next/` | 有效小题及停用记录，答案仅留在服务端 |
| `tools/lib/public-knowledge-sources.mjs` | 构建与导出共用的原稿加载 |
| `tools/export-public-knowledge.mjs` | 无写库、无生成页面副作用的导出入口 |
| `tools/lib/public-knowledge-export.mjs` | 数据行、内部条目、契约与关联哈希、资源版本及总内容版本 |
| `server/shuxueshuo_server/learning/content.py` | 导出调用、二次校验和事务发布 |
| `server/alembic/versions/0011_public_learning_content.*` | 增量迁移及数据库约束、权限 |
| `server/alembic/versions/0012_drill_updated_at.*` | 小题轮次活动时间；已有行按最近已记录活动回填 |

导出直接读取原稿，不读取详情页 HTML、旧图谱目录或已生成的预览页面。普通导出含私有答案和教学判定，只供管理发布器消费，不能写入 `site/`。`--check` 仅输出安全的版本及数量统计。

静态构建与数据库发布使用同一导出规则计算 `content_version`；静态清单在 `site/knowledge-next/teaching/version.json`。数量由有效原稿统计，不作为日常发布的固定断言。停用小题不进入有效题池；不足五题的节点仍可入库。

发布前校验八类节点、十类关系、规则子类、条目与资源引用、关系端点、知识前置无环及教学契约。表名、主键与字段通过白名单校验，再由 SQLAlchemy 生成写入语句。整个发布持有 `learning.publish` 排他锁，在一个事务中执行；失败整体回滚，重复发布不会产生重复行。开整题、小题检测和导师恢复仅持有同一把锁的共享模式，彼此可并行；发布、重建与重算使用排他模式。

教学契约和图谱关联分别计算哈希：

- `contract_hash` 保护已经发布的题目正文、路线步骤、交互和判定规则，同一题目身份不能悄悄改变教学契约。
- `association_hash` 固定题型、路线方法、步骤引用及提示条件树。关联调整可保留题目 ID。
- `content_version` 标识完整发布内容。纯正文变化也可以产生新版本，但不会仅因此关闭进行中的轮次。

发布同步删除过期的当前关联，停用移除的对象。路线关联变化只关闭受影响路线的未完成整题轮次；小题归属或有效题池内容变化关闭受影响节点的未完成检测轮次。保留已答记录、原归属及现有评估状态，未受影响轮次继续使用自身快照。

## 3. 数据结构与历史语义

| 对象 | 主要保存内容 |
| --- | --- |
| `knowledge_nodes` | 显式 `kind`、规则子类、别名、结构化正文、启用状态 |
| `knowledge_entries` | 节点下稳定条目 ID、条目类型、标题、顺序和正文 |
| `knowledge_edges` | 关系类型、端点、条目及重复调用 occurrence；不丢失同技能的多次调用 |
| `knowledge_resources` | 资源地址、作用域、允许的 case、样式及版本 |
| `learning_content_releases/current` | 发布元数据和当前版本指针 |
| `practice_topics/topic_problems/problem_types` | 训练分组与排序、题目—题型多对多关系 |
| `practice_routes/steps` | 路线方法、步骤引用、提示及完整 `field/options` 条件树 |
| `knowledge_drill_items` | 全局稳定题目 ID、主要节点、可选条目、来源、私有判定与内容哈希 |
| `student_practice_attempts` | 本轮版本、关联哈希、关联快照、私有教师契约快照 |
| `knowledge_drill_attempts/answers` | 固定五题、当时题目快照与归属、首答选项和正误、时间 |
| `student_node_assessments` | 可重建的状态、策略版本、依据轮次、证据位置、评估时间和可空概率 |

类型不根据 ID 前缀推断；例如 `method-complete-square` 是技能。内部引用使用 `node_id#entry_id`，不另造重复节点。

整题证据使用本轮关联快照和真实作答解析条件树，不 JOIN 当前映射重新归因。教师契约随轮次私有保存，后续移除旧教师文件仍可读取历史证据；API 不返回私有 `_lesson`、预期答案或判定规则。

`confirmed_choices` 只来自学生实际提交且被服务端规则确认通过的选择。为了恢复页面而填入的标准答案不属于实际选择，不能用于分支归因。候选提示可以保留为提示展示证据，但不表示学生已经采用候选方法或技能。

提示记录仍是 `hint` 事件，来源为 `node_explainer`，保存节点／条目、可选资源和服务端推导的候选标记。服务端校验当前步骤及实际分支。Q30 尚未通过或仅点选草稿时不决定提示分支；存在缺失选项分支时隐藏候选，防止暴露正确选项。导师判定通过但没有真实确认选项时，可以展示标有“候选”的提示，记录为候选展示，不进入实际方法或技能归因；前后端均使用服务端确认的通过步骤判断这个边界。

原始过程事件只允许补充 `displayed_at`，不开放 payload 更新。小题首答不可覆盖；同题在不同轮次出现时保存独立首答。公开接口在作答前不返回正确答案，并把可能暗示正误的原始选项 ID 转为中性选项编号。

## 4. 状态、证据和评估器

| 节点类别 | 个人记录 |
| --- | --- |
| 知识点、技能、方法、题型 | 独立能力状态，仅由本节点有效评测证据更新 |
| 教材、章、节 | 包含、拓展两组汇总；每组内按能力节点去重 |
| 判断规则 | 只保留实际选择与依据，无掌握状态、无概率，不虚构执行记录 |

当前评估器 `drill_round_v1` 独立于作答采集：无完成轮次为 `unassessed`；最近完成轮次首答 5/5 为 `mastered`，不足 5/5 为 `needs_review`。第五题首答、轮次完成和评估结果在同一事务中提交，重复提交不重复评估。进行中及已关闭轮次不覆盖状态，完成新一轮后状态可以下降。

概率字段保持 `NULL`，固定规则不伪造概率。当前题型没有有效检测题，保持未评估；整题通过仅增加过程证据，不自动传播到知识点、技能、方法或题型的掌握状态。目录返回状态和检测资格计数，不将其解释为教材或章节的掌握概率。

`assessment.rebuild(db)` 从原始完成轮次重建派生结果，也清除没有有效依据的残留结果。每个学生—节点在同一评估锁下重新读取最新完成轮次，避免与第五题并发提交互相覆盖。管理命令 `reassess-learning` 调用该入口；未来替换贝叶斯评估器不需要重做证据采集。

节点详情展示最近完成轮次的五题依据、历史首答及整题原始事件。尚未提交答案但已有提示或导师对话的步骤也可查询；仅初始化题目上下文不生成证据。条目锚点可以筛选证据；提示候选、展示确认、规则判分与导师判分分别显示，公式使用公共数学渲染器。候选提示单独保存在 `shown_references` 展示清单，不并入实际采用的 `refs`。查询先在数据库按历史节点／条目引用筛选，再批量读取真实选择；过程记录按 `last_activity_at DESC NULLS LAST` 排列。

小题轮次的 `updated_at` 在首答、完成、手动关闭和发布关闭时更新；重复提交不会刷新活动时间。迁移前已关闭的轮次无法恢复真实关闭时间，仅按已有开始、作答、完成时间回填，不伪造历史。

## 5. 接口与网页接线

除安全的内容版本接口外，下列接口均按当前账号隔离。

| 接口 | 主要约定 |
| --- | --- |
| `GET /api/learning/content` | 公开返回 `schema_version`、`content_version`、安全的 counts |
| `POST /api/learning/practice` | 要求题目、路线、请求 ID 及内容版本；固定本轮快照 |
| `GET /api/learning/practice/{id}` | 本轮固定版本、关联、服务端进度、真实 `confirmed_choices` 和安全原始事件 |
| `POST /api/learning/practice/{id}/answers` | 幂等提交；错误不能推进，旧首答不能伪造为新选择 |
| `POST /api/learning/practice/{id}/references` | 节点、可选条目引用及资源；校验实际或允许的候选提示 |
| `POST /api/learning/practice/{id}/displayed/{event}` | 确认提示或导师内容已展示 |
| `POST /api/learning/drills` | 要求节点、请求 ID、内容版本；服务端决定五题资格 |
| `GET /api/learning/drills/{id}` | 固定本轮题目与首答；未答题不返回答案 |
| `POST /api/learning/drills/{id}/answers/{position}` | 当前题首答，完成第五题时更新评估 |
| `GET /api/learning/nodes` | 四类能力状态、策略、依据、有效题数和检测资格 |
| `GET /api/learning/progress?scope=...` | 教材／章／节的 `contains` 与 `extends` 两组汇总 |
| `GET /api/learning/nodes/{id}/evidence?entry=...` | 当时归属的整题证据和小题首答，条目可选 |
| `POST /api/tutor-demo/sessions` | 绑定练习时必须带 `practice_attempt_id` 和 `content_version`；独立导师兼容原入口 |

前端在启用记录前同时校验静态版本、单题关联版本和 API 版本；关联加载器再次读取时也校验同一版本。版本不符阻止新记录写入并提示刷新，静态作答仍可继续。

记录队列将网络错误、401、429 和 5xx 保留为可重试。提示辅助记录被明确拒绝时提示未保存并继续处理后续正式作答，不清空整个队列。登录联调中的导师绑定轮次，事件不能把已绑定会话转移到另一轮；普通题页导师使用独立会话。恢复时保留实际确认选择，不用标准答案构造证据。版本检查重试成功后，已在静态模式完成的步骤不会补记为评测证据，需要刷新后开始保存。

## 6. 管理命令与本地重建

仓库根目录的常规维护：

```sh
node tools/export-public-knowledge.mjs --check
node tools/build-public-knowledge-graph.mjs
node tools/build-public-knowledge-graph.mjs --check
./deploy/product/manage.sh --mode local check-learning
./deploy/product/manage.sh --mode local publish-learning
./deploy/product/manage.sh --mode local doctor
./deploy/product/manage.sh --mode local reassess-learning
```

`check-learning` 校验但不写库；`publish-learning`、安装和部署使用同一新发布器。修改原稿后应生成静态页面并发布对应数据库版本，避免页面和 API 版本不一致。

一次性旧库替换另用 `rebuild-learning`，仅允许本机 local 模式的 `0010_learning_record_integrity` 实例：

```sh
./deploy/product/manage.sh --mode local rebuild-learning
```

此命令先校验原稿、列出清理范围、停写和备份，再在一个事务内清理旧图谱学习记录、迁移结构并导入新内容。只清理相关整题事件与汇总、小题轮次与答案、旧公共映射及这些题目的学习标记；用户、登录及其他业务数据保留。没有使用级联删除扩大范围。失败回滚并保留停写保护，排查后再恢复服务。

本轮日常本地实例已完成该一次性替换，备份 ID 为 `caa84d3b972d4038a5c55f9f337d627d`，随后用普通迁移增量升级到 0012，没有再次清理记录。后续使用普通迁移和发布，不重复执行重建。普通迁移和部署遇到尚未替换的旧内容会明确停止，不自动清空记录。

管理镜像包含新原稿、Node 导出和共享校验依赖，按需复制题页契约和图解资源；API 镜像保留运行所需教师契约，不依赖静态构建。发布包从同份 Alembic 源码解析 head，不写死旧 revision。权限由 `doctor` 核对，API 账号不能修改公共内容和私有原始答案。

## 7. 验收记录（2026-10-13）

最终公开版本为 `71c99da6e16bdd1c4f6bb97b84f2597321d5860fbb53daff7d209d699c7a71f9`，结构版本为 `2`。
原稿、静态清单和本地 PostgreSQL 使用同一内容版本。

| 当前内容 | 数量 |
| --- | ---: |
| 公共节点／内部条目／公共关系 | 67／183／218 |
| 图解资源／专题 | 32／2 |
| 整题／路线／步骤／提示分支 | 39／50／259／219 |
| 有效小题／有小题节点／可五题检测节点 | 177／29／16 |

| 初次实现验收 | 结果 |
| --- | --- |
| 独立 PostgreSQL 的认证、学习记录及导师回归 | 512 通过；54 项可选集成用例未启用，不计入通过 |
| 最终学习发布与记录定向回归（开启真实导师） | 47 通过，无跳过；含最后的历史证据修复 |
| Node 导出、图谱、预览、记录队列及联调模块 | 67 通过，无跳过；含 50 条路线与 Q30 分支回放、SVG 导航 |
| 本地 0010 一次性重建 | 2 通过；使用一次性 PostgreSQL，包含发布后注入故障、DDL 与数据共同回滚 |
| 管理命令及发布源码版本 | 9 通过 |
| 实际 linux/amd64 管理及 API 镜像 | 2 通过；独立容器空库安装、两次发布、doctor 和 API 题页编译 |
| 新旧静态产物 | 新生成器 238 个文件 `--check` 无差异，旧生成器 27 页校验通过 |
| 初次本地 doctor | PostgreSQL 17.10、0011、2606 个原有产物、无孤立产物，权限检查通过 |

使用专门的测试账号（尾号 8883）完成浏览器联调：手机宽度 390 px 下完成五题检测；前三题后仍未评估，刷新从第四题继续，第五题后变为已掌握。桌面上可以查看五题首答及排版后的公式。基本不等式知识点仅有一题，界面明确不开放五题检测。

整题 Q01 实测错误不能推进、修正后保存、图解确认展示、刷新恢复到服务端确认步骤；真实导师回复保存后，再次刷新能够恢复，提交 0 次的步骤也能从节点详情查看这段对话。节点原始记录区分错答、规则判定与提示，整题过程不改变掌握状态。2.2 的目录汇总分别显示包含与拓展，配方技能的掌握计入拓展组；教材汇总、总览 SVG 章链接也已实测保留登录联调模式。

本轮浏览器证据保存在本机 `/private/tmp/shuxueshuo-stage3-evidence/`：`mobile-drill-mastered.jpg`、`mobile-reference.jpg`、`desktop-practice-restored.jpg`、`desktop-assessment-evidence.jpg`。测试日志保存在 `/private/tmp/stage3-*-final.log`，不作为仓库或发布镜像输入。

代码审查修复后的定向复验：

| 验收 | 结果 |
| --- | --- |
| 学习记录、发布、证据查询、路由鉴权及导师定向回归 | 85 通过，无跳过；使用独立 PostgreSQL 并开启真实导师 |
| Node 图谱、导出、教学关联、记录队列、导师可用性 | 76 通过，无跳过；包含普通页版本接口缺失、离线、异常及不返回的情况 |
| 管理入口与实际镜像 | 管理入口 10 通过；重建两镜像后集成 2 通过，无跳过；本次未重复执行本地 0010 清理重建测试 |
| 共享发布锁 | 三类读取操作可并行；与发布排他锁双向等待，锁顺序回归通过 |
| 发布字段与轮次时间 | 非法字段拒绝、事务回滚、0012 回填、作答与关闭更新时间、重复提交不改时间通过 |
| 证据查询与接口登录保护 | 按节点／条目筛选；多轮历史固定四次查询；遍历全部图谱接口，只有 `/content` 可匿名 |
| 静态产物与本地实例 | 238 文件 `--check` 无差异，内容版本不变；本地 doctor 验证 0012 及权限通过 |

浏览器实测无参数的 `/1/q01/`：提示暂不保存进度时，导师输入与提示仍可用，并收到真实回复。截图为 `/private/tmp/shuxueshuo-stage3-evidence/ordinary-page-tutor-review.jpg`。本次 Node、Python 定向日志分别为 `/private/tmp/stage3-review-node.log`、`/private/tmp/stage3-review-python.log`。

## 8. 复验命令与后续边界

数据库验证使用独立实例，与日常 5432 数据隔离。本轮独立实例验收后已停止，数据保留在 `/private/tmp/sss-stage3-20261013`，固定日常实例和网站继续运行。复验时先在仓库根目录执行 `./deploy/product/manage.sh --mode local --data-dir /private/tmp/sss-stage3-20261013 --instance stage3 db-start`，然后在 `server/` 下运行：

```sh
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-stage3-20261013 PRODUCT_TEST_INSTANCE=stage3 uv run pytest -q tests/auth/test_learning_graph.py tests/auth/test_learning_publish.py tests/auth/test_learning_evidence_query.py tests/auth/test_learning_route_auth.py
uv run pytest -q tests/tutor_demo/test_session_start.py tests/tutor_demo/test_learning_associations.py
```

根目录的前端及导出回归：

```sh
node --test tools/tests/public-knowledge-learning.test.mjs tools/tests/practice-records.test.mjs tools/tests/public-knowledge-export.test.mjs tools/tests/practice-tutor-access.test.mjs
```

真实导师测试需要显式启用 `RUN_LLM_INTEGRATION=1`；没有数据库或凭据造成的跳过不算相应功能通过。数据库测试覆盖空库与旧库替换、重复发布和回滚、账号隔离、不可变首答、并发开练、状态升降、重算、历史归属、Q30 分支边界和权限。浏览器检查另外覆盖桌面及手机的公式、恢复、图解、刷题和导师。

阶段 4 继续处理正式入口切换、全图个人状态及服务器实际版本核对和上线。自动题型识别、图计算、可执行 Plan、贝叶斯模型参数和整题能力评估不在当前实现中。
