# 最终容器离线演练

日期：2026-10-25。结果：**通过**。本轮没有调用付费模型或真实短信，没有部署线上或 push；没有替换现有 8779 服务，也没有挂载日常数据库。

## 1. 本轮证据

- 源码基线：`d3224bd4a8d1d1cd50c55ebb32ee54720093232d`，叠加本轮演练脚本、fixture 和回归修复；完整工作树摘要保存在报告中，不冒充干净提交的正式发布包。
- 成功报告：`/private/tmp/search-compose-final-20261025-c/report.json`，`passed: true`、`cleanup_ok: true`，包含 16 组端到端断言。
- 总日志：`/private/tmp/search-compose-final-20261025-c.log`；容器及清理日志分别为输出目录内 `services.log`、`cleanup.log`。
- 项目名：`search-rehearsal-39804e1a7a`。演练结束后另行按 Compose 项目标签核对，容器、网络、PostgreSQL 卷和 RabbitMQ 卷均无遗留；只保留派生镜像和仓库外证据。
- 应用镜像：`search-rehearsal-39804e1a7a-app:latest`，ID `sha256:05d0e0c14862e4bf7bd1db564b4811db9990cd5cabb5eb8e6a98d8eda1b58972`。
- 管理镜像：`search-rehearsal-39804e1a7a-admin:latest`，ID `sha256:2a05102518dd37f42d15951cf61beba65d3f670bd31c71fc107a380aca38c859`。

输出目录权限为 0700，其中含一次性凭据、证书私钥、fixture 短信和登录 Cookie；不要提交或公开整个目录。外层报告只摘取限额、计次数量和预置票据数量，不复制 Cookie 或账号标识。

## 2. 实际运行范围

使用 Docker Desktop 29.5.3 / Compose 5.1.4，将原生产 `compose.yml`、`compose.server.yml`、`compose.app.yml` 与演练专用 overlay 合并后实际启动。生产三份 Compose 和 Nginx 配置未修改，报告保存其 SHA-256 及脱敏后的最终配置。

| 范围 | 实际结果 |
| --- | --- |
| 最新代码镜像 | 应用、管理镜像均重新构建；复用本机锁文件一致的依赖层，构建禁网、不拉取镜像；镜像不含测试、真实 `.env` 或本机虚拟环境 |
| 空库安装 | PostgreSQL 17.10 空卷安装、授权、迁移至 `0016_search_admission`；`install`、`services-install`、`services-doctor` 成功 |
| 完整服务组合 | PostgreSQL、RabbitMQ、OCR、API、worker、publisher、Nginx 各一个容器；有健康检查的服务均 healthy，worker/publisher 心跳新鲜，无 OOM |
| 生产约束 | 保留健康依赖、admin 只读根目录与 tmpfs、安全选项、API 十分钟排空宽限；独立内部网络、无宿主端口绑定 |
| 单进程 | `/proc` 与进程列表确认 API、OCR 各一个服务 Python 进程；不增加 OCR 副本 |
| HTTPS 与认证 | 原生产 Nginx、自签名测试证书、Secure/HttpOnly 登录 Cookie、匿名拒绝、错误 Origin、跨账号拒绝、私有响应 no-store、TLS WebSocket |
| 图片 | 真实 sidecar HTTP 和路径校验；24MP JPEG 归一化、恰好 32MP PNG 接受、超过 32MP 解码前拒绝、长边不超过 4096、20 MiB Nginx 边界、旋转 |
| 课程与历史 | 明确标记的合成复核、阶段二离线录制、真实 PostgreSQL 阶段三、提交幂等、课程快照/事件、本人历史 |
| 生命周期 | 排空拒绝新 POST、保留读取；公共题停用、删除与来源整页保留；API 重启恢复中断、启动到期清理、维护 cleanup 命令 |
| 产品后台 | 原 worker/publisher 命令实际启动并连接 RabbitMQ；无产品任务投递，数据库 `jobs=0`、`builds=0` |

真实 OCR 镜像为本机 `shuxueshuo-ocr:3.3.0`，ID `sha256:4f23c8f0a5f06f46c633fb1c42d35cb3eaec101a6fea3f0996750bd4276c50d1`。另在断网容器中确认其 `search.ocr_protocol` / `search.ocr_worker` 可导入，已安装 PaddlePaddle 3.3.0、PaddleOCR 3.7.0。本轮预热与推理使用 fixture，**没有加载真实模型，不重新声明识别质量、方向效果或峰值内存验收**；既有真实模型证据见[真实 OCR 本地验收](search-real-ocr-local-acceptance.md)。

