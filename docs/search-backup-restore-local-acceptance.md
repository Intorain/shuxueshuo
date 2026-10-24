# 拍题备份恢复：删除与到期不复活

日期：2026-10-24。范围为单机 PostgreSQL、产品产物及拍题私有文件的备份恢复，不引入账号注销、跨机调度或自动线上发布。未调用付费模型或真实短信，不部署、不 push。

## 1. 存储与保留契约

- `product-backup/v2` 包含数据库 dump、产品登记产物及数据库登记的未到期拍题页面/提交文件。私有文件清单记录相对 key、owner、SHA-256、字节数和原始 `expires_at`；不按磁盘目录扫描导入匿名记录或孤立文件。
- 页面与整页旋转副本仍以首次上传后 24 小时为限；提交裁剪图和私有课程产物仍以原提交后 30 天为限。备份、恢复和旋转不续期；删某题不提前删除来源整页，同页其他题不受影响。
- 完整 v2 备份最多保留 30 天，其拍题文件副本在原截止时间先到时提前清除。数据库 dump 不支持单行即时擦除，最多保留到整份备份到期；这不表示已删内容可以恢复开放，恢复流程必须重放删除并执行原期限检查。
- 运行文件在启动及每分钟清理；本实例可识别的 v2 备份在启动及每小时清理，显式 `cleanup` / `backup-prune` 不等待定时周期。本轮格式的不完整备份在创建一小时后可清理。失败在下个对应周期重试，未知格式不擅自删除。复制到实例外的备份不在自动清理范围内，必须另行落实相同保留期。

保留期是到期判定时间，物理删除在之后的对应维护周期执行；故障时可能更晚，需要告警和值守处理。降低备份扫描频率不延长页面或提交的有效期限，恢复仍按当时的原始截止时间过滤私有文件。

## 2. 删除权威独立于备份

源实例 `work/search/private-v1/recovery/deletions.jsonl` 是追加式删除意图日志。每项只包含 `user_id`、`search_id`、`created_at`，不包含照片或题面；按这三个字段共同匹配，避免跨账号、重新建立的独立提交或重复 ID 被误删。

日志写入并 `fsync` 必须先于数据库删除。即使数据库事务失败或稍后回滚，已经持久记录的删除意图仍有效，不能靠恢复旧数据库让它失效。关联题删除仍仅记录当时选中的本人提交集合，不扩大为今后同题所有提交。

历史分页复用已校验的日志快照，不再为每条记录重复读取日志及数据库游标；查询前、查询后和返回前各校验一次，次数不随每页条数增长。返回前重新过滤期间新增的删除意图，包括数据库回滚但日志已持久化的删除；日志校验失败仍返回 503，不用旧快照继续开放数据。

迁移 `0015_search_recovery` 增加数据库与删除日志 authority/cursor 的绑定。日志哈希链、序号、authority 与数据库游标必须一致；缺失、完整行损坏、中间损坏、authority 不匹配或落后于已有游标时失败关闭，不自动重建空日志。该校验只证明完整性与已知前缀，不证明任意离线副本就是“最新”：操作员必须提供并独立保管当前源权威，不能用旧备份内的日志替代，也不能用回滚数据库覆盖它。

### 尾部未完成写入的修复边界

追加前记录原文件长度；写入或刷盘失败时尝试截回该长度并再次刷盘，删除事务不提交。若进程中断留下**末尾无换行的残片**，初始化只在持有数据库状态行锁及日志排他锁、验证全部完整前缀的哈希链/authority，且数据库游标不超过该前缀并匹配其摘要、已重放游标也不越界后，截去残片、刷盘并记录告警。不会删除任何完整记录，完整且已刷盘但数据库尚未提交的删除意图仍有效。

