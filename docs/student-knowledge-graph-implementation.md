# 个人知识图谱：六阶段实现与验收

2026-10-08。代码及本地验收完成，已构建 linux/amd64 管理与 API 验收镜像；尚未制作正式发布包或上线。设计依据：[数据设计](student-knowledge-graph-data-design.md)。复用现有 PostgreSQL、账号、管理工具及备份流程，无需新增数据库服务。

## 1. 六阶段交付

| 阶段 | 已实现 | 验收要点 |
| --- | --- | --- |
| 1. 身份统一 | 基本不等式改用 `basic-inequality-qNN`，显式别名保留 `qNN`；迁移 `0008_practice_identity` | 新旧 ID 访问同一题；迁移保留学习标记与自评；冲突拒绝，不静默覆盖 |
| 2. 公共内容导入 | 迁移 `0009_learning_graph`；`learning/content.py` 校验后事务导入 | 重复导入幂等；错误整批回滚；题页／教师／专题步骤一致；公共内容应用账号只读 |
| 3. 节点五题检测 | 服务端抽题和规则判分；一轮五个固定题位，保存首答选项 | 并发开练只产生一轮；重试不重复计分；首答不可覆盖；账号隔离 |
| 4. 整题步骤记录 | `learning/practice.py` 与 `practice-records.js` 保存路线、上下文、正式提交、对话、提示展示和汇总 | 50 条路线可完整记录；真实模型对话保存；失败输入保留；排队重试与刷新恢复 |
| 5. 个人图谱 | 平面／立体图谱和详情页叠加本人节点状态；详情页查看关联步骤证据 | 小题完成后刷新状态；整题完成不自动认定节点掌握；退出账号清除个人显示 |
| 6. 发布演练 | `install / deploy` 接入内容导入；镜像包含导入资源；备份与独立恢复演练 | 独立 PostgreSQL 迁移、权限自检及恢复计数一致；不代表生产已发布 |

当前公共数据：2 个专题、39 道整题、50 条路线、259 个步骤、269 条步骤—节点关系；27 个图谱节点、8 条边、180 道节点小题。

## 2. 节点状态

| 状态 | 判断 |
| --- | --- |
| 未评估 `unassessed` | 没有完成过五题轮次 |
| 已掌握 `mastered` | 最近完成轮次首答 5/5 |
| 待巩固 `needs_review` | 最近完成轮次首答不足 5/5 |

**本轮五题全部完成后才更新。** 已掌握后中途做错仍保留旧结论；完成后可转为待巩固，再完成 5/5 可恢复已掌握。“练习中”是独立标记，已关闭轮次不影响结论。页面展示依据、正确数和完成时间，状态由最近完成记录推导，不复制一张成绩表。

## 3. 维护与接口

