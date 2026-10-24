# OCR

## 本地 Mac（直装，无 Docker）

产品本地模式（`--mode local`）与开发机：在本机 Python 环境安装 Paddle / PaddleOCR，用 `REVIEW_OCR_PYTHON` 指向该解释器。不启动 sidecar，不设 `PRODUCT_OCR_URL`。

## 服务器（CentOS 7 + Docker 常驻 sidecar）

CentOS 7（glibc 2.17）无法直接运行 PaddlePaddle 3.x（需要 glibc ≥ 2.27）。
因此 OCR 使用 `shuxueshuo-ocr:3.3.0` 镜像。产品栈通过 Compose 服务 **`ocr`** 常驻该镜像，预热模型后提供 HTTP：

- `GET /health`
- `GET /v1/manifests` — provider 清单（构建依赖指纹）
- `POST /v1/observe` — body：`{work_dir, source_id, phase}`
- `POST /v1/search/observe` — body：`{image, auto_orient}`，仅学生搜题页面 OCR；返回 `ok,width,height,orientation,lines,layout,latency_ms`，不使用产品 journal 的输出代替搜题协议。

Worker / API 设置 `PRODUCT_OCR_URL=http://ocr:8080`，**不再**经 `docker.sock` 每次 `docker run`。

脚本入口：[`sidecar_server.py`](sidecar_server.py)（容器内挂载仓库 `deploy/ocr/`）。

搜题端 API 与 sidecar 共享私有存储的绝对路径。sidecar 设置 `PRODUCT_DATA_DIR=/var/lib/shuxueshuo`，
默认只读取 `work/search/private-v1/pages/<12位小写十六进制>/source.png`；非默认挂载可显式设置
`PRODUCT_SEARCH_OCR_PAGES_ROOT`。拒绝非规范路径、遍历、任意层级符号链接、非普通文件，以及超过
64 MiB / 4000 万像素的图片。文件由目录描述符逐级打开，验证后不重新按路径读取。
两个 observe 接口共用串行模型锁。产品接口保留原来一直等锁的行为，由产品客户端原有的 900 秒超时兜底；
搜索单独最多等锁 100 秒，不复用 HTTP 请求体读取的 15 秒限制。搜索客户端 HTTP 读取等待为 120 秒，
sidecar 返回首字节前的等锁和推理共用这段等待，不保证长时间排队后还能完成整次推理。请求体最多 8 KiB，搜索响应最多 2 MiB；
产品响应的 stdout/stderr 日志不套用搜索响应上限，保留原产品契约。
sidecar 启动同时严格加载产品与搜索模型，包括 `PP-LCNet_x1_0_doc_ori`，全部成功才就绪；
搜索请求不再负责首次加载。方向模型加载失败会使启动失败，不能悄悄退化为自动转正不可用。
本机 Mac 仍保留方向模型可选降级，手动旋转请求保持 `auto_orient=false`。
客户端不接受重定向或代理环境变量；远程失败只返回稳定错误码，绝不回退本地解释器。
本地 Mac 不设置 `PRODUCT_OCR_URL` 时仍使用长期子进程（启动等待 180 秒，推理等待 120 秒）。

拍题上传入口在进入 OCR 前统一处理图片：20 MiB 上传文件上限不变，所有支持格式（包括 JPEG、PNG、WebP）
统一最多 32MP（32,000,000 像素），在解码前检查；不能通过改用 JPEG 或伪造 `Content-Type` 绕过。
限额内的图片先将长边缩至最多 4096，再转正、转 RGB 并清除上传元数据；保存的 `source.png` 最多 4096×4096 像素。
API 进程内串行执行图片解码和缩图，进入 OCR 等待前释放预处理锁；不把等待模型锁或推理的时间放进该锁。
48MP/50MP 手机图片须先降低分辨率，不能只压缩文件体积。超过像素上限或触发 Pillow 解压炸弹检查返回
`413 page.pixels`，不是 OCR 服务不可用。本地与服务器使用相同入口。

### 已知容量与排队限制

