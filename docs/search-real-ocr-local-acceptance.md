# 真实 OCR 镜像本地验收（2026-10-24）

## 范围与环境

这次使用真实 Paddle Linux 镜像，不是应用镜像加 fixture 推理。未启动线上服务、调用付费模型或真实短信，未 push。
只在构建镜像时下载公开软件依赖；模型使用本机已有缓存的隔离副本，全部运行验收使用 Docker `--network none`，不映射宿主机端口。

| 项目 | 实测配置 |
| --- | --- |
| 代码基线 | `ff320574`，生产 Dockerfile 和 sidecar 未作修改；另加标准库验收探针 |
| 镜像 | `docker.io/library/shuxueshuo-ocr:3.3.0` |
| 镜像 ID | `sha256:4f23c8f0a5f06f46c633fb1c42d35cb3eaec101a6fea3f0996750bd4276c50d1` |
| 架构 | Linux/amd64，在 Apple Silicon Docker Desktop 中经 Rosetta 运行；不是原生 x86 服务器 |
| Docker VM | 10 CPU，8,321,515,520 bytes 内存，cgroup v2 |
| 容器限制 | 6 GiB，`--memory-swap 6g`，不额外提供交换空间 |
| 运行身份 | UID/GID `1000:1000`，`HOME=/tmp`，与 Compose 默认相同 |
| 运行版本 | PaddlePaddle 3.3.0、PaddleOCR 3.7.0、PaddleX 3.7.2、NumPy 2.3.5、Pillow 13.0.0 |
| OCR 进程 | 一个 PID 1 `python sidecar_server.py`；产品与搜索共用它，未增加副本或 worker |

探针只执行标准库 HTTP 和 procfs/cgroup 采样，不导入 Paddle、不创建模型。进程快照中唯一常驻业务进程是 sidecar。
正例停止之后才启动缺缓存负例，二者没有同时运行。

## 五种缓存与断网预热

镜像内已实际导入 `search.ocr_protocol`、`search.ocr_worker`，并调用 `preheat_models.validate_cache()` 验证缓存。
每种模型的 `inference.json`、`inference.pdiparams`、`inference.yml` 均非空，15 个核心文件的 SHA-256 与原缓存一致。

| 模型 | 三个核心文件总字节数 |
| --- | ---: |
| `PP-DocLayout-S` | 5,146,359 |
| `PP-OCRv6_medium_det` | 62,273,512 |
| `PP-OCRv6_medium_rec` | 76,837,481 |
| `PP-FormulaNet_plus-M` | 620,439,684 |
| `PP-LCNet_x1_0_doc_ori` | 6,859,373 |
| 合计 | 771,556,409（约 735.8 MiB） |

只复制这五个模型目录，包括随附元数据共 33 个文件；没有复制整个用户 HOME，也没有修改原缓存。
容器 `/tmp/.paddlex/official_models` 只读，父目录可写，以便 PaddleX 创建非权重运行缓存。

真实 sidecar 严格加载产品和搜索两套模型对象后，`/health` 返回 `ok=true, ready=true`。
探针等待就绪 **13.77 秒**，容器启动至就绪约 14 秒；本机没有触及 Compose 120 秒启动宽限或服务启动 240 秒等待，但不能据此保证其他机器的时限。
`/v1/manifests` 返回真实版本和权重指纹。Docker inspect 记录网络为 `none`，接口计数仅回环有流量，没有外网访问能力。

负例只挂载同一缓存中的四种模型，缺少方向模型目录；原缓存未删除或改名。真实 sidecar 在严格方向加载处失败，约 **46.31 秒**后退出 **1**，健康检查为 `unhealthy`，`OOMKilled=false`，从未进入监听就绪日志。
PaddleX 尝试回退到公开模型源，但 DNS/网络被 `--network none` 阻断，没有下载成功，也没有以 `orientation=None` 继续提供服务。
这同时说明“跳过模型源连通性检查”不等于禁止下载；离线保证来自容器网络隔离与已准备好的只读权重。

## 方向与真实推理

使用仓库已有南开一模第 25 题整页（1200×2652）及印刷题干裁图（1180×640），不生成或改写题目。
只做确定性的 EXIF/RGB 规范化、顺时针旋转、去元数据和 PNG 编码；作者期望与模型实际输出分别保存。
整页仍按原尺寸输入，由真实 worker 缩到长边 1600，不把预缩图冒充服务缩图。

| 输入 | 自动方向 | 手动模式 | 实测输出 |
| --- | --- | --- | --- |
| 整页 | 顺时针 0/90/180/270，修正 0/270/180/90 | 90/270 输入，禁止再次自动转正 | 自动 724×1600；手动 1600×724 |
| 裁图 | 顺时针 0/90/180/270，修正 0/270/180/90 | 90/270 输入，禁止再次自动转正 | 自动 1180×640；手动 640×1180 |

**12/12 通过**：8 项自动方向均正确，置信度 0.92329–0.92634，未降低生产阈值 0.90；4 项手动模式均保持 `rotation_degrees=0`。
整页自动请求 6.08–7.27 秒，裁图自动 2.86–3.27 秒，手动 1.36–1.78 秒，均小于生产客户端 120 秒预算。
诊断探针允许等待 900 秒以保存慢请求证据，但独立按 120 秒判定通过，不能用放宽超时掩盖生产失败。

