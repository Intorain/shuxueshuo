# 阶段三执行器：PostgreSQL 存储实施说明

更新日期：2026-10-24。本轮将 `graph_lesson/stage_three` 的执行权威存储接入现有产品 PostgreSQL，学生拍题与离线 CLI 共用同一实现。数学执行、事件、检查点、交互卡片、阶段四交接及预算回执协议保持不变；不修改 legacy Review 的存储。

## 1. 单一权威与范围

- 不再创建或读取阶段三 `events.sqlite3`，没有 SQLite fallback，也没有双写后端。
- 迁移 `0014_lesson_execution` 建立共享 `lesson_*` 表，以 `run_id` 隔离运行，不为每次运行新建 schema。`lesson_runs.identity` 固定运行身份，所有子表以运行外键级联。
- 数据包括事件与水位、提交幂等回执、路线检查点、数学步骤和哈希摘要、目标状态、选择片段、交互状态与卡片、阶段四交接与 QA，以及计算预算、占用和尝试回执。
- 运行目录仍保存冻结输入、`run.json`、调试导出和 supervisor 文件回执。`checkpoint.json`、`events.jsonl` 和导出 manifest 是可读视图，不是执行恢复权威。
- 旧 SQLite 运行只作历史归档，本轮不导入 PostgreSQL，不用旧 JSON 重建可写执行记录。只有本轮创建的 PostgreSQL 运行可继续恢复执行；保留旧输出并使用新目录发起新的离线运行。

## 2. 事务、隔离与生命周期

`storage_context(db, submission_id=None, clock=None)` 显式绑定产品连接、可选私有提交及生命周期时钟。学生 API、后台工作线程和 WebSocket 读取各自绑定提交范围；已有 `EventStore` 保存构造时的上下文，避免线程切换落回其他实例。无显式上下文的离线调用从现有 `Settings` 取得 PostgreSQL 配置，连接失败直接报错。

Web 请求通过可恢复的 ContextVar 强制要求执行器绑定具体提交，后台线程复制该约束；正式本地服务入口另设进程标志 `PRODUCT_EXECUTION_STORAGE_CONTEXT_REQUIRED=1`，使 spawn 子进程同样不能回退默认实例。缺少绑定或只有无提交的 CLI scope 时直接报 `events.storage_context_required`（HTTP 503 / WebSocket 1011），不尝试创建默认引擎。独立 CLI 未启用 Web 标志时保留原默认配置行为。

`EventStore.transaction(write=True)` 只包围短数据库变更，不覆盖代数计算、子进程等待或模型调用。搜索运行写事务采用页面、提交、公共题目、运行的锁顺序，页面使用 `FOR SHARE`，提交与运行仍使用排他行锁。这样同页不同题目的课程写入可以并发，删除和清理的页面排他锁仍会等待；检查提交仍存在、产物未到期且公共题目未停用，提交前再次检查 30 天期限。同一运行行锁串行化水位、幂等回执与预算更新。只读快照使用 PostgreSQL `REPEATABLE READ`，保证游标、物化状态与事件来自同一个已提交视图。

运行的提交归属不可变。无提交 scope 的 CLI 只能访问独立 CLI 运行，不能凭 `run_id` 读取学生私有运行；其他提交的 scope 同样不能访问。已打开的 store 还校验运行身份与创建代次，拒绝采用同 ID 后来重建的记录。

- **主动删除私有提交**：`lesson_runs.submission_id` 外键随提交级联删除，事件、预算和交接数据一并消失；删除后的后台写入失败，不能重建运行。
- **私有产物满 30 天**：清理事务删除该提交的执行运行及子表；已关联的规范公共题目和历史关系可以保留，不能继续恢复旧私有课程。
- **公共题目停用**：拒绝该题私有运行的新读写，不因存量 store 已打开而绕过状态检查。
- **来源整页满 24 小时**：保持第一期规则，不提前删除仍在 30 天期限内的独立裁剪提交与执行数据。主动删单题也不提前删除来源整页。

文件物理清理继续通过第一期的 pending cleanup 队列、生命周期锁和读取锁完成；数据库级联删除不是文件删除的替代品。

WebSocket 无新事件时指数退避，最长 3 秒；有新事件恢复 150 毫秒续读，发送前重验会话与归属，客户端 ping 不得加速数据库轮询。真实 PostgreSQL 的可控时钟回归中，空闲及完成态在 30 秒内各执行 13 次事件读取，而非约 200 次；撤权检查仍不超过 3 秒。

## 3. 迁移与本地命令

升级前停止所有连接目标实例的 web、worker 和 cleanup，按既有本地备份、迁移、自检流程操作。下列为隔离实例示例，不是线上部署指令：

