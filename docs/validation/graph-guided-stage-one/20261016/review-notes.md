# 阶段①检查与人工核对记录（2026-10-16）

> **2026-10-16 补充：** 本文记录的是 v1 契约（含出处锚点与约定声明）的运行与验收。阶段①已精简为 v2 契约，出处与约定机制已删除，见[阶段①实现计划第 0 节](../../../graph-guided-stage-one-implementation-plan.md#0-v2-精简修订)。文中 `recorded/` 下的 v1 录制已移出受版本管理目录，归档在本机 `internal/solver-runs/graph-guided-stage-one/archive-v1/`，相关链接不再有效。

本文件区分 **Codex 已执行的检查** 与 **尚待用户完成的人工核对**。下列 Codex 检查不能填写为 human review 已通过，也不把金标调试报告当成真实 LLM 样本。

当前第四轮 `live-20261016-04` 自动验收 **18/18 通过**，全部九个独立 pytest case 通过；录制、零网络回放及完整成功批次目录门禁通过。用户人工核对仍为 **pending**。

## Codex：九题输入图片检查

检查对象为 [固定语料 manifest](../../../../server/tests/solver/fixtures/graph-guided-stage-one/quadratic-always/manifest.json) 对应的九张 `source.png`。这些图片由网页的原题段经过本地 Playwright、KaTeX 和固定字体渲染，来源类型为 `synthetic-rendered`。

Codex 已逐张打开 Q01–Q09 图片并与冻结 `problem.md` 核对，观察结果如下。此处记录的是 Codex 视觉检查，不是用户签字。

| 题目 | Codex 检查重点 | 观察结果 |
| --- | --- | --- |
| Q01 | 负二次项、非严格关系、任意实数 x 与目标 a | 原题完整，关系符号与上下标清晰，无裁切。 |
| Q02 | 含 k 的二次式及“恒成立” | 原题完整；图片没有额外补入 x 的量词范围或解法。 |
| Q03 | 两处括号、平方项与严格关系 | 原题完整，括号和上标可辨；末尾自然换行，没有裁切。 |
| Q04 | 闭区间的两个等号、严格小于关系 | 原题完整，端点及不等号清晰。 |
| Q05 | 开区间、严格大于关系与“有解” | 原题完整，开闭区别及存在语义措辞可见。 |
| Q06 | 全称符号、x 小于零、非严格关系与“为真命题” | 所有原文部分均在图片中，未换成解题解释。 |
| Q07 | 集合描述的花括号、竖线与两个端点 | 原题集合描述保留，未在图片中改写为区间。 |
| Q08 | y 定义、m 的范围、y 小于零与目标 x | 两处数学信息与量词措辞完整，未附带求解答案。 |
| Q09 | y 定义、a 的范围、y 大于零与目标 x | 原文完整；未额外补入原题没有逐字写出的实数目标域。 |

`prepare_graph_stage_one_corpus.py --check` 曾对九题原题段、图片、渲染配置、金标及验收规则哈希执行校验并通过。金标依据原题独立编写，九题题意和特征离线自洽检查通过；这些属于确定性验证，不是模型识图通过成绩。

## Codex：报告与出处联动检查

检查使用独立人工金标构造的 `authored_debug` 报告，没有发起模型调用。临时产物为 [本机调试报告](/private/tmp/graph-stage-one-report-check/report/index.html)；临时目录可能被清理，不作为受版本管理的正式验收材料。

Codex 在本地浏览器实际打开报告，检查了汇总页和 Q08 样本页。点击 `normal_form` 后，原文中以下两段同时高亮：

1. `$y=mx^2-mx-6+m$`。
2. `若对于 $1\le m\le3$，$y<0$ 恒成立`。

出处详情显示对应 `/root/facts/1` 及冻结原文的字符区间。浏览器记录 `pageerror=[]`，Q08 页的四个公式块正常渲染。报告使用本地 KaTeX 资源，没有外部 CDN 依赖。

另已用确定性测试覆盖：无效 JSON 和截断文本保留、失败调用材料、缺失账本、非 BMP 字符的 code point 高亮、缺失耗时不按零统计，以及历史 live 与离线重评分开展示。这些测试和浏览器检查说明报告可以调试，不证明每个真实模型输出正确。

## 已有真实材料与核对入口

- 第一轮真实批次：[统一报告](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-01/index.html)、[冻结汇总](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-01/batch-summary.json)、[录制入口](../../../../server/tests/solver/fixtures/graph-guided-stage-one/recorded/live-20261016-01/batch-summary.json)。历史最终成绩为 9/18，保持原样。
- 第一轮材料经修复后离线重评：[独立汇总](../../../../internal/solver-runs/graph-guided-stage-one/offline-evaluation-20261016-fixes-01/summary.json)。12/18 是零网络重评结果，不是新增 live 成绩。
- 第二轮真实批次：[统一报告](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-02/index.html)、[冻结汇总](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-02/batch-summary.json)、[录制入口](../../../../server/tests/solver/fixtures/graph-guided-stage-one/recorded/live-20261016-02/batch-summary.json)。完整 18 个样本的历史最终成绩为 **13/18**，冻结版本一致，正式验收未通过。初次提取独立验收 **15/18** 不包含原图 review 确认。
- 第三轮真实批次：[统一报告](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-03/index.html)、[冻结汇总](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-03/batch-summary.json)、[录制入口](../../../../server/tests/solver/fixtures/graph-guided-stage-one/recorded/live-20261016-03/batch-summary.json)。完整 18 个样本，初次提取独立验收 **15/18**，最终 **17/18**；pytest 为 8 项通过、1 项失败。已导出并纳入历史样本零网络回放，历史正式验收未通过。
- 第四轮正式成功批次：[统一报告](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-04/index.html)、[冻结汇总](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-04/batch-summary.json)、[录制入口](../../../../server/tests/solver/fixtures/graph-guided-stage-one/recorded/live-20261016-04/batch-summary.json)。初次提取 **16/18**，Q08 两个样本各一次 repair 后最终 **18/18**；独立 CLI [回放](../../../../internal/solver-runs/graph-guided-stage-one/replay-20261016-final/batch-summary.json)全 18 通过，新语义调用与网络尝试均为 0。

## Codex：第二轮失败核对与 v2 协议复核

Codex 已只读核对第二轮的逐样本汇总、独立验收结果、最终候选和关键调用事件。五个历史失败应分别理解：

| 样本 | 可复查的问题 | 核对结论 |
| --- | --- | --- |
| Q05/01、Q05/02 | 出处已覆盖开区间、完整不等式和“有解”，v1 仍要求“关于 x 的不等式”的叙述部分。 | 旧出处判据误拒，不能写成数学提取失败。历史成绩仍保留为未通过。 |
| Q07/01 | review 虽写 confirmed，却同时返回了题意字段。 | 输出不符合 `status/findings` 契约；`source_reviewed=false`，不能算有效原图确认。 |
| Q08/02 | 量词内关系已展开，但额外保留了涉及自由 m 的全局 y 定义。 | 数学作用域不等价。这是**第二轮**问题；第一轮 Q08 的两个失败分别是缺量词出处和缺显式目标实数域。 |
| Q09/01 | 初次提取正确，review 错误要求加入全局 y 定义，并将量词关系改回未展开的 y>0。 | 复核与修复引入错误，最终题意和结构特征均未通过；不能以最后的 confirmed 替代独立验收。 |

详细调用、用量和 18 个样本结果见 [验证记录](validation.md)。上述判断来自已保存产物，不代表用户已逐项核对。

第二轮完整结束并录制后，另一实现者依据九题原文与独立数学金标统一编写 `graph-stage-one-acceptance/v2`，共 54 个 typed evidence components。Codex 复核了所有组件的 AND 关系、同组件 alternatives 的 OR 关系、每个 alternative 内 quotes 的 AND 关系及原出处窗口限制。目标字母只能从原目标出处引用，Q08/Q09 必须同时引用 y 定义与原不等式，Q06 真值证据保留“真命题”；Q02/Q03 的省略量词变量和实数域仍需程序核验约定。

九题的原文、图像、数学题意、出处上下文和特征金标没有改变；只修订出处验收协议及相应程序规则。旧新验收哈希、统一修订依据和历史录制引用见 [验证记录中的 revision 2](validation.md#出处验收协议-revision-2) 以及各题 `source-manifest.json`。v2 的预检分型是当前九题范围内的保守校验，不能据此宣称已能自动证明任意新题的出处语义。金标自验和确定性测试均不能将第二轮历史 **13/18** 改写为新的 live 成绩。

## Codex：第三轮失败与修复核对

Codex 已只读核对第三轮 18 个样本的汇总、ledger、首轮及最终独立验收。38 次真实语义调用包含 18 次 extract、18 次 review、2 次 repair；Q04/02 的错误默认域约定和 Q08/01 的量词依赖全局别名各经过一次 repair，最终通过。其余 16 个样本没有 repair；“没有 repair”不等于独立首轮通过，Q08/02 是唯一反例。

唯一失败 [Q08/02 独立验收](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-03/q08/q08/sample-02/evaluation.json)显示：数学语义、候选自身出处绑定和特征均通过，原图 review 也给出确认，但转录在“恒成立”后遗漏逗号，以换行接“求”。主任务与契约实现者的 Codex 视觉检查确认原图第二行“立，求”的逗号清晰存在，因此这是实际漏转录标点；不应把它表述为单纯换行差异。

严格题文比较为 false，导致依赖规范全文一致性的七个出处组件都显示 false；**这不代表七处引文全部缺失**，也不否定候选自身 `source_map.ok=true`。该样本仍按当批规则记作未通过，不放宽题文或 v2 金标，不将后续重评回写历史结果。第四轮前已加强通用标点保留及原图复核提示；第四轮通过是新样本结果，不改变本轮失败记录。

离线工具另修复了未完成批次回放完整性、已有调用但终态落盘失败的录制与回放、报告发现 pytest 嵌套样本三处问题。相关程序回归与第三轮 live 成绩分开记录，详见 [验证记录](validation.md#第三轮修复唯一失败与后续边界)。这些 Codex 检查均不替代用户人工核对。

## Codex：第四轮自动结果核对

Codex 只读核对了第四轮 18 个样本的冻结指纹、初次及最终独立验收、ledger 与模型用量。所有样本的 `implementation_unchanged=true`，最终题文、数学、出处和必需特征均通过；初次提取 16/18 不包含原图 review 确认，最终 18/18 包含有效原图 review。Q08/01、Q08/02 的全局 y 别名作用域问题由程序检出，各 repair 一次后通过，保留了修复前候选与诊断。

全部 73 个历史样本的禁网络回放与完整成功批次门禁已纳入最终 **927 passed、16 skipped** 回归；没有排除目录门禁。第四轮 CLI 全量回放 18/18、新调用 0，历史 live 与当前 offline 模式分开保存。完整逐样本表、计量及证据链接见 [验证记录](validation.md#第四轮逐样本记录)。最终 59 个冻结实现文件与第四轮 live 指纹一致；新增及相关文件 Ruff 检查和 `git diff --check` 通过，不作全仓 lint 通过声明。

## Codex：第四轮真实报告浏览器 QA

Codex 使用真实 Chrome 打开第四轮 `index.html`，确认首页列出 18 行样本、18/18 通过、9/9 题覆盖和“人工核对待完成”。从页面实际链接进入 Q08/02（`sample-016.html`），点击 `normal_form` 后，y 定义与量词不等关系两处原文同时高亮，出处详情显示 `/root/facts/0`；清除高亮正常。检查过程中 `pageerror`、`console.error` 和失败请求均为空。

QA 前后检查的 51 个样本冻结 JSON 文件哈希一致，浏览器检查没有改写候选、评价或历史调用。材料保存在运行目录，未复制到文档目录：[QA 记录](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-04/qa/browser-qa.json)、[首页截图](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-04/qa/index.png)、[Q08/02 双出处高亮](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-04/qa/q08-02-normal-form-sources.png)、[规范关系特征](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-04/qa/q08-02-normal-form-value.png)。

以上为 Codex 的程序与视觉检查，**不是用户人工核对通过或签字**。

## 人工核对：待用户填写

| 字段 | 当前记录 |
| --- | --- |
| 核对人 | 待用户填写 |
| 核对日期与时间 | 待用户填写 |
| 核对批次与冻结版本 | 待用户确认第四轮 `live-20261016-04`；实现指纹 `fcea9dc8d9379ff5462defdbdc359a97dde4140bba74c731b25660276e3bb302` |
| 核对样本范围 | 待填写，应覆盖第四轮 Q01–Q09 的全部 18 个样本 |
| 原图与转录是否一致 | 待核对 |
| 题设／目标出处是否支持对应数学语义 | 待核对，特别是 Q02/Q03 的约定补全、Q08/Q09 的两处出处、目标变量的原请求位置与 Q06 的真值断言 |
| 量词与全局定义的作用域是否正确 | 待核对；不得把量词中的参数改成全局自由变量，须检查 review/repair 是否把正确展开改坏 |
| 结构特征、严格性、端点和变量角色是否正确 | 待核对 |
| 失败与修复记录是否完整且未覆盖 | 待核对 |
| 结论 | 待用户填写；当前不表示通过 |

逐项发现问题时，请记录稳定路径，例如 `q08/sample-02`、`/root/facts/1`、`normal_form` 或具体调用号，同时说明原图依据、预期行为和实际行为。建议记录格式：

| 样本／调用／字段 | 人工观察 | 结论或待处理事项 | 核对人 |
| --- | --- | --- | --- |
| 待填写 | 待填写 | 待填写 | 待填写 |

阶段①范围限于合成题图、根 scope 和结构特征；本记录不对真实扫描质量、题型定位、方法选择、最终解答或阶段②–④作通过声明。
