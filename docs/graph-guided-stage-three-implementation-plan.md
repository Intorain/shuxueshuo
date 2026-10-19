# 图谱交互课程阶段③实现计划：选法评估、方法驱动求解与数学步骤逐步交付

> 状态：批次 1a、1b-1、1b-2 已实现；路线求解／验证隔离及中断预算恢复的历史验收见 12.2，隔离不包含入口题意准入、`build_context` 和 D3 选法。批次 1c 的本机开发拍题入口主链路已通过验收：持久流、D1–D4、Q01 双路线阅读及构造问答附加可用；审查前 Python 回归合计 923 passed、1 skipped，前端 93 passed。审查发现的状态轮询提前退出 P2 已修复，相关前端 102 项回归及浏览器复核通过；修复验收与剩余台账见 12.3。阶段④真实生成及正式学生服务的登录、归属与额度尚未完成。Demo 例外继续待人工确认，其余 P3 见 12.2、12.3（2026-10-19 修订）。
> 设计依据：[四阶段交互课程生成设计](graph-guided-interactive-lesson-design.md)第 6–9 节。
> 输入依据：[阶段②实现计划](graph-guided-stage-two-implementation-plan.md)。阶段③读取阶段②已确认归属的目标，不重新判型、不重新提取题意或计算阶段①特征。
> 执行器选择：在 `graph_lesson/stage_three` 新建轻量外层驱动器和能力函数，只复用 `math_kernel`、`notation_semantics` 里的纯代数部件；轨迹使用本阶段自己的契约，预留到 ExplanationSnapshot 的映射（第 9.4 节）。理由见第 1 节。
> 范围：选法评估（D3、D4）覆盖 Q01–Q11 全部已确认目标，并补入 Q13 参数最小值；路线执行先打通 Q01 的判别式法和分离参数法，再分批扩展到 Q02–Q09 的全部人工课程路线及 Q13 目标收束。每个有意义的数学步骤局部校验后即交付网页，包含稳定步骤 ID、标题、数学表达、条件依据和模板说明。分批验收见第 12 节。
> 阶段④边界：单条路线完整验证通过后，为其固定步骤补充学生可能的问题、提示和 AI 反馈；不再合并、拆分、重排步骤或改写数学正文。问答生成不阻塞阶段③步骤阅读，失败不改变数学路线结果。
> 本期阶段③不调用 LLM：已覆盖方法的计算、判断和数学步骤展示均由程序完成；需要启发式构造或尚不支持的判断报告能力缺口。阶段①识图与题意提取、阶段②多命中时的题型选择、阶段④教学问答仍承担相应 LLM 职责。

## 1. 目标与边界

阶段③对每个已确认目标做三件事：

1. **选法评估**：沿主要题型取得选法规则，对规则的全部分支分别给出触发、数学适用性、推荐状态和首轮路线计划，生成 D3（选法判断）和 D4（选择方法）片段。这是纯程序计算，不等待任何路线执行。
2. **方法驱动求解**：对计划生成的每条路线，由外层驱动器按方法执行契约逐步调用能力函数，记录轨迹，独立校验答案，输出每条路线的状态。
3. **数学步骤逐步交付**：方法契约与通用展示规则确定学生可读的步骤边界；每步局部校验后，持久化结果与事件并交付网页。单条路线完整验证通过后发布完成态及阶段④输入清单，不等待其他路线或教学问答。

```text
阶段②结果（goals[].status = resolved 的目标）
→ 输入准入；不合格则 input_error，停止
→ 每个目标：主要题型 → 节点 rules → 选法契约
   → 没有选法契约：unsupported_type（未收录题型）
→ 方法前提检查（与执行共用实现）→ 全部分支评估 → D3、D4
→ 计划生成的路线各自执行（只读共享原题，结果不跨路线混用）
   → 每步：执行契约 → 能力函数 → 局部检查 → 保存轨迹、上下文增量与事件
   → 生成可读数学片段 → WebSocket 推送或按游标增量读取；继续计算不等待浏览器
   → 判断节点：程序判定；需要 LLM 的节点本阶段报告为能力缺口
→ 合并全部可见题设约束，得到参数可行集
→ 独立校验可行集的正确性与完整性 → 按目标收束为范围或最值
→ 同一目标多条已验证路线的可行集与目标答案互相比较
→ 发布已验证路线的完成态与不可变快照 → 阶段④附加本路线各步骤的教学问答
→ 结果、轨迹、数学片段、持久事件、路线状态、调试报告
```

**为什么不接现有执行器。** 现有 `solver/runtime` 的 FunctionalPlan 面向具体题的类型化状态，没有量词、参数分类和“对参数求集合”的语义；把恒成立四种方法塞进去，需要同时改计划格式、状态类型和检查点，成本高于新建一个只服务图谱方法的驱动器。新驱动器只复用纯代数部件：`notation_semantics` 的 `Canonical`、`bounded_expand` 等表达式规范化与等价判断，`math_kernel` 中可直接调用的 SymPy 封装（实现前逐一核对 `sympy_kernel`、`quadratic_bound.verify_quadratic`、`reciprocal_bound.verify_reciprocal`，能用则用，不能用不强行适配）。不修改现有执行器，不改它的控制流。

本阶段做：

- 选法契约 `rule-quadratic-method`，四个分支的触发、适用性、推荐和路线计划规则；方法前提检查。
- 四个方法及其子方法的执行契约；公共技能到内部能力的映射表；运算到知识依据的映射表。
- 外层驱动器：方法实例、步骤、条件调用、判断节点、子方法调用栈、分类讨论分支。
- 能力函数（SymPy，精确算术），按批次补齐。
- 目标作用域内完整题设的约束上下文；参数可行集到范围、最小值、最大值的目标收束。
- 轨迹契约、路线答案独立校验、失败分类、D3/D4 片段、离线调试报告与 CLI。
- 通用数学步骤展示注册表、稳定步骤 ID、单片段编译、持久事件与恢复快照，以及网页逐步展示和 WebSocket／游标轮询接线。
- 对阶段④的交接契约：已验证路线快照、固定步骤清单与内容哈希；问答作为独立附加片段挂到原步骤。

本阶段不做：学生可能问题、引导问题和 AI 反馈的 LLM 生成（阶段④），任意实时导师对话，LLM 判断节点的真实调用，基本不等式题，前问结论供后问使用（Q10、Q11 的小问彼此独立，不需要），`method-parameter-quadratic-cases`（含参二次不等式求解，属另一题型）。数学步骤边界、模板说明与逐步交付属于本阶段，不再推迟给阶段④。

## 2. 输入

正常输入是阶段②的 `stage-two-result.json`（`graph-stage-two-result/v1`）。入口检查：

1. 通过阶段②结果 Schema 与 `stage_two.contracts.validate_result`；契约缺失或版本不支持时拒绝。
2. `status ∈ {completed, partial}`；`input_error`、`failed` 拒绝。
3. 阶段①结果优先读取阶段②结果同目录的 `input.json`（阶段②每次运行都保存其输入副本），按阶段②相同的 `identity.revision` 规则与 `stage_one.sha256` 核对，并再次通过阶段②的 `validate_input`。`stage_one.reference` 是阶段②调用方传入的原始路径（批次中通常相对 `server/` 工作目录，回放时为录制目录），只作出处记录，不按阶段②结果所在目录解析；同目录 `input.json` 缺失时才尝试 `reference`：绝对路径直接读取，相对路径须由调用方显式给出基准目录，否则 `input_error`。准入策略继承阶段② `options.admission`；旧结果缺省为 `acceptance`，非法值拒绝。`student_upload` 沿用学生上传的验证要求，不补造 `evaluation/passed`。阶段③从该文件读取候选题意和按 `target_ref` 分组的特征，不信任阶段②结果里的任何特征副本。
4. 阶段②每个目标的 `target_ref` 都能在阶段①候选中解析。

任一检查失败：顶层 `status=input_error`、`goals=[]`，`input_diagnostics` 定位到字段；不做选法评估和求解。调试报告仍可打开。

阶段③保存的 `stage-two-input.json` 同样可直接作为新运行输入。此时同目录 `input.json` 是 `graph-stage-three-input-manifest/v1` 出处清单，入口识别清单后，核对其阶段②哈希与当前输入、阶段①哈希与阶段②出处、准入策略与当前策略，再读取清单指定的 `stage-one-input.json`。快照路径必须位于清单所在目录内，禁止绝对路径、目录逃逸及符号链接逃逸。兼容首版 1a 未带 `contract` 但具有完整双快照元数据的清单；清单损坏或其引用的快照缺失／损坏时，不得回退到历史引用。

逐目标准入：只有 `status=resolved` 的目标进入阶段③；`unsupported`、`selection_failed` 的目标在结果中保留为 `skipped`，带阶段②状态，不生成 D3/D4。`primary_source` 为 `program` 或 `llm` 一视同仁。

本阶段读取的阶段①特征：`quantifier`、`bound_vars`、`free_vars`、`goal`、`domain`、`domain_kind`、`relation`、`normal_form`、`degree_in_bound`、`degree_in_goal`、`leading_coeff_in_bound`、`coefficients`、`range_var_is_principal`。特征里的表达式字符串用阶段①特征计算时的同一解析入口转成 SymPy，不另写解析器。特征为 `unknown` 时，依赖它的检查结论为 `unknown`，不能当成不成立。

**特征不是完整题设。** 驱动器还必须从候选题意建立 `constraint_context`：收集目标所在 scope 及祖先 scope 的全部可见事实、定义和符号定义域，保留各自 `source_ref`；不读取兄弟小问，也不把量词内绑定的变量当作全局自由变量。为每项记录处理方式：展开的定义、主量词关系、参数限制、已证明冗余或不支持；任何题设都不能仅因未出现在特征 `source_refs` 中而丢弃。

方法先求主量词关系的参数集合，再与完整上下文中的参数限制求交。其他量词关系或涉及额外自由变量的条件，若没有已注册能力处理，则为 `capability_gap`（`unsupported_constraint`），不得忽略后标为 `verified`。例如 `a<1` 与 `∀x∈ℝ:x²+a≥0` 的最终可行集必须是 `[0,1)`，独立验证也使用这两项原始条件。`goal.kind` 保留 `find_range/find_minimum/find_maximum`；本期极值目标仅支持单个实数符号，不能把最值目标改写成范围目标后直接结束。

测试输入分四路，都不新增 LLM 调用：

- **金标路径**：从 11 题 `notation.gold.json` 计算完整特征，先与 `features.gold.json` 作语义子集断言，再经阶段②内部判型进入阶段③评估与驱动器；完整约束上下文取自同一题意金标。`features.gold.json` 是断言子集，不能直接当生产特征输入，也不能替代题设。
- **录制路径**：阶段①录制 `recorded/live-v2-20261017-02` 的 22 个候选，先由阶段②离线批次（验证关闭）生成阶段②结果，再通过上面的对外入口进入阶段③。共 24 个已确认目标，两个 Q11（1）样本为 `skipped`。阶段②批次产物位于 gitignore 目录，测试中现场生成，不入库。
- **LLM 归属路径**：阶段② Q01 真实选择录制 `q01-20261018-02` 零网络回放后的结果（`primary_source=llm`），确认阶段③对 LLM 确认的归属同样准入。
- **学生上传极值路径**：复用 `server/tests/search/fixtures/parameter-extremum/recorded-20261018` 的 Q13 真实提取与复核证据，重新校验录制、计算特征并生成 `student_upload` 阶段②结果，再进入阶段③；不把它混入上述 22 份验收录制计数。

## 3. 选法契约与分支评估

### 3.1 契约位置与格式

选法契约放在 `site/data/knowledge-next/selection/`，一份规则节点一份，文件名与规则节点 ID 相同（首份为 `rule-quadratic-method.json`）。入口由主要题型节点的 `rules` 字段决定；`type-quantified-quadratic` 的 `rules` 为 `["rule-quadratic-method"]`。节点 JSON 只保留学生可读的 `condition` 文字，可执行规则写在契约里，与阶段②识别契约分离的理由相同。

每个分支在契约中声明：

| 字段 | 内容 |
| --- | --- |
| `branch`、`target` | 与规则节点 `branches[].id/target` 一致，测试校验 |
| `route_id` | 该分支生成路线的 ID，显式声明，不从分支名推导：`discriminant→discriminant`、`interval→interval`、`separation→extremum`、`swap→variable`；与 `topics/quadratic-always.json` 人工路线 ID 一致，没有人工课程的目标（Q10、Q11（2）、Q13）同样使用 |
| `trigger` | 只读阶段①特征的触发条件（如判别式法：`quantifier=∀`、`domain_kind=real`、`degree_in_bound.degree=2` 且 `range_var_is_principal=true`） |
| `premises` | 依次运行的方法前提检查及期望结论（见 3.3） |
| `plane` | 该方法在 D3 方法坐标图上的典型格子，只用于教学展示“这类方法通常用于哪类题”；本目标格子里可选的方法由第 4 节按分支结论计算，不直接取这里的静态覆盖 |
| `messages` | D3 结论的学生措辞模板，占位符只能引用检查的绑定值 |

契约顶层另有 `plane_axes`（横轴 `domain_kind` → `real/interval`，纵轴 `range_var_is_principal` → `free/given`）与 `recommendation`（3.4 的有序策略）。

### 3.2 每个分支的四项结论

| 结论 | 取值 | 来源 |
| --- | --- | --- |
| 触发 `trigger` | `triggered` / `not_triggered` / `unknown` | 只读特征 |
| 适用性 `applicability` | `applicable` / `not_applicable` / `unknown`；未触发时为 `null` | 方法前提检查 |
| 推荐 `recommendation` | `preferred` / `optional` / `superseded`；不适用或未触发时为 `null` | 3.4 推荐策略 |
| 路线计划 `route_plan` | `planned` / `capability_gap` / `not_planned` | 执行契约与能力注册表 |

三条约束沿用设计文档第 6.1 节：推荐和路线计划不能改写适用性；未触发不等于数学上不可行，措辞写“本选法分支未触发”；能力缺口不影响 D3 中“可用”的结论。

`not_applicable` 只在前提检查得到明确的反面结论时给出，并带证据（例如除数在定义域内变号的两个取值点）。检查超出能力范围时给 `unknown`，`unknown` 分支在 D3 中不作为可选方法，只进调试报告。

`route_plan=planned` 的条件：分支适用且推荐不是 `superseded`，方法有执行契约，并且本题需要的能力（函数类别、量词组合、可见约束、完整性验证与目标收束）都已注册；缺能力为 `capability_gap`，带缺失能力 ID。已计划的路线仍可能在实际计算时发现缺口，不能把注册等同于计算成功。被 `superseded` 的分支 `not_planned`，与 Demo 中 Q01 区间最值法“数学可行但不生成独立路线”一致。

### 3.3 方法前提检查

前提检查放在 `stage_three/premises.py`，与执行时同名能力共用实现，结论为 `holds` / `fails` / `unknown`，附绑定值和证据。

| 检查 | 用于 | 内容 |
| --- | --- | --- |
| `degenerate_branches` | 判别式法 | 关于量词变量的二次项系数可否为 $0$；可以时给出使其为 $0$ 的参数值集合（Q02：$k=0$；Q03：$a=\pm1$） |
| `param_separable` | 分离参数法 | 能否整理成 $h(\text{参数})d(x)\ \square\ g(x)$ 的形式，参数只出现在 $h$ 中；Q01 已分离（$d=1$），Q03 中 $a^2$、$a$ 分别乘 $x$ 的不同次幂，不可分离 |
| `divisor_sign` | 分离参数法 | 需要除以的 $d(x)$ 在定义域上的符号：恒正 / 恒负 / 变号或可为 $0$；变号时不适用，证据为两个异号取值点 |
| `extremum_computable` | 区间最值法 | 关于量词变量的函数属于二次、一次或对勾类，能在该定义域上求最值（可能需要分类） |
| `interval_case_split` | 推荐策略 | 区间最值法是否需要按参数分类：首项系数符号不定，或在非全实数区间内，所需最值是顶点型（开口向上求最小值、开口向下求最大值）且对称轴含参数；全实数域无需按对称轴位置分类 |
| `swap_linearity` | 更换主元法 | 按给出范围的字母整理后次数不超过 $1$；一次项系数关于要求字母的符号判断留给执行时的判断节点 |

