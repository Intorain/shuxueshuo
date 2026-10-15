# 恒成立 Q01 图谱解题 Demo

本地入口：<http://127.0.0.1:8779/lab/graph-walk/quadratic-always-q01/>。

学生先识别知识、判断题型与方法适用性，再选择判别式法或分离参数法。两条路线分别复用正式 Q01 的 6、5 个步骤，结论均为 $a\le-1$ 或 $a\ge4$。页面支持后退、换路线比较、图谱缩放平移和真实 AI 回放。Demo 不连接导师、不保存学习记录。

## 内容与代码

| 原稿或入口 | 职责 |
| --- | --- |
| `site/data/math-notation-v1/quadratic-always/q01.json` | 按现有 `problem-math-notation/v1` 表达题面 |
| `site/data/graph-walk/quadratic-always-q01.source.json` | D1–D3、实际调用位置、使用依据与通过后结果 |
| `site/2/q01/index.html`、对应教师 JSON | 原有交互、教学契约和图像模板 |
| `tools/build-graph-walk-demo.mjs` | 共享校验、数学编译、图查询、模板快照与页面生成 |
| `site/assets/graph-walk/walk-state.mjs` | 学生、录制、回放共用的输入投影、判定和状态 |
| `site/assets/graph-walk/walk.mjs`、`walk-graph.mjs` | 页面交互与固定布局的 SVG 图谱 |
| `site/assets/graph-walk/walk-graph-3d.mjs` | 默认的 three.js 三维图谱：题目在圆心，六列变成同心环的倾斜圆盘，随解题进度显示节点。控制区用“3D / 平面图”切换视图；接口与 SVG 版相同，WebGL 不可用时自动退回 SVG（`localStorage['gw-graph-mode']`） |
| `walk.mjs` 中的字幕与时间轴 | 每步一句字幕（AI 回放用其 `reason`，自己做用过程记录），T0…Tn 可点击回看、播放；回看只换图谱，不改作答进度 |
| `walk.css` 页面布局 | 桌面（≥960px）为一屏工作台：左侧作答列独立滚动，右侧整列图谱；3D 模式下图谱面板为深色（`#gw-graph-panel[data-mode="3d"]`），过程记录、依据、调用收成时间轴下的一排弹出按钮（`walk.mjs` 运行时包进 `.gw-panel-dock`）。手机端仍是全屏抽屉 |
| `tools/graph-walk-actor.mjs` | 录制器使用的 Node JSONL 桥 |
| `server/tools/run_graph_walk_actor.py` | 真实 DeepSeek 调用、纠错限制与私有审计 |

候选、关系和调用位置来自公共图谱；适用性与步骤反馈由人工原稿确定。LLM 只收到原题、当前候选、回答格式和当前路线已通过的结果，不收到预期答案、题型匹配标签、模板正文或未来结果。此 Demo 不实现通用规划。

图中关系保持公共语义方向，知识反查题型不会反转箭头。方法调用的发生位置、执行次序和实际使用的知识条目分别保存，不能将全部候选依据当作实际使用。配方路线保留“分离参数法 → 配方求最值法 → 配方技能”。

## 构建与录制

在仓库根目录运行，需现有 `server/.venv`，也可用 `GRAPH_WALK_PYTHON` 指定已安装项目依赖的 Python：

```sh
node tools/build-public-knowledge-graph.mjs
node tools/build-graph-walk-demo.mjs
node tools/build-public-knowledge-graph.mjs --check
node tools/build-graph-walk-demo.mjs --check
```

修改原稿后先完成构建，再录制。Demo 版本包含数学输入、共享判定、相关公共内容、题页配置、模板及编译器；旧版本回放不会在新版本上播放。不要手改生成的 bundle 或回放。

```sh
cd server
uv run python tools/run_graph_walk_actor.py \
  --bundle ../site/data/graph-walk/quadratic-always-q01.json \
  --output /private/tmp/graph-walk-q01-new-run
```

一次录制是一份连续回放：AI 在方法坐标图上自己选第一种方法并走完，录制器随后换到另一条路线（回放中记为 `{"switch_route": …}`），AI 只重走方法步骤；回放的 `routes` 按实际顺序记录走过的路线。页面进入“看 AI 解题”后自动播放这份回放，步骤卡随 AI 的提交逐张出现。

