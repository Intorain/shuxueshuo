# 出处验收协议修订 2（2026-10-16）

> **2026-10-16 补充：** 本文记录的是 v1 契约（含出处锚点与约定声明）的运行与验收。阶段①已精简为 v2 契约，出处与约定机制已删除，见[阶段①实现计划第 0 节](../../../graph-guided-stage-one-implementation-plan.md#0-v2-精简修订)。文中 `recorded/` 下的 v1 录制已移出受版本管理目录，归档在本机 `internal/solver-runs/graph-guided-stage-one/archive-v1/`，相关链接不再有效。

本次将九题的出处验收统一升级为 `graph-stage-one-acceptance/v2`、`revision: 2`。它是验收协议修订，不是模型通过记录；不会改变先前真实批次或录制目录中的 `fixture`、`frozen.json`、调用记录与历史成绩。

## 修订依据与范围

将出处验收统一改为按数学语义分型的最小完整证据：所有语义组件必需，同义量词证据可择一，目标只在原请求位置定位；不要求无数学意义的叙述前缀或系词。依据九题原文与独立数学金标统一编写，不按模型候选反推判据，不改变数学、图片、出处上下文或特征金标。

原题来源仍为 `site/2/qNN/index.html` 的 `.problem-card > p[data-math-text]`，冻结题文见各题 `problem.md`。编写证据组件只使用原题与未改变的 `notation.gold.json`、`source-map.gold.json`；不根据模型是否命中来增删数学要求。每题 acceptance 的 `authoring_basis` 保存来源 HTML、选择器及题文和金标 SHA-256。

本次只变更九份 `acceptance.json`、九份 `source-manifest.json`、[总 manifest](../../../../server/tests/solver/fixtures/graph-guided-stage-one/quadratic-always/manifest.json) 和本文。九题的 `problem.md`、`source.png`、`notation.gold.json`、`source-map.gold.json`、`features.gold.json` 共 45 个文件 SHA-256 均保持不变。原先的长出处片段继续作为定位上下文。

## 统一证据规则

`required_evidence_components` 中所有组件都必须满足；一个组件的 `alternatives` 可任选一组，但组内的每个 quote 都必须覆盖。同义词只在原文确实同时存在时列作备选，不凭空改写题文。

- 每个 quote 必须在该数学字段的金标出处窗口内定位，再检查模型自身出处是否覆盖同一原文位置。
- 目标拆成 `goal_target` 与 `goal_kind`；目标字母必须位于原请求范围，题文其他位置的同名字母不能代替。
- 显式目标实数域需要“实数”和对应目标字母的证据。Q01–Q08 保留此事实；Q09 不新增。
- 量词事实分解为域、数学关系与量词证据。Q02/Q03 没有显式域，继续要求两条经过验证的约定：隐含量词变量与默认实数域。
- Q08/Q09 的 y 定义和原文 y 不等关系是两个独立必需组件，不能只引用展开后的猜测。
- Q06 的“真命题”是独立必需证据；系词“为”不是数学要求。
- `required_goal/quantifier/bound_variable/domain/source_paths/conventions/features` 和 `equivalence_policy` 全部与 revision 1 一致。

## 九题量词事实的最小证据

下表使用原文数学形式；未将原文域替换为推导后的区间。“或”表示同一组件的备选，其余列同时必需。

| 题目 | domain | relation | quantifier | 其他必需组件 |
| --- | --- | --- | --- | --- |
| Q01 | `实数 $x$` | `-x^2+2x+3\le a^2-3a` | `任意` 或 `恒成立` | — |
| Q02 | 两条 verified conventions | `kx^2+2kx-(k+2)<0` | `恒成立` | — |
| Q03 | 两条 verified conventions | `(a^2-1)x^2-(a-1)x-1<0` | `恒成立` | — |
| Q04 | `1\le x\le2` | `x^2+mx+4<0` | `恒成立` | — |
| Q05 | `1<x<2` | `x^2+mx+4>0` | `有解` | — |
| Q06 | `x<0` | `x^2+ax+2\ge0` | `\forall` | truth_assertion：`真命题` |
| Q07 | `2\le x\le3` | `mx^2-mx-1<0` | `\forall` 或 `恒成立` | — |
| Q08 | `1\le m\le3` | `y<0` | `恒成立` | definition：`y=mx^2-mx-6+m` |
| Q09 | `-1\le a\le1` | `y>0` | `任意` 或 `恒成立` | definition：`y=ax^2-(a+1)x+1` |

每题另有目标位置的 `$目标字母$` 与“取值范围”组件；Q01–Q08 另有显式目标实数事实的 `实数 $目标字母$` 组件。

## 修订历史与哈希

各 source manifest 的 `gold_revision.history` 保留完整 revision 1 元数据、旧 acceptance SHA-256；当前 `acceptance_sha256` 指向 revision 2。总 manifest 逐题保存 acceptance 与 source manifest 的旧新 SHA-256。revision 1 acceptance 的原始文件仍可在 [第二轮冻结录制](../../../../server/tests/solver/fixtures/graph-guided-stage-one/recorded/live-20261016-02/batch-summary.json) 中找到，逐题引用已写入 `revision_history`，没有修改该录制。

| 题目 | 组件数 | acceptance revision 1 SHA-256 | acceptance revision 2 SHA-256 |
| --- | ---: | --- | --- |
| Q01 | 6 | `92a5b100173842bf0db22fd2b72ba5f3d7ead177737e419b27ec35b49d2db8b8` | `5c8a2be1d4bc9caba65debaebc89d35dc0de5bbd3c46f0ec260fc11598a2252d` |
| Q02 | 5 | `5ed938d8ec24d1a5d8f0fdbf9030fb0c79bf19d7d6f9470fe2a0cd874614fc03` | `4228ce99225d9cf55c369b45fdae7393f56bf22dc70fcbb39a0ba236951ffb3e` |
| Q03 | 5 | `a992e54322ca8862aa6ca2c9468f9087f2d476f4abebe47b5e981e97b5c48740` | `90cc3e2fc7756edeeeb34e5d8ab5c69bd28c3dd18c39729c69208ecb87faecde` |
| Q04 | 6 | `322da39c8f601f453cae078621067f270ab1fed1c0de6b6e1652d896d57a3ae4` | `e430ec48614cf1d1f1a442ca4c3b64482cfa75d8fa465e5e31aba6c95a6c5767` |
| Q05 | 6 | `8b88ec2364e9452ea0fb81a2f2e12dccaa855135379c1a252ec8995ef265b805` | `f61ab5311226062acacb7406eb23c508cffced176005db007e3e90aaff6fbce4` |
| Q06 | 7 | `aa4e79a41592bb4bc6f502ffb1b4794f2f2b6ef9045a23e2c21d6110c0a8d00d` | `620d0faa4d3f030d730fd311b907cafbee6c2dd5c30c2ee5a2eb7dd30b214166` |
| Q07 | 6 | `9e92bbd206105f7e46072d67a9cdda730d2c10837fbf82645e3401a89ab57f06` | `84c8823f4b2c9628d83d3175ca44bb85031855d4a93aac3d20bb4a9778ef0300` |
| Q08 | 7 | `a5f8dd6ba4e2f10ec611c7a32d9194d2fc4d78880904f8634788a271a5c1ee7b` | `d977070df69aa1c78aa795d4dce9d7f5f4e212a8b72c85799a85cb56075c4db8` |
| Q09 | 6 | `64555f76464c6cfb5a17fea2747980999ccbbc566c3104c521a02d68ccd9daef` | `d8b6bfef24979cfd83e29e88449e73a6b8b055fd2abef1e0f07b005030e2639a` |

总 manifest 旧 SHA-256：`171620e91dd79698df058d593f6cf3de02c8e67be707eb76b0b274fdbc6ff388`。
总 manifest 新 SHA-256：`61aa7bbfdf1d672f814b516aa4d522ad5643c71ceff8d595da284332f53dbbb8`。

本次独立静态核对确认：所有组件的所有 alternatives 都能唯一定位于该目标的旧金标出处窗口；45 个非验收输入文件的哈希保持不变；每题旧 acceptance 的 SHA-256 与第二轮录制对应文件一致。运行时 v2 评估与回归结果由实现验收另行记录，本文件不将协议修订宣称为真实调用通过。