### 3.4 推荐策略

推荐策略写成契约中的有序规则，程序逐条应用，第一条匹配即定：

1. 判别式法适用：判别式法 `preferred`；区间最值法若适用则 `superseded`（$\mathbb R$ 也是区间，但判别式法更直接）；分离参数法若适用则 `optional`。
2. 更换主元法适用：更换主元法 `preferred`。
3. 定义域不是 $\mathbb R$：区间最值法不需要分类时 `preferred`、分离参数法 `optional`；需要分类且分离参数法适用时，分离参数法 `preferred`、区间最值法 `optional`；需要分类但分离参数法不适用时，区间最值法 `preferred`。
4. 只有一个分支适用：该分支 `preferred`。

其余多个分支同时适用时，按契约声明的固定方法优先序（判别式、更换主元、区间最值、分离参数）选一个 `preferred`，其余 `optional`，并记录命中的兜底规则；例如全实数上的存在问题不能使用第 1 条，应在适用方法中优先区间最值。优先序不依赖题号，也不能使未触发或不适用分支被选中。

第 3 条是从九份人工课程的路线顺序归纳出的可计算规则，按 3.5 的金标逐题核对；与人工原稿不一致时先改规则，不为个别题打补丁。

没有任何分支适用（全部未触发、不适用或未知）时，不设 `preferred`，目标状态为 `no_applicable_method`，带各分支结论与原因；不生成 D3/D4 学生片段，调试报告照常展示分支评估。这不是执行失败，不影响顶层 `completed`。

### 3.5 选法金标

下表由各题原文、人工课程（`/2/q01/`–`/2/q09/`）和 Demo 原稿独立编写，冻结为 `selection.gold.json`。“可选/优先/不优先”均指“可用”。路线列为 `topics/quadratic-always.json` 中人工课程已有的路线。

| 目标 | D3 格子 | 判别式法 | 区间最值法 | 分离参数法 | 更换主元法 | 计划路线 |
| --- | --- | --- | --- | --- | --- | --- |
| Q01 | real, free | 优先 | 不优先 | 可选（已分离，无需除法） | 未触发 | discriminant、extremum |
| Q02 | real, free | 优先（退化 $k=0$） | 不优先 | 不适用（$x^2+2x-1$ 在 $\mathbb R$ 上变号） | 未触发 | discriminant |
| Q03 | real, free | 优先（退化 $a=\pm1$） | 不优先 | 不适用（参数不可分离） | 未触发 | discriminant |
| Q04 | interval, free | 未触发 | 优先（开口向上求最大值，在端点） | 可选（除以 $x>0$） | 未触发 | interval、extremum |
| Q05 | interval, free | 未触发 | 优先（同上；开区间最大值取不到） | 可选（除以 $x>0$） | 未触发 | interval、extremum |
| Q06 | interval, free | 未触发 | 可选（对称轴 $-\frac a2$ 需分类） | 优先（除以 $x<0$，不等号反向） | 未触发 | extremum、interval |
| Q07 | interval, free | 未触发 | 可选（首项系数 $m$ 需分类） | 优先（$x^2-x$ 在 $[2,3]$ 上为正） | 未触发 | extremum、interval |
| Q08 | interval, given | 未触发 | 未触发 | 未触发 | 优先 | variable |
| Q09 | interval, given | 未触发 | 未触发 | 未触发 | 优先 | variable |
| Q10（1） | real, free | 优先 | 不优先 | 不适用（除数 $x$ 变号且可为 $0$） | 未触发 | discriminant（扩展） |
| Q10（2） | interval, free | 未触发 | 可选（对称轴 $a$ 需分类） | 优先（除以 $x>0$） | 未触发 | extremum、interval（扩展） |
| Q11（2） | interval, free | 未触发 | 可选（首项系数 $m$ 需分类） | 优先（$x^2-x+1>0$） | 未触发 | extremum、interval（扩展） |

Q08、Q09 中前三个分支以给出范围的字母为主元，而本题给出范围的是 $m$（或 $a$），要求的是 $x$，因此未触发；措辞同 Demo 对 Q01 更换主元法的写法。Q10、Q11（2）没有人工课程，路线标“扩展”：不为它们单独开发能力，但第 12 节批次完成后自动运行并按答案金标校验（见 12.7）。

补充金标 Q13：`∀x∈(0,1/2]:x²+ax+1≥0`，目标 `find_minimum(a)`；格子为 `interval, free`，判别式法与更换主元法未触发，分离参数法优先（除以 `x>0`），区间最值法可选（对称轴 `-a/2` 需要分类）。两条路线先得到可行集 `[-5/2,+∞)`，再得到最小值 `-5/2`。该目标单独计数，并列入本期必需验收。

## 4. D3、D4

**D3** 与 Demo 原稿 `intro[D3]` 同构：`interaction.type=plane`，坐标轴及选项取自选法契约的 `plane_axes`，`expected_answer.cell` 由本目标特征推出。`coverage` 按目标计算：本目标格子 `expected_answer.cell` 只列出 D3 结论为 `fit` 的分支；`superseded`、未触发、不适用分支不出现在本格，只保留 `verdicts` 说明，未知分支两者都不进。其他格子沿用各分支的静态 `plane` 作教学展示。因此学生在本格中选得到每个推荐或可选的方法，选不到未触发的方法。Q01 按此计算的 `coverage` 与 Demo 原稿相同（区间最值法不优先，不在 `real, free` 格）；全实数存在题的本格不含判别式法，而含兜底规则下优先的区间最值法。`verdicts` 按分支给出：

| 分支结论 | D3 `verdicts[].value` |
| --- | --- |
| 可用且优先或可选 | `fit` |
| 可用但不优先 | `superseded` |
| 未触发 | `not_triggered` |
| 不适用 | `unfit` |
| 未知 | 不进 `verdicts`，该方法在格子中不可选，只进调试报告 |

`message` 由模板填入检查绑定值，例如“对所有实数 $x$ 成立，关于 $x$ 的二次项系数为 $-1$，确定非零”。Q01 的 `coverage`、`expected_answer.cell` 和每个 `verdicts[].value` 必须与 Demo 原稿逐项相同；文字不要求逐字一致，但须包含 Demo 文字中的判断依据（系数、已分离、$\mathbb R$ 也是区间、要求的是参数），在报告中并排展示供人工核对。`feedback` 的横轴、纵轴提示由坐标轴模板和本题特征生成。

机器用的 `bindings` 保留规范表达式，学生文案的 `display_bindings` 直接由计算所得数学对象生成 LaTeX；模板只使用显示绑定，不能把 `sstr`、`sqrt(...)`、`Interval(...)` 等内部写法塞进 `$…$`。分离参数法说明除数的正负以及是否反向；区间最值法说明是否需要分类及其原因，涉及开区间时区分端点值／极限与是否取得。按规范化关系判断开口时，文案须明确是在说明规范化后的二次式。

**D4** 列出全部 `fit` 分支对应的路线选项：`route_id`、`branch`、`method`、`recommendation`、`route_plan`。`capability_gap` 的选项标“详细步骤暂不支持”。D4 只依赖选法评估，在路线执行前即可生成；路线执行结果另以 `route_status` 记录追加（`pending → running → verified / capability_gap / math_failed / execution_error`），不改写 D4。这与设计文档第 9.3 节“片段只增不改”一致。Demo 把格子判断和选方法合在 D3 一次提交，由本阶段共用页面编译规则决定 D3、D4 的呈现方式，两份片段均输出，不依赖阶段④。

能力补齐过程中，D3 在各批次之间必须完全不变；D4 只有 `route_plan` 从 `capability_gap` 变为 `planned`。

## 5. 方法执行契约

### 5.1 位置与格式

执行契约放在 `site/data/knowledge-next/execution/`，一个方法一份，文件名与方法节点 ID 相同：`method-discriminant`、`method-separation`、`method-interval-extremum`、`method-variable-swap`，子方法 `quadratic-inequality-solve`、`method-square-extremum`。另有两张表：

- `skill-capabilities.json`：公共技能或方法 ID → 内部能力 ID 列表。一个公共技能可对应多个能力（`skill-inequality-transform` 对应移项、乘除常数、取倒数等）；能力可复用于不同技能，但每次公共调用只绑定一个已登记且语义相符的 `public_ref`，不能因底层实现相同而绕过调用位置校验。不属于任何公共技能的为内部能力（如端点检验）。
- `basis-operations.json`：能力报告的运算种类 → 知识依据锚点（如 `add_both_sides → inequality-properties#addition`、`multiply_negative → inequality-properties#multiplication`、`discriminant_condition → quadratic-equation#discriminant`）。

每份执行契约：

| 字段 | 内容 |
| --- | --- |
| `method` | 方法节点 ID |
| `inputs` | 输入角色：关系、量词、量词变量、定义域、要求的字母、给出范围的字母，以及原始 `goal`、完整 `constraint_context`；由驱动器从特征、候选题意或父方法绑定，均保留来源 |
| `steps[]` | 与方法节点 `steps[].id` 一一对应、顺序相同 |
| `steps[].calls[]` | 对应节点该步骤的 `calls`，或该步骤 `rule` 的分支目标：`public_ref`、`capability`、输入绑定、输出名，以及可执行的 `guard`（如 `param_condition.degree == 2`）；规则调用另存 `rule_ref/branch` 来源链，未执行的候选保留原因 |
| `steps[].judgments[]` | 本步骤内的判断节点：节点 ID、依赖的绑定、程序判定函数、可选项、各选项通向的调用或分支 |
| `steps[].cases` | 分类讨论：由哪个能力产生情况列表，每种情况执行哪些步骤，合并发生在哪一步 |
| `steps[].display_units[]` | 本方法步骤的数学展示单元：稳定单元 ID、就绪依赖、标题／说明模板、表达式与依据绑定、分支条件；不声明本题数值或 AI 问题，详见 5.3 |
| `outputs` | 方法完成时返回给父方法或路线的绑定 |
| `exits` | 失败时的退出位置：前提被否定（正常数学结果）、能力缺口、校验失败 |

同一步骤的多个 `calls` 不一律顺序执行：有 `guard` 的条件调用彼此可以互斥，例如分离参数法 `range` 步骤的四个候选，由判断节点“区间求值技能选择”选中一个，其余记为候选调用。

`quantifier` 步骤只输出求上确界或下确界的策略，不读取后续 `range/select` 的输出。范围算出后，分离参数法在 `restore`、区间最值法在 `conditions`、更换主元法在 `solve` 应用策略，得到参数条件。此处的 `apply_quantifier_policy` 是内部能力，`public_ref=null`，明确引用前面策略记录和知识依据，不伪造一次位于该步骤的公共技能调用。约束求交、独立验证及目标收束放在方法返回后的路线 `finalization[]` 中，不给图谱方法增添不存在的步骤。

分离参数法的策略应用须保留参数关系本身，例如 $h(a)\ge4$；移项为 $h(a)-4\ge0$ 应由 `restore` 声明的公共变形调用执行、局部检查并记入轨迹，不能藏在内部策略中，再把公共调用固定跳过。该实现偏差已修复，相关 Demo 例外仍待确认，见 9.2 与 12.2。

区间最值法的 `select` 通过 `rule-interval-skill.branches[].target` 选择公共技能，执行契约必须将这条规则来源链展开为有条件的候选调用，不能因节点没有 `calls` 就跳过计算或虚构直接调用。分离法 `range` 则使用节点已列出的候选；遇到正二次式的倒数时，`range` 先保存分母值域，`restore` 在已声明的 `skill-inequality-transform#reciprocal` 调用下取倒数，再应用量词策略。中间的分母值域不能被误当作原函数值域。

### 5.2 契约自检

加载时检查并在测试中覆盖：

- 方法节点每个步骤在契约中都有，顺序一致；契约没有节点之外的步骤。
- 节点每个 `calls[].ref` 在契约中或者有对应调用（含 `guard`），或者显式标为“教学提示，不执行”并写原因。非空 `public_ref` 必须来自节点该步骤的 `calls`（含其中的子方法），或由该步骤 `rule` 指向的 `branches[].target`；后者逐项校验规则、分支和目标 ID。规则扩展只产生已声明目标，不允许从文字推测额外调用；目标为子方法时压栈执行。带锚点的技能引用同时核对所属技能 ID 与有效锚点。内部能力声明 `public_ref=null`、合法执行位置和依据来源，不冒充公共技能。
- 输入、`guard`、判断与输出绑定组成可执行的依赖图：无环，每次读取均有先前可达的定义；禁止未来步骤输出、互斥分支输出或未合并的情况局部绑定被直接读取。同一步骤内也须声明调用与判断的依赖顺序。
- 每个 `capability` 已在能力注册表登记，或登记为计划中的能力（产生 `capability_gap` 而不是执行错误）。
- `skill-capabilities.json`、`basis-operations.json` 引用的技能、方法和知识锚点都存在于现有图谱。
- 展示单元只读取已完成且局部校验通过的输出，条件与来源完整；发布不依赖后续步骤，步骤 ID 不冲突；已经发布的单元不允许被后续展示规则覆盖或重排。

### 5.3 通用上下文绑定与数学展示规则

驱动器只解释契约，不按题号、题面原式或固定字母编排过程。输入绑定使用数学角色与有作用域的符号身份；中间结果使用带类型的引用。原题及其完整约束只读，方法帧保存本路线／当前分类的局部绑定，子方法返回契约声明的输出；任何新条件都必须带来源和依赖。新增同类题无需修改驱动器；新增方法可以复用已注册能力并增加契约，新增数学操作才增加能力函数。变量重命名、系数变化、等价表达、区间变化、额外参数限制与兄弟小问隔离都须有变式回归，避免把按题写死的代码转移到 JSON。

以上是通用性目标。当前 1b 的 `can_execute` 和输入绑定仍按方法分支，展示函数内有按模板分支生成说明的代码，`append_boundary` 还固定选择 `merge/restore` 作为方法步骤；不能据此声称新增方法只需增加契约。现有支持范围内须先保证数学与轨迹正确，后续再把可复用的绑定、收束展示位置和文案规则迁入声明式配置，剩余项见 12.2 的 P3#4。

`presentation-registry.json` 按能力、数学操作与方法步骤选择通用展示模板。一个图谱方法步骤可产生多个数学片段，例如“开口条件”和“判别式条件”分别展示；每个有意义的移项、求值、条件转换、判断或分类合并都应可追溯。本期对外发布边界必须是显式可恢复的调用／子调用边界；能力若包含多个需实时展示的单元，应拆成具名子调用，逐个返回输出并提交，不能在尚未保存可恢复状态的能力内部直接推送片段。不能等整条路线返回后才补写全部事件。代数库内部无数学展示意义的函数调用不生成学生步骤。

片段标题和基本说明使用通用模板，如“由已知区间可得 $x>0$，两边同除以 $x$”；公式、数值、取值范围及条件全部来自绑定结果。阶段③本身形成完整可阅读推导，阶段④仅附加问答。展示单元发布前确定边界，发布后固定 `step_id`、顺序、正文和公式；动态分类可以追加新单元，但不能回头拆分、合并或重排已有单元。

## 6. 外层驱动器

驱动器放在 `stage_three/driver.py`，只服务图谱方法，不依赖 `solver/runtime`。