- API 的 `OcrClient._lock` 仍串行处理上传 OCR，该本地锁没有排队截止时间，且不计入随后 HTTP 的 120 秒读取等待。产品整页识别占用 sidecar 数分钟时，前一个搜索请求可能等 100 秒才失败，后续请求还会继续在 API 排队；120 秒不是学生上传的端到端上限。
- 即使搜索在第 99 秒获得 sidecar 锁，留给推理和返回首字节的等待仍可能不足。客户端超时不会取消已开始的 Paddle 推理，故可能出现已耗费计算但结果未交付。此次只记录限制，不增加优先级队列、取消协议或调整锁策略。
- 统一 32MP 像素限额只约束单张解码规模；进程内解码/缩图互斥减少同时处理原始大图的峰值，但不覆盖上传请求体和等待 OCR 的已缩图图像。JPEG 缩略解码不能保证每个尺寸都在解码前降到 4096，多份请求体、图像转换副本和排队图像仍可能叠加内存。上线前需要实测并发上传及 OCR 常驻内存，按容量配置准入/并发上限，不能把像素检查或预处理互斥当成进程总内存硬限额。

### OCR 进程数量

当前 Compose 默认只有一个 `ocr` 容器，运行一个 `python sidecar_server.py` 进程；`ThreadingHTTPServer` 用线程接收请求，产品与学生搜索共用模型锁，同一时刻只执行一项推理。API 固定一个 Uvicorn worker。搜索模型配置的 `cpu_threads=8` 是模型内部计算线程数，不是 8 个 OCR 进程。

初期保持 **1 个 OCR 进程**，本轮不增加进程或副本。增加副本会重复常驻模型并争用 CPU，不能只按上传人数扩容；先测真实镜像的 CPU、RSS/峰值内存、排队时间和推理延迟。若产品长任务确实影响学生请求，再结合容量评估分别部署产品与学生 OCR 实例，而不是直接扩大当前共享 sidecar。

## 已验证基线（2026-09-12）

| 项 | 值 |
| --- | --- |
| 宿主机 | CentOS 7 x86_64，AVX/AVX2，Docker 26 |
| 镜像 | `shuxueshuo-ocr:3.3.0` |
| PaddlePaddle | 3.3.0 CPU |
| PaddleOCR | 3.7.0 + doc-parser |
| PaddleX | 3.7.2 |
| 模型缓存 | `$HOME/.paddlex/official_models/` |
| 推理后端 | `run_mode=paddle`（禁用默认 mkldnn，避免 PIR/oneDNN 崩溃） |

## 构建

Docker Hub 直连常超时，先用镜像源拉基础镜像并打本地 tag：

```bash
docker pull docker.m.daocloud.io/library/python:3.11-slim-bookworm
docker tag docker.m.daocloud.io/library/python:3.11-slim-bookworm python:3.11-slim-bookworm

cd /home/ronghao/code/shuxueshuo
docker build -t shuxueshuo-ocr:3.3.0 -f deploy/ocr/Dockerfile .
```

部署用户需能访问 Docker（`docker` 组或 sudo）。

## 手工封装（可选，非产品 server 路径）

宿主机冒烟仍可用包装脚本（每次临时容器，**产品 server 已改用 sidecar**）：

```bash
mkdir -p server/.venv-ocr/bin
cp deploy/ocr/python-wrapper.sh server/.venv-ocr/bin/python
chmod +x server/.venv-ocr/bin/python
```

## 模型预热

```bash
docker run --rm \
  -v "$HOME/code/shuxueshuo:/opt/shuxueshuo" \
  -v "$HOME/.paddlex:/root/.paddlex" \
  -w /opt/shuxueshuo/server \
  -e PADDLE_PDX_MODEL_SOURCE=bos \
  -e PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  -e OMP_NUM_THREADS=1 \
  shuxueshuo-ocr:3.3.0 \
  python /opt/shuxueshuo/deploy/ocr/preheat_models.py
```

产品 `services-start` 会启动 sidecar。双模型预热耗时须真实测量；当前 Compose 健康检查 `start_period` 为 120 秒，应用组启动等待为 240 秒，fixture 不证明这些时限对真实引擎足够。验收：