随后在同一进程调用产品 `source → observation`：完整题图实际产生 **11 个公式输入和 11 个原始结果**，包含预先约定的 `y=ax^{2}+bx+c`，observation 耗时 **46.91 秒**。
再执行一次搜索成功（3.19 秒），PID 1 未替换。这证明两条真实调用路径可先后复用模型；不等于验证了所有公式的语义准确率，也不是产品长任务与学生上传的并发压测。

保留一次未通过的探索记录：229×41 的历史单公式小裁图虽然返回 HTTP 200，但版面分析没有生成公式请求，`items/raw_payloads` 均为空，因此未计作公式推理通过。
该报告没有覆盖或改成成功；完整题图使用独立工作目录和报告补验。

## 峰值内存

每 0.1 秒读取 PID 1 的 `VmRSS/VmHWM` 和 cgroup v2 的 `memory.current/peak/stat/events`。
表中 RSS/current 是阶段内采样最大值，kernel peak 是截至该阶段的累计值；不相减推导阶段峰值。

| 阶段 | PID 1 RSS 采样最大值 | 容器 current 采样最大值 | 容器 kernel peak 累计值 |
| --- | ---: | ---: | ---: |
| 严格预热 | 1.693 GiB | 2.166 GiB | 2.169 GiB |
| 12 项搜索 | 2.249 GiB | 2.642 GiB | 2.642 GiB |
| 完整题图产品推理 | 2.662 GiB | 3.005 GiB | **3.009 GiB** |

全程 `oom=0, oom_kill=0`，未碰到 6 GiB 容器上限。产品推理后的 kernel peak 为 **3,231,404,032 bytes**，PID 1 RSS/HWM 最大值为 **2,858,463,232 bytes**。
容器指标包括文件缓存和测量客户端，不是模型权重的简单相加；采样可能漏掉短峰值，故同时保留内核累计峰值。

这只是以上样本的**观测峰值，不是生产容量上限**。本次未同时运行 API、数据库和业务 worker，未压测并发上传/32MP 解码及数分钟产品整页任务。
还需在目标服务器原生 x86 环境、真实整套服务负载下测余量，不能拿 Rosetta 的时间或本次 3.009 GiB 直接承诺服务器规格；OCR 仍保持一个进程。

## 复验工具和证据

标准库探针：`deploy/ocr/acceptance_probe.py`；必须在已有真实 sidecar 容器中用 `docker exec`，不要将探针当成 OCR 服务或另开模型进程。

```bash
docker exec search-real-ocr-20261024 \
  python /opt/shuxueshuo/deploy/ocr/acceptance_probe.py \
  --cases /acceptance/cases.json \
  --output /acceptance/reports/positive \
  --startup-timeout 600 --request-timeout 900
```

此命令用于新一轮容器；本轮容器结束后清理，复验需按相同 UID/HOME、网络和挂载配置重新创建。输出目录必须是新的，工具拒绝覆盖已有证据。
`cases.json` 是非空数组，每项为：

```json
{"id":"page-r090-auto","image":"/var/lib/shuxueshuo/work/search/private-v1/pages/4524e4687b32/source.png","auto_orient":true,"expected_rotation":270,"expected_size":[724,1600],"expected_status":"corrected"}
```

`expected_size` 使用 OCR 缩到长边 1600 后再修正方向的尺寸。`uncertain` 必须为待复核，HTTP 失败、方向/尺寸错误、超过 120 秒、内存指标缺失或 OOM 都不能使总报告通过。

本机原始证据保留在 `/private/tmp/search-real-ocr-20261024/`，不把权重、镜像、OCR 原始正文或大体积采样提交到 Git：

- `build.log`、`source-revision.txt`、`image-inspect.json`、`import-check.log`、`pip-freeze.txt`：构建与真实运行版本。
- `provenance.json`、`cases.json`、`cache-after.json`：图片变换、预先标注期望、模型文件哈希及不变性。
- `reports/positive/{report.json,memory.jsonl}`：预热及 12 项方向实测。
- `product/report.json`：小裁图未触发公式模型的失败原证据。
- `product-problem/{report.json,memory.jsonl,formula-call.json}`：完整题图真实产品推理。
- `reports/after-product/report.json`、`runtime-final.txt`、`processes-final.txt`、`sidecar.log`、`container-inspect-*.json`：复用、内存及断网证据。
- `missing-orientation-{exit.txt,inspect.json}`、`missing-orientation.log`：缺方向模型的真实失败退出及健康检查。
- 输入准备脚本 `/private/tmp/prepare-real-ocr-inputs.py` 与产品驱动 `product_probe.py` 为本轮文件准备/HTTP 客户端，不是线上入口。

离线回归：

```bash
cd server
PYTHONDONTWRITEBYTECODE=1 RUN_LLM_INTEGRATION=0 uv run --no-sync pytest -q \
  tests/search/test_search_ocr_sidecar.py \
  tests/search/test_ocr_sidecar_startup.py \
  tests/search/test_ocr_acceptance_probe.py
PYTHONDONTWRITEBYTECODE=1 .venv-ocr/bin/python -m unittest discover \
  -s tests/search -p test_ocr_orientation_worker.py
```

结果：**106 passed + 5 passed**，无跳过。新增探针的 27 项测试在前一组内；模拟模型的单测不冒充真实镜像证据。