- **状态**：课程版本、运行与路线 ID、调用栈（每帧为方法 ID、当前步骤序号、绑定表、所在情况路径）、正在记录的轨迹、已发布数学步骤清单、事件水位和下一次稳定实例编号。
- **步骤执行**：逐个检查调用的 `guard`；成立则把绑定传给能力函数，取得输出、运算列表和后置检查结果，写入绑定表和轨迹；不成立则记录跳过原因（`guard_false`、`already_satisfied` 等）。
- **判断节点**：先确认节点依赖的绑定已计算，再调用程序判定函数，返回选项 ID 与判定依据；判定函数无法给出结论时，路线以 `capability_gap`（`judgment_undecidable`）结束。契约声明需要 LLM 的节点，本阶段一律报告 `capability_gap`（`llm_judgment_unavailable`），不调用模型。
- **子方法**：压栈执行，子方法 `outputs` 返回父帧的指定绑定后回到父方法下一个调用。子方法内部的调用和跳过同样进入轨迹，带父调用序号。
- **分类讨论**：`cases` 产生的每种情况在同一路线内依次执行，绑定按情况隔离，合并步骤读取各情况的结果。
- **路线收束**：方法返回主关系解集后，检查全部题设的处理记录并求交，独立验证完整可行集，再按原目标生成范围或极值答案（第 10.2 节）。任何未处理题设、未验证的集合或未知极值判定都不能发布为 `solved`。
- **逐步提交**：完成的输出、上下文增量、局部检查、数学片段及其事件以同一次逻辑提交登记；未提交内容不可被推送或轮询读到。发布器读取已提交事件，不由求解驱动器直接持有浏览器连接；求解不等待前端确认。详细协议见 11.2。
- **中断恢复**：在每个可发布的调用／子调用完成边界持久化帧、下一子调用位置、情况路径、输出引用、已分配步骤 ID 和事件水位。恢复核对题意哈希与轨迹 `revisions` 中的全部版本（含展示注册表，因为标题和说明模板变化会使同一步骤 ID 的正文不同），任一不符即拒绝原地续跑、需新建运行版本；全部相符则继续最后一次已提交状态；未提交的调用可重算，已发布步骤不生成新 ID 或重复业务事件。仅有日志但不能恢复绑定时，不冒充继续执行，应明确失败或启动新的运行版本。
- **隔离与预算**：每条路线从共享只读输入新建状态，不读取其他路线的中间结果。方法求解默认 10 秒，验证收束另有默认 20 秒，均可配置；执行预算由隔离会话与持久账本实施，不能只依赖 `driver` 内逐调用的事后检查。计算计时含进程启动、编码、计算和传输，测试钩子、屏障、持久化提交、事件发布及会话空闲期间不计时。求解超时或异常记为 `execution_error`；验证收束超时为 `capability_gap`（`verification_incomplete`，诊断保留超时原因），保留已提交前缀，不发布 `verified` 或阶段④交接。

**本轮隔离实现。** 每条路线使用持久 JSON 会话，由独立监督进程管理数学 worker。初始 `can_execute/create_state`、每次 `advance`、精确数学对象的解码／编码、数学文案渲染，以及约束求交、独立验证、端点展示、目标收束与一致性这四个验证边界，全部在数学 worker 内执行。父进程在这条路线边界上只处理受大小、深度和节点数限制的 JSON，不再用 pickle 重建 SymPy 对象；每次计算使用所属预算桶的剩余额度设置硬截止，超时终止并回收 worker。

数学 worker 返回结果后，父进程须在同一截止时间前完成 JSON 接收并 ACK；监督进程收到 ACK 后才写入成功的 `returned` 回执。结果还未送达或 ACK 已超时，不能留下可在恢复时绕过截止的成功回执。父通道断开时先比较共享截止时间：已到期按 `timeout`，只有提前失去父进程才记 `parent_lost`，防止正常超时与 EOF 的竞态误归类。

**持久预算与恢复。** SQLite 账本按目标、路线及 `solve/verification` 桶保存预算；每次计算先取得路线租约并登记带输入哈希的 attempt，再启动工作，防止两个恢复进程同时消费同一路线。监督进程原子保存带 attempt 身份的 receipt，账本结算实际耗时；checkpoint 同步 `compute_seconds/verification_seconds` 和逐操作计时。已测实际用量 `actual` 与回执尚未知时的保留上界 `reserved` 分开记录，准入按两者之和扣预算，不能将未知用量冒充零或实际测量值。

父进程被 SIGKILL 后，监督进程回收数学 worker 并保存 `parent_lost` 的实际耗时；恢复先核对和导入回执，再按剩余额度重试。回执暂不可得时保留预算上界，不能重复恢复以重置消耗。若计算已 `returned` 但数学步骤／事件尚未提交，恢复复用相同输入哈希下的回执，不重新计算；步骤和完成态仍须通过原子的发布提交，已发布事件不重复。

该隔离边界明确为**路线求解与验证**。入口的 Notation 准入、`build_context` 和 D3 选法仍走现有父进程路径，不能概括为阶段③所有数学都已移出父进程。P3#6 在上述路线边界内已通过全量回归、真实 SIGKILL 恢复与浏览器验收，证据见 12.2；1c 的页面接线与问答附加验收另见 12.3，不计入此前的通过结论。`cases` 的完整分支执行、隔离与结果合并仍须先通过 12.4 的门槛才能扩大支持类别。

## 7. 能力函数

能力函数放在 `stage_three/capabilities/`，输入输出都是精确对象：多项式与有理式用 SymPy 表达式，集合用 SymPy `Interval`/`Union`/`FiniteSet`，允许平方根等代数数（Q06 的 $2\sqrt2$、Q08 的 $\frac{1\pm\sqrt5}2$），不使用浮点近似判断。每个能力返回：输出、运算列表（供 `basis-operations.json` 换成知识依据）、后置检查结果。能力只对声明支持的输入类别工作，其余输入抛出“能力缺口”，不能猜测执行。

| 能力 | 公共技能或方法 | 输入 → 输出 | 后置检查 | 批次 |
| --- | --- | --- | --- | --- |
| `normalize_to_zero` | `skill-inequality-transform` | 关系、变量 → 多项式与 $0$ 比较。首项系数符号确定时移到使其为正的一侧；含参时保持方向移到左边 | 比较方向归一后的残差只差已证明为正的常数倍，严格性不变；见下文 | 1 |
| `simplify_expression` | `skill-simplify` | 表达式 → 展开、合并的规范形式 | 恒等 | 1 |
| `quadratic_sign_condition` | `skill-quadratic-sign` | `∀`、$\mathbb R$ 上非退化二次式、不等号 → 开口条件与判别式条件 | 核对非零首项前提、方向及严格性对应的代数定理；独立集合验证兜底，数值抽查仅诊断 | 1 |
| `transform_param_inequality` | `skill-inequality-transform` | 参数不等式 → 移项、乘除常数后的等价形式；乘负数时变号 | 解集不变 | 1 |
| `solve_quadratic` | `skill-solve-quadratic` | 常系数二次方程 → 精确实根（含无实根、重根） | 回代为 $0$ | 1 |
| `quadratic_sign_pattern` | `skill-quadratic-sign` | 开口、完整实根及重数、不等号 → 解集 | 完整根分区内精确取点检验，根处单独判定；确认各段没有其他根 | 1 |
| `separate_parameter` | `skill-inequality-transform`、`skill-equality-transform` | 关系、参数 → $h(\text{参数})\ \square\ g(x)$；需要除法时读取 `divisor_sign`，负号变向；已分离时跳过 | 两种形式在定义域内等价 | 1（已分离）、3（除以正数）、4（除以负数） |
| `select_quantifier_policy` | `skill-quantified-range` | 量词、比较方向 → 求 `sup/inf` 的策略与取得边界时的比较规则；不输入值域 | 与下方规则表一致，不能提前假定端点可取 | 1（∀）、3（∃） |
| `apply_quantifier_policy` | 内部能力（引用先前策略及 `skill-quantified-range` 依据） | 策略、已计算值域及边界可达性 → 参数条件或条件的 AND/OR 组合 | 值域已绑定，按规则处理严格性、无穷与可达性；不读取未来结果 | 1（∀）、3（∃、取不到） |
| `square_extremum` | `method-square-extremum`（子方法，内部用 `method-complete-square`） | $\mathbb R$ 上常系数二次函数 → 配方形式、最值、取到点 | 顶点回代 | 1 |
| `quadratic_interval_range` | `quadratic-interval-extremum` | 常系数二次函数、区间 → 值域、各端点能否取到 | 端点与顶点取值 | 3 |
| `endpoint_values_extremum` | `quadratic-interval-extremum` | 含参二次函数、区间，不需要分类时 → 所需上/下确界的端点候选及可达性；开区间端点用极限值 | 凸凹条件、端点开闭、是否存在内部同值点均匹配 | 3 |
| `parametric_interval_extremum` | `quadratic-interval-extremum` | 含参二次函数、区间 → 按首项系数符号或对称轴位置分情况的确界及可达性 | 分类条件完备且无冲突、每类代数公式成立；抽样仅诊断 | 4 |
| `reciprocal_range` | `skill-reciprocal-range` | $c\left(x+\frac kx\right)$（$k>0$）、同号区间 → 值域、取到点 | 单调区间端点取值 | 3（$x>0$）、4（$x<0$） |
| `reciprocal_of_range` | `skill-inequality-transform`（`#reciprocal`） | 恒正函数的值域 → 倒数的值域 | 端点取倒数 | 4 |
| `linear_range` | `skill-linear-range` | 一次式或常数、闭区间 → 两端点值、上下确界及可达性；斜率符号不定时保留条件表达式，不决定 AND/OR | 端点回代、斜率与常数情形；量词组合交给 `apply_quantifier_policy` | 4（常数情形）、5 |
| `degenerate_case_check` | `linear-interval-extremum` | 退化后的一次式或常数 → 在 $\mathbb R$ 上是否恒满足 | 直接判定 | 2 |
| `merge_cases` | `method-discriminant#merge` | 各情况的参数集合 → 并集 | 集合运算复核 | 2 |
| `intersect_conditions` / `union_conditions` | `skill-inequality-transform` | 已明确为 AND / OR 的参数条件解集 → 交集 / 并集；不可根据方法名硬选一种 | 条件逻辑与集合运算对应 | 3、5 |
| `reorder_by_variable` | `skill-simplify` | 表达式、新主元 → 按新主元整理的一次式 | 恒等 | 5 |
| `endpoint_check` | 内部能力（依据 `function-range-extrema#attainability`） | 原题、候选参数集合的有限端点 → 每个端点保留或排除 | 独立判定器（第 10.1 节） | 1 |
| `apply_visible_constraints` | 内部能力 | 主关系参数集、完整 `constraint_context` → 全部题设约束下的可行集 | 每个来源均有处理记录；不可解的额外条件为缺口，不能丢弃 | 1 |
| `finalize_goal` | 内部能力 | 已验证可行集、原始 `goal` → 范围或极值答案及存在性状态 | 极值须检查是否为集合成员、是否有界及是否为空；见 10.2 | 1（范围）、6（极值） |

归一化检查定义方向残差：`>`、`≥` 取 `lhs-rhs`，`<`、`≤` 取 `rhs-lhs`，另存严格性。Q01 的 `-x²+2x+3≤a²-3a` 与 `x²-2x+a²-3a-3≥0` 的方向残差相同；若只改负号却未翻转比较符，检查必须失败。含参乘除需要先证明乘数符号并保存非零条件，不能套用常数倍规则。

量词策略的规则表（$g$ 为量词变量一侧的函数，$h$ 为参数一侧，$\sup$、$\inf$ 可为无穷；以下先假定定义域非空）：

| 条件 | 等价参数条件 |
| --- | --- |
| $\forall x,\ g(x)\le h$ | $h\ge\sup g$ |
| $\forall x,\ g(x)<h$ | 上确界取到：$h>\sup g$；取不到：$h\ge\sup g$ |
| $\exists x,\ g(x)<h$ | $h>\inf g$ |
| $\exists x,\ g(x)\le h$ | 下确界取到：$h\ge\inf g$；取不到：$h>\inf g$ |

方向相反的四种情况对称处理。这张表也是 Q05 开区间“最值取不到时单独看等号”的依据。求值前只选择本表策略，求值后才代入确界、无穷与可达性。空定义域单独处理：`∀` 为真、`∃` 为假，不请求空集的最值；无穷界不能视为可取到的函数值。

本期量词支持边界：

| 方法 | `∀` | `∃` |
| --- | --- | --- |
| 判别式法 | 全实数域，含明确分离的退化分支 | 本分支不触发，不能套用恒同号判别式条件 |
| 分离参数法、区间最值法 | 按上表及其对称规则 | 按上表及其对称规则；所需函数/定义域未支持则缺口 |
| 更换主元法 | 对闭区间上一次式，两端条件 AND | 对闭区间上一次式，两端条件 OR；包括斜率为零 |

更换主元的端点规则只用于闭区间与单个大小比较关系。开区间必须另算确界可达性；本期 `linear_range` 未覆盖时报告缺口，不能照搬闭端点 OR。Q09 原题的两端取交集，改成存在量词后取并集，两者共享端点计算而不共享逻辑组合。

## 8. 判断节点

全部由程序判定，判定函数与能力共用代数实现，结论写入轨迹的 `judgments`：

| 判断 | 位置 | 判定 | 批次 |
| --- | --- | --- | --- |
| 二次项系数能否为 $0$ | 判别式法 `degree` | `degenerate_branches`；能为 $0$ 时产生“系数为 $0$／不为 $0$”两类情况 | 1（不需讨论）、2 |
| 区间求值技能选择 | 分离参数法 `range`、区间最值法 `select` | 分离法在节点候选中选择：全实数二次用 `method-square-extremum`，其他区间二次用 `quadratic-interval-extremum`；区间最值法的二次分支沿 `rule-interval-skill` 始终选择 `quadratic-interval-extremum`。一次/常数用 `skill-linear-range`，对勾用 `skill-reciprocal-range`。分离法的正二次式倒数按 5.1 分两步求值 | 1、3、4 |
| 要上确界还是下确界 | 各方法的 `quantifier` 步骤 | 量词与比较方向查 7 节规则表，只选策略；数值及端点可达性留给后续求值与应用 | 1 |
| 除数符号 | 分离参数法 `separate` | `divisor_sign` | 3、4 |
| 是否需要按参数分类 | 区间最值法 `select` | `interval_case_split`；需要时按首项系数符号（含为 $0$ 的常数情形）或对称轴与区间位置分情况 | 3、4 |
| 斜率符号 | 更换主元法 `range` | 确定上下确界所在端点；不定时保留两端候选。后续 `solve` 按量词组合：`∀` 两端都满足，`∃` 至少一端满足 | 5 |
| 极值是否存在 | 路线 `finalization` | 可行集是否为空、所需边界是否有限且在集合内；按原目标返回值或不存在的原因 | 6 |

## 9. 轨迹契约

### 9.1 结构

每条路线完成或退出时保存一份 `graph-stage-three-route/v1`；运行中的 `pending/running` 状态由快照和路线状态事件表示：

| 字段 | 内容 |
| --- | --- |
| `route_id`、`branch`、`method`、`target_ref` | 路线标识；`route_id` 取自选法契约分支声明（3.1），与人工课程路线 ID 一致 |
| `run_id`、`lesson_version` | 运行与课程版本 |
| `revisions` | 本路线实际使用的选法契约、方法执行契约、能力实现、展示注册表及两张映射表的版本哈希；参与执行快照身份、`math_step_sha256` 输入与阶段④问答绑定 |
| `status` | `verified` / `capability_gap` / `math_failed` / `execution_error` |
| `steps[]` | 按执行顺序：`seq`、`method`、`step`、`depth`（子方法深度）、`parent_call`（调用它的父调用序号）、`case_path`（如 `["k=0"]`） |
| `steps[].calls[]` | `seq`、`capability`、`public_ref`（内部能力为 `null`）、`rule_ref/branch`（规则产生的调用）、输入与输出（表达式串及规范形式）、`operations`、`used_basis`、后置检查 |
| `steps[].skipped_calls[]` | 节点上有、本次没执行的候选调用：`public_ref`、原因（`guard_false` / `already_satisfied` / `not_selected`）、`guard` 或判断节点引用 |
| `steps[].judgments[]` | 节点 ID、输入绑定、全部选项、选中项、`decided_by=program`、依据 |
| `math_steps[]` | 按发布顺序引用第 11.1 节数学片段：`step_id`、内容哈希、轨迹来源及片段文件；终态轨迹不重建或改写已发布片段 |
| `constraint_context` | 第 2 节的完整题设及来源、逐项处理记录；保留原式供独立验证 |
| `finalization[]` | 方法返回后依次记录约束求交、独立集合验证、目标收束；内部操作不冒充图谱方法步骤 |
| `result` | 原始 `goal`、`feasible_set`（区间/孤立点、精确端点与开闭）、第 10.2 节类型化 `answer` 及学生写法；参数范围与最值分开保存 |
| `verification` | 第 10.1 节后置检查、独立集合完整性与一致性证据；不足证明时不能 `verified` |
| `gap` / `error` | 缺口的能力或判断节点 ID，或异常类型与位置；成功时省略 |

