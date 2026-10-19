# 阶段③轨迹与将来 ExplanationSnapshot 的对应

本阶段不构造 ExplanationSnapshot。每条路线对应未来的一份 snapshot；`math_steps` 对应不可改写的讲解步骤，以 `source_refs` 关联执行轨迹。`calls.outputs` 对应事实，`used_basis` 对应知识依据，`judgments` 对应分支说明，`case_path` 对应分类小节。

执行恢复使用 `graph-stage-three-checkpoint/v1`。`driver_state.frames` 保存方法调用栈、下一操作位置和精确数学绑定；绑定使用有白名单构造器的结构化编码，不执行字符串表达式。子方法完成后仅返回契约声明的输出。已发布片段的身份与正文哈希保存在同一次提交中。恢复执行快照与未来教学 ExplanationSnapshot 是两种独立数据。