```bash
./deploy/product/manage.sh --mode local \
  --data-dir /private/tmp/sss-search-acceptance --instance search-acceptance --port 55444 deploy
./deploy/product/manage.sh --mode local \
  --data-dir /private/tmp/sss-search-acceptance --instance search-acceptance --port 55444 doctor
```

数据库版本须达到 `0014_lesson_execution` 或更新版本。迁移同时将新表加入应用权限、自检和备份清单；运行时不执行 DDL。应用只允许更新必要状态列，运行身份和已提交数学证据不授予更新权限。

阶段三 CLI 的数据库参数属于主命令，必须放在 `run`、`resume`、`events`、`serve`、`batch`、`report` 等子命令之前。在 `server/` 目录执行：

```bash
uv run --offline python -m shuxueshuo_server.graph_lesson.stage_three.cli \
  --data-dir /private/tmp/sss-search-acceptance --instance search-acceptance \
  run --input /absolute/path/to/stage-two-result.json --output /absolute/path/to/new-run

uv run --offline python -m shuxueshuo_server.graph_lesson.stage_three.cli \
  --data-dir /private/tmp/sss-search-acceptance --instance search-acceptance \
  events --run /absolute/path/to/new-run --after-seq 0
```

未传数据库参数时沿用产品默认持久目录及实例，不自动创建数据库。测试和录制验证必须显式指定隔离实例，不能用日常数据库替代。

## 4. 真实 PostgreSQL 离线测试

以下测试需要已迁移的独立 PostgreSQL，缺少配置直接失败，不以跳过视作通过。示例在 `server/` 执行：

```bash
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-search-acceptance \
PRODUCT_TEST_INSTANCE=search-acceptance RUN_LLM_INTEGRATION=0 \
uv run --offline pytest -q tests/search/test_execution_storage.py \
  tests/solver/test_graph_stage_three_events.py \
  tests/solver/test_graph_stage_three_postgres_budget.py
```

搜索数据库测试逐例建立临时 schema，并复现完整迁移、外键和应用权限。阶段三测试在隔离实例中按测试模块建立 `test_*` schema，清理用例新增运行，保留模块级录制 fixture。测试用 `PRODUCT_TEST_SCHEMA` 将同一 schema 传给 spawn 子进程；该配置只允许同时显式指定测试数据目录和实例，且目标执行表必须已经存在，不能回退到 public 的旧运行。

重点覆盖原子回滚、并发幂等、连续水位、读取快照一致性、预算中断恢复、跨 run/提交隔离、删除与后台提交交错、到期边界及停用拒绝。历史阶段三文档中的测试数字仍只代表当时版本。

专项还发现并修复两处运行边界：路线 advisory lease 使用独立 AUTOCOMMIT 连接并脱离应用连接池，避免持有多条路线时耗尽池；本地计算子进程被并发回收时，等待退出码发布后再关闭 `Process`，避免恢复过程中误报仍在运行。均有确定性回归，不靠延长计算预算或忽略异常规避。

首次适配验收的搜索与账号测试：`tests/search tests/auth` 为 **670 passed、4 skipped**，数据库用例没有跳过。4 个跳过中，3 个 OCR worker 用例已在 `.venv-ocr` 独立环境执行并全部通过，另 1 个为本轮禁止调用的真实模型测试。前端 `tools/tests/*.test.mjs` 与迁移测试为 **802 passed、0 skipped**。日志分别为 `/private/tmp/search-pg-final-complete.log`、`/private/tmp/search-ocr-final-complete.log` 和 `/private/tmp/search-pg-frontend.log`。后续复审结果见第 7 节。

阶段三全量离线回归原次运行收集 2992 项，结果为 **2984 passed、8 failed、2 teardown errors**（3007.62 秒）。该进程启动后仍有修复落地，不能把它当作冻结版本结果。代码冻结后，按日志实际失败节点重跑，并覆盖完整预算模块及新增 CLI、子进程回收回归，共 **22 passed、1 failed、0 errors、0 skipped**（230.58 秒）；原先另外 7 个失败和 2 个 teardown 错误均已通过复测。另有存储专项 82 项、非阶段三前缀的交互失败存储用例 16 项通过。最新收集为 2996 项，本轮不将分批结果推算成一次全量全绿。

唯一保留的失败是 `test_graph_stage_three_interaction_ranges.py::test_every_presentation_template_has_an_explicit_rule`：现有 presentation registry 有 43 个模板，interaction registry 有 42 个，缺少 `opening_excluded` 的显式规则，且测试仍硬编码 37。测试及两个注册表与本轮开始时的 `HEAD 1a0830a1` 完全相同；这属于既有模板覆盖问题，不是 PostgreSQL 适配回归，未修改断言、注册表或跳过该用例。原次日志为 `/private/tmp/stage-three-pg-full.log`，冻结复测日志为 `/private/tmp/stage-three-pg-final-retests.log`，最终收集日志为 `/private/tmp/stage-three-pg-collected-final.log`。