跳过的准备步骤和未选中的候选不进入实际调用，只在 `skipped_calls` 中保留，供图谱展示“候选调用”。

内部策略应用保留其来源与知识依据，但不增加公共调用引用；`finalization[]` 单独展示，不参与 9.2 的方法步骤调用序列对齐。范围目标在批次 1 即可完成收束，最值目标在批次 6 能力补齐前为 `capability_gap`，不能以已有可行集提前标记 `verified/solved`。

### 9.2 与 Demo 原稿的对齐（Q01）

Demo 原稿每个课程步骤的 `effects.calls` 为 `{method, step, ref, usedBasis}`，子方法的调用平铺列出，进入子方法的那一次调用写成父方法步骤上 `ref=子方法 ID`、`usedBasis=[]`。轨迹按同一规则平铺后与 Demo 比较：

- 按 `(method, step)` 分组，比较组内公共引用的出现顺序（去重）与每个引用 `usedBasis` 的并集。Demo 把同一步骤拆成多个课程步骤（如判别式法 `conditions` 拆成 `d_position`、`d_delta`），同一技能出现两次，因此不比较调用次数。数学展示边界由阶段③契约与通用展示规则确定，逐步发布后冻结；阶段④不再拆分或合并这些步骤。
- Demo 列出的 `skippedCalls` 必须是轨迹 `skipped_calls` 的子集（如 `e_basis` 中已分离而跳过的两个调用、`e_extremum` 中 `method-square-extremum` 的 `prepare` 候选）。
- 轨迹多出的实际调用须逐条裁决：属于 Demo 省略的，登记在 `demo-alignment-exceptions.json` 并写理由，经人工确认，不修改 Demo 原稿；不能登记的视为程序错误。本轮已把分离参数法 `restore` 中 $a^2-3a\ge4$ 移项成 $a^2-3a-4\ge0$ 恢复为真实公共调用，Demo 的 `e_range` 未列出该调用。这项额外调用已登记为待人工确认的例外，不能为了空表隐藏实际计算，也不能以测试通过代替人工确认。

当前 `separation-restore-normalize` 保持 `pending_human_confirmation`。按本轮安排，先完成嵌套根式和验证收束修复，再统一确认；本轮不重复征询，也不提前标为已确认。

**数学步骤边界金标。** 阶段④不再拆分、合并或重排步骤，阶段③发布的 `math_steps` 就是最终页面结构，因此 Q01 另有步骤边界金标 `demo-step-alignment.json`：

- 每个已发布数学片段映射到恰好一个 Demo 课程步骤（判别式法 `d_rewrite`、`d_position`、`d_delta`、`d_range`、`d_boundary`；分离参数法 `e_basis`、`e_condition`、`e_extremum`、`e_range`、`e_boundary`），映射依据为片段的 `method_ref` 与来源调用，对照 Demo 的 `templateSteps` 与 `effects.calls`；不按标题文字匹配。
- 同一 Demo 步骤可以对应多个连续片段，但顺序不能交错，也不能有片段跨两个 Demo 步骤。Demo 的每个步骤都至少有一个片段，Demo `omit` 中的步骤（`d_basis`）不发布片段。
- “方法依据”类步骤由展示注册表按通用规则处理，不按题号：
  - 节点上有调用、但本次全部以 `already_satisfied` 跳过的步骤（如 Q01 分离参数法 `separate`，参数已在一边），仍发布一个说明片段，写明为何无需变形，正文来自跳过原因与前提检查，对应 `e_basis`。
  - 节点上本无调用、只有判断且结论为“无需处理”的步骤（如 Q01 判别式法 `degree`，二次项系数为常数 $1$），不单独成片，结论作为条件写入下一个片段的 `premise_refs`；这与 Demo `omit: ["d_basis"]` 一致。判断产生分类时（Q02、Q03）则单独发布。端点与取等检查（`d_boundary`、`e_boundary`）作为路线收束前的独立片段发布，来源为 `endpoint_check`。
- 不一致须登记到同一例外表并写理由，经人工确认。空表只表示该次比较未登记差异，不自动证明调用真实、对齐完整或已获人工确认。

### 9.3 与人工课程的对齐（Q02–Q09）

人工课程在 `topics/quadratic-always.json` 中只给每个课程步骤的 `refs`，没有方法步骤对应关系，因此按路线比较集合：人工路线所有 `refs`（技能、方法、方法步骤锚点、知识锚点）都必须出现在轨迹中，可以是公共调用引用、子方法、`used_basis` 或判断依据；轨迹多出的引用列入报告，不判失败。数学步骤边界按同一粒度检查：人工路线的每个课程步骤都至少有一个数学片段，其 `refs` 中的技能或方法出现在该片段的来源调用中，片段顺序与人工步骤顺序一致；人工步骤之外多出的片段列入报告，由人工确认。例如 Q07 `extremum` 路线须出现 `quadratic-interval-extremum`、`function-monotonicity`、`skill-inequality-transform#reciprocal`，Q02 须出现 `method-discriminant#degree`、`linear-interval-extremum`、`method-discriminant#merge`。

### 9.4 ExplanationSnapshot 映射（预留）

本阶段不生成 ExplanationSnapshot，也不引入其类型。在 `stage_three/snapshot_mapping.md` 写明对应关系，供将来接入：路线 ↔ 一份 snapshot；`math_steps` ↔ 讲解步骤（通过来源关联执行 `steps`）；`calls.outputs` ↔ 事实；`used_basis` ↔ 依据引用；`judgments` ↔ 分支说明；`case_path` ↔ 分类小节。轨迹字段命名避免与 snapshot 字段同名异义。阶段③自己的执行恢复快照不使用 ExplanationSnapshot 类型。

## 10. 数学校验与失败分类

### 10.1 路线答案校验

每条路线的 `verified` 要同时满足：逐步后置检查全部通过；完整题设约束下的可行集通过独立完整性验证；按原始目标完成第 10.2 节收束。跨路线一致性另决定目标是否能发布答案。

**独立单点判定器。** 不使用求解路线的能力函数与中间结果。给定一个参数值，先检查原题全部参数限制与表达式定义条件，再代入原量词关系，以独立精确证书判定量词谓词。首批全实数非严格二次式独立构造并核验 $q(x)=A(x-v)^2+m$ 且 $A>0$，以 $m\ge0$ 判定恒成立；若 $m<0$，记录 $x=v$ 处的负值反例。精确判零已由多生成元数域约化改为对整个表达式调用 `minimal_polynomial(value)`：一次最小多项式恢复精确有理值（含 0），高次保留原表达式及原实嵌入，再由有理隔离区间及向外区间算术证明符号，不用最小多项式的另一个根替代原值，也不依赖解集与 `Reals` 的结构相等。后续区间、存在量词或更换主元类别须另外注册完整证书，空定义域按空量词语义处理。比较、求根或证书仍为未知时返回缺口，不能把 `ConditionSet` 或符号真假强转为布尔值。

本轮 P1 暴露了精确代数端点的判定缺陷：对于 $\forall x\in\mathbb R:x^2+a^3-a-1\ge0$，设 $r$ 为 $a^3-a-1$ 的唯一实根，正确可行集为 $[r,+\infty)$；旧实现会拒绝这个闭区间，却接受漏掉端点的 $(r,+\infty)$。修复后正确闭区间为 `verified`，错误开区间为 `math_failed`，反例是被遗漏的 $r$，该点精确最小值为 0；`endpoint_check` 共用该判定，闭区间 `passed`、错误开区间 `failed`。完整复测与可调试证据见 12.2。

新增 P2 来自合法嵌套根式 $\sqrt{1+\sqrt2}$：此前构造多生成元数域可能触发 SymPy 的 `IndexError`，最终错误归类为 `execution_error`。修复已完成编码：具备完整证明的输入为 `verified`，库能力不足或验证超时受控返回 `capability_gap/verification_incomplete`，SymPy 异常的类型、消息及定位保留在 diagnostics。异常转换仅包围具体 SymPy 库调用，不用宽泛捕获吞掉本地绑定和程序逻辑的 `KeyError`、`TypeError`。嵌套根式、原三次代数根和错误候选必须一并回归，不能用缺口掩盖已有类别的错误放行；本轮全量结果在 12.2 补记。

这里的“独立”目标包括题设读取和验证证明。目前验证证明不使用方法的中间计算结果，但路线求交的 `apply_visible_constraints` 本身位于 `verification.py`，与验证流程直接共用 `read_problem`，并非仅共用 `NotationValidator`、`Canonical` 等基础设施。因此不能声称路线求交与验证的题设读取完全独立；P3#5 还需拆出路线求交的输入构造，再以独立预期、等价表示和解析反例检查两条路径，防止同一读取错误同时进入候选集与验证证明。

**独立完整性验证。** 批次 1b-1 的首条路线即实现从原题构造临界分区的验证器，不以候选答案的端点作为唯一分区来源。按输入类别分批扩展验证能力，但每个已支持类别都必须完成以下全部证明步骤，不能用抽查替代尚未实现的完整性证明。

- **首批支持类别（1b-1、1b-2）**：单个实数参数、全实数域上的全称非严格二次不等式；按第 7 节方向残差规范表达后，二次项系数为正有理常数，其余系数为该参数的有理系数多项式；额外参数限制先支持该参数的一次不等式与实区间成员条件。类别判定从输入表达式与作用域得到，覆盖 Q01、系数或符号变化的同类题，以及 `a<1 ∧ ∀x∈ℝ:x²+a≥0`，不得按题号或 Q01 原式查表。首批即保留独立题设收集、未定义点检查、完整临界集合、精确分区与集合等价比较。
- **本期最终覆盖**：一个量词变量、一个实数求解参数；关于量词变量次数不超过 2 的多项式，其系数关于参数是实代数常数系数的有理函数；量词定义域是固定实代数端点的单区间（可开闭、含无穷端）；额外参数限制是同一参数的一元半代数条件。随批次 2–5 同步扩展退化、有限与开闭区间、严格不等式、存在量词、含参系数及更换主元的验证，最迟批次 6 验收前覆盖本段全部范围；只让题库样本通过不代表覆盖已经完成。

当前批次尚未支持的类别，以及参数相关定义域、多个独立参数或其他超出本期范围的条件，必须有另外注册的完整集合等价证明，否则为 `capability_gap`（`verification_incomplete`）。方法求解成功不能绕过此门槛；不能仅因数值抽查通过就标记 `verified`。分批只改变可接收输入类别，不降低第 14 节最终完成判据。

验证步骤：

1. 验证器不复用求解路线使用的 `constraint_context`，而由独立的收集函数直接从候选题意重建本目标作用域及祖先作用域的全部事实、定义与符号定义域，再与路线的 `constraint_context` 逐项比对来源：任一方多出或缺少题设都记为 `math_failed`（`constraint_context_mismatch`），避免两者因同一处遗漏而一起通过。随后从原始表达式及重建的题设提取定义条件，保留每个原始分母的非零约束；约分不能丢掉未定义点。若清分母，使用已证明为正的分母平方积并保留非零条件，或逐分区检查分母符号，不能直接乘符号未知的分母。
2. 独立生成参数临界多项式：关于量词变量的各系数分子与分母、二次判别式分子与分母、原式在每个有限定义域端点的取值分子与分母，以及每条额外参数条件原子的分子与分母。恒零多项式记录为恒等事实，不尝试枚举它的全部零点。常数、一次、重根恒存及退化情形单独覆盖。
3. 对非恒零临界多项式做精确实根隔离、去重排序，得到全部临界点及它们之间的开区间，包括两侧无界区间。记录每个临界点的原式来源；仅用浮点根近似不能构造分区证明。
4. 验证所支持类别的分区不变性：每个开区间内次数、系数与判别式符号固定，实根数及其与固定有限端点的相对位置不变；所以原量词谓词与各参数限制的真假固定。无限端不代入数值，降次临界点负责覆盖根向无穷逃逸的情况。不能完成该证明的输入报告缺口。
5. 每个开区间取一个由根隔离区间确定的精确有理样点，每个临界点用精确代数数调用独立单点判定器；参数约束和未定义条件也逐项判定，由此独立重建完整可行集。之后才比较候选集合：汇合两集合的全部有限端点和孤立点，精确排序、去重，按共同端点形成覆盖实轴的完整分区；逐开区间和端点比较精确成员关系，既不能多一段，也不能少一段或漏孤立点。候选集合只参与最终集合等价比较，不参与原题临界集合及可行集的重建。单点真假决定边界开闭；任何等价比较未知均为缺口。

步骤 4 的不变性与步骤 3 的完整临界集合，使这里的有限点检验成为完整证明；任意根隔离、排序、判定、集合比较无法完成时为能力缺口。发现具体反例则为 `math_failed`，报告保留反例参数、被违反的原题及来源。可另保留候选答案端点和中点的抽查作为诊断，但抽查自身没有授予 `verified` 的资格。Q01 错误答案 `[4,+∞)` 必须被拒绝：原式临界分区仍包含 `-1` 及左侧区间，不能因候选漏掉左段就不检查该段。

**路线一致。** 同一目标所有 `verified` 路线的完整可行集及类型化目标答案都应相同；若不一致，目标为 `conflict`，保留各路线状态和证据，不选其一。若无法证明相同，则目标为 `no_verified_route`，诊断 `route_consistency_undecidable`，不发布答案。测试中另用独立编写的答案金标断言（第 13 节）；金标不参与运行时判定，也不能替代完整性验证。

### 10.2 从可行集收束到原目标

`finalize_goal` 的输入是已验证的完整可行集和未改写的 `goal`，范围目标在批次 1 实现，最值目标在批次 6 实现。类型化 `answer` 至少包含 `kind`、`status`，并按下表携带值：

| 原目标 | 输出 |
| --- | --- |
| `find_range` | `status=set`，`set=feasible_set`；空集同样是已解决的范围答案 |
| `find_minimum` / `find_maximum`，集合非空且所需有限边界属于集合 | `status=attained`、精确 `value`；附有界性与成员检查证据 |
| 非空、有有限下/上确界但该边界不属于集合 | `status=not_attained`、精确 `bound`；回答最值不存在，并保留下/上确界供解释 |
| 非空且向所求方向无界 | `status=unbounded_below` / `unbounded_above`；回答最值不存在，不把无穷记为 `value` |
| 极值目标的可行集为空 | `status=empty_feasible_set`；回答没有满足题设的参数，不与无界混淆 |

已证明最值不存在仍是正常且已解决的数学答案；只有收束能力不支持、界或成员关系不能判定时才是 `capability_gap`。`result.feasible_set` 始终保留，不能只用最值数值做路线比较。例如 Q13 两路线均应保存 `[-5/2,+∞)`，而 `answer={kind:find_minimum,status:attained,value:-5/2}`。

### 10.3 失败分类

| 类别 | 记录位置 | 含义 |
| --- | --- | --- |
| 未收录题型 | 目标 `status=unsupported_type` | 主要题型没有选法契约 |
| 能力缺口 | 选法 `route_plan=capability_gap`，或路线 `status=capability_gap` | 方法可用，但能力、判断、额外题设、完整性证明或目标收束尚不支持该输入；D3 结论不变，D4 标“详细步骤暂不支持” |
| 数学校验失败 | 路线 `status=math_failed` | 后置检查失败，或独立验证找到候选解集/目标答案的错误证据 |
| 路线冲突 | 目标 `status=conflict` | 各自通过校验的路线结果不一致；保留路线证据以定位验证器问题，不发布目标答案 |
| 执行错误 | 目标或路线 `status=execution_error` | 目标上下文／选法异常，或路线执行异常、方法求解超时、契约绑定缺失；验证收束超时按能力缺口处理 |

方法前提被否定是选法结论（`not_applicable`），不是失败；路线结果为空集（参数无解）是正常数学结果，照常校验。

## 11. 输出