- 公共节点、边、专题映射继续编写 JSON；题页和教师 JSON 保留现有结构。发布工具读取全部原稿并比对路线、步骤、标题、顺序和作答契约。每一步可打开的图解（含全部条件分支）必须属于该步骤的节点映射；缺失时拒绝发布，并报告题目、路线、步骤和图解节点。
- 节点正文从图解 JS 的可读正文与公式提取，不另写一套。静态图解、样式和详情页继续作为文件发布。
- 小题原稿移到 `server/shuxueshuo_server/learning/drills/`，不再放在可直接访问的静态目录。生成的页面只保留节点 ID 和名称。API 首答前不返回答案、解析、干扰项反馈，对外选项 ID 使用中性编号；数据库保存原稿选项 ID。
- 原题、作答配置、判据及节点映射的校验摘要用于阻止同 ID 覆盖不同教学内容，不是题目版本系统。实质变更需分配新 ID；旧题与旧小题停用后保留历史记录。摘要对正文／判据变更采取保守拒绝，单纯页面排版、步骤标题不受影响。
- 整题按选定路线记录；规则提交无需模型。网络失败的队列保存在当前标签页的 `sessionStorage`，重试沿用事件 ID；服务端确认过的结论可恢复，不把系统恢复当作学生新作答。
- 记录请求在网络／传输失败、401（登录过期）、429（限流）或 5xx 时保留原操作及事件 ID。登录恢复或限流结束后可重试；刷新仍保留队列，账号切换不把旧队列交给新账号。其他 4xx 拒绝后移除该操作及依赖它的待保存操作，显示“刷新并继续”，刷新只读取服务端确认进度，不重放被拒绝的请求。开练请求的路线与已有进行中练习不同时返回 409 和已有路线，学生明确选择继续旧路线或重新开始；后者携带旧练习编号。开练确认先出队，再读取进度，恢复回调不阻塞已成功的记录。账号查询晚于登录组件挂载时，待账号确认后再读取该账号保存的队列与恢复选择。
- 恢复答案由服务端统一提供：沿步骤汇总对应的通过判定引用点选提交；若为导师对话通过，使用标准结论。网页与导师会话共用此结果，错误提交保留为历史，不作为已通过答案。
- 导师会话完成练习恢复后才登记；恢复失败或请求取消不占会话名额，也不淘汰已有会话。节点类型、边类型与前提环使用同一套校验，文件读取和直接发布入口均执行。
- `0010_learning_record_integrity` 增加节点 `is_active` 和事件 `displayed_at`。迁移保留旧展示时间并从 payload 移除该元数据；应用账号只允许更新展示时间，原始事件内容不可改写。内容发布停用移除的节点，清理旧专题及专题—题目关系，保留历史练习与步骤关联。
- 提示只在实际显示后确认；`hint_used` 采用服务端收到展示确认的时间，迟于通过的补报不反推为通过前帮助。

| API（均需登录） | 用途 |
| --- | --- |
| `POST /api/learning/drills` | 开始／继续五题轮次；明确重开须附旧轮次 ID |
| `GET /api/learning/drills/{id}` | 读取固定清单及首答 |
| `POST /api/learning/drills/{id}/answers/{position}` | 提交首答，服务端判分 |
| `GET /api/learning/nodes` | 本人节点状态与依据 |
| `POST /api/learning/practice` | 开始／继续整题路线 |
| `GET /api/learning/practice/{id}` | 查看本人的原始记录与已确认进度 |
| `POST /api/learning/practice/{id}/answers` | 规则判定并记录本步提交 |
| `POST /api/learning/practice/{id}/references` | 记录已展示的本步关联图解 |
| `POST /api/learning/practice/{id}/displayed/{event}` | 确认导师内容已显示 |
| `GET /api/learning/nodes/{id}/evidence` | 查看本人关联整题步骤，不作掌握评估 |

导师 API 支持绑定 `practice_attempt_id / practice_step_id`。服务端验证账号、题目、路线和步骤；学生消息先入库，模型调用不占用长数据库事务，完成后另存老师回复与判定。页面选法前尚未绑定路线的临时对话仍只在导师会话中；从选定路线开始保存步骤证据。

首期没有整题节点评估、自动跳步、语音录入／转写、任意填空判分和未提交输入的跨设备同步。小题现有原稿全部是单选、多选。历史教师文件与所引用资源须随停用题保留，不能删除仍被历史记录引用的文件。

## 4. 发布顺序

从仓库根目录校验与生成：

```sh
node tools/build-knowledge-pages.mjs --check
cd server
uv run python tools/publish_learning.py --check
```

首次安装已有管理命令 `install` 会完成迁移并导入内容。已有实例应按维护窗口执行 `deploy`，其中顺序为：禁止应用写入 → 备份 → Alembic 迁移 → 导入公共内容 → 权限／版本自检 → 恢复数据库登录。先停掉使用该实例的 API、Worker 等应用连接；工具不会强杀其他进程。

```sh
./deploy/product/manage.sh --mode local --data-dir /absolute/path/data --instance instance-name deploy
```

如已单独执行 `migrate`，还需导入内容：