首次创建日志头时若本次写入、文件刷盘或目录刷盘失败，仅撤销本次排他创建的新文件并刷盘目录，不删除既有日志。首次断电遗留空文件或半行时，仅当数据库仍为 `initialized=False`、`sequence=replayed_sequence=0` 且 `digest` 为空，才在状态行锁和日志排他锁内检查并清除不含任何完整行的普通文件，刷盘目录后用同一个 authority 重建日志头。已有完整行不丢弃；已初始化或有游标痕迹、符号链接及非普通文件均不走此重建路径。并发初始化由锁串行化，修复过程失败仍不绑定数据库，可在排除磁盘故障后重试。

排查磁盘故障时先停止业务写入、腾出空间并修复文件系统，再重启应用，让初始化执行上述有限修复；不要手工编辑 JSONL、改游标、删除日志或创建空日志绕过检查。若完整记录、游标或 authority 校验仍失败，继续失败关闭，须取回可信当前删除权威；不提供跳过校验的恢复方式。独立异地保管、同步频率及灾备取回流程仍属部署前运维工作。日志没有通过逐行删除来缩短保留的实现，避免破坏仍可能恢复的旧备份所需删除证据。

### 升级后的首个恢复点

含拍题数据的 `0014` 备份以及所有含拍题数据的 v1 备份，不能作为新版私有拍题恢复源。升级到 `0015` 并首次初始化当前日志成功后，**立即停止业务写入和清理，创建并核验第一份 v2 备份，同时独立保管当前日志，然后再开放接单**。仅完成迁移或生成日志不等于已有可恢复备份；迁移前备份到这份 v2 备份之间存在恢复点空窗，不能等到下一次日常备份才补齐。

## 3. 恢复顺序与失败关闭

先停止源实例全部业务写入、清理和管理操作。恢复全程持有源日志共享锁；如果错误地让源继续接收删除，删除争用排他锁最多等待 250 毫秒，超时返回 HTTP 503 `recovery.busy`，而不是无限等待，**503 不代表删除成功**。此保护不代替停源：恢复完成后在旧源产生的删除不会自动同步到新目标。恢复必须使用全新实例、数据根与空闲端口；备份包与当前源拍题根分开提供：

```bash
./deploy/product/manage.sh --mode local \
  --data-dir /absolute/path/restored --port 55433 \
  restore --target restored --backup /absolute/path/source/backups/BACKUP_ID \
  --search-recovery-root /absolute/path/source/work/search/private-v1
```