`graph-stage-three-result/v1` 顶层：`contract`、`run_id`、`lesson_version`、`stage_two`（引用、`sha256`、`run_id`）、`stage_one`（引用、`sha256`）、`input_validation`、`input_diagnostics`、`status`、`goals[]`、`events`（流标识、最新提交序号、快照引用）、`llm`（语义调用数与网络尝试数，本阶段恒为 $0$）。这是最终汇总；运行中的网页从下述持久事件与快照读取增量，不等待该文件生成。

`goals[]` 按阶段②的目标顺序：

| 字段 | 内容 |
| --- | --- |
| `target_ref`、`label`、`stage_two_status`、`primary` | 来自阶段② |
| `status` | `solved`（至少一条路线 `verified` 且已证明所有已验证路线一致）/ `no_verified_route`（无已验证路线，或无法证明路线一致）/ `no_applicable_method`（没有任何分支适用，见 3.4）/ `conflict` / `execution_error`（目标上下文或选法异常）/ `unsupported_type` / `skipped`（阶段②未确认） |
| `selection` | 规则 ID、每个分支的四项结论、前提检查明细与证据 |
| `d3` / `d4` | 第 4 节片段；`skipped`、`unsupported_type`、`no_applicable_method` 时为 `null` |
| `routes[]` | `route_id`、`branch`、`method`、`status`、轨迹文件引用、答案 |
| `route_status[]` | 按时间追加的路线状态记录 |
| `feasible_set` | `solved` 时的完整参数可行集；否则 `null`，各路线中间结果仍保留 |
| `answer` | `solved` 时第 10.2 节的类型化目标答案，区分范围、取得的最值与最值不存在；否则 `null` |
| `diagnostics` | 错误码、消息及定位 |

顶层状态：输入准入失败为 `input_error`；准入后，若没有任何路线 `math_failed`、`execution_error` 且没有目标 `conflict`、`execution_error`，为 `completed`（能力缺口与暂不支持都不影响 `completed`）；部分目标出现上述失败为 `partial`；所有进入阶段③的目标都出现上述失败为 `failed`。

前提检查仅把明确的数学能力缺口、NotationError 与可预期的代数库异常转为 `unknown`，不得吞掉程序自身的 `KeyError`、`TypeError`、`ValueError`。目标处理边界捕获程序异常，保留异常类型、处理阶段和堆栈；选法尚未成功发布时不伪造 D3/D4 或路线，执行阶段失败时则保留已提交的 D3/D4 和数学片段前缀，单独追加错误／不可用状态，不清空既有事件中的内容。答案与问答可用性须撤销，已收集上下文及原目标／特征仍可调试，其余目标继续执行。结果 JSON 和离线报告照常生成，CLI 对 `partial/failed` 返回 1；恢复不重新执行已经失败的目标。

### 11.1 数学步骤片段与阶段④交接

每个学生可读数学片段为 `graph-math-step/v1`：

| 字段 | 内容 |
| --- | --- |
| `lesson_version`、`run_id`、`route_id`、`target_ref` | 当前课程、运行、路线和目标的身份 |
| `step_id`、`ordinal` | 稳定步骤 ID 与路线内展示顺序；ID 在目标命名空间内按方法调用路径、展示单元、分类路径及实例序号分配，同一运行恢复时复用，不用事件到达顺序或标题作 ID |
| `method_ref`、`source_refs`、`case_path` | 对应的方法步骤、计算输出／判断／原题引用、当前分类条件 |
| `title`、`before`、`after`、`explanation` | 通用模板标题和基本说明、结构化前后数学表达式及其显示形式；不含 AI 问题或反馈 |
| `premise_refs`、`used_basis`、`local_check` | 依赖前提、知识依据、局部检查证据；只有 `local_check=passed` 的片段可以发布 |
| `math_step_sha256` | 固定内容与路线 `revisions` 的规范哈希，供重放去重与阶段④精确绑定 |

数学片段只说明本步在列出的条件下通过检查，不表示整题已解完。当前路线仍在运行时，前端可阅读已提交推导，最终候选集合可作为“当前推导结果”保留；只有完整验证、目标收束通过，且与当前其他已验证路线的一致性已确认时，才发布 `route_completion` 和最终答案。尚未完成的路线不参与此门槛，不要求等待；第一条通过的路线可单独交付。已知冲突和 `route_consistency_undecidable` 均禁止交付。失败、缺口或后续发现目标不可用时追加状态，停止把对应过程当作有效完整解答；保留先前过程与证据，不悄悄改写已发布公式，更正进入新课程版本。

路线 `verified` 后冻结 `verified_route_sha256` 和步骤清单，满足上述一致性发布门槛后才以包含目标身份的幂等任务交给阶段④；本期只实现交接和附加片段消费，真实问答生成属于阶段④实施。阶段④产物按 `lesson_version/run_id/target_ref/route_id/step_id` 附加，必须同时匹配 `math_step_sha256` 与 `verified_route_sha256`。`route_id` 是方法路线名，可在不同小问重复；不能省略 `target_ref`。它可增加学生可能追问、引导问题、提示与常见错误反馈，不能增删、合并、拆分或重排数学步骤，不能替换正文、公式或答案。

问答状态 `pending/running/completed/partial/failed` 与数学路线状态独立。问答分批校验、逐步附加，最终每个数学步骤都有问答产物或明确失败记录；超时、失败或重试只影响问答区域，不改变数学 `verified`、步骤哈希、阅读位置或已完成的学生作答。后来发现数学冲突时应阻止该路线继续生成或使用问答，追加不可用状态，不能继续以旧快照发布正式补充内容。

### 11.2 事件、快照与网页接线

线上接线与离线 CLI 共用阶段③的持久事件、游标和快照语义。当前 1c 由本机开发拍题 API 为同一 SQLite `EventStore` 提供 HTTP 轮询和 WebSocket 适配；不把事件复制进第二个存储，也不从导出的 JSONL 恢复执行。正式产品服务现有的 build/problem/batch 流使用产品数据库与授权边界，当前开发接线不等于已完成该服务的学生账号接入。事件信封至少含协议版本、`event_id`、流 ID、流内单调 `seq`、`lesson_version/run_id`、事件类型和负载；所有目标／路线消息携带 `target_ref`，路线消息另带 `route_id`，步骤消息再带 `step_id` 与内容哈希。片段身份与幂等键保留完整目标命名空间；整题级消息才允许 `target_ref=null`。`seq` 是传输水位，`ordinal` 是数学展示顺序，不能混用。事件类别：

| 事件 | 触发与用途 |
| --- | --- |
| `solver.step_completed` | 一个计算／判断单元局部检查完成并提交；保存输入、输出、条件与校验供调试，未达到展示单元边界时也可记录 |
| `lesson.chunk_ready`，`kind=math_step` | 数学片段与局部证据均已校验并提交，网页可立即显示，不等待路线完成或 LLM |
| `lesson.route_status` | 数学路线进入运行、通过验证、缺口或失败等状态；不承载问答失败 |
| `lesson.goal_status` | 以 `target_ref` 同步目标状态及原因；后续出现 `conflict` 或 `no_verified_route`（含一致性未知）时，前端停止使用该目标旧完成态与问答，不改写各路线独立验证记录 |
| `lesson.chunk_ready`，`kind=route_completion` | 本路线完整验证及目标收束通过，携带已验证答案与完成态 |
| `lesson.chunk_ready`，`kind=step_qa` | 阶段④生成的单步补充问答校验通过，仅挂接到精确匹配的数学片段 |
| `lesson.enrichment_status` | 阶段④问答生成进度、部分失败或完成；数学内容继续可用 |

D1–D4 沿用原有 `lesson.chunk_ready` 片段协议。快照在同一只读事务中恢复已发布的 `selection_chunks`；即使传输事件已被保留策略裁剪，也从未裁剪的提交回执取得 D3/D4。D1/D2 的题意引文、正确项、错误反馈和替代思路继续由固定阶段②结果生成，不为阶段③重做判型。持久化输出、上下文增量、快照推进与事件登记须形成可恢复的逻辑提交；单纯写 JSONL 后立即发消息不构成执行恢复保证。离线适配器也必须区分已提交记录与中断尾部，恢复后不能把同一计算或片段登记两次。网络通知失败可重发，不回滚已提交计算。

完成态和阶段④任务登记须与当前 `goal_status` 的发布门槛在同一提交中核对。后来目标变为不可用时追加 `lesson.goal_status`，取消尚未执行的问答任务，并拒绝已在途任务的迟到发布；已保存问答与数学片段保留为证据但不再作为可用答案展示。目标冲突不伪装成某条路线的 `math_failed`，一致性未知也不冒充已证明冲突。

首次加载返回当前快照及同一一致性水位 `last_seq`，随后 WebSocket 以 `after=last_seq` 订阅，HTTP 以 `after_seq=last_seq` 轮询；两者表达同一事件水位。客户端按版本与事件 ID 去重、按序补缺，迟到的旧运行事件不能污染当前课程。游标过期则明确要求重取快照。刷新和断线后不重跑题意提取或已完成求解；同一运行恢复读取提交状态，版本改变时新建运行。快照与事件不可有读取空窗。

网页以独立数学片段增量更新，不需要重新加载整份 bundle。D1–D4 仍由原 graphwalk 引擎负责作答；数学片段使用独立 DOM 追加，不伪造成学生答对的题目。bundle 的进度身份从首份流身份起固定，后来到达的 D3/D4、数学片段和问答不改变该身份。计算进度与学生阅读／作答进度分开：“看 AI 解题”按到达的数学步骤展示，“自己做”只显示学生已到达的步骤，图谱不提前点亮后续节点。图谱的公共调用从对应数学片段的 `source_refs` 解引用已提交轨迹，依据取 `used_basis`，只点亮已阅读片段涉及的真实节点和边，不能从方法的全部可能连线推测已经调用的技能。问答尚未就绪不阻塞阅读；附加问答不得替换 DOM 中的数学卡片、重置作答或跳动当前步骤。片段事件可以小批量发送，但不得积压到整条路线结束才交付；慢客户端可按游标补读，求解不等待其确认。

### 11.3 文件与报告

输出目录：

```text
<output>/
  stage-three-result.json
  input.json                    # graph-stage-three-input-manifest/v1 出处清单，含快照引用与哈希
  stage-two-input.json           # 可直接作为新运行输入的阶段②副本
  stage-one-input.json           # 清单引用的阶段①副本，重跑仍须核对哈希与准入
  run.json                      # 本运行身份、输入哈希与计算预算；恢复时不重新分配 ID
  frozen.json                   # 能力、方法、展示与输入相关实现的版本哈希
  events.sqlite3                # 权威提交库：状态／数学片段／事件／交接同事务，另含计算租约与预算账本
  calculation-budget/receipts/  # 监督进程原子写入的计算回执，按 attempt 身份导入账本
  events.jsonl                  # 导出的已提交事件，与在线事件具有相同语义
  checkpoint.json              # 同一水位的状态导出；恢复读取 SQLite，不用导出文件代替提交库
  goals/goal-001/selection.json
  goals/goal-001/d3.json
  goals/goal-001/d4.json
  goals/goal-001/routes/<route_id>.json
  goals/goal-001/math-steps/<route_id>/<step_id>.json
  goals/goal-001/handoff/<route_id>.json   # verified 后冻结的阶段④输入引用与哈希
  index.html
```

调试报告沿用阶段①②的离线 HTML：准入结果；每个目标的完整可见题设、来源及逐项处理记录、特征、分支四项结论与前提检查证据；D3 方法坐标图与 Demo 文字并排（Q01）；D4 与路线状态；每条路线按方法步骤展开的调用、输入输出、知识依据、判断节点、跳过的候选、分类情况；方法之后的约束求交、临界分区证明、精确检验点与反例、可行集及目标收束；Q01 的 Demo 对齐差异与 Q02–Q09 的人工课程引用覆盖。失败路线也能打开并定位到出错步骤。

另提供按事件游标查看过程的视图：并排展示已发布数学片段与其来源、局部检查和路线终态，显示提交／发布顺序及恢复水位。最终自包含报告能够离线回放相同片段序列；回放事件只重建视图，不重新求解或触发阶段④。问答状态与数学状态分栏，不把“补充内容失败”显示成“数学解答错误”。

## 12. 分批实施与验收

各批次是开发里程碑，不是录制批次。每个批次的验收都在新输出目录上从 22 份阶段①录制完整运行一遍（阶段②离线、阶段③），不拼接不同运行的结果。每个批次通过后，此前批次的全部验收继续通过，D3 与第 3.5 节金标逐项相同；只有新覆盖路线的 `route_plan` 从 `capability_gap` 变为 `planned`。批次 2–5 新增的人工课程路线除答案与引用覆盖外，数学片段还须按 9.3 节对应人工课程步骤。

首轮完整交付目标是 Q01 两条路线从阶段②输入到网页逐步展示，先完成 1a → 1b-1 → 1b-2 → 1c，再扩展批次 2–6。这些是可以连续推进的开发与验收单元，每个单元须保留可调试产物和回归结果。1a 固定片段与事件契约后，前端消费者可并行实现；1b-1 即做真实浏览器提前展示冒烟，1c 再完成双路线、重连与问答附加的全面验收。

首条路线必须具备完整题设与作用域处理、独立完整性验证、稳定步骤身份和展示／恢复边界，以及计算输出、上下文、快照和事件的一致提交。不能先交付只产生最终答案的求解器，再把这些能力作为后续补丁。验证覆盖按 10.1 节逐类扩大，未覆盖输入始终报告能力缺口。

Q13 学生上传录制作为单独入口回归：批次 1a 即检查准入与选法，批次 6 要求两条路线和最小值全部通过；额外约束、量词变式及错误答案构造不增加原有 22 份录制的计数。

### 12.1 批次 1a：入口、选法评估、D3、D4

实施记录（2026-10-19）：本批新增测试 87 passed；阶段②、阶段①特征及 Q13 录制相关回归 437 passed、1 skipped，Ruff 通过。22 份阶段①录制重验后得到 24 个已确认目标与 2 个跳过目标，选法与独立金标一致；Q01 历史 LLM 选择及 Q13 学生上传证据另行验收，本次模型调用与网络尝试均为 0。可调试产物位于 `internal/solver-runs/graph-guided-stage-three/acceptance-1a-20261019-01/`，其中 `selection-replay/`、`student-upload/` 保留两条补充证据路径。设置 `GRAPH_STAGE_THREE_RUN_DIR` 为新的目录并运行阶段③测试，可保留同样的验收产物。当前只完成选法，不执行数学路线；片段、事件与恢复快照的 Schema 已定义，实际提交与恢复机制从 1b-1 实现。

审查修复记录（2026-10-19）：修复学生文案 LaTeX、除数符号与分类依据、前提检查异常边界、单目标失败隔离及保存副本重跑这 5 项问题。阶段③回归增至 133 passed；连同上述相关回归共 570 passed、1 skipped，Ruff 通过，无新增 LLM 调用。新版[调试报告](../internal/solver-runs/graph-guided-stage-three/acceptance-1a-review-20261019-01/index.html)保留相同的 22 份录制及两条补充证据路径；另将首版目录中的 `q01/sample-01/stage-two-input.json` 直接作为输入重跑，结果为 `completed`，产物位于新版目录的 `retained-input-replay/`。失败回归覆盖单目标异常后继续其他目标、全目标失败仍生成报告且 CLI 返回失败，以及新版／旧版清单在验收和学生上传两种准入下的副本重跑。

内容：输入准入与完整 `constraint_context`、结果／轨迹／数学片段／事件及恢复快照 Schema、选法契约、方法前提检查、推荐策略、D3/D4、报告骨架、CLI。

验收：

- 金标路径 12 个目标与录制路径 24 个目标的分支四项结论（除 `route_plan` 外）等于 3.5 节金标；两个 Q11（1）样本为 `skipped`。
- Q01 的 D3 `coverage`、`expected_answer.cell`、全部 `verdicts[].value` 与 Demo 原稿相同；文字包含 Demo 的判断依据。
- 此时全部 `fit` 路线为 `capability_gap`，D4 标“详细步骤暂不支持”，顶层 `completed`。
- 阶段② Q01 LLM 选择回放结果被准入，结论与程序路径相同。
- Q13 的 `student_upload` 录制路径被准入，选法符合补充金标，保留 `find_minimum`，此时收束能力缺口不影响 D3。
- 准入反例全部输出 `input_error`（见第 13 节）；0 次 LLM。