```sh
./deploy/product/manage.sh --mode local --data-dir /absolute/path/data --instance instance-name publish-learning
```

首次上线或涉及接口／结构变更时，使用[产品部署流程](../deploy/product/README.md)：提交审核后的代码，构建发布包，停止旧应用，再用新包的 `server/deploy.sh` 更新数据，配套切换 API 与静态站点后恢复访问。参与同一次教学内容发布的题页、教师 JSON 和导入数据必须一致。

后续纯样式、布局及普通静态页仍可直接 `git pull`，无需重建 API。节点、图解正文、专题关联或小题变化时，需用包含新原稿的管理镜像执行 `publish-learning`；教师 JSON 或后端也变化时再同步更新 API。宿主机更新不会改变镜像内文件，详见[按改动区分发布方式](../deploy/product/README.md#个人知识图谱内容发布)。

静态站点采用完整目录切换；如用增量同步，必须删除旧的 `site/data/knowledge/drills/*.json` 和旧详情页中内嵌的小题数据，清理 CDN 缓存。不能只复制新增文件，否则旧答案仍可访问。教师 JSON 与私有小题目录不能作为静态资源公开。

静态模块修改后，版本号须沿引用链更新到 HTML 入口及页面生成模板，包括动态导入；只更新叶子模块 URL 无法绕过已缓存的旧入口脚本。本次题目 ID 迁移已同步更新图解、图谱、专题、详情页和练习入口的引用链。

检查新旧题目 ID 指向同一条标记、匿名接口 401、五题首答与中途续练、三种节点状态、整题 UI／导师记录和旧静态答案地址 404。部署失败保持维护状态；不要直接用旧 API 接新数据恢复写入。使用部署前备份恢复到新实例，核对计数和权限后再切换应用与同版静态文件。

## 5. 日常手动测试

固定使用 `local` 实例：网站 `http://127.0.0.1:8779/`，数据库 `127.0.0.1:5432/product`，持久目录 `~/Library/Application Support/shuxueshuo/local/`。从仓库根目录运行：

```sh
uv run --project server python server/tools/run_site.py
```

启动器自动启动或复用已安装的数据库。重启不会更换端口、目录、账号或登录密钥。详细连接和启停方式见[本地测试说明](site-login-local-testing.md)。

2026-10-08 已在备份后将 `graph-stage` 的学生记录迁入 `local`：173 个学生账号、144 条学习标记、47 轮小题、172 次整题练习、2,505 条过程事件和 809 条步骤汇总。逐条核对迁移数据并保留登录密钥与 218 条会话记录；原有 9 道产品题目、2,606 个产物保持不变。旧隔离目录保留作追溯，不再作为手动测试入口。下节中的临时端口属于自动化验收记录。

固定实例迁移前备份为 `backups/966f383632e147dd9aea229016b457ff`，合并后备份为 `backups/fca43836a47349c9a55090cb40beeb21`（均相对于上述数据根）。已通过数据库完整性自检、默认命令冷启动、浏览器刷新保留登录和节点状态验证。原隔离实例 `graph-stage / graph-restore` 已停止，数据目录未删除。快速重启的端口探测兼容 `TIME_WAIT`，另有两个真实回环端口测试，确认连接回收不误拦、其他服务监听时仍拒绝启动。

## 6. 验收记录

隔离实例 `graph-stage`，数据根 `/private/tmp/sss-graph-20261008`，PostgreSQL 17.10，端口 55449；模拟短信账号只用于本地。恢复实例 `graph-restore` 使用另一数据根与端口 55450，没有操作生产数据。

已验证：

- 数据库迁移／重复导入／冲突回滚；旧题 ID 迁移保持标记与自评。
- 并发开练、首答幂等、拒绝覆盖、五题完成才改状态、已掌握可回退、跨账号不可读写。
- 39 道整题的 50 条路线全部按真实教学规则记录完成，仍不改变节点掌握状态。
- 模型失败保留输入；真实模型提示和浏览器实际对话均落库；普通求助不记为错误作答。
- 浏览器完成五题、查看图谱已掌握状态、整题刷新续练后继续真实导师对话。
- 备份恢复到新实例，15 张学习相关表的记录数与备份清单一致；两实例 `doctor` 通过。新实例执行完整 `deploy` 成功。

回归结果：`tests/auth tests/tutor_demo tests/product/test_admin.py` 为 **471 passed、54 skipped**（45.33 秒）；最终学习记录／发布／队列专项显式启用真实模型后 **11 passed**（4.65 秒），覆盖真实提示、正确回答推进、重试去重及展示确认；不将默认跳过当作通过。日志位于 `/private/tmp/graph-acceptance-final.log` 与 `/private/tmp/graph-final-focused.log`。

记录完整性修复验收（2026-10-08）：新增先错选后对话通过、通过提交顺序恢复、发布清理与回滚、节点停用保留历史、旧展示时间迁移和应用账号禁止改写 payload 的测试。`tests/auth`、导师重试／本地练习及部署管理回归 **75 passed、1 skipped**；本轮未启用真实 LLM。浏览器记录器测试 **19 passed**。日常本地实例已备份并升级至 `0010_learning_record_integrity`，10 张学生记录表数量与备份一致，2505 条过程事件和 16 条展示确认保留；网页仍为 `8779`、数据库仍为 `5432`，浏览器节点状态可正常读取。

镜像验收（2026-10-08）：实际构建 `linux/amd64` 管理/API 镜像，标签均为 `learning-review-20261008`。
管理镜像使用 Debian bookworm 的 Node.js **18.20.4**，构建时内容校验通过；镜像内 `site/` 从整站约 110 MB
缩为管理镜像 **2.2 MB**、API/Worker 镜像 **4.5 MB**（不是镜像总大小）。管理镜像仅保留图谱原稿、图解模块、
题页与导出脚本；API/Worker 保留编译资源，排除小红书图片。

`tests/product/test_learning_image.py` 显式启用后 **2 passed**（20.27 秒）：独立 PostgreSQL 17.10 容器中，
只读、非 root 管理容器执行 `install`、两次 `publish-learning` 和 `doctor`，导入 27 个节点、39 道题、
259 个步骤、180 道小题；全部图解导出与本地一致。API/Worker 镜像实际编译独立题页成功，另验 API 模块加载正常。
测试数据库不映射宿主机端口；专用容器、数据卷及网络已清理，日常 5432 实例未参与。
构建与测试日志：`/private/tmp/learning-admin-image-build.log`、`/private/tmp/learning-app-image-build.log`、
`/private/tmp/learning-image-integration-final.log`。可复跑命令见[镜像验收说明](../deploy/product/README.md#个人知识图谱内容发布)。

缓存／会话修复验收（2026-10-08）：`tests/auth`、导师会话创建／主应用入口／图谱／重试／本地练习及部署管理回归 **121 passed、1 skipped**（10.96 秒），未启用真实 LLM。覆盖恢复返回 404／409／503、取消请求不消耗或淘汰会话，以及两个内容入口拒绝非法节点、边和前提环。重构前后全部导出数据相同，27 个详情页生成检查通过。恢复三个既有文件的原排版时已比对语法树；无关的 `review/dependencies.py` 保持原样。本轮修复晚于上述镜像验收，正式发布时须重新构建镜像。

测试命令（必须指定独立测试实例）：

```sh
cd server
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-graph-20261008 PRODUCT_TEST_INSTANCE=graph-stage \
  uv run pytest tests/auth tests/tutor_demo tests/product/test_admin.py -q
RUN_LLM_INTEGRATION=1 PRODUCT_TEST_DATA_DIR=/private/tmp/sss-graph-20261008 PRODUCT_TEST_INSTANCE=graph-stage \
  uv run pytest tests/auth/test_learning_graph.py::test_live_tutor_persists_original_dialogue -q
```

正式发布包、服务器切换及真实短信不在本次本地验收结果内。