输出目录必须是新的私有目录，不得放入 `site/`。客户端复用现有 DeepSeek 配置。每个决策最多初答加两次纠正，超限保留失败，不填标准答案。每次模型调用（包含 SDK 内部重试）默认最多 120 秒，可用 `--call-timeout` 修改；这个总截止时间独立于 HTTP 读超时，持续心跳也不能延长它。录制器须在 macOS/Linux 主线程运行。超时记录为 `actor.provider_timeout`，失败回放和审计仅保存在私有输出目录。

两条路线均完成且通过共享状态机离线重放校验后，才更新 `site/data/graph-walk/replays/`。回放文件名同时包含题目版本和本次录制内容摘要；先写新文件，再原子替换索引，最后清理旧索引登记的文件。失败录制不会替换已有成功回放。公开目录仅保存版本、路线顺序及作答序列，私有记录另存请求、原始响应、反馈、时间和用量。网页不会调用模型。

## 2026-10-15 当前回放

当前公开回放由 Codex 在本次对话中逐步作答录制，页面入口统一标注“看 AI 解题”，录制来源保留在回放索引中。这不是 DeepSeek API 的成功录制：同日重试 DeepSeek 时，首步在 60 秒总截止时间后退出，失败审计保留在私有目录。

- 题目版本：`1b2417e602cfbbb45d00c37f5eec8492beefc5d7b688e7c318c15647d33366c4`。
- 回放文件：`site/data/graph-walk/replays/walk-1b2417e602cf-e4cbec1377ae.json`。
- 顺序：读题、题型与选法 → 判别式法 → 分离参数法，共 13 次作答和 1 次换路线，全部首次通过。
- Codex 根据桥接器逐步提供的当前问题和选项提交答案及简短理由，再由共享状态机判分；导出后再次完整重放，验证两条路线均完成。
- 两条路线的结论都是 $a\le-1$ 或 $a\ge4$，两个端点均保留。公开索引的 `recorder` 为 `Codex`，原 DeepSeek 回放已由与当前题目版本一致的本次回放替换。
- 本次录制不调用外部模型 API；私有来源说明和校验记录在 `/private/tmp/graph-walk-q01-codex-20261015/`，不属于公开交付文件。

## 2026-10-14 本地验收（历史记录）

- 公共内容版本：`45c9033e9d60644f1df90115c2d479811c074b3e34793dc972b2a4d43da89f6f`。
- Demo 版本：`31c63723bf6f457371f5454b7f882bae7a9ead627375091185c7cc7ae5fd9d51`。
- 图谱、专题关联、导出、Demo 构建和共享状态：57 项通过；新增真实回放一致性检查 1 项通过；UI 定向测试：6 项通过。
- 录制器：21 项通过，Ruff 通过。原 Q01 与共享教学契约测试：33 项通过，2 项既有可选在线导师测试跳过；跳过项不计为通过。
- 39 份正式题页的 `practice-config` 与提交基线相同，教师 JSON 和专题路线原稿未修改。共享 `PracticeContext` 仅公开已有纯判定函数，各题页同步资源版本。
- 两个构建器的 `--check` 均无差异；公开产物不包含私有小题题库或模型请求审计。
- 实际浏览器走完桌面判别式路线与 390×844 手机分离参数路线；确认错答拦截、修正推进、后退、换路线、键盘选择、公式换行与 SVG 图像。手机页面宽度与滚动宽度均为 390，没有横向溢出。
- 浏览器验证了两份 AI 回放及单步、暂停、从头播放；手机图谱抽屉、缩放、聚焦与 Escape 关闭可用。Demo 脚本和入口不引用练习 runtime、导师或记录接口。

真实模型返回身份为 `deepseek-flash`。一次连续录制：AI 在方法坐标图上自选判别式法，走完后换到分离参数法：

| 录制 | 模型调用 | 纠正次数 | 模型耗时 | Token 用量 |
| --- | ---: | ---: | ---: | ---: |
| 判别式法 → 分离参数法 | 13 | 0 | 64.82 秒 | 20,054 |

公开记录完成离线重放，结果与录制一致。私有审计目录为 `/private/tmp/graph-walk-q01-live-20261015T000134Z/`；临时目录不属于交付源文件。

本地已依次执行以下命令，内容和网站版本一致：

```sh
./deploy/product/manage.sh --mode local check-learning
./deploy/product/manage.sh --mode local publish-learning
./deploy/product/manage.sh --mode local verify-release \
  --site-version /Users/haorong/projects/code/shuxueshuo/site/knowledge/teaching/version.json
```

仍使用固定 `127.0.0.1:5432/product` 和本地数据目录。本次只做正常公共内容发布，未运行数据库迁移、重建、清理、镜像构建或生产部署。现有个人记录按原发布机制保留。