### 12.2 批次 1b：分两步完成 Q01 两条路线

首轮实施记录（2026-10-19，本轮审查前）：`1b-1` 接通判别式路线，`1b` 表示包含 1b-2 的双路线版本。两者共用契约驱动器、独立临界分区验证器及 SQLite 原子提交机制；方法运行中逐调用保存上下文和数学片段，完整验证后才提交路线完成态和阶段④交接。当时每条 Q01 路线包含 5 个数学片段，对齐检查通过且例外表为空；这是审查前产物的记录，本轮发现 `restore` 调用不真实，不能沿用为当前“无例外”或完全验收的结论。现有图谱中的 `method-complete-square` 是 `kind=skill`，执行时保留这次公共能力调用；配方求最值的 `method-square-extremum` 则作为子方法压栈，不虚构新的图谱调用。

首轮测试记录（2026-10-19，本轮审查前）：阶段③共 281 passed；连同阶段②、阶段①特征和 Q13 录制回归共 718 passed、1 skipped，Ruff 通过。事件消费者及相关前端回归共 63 passed。[1b-1 完整录制报告](../internal/solver-runs/graph-guided-stage-three/acceptance-1b-20261019-02/1b-1/index.html)与 [1b-2 完整录制报告](../internal/solver-runs/graph-guided-stage-three/acceptance-1b-20261019-02/1b/index.html)分别在新目录完整运行 22 份录制，各保留 24 个已确认目标、2 个跳过目标；两份 Q01 样本分别完成单路线／双路线，答案均为 $a\le-1$ 或 $a\ge4$。本次新增 LLM 调用为 0。另覆盖恢复时上下文／选法异常撤销旧完成态，以及失败操作提交后中断、恢复补齐终态而不重复发布的回归。这些历史测试数和产物保留供对照，不代表已覆盖本轮新增反例。

真实浏览器验收：暂停判别式路线的完整验证后，页面已显示 4 张真实数学卡片、没有完成态或交接任务；解除屏障后两条路线共 10 张卡片、2 份交接，刷新恢复成功，无浏览器脚本错误。使用同一持久事件消费者和本地只读预览服务；产品 WebSocket／拍题页面全面接入仍属于 1c。[验证记录](../internal/solver-runs/graph-guided-stage-three/browser-1b-20261019-04/browser-evidence.json)、[完成前截图](../internal/solver-runs/graph-guided-stage-three/browser-1b-20261019-04/before-completion.png)及[完成后截图](../internal/solver-runs/graph-guided-stage-three/browser-1b-20261019-04/after-completion.png)由 `server/tools/smoke_graph_stage_three_browser.py` 保存。

**本轮审查修订与剩余项（2026-10-19）。** 下表区分已通过自动回归的修复、待人工确认的对齐例外和后续工作；测试通过不代替人工确认，批次 1b 暂不宣称全部审查项关闭。

| 审查项 | 当前问题与处理要求 | 状态／门槛 |
| --- | --- | --- |
| P1：精确代数端点 | 本轮已改为整个表达式的最小多项式判零，保留原实嵌入的有理隔离区间定号及原题单点证书；最终以两集合共同端点的完整分区做等价比较，候选不参与原题可行集重建 | 本轮验证器 87 项及完整回归通过；正确闭区间通过，错误开区间与伪段被拒绝 |
| P2：真实 `restore` 移项 | `apply_quantifier_policy` 保留参数式与界的比较，由 `restore` 的公共 `skill-inequality-transform` 调用真实执行 `normalize_to_zero`，知识依据为 `inequality-properties#addition` | 已修复并通过自动回归；新增 `separation-restore-normalize` 例外为 `pending_human_confirmation`，未确认前不算对齐验收完成 |
| 新增 P2：嵌套根式异常 | 对整个表达式求最小多项式，避免为 $\sqrt{1+\sqrt2}$ 等表达式构造冗余多生成元数域；SymPy 库边界异常受控转为缺口，diagnostics 保留原类型与消息，完整证明才能 `verified` | 已修复并通过回归：嵌套根式完整路线 verified；库异常和真实超时为缺口，本地程序错误仍可见 |
| P3#1：契约外分离变形 | 分离绑定由契约中的真实调用产生，保留两侧角色和方向残差校验；跳过依据引用 `already_separated` 的计算证据。`range.interval` 未选中原因更正为 `not_selected` | 已修复；方法执行 57 项及完整回归通过 |
| P3#2：分类与合并 | `range_skill` 的判断尚未守卫 `square` 子方法，契约也禁止带守卫动作产生输出；须补判断驱动的分支执行、隔离帧、输出收集与合并，检验情况覆盖和来源 | 尚未完成；批次 2 放宽支持类别前的必过门槛 |
| P3#3：关系方向 | `quadratic_sign_condition` 仅接收表达式，不知道关系方向；目前由正首项准入挡住翻转情况。放宽前必须传递类型化关系，覆盖归一化乘负数后方向反转的变式 | 尚未完成；批次 2 放宽支持类别前的必过门槛 |
| P3#4：方法与文案硬编码 | `can_execute`、输入绑定及展示说明含方法／模板分支，`append_boundary` 固定选择 `merge/restore`；通用规则尚未全部进入契约与展示注册表。后续迁移可复用部分并补新增方法与同类变式回归 | 剩余项；当前不声称仅增加契约就能新增方法 |
| P3#5：解析独立性 | 路线求交的 `apply_visible_constraints` 位于 `verification.py`，直接复用验证的 `read_problem`，同一题设读取错误可能影响双方；须拆出路线求交输入，并补独立预期、等价表示和解析反例的交叉校验 | 剩余项；不声称路线求交与验证的题设读取完全独立 |
| P3#6：计算截止与预算恢复 | 路线初始化、advance、数学编解码／展示及四个验证边界均在受监督数学 worker 内；父进程只处理有界 JSON，ACK 前不落成功回执。SQLite 租约、attempt 与 receipt 实施累计预算，区分 actual 与未知 reserved；parent_lost 回收后按余量重试，returned 在发布前可复用不重算 | 路线求解／验证边界内已通过全量回归、真实 SIGKILL 恢复与浏览器验收；入口 Notation 准入、上下文与 D3 选法不在此隔离范围，1c 页面接线验收见 12.3 |
| P3#7：失败后已发布片段 | 从权威提交回执中的选择事务恢复已发布 D3/D4，保留当前选法调试信息，同时撤销答案与可用状态；事件保留策略裁剪后仍可用提交回执恢复，失败目标不重新执行 | 已修复；执行失败、恢复失败及事件裁剪后的结果一致性回归通过 |
| P3#8：重复加载与全量导出 | 运行中重复加载配置／输入及全量导出累计状态；`snapshot()` 每次扫描全部 `commits` 重建 `selection_chunks`，`export()` 调用快照也承担该开销，随步骤和事件增加会放大成本。后续缓存同版本只读配置、减少非必要重载，并将调试导出与必要增量读取区分 | 剩余项；1c 审查再次确认，当前未完成长路线的性能验收 |
| P3#9：显示与条件引用 | 数学片段使用 `display`、部分结果使用 `latex`，显示字段尚未统一；`premise_refs` 当前累积全部历史判断，混入与本片段无关的前提，应只引用本片段实际依赖的判断 | 剩余项；统一显示字段并补前提相关性回归，不能以历史判断的全集充当片段依赖 |

上一轮复测记录（新增嵌套根式 P2 之前）：阶段③ **307 passed**；连同阶段②、阶段①特征和 Q13 录制回归共 **744 passed、1 skipped**，Ruff 与 `git diff --check` 通过，新增 LLM 调用为 0。两批各 22 份录制已在新目录完整重跑：[1b-1 报告](../internal/solver-runs/graph-guided-stage-three/acceptance-1b-review-20261019-01/1b-1/index.html)、[1b-2 报告](../internal/solver-runs/graph-guided-stage-three/acceptance-1b-review-20261019-01/1b/index.html)。[代数数端点报告](../internal/solver-runs/graph-guided-stage-three/acceptance-1b-review-20261019-01/algebraic-endpoints/index.html)保留正确／错误候选的完整分区证据与端点检查。真实浏览器复测仍为完成前 4 张卡片、完成后 10 张卡片、2 份交接，刷新恢复成功且无脚本错误，[记录在此](../internal/solver-runs/graph-guided-stage-three/browser-1b-review-20261019-01/browser-evidence.json)。当时额外只读终审的 19 个精确代数探针未发现新增阻断问题；此历史记录不包含本轮嵌套根式和硬截止修复，本轮记录另列如下。其余剩余项按上述门槛继续实施，不因 Q01 两条路线通过而标为完成。

历史复测记录（嵌套根式与验证收束截止修复后，持久 JSON 会话与预算账本实现前）：阶段③ **364 passed**；连同阶段②、阶段①特征和 Q13 录制回归共 **801 passed、1 skipped**（179.43 秒），Ruff 与 `git diff --check` 通过，新增 LLM 调用为 0。两批各 22 份录制全部重跑：[1b-1 报告](../internal/solver-runs/graph-guided-stage-three/acceptance-1b-budget-20261019-01/1b-1/index.html)、[1b-2 报告](../internal/solver-runs/graph-guided-stage-three/acceptance-1b-budget-20261019-01/1b/index.html)。[嵌套根式与预算调试报告](../internal/solver-runs/graph-guided-stage-three/acceptance-1b-budget-20261019-01/budget-probes/index.html)保留复现脚本、四组正确／错误候选的证明与端点证据、正常路线及超时路线：嵌套根式完整路线约 4.89 秒得到 `verified`；注入的 60 秒验证调用在 3 秒累计预算下终止并回收，验证累计耗时约 3.01 秒，路线为 `capability_gap`，保留 4 张数学卡片且无交接。预算回归覆盖四个收束边界、首次提交保存自定义预算、累计恢复与程序错误分类；进程测试覆盖线程调用、真实超时、父进程中断及清理。真实浏览器仍为完成前 4 张卡片、完成后 10 张卡片、2 份交接，刷新恢复成功且无脚本错误，[记录在此](../internal/solver-runs/graph-guided-stage-three/browser-1b-budget-20261019-01/browser-evidence.json)。此记录不包含本轮持久会话、ACK 截止及真实 SIGKILL 预算恢复，新全量计数和产物另行补记。`separation-restore-normalize` 例外继续保留 `pending_human_confirmation`，自动测试不代替人工确认。

**本轮验收记录（1c 前路线隔离门槛，2026-10-19）：** 阶段③ **404 passed**；连同阶段②、阶段①特征和 Q13 录制回归共 **841 passed、1 skipped**（219.07 秒），Ruff 干净。[验收总报告](../internal/solver-runs/graph-guided-stage-three/acceptance-pre1c-isolation-20261019-01/index.html)汇总 [1b-1 的 22 份录制](../internal/solver-runs/graph-guided-stage-three/acceptance-pre1c-isolation-20261019-01/1b-1/index.html)和 [1b-2 的 22 份录制](../internal/solver-runs/graph-guided-stage-three/acceptance-pre1c-isolation-20261019-01/1b/index.html)，保留正常、故障、预算和恢复诊断。旧的 364/801 记录及报告继续保留，作为本轮扩展前的对照。

真实 SIGKILL 覆盖两个恢复位置：计算在途时回收 worker、结算已耗预算并按剩余额度恢复，见 [inflight 运行报告](../internal/solver-runs/graph-guided-stage-three/acceptance-pre1c-isolation-20261019-01/process-recovery/inflight/run/index.html)和[恢复证据](../internal/solver-runs/graph-guided-stage-three/acceptance-pre1c-isolation-20261019-01/process-recovery/inflight/recovery-evidence.json)；计算已返回但发布尚未提交时复用回执、不重复数学计算或发布，见 [returned 运行报告](../internal/solver-runs/graph-guided-stage-three/acceptance-pre1c-isolation-20261019-01/process-recovery/returned/run/index.html)和[恢复证据](../internal/solver-runs/graph-guided-stage-three/acceptance-pre1c-isolation-20261019-01/process-recovery/returned/recovery-evidence.json)。

[本轮真实浏览器证据](../internal/solver-runs/graph-guided-stage-three/browser-pre1c-isolation-20261019-01/browser-evidence.json)记录完成前 4 张、完成后 10 张数学卡片，交接任务由 0 份增至 2 份，`refresh_restored=true`，浏览器错误列表为空。这组历史验证使用开发预览和共用事件消费者；随后 1c 的本机拍题页面、WebSocket 及问答附加验收另见 12.3。上一阶段代码已提交为 `c0868eae`，未 push；本轮新增的隔离与 1c 开发保留未提交，供审查。Demo 例外继续为 `pending_human_confirmation`。

#### 12.2.1 批次 1b-1：判别式法完整纵向闭环

内容：驱动器、判别式法与 `quadratic-inequality-solve` 执行契约、两张映射表、通用展示注册表，以及第 7 节批次 1 中判别式路线所需能力；范围目标收束、完整约束求交和第 10.1 节首批类别的独立临界分区验证；数学片段逐步提交、事件、恢复快照及阶段④交接清单。前端以 1a 固定的事件契约接收首条真实路线，用于提前展示冒烟。

验收：

- Q01 `discriminant` 为 `verified`，答案为 $a\le-1$ 或 $a\ge4$，两端点都取到，目标 `solved`；分离参数法仍为适用但执行能力缺口，区间最值法保持“可用、不优先、不生成路线”。
- 关系归一化的方向残差一致；`degree` 步骤记录“二次项系数为常数，不需讨论”且没有调用。轨迹与 Demo 原稿按 9.2 节对齐，例外登记表经人工确认。
- `a<1 ∧ ∀x∈ℝ:x²+a≥0` 得 `[0,1)`；未支持的额外条件和验证类别为缺口。Q01 错误候选 `[4,+∞)` 被独立验证拒绝，报告指出漏掉的左侧分区。变更参数符号或系数的同类题通过相同路径，不修改驱动器。
- 在最后一步设置测试屏障，前面的数学片段与事件已提交且可被读取，路线仍为 `running`，没有最终完成态或阶段④任务；解除屏障并通过完整校验后，才生成完成态和幂等交接。真实浏览器在屏障解除前已显示先前数学卡片，不只显示进度条。
- 数学片段含标题、条件、前后表达式与模板说明，不需要 AI 问题即可阅读。局部检查失败的步骤不发布，前缀与失败证据仍可调试。
- 判别式路线的数学片段按 9.2 节步骤边界金标映射到 Demo：每个保留的 Demo 步骤至少一个片段、无交错或跨步骤片段，`d_basis` 不成片；例外经人工确认。
- 进程在提交前／后中断并恢复，已提交片段、上下文、步骤 ID 与连续运行一致；未提交半成品不可读，同一步不会重复提交或发布。
- 0 次 LLM；两份 Q01 录制样本与金标路径结果相同，22 份录制完整回归符合当前能力边界。

#### 12.2.2 批次 1b-2：分离参数法与多路线

内容：分离参数法、`method-square-extremum` 子方法执行契约及配方技能，补齐第 7 节批次 1 能力；复用 1b-1 的上下文、验证、展示和提交机制，实现路线隔离、一致性验证及逐路线交接。方法差异通过执行契约、能力与展示注册表表达，不在驱动器中增加 Q01 或固定原式分支。

验收：

- Q01 `discriminant`、`extremum` 均 `verified`，答案为 $a\le-1$ 或 $a\ge4$，两端点都取到；两路线一致，目标 `solved`。区间最值法仍不生成路线。
- 分离参数法 `separate` 步骤在契约内完成分离检查，以 `already_separated` 的计算结果决定是否将两个公共调用记为 `already_satisfied` 跳过；任何实际交换、翻转或变形都须有调用轨迹与局部检查。先选量词策略、后求值域、再应用策略和真实移项，无未来绑定读取。
- 分离路线的轨迹与数学片段按 9.2 节对齐，`e_basis` 发布“参数已分离”说明片段；每个 Demo 步骤至少一个片段、无交错或跨步骤片段，例外经人工确认。判别式路线产物保持不变。
- 一条路线通过完整验证即可按第 11.1 节门槛交付，未完成的另一条路线不阻塞。两路线的上下文、步骤身份与恢复进度隔离；构造冲突或一致性未知时追加目标状态，阻止旧完成态与问答继续使用。
- 分离路线同样通过屏障提前交付、局部失败不发布、提交前后中断恢复与完整约束验证；同类变式不依赖题号或固定原式。
- 0 次 LLM；两份 Q01 录制样本与金标路径结果相同，22 份录制完整回归继续通过。

