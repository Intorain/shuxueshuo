# 学生讲解 demo

当前入口：纯页面 `/1/q12/explain/page/`，页面 + 对话 `/1/q12/explain/`。

每次学生选择完整操作或提交讲解后，LLM 在一次调用中生成本步数学推导、完整数学状态和下一批操作。首步单独生成候选。代码校验结构并原子保存，支持幂等重试、撤回和保留分支；数学内容没有经过独立代码验算，页面不显示“已验算”。双换元等一个选择只形成一张卡。

启动（需要本地登录数据库及服务端 DeepSeek 配置）：

```sh
cd server
uv run python tools/run_site.py --data-dir /private/tmp/sss-auth-stage1 --instance auth-stage1 --port 8768
```

具体数据库配置见 [本地登录说明](../../../../docs/site-login-local-testing.md)。密钥不进入页面。刷新页面或服务重启后需重新开始；只读静态服务不能生成推导。

实现入口：

- `generated_contracts.py`：通用题目、数学快照、推导与候选协议。
- `generated_session.py`：事件、原子快照、权限隔离、撤回与分支。
- `generated_llm.py` / `prompts/generate.jinja`：单轮推导与候选生成。
- `api.py`：当前运行路由。
- `site/assets/student-explanation/`：共用页面交互。

历史 Q12 专用验算器及 `legacy_api.py` 留作回归参考，不在当前服务挂载。题目公开数据只含题干、条件和目标；服务端另读取已有参考数学路径与 family spec 的通用解法，作为参考上下文，不执行旧 Q12 规则。步骤卡上层突出本步关键结果，下层展示具体数学推导。

设计与验收范围见 [会话上下文设计](../../../../docs/student-explanation-context-design.md)。
