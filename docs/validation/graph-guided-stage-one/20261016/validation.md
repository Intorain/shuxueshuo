# 图谱课程阶段①验证记录（2026-10-16）

> **2026-10-16 补充：** 本文记录的是 v1 契约（含出处锚点与约定声明）的运行与验收。阶段①已精简为 v2 契约，出处与约定机制已删除，见[阶段①实现计划第 0 节](../../../graph-guided-stage-one-implementation-plan.md#0-v2-精简修订)。文中 `recorded/` 下的 v1 录制已移出受版本管理目录，归档在本机 `internal/solver-runs/graph-guided-stage-one/archive-v1/`，相关链接不再有效。

状态：第四轮 `live-20261016-04` 的九题独立真实测试全部通过，最终 **18/18**；初次提取独立验收 **16/18**，两次 repair 后全部通过。最小录制、全量零网络回放和最终离线回归已完成，**自动验收通过，人工核对仍为 pending**。前三轮失败记录保留，人工核对人及签字待用户填写，详见 [review-notes.md](review-notes.md)。

依据：[阶段①实现计划](../../../graph-guided-stage-one-implementation-plan.md)。本文只汇总可定位的记录，不把离线重评、金标检查或探针运行计入正式真实通过成绩。

## 运行与验证范围

输入为 Q01–Q09 的原题段合成图片，标记为 `synthetic-rendered`。只读取 `site/2/qNN/index.html` 的 `.problem-card > p[data-math-text]`；题意整理、教学步骤及答案未进入图片。题文、图片、来源、渲染配置与金标哈希见 [语料 manifest](../../../../server/tests/solver/fixtures/graph-guided-stage-one/quadratic-always/manifest.json)。

当前链路覆盖根 scope 的题文转录、无 family 数学题意、出处与约定校验、原图 review/repair、结构特征、记录和离线报告。阶段②–④尚未接入；不包含题型识别、选法、参数答案求解、首项系数符号或降次分支检查。合成题图不能作为真实扫描识图质量验收。

## 批次结论

| 记录 | 输入与调用 | 已确认结果 | 解释 |
| --- | --- | --- | --- |
| `q01-probe-20261016-01` | Q01，1 个真实图片样本，2 次语义调用 | 不计正式验收；`implementation_unchanged=false` | 执行期间代码冻结指纹变化，虽然工作流到达 `reviewed_candidate`，不能把它当作冻结版本下的通过样本。 |
| `live-20261016-01` | 9 题 × 2 个独立真实样本，共 18 个样本 | **9/18 最终通过**；完整覆盖，正式通过为否 | 历史结果保持原样；没有从其他批次补入成功样本。 |
| `offline-evaluation-20261016-fixes-01` | 对第一轮保存材料进行程序修复后的重评 | **12/18 离线通过**，`network_calls=0` | 这不是第二次真实运行，不改变第一轮的 9/18。汇总声明 `gold_modified=false`、`historical_live_modified=false`。 |
| 受影响离线回归 | 新契约、数学核心、出处、特征、工作流、录制与报告相关回归 | **389 项通过** | 来自主任务执行记录；不是新增模型样本。本文未把该数字记作真实 LLM 验收结果。 |
| `live-20261016-02` | 9 题 × 2 个新的真实样本，共 18 个样本 | **13/18 最终通过**；初次提取独立验收 **15/18** | 完整覆盖，冻结版本一致；初次提取统计不含原图 review 确认。正式通过为否。 |
| 出处验收协议 revision 2 | 依据九题原文独立重写 54 个数学证据组件 | 九题金标自验通过；相关 73 项确定性测试通过 | 属于验收协议与程序修订，不是新增真实样本。 |
| 第三轮前完整离线回归 | 新模块、数学核心及受影响工作流的完整回归 | **839 项通过，7 项跳过** | [执行日志](../../../../internal/solver-runs/graph-guided-stage-one/offline-final-20261016.log)；不是模型样本。 |
| `live-20261016-03` | v2 协议，9 题 × 2 个新的真实样本，共 18 个样本 | **17/18 最终通过**；初次提取独立验收 **15/18** | 完整覆盖、冻结一致。pytest 为 8 项通过、1 项失败，282.25 秒；唯一失败 Q08/02 漏转录逗号，正式通过为否。 |
| 第四轮前离线回归 | 含工具修复及全部 55 个历史录制样本回放 | **906 项通过，16 项跳过，1 项未选择** | [执行日志](../../../../internal/solver-runs/graph-guided-stage-one/offline-before-fourth-20261016.log)；未选择项是当时尚未满足的完整 18/18 成功批次 catalog 门禁，保留该要求，不作为当时通过。 |
| `live-20261016-04` | 同一冻结版本，9 题 × 2 个新的真实样本 | **18/18 最终通过**；初次提取独立验收 **16/18** | 9 个独立 pytest case 全部通过，285.99 秒；两次 repair 均发生在 Q08，`formal_passed=true`，人工 pending。 |
| 最终离线回归 | 全部 73 个录制样本禁网络回放、完整成功批次 catalog 及受影响程序回归 | **927 项通过，16 项跳过，无 deselected** | [执行日志](../../../../internal/solver-runs/graph-guided-stage-one/offline-acceptance-20261016.log)；完整成功目录门禁已纳入并通过。 |
| `replay-20261016-final` | CLI 从第四轮录制独立全量回放 | **18/18 离线通过，新语义调用及网络尝试均为 0** | 离线模式保持 `formal_passed=false`，不会把重放包装成新 live 验收。 |

第一轮原始材料：[汇总](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-01/batch-summary.json)、[离线 HTML 报告](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-01/index.html)、[受版本管理的录制入口](../../../../server/tests/solver/fixtures/graph-guided-stage-one/recorded/live-20261016-01/batch-summary.json)。探针材料：[汇总](../../../../internal/solver-runs/graph-guided-stage-one/q01-probe-20261016-01/batch-summary.json)、[报告](../../../../internal/solver-runs/graph-guided-stage-one/q01-probe-20261016-01/index.html)、[录制入口](../../../../server/tests/solver/fixtures/graph-guided-stage-one/recorded/q01-probe-20261016-01/batch-summary.json)。

离线重评依据：[独立汇总](../../../../internal/solver-runs/graph-guided-stage-one/offline-evaluation-20261016-fixes-01/summary.json)。该目录保存逐样本 `evaluation.json`，没有将离线通过结果回写历史 live 汇总。

## 第一轮逐样本记录

下表的调用数从每个样本 `workflow/ledger.json` 离线计数；耗时读取历史 `summary.json`。每个样本都包含一次新的 extract；全部 39 次语义调用有已完成的 provider 响应记录。模型请求和响应均记录为 `deepseek-flash`，provider 为 `deepseek`，图片传输为 `files`。

“最终 live”指历史独立验收结果，不等同于模型 review 返回确认。第一轮没有独立 `first_evaluation` 或 `first_passed` 记录，因此**不报告独立的首轮通过率**；“修复调用为 0”也不自动代表首轮正确。

| 题目 | 样本 | 最终 live | 修复后离线重评 | 语义调用 | review | repair | 历史耗时（秒） | 历史终态 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Q01 | 01 | 通过 | 通过 | 2 | 1 | 0 | 24.103 | reviewed_candidate |
| Q01 | 02 | 未通过 | 未通过 | 2 | 1 | 0 | 29.029 | reviewed_candidate |
| Q02 | 01 | 通过 | 通过 | 2 | 1 | 0 | 44.012 | reviewed_candidate |
| Q02 | 02 | 通过 | 通过 | 2 | 1 | 0 | 31.722 | reviewed_candidate |
| Q03 | 01 | 未通过 | 未通过 | 2 | 1 | 0 | 31.305 | reviewed_candidate |
| Q03 | 02 | 未通过 | 未通过 | 4 | 1 | 2 | 80.140 | workflow.budget_exhausted |
| Q04 | 01 | 通过 | 通过 | 2 | 1 | 0 | 24.168 | reviewed_candidate |
| Q04 | 02 | 通过 | 通过 | 2 | 1 | 0 | 31.972 | reviewed_candidate |
| Q05 | 01 | 未通过 | 通过 | 2 | 1 | 0 | 18.987 | reviewed_candidate |
| Q05 | 02 | 通过 | 通过 | 2 | 1 | 0 | 27.148 | reviewed_candidate |
| Q06 | 01 | 未通过 | 未通过 | 2 | 1 | 0 | 15.452 | reviewed_candidate |
| Q06 | 02 | 未通过 | 通过 | 2 | 1 | 0 | 70.690 | reviewed_candidate |
| Q07 | 01 | 通过 | 通过 | 2 | 1 | 0 | 43.052 | reviewed_candidate |
| Q07 | 02 | 未通过 | 通过 | 2 | 1 | 0 | 40.688 | reviewed_candidate |
| Q08 | 01 | 未通过 | 未通过 | 2 | 1 | 0 | 48.883 | reviewed_candidate |
| Q08 | 02 | 未通过 | 未通过 | 2 | 1 | 0 | 32.514 | reviewed_candidate |
| Q09 | 01 | 通过 | 通过 | 2 | 1 | 0 | 38.420 | reviewed_candidate |
| Q09 | 02 | 通过 | 通过 | 3 | 1 | 1 | 72.414 | reviewed_candidate |

合计：18 次 extract、18 次 review、3 次 repair，共 **39 次语义调用和 39 次推理网络尝试**，另有 **8 次文件 API 调用**。这些调用类型分别统计，文件上传不计为语义调用。已记录输入 token 为 239,793，输出 token 为 121,119，其中 reasoning token 为 115,282；这些数值是 provider 记录的计量，不是费用估算。

历史样本耗时 P50 为 **32.243 秒**，最大为 **80.140 秒**。此统计沿用第一轮历史计时：包括请求准备、传输与模型工作流，尚未包含最后一段特征计算、独立验收及产物保存；provider 排队与模型执行时间未单独提供。顶层汇总未记录整批墙钟耗时，不能把各样本耗时之和当成并发批次实际用时。

## 第一轮失败与离线修复边界

第一轮失败包含出处覆盖缺失、显式目标实数域遗漏、量词和命题为真的证据不足，以及题文排版归一问题。Q03 样本 02 使用了两次 repair 后耗尽内容调用预算，最后未获得原图确认。**Q08 的额外全局 y 定义问题发生在第二轮 Q08/02，不属于第一轮**；第一轮 Q08/01 缺量词出处，Q08/02 缺显式目标实数域。

离线修复新增通过的是 Q05/01、Q06/02、Q07/02；其余六个离线失败样本仍保留诊断：

| 样本 | 离线重评仍未满足的要求 |
| --- | --- |
| Q01/02、Q03/01、Q08/02 | 显式目标实数域缺失：`source.missing_explicit_target_domain` |
| Q03/02 | 默认域约定覆盖了原题明确的实数声明：`source.default_overrides_explicit_real`；原图 review 未确认 |
| Q06/01 | 缺少“为真命题”的出处支持：`source.missing_truth_assertion` |
| Q08/01 | 缺少量词语义所需的出处支持：`source.missing_quantifier_evidence` |

程序修复后的重评只说明同一份录制材料在当时修复版本下的结果，不能据 12/18 离线结果宣称达到正式通过门槛。第二轮另行运行了新的 18 个真实样本，其结果如下。

## 第二轮逐样本记录

第二轮材料：[统一汇总](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-02/batch-summary.json)、[离线 HTML 报告](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-02/index.html)、[受版本管理的录制入口](../../../../server/tests/solver/fixtures/graph-guided-stage-one/recorded/live-20261016-02/batch-summary.json)。汇总记录 `complete=true`、`formal_complete=true`、`single_frozen_version=true`、`formal_passed=false`。18 个样本的实现指纹均为 `ef72c7230f87dd95c2a5afaee56790e453907e8077f7003848ae274ba73d276b`，且 `implementation_unchanged=true`。

初次提取成绩来自每个样本独立保存的 `first-evaluation.json`，均明确记录 `source_reviewed=false`、`source_review_required=false`；它衡量初次提取的题意、出处和特征，不表示已通过原图复核。最终成绩要求有效原图复核，并采用当批冻结的 v1 验收规则。第二轮初次提取为 **15/18**，最终为 **13/18**，两者不能混用。

| 题目 | 样本 | 初次提取独立验收 | 最终 live | 语义调用 | review | repair | 耗时（秒） | 终态 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Q01 | 01 | 通过 | 通过 | 2 | 1 | 0 | 41.228 | reviewed_candidate |
| Q01 | 02 | 通过 | 通过 | 2 | 1 | 0 | 25.754 | reviewed_candidate |
| Q02 | 01 | 通过 | 通过 | 2 | 1 | 0 | 69.344 | reviewed_candidate |
| Q02 | 02 | 通过 | 通过 | 2 | 1 | 0 | 46.229 | reviewed_candidate |
| Q03 | 01 | 通过 | 通过 | 2 | 1 | 0 | 50.594 | reviewed_candidate |
| Q03 | 02 | 通过 | 通过 | 2 | 1 | 0 | 33.675 | reviewed_candidate |
| Q04 | 01 | 通过 | 通过 | 2 | 1 | 0 | 23.721 | reviewed_candidate |
| Q04 | 02 | 通过 | 通过 | 2 | 1 | 0 | 45.967 | reviewed_candidate |
| Q05 | 01 | 未通过 | 未通过 | 2 | 1 | 0 | 43.881 | reviewed_candidate |
| Q05 | 02 | 未通过 | 未通过 | 2 | 1 | 0 | 53.928 | reviewed_candidate |
| Q06 | 01 | 通过 | 通过 | 2 | 1 | 0 | 51.278 | reviewed_candidate |
| Q06 | 02 | 通过 | 通过 | 2 | 1 | 0 | 77.602 | reviewed_candidate |
| Q07 | 01 | 通过 | 未通过 | 2 | 1 | 0 | 41.213 | review.invalid_response |
| Q07 | 02 | 通过 | 通过 | 2 | 1 | 0 | 39.265 | reviewed_candidate |
| Q08 | 01 | 通过 | 通过 | 2 | 1 | 0 | 69.642 | reviewed_candidate |
| Q08 | 02 | 未通过 | 未通过 | 5 | 2 | 2 | 122.936 | reviewed_candidate |
| Q09 | 01 | 通过 | 未通过 | 5 | 2 | 2 | 88.604 | reviewed_candidate |
| Q09 | 02 | 通过 | 通过 | 2 | 1 | 0 | 77.522 | reviewed_candidate |

合计 **18 次 extract、20 次 review、4 次 repair**，共 **42 次语义调用和 42 次推理网络尝试**。文件 API 调用为 **0**：使用已上传图片的文件缓存，不代表复用了模型推理结果。provider 记录输入 token **265,060**，输出 token **181,126**，其中 reasoning token **173,864**。样本耗时 P50 为 **48.412 秒**，最大 **122.936 秒**；此轮计时包括末段特征计算、独立验收和保存。整批墙钟耗时未提供，仍不能将样本耗时相加作为并发批次用时。

## 第二轮失败原因与修订边界

| 样本 | 已保存材料中的失败 | 判断及处理方向 |
| --- | --- | --- |
| Q05/01、Q05/02 | 数学题意、特征和原图 review 均通过；`source_coverage.missing_evidence` 要求覆盖整句“关于 x 的不等式…有解”。实际 anchors 已覆盖 `1<x<2`、`x²+mx+4>0` 和“有解”。 | v1 出处判据把叙述前缀当成必要数学信息，属于验收程序误拒。采用下述统一 v2 协议，不按单题增加中文删除词。 |
| Q07/01 | 初次提取正确；review 返回 `status/findings` 之外还携带 `original_text/root/source_annotations/conventions`，终态为 `review.invalid_response`。 | 模型复核输出违反契约，不能把其中的 confirmed 当成有效确认。复核提示已明确只返回 `status/findings`。 |
| Q08/02 | 最终量词关系已展开，但另有全局 `definitions: [y=m*x²-m*x-6+m]`；独立语义比较不等价。两次 repair 与两次 review 未消除额外定义。 | 属于提取与复核遗漏：全局定义中的 m 是自由变量，不能当作量词内部别名。本问题属于第二轮。程序应检查作用域，原 y 公式保留在转录与量词关系的出处中。 |
| Q09/01 | 初次提取已将公式正确展开到 `∀a` 内；review 错误要求增加全局 y 定义并把事实改回 `∀a∈[-1,1]: y>0`。最终题意不等价，多个结构特征变为 unknown。 | 复核导致错误修改。保留量词内展开及定义、原关系两处出处；不能因省去全局 y 定义而判为信息遗漏。新的作用域校验和复核约束需由新真实批次验证。 |

对应证据可从第二轮报告进入各样本的 `evaluation.json`、`candidate.json` 和 `workflow/calls/`；Q09/01 的错误复核要求保存在 `workflow/workflow-result.json` 的第 2 次调用事件中。以上模型缺陷与 v1 判据误拒分开记录，不把五个失败全部归因于模型。

## 出处验收协议 revision 2

第二轮完整结束并录制后，将九题的 `acceptance.json` 从 `graph-stage-one-acceptance/v1` 统一修订为 `graph-stage-one-acceptance/v2`。修订依据为各题原文与独立数学金标；全部九题使用同一原则重新编写，共 **54 个组件**，并由另一实现者复核协议与程序的一致性。

`required_evidence_components` 每项指定 `target_path`、`kind` 和 `alternatives`：所有组件都必须满足；同一组件的 alternative 可择一；一个 alternative 中的每段 quote 都必须覆盖。组件种类为 `domain/relation/quantifier/definition/truth_assertion/goal_target/goal_kind`。引用先限制在该数学条目的金标出处窗口，再比较候选自身规范显示后的原文位置；不能借用公式里的同名字母支持目标。

范围端点与开闭、完整关系式及严格性、量词、真值和必要定义仍不可遗漏。Q02/Q03 未明写的量词变量和实数域通过已声明且由程序验证的约定验收；Q08/Q09 的 y 定义和原不等式必须分别有证据；Q06 要求“真命题”真值证据，系词“为／是”不作为独立数学信息。连接词及“求”不单独成为验收条件。

此次只修订出处验收协议及相应校验程序，九题共 45 个原文、图片、数学题意金标、出处上下文金标与特征金标文件的哈希保持不变。历史 v1 分支、第二轮录制中的旧验收文件及两个 live 批次结果保留。每题 `source-manifest.json` 的 `gold_revision.history`、`previous_acceptance_sha256` 以及 `acceptance.json` 的 `revision_history` 记录旧新版本及旧录制路径。验收文件 SHA-256 如下：

| 题目 | v1 SHA-256 | v2 SHA-256 |
| --- | --- | --- |
| Q01 | `92a5b100173842bf0db22fd2b72ba5f3d7ead177737e419b27ec35b49d2db8b8` | `5c8a2be1d4bc9caba65debaebc89d35dc0de5bbd3c46f0ec260fc11598a2252d` |
| Q02 | `5ed938d8ec24d1a5d8f0fdbf9030fb0c79bf19d7d6f9470fe2a0cd874614fc03` | `4228ce99225d9cf55c369b45fdae7393f56bf22dc70fcbb39a0ba236951ffb3e` |
| Q03 | `a992e54322ca8862aa6ca2c9468f9087f2d476f4abebe47b5e981e97b5c48740` | `90cc3e2fc7756edeeeb34e5d8ab5c69bd28c3dd18c39729c69208ecb87faecde` |
| Q04 | `322da39c8f601f453cae078621067f270ab1fed1c0de6b6e1652d896d57a3ae4` | `e430ec48614cf1d1f1a442ca4c3b64482cfa75d8fa465e5e31aba6c95a6c5767` |
| Q05 | `8b88ec2364e9452ea0fb81a2f2e12dccaa855135379c1a252ec8995ef265b805` | `f61ab5311226062acacb7406eb23c508cffced176005db007e3e90aaff6fbce4` |
| Q06 | `aa4e79a41592bb4bc6f502ffb1b4794f2f2b6ef9045a23e2c21d6110c0a8d00d` | `620d0faa4d3f030d730fd311b907cafbee6c2dd5c30c2ee5a2eb7dd30b214166` |
| Q07 | `9e92bbd206105f7e46072d67a9cdda730d2c10837fbf82645e3401a89ab57f06` | `84c8823f4b2c9628d83d3175ca44bb85031855d4a93aac3d20bb4a9778ef0300` |
| Q08 | `a5f8dd6ba4e2f10ec611c7a32d9194d2fc4d78880904f8634788a271a5c1ee7b` | `d977070df69aa1c78aa795d4dce9d7f5f4e212a8b72c85799a85cb56075c4db8` |
| Q09 | `64555f76464c6cfb5a17fea2747980999ccbbc566c3104c521a02d68ccd9daef` | `d8b6bfef24979cfd83e29e88449e73a6b8b055fd2abef1e0f07b005030e2639a` |

v2 语料 manifest SHA-256 为 `61aa7bbfdf1d672f814b516aa4d522ad5643c71ceff8d595da284332f53dbbb8`。预检已检查所有组件和 alternative 的合法性及原出处，九题金标自验通过；这些确定性检查不表示新版本已通过真实 LLM 验收。

## 第三轮逐样本记录

第三轮材料：[统一汇总](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-03/batch-summary.json)、[离线 HTML 报告](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-03/index.html)、[受版本管理的录制入口](../../../../server/tests/solver/fixtures/graph-guided-stage-one/recorded/live-20261016-03/batch-summary.json)。18 个独立真实样本均已完成，`complete=true`、`formal_complete=true`、`single_frozen_version=true`、`formal_passed=false`。所有样本的实现指纹均为 `0fb792a85572da3a5b0b83e772a6b7e461f925950a6c50faa47b3da407679248`，`implementation_unchanged=true`，采用冻结的 v2 验收文件。第三轮已完整导出，并计入上述 55 个历史样本的零网络回放；历史 17/18 保持不变。

初次提取的 **15/18** 来自保存的 `first-evaluation.json` 和 `first_passed`，不含原图 review 确认。Q04/02 与 Q08/01 各发生一次 repair，最终通过；其余 16 个样本没有 repair，其中 Q08/02 最终仍未通过。全部样本的工作流终态均为 `reviewed_candidate`、`source_reviewed=true`，但这不能替代独立验收。

| 题目 | 样本 | 初次提取独立验收 | 最终 live | 语义调用 | review | repair | 耗时（秒） |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| Q01 | 01 | 通过 | 通过 | 2 | 1 | 0 | 23.063 |
| Q01 | 02 | 通过 | 通过 | 2 | 1 | 0 | 36.574 |
| Q02 | 01 | 通过 | 通过 | 2 | 1 | 0 | 43.650 |
| Q02 | 02 | 通过 | 通过 | 2 | 1 | 0 | 26.626 |
| Q03 | 01 | 通过 | 通过 | 2 | 1 | 0 | 39.939 |
| Q03 | 02 | 通过 | 通过 | 2 | 1 | 0 | 42.671 |
| Q04 | 01 | 通过 | 通过 | 2 | 1 | 0 | 27.321 |
| Q04 | 02 | 未通过 | 通过 | 3 | 1 | 1 | 57.135 |
| Q05 | 01 | 通过 | 通过 | 2 | 1 | 0 | 23.424 |
| Q05 | 02 | 通过 | 通过 | 2 | 1 | 0 | 31.042 |
| Q06 | 01 | 通过 | 通过 | 2 | 1 | 0 | 48.302 |
| Q06 | 02 | 通过 | 通过 | 2 | 1 | 0 | 40.692 |
| Q07 | 01 | 通过 | 通过 | 2 | 1 | 0 | 44.697 |
| Q07 | 02 | 通过 | 通过 | 2 | 1 | 0 | 44.692 |
| Q08 | 01 | 未通过 | 通过 | 3 | 1 | 1 | 96.750 |
| Q08 | 02 | 未通过 | 未通过 | 2 | 1 | 0 | 53.380 |
| Q09 | 01 | 通过 | 通过 | 2 | 1 | 0 | 35.511 |
| Q09 | 02 | 通过 | 通过 | 2 | 1 | 0 | 48.780 |

逐样本账本合计 **18 次 extract、18 次 review、2 次 repair**，共 **38 次语义调用和 38 次推理网络尝试**，38 次均保存 completed 响应。文件 API 调用为 **0**，图片使用已上传文件缓存；这不复用模型推理结果。全部响应记录 provider 为 `deepseek`、请求与响应模型均为 `deepseek-flash`、图片传输为 `files`、`finish_reason=stop`。输入 token 为 **243,072**，输出 token 为 **146,960**，其中 reasoning token 为 **141,590**。

样本耗时 P50 为 **41.682 秒**，最大 **96.750 秒**。批次 `batch-summary.json` 记录会话墙钟时间 **280.710 秒**；主任务的 pytest 执行记录为 **8 passed、1 failed，282.25 秒**。两者计时边界不同，分别列出；不把样本耗时之和视为批次用时。

## 第三轮修复、唯一失败与后续边界

| 样本 | 原始问题 | 本轮处理与最终结果 |
| --- | --- | --- |
| Q04/02 | 对原文已明确的内容使用默认域约定，程序返回 `source.convention_overrides_explicit_source`。 | 一次 repair 修正约定，再由原图 review 确认，最终独立验收通过。 |
| Q08/01 | 顶层全局 y 定义依赖量词变量 m，程序返回 `scope_policy.quantifier_dependent_alias`。 | 一次 repair 处理量词依赖别名，保留定义与原关系两处出处；最终数学、来源及特征通过。 |
| Q08/02 | 数学语义、候选自身的 `source_map` 和结构特征均通过；`original_text` 把“恒成立，求”转录为“恒成立”后换行接“求”，实际漏掉逗号。 | 原图 review 未发现漏标点，未触发 repair。严格转录比较 `transcription.ok=false`；依赖规范全文一致性的 `source_coverage.ok=false`，最终未通过。 |

Q08/02 的[候选](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-03/q08/q08/sample-02/candidate.json)和[独立验收](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-03/q08/q08/sample-02/evaluation.json)保留原样。主任务与契约实现者的 Codex 视觉核对均确认原图第二行的“立，求”中逗号清晰可见；不是图片缺字，也不是只改变换行。出处覆盖中七个组件均显示 false，是**规范全文一致性前置条件失败的连带结果**，不能解释成七处数学引文都不存在；候选自身的锚点绑定仍为 true。

第四轮前已加强提取与复核的通用标点保留提示。三个离线工具问题已另行修复：回放保留历史批次的预期题目和样本数，不能把未完成批次缩成当前已有样本；已有账本但终态落盘失败时，录制保留 failure/preflight，回放先核验调用哈希再保留失败；顶层汇总缺失或损坏时，报告能发现 pytest 的 `qNN/qNN/sample-NN` 嵌套样本。修复后的局部检查有 **58 passed** 和新旧工作流 **148 passed**；第三轮导出后的相关完整离线回归为 **906 passed、16 skipped、1 deselected**，包含当时全部 55 个历史样本零网络回放。唯一未选择项是当时尚未满足的完整 18/18 成功批次 catalog 门禁，该要求未删除，已在第四轮后的最终回归中通过。所改模块 Ruff 检查通过，不表示全仓 lint 通过。

成功重试响应中异常元数据脱敏也已补强：`metadata.provider_attempts` 应用既有白名单，避免先失败后成功时把 SDK 异常串或敏感字段写入录制和报告；模型正文、总 usage 与调用计数不变。实现任务报告新增字典与 typed 两种重试响应回归，共享 workflow/provider/files 检查 **185 passed**、所改文件 Ruff 检查通过；这组验证单独列出，不沿用修改前的 906 项作为新修订结论。主任务只读扫描现有 121 份真实响应，没有非空 `error_message`，历史响应不改写。

上述提示与工具修复均不放宽原文或 v2 金标，不把 Q08/02 改记为通过，也不改写第三轮冻结记录。离线测试通过不是新增真实调用成绩。

## 第四轮逐样本记录

第四轮材料：[统一汇总](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-04/batch-summary.json)、[离线 HTML 报告](../../../../internal/solver-runs/graph-guided-stage-one/live-20261016-04/index.html)、[受版本管理的录制入口](../../../../server/tests/solver/fixtures/graph-guided-stage-one/recorded/live-20261016-04/batch-summary.json)。本轮是九题各两个全新的真实图片样本，没有从历史批次挑选结果拼接。汇总记录 `complete=true`、`formal_complete=true`、`formal_passed=true`、`single_frozen_version=true`。18 个样本的实现指纹均为 `fcea9dc8d9379ff5462defdbdc359a97dde4140bba74c731b25660276e3bb302`，且 `implementation_unchanged=true`，沿用同一 revision 2 金标。

初次提取独立验收为 **16/18**。Q08/01、Q08/02 均因多余的量词依赖全局 y 别名被 `scope_policy.quantifier_dependent_alias` 检出，各经过一次 repair 后通过；其余 16 个样本首轮独立验收通过且无 repair。全部 18 个最终候选获得有效原图 review，并通过题文、数学语义、出处覆盖、约定与必需特征的独立验收。

| 题目 | 样本 | 初次提取独立验收 | 最终 live | 语义调用 | review | repair | 耗时（秒） |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| Q01 | 01 | 通过 | 通过 | 2 | 1 | 0 | 41.749 |
| Q01 | 02 | 通过 | 通过 | 2 | 1 | 0 | 36.816 |
| Q02 | 01 | 通过 | 通过 | 2 | 1 | 0 | 66.741 |
| Q02 | 02 | 通过 | 通过 | 2 | 1 | 0 | 22.326 |
| Q03 | 01 | 通过 | 通过 | 2 | 1 | 0 | 29.549 |
| Q03 | 02 | 通过 | 通过 | 2 | 1 | 0 | 28.483 |
| Q04 | 01 | 通过 | 通过 | 2 | 1 | 0 | 49.435 |
| Q04 | 02 | 通过 | 通过 | 2 | 1 | 0 | 11.396 |
| Q05 | 01 | 通过 | 通过 | 2 | 1 | 0 | 54.660 |
| Q05 | 02 | 通过 | 通过 | 2 | 1 | 0 | 34.150 |
| Q06 | 01 | 通过 | 通过 | 2 | 1 | 0 | 38.551 |
| Q06 | 02 | 通过 | 通过 | 2 | 1 | 0 | 35.539 |
| Q07 | 01 | 通过 | 通过 | 2 | 1 | 0 | 58.648 |
| Q07 | 02 | 通过 | 通过 | 2 | 1 | 0 | 30.941 |
| Q08 | 01 | 未通过 | 通过 | 3 | 1 | 1 | 48.090 |
| Q08 | 02 | 未通过 | 通过 | 3 | 1 | 1 | 68.086 |
| Q09 | 01 | 通过 | 通过 | 2 | 1 | 0 | 43.345 |
| Q09 | 02 | 通过 | 通过 | 2 | 1 | 0 | 35.560 |

账本共 **18 次 extract、18 次 review、2 次 repair**，即 **38 次语义调用与 38 次推理网络尝试**，全部有 completed 响应；文件 API 调用 **0**，仅复用已上传图片文件。全部请求与响应模型均为 `deepseek-flash`，provider 为 `deepseek`，传输为 `files`，`finish_reason=stop`。输入 token **246,412**、输出 token **140,918**，其中 reasoning token **134,756**。

样本耗时 P50 为 **37.684 秒**（未舍入值 37.6835），最大 **68.086 秒**；批次汇总的会话墙钟时间 **284.391 秒**，pytest 九个独立 case 全通过，总时间 **285.99 秒**。首轮成绩不含原图 review 确认；最终通过包含原图 review 和程序独立验收。首批 18/18 是本次接入门槛通过，不代表已取得更大样本的可靠性结论。

## 最终录制、回放与完成边界

探针加四轮全部 **73 个样本**均保存在 `recorded/`，保留前三轮失败与第四轮成功。最终离线回归为 **927 passed、16 skipped，无 deselected**，包含全部录制样本的禁网络回放和单一冻结版本完整成功批次 catalog 门禁；后者已通过，没有通过删除或排除门禁获得完成状态。

另从第四轮录制运行 CLI 独立全量回放：[回放汇总](../../../../internal/solver-runs/graph-guided-stage-one/replay-20261016-final/batch-summary.json)、[回放报告](../../../../internal/solver-runs/graph-guided-stage-one/replay-20261016-final/index.html)。当前代码重评 **18/18 通过**，`new_semantic_calls=0`、`new_network_attempts=0`。回放的 `formal_passed=false` 是正确的离线模式标记；历史 live 的 `formal_passed=true` 与冻结记录分别保留，未被重写。

当前自动验收通过。最终 59 个冻结实现文件与第四轮 live 指纹一致，新增及相关文件 Ruff 检查、`git diff --check` 通过。Codex 已用真实 Chrome 检查正式报告首页与 Q08/02 的双出处高亮，未出现页面、控制台或请求错误，QA 前后检查的 51 个样本冻结 JSON 哈希保持一致；证据见 [检查记录](review-notes.md#codex第四轮真实报告浏览器-qa)。用户人工核对仍待完成。

阶段①完成还需用户填写人工核对记录；`human_review` 当前仍为 `pending`。Codex 的图片和浏览器检查见 [review-notes.md](review-notes.md)，不替代人工核对。

本目录只存验证说明与核对记录，不复制题图、HTML 或大体积运行材料。完整报告留在 `internal/solver-runs/`；可移植的最小录制材料位于 `server/tests/solver/fixtures/graph-guided-stage-one/recorded/`。