## 3. 准入与费用停止

未用环境变量缩小限额，按当前生产默认值执行：

| 策略 | 验证 |
| --- | --- |
| 上传每账号 2、全站 10 | 暂停 fixture OCR，真实并发 HTTPS 上传占住名额；同账号第三个、全站第十一个立即拒绝，未进入 OCR；释放后十个请求全部完成 |
| 生成每账号 1、全局 2 运行＋4 等待 | 暂停 fixture 识别，确认真实票据状态为 2 running / 4 reserved；同账号第二个和全局第七个拒绝 |
| 每账号每日新生成 10、重跑 3 | 预置明确标记的已消费账本后，真实第 10/3 个边界请求成功，下一次拒绝；重复请求不重复计数 |
| 全站每日新生成 100、重跑 50 | 预置账本后，真实第 100/50 个边界请求成功，下一次拒绝；删除和重启后消费总量不变 |
| 费用开关 | 空库默认关闭；维护 CLI 显式开启；2+4 队列下停止会取消四个未消费等待项，已运行任务在下一次模型调用检查时停止；私有读取仍可用；关闭状态跨 API 重启保留 |

日额度预置票据使用 `offline.fixture.preconsumed` 和独立请求 ID 标记。报告列出预置数：账号生成 8、账号重跑 2、全站生成 87、全站重跑 46，即 **95 个生成票据、48 个重跑票据来自预置**；余下消费来自真实路由受理的 fixture 任务，其中包括热停止时已经消费的任务。最终账本 100/50 不表示实际完成了 150 门课程，更不表示有任何付费调用。

## 4. 修复与回归

原演练手工启动容器，且在 fixture API 启动时自动开启费用开关，无法验证生产 Compose 或初始关闭。现已改为真实 Compose 组合，fixture 不再自动开启；加入真实并发、默认额度边界、热停止与重启验证。

实际执行暴露并修复两处演练兼容问题：配置展开须同时启用 `admin` 和 `fixture` profile；本机 RabbitMQ 缓存可能只有 OCI 索引顶层元数据，需要使用本地平台 inspect 解析到可运行镜像，不能把空 OS/Architecture 写成 `/`。解析失败直接退出，不联网拉取。两次失败的报告分别保留在 `-a`、`-b` 输出目录，已完成相应临时资源清理。

新增回归还覆盖隔离 overlay、私有挂载、生产安全参数、输出脱敏、构建早期失败报告、清理失败不掩盖原异常、fixture 必须显式离线启用、账本边界和上海时区日期。

```bash
cd server
PRODUCT_TEST_DATA_DIR=/private/tmp/sss-search-stage1 \
PRODUCT_TEST_INSTANCE=search-stage1 RUN_LLM_INTEGRATION=0 \
uv run pytest -q \
  tests/search/test_container_rehearsal.py \
  tests/search/test_server_rehearsal.py \
  tests/search/test_local_admission_rehearsal.py \
  tests/product/test_search_deployment.py \
  tests/search/test_generation_admission_api.py \
  tests/search/test_upload_admission.py \
  tests/search/test_admission.py \
  tests/search/test_admission_cli.py
```

独立 PostgreSQL 55443 上 **121 passed，0 skipped，10.83 秒**；日志 `/private/tmp/search-final-container-regression-20261025.log`。四个本轮 Python 文件从 `server/` 运行离线 Ruff 全部通过，`git diff --check` 通过。

## 5. 复现与边界

完整命令见[单机生产说明](search-single-host-production.md#4-可复现的离线镜像演练)。须准备六种本机已有镜像，使用全新仓库外输出目录；脚本保留失败报告并只清理本项目资源，不拉取镜像、不连接日常实例。

演练仍有明确边界：应用、管理、OCR、RabbitMQ 为 linux/amd64，数据库与 Nginx 为 linux/arm64，不代表原生服务器容量；依赖层来自缓存，不是从零安装依赖；Nginx 共享 API 网络命名空间以沿用原 loopback 上游，fixture Uvicorn 因此信任 loopback，而生产参数信任宿主桥接范围。API 启动适配器只为注入离线依赖，不取代目标服务器正式启动验证。

本轮没有验证公网 DNS/证书、真实短信/模型供应商、目标服务器资源容量、产品构建任务或正式发布包切换。API 重启前停止并完成 fixture 任务，再用预置 queued 提交验证中断恢复，不冒充活跃付费推理过程中的断电演练。账号注销仍不在范围内。
