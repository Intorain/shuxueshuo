# 新公共知识图谱：阶段 2 教学内容迁移

日期：2026-10-13。状态：关联原稿、预览及验收完成。正式题页、数据库、旧练习记录及提交接口仍使用原有数据；本阶段没有清理或迁移数据库。

## 1. 交付与入口

| 内容 | 数量及处理 |
| --- | --- |
| 公共节点 | 67：教材 1、章 3、节 5、知识点 13、技能 20、方法 14、题型 9、判断规则 2 |
| 公共关系 | 218 条；从节点原稿派生，不包括具体题目的教学关联 |
| 整题关联 | 39 道题、50 条路线、259 个步骤、219 个提示分支 |
| 旧新身份清单 | 27 个旧节点逐一登记，按上下文复用、改类、拆分或引用内部条目 |
| 小题来源 | 27 套、180 道；75 道保留原主要归属、102 道调整归属、3 道暂时停用 |
| 新小题库 | 29 个节点、177 道有效题；其中 16 个节点至少有五道题 |
| 构建产物 | `site/knowledge-next/` 共 233 个文件，含页面、关联 JSON、反向索引及内容哈希资源 |

本地入口：

- [教学关联总览](http://127.0.0.1:8779/knowledge-next/topics/)。
- [基本不等式预览](http://127.0.0.1:8779/knowledge-next/topics/basic-inequality/)及[完整关联表](http://127.0.0.1:8779/knowledge-next/topics/basic-inequality/review/)。
- [一元二次不等式预览](http://127.0.0.1:8779/knowledge-next/topics/quadratic-always/)及[完整关联表](http://127.0.0.1:8779/knowledge-next/topics/quadratic-always/review/)。
- [小题去向表](http://127.0.0.1:8779/knowledge-next/topics/drills/)及[旧新身份清单](http://127.0.0.1:8779/knowledge-next/topics/migration/)。

题页通过 `?knowledge=next` 启用预览，例如 `/1/q01/?knowledge=next`。原有点选、规则判定、步骤推进与路线切换保留；页面标注“关联预览，不保存练习记录”。预览不初始化学习记录器、学习标记或导师，不调用小题作答接口。专题返回、相邻题目、新图谱的现有例题链接均进入预览。

新增方法“二次函数最值法”承接 Q01、Q09 消元后的顶点分支；配方分支使用“配方求最值法”。方法使用已有消元、换元、化简和二次函数区间求值技能。和积换元法的后续调用按实际任务补入基本不等式求界及不等式求解。

## 2. 唯一原稿与引用规则

| 原稿或工具 | 职责 |
| --- | --- |
| `site/data/knowledge-next/nodes/` | 公共节点正文、内部条目与方法路径 |
| `site/data/knowledge-next/topics/<专题>.json` | 专题分组、题型、路线方法、步骤关联和图解提示的唯一新原稿 |
| `site/data/knowledge-next/migration.json` | 旧新公共身份清单；仅作迁移解释，运行时不据此批量猜测归属 |
| `site/data/knowledge-next/catalog.json` | 明确的图解资源地址、样式作用域、允许的 `case`、旧资源内部链接转换 |
| `server/shuxueshuo_server/learning/drills-next/` | 私有新小题库、逐题去向与停用原稿 |
| `tools/lib/public-knowledge-teaching.mjs` | 教学契约、关联与小题校验，派生反向索引 |
| `tools/lib/public-knowledge-teaching-html.mjs` | 专题预览、审阅表、弹层正文与静态关联数据生成 |
| `site/assets/knowledge-next/teaching-model.mjs` | 构建及浏览器共用的条件分支解析 |
| `site/assets/knowledge-next/practice-preview.mjs` | 预览关联面板、步骤提示及导航 |
| `site/assets/knowledge-next/resource-runtime.mjs` | 详情页与练习弹层共用的图解加载及清理 |

旧专题映射不随新原稿手工同步。阶段 3 导入上述新原稿；`site/knowledge-next/teaching/` 是派生产物，不反向编辑。`teaching/reverse.json` 保留为阶段 3 的反向关联接口，目前前端不读取它。

题目、路线、步骤 ID 保持原样。题页 `practice-config` 提供步骤标题和顺序；生成时与教师 JSON 核对 ID、版本、路线、步骤顺序、标题、提问、交互、预期答案和反馈。新图谱关系不复制到题页配置或教师 JSON。

关联叶子是引用数组，可写 `节点ID#条目ID`。`kind` 以节点数据为准，例如历史 ID `method-complete-square` 实际是技能。路线的 `methods` 只能引用完整方法节点；步骤可以引用知识点、技能、方法或其内部条目。没有教学关联的展示步骤必须填写 `reason`。

条件关联复用题页已有选择字段，例如：

```json
{
  "methods": {
    "field": "technique",
    "options": {
      "square": ["method-square-extremum"],
      "vertex": ["method-quadratic-extremum"]
    }
  }
}
```

步骤的 `refs` 使用同样的结构；`tip` 的叶子为 `{ref, resource?, case?, note?}`，允许多层 `field/options`。没有资源时展示正文与例子，不允许指定 `case`。步骤不得引用未来步骤才出现的选择。

未选择时返回候选关联；选择后只返回匹配分支。选择以所在步骤提交通过为准，未提交的点选不参与匹配。未作答的选择只要有选项缺少分支（通常是错误选项），就不列候选，改为提示作答后显示，避免候选暴露正确选项。专题审阅表和反向索引保留每条分支条件，不能把静态汇总视为学生实际使用过的全部节点。图解提示必须登记在相容分支的步骤关联中；日常构建校验新引用、`case` 和选择条件，旧 `case`、`note` 与分支是否完整迁移由一次性迁移验收核对。

## 3. 图解与小题

图解通过显式资源 ID 加载，资源身份与节点身份分开。弹层显示真实节点类型，直接调用详情页的共享正文渲染器，不从完整 HTML 截取内容。条目引用定位到对应正文，审阅链接显示条目标题。Q01、Q09 顶点分支使用二次函数顶点图解。

资源生成到 `teaching/resources/<资源ID>.json`，当前共 32 个文件。打开提示只请求所需资源，成功后在当前页面复用；失败时可单独重试。正文数据不重复包含图解 HTML，也不再生成或请求整包 `resources.json`。已存在但加载失败的样式表会重新发起加载，避免错过旧请求的失败事件后一直等待。

资源自身的适用条件在弹层和详情页同时显示。例如水平线图解使用最值可达的闭区间，明确提示开区间需另行检查边界，不能直接套用最大值／最小值表。

完成当前步骤前只显示通用说明、条件及通用图解，不传入本题的 `case/note`，不显示本题完成后的结论。完成后可以查看条目正文及原有本题说明。正文和图解独立加载，一方失败不遮住另一方；提供重试和普通详情链接。关联加载失败时静态作答继续可用，不回退到旧关联。

小题每道只有一个主要考查节点，可附 `entry`。迁移题的 ID 为 `旧节点ID--旧题ID`，保留 `origin: {node, item}` 与原出处，合并归入同一节点时不会发生 ID 冲突。迁移清单逐道记录动作、目标和理由；一次性验收检查保留或改归属的题目与原题内容一致，内容改动需标为 `revise`。后续新编小题使用唯一稳定 ID，可省略 `origin`，无需虚构旧来源或追加迁移记录；日常构建仍校验归属、题干、选项、答案与反馈。

本轮复核保留有效题的题干、正确答案、选项和干扰项反馈。原 `case-merge` 中 `intersect-endpoint`、`union-endpoint`、`which-union` 三题主要考查一般集合交并，当前没有对应公共节点，因此保存在 `retired.json`，不硬挂到某种方法。

`sets/<节点ID>.json` 中的答案与判定留在服务端；公开审阅表仅有来源、归属、数量和迁移说明。五题数量资格由有效题数派生，当前不开放新图谱刷题；少于五道的节点未来也不开放五题检测。

## 4. 构建与验收

仓库根目录：

```sh
node tools/build-public-knowledge-graph.mjs
node tools/build-public-knowledge-graph.mjs --check
node tools/build-knowledge-pages.mjs --check
node --test tools/tests/public-knowledge-graph.test.mjs tools/tests/public-knowledge-teaching.test.mjs
```

新图谱日常构建读取新原稿、题页配置、教师 JSON 和显式引用的图解模块，不读取 `site/data/knowledge/` 或旧 `learning/drills/`。题目、路线、步骤、提示和小题数量由原稿统计，不作为构建断言；新增内容只需满足引用与教学契约。

迁移基线核对独立运行，需要保留旧原稿：

```sh
node --test tools/tests/migrations/public-knowledge-stage2.test.mjs
```

该测试固定阶段 2 的数量和旧新内容一致性，不加入日常构建。阶段 4 删除旧数据时，一并归档或移除这项历史迁移测试；上述旧图谱生成器检查也仅在旧页面保留期间运行。

在 `server/` 下运行旧流程定向回归：

```sh
uv run pytest -q tests/tutor_demo/test_knowledge_graph.py tests/tutor_demo/test_quadratic_graph.py tests/tutor_demo/test_quadratic_always_consistency.py tests/tutor_demo/test_local_practice.py tests/tutor_demo/test_runtime_retry.py
```

| 验收项 | 覆盖与结果 |
| --- | --- |
| 数据与本体 | 67 节点、39 题、50 路线、259 步骤、219 提示、180 小题全量覆盖；节点、条目、资源、`case`、选择字段、教学契约及端点类型通过校验 |
| 构建 | 重复生成一致，`--check` 能检出缺失、过期与多余产物；旧图谱 27 个详情页校验通过 |
| 独立维护 | 临时副本不含旧图谱和旧小题库时仍可构建；新增整题与新编小题后通过校验，教学契约错误仍会被拒绝 |
| 自动回放 | 实际 `PracticeContext` 回放 50 条路线及全部正确选择组合，错答与空答不能推进，改正后可完成，路线切换清空旧选择 |
| 隔离与恢复 | 实际运行时在登录和未登录两种状态回放全部路线；关联 503 后仍可作答，重试成功；未初始化记录器、标记、导师，也未发出学习提交或完成事件 |
| 提示故障 | 实际弹层控制器验证完成前隐藏结论、按资源请求与缓存、正文与图解独立失败及重试、无资源正文展示和旧图解卸载；覆盖已失败样式表的重新加载 |
| 测试 | Node 常规回归 29 项、一次性迁移验收 2 项通过；旧题页与运行时 Python 定向回归 52 项通过 |
| 浏览器 | 桌面与 390×844 手机视口检查路线分支、错答纠正、条目链接、长公式、图解及专题导航；Q30 选不等式一步作答前不列候选，提交后按所选写法显示对应提示 |

新页面、模块和样式使用内容哈希地址；共用题页运行时引用统一更新为 `runtime.js?v=36`。生成器只管理新预览目录，未重写旧图谱原稿或产物。浏览器几何布局与自动回放分别验证，自动回放不声称替代浏览器截图检查。

## 5. 阶段 3 交接

数据库导入需支持八类节点、节点内部条目、具体题型关联、逐路线方法，以及保留条件的步骤与图解引用。导入时复用校验后的唯一原稿，不从页面显示文本或旧专题路线名推断新方法。

接口解析必须区分候选和实际关联，按已保存的选择值解析 `field/options`。记录图解时分别保存节点／条目与资源身份，并校验当前步骤和选择条件。节点或条目的有效性按明确类型判断，不能根据历史 ID 前缀判断。

新小题导入仅使用 `drills-next/sets/` 的有效题，`retired.json` 不开放练习；主要节点与可选条目单独保存，答案不暴露到静态发布目录。后续五题检测仍需完成整轮才更新个人状态，规则在数据库与接口阶段接入。

清理本地旧学习记录、替换正式公共内容导入、接通练习记录和导师、切换正式图谱入口均属于后续阶段。图计算、自动题型识别、可执行 Plan 和整题节点掌握评估不在本阶段实现范围。