### 12.3 批次 1c：Q01 网页逐步展示与问答附加接口

**前置门槛验收记录：** 第 6 节的路线求解／验证隔离、受限 JSON 传输、父 ACK 后确认成功、持久预算和外部中断回执恢复已通过完整回归、真实 SIGKILL 恢复与浏览器验收（第 12.2 节）。门槛验证覆盖长时间调用、累计预算耗尽、计算完成而发布未提交、进程运行中断后的清理与恢复，以及超时保留前缀、无完成态或阶段④交接。此门槛不包含入口准入／选法隔离；下述 1c 页面功能单独验收。

内容：在 1a 后并行开发、1b-1 已完成提前展示冒烟的前端消费者基础上，完成双路线与恢复的全面接入。HTTP／WebSocket 共同读取阶段③持久流，页面按数学片段增量渲染，支持快照恢复；单片段编译由共用编译入口承担。开发拍题入口同步接入阶段③事件，不另建一套求解流程；具体入口见[学生拍题学页面设计](student-problem-search-design.md) 3.8 与第 6 节。阶段④以固定录制或构造的合格附加片段测试接口，本批不调用真实 LLM。

**本轮实现状态：本机开发入口已实现并通过验收。** 每个已保存的 `stage-two-<n>` 对应一个 `stage-three` 运行目录；页面获得其固定 `run_id/lesson_version/stream_id` 和运行限定的快照、HTTP 事件及 WebSocket 地址。读取不触发识图、判型或求解；显式 start 启动已有阶段②结果，显式 resume 先核对最新判型批次和冻结版本，重试判型另建批次。开发入口通过文件锁防止重复排队或跨进程并行改写同一题。本轮覆盖 Q01 双路线、D1–D4、独立数学阅读进度、快照恢复和构造问答附加；真实阶段④生成、正式登录／归属／额度与全部 S1–S5 上线验收仍是后续工作。

**审查前回归记录（2026-10-19）：** 阶段③ **405 passed**；阶段③、阶段②与阶段①特征相关回归合计 **841 passed、1 skipped**（290.22 秒，此计数不含学生拍题 `search` 测试）。[1c 验收总入口](../internal/solver-runs/graph-guided-stage-three/acceptance-1c-20261019-01/index.html)汇总录制与浏览器证据；其中[判别式闭环报告](../internal/solver-runs/graph-guided-stage-three/acceptance-1c-20261019-01/1b-1/index.html)和[双路线报告](../internal/solver-runs/graph-guided-stage-three/acceptance-1c-20261019-01/1b/index.html)各保留 22 份完整录制产物。

学生拍题后端最终回归 **82 passed**（65.36 秒），覆盖运行身份固定、旧批次读取不混入新批次状态，以及 start／resume 的排队与锁竞争；与上述核心测试合计 **923 passed、1 skipped**，两组独立运行、测试项不重复。前端最终回归 **93 passed**，覆盖阶段②进度迁移、双路线及跨小问切换、后台增量不打断 AI 回放、已读图谱、快照／重连与问答附加身份。修改文件的 Ruff 检查通过；全 `search` 目录另有 3 个既有检查问题，不属于本轮修改。

[真实浏览器验收报告](../internal/solver-runs/graph-guided-stage-three/browser-1c-20261019-05/index.html)与[机器可读证据](../internal/solver-runs/graph-guided-stage-three/browser-1c-20261019-05/browser-evidence.json)使用录制 Q01，从真实 `/lab/search/problem.html` 入口运行。完整验证前已有 **4 张**数学卡片；第一条路线单独完成后已有 **1 份**交接，最终为 **10 张**数学卡片、**2 份**交接及 **5 张**问答附加。学生模式实际阅读 **2 张**卡片后刷新，进度恢复成功；问答附加保持数学 DOM，目标冲突会撤销完成态与旧问答。记录包含 **20 帧** WebSocket、**1 次**游标过期及 **3 次**快照读取，浏览器错误列表为空，新增 LLM 调用为 **0**。[刷新后截图](../internal/solver-runs/graph-guided-stage-three/browser-1c-20261019-05/04-refreshed.png)保留人可复核的页面状态。

本轮只验收 Q01 已支持路线的开发入口交付，不扩大数学支持类别。Demo 的 `separation-restore-normalize` 例外仍待人工确认；批次 2 放宽支持类别前必须完成下节的分支隔离／合并与关系方向门槛。本轮隔离及 1c 新增代码尚未提交，保留供审查。

**1c 审查修订（2026-10-19）：** 页面此前在已有目标与可读流后停止题目状态轮询，只依赖数学事件推进；求解在发布终态前中断时，流可能不再增长，页面仍显示运行中而没有“继续计算”。现已将状态监控与片段消费分开：已有流时每 3 秒只读请求题目状态，`starting/running` 继续监控；初次打开已有流也启动同一监控。`interrupted/error` 且流身份可读时显示“继续计算”，显式恢复请求成功后立即后台监控并刷新快照，不等路线结束才恢复按钮。状态请求失败时保留已到达的数学 DOM、流身份与阅读进度，继续重试，不回到清空步骤的失败页。修复回归结果单独补记，以上历史计数不作为新增反例通过的证据。

| 本轮审查项 | 当前处理与后续要求 | 状态／门槛 |
| --- | --- | --- |
| P2：状态轮询提前退出 | 补齐已有流持续监控、初次进入已有流、`interrupted/error` 恢复入口、恢复请求后及时解禁及断线保留前缀 | 已修复；相关前端 102 passed，真实浏览器复核通过，此 P2 关闭 |
| 浏览器复测新增：裁剪与导出竞争 | `export()` 原先分别读取快照和事件，裁剪恰好发生在两次读取之间时抛出 `CursorExpired`，使运行中的路线被误记为 `execution_error`；导出与路线收尾现共用同一读事务的快照／事件读取，公开事件接口仍拒绝过期游标 | 已修复并补确定性并发回归，完整浏览器重跑通过；全量扫描的性能 P3 仍保留 |
| P3：快照全量扫描 | `snapshot()/export()` 扫描全部提交重建 `selection_chunks`，长路线成本随提交数增长 | 归入 12.2 的 P3#8，尚未优化 |
| P3：WebSocket 准入顺序 | 开发接口先 `accept()` 再查询运行；正式服务须在建立连接前校验运行，并检查登录与归属 | 本机开发入口保留；正式服务接入前处理 |
| P3：父进程边界 | 入口 Notation 准入、`build_context` 和 D3 选法仍在父进程 | 与第 6 节及 12.2 一致；不得表述为阶段③所有数学均已隔离 |
| P3：批次 2 与人工对齐 | 分支隔离／合并、关系方向仍未完成；`separation-restore-normalize` 仍为 `pending_human_confirmation` | 批次 2 放宽类别前通过两项门槛；自动测试不代替人工确认 |
| P3：正式服务与阶段④ | 正式登录、归属、额度及真实阶段④生成仍未接入 | 不在本批范围；构造问答通过不代表真实生成或产品上线完成 |

**审查修复验收：** 相关前端回归 **102 passed**，其中拍题流程 **18 passed**，覆盖已有流与初次打开的状态监控、`interrupted/error`、终态停止轮询、连续 12 次元数据请求失败仍保留步骤、过时响应隔离与显式恢复不等待整条路线结束。新增[浏览器报告](../internal/solver-runs/graph-guided-stage-three/browser-1c-review-20261019-04/index.html)及[中断态截图](../internal/solver-runs/graph-guided-stage-three/browser-1c-review-20261019-04/01a-interrupted-prefix.png)记录：验证屏障暂停期间不增加事件，页面无需刷新即出现“继续计算”；显式恢复请求 1 次，原数学 DOM 保留。该探针只构造执行状态响应与恢复回执，不宣称模拟了真实进程崩溃；进程恢复沿用既有后端测试。完整浏览器链路仍得到 4 张前缀卡片、10 张完整数学卡片、2 份交接、5 张问答，学生阅读 2 张后的刷新恢复成功；21 帧 WebSocket、1 次游标过期和 4 次快照读取，浏览器错误为空，新增 LLM 调用为 0。

本次后端针对性回归 **61 passed**：事件存储 **31 passed**（0.69 秒，含两个确定性并发裁剪用例），路线执行与拍题阶段③ API **30 passed**（134.50 秒）。并发用例在读取旧水位后由另一连接裁剪旧事件并提交新步骤，确认导出仍为完整旧快照，而公开旧游标仍被拒绝。修改的后端文件与浏览器验收脚本 Ruff、JS 语法检查、`git diff --check` 通过。本次没有重跑此前全部 923 项 Python 用例，不将两次计数累加为新全量结果。1c 本轮 P2 及复测发现的并发问题已关闭，剩余 P3 和人工例外按上述台账继续处理。

验收：

- 最后一步仍被屏障暂停时，网页已经显示前面的可读数学步骤，不能只显示进度条；全路线验证后出现答案与完成态。浏览器关闭或暂停消费不阻塞求解。
- WebSocket 和 `after_seq` 游标轮询得到相同的片段序列；断线、刷新、重复事件、乱序到达、旧版本迟到事件及游标过期均正确恢复，不重复卡片或漏步。
- 已有流且执行仍在 `starting/running` 时继续低频监控题目状态；无新事件的 `interrupted/error` 也显示恢复入口。状态连接失败和显式恢复均保留数学 DOM 与阅读进度，恢复按钮不等待整条路线计算完成才可用。
- 进程在提交前／后中断并恢复，已提交片段、上下文、步骤 ID 与连续运行一致；未提交的半成品不能出现在网页。
- 一条路线 `verified` 即可交接阶段④，其他路线仍运行不阻塞；已知数学失败或冲突的路线不得启动问答。
- 构造问答按原 `step_id` 与双重内容哈希附加；错版本、错步骤或数学内容修改被拒绝。问答完成、部分失败、重试均不改变正文、顺序、数学完成态、阅读位置与已作答记录。

### 12.4 批次 2：Q02、Q03 判别式法的退化情况

内容：`degenerate_branches` 分类、`degenerate_case_check`、`merge_cases`。

**放宽支持类别之前的门槛：** 先完成 P3#2 的情况隔离、全部分支执行、子调用输出收集与带来源的合并，覆盖遗漏分支和错误交并的反例；再完成 P3#3 的关系方向传递与求解，覆盖关系左右交换、乘负数后的方向变化及相关严格／非严格边界变式。每项须在独立完整性验证下比较完整解集；尚未支持的变式继续给 `capability_gap`。两项通过前，不将退化或新增关系类别从缺口改成已支持，也不声称分类能力已完成。

验收：Q02 答案 $(-1,0]$，Q03 答案 $\left(-\frac35,1\right]$；Q03 的 $a=1$ 保留、$a=-1$ 排除，均在轨迹的情况路径中可见；人工路线引用覆盖 `method-discriminant#degree`、`linear-interval-extremum`、`quadratic-function-properties#definition`、`method-discriminant#merge`。

### 12.5 批次 3：Q04、Q05 区间最值法（不分类）与分离参数法（除以正数）

内容：`separate_parameter` 除以正数、量词策略的 ∃ 与边界取不到处理、`endpoint_values_extremum`、`quadratic_interval_range`、`reciprocal_range`（$x>0$）、条件交并。独立验证同步覆盖开区间、严格不等式和存在量词。

验收：Q04 两条路线答案都为 $m<-5$，Q05 两条路线答案都为 $m>-5$；Q05 的轨迹体现开区间最大值取不到时等号的处理；人工路线引用覆盖 `reciprocal-sum-function`、`skill-reciprocal-range`、`inequality-properties#multiplication`、`method-interval-extremum#conditions`。

### 12.6 批次 4：Q06、Q07 分离参数法（除以负数、倒数）与区间最值法（分类）

内容：`separate_parameter` 除以负数并变号、`reciprocal_range`（$x<0$）、`reciprocal_of_range`、`parametric_interval_extremum`（按对称轴位置、按首项系数符号含常数情形）、`linear_range` 的常数情形。

验收：Q06 两条路线答案都为 $a\le2\sqrt2$，Q07 两条路线答案都为 $m<\frac16$；Q06 分离时的变号、Q07 区间路线 $m=0$ 的常数情形（`skill-linear-range#constant`）在轨迹中可见；Q07 `extremum` 路线覆盖 `function-monotonicity`、`skill-inequality-transform#reciprocal`。

### 12.7 批次 5：Q08、Q09 更换主元法，及扩展目标

内容：更换主元法执行契约、`reorder_by_variable`、`linear_range` 斜率符号判断、按量词对二次不等式解集求交或并。

验收：Q08 答案 $\left(\frac{1-\sqrt5}2,\frac{1+\sqrt5}2\right)$，Q09 答案 $(-1,1)$；Q09 斜率 $x^2-x$ 符号不定，判断结论为“两端都要满足”。至此 Q02–Q09 人工课程的全部路线 `verified`。

存在量词变式必须覆盖：`∃a∈[-1,1]:ax²-(a+1)x+1>0` 取两端条件的并集，答案为 `ℝ\{1}`；`x=2,a=1` 是有效见证，不能被原题的交集规则排除。全实数存在题不能触发恒成立判别式分支。

扩展目标：不新增能力，直接运行 Q10（1）、Q10（2）、Q11（2）的计划路线，按答案金标校验：Q10（1）$-\sqrt3\le a\le\sqrt3$，Q10（2）$a>\sqrt3$，Q11（2）$m<\frac67$。结果写入报告；能力缺口或失败登记为后续工作，不计入本计划完成判据，但不允许出现与金标不一致的 `verified` 路线。

### 12.8 批次 6：参数最小值、最大值与学生上传路径

内容：`finalize_goal` 的极值分支、类型化答案、目标收束证据及调试展示；复用此前求解与独立验证能力。

验收：

- Q13 真实录制经重新验证进入 `student_upload` 阶段②、阶段③，分离与区间两路线均 `verified`，完整可行集 `[-5/2,+∞)`，最小值 `-5/2`，目标 `solved`。题图、原始提取与复核证据、约束和收束结果可在报告中追溯。
- 反号最大值变式 `∀x∈(0,1/2]:x²-ax+1≥0` 求 `a` 最大值：可行集 `(-∞,5/2]`，答案 `5/2`。
- 严格不等式变式 `∀x∈(0,1/2]:x²+ax+1>0` 求最小值：可行集 `(-5/2,+∞)`，最小值不存在，下确界 `-5/2` 未取到；原 Q13 改求最大值为向上无界；加条件 `a<-3` 后为空集。均给出对应类型化答案，不能混为能力缺口或以无穷作最值。
- provider 工厂仍打桩为抛错；本次执行语义调用及网络尝试为 0，历史真实提取与复核调用数单独展示。

## 13. 测试与文件