## 5. 仍是本地执行，不等于分布式改造

执行状态与预算账本统一到 PostgreSQL，但运行目录、冻结输入、supervisor 回执、导出锁及搜索文件生命周期锁仍依赖当前主机文件系统。路线预算除本机 `flock` 外，也使用 PostgreSQL session advisory lease，阻止同一运行的相同路线从另一个目录并发占用；这不等于完整的跨主机 worker 协调。

本轮不增加远程任务队列、共享对象存储、跨机 supervisor 恢复、自动重试付费调用或线上部署。

**现有 `backup` 不是私有课程的完整文件备份。** 它通过 `pg_dump` 备份数据库，并按 `artifacts` 表清单复制产品 artifact 根目录；新 `lesson_*` 表已进入数据库和行数校验清单，但 `work/search/private-v1/` 以及独立 CLI 运行目录不在自动复制范围内。只恢复该备份能恢复数据库证据，不能承诺恢复原图、冻结输入、私有课程文件或继续本机 supervisor 执行。

需要完整恢复仍在保留期内的私有课程时，应在停止所有共用实例和文件存储的 web、worker、cleanup 后，另行一致备份所需运行目录；恢复时核对存储 key、运行身份、原始到期期限和文件完整性，不因恢复备份延长保留期。此文件备份及完整恢复流程本轮尚未实现或验收。搜索稳定锁文件的 inode 容量和安全离线回收仍按[第一期上线前待办](shared-problem-library-and-student-learning-stage1.md)处理，不在运行中按 mtime 或记录缺失直接 unlink。

## 6. 8779 离线验收（2026-10-24）

使用独立 `search-acceptance` 实例（55444）和 `0014_lesson_execution`。本机 harness 将识别替换为明确标记的合成复核 fixture，阶段二重放 Q01 原录制，阶段三执行真实本地计算及 PostgreSQL 事务；拒绝外部网络，短信为 mock。此验收不冒充真实 OCR/LLM 复核质量证据，也未改变日常数据库或部署线上。

- 真实浏览器走通登录、上传、整图选题、生成和课程打开。新提交 `dc6cf27a6a1a` 的事件、快照及互动步骤由 PostgreSQL 提供，与另一账号同题共用公共身份但不共用私有运行。
- 预置 25 个私有提交，按题聚合成 24 条历史；浏览器首次显示 20 条，加载更多后为 24 条，没有重复，按钮消失。
- 另一个标签同账号重登时，选题页不退出，课程保留在“确定题型”及已完成的读题步骤；换号和退出立即停止原课程并回首页。账号 B 访问账号 A 提交显示不存在，同题新课程从 0 步开始；切回 A 后原进度可恢复。
- “识别有误”仅出现一次确认，并明确删除该题本人全部关联记录。确认后返回拍题页，另一个正在学习的标签显示已删除；账号 A 该题所有版本的本机进度键消失，刷新不复活。
- 删除账号 A 的两次 Q01 提交后，提交行、目录、`lesson_runs` 及全部 15 个执行子表中的对应数据均为零。同来源页的另一条合成题仍保留；账号 B 的 Q01 课程仍可打开；来源整页仍为 active，期限保持首次创建后 24 小时，待清理队列为空。
- CLI 在同一 PostgreSQL 上完成 `run → events → resume → events`；恢复前后事件导出逐字节相同，未产生重复事件。新 CLI 与浏览器运行目录不含 SQLite 文件。旧验收目录不导入，也不作为本轮证据。

本轮浏览器全流程以顶层页面验证。嵌入式窄视口只检查访客布局；站点认证刻意拒绝 iframe，不能据此声称手机端真实登录、拍摄权限或相机硬件已复测。

本机复核文件：`/private/tmp/search-postgres-8779.log`、`/private/tmp/search-postgres-deletion-audit.json`、`/private/tmp/cli-postgres-q01.log`、`/private/tmp/search-postgres-8779-proof.png`，以及独立实例 `work/browser-postgres-execution-fixture-20261024.json`。上述为本地验收产物，不含真实短信或新付费模型回执。

## 7. PostgreSQL 适配复审修复（2026-10-24）

没有修改 `0014` 去覆写旧提交状态，而是统一计算运行时可用性：持久状态为 `ready`，但缺少匹配提交的 PostgreSQL 运行、原始题目结果、裁剪元数据、题图、阶段二结果、运行身份、冻结输入或阶段三结果时，历史与详情响应 `unavailable`，显示“课程不可用”，不是“可开始学习”。持久 `ready` 保持原样，读取不重建文件、不触发计算。已到期和已停用状态仍优先；同题有较旧可用课程时继续打开旧课程，同时独立标记最近一次课程不可用。