`--search-recovery-root` 指向包含 `recovery/` 的拍题根，不直接指向 JSONL 文件，不指向备份中的拍题文件目录。服务器命令及发布包约束见[部署手册](../deploy/product/README.md#备份和恢复)。

服务器包装脚本自动只读挂载该源拍题根。v2 备份没有任何拍题页面/提交时可省略参数；有拍题数据但缺 `0015` 游标或当前日志时拒绝恢复。v1 备份仅在没有拍题页面/提交且迁移版本匹配时沿用原恢复约定；含拍题记录的 v1 返回 `restore.search_backup_unsupported`，不把缺失文件当作无害空目录。

1. 全程保持新目标应用角色 `NOLOGIN`；核对备份版本、数据库哈希、文件清单和当前源删除权威。
2. 恢复数据库，按当前源删除日志重放备份之后的删除；撤销备份中的全部学生登录会话及未消费短信挑战，要求重新获取验证码并登录。
3. 新目标建立自己的 authority，再复制剩余且仍在原期限内的记录所需文件；已删记录的私有文件不复制到新目标。
4. 按原始截止时间清理：已关联记录保留题面而课程不可用，未关联过期提交删除；页面与提交分别到期。遗留非终态转为中断，不自动重跑模型。
5. 检查迁移、权限、内容与 doctor，全部完成才恢复应用登录。源数据库、源文件和源日志保持不变，不自动切换流量。

任一阶段失败均保留目标 `locks/restore-incomplete`，`resume` 和 `services-start` 不能绕过；保留失败实例作诊断并用另一全新目标重试。不得删除该标记后接单，也不得覆盖正在使用的源实例。

### 正式切换时的权威交接

本地隔离演练不切换流量，原源实例仍是当前权威。若正式采用恢复目标服务业务，必须将运维中的当前权威改为新目标 journal，并立即创建新 v2 备份，后续备份恢复沿用这个新 authority。

旧备份携带旧 authority，搭配新目标日志会失败关闭；不能为绕过校验而继续搭配旧源日志。旧备份和旧源日志可能仍相互匹配，但并不包含切换后在新目标发生的删除。工具无法仅凭旧源仍存在就判断其是否最新，故不能宣称自动识别所有陈旧副本；交接记录、独立保管及淘汰旧恢复入口由运维明确完成。

## 4. 单次清理

```bash
cd server
uv run python -m shuxueshuo_server.search.maintenance \
  --mode local --data-dir /absolute/path/source --instance source cleanup
```

使用实际实例名与数据根；生产容器继承对应配置，不读取开发实例。单次命令不调用模型或短信；清理还会处理运行文件、保留元数据中的待清路径，以及本实例中可识别的备份到期项。到期访问检查不等待物理删除，磁盘清理失败不能使过期课程重新可用。

停服期间无应用后台定时清理，使用独立管理命令：

```bash
./deploy/product/manage.sh --mode local \
  --data-dir /absolute/path/source --instance source backup-prune
/absolute/path/release/scripts/manage.sh --mode server \
  --release /absolute/path/release --data-dir /srv/shuxueshuo backup-prune
```

`backup-prune` 不需要数据库或删除日志，当前日志故障也不妨碍按期清除备份副本。正常启动、每小时备份维护及显式 `cleanup` 中，即使运行文件清理失败，也会尝试应执行的备份清理并报告各自失败；其余每分钟只处理运行文件，避免反复扫描全部备份或每分钟重复报告同一备份错误。停服保留期由值守人员或既有系统 timer 调用该命令落实；本轮只接通命令，不新增调度系统或宣称服务器已安装 timer。实例外备份副本仍须独立清理。

显式 `maintenance cleanup` 若运行文件清理与备份清理同时抛错，会记录备份异常并保留最先的异常及 traceback；若只有备份清理抛错，该异常继续向命令行传播，不输出成功结果。

## 5. 本地验收基线（审查修复前）

2026-10-24 使用独立原生 PostgreSQL 17、真实 `pg_dump`/`pg_restore` 和明确标记的离线数据完成验收。每个恢复场景创建全新临时实例及空闲端口，并在 `finally` 停止临时数据库；不使用 8779、55444 或日常实例。相邻全量回归使用独立 `search-stage1` 实例（数据根 `/private/tmp/sss-search-stage1`、端口 55443），已迁移至 `0015_search_recovery` 并核对角色授权。数据库用例无跳过。

| 范围 | 结果 | 日志 |
| --- | --- | --- |
| 尾部写入修复前的合并基线 | **79 passed、0 skipped**，46.76 秒；16 个真实 PostgreSQL 恢复场景 + 39 个文件边界 + 3 个恢复围栏 + 21 个删除日志用例 | `/private/tmp/search-backup-final-acceptance.log` |
| 完整 Search 回归 | **771 passed、5 skipped**，223.82 秒；5 项只因主解释器无 NumPy 跳过 | `/private/tmp/search-backup-all-search.log` |
| 独立 OCR 解释器补跑 | **5/5 OK**，补齐上述 5 项；使用假模型单测，不冒充真实 OCR 推理 | `/private/tmp/search-backup-ocr-unit.log` |
| Auth、管理、学习发布、恢复围栏、PostgreSQL 执行预算 | **150 passed、1 skipped**，29.60 秒；唯一跳过为明确关闭的付费学习图谱集成 | `/private/tmp/search-backup-final-regression.log` |

各范围存在重叠，不能相加作为独立总测试数。79 项是在删除日志/FIFO/符号链接安全收口后合并重跑的历史基线，不冒充包含后续尾部写入修复；此前单独的备份恢复/文件边界 **55 passed**（50.70 秒，`/private/tmp/search-backup-restore-rehearsal-final.log`）与删除日志 **21 passed**（1.93 秒，`/private/tmp/search-recovery-journal-20261024.log`）均已被该组合覆盖，不重复计数。此前 771 项全量结果不冒充包含其后新增用例。告警仅见既有 Alembic 配置弃用提醒。

### 实际执行命令

在仓库 `server/` 下执行：

```bash
RUN_SEARCH_BACKUP_RESTORE_TEST=1 RUN_LLM_INTEGRATION=0 \
  PRODUCT_TEST_DATA_DIR=/private/tmp/sss-search-stage1 PRODUCT_TEST_INSTANCE=search-stage1 \
  uv run pytest -q tests/product/test_search_backup_restore.py tests/product/test_search_backup_files.py \
  tests/product/test_restore_fence.py tests/search/test_recovery_journal.py

RUN_LLM_INTEGRATION=0 PRODUCT_TEST_DATA_DIR=/private/tmp/sss-search-stage1 \
  PRODUCT_TEST_INSTANCE=search-stage1 uv run pytest -q tests/search

PYTHONDONTWRITEBYTECODE=1 .venv-ocr/bin/python -m unittest discover \
  -s tests/search -p test_ocr_orientation_worker.py

RUN_LLM_INTEGRATION=0 PRODUCT_TEST_DATA_DIR=/private/tmp/sss-search-stage1 \
  PRODUCT_TEST_INSTANCE=search-stage1 RUN_LEARNING_ROLLOUT_TEST=1 uv run pytest -q \
  tests/auth tests/product/test_admin.py tests/product/test_learning_rollout.py \
  tests/product/test_restore_fence.py tests/solver/test_graph_stage_three_postgres_budget.py

```

### 已核对行为

- 数据库与拍题私有文件真实恢复，校验 SHA-256、大小、归属和原截止时间；保留既有产品产物备份通路，本轮恢复场景未额外植入非拍题产品产物。正常演练不改变源实例，也不切换业务流量。
- 备份后删除不复活；删除后新建的独立重拍提交幸存，同页其他题和另一账号记录不误删。原页面 24 小时及提交 30 天分别到期；24 小时场景先实际清除备份中的过期页面文件，再恢复仍未到期的课程文件。
- Q01 使用既有阶段二真实离线录制回放，再运行本地阶段三至 `completed`；两阶段新增语义调用及网络调用均为 0。备份后将源 `submissions` 目录隔离改名，再从新目标通过 HTTP 读取课程详情、快照及事件；课程运行标识、快照和事件与源结果匹配，历史仍可学习，响应保持 `no-store`，不依赖原课程目录。
- 删除日志在数据库回滚后仍生效；日志写入失败不提交数据库删除。缺日志、完整记录损坏或截断、落后游标、错误 authority、符号链接/FIFO、篡改文件或未知额外文件均不能变成有效恢复；应用角色不能替换数据库 authority。
- 真实导入后的复制/清理失败保留 `NOLOGIN` 和恢复失败标记；`resume` 不能绕过，服务启动围栏由专项回归覆盖。
- 旧学生 Cookie/会话及未消费验证码失效，验证码用离线 MockSMS 验证；含拍题数据的 v1 备份拒绝恢复。
- 私有文件副本按原截止时间清理，完整包最多 30 天、不完整包一小时；正在备份或恢复的 lease 阻止并发物理清理。失败可重试，不修改未知/外部目录，运行锁文件不进入拍题文件清单。

## 6. 未覆盖边界

- 本轮是原生 PostgreSQL 的本地恢复验收，不是服务器发布。源备份/日志只读打开由代码与单测覆盖，**尚未在真实 Docker 只读 volume 挂载中端到端执行恢复**。
- 未安装停服清理 timer、独立异地权威保管或备份复制系统；实例外副本仍由运维落实期限。删除权威切换与最新性不能由任意旧副本自动证明。
- 账号注销按当前决定暂缓，不列本轮工作；按题删除、退出登录和恢复时撤销会话都不等同于注销账号。
- 未调用付费模型或真实短信，未进行真实供应商联调；未改动 8779/55444、部署线上、提交代码或 push。离线课程验收不代表新图片识别质量或真实模型付费路径通过。

## 7. 审查修复验收（2026-10-24）

补齐首次建头断电及清理双异常后，按本节相同八文件命令重跑合并回归：**200 passed、0 skipped，53.98 秒**，日志 `/private/tmp/search-backup-edge-acceptance-20261024.log`；38 条告警为既有 Alembic 配置弃用提醒。使用独立 `search-stage1` 数据库及临时原生 PostgreSQL 恢复实例，未跳过数据库用例。此前 **177 passed**（55.26 秒，`/private/tmp/search-backup-review-fixes-20261024.log`）及本次先行 **71 passed**（4.90 秒，`/private/tmp/search-backup-edge-cases-20261024.log`）均已被该组合覆盖，不与第 5 节历史基线相加。

前轮相邻私有 API、PostgreSQL 执行、阶段三 API、课程准入并发及执行预算回归 **86 passed、0 skipped，77.45 秒**，日志 `/private/tmp/search-backup-review-api-20261024.log`。本次两项边缘修复后未重跑这组邻接测试；该范围单列，不与专项或历史结果相加。

已验证：

- 模拟追加写入、文件/目录刷盘失败，原有完整记录不丢失，未完成删除不提交；首次新文件失败可回滚。初始化仅修剪经游标校验的末尾残片，完整记录损坏、日志落后及不匹配 authority 继续拒绝启动。
- 首次断电的空文件、半行及缺少末尾换行的日志头可在未绑定状态下重建；并发首次启动只重建一次、authority 不变。已有完整记录或检查点不清空，目录刷盘失败后仍未绑定且可重试；生产 lifespan 在首次空文件/半行后能正常提供产品、登录和拍题接口。
- 生产 lifespan 用真实 `SearchRepository` 修复半行后，API 与产品健康检查可用；通过 HTTP MockSMS 发送/验证并登录，搜索归属隔离仍有效。未调用真实短信。
- 恢复持源日志共享锁时，HTTP 删除在有界等待后返回 503；释放共享锁后重试可删除，不把失败请求当作已完成删除。
- 历史分页复用快照，校验次数不随页内记录数增长；返回前过滤新写入的删除意图，包括数据库删除回滚的情形，日志损坏仍返回 503。
- 运行文件每分钟维护，备份仅启动及每小时扫描，失败按对应周期重试；显式维护仍立即执行，运行文件清理失败不跳过已到时的备份清理。
- 显式清理遇到双异常保留原始错误对象及 traceback，同时记录备份错误；仅备份失败仍报错。覆盖真实 `backups` 符号链接异常、无 settings、CLI 失败无成功输出及数据库资源释放。

在 `server/` 下实际执行：

```bash
PYTHONDONTWRITEBYTECODE=1 RUN_LLM_INTEGRATION=0 RUN_SEARCH_BACKUP_RESTORE_TEST=1 \
  PRODUCT_TEST_DATA_DIR=/private/tmp/sss-search-stage1 PRODUCT_TEST_INSTANCE=search-stage1 \
  uv run pytest -q tests/product/test_search_backup_restore.py \
  tests/product/test_search_backup_files.py tests/product/test_restore_fence.py \
  tests/search/test_recovery_journal.py tests/search/test_repository.py \
  tests/search/test_maintenance_schedule.py tests/search/test_recovery_startup.py \
  tests/search/test_application.py

PYTHONDONTWRITEBYTECODE=1 RUN_LLM_INTEGRATION=0 \
  PRODUCT_TEST_DATA_DIR=/private/tmp/sss-search-stage1 PRODUCT_TEST_INSTANCE=search-stage1 \
  uv run pytest -q tests/search/test_private_api.py tests/search/test_postgres_execution.py \
  tests/search/test_stage_three_api.py tests/search/test_lesson_admission_concurrency.py \
  tests/solver/test_graph_stage_three_postgres_budget.py
```

第 6 节的未覆盖边界不变：本轮是本地离线回归，不是线上发布、真实供应商调用或 Docker 只读挂载恢复端到端验收；没有新增账号注销、付费模型或真实短信调用。
