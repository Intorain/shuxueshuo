# 阶段③轨迹与将来 ExplanationSnapshot 的对应

本阶段不构造 ExplanationSnapshot。每条路线对应未来的一份 snapshot；`math_steps` 对应不可改写的讲解步骤，以 `source_refs` 关联执行轨迹。`calls.outputs` 对应事实，`used_basis` 对应知识依据，`judgments` 对应分支说明，`case_path` 对应分类小节。

卡片的 `case_path` 与来源执行记录保持一致，`case_condition` 保存该执行情况的条件。同一执行情况内按开口方向展示时，另外用 `branch_id` 和非恒真的 `branch_condition` 标识展示分支，不把它们追加到执行路径。两个字段随卡片参与哈希并复制到交互种子；前端以执行路径和分支标识共同判断是否可以承接上一步结论。

执行恢复使用 `graph-stage-three-checkpoint/v2`，兼容读取旧 v1。`driver_state.frames` 保存方法调用栈、下一操作位置和精确数学绑定；绑定使用有白名单构造器的结构化编码，不执行字符串表达式。子方法完成后仅返回契约声明的输出。已发布片段的身份与正文哈希保存在同一次提交中。新检查点、轨迹与数学片段只引用运行级版本清单的 `revisions_ref`；旧卡片及其哈希保持原样。

浏览器读取 `graph-stage-three-snapshot/v2`，包含路线状态、卡片、图谱来源证据投影、答案／问答和事件水位，不包含内部 `driver_state`。刷新恢复视图不会触发重新求解；计算进程恢复则读取完整内部检查点。调试导出保留全部证据。展示快照、执行恢复检查点与未来教学 ExplanationSnapshot 是三种用途不同的数据。