不可用详情保留公共规范题面，只提供重新拍照；不显示失效图片、生成或继续计算入口。直接调用重跑阶段二 `POST /problems/{id}/lesson`、start 或 resume 均返回 `409 lesson.execution_unavailable`，重跑阶段二取得生命周期锁后也再次检查，不登记重试意图或投递任务。未开始的正常课程与仍在生成的早期运行不因此被判作归档缺失。

重跑入口收口的后续专项为 **18 passed**（`/private/tmp/search-pg-retry-availability-final.log`）：覆盖 9 类不可用产物、拿锁时运行/题目结果/课程结果消失，以及原有正常重试与失败恢复流程；拒绝请求不触发 provider、任务或重试意图，锁会释放，原持久状态不变。题目结果读取也放在生命周期锁内。8779 已重新加载该修复，日志为 `/private/tmp/search-pg-retry-8779.log`；此次小改动未重跑后文记录的完整测试集。

重跑阶段二、启动和继续计算的准入检查不再持有进程内 `errors_lock` 执行数据库或文件操作；该锁只保护 `judging` 与错误字典。每提交的生命周期锁仍贯穿复查、排队与后台执行，防止同题重复启动以及删除/到期后重建产物。任务收尾及排队失败时，先完成状态写入与内存标记清理，最后释放生命周期锁，避免旧任务覆盖新任务状态；慢请求不再让其他题目的状态轮询等待全局锁。

此项修复冻结后离线 PostgreSQL 专项 **104 passed、0 skipped**（`/private/tmp/search-pg-admission-final.log`），其中新增 13 项确定性交错测试，覆盖三个入口的慢数据库/文件检查、跨题轮询、同题不重复排队、失败重新准入与旧任务收尾；同时回归可用性、账号、删除和到期边界。Ruff 与差异空白检查通过。8779 已重新加载，首页返回 200、匿名历史返回 401（`/private/tmp/search-pg-admission-8779.log`）；此次仅做服务冒烟，没有重复整套浏览器流程，没有付费模型、真实短信或线上部署。

执行器 SQL 已统一命名绑定，不再按问号拆分语句；回归覆盖 JSONB `?` 操作符、问号字面量及固定 `run_id` 作用域。`RunNotFound` 是独立领域异常，不再继承 `FileNotFoundError` / `OSError`；需要将运行缺失降级为不可用的调用点显式处理。

本地 `_reap` 的 join 与退出码等待共享 1 秒上限，仍兼容并发回收者稍后发布退出码。若退出状态始终不可得，记录明确 warning、关闭管道，不调用可能掩盖原异常的 `Process.close()`；保留已收到的数学结果或原异常。此极端分支不宣称进程已确认回收，进程句柄可能延后释放。

8779 已重启并启用严格上下文标志。只在隔离实例建立明确合成的 `66f8530dea44` 缺失运行样本（数据库仍为 `ready`，无对应 `lesson_runs`）：浏览器历史显示“课程不可用”，详情保留公共题面并仅显示重新拍照；既有正常 PostgreSQL 课程 `dc6cf27a6a1a` 仍能读取快照并进入读题步骤。未重新生成课程、调用付费模型或真实短信，也未部署线上。样本清单为 `work/browser-missing-run-review-20261024.json`，截图为 `/private/tmp/search-pg-review-8779-proof.png`，服务日志为 `/private/tmp/search-pg-review-8779.log`。

本轮冻结后的完整搜索/账号回归为 **706 passed、4 skipped**（`/private/tmp/search-pg-review-frozen-all.log`），数据库用例无跳过；3 个 OCR worker 用例在独立环境再次全部通过（`/private/tmp/search-pg-review-ocr.log`），另一个跳过仍为禁止调用的付费模型测试。前端全套为 **806 passed、0 skipped**（`/private/tmp/search-pg-review-all-frontend.log`）。事件/交互/裁剪专项 69 项、CLI/运行身份/进程恢复专项 53 项、bounded 与回收专项 48 项、Q07/Q09 的 after-commit 恢复 2 项均通过；日志依次为 `/private/tmp/search-pg-review-events.log`、`/private/tmp/search-pg-review-recovery.log`、`/private/tmp/stage-three-bounded-cleanup-final.log`、`/private/tmp/stage-three-bounded-cleanup-recovery.log`。Ruff 和差异空白检查通过。本轮未重跑阶段三全部数学矩阵，也未改动第 4 节记录的既有模板覆盖失败。