| 测试 | 要求 |
| --- | --- |
| 契约 | 选法契约的分支与规则节点一致；执行契约通过 5.2 节自检，区间最值 `select` 的规则分支来源有效；拒绝规则外公共调用；两张映射表引用的技能、方法、知识锚点都存在 |
| 输入准入 | `acceptance/student_upload` 分别沿用原准入要求，Q13 不补造评测状态；相对引用与规范哈希可复核；契约错误、`status` 为 `input_error/failed`、引用缺失或哈希不符、准入策略非法、目标无法解析，均输出 `input_error`，不执行评估，报告可打开 |
| 完整题设 | 主量词外 `a<1` 与 `∀x∈ℝ:x²+a≥0` 合并得 `[0,1)`；祖先条件继承、兄弟条件隔离、定义展开、参数域与原始分母非零条件均保留；未知额外条件为缺口，不能丢弃 |
| 逐目标准入 | `unsupported`、`selection_failed` 目标为 `skipped`，不影响同题其他目标；`primary_source=llm` 准入 |
| 未收录题型 | 构造主要题型没有选法契约的目标：`unsupported_type`，不生成 D3/D4 |
| 前提检查 | 3.3 节每个检查对 Q01–Q11 的结论与证据；特征改为 `unknown` 时结论为 `unknown` 而不是 `fails`；反例：除数在区间内变号、参数以两种形式出现、斜率可为 $0$ |
| 选法金标 | 原有 12 个目标及单列 Q13 的结论等于 `selection.gold.json`；推荐策略各条规则含兜底均有覆盖；`∃` 不触发恒成立判别式分支 |
| D3、D4 | Q01 与 Demo 原稿逐项对照；`unknown` 分支不进 `verdicts`；各批次之间 D3 不变；全实数存在变式的本格 `coverage` 只含 `fit` 分支（区间最值法在、判别式法不在）；构造全部分支未触发或不适用的目标为 `no_applicable_method`，不生成 D3/D4 |
| 能力 | 每个能力的正例、边界（重根、无实根、端点取不到、空集、全体实数）和能力缺口输入；Q01 正确反向移项通过、错误比较方向失败；量词策略全部方向及严格性组合、空定义域、无穷界；运算列表与知识依据 |
| 驱动器 | 拒绝循环依赖、未来绑定及分支局部绑定泄漏；量词策略先选择再应用；条件调用互斥、子方法返回、情况隔离与合并、判断未知、LLM 节点缺口、超时异常保留轨迹前缀、路线间不共享绑定 |
| 通用性 | 变量重命名、同类系数／区间变式、等价关系及额外参数条件不修改驱动器即可计算或明确报告数学能力缺口；禁止题号或原式查表；输入绑定不依赖字母或题设数组位置 |
| 数学片段 | 表达式、标题参数与依据均来自轨迹；每个有意义数学操作可追溯；未完成路线已发布前缀；条件分支身份明确，局部通过不冒充整题完成 |
| 步骤边界 | Q01 片段按 `demo-step-alignment.json` 映射到 Demo 课程步骤，覆盖 `omit` 步骤不成片、全跳过步骤发布说明片段、无交错与跨步骤片段；Q02–Q09 每个人工课程步骤至少一个片段且顺序一致 |
| 持久化与恢复 | 输出、绑定增量、片段、快照水位与事件提交一致；一个能力的首个子调用已发布而后续子调用中断时仍可恢复；重复投递、重启恢复不产生新步骤或丢失已提交步骤；版本改变拒绝原地续跑 |
| 目标状态 | 路线一已交付后，路线二揭示冲突或一致性未知：通过 `lesson.goal_status` 停止使用旧完成态并拒绝迟到问答，保留独立路线校验状态；不影响其他小问 |
| 网页增量 | 测试屏障证明首步在末步完成前已渲染；WebSocket／轮询同源；断线、刷新、重复、乱序、游标过期和旧运行迟到均可恢复，求解不等待浏览器 |
| 阶段④边界 | 只在本路线完整验证后幂等交接；按目标作用域、固定步骤 ID 与数学片段／路线哈希附加问答；同题两个小问使用相同路线名不串线；失败仅影响问答，不能改公式、重排或重置学生进度 |
| 量词端点组合 | Q09 的 `∀` 交集与 `∃` 并集；斜率为零、方向相反、严格比较；开端点不能套闭端点规则 |
| 校验 | 原题独立临界分区必须拒绝 Q01 `[4,+∞)`，覆盖漏段、多段、空集/全实数错误候选、孤立点、端点开闭、额外参数截断、原分母极点、恒零临界多项式；证明或精确比较未知为缺口；两个已验证结果不一致为 `conflict`，一致性未知不发布答案 |
| 验证覆盖边界 | 1b-1 覆盖第 10.1 节首批类别的同类变式与明确拒绝样例；每批新增求解类别同步增加完整证明回归，未覆盖时保持 `verification_incomplete`；最终覆盖第 10.1 节全部承诺范围，包括题库未出现的有理函数系数与实代数端点，不以 Q01–Q13 样本通过代替类别覆盖 |
| 目标收束 | Q13 及第 12.8 节最大值、有限界未取得、无界、空集变式；保留原 `goal.kind`、完整可行集和类型化答案，未完成收束不能 `solved` |
| 路线金标 | 各批次路线答案等于 `answers.gold.json`；Q01 按 9.2 节对齐 Demo；Q02–Q09 按 9.3 节覆盖人工路线引用 |
| 录制路径 | 24 个目标的选法结论、路线状态和答案与金标路径相同 |
| 学生录制 | Q13 从真实提取/复核证据重验后经当前阶段②进入阶段③，两路线与目标收束一致；不得手填 `confirmed/passed` 绕过验证 |
| 零 LLM | provider 工厂打桩为抛错；所有测试中语义调用与网络尝试为 $0$ |
| 确定性 | 同一题意与契约版本两次运行，除运行／课程身份、事件时间与耗时外，数学结果、展示内容和每路线顺序相同；同一运行恢复保持原 ID |
| 报告 | 成功、能力缺口、校验失败、输入失败均能生成自包含报告；支持事件回放，数学步骤／路线校验／问答状态分别显示；无远端资源 |

文件：

| 位置 | 内容 |
| --- | --- |
| `site/data/knowledge-next/selection/rule-quadratic-method.json` | 选法契约 |
| `site/data/knowledge-next/execution/*.json` | 六份方法执行契约（含展示单元），`skill-capabilities.json`、`basis-operations.json`、`presentation-registry.json` |
| `server/shuxueshuo_server/graph_lesson/stage_three/` | `contracts`（准入与 Schema）、`context`（完整可见约束）、`selection`、`premises`、`driver`、`capabilities/`、`judgments`、`verification`、`goals`、`trajectory`、`presentation`（数学片段）、`events`／`checkpoint`（提交与恢复接口）、`handoff`（阶段④引用清单）、`runner`、`report`、`cli`，以及 `snapshot_mapping.md` |
| `server/shuxueshuo_server/product/`、`server/shuxueshuo_server/search/` | 持久事件、快照／游标与 WebSocket／轮询适配，阶段③任务及阶段④幂等交接；共用求解与片段契约 |
| `site/assets/graph-walk/`、`site/lab/search/`、`tools/build-graph-walk-demo.mjs` | 单片段编译、增量数学步骤、问答附加与图谱／阅读进度保持 |
| `server/tests/solver/test_graph_stage_three_*.py` | 上表测试 |
| 产品／拍题服务与网页对应测试目录 | 事件投递、恢复和真实浏览器增量渲染测试，阶段④接口用固定片段，不调用 LLM |
| `server/tests/solver/fixtures/graph-guided-stage-three/` | `selection.gold.json`、`answers.gold.json`、`demo-step-alignment.json`、`demo-alignment-exceptions.json`、构造反例输入 |
| `internal/schemas/graph-stage-three-result-v1.schema.json`、`graph-stage-three-route-v1.schema.json`、`graph-method-selection-v1.schema.json`、`graph-method-execution-v1.schema.json` | 结果（含 D3/D4 定义）、轨迹、选法契约与执行契约 |
| `internal/schemas/graph-math-step-v1.schema.json`、`graph-stage-three-event-v1.schema.json`、`graph-stage-three-checkpoint-v1.schema.json` | 数学片段、离线／在线共用事件负载与可恢复执行快照；本机 HTTP／WebSocket 适配读取相同 EventStore |
| `internal/solver-runs/graph-guided-stage-three/` | 运行输出（gitignore） |

选法金标和答案金标按各题原文、人工课程与 Demo 原稿独立编写，不从程序输出抄回来再标为正确。人工路线引用直接读取 `topics/quadratic-always.json`，不复制。

## 14. 完成判据

- [ ] 阶段②不合格结果被入口拒绝，输出 `input_error`；未确认目标为 `skipped`，不阻断同题其他目标。
- [ ] Q01–Q11 全部 24 个已确认目标（12 个不同目标）的选法结论与金标一致；D3、D4 由程序生成，Q01 的 D3 与 Demo 原稿一致。
- [ ] 推荐与能力缺口不改写适用性；能力补齐前后 D3 不变。
- [ ] Q01 两条路线不调用 LLM、全部 `verified`，结论为 $a\le-1$ 或 $a\ge4$ 且两端可取；轨迹调用位置和依据与 Demo 原稿一致，数学片段边界映射到 Demo 课程步骤，例外经人工确认。
- [ ] Q01 区间最值法保留“可用但不优先”，不生成独立路线。
- [ ] Q02–Q09 人工课程的全部路线 `verified`，答案与人工课程一致，轨迹覆盖人工路线引用。
- [ ] 完整题设均有来源和处理记录；`a<1 ∧ ∀x∈ℝ:x²+a≥0` 得 `[0,1)`，不支持的额外条件为缺口。
- [ ] 独立完整分区证明覆盖第 10.1 节本期最终支持类别及其全部可行集，拒绝 Q01 漏左段的候选；仅有抽查、题库样本通过或未定符号结果不能替代完整证明，未覆盖输入不能 `verified`。
- [ ] 判别式法不接收存在量词；Q09 存在变式答案 `ℝ\{1}`，与全称端点交集规则分开。
- [ ] Q13 学生上传录制两路线均 `verified`，可行集 `[-5/2,+∞)` 与最小值 `-5/2` 分别保留；最大值、未取得、无界、空集回归通过。
- [ ] 判断节点全部由程序判定并在轨迹中可见；全部测试 0 次 LLM。
- [ ] 同类变式无需修改驱动器；角色、作用域与输出引用传递上下文，数学展示不依赖题号或固定原式。
- [ ] 最后一步尚未结束时，网页已展示先前通过局部检查的数学步骤；没有阶段④问答也能阅读完整推导。
- [ ] 数学片段的步骤 ID、正文及顺序冻结；阶段④只在本路线 `verified` 后附加问答，失败不影响数学结果或学生进度。
- [ ] WebSocket／游标轮询同源，断线重连、快照补读、重复／乱序事件、旧运行隔离与执行恢复通过；求解不等待前端。
- [ ] 能力缺口、数学校验失败、执行错误分别报告；错误答案构造样例被独立判定器拒绝。
- [ ] 录制路径与金标路径结果相同；同一输入两次运行结果确定。
- [ ] 自包含离线报告覆盖选法、D3/D4、完整约束、路线轨迹、分区证明、反例、目标收束、数学片段、提交事件与对齐差异。

## 15. 运行与调试

入口为 `shuxueshuo_server.graph_lesson.stage_three.cli`，在 `server/` 执行。已实现 `run`、`batch`、`report`、`resume`、`events`、`serve`；新运行的输出目录必须是新目录。正常完成返回 0；`input_error`、`partial`、`failed` 返回 1。本阶段不调用 LLM，因此没有 LLM `record/replay` 子命令，也不需要 `RUN_LLM_INTEGRATION`。

默认 `milestone=1b`：在当前支持类别内执行判别式和分离参数路线；`--milestone 1b-1` 只启用判别式执行。`--milestone 1a` 保留原选法验收模式，不执行求解、事件或恢复。各模式的 D3 不变；支持的 D4 路线计划改为 `planned`，尚未支持的保持 `capability_gap`。顶层 `completed` 表示本批处理完成，目标 `solved` 和路线 `verified` 才表示完成数学解答。

1b 当前产物包含第 11.3 节的路线、数学片段、持久事件、恢复快照和阶段④交接清单。`events.sqlite3` 是权威状态；`events.jsonl`、`checkpoint.json` 是可调试导出，导出中断不改变已提交进度。路线文件包含完整题设处理记录、调用和判断、独立分区证明、边界检查及范围目标收束。报告内嵌本地 KaTeX，以 MathML 显示公式；可通过事件游标回看已发布数学卡片，无远端资源。

从阶段①录制完整重跑阶段②（离线）与阶段③：

```sh
.venv/bin/python -m shuxueshuo_server.graph_lesson.stage_three.cli batch \
  --stage-one-batch tests/solver/fixtures/graph-guided-stage-one/recorded/live-v2-20261017-02 \
  --output ../internal/solver-runs/graph-guided-stage-three/my-offline-run
```

读取一个阶段②结果：

```sh
.venv/bin/python -m shuxueshuo_server.graph_lesson.stage_three.cli run \
  --input /absolute/path/stage-two-result.json \
  --output ../internal/solver-runs/graph-guided-stage-three/my-single-run
```

重建已有运行或批次的离线调试报告（不重新求解）：

```sh
.venv/bin/python -m shuxueshuo_server.graph_lesson.stage_three.cli report \
  --run ../internal/solver-runs/graph-guided-stage-three/my-offline-run
```

`batch --case q01` 可只重验 Q01 的两个录制样本，完整验收仍使用默认全部样本。若阶段②同目录 `input.json` 缺失，且只保留相对来源引用，`run --reference-base <明确基准目录>` 指定该引用的基准；不会猜测相对路径。

后续拟增加只执行指定路线的调试选项：`run ... --target /root/goals/0 --route extremum`（结果标记为部分运行，不作为验收）。当前 CLI 尚未提供这两个选项；首条路线验收可用 `--milestone 1b-1`。

`resume --run <运行目录>` 核对输入、契约、能力及展示版本后，从 SQLite 最后一次提交恢复；已终态路线不重新计算，重复恢复不会重复步骤、事件或交接任务。`events --run <运行目录> --after-seq <序号>` 读取已提交增量。`serve --run <运行目录> --port 8783` 提供仅监听 `127.0.0.1` 的只读开发预览，网页轮询 `/events?after_seq=…` 并通过 `/snapshot` 恢复；计算仍由另一个 `run`／`resume` 进程推进，不等待网页消费。离线报告事件播放只重建视图，不重新计算或触发阶段④。

`run` 可配置 `--solve-budget-seconds`（默认 10）与 `--verification-budget-seconds`（默认 20）。路线初始化、方法推进及验证收束通过受监督的持久 JSON 数学会话执行，SQLite 账本保存预算与逐次 attempt／receipt；`compute_seconds`、`verification_seconds` 累计实际用量，未知回执的保留上界另存，恢复不能重置消耗。耗时含启动、编码和传输，测试钩子、持久化与空闲等待不计；超时回收数学 worker，保留前缀且不交接阶段④。验证超时为 `capability_gap/verification_incomplete`，求解超时为 `execution_error`。父进程在路线边界只接收有界 JSON；入口 Notation 准入、`build_context` 与 D3 选法仍走现有路径（第 6 节）。1c 本机开发拍题页面接线的实现与验收状态见 12.3，正式学生服务接入尚未完成。运行时仍按已注册数学类别限制输入；尚未支持的区间、退化、存在量词或极值收束如实报告缺口，不由 LLM 补算。

Q13 的学生录制集成测试复用 `test_parameter_extremum_recorded.py` 的 `revalidate_recording()`，核验历史真实提取与复核证据，再经学生拍题入口生成阶段②输入并调用 `run`；沿用 `student_upload` 准入，不补造评测通过状态、不冒充阶段①验收批次格式。批次 1a 验收其选法和原始 `find_minimum` 目标保真，最小值计算仍属于批次 6。

全部阶段③离线测试：

```sh
.venv/bin/python -m pytest -q tests/solver/test_graph_stage_three*.py
```

设置 `GRAPH_STAGE_THREE_RUN_DIR` 可保留 1a 录制回归产物；设置 `GRAPH_STAGE_THREE_1B_RUN_DIR` 可将两个 1b 里程碑的全部 22 份录制产物分别保存在 `1b-1/`、`1b/`。真实浏览器冒烟使用已安装的 Playwright 和 Chrome，示例：

```sh
PLAYWRIGHT_MODULE=/path/to/playwright CHROME_EXECUTABLE=/path/to/chrome \
  .venv/bin/python tools/smoke_graph_stage_three_browser.py \
  --output ../internal/solver-runs/graph-guided-stage-three/my-browser-run
```

该测试先暂停首条路线，再检查网页中的真实数学卡片与未发布完成态，继续运行后检查双路线答案和刷新恢复；保存前后截图及 `browser-evidence.json`，不会调用模型。
