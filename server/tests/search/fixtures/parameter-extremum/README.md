# 参数最小值：真实 LLM 录制回归

题目：若 $x^2+ax+1\geq0$ 对所有 $x\in(0,1/2]$ 恒成立，求实数 $a$ 的最小值。

`recorded-20261018` 保留学生上传路径中的真实原图裁剪、识图与复核响应、脱敏请求、调用账本和修改前结果。原运行使用 DeepSeek，识图和复核各发生一次网络请求，复核为 `confirmed`。两次响应的 provider completion ID、token 用量、候选 revision 和账本请求/响应哈希均保留；不是手写的 confirmed 响应。原图只有这道题，没有页面其他题或应用截图。

`frozen.json` 是导出适配文件：implementation 来自原始 ledger 的 binding/files，图片哈希来自原始输入；其余证据文件未经改写。`recording.json` 校验导出文件的 SHA-256。响应内保留历史上传文件 ID 作为证据，但回放不读取远程文件；未保留 provider-attempts、密钥或带图片编码的 provider 请求，也不需要访问原电脑的用户运行目录。

回归先用既有 `verify_recorded_sample` 校验原始账本、请求、响应和图片，再用当前提取/复核契约校验原始响应。`source_reviewed` 由 confirmed 响应、finish_reason 和候选 revision 的一致性重新计算，随后重算数学特征，经过真实阶段二及 `search.lesson` 页面数据编排。阶段二还使用既有 `record_run` / `replay_run` 验证可移植回放。

默认离线运行，禁止创建 live provider 或连接网络：

```sh
cd server
.venv/bin/python -m pytest -q tests/search/test_parameter_extremum_recorded.py
```

保留人可调试报告（目录必须尚未存在，重复执行须换一个新目录，不覆盖历史）：

```sh
cd server
GRAPH_PARAMETER_EXTREMUM_RUN_DIR=../internal/solver-runs/graph-guided-stage-two/extrema-q13-20261018-01 \
  .venv/bin/python -m pytest -q -s tests/search/test_parameter_extremum_recorded.py
```

输出中的 `index.html` 链接原始识图/复核响应、历史未知特征、当前特征与题型检查、D1/D2、学生页面 JSON 和阶段二回放差异。历史真实调用为 2，本次新增模型和网络调用为 0；离线通过不代表又做了一次真实识图验收。