```bash
docker exec shuxueshuo-product-server-ocr-1 \
  python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/health').read())"
```

### 真实镜像本地验收与上线前复验

应用镜像加 fixture 的演练不替代真实 `shuxueshuo-ocr:3.3.0` 镜像验收。
2026-10-24 已在本机构建真实 Linux/amd64 镜像，用已有五模型缓存、UID/GID 1000、HOME=/tmp 和断网容器完成预热、12 项方向用例、产品公式推理及峰值内存检查。
缺方向缓存时不能就绪并退出 1；运行过程没有下载模型。详见[真实 OCR 本地验收记录](../../docs/search-real-ocr-local-acceptance.md)。
本机使用 Apple Silicon/Rosetta，不等同于目标服务器原生 x86 容量验收。上线前仍须在真实服务器架构、相同 UID/HOME/挂载路径下逐项复验：

1. 能导入 `shuxueshuo_server.search.ocr_protocol` 和 `shuxueshuo_server.search.ocr_worker`，不是只检查应用镜像。
2. `preheat_models.py` 成功验证全部五种模型，包括方向模型；缓存目录跟随 `Path.home()`，Compose 中是 `/tmp/.paddlex/official_models`。
3. 使用已备好的缓存、禁用网络启动 sidecar，严格预热成功且 `/health` 返回 `ok: true, ready: true`；缺方向模型必须不能就绪。
4. 用明确授权的离线图片验证方向识别、手动旋转以及产品/搜题交错调用，产品不能因搜索占锁 15 秒而失败。
5. 测量两套模型同时常驻时的启动峰值和推理峰值内存，确认容器/宿主机余量及启动时限；不能拿 fixture 的内存或延迟代替。

本机实测严格预热等待 13.77 秒，样本工作负载的容器累计峰值 3.009 GiB，OOM 为 0；不能将该值当成生产总内存上限。
仍保持一个 OCR 进程。本轮串行复用了产品/搜索路径，未替代并发上传、产品长任务和整套服务共同运行的容量复验。
`acceptance_probe.py` 可通过 `docker exec` 对已有 PID 1 sidecar 采集真实 HTTP 结果及内存；它不是 OCR 服务，不加载模型。
输出包含阶段采样最大值与内核累计峰值；指标缺失、OOM、方向不确定或请求超过 120 秒均不能整体通过。

可先在已存在的真实镜像上执行不下载模型的模块检查（仓库路径及模型缓存均需与服务器配置一致）：

```bash
docker run --rm --pull=never --network none \
  -v "$PWD:/opt/shuxueshuo:ro" -e PYTHONPATH=/opt/shuxueshuo/server \
  docker.io/library/shuxueshuo-ocr:3.3.0 python -c \
  'import shuxueshuo_server.search.ocr_protocol; import shuxueshuo_server.search.ocr_worker; print("search OCR imports OK")'
```

模块检查不加载模型，不代表后四项通过。客户端超时也不会终止已进入 Paddle 的计算；推理卡住时需诊断并重启 sidecar。

## 注意

- 不要在 CentOS 7 宿主机 `uv pip install paddlepaddle`。
- Linux CPU 上 PaddleX 默认 `mkldnn`；`paddle_worker` 已强制 `run_mode=paddle` / `enable_mkldnn=False`。
- `.venv-ocr/` 与 `~/.paddlex/` 不进 Git。
- sidecar 与 worker 共享 `/var/lib/shuxueshuo`；以部署用户 UID 运行，避免 work 目录权限问题。

当前统一 32MP / 20 MiB / 长边 4096 规则覆盖此前按格式区分及统一 10MP 的像素阈值；旧镜像演练中的 48MP JPEG 成功记录仅代表当时的代码。fixture 离线镜像演练的 24MP JPEG、32MP PNG 和超限拒绝均通过，报告见 `/private/tmp/search-image-rehearsal-20261024-32mp/report.json`；真实 OCR 镜像另有上述本地验收，不应混淆两类证据。
