#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"
release='' operation='' root=${PRODUCT_DATA_DIR:-/srv/shuxueshuo} instance=server port='' backup='' target='' search_recovery_root='' replace_public=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) [[ "$2" == server ]] || fail 'server mode required'; shift 2;;
    --release) release=${2:?}; shift 2;;
    --data-dir) root=${2:?}; shift 2;;
    --instance) instance=${2:?}; shift 2;;
    --port) port=${2:?}; shift 2;;
    --backup) backup=${2:?}; shift 2;;
    --search-recovery-root) search_recovery_root=${2:?}; shift 2;;
    --target) target=${2:?}; shift 2;;
    --replace-legacy-public) replace_public=1; shift;;
    install|deploy|prepare-release|preflight-learning|verify-release|resume|status|migrate|seed|doctor|backup|backup-prune|restore|bootstrap|publish-learning|check-learning|reassess-learning|services-install|services-start|services-stop|services-status|services-doctor) operation=$1; shift;;
    *) fail "未知参数：$1";;
  esac
done
if [[ -z "$port" && -f "$root/config/compose.env" ]]; then
  port=$(sed -n "s/^PRODUCT_DB_PORT='\([0-9]*\)'$/\1/p" "$root/config/compose.env")
fi
port=${port:-5432}
[[ "$root" == /* && "$root" != / ]] || fail '需要 Git 外绝对数据目录'
if [[ -f "$PRODUCT_REPO/server/pyproject.toml" && "$root" == "$PRODUCT_REPO"* ]]; then fail '数据目录不能在 Git 内'; fi
[[ "$instance" =~ ^[a-z][a-z0-9_-]{0,39}$ && "$port" =~ ^[0-9]+$ ]] || fail '实例或端口无效'
[[ -n "$operation" ]] || fail '缺少管理操作'
case "$operation" in
  services-start|services-doctor|resume|deploy)
    [[ ! -e "$root/locks/restore-incomplete" ]] || fail '恢复尚未完成，禁止启动；请使用新目标重新恢复';;
esac
if [[ "$operation" == preflight-learning && ! -f "$root/config/compose.env" ]]; then
  printf '%s\n' '{"state":"empty","revision":null,"counts":{},"action":"install"}'
  exit 0
fi
[[ "$replace_public" == 0 || "$operation" == deploy ]] || fail '--replace-legacy-public 仅适用于 deploy'
if [[ "$operation" != install && "$operation" != restore && "$operation" != prepare-release && ! -f "$root/config/compose.env" ]]; then
  fail '实例尚未安装'
fi
if [[ -z "$release" && -f "$root/config/release-path" ]]; then release=$(cat "$root/config/release-path"); fi
[[ "$release" == /* && -f "$release/release.env" ]] || fail '--release 需要完整发布包的绝对路径'
command -v docker >/dev/null || fail '请预装 Docker/Compose'
docker compose version >/dev/null
# Parse a restricted data format, never source/eval the release manifest.
PRODUCT_RABBITMQ_IMAGE=''
PRODUCT_RABBITMQ_MANIFEST=''
PRODUCT_APP_IMAGE=''
PRODUCT_ADMIN_IMAGE_OCI=''
PRODUCT_APP_IMAGE_OCI=''
PRODUCT_POSTGRES_IMAGE_OCI=''
PRODUCT_RABBITMQ_IMAGE_OCI=''
while IFS='=' read -r key value; do
  [[ "$key" =~ ^PRODUCT_[A-Z_]+$ && "$value" =~ ^[a-zA-Z0-9/.:@_-]+$ ]] || fail '发布清单格式错误'
  case "$key" in
    PRODUCT_RELEASE_ID|PRODUCT_PLATFORM|PRODUCT_ADMIN_IMAGE|PRODUCT_POSTGRES_IMAGE|PRODUCT_POSTGRES_MANIFEST|PRODUCT_ALEMBIC_REVISION|PRODUCT_SOURCE_REVISION|PRODUCT_CONTENT_VERSION|PRODUCT_CONTENT_SCHEMA)
      export "$key=$value";;
    PRODUCT_RABBITMQ_IMAGE|PRODUCT_RABBITMQ_MANIFEST|PRODUCT_APP_IMAGE|PRODUCT_ADMIN_IMAGE_OCI|PRODUCT_APP_IMAGE_OCI|PRODUCT_POSTGRES_IMAGE_OCI|PRODUCT_RABBITMQ_IMAGE_OCI)
      export "$key=$value";;
    *) fail '未知发布字段';;
  esac
done < "$release/release.env"
[[ "$PRODUCT_ADMIN_IMAGE" == sha256:* && "$PRODUCT_POSTGRES_IMAGE" == sha256:* ]] || fail '镜像必须固定内容 ID'
resolve_image() {
  local key=$1 alternate_key="${1}_OCI" primary alternate candidate actual
  primary=${!key}; alternate=${!alternate_key}
  [[ -n "$primary" ]] || return 0
  [[ "$primary" =~ ^sha256:[a-f0-9]{64}$ ]] || fail '镜像内容 ID 无效'
  [[ -z "$alternate" || "$alternate" =~ ^sha256:[a-f0-9]{64}$ ]] || fail 'OCI 镜像内容 ID 无效'
  for candidate in "$primary" "$alternate"; do
    [[ -n "$candidate" ]] || continue
    actual=$(docker image inspect --format '{{.Id}}' "$candidate" 2>/dev/null) || continue
    [[ "$actual" == "$primary" || "$actual" == "$alternate" ]] || fail '镜像身份不在归档候选中'
    printf -v "$key" '%s' "$actual"
    export "$key"
    return 0
  done
  return 1
}
need_load=0
for image_key in PRODUCT_ADMIN_IMAGE PRODUCT_POSTGRES_IMAGE PRODUCT_APP_IMAGE PRODUCT_RABBITMQ_IMAGE; do
  resolve_image "$image_key" || need_load=1
done
if [[ "$need_load" == 1 ]]; then
  [[ "$operation" != preflight-learning ]] || fail '只读预检不加载镜像，请先执行 prepare-release'
  [[ "$(checksum "$release/images.tar")" == "$(cat "$release/images.sha256")" ]] || fail '离线镜像包校验失败'
  docker load -i "$release/images.tar"
fi
for image_key in PRODUCT_ADMIN_IMAGE PRODUCT_POSTGRES_IMAGE PRODUCT_APP_IMAGE PRODUCT_RABBITMQ_IMAGE; do
  resolve_image "$image_key" || fail "无法加载归档中的固定镜像身份：$image_key"
done
docker run --rm --entrypoint /opt/product/bin/python -v "$release:/release:ro" "$PRODUCT_ADMIN_IMAGE" -c \
 'import hashlib,json,pathlib; p=pathlib.Path("/release"); m=json.loads((p/"manifest.json").read_text()); assert all(hashlib.sha256((p/n).read_bytes()).hexdigest()==h for n,h in m["files"].items()), "release checksum mismatch"'
actual_platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$PRODUCT_ADMIN_IMAGE")
[[ "$actual_platform" == "$PRODUCT_PLATFORM" ]] || fail '镜像架构与清单不一致'
if ! cmp -s "$0" "$release/scripts/server/run.sh"; then fail '请使用目标发布包 scripts/server/run.sh 或对应版本脚本'; fi
export PRODUCT_DATA_DIR="$root" PRODUCT_INSTANCE="$instance" PRODUCT_DB_PORT="$port" PRODUCT_UID="$(id -u)" PRODUCT_GID="$(id -g)"
# Server OCR is the compose sidecar (PRODUCT_OCR_URL). Mac/local uses REVIEW_OCR_PYTHON.
PRODUCT_OCR_URL="${PRODUCT_OCR_URL:-http://ocr:8080}"
export PRODUCT_OCR_URL
PRODUCT_HOST_HOME="${PRODUCT_HOST_HOME:-$HOME}"
PRODUCT_REPO_HOST="${PRODUCT_REPO_HOST:-$PRODUCT_HOST_HOME/code/shuxueshuo}"
PRODUCT_OCR_IMAGE="${PRODUCT_OCR_IMAGE:-shuxueshuo-ocr:3.3.0}"
export PRODUCT_REPO_HOST PRODUCT_HOST_HOME PRODUCT_OCR_IMAGE
if [[ "$operation" == verify-release ]]; then
  # A full release must use this exact clean checkout. services-start/doctor
  # call the content-only optional check below, allowing independent page updates.
  bash "$PRODUCT_SCRIPTS/server/check-site-revision.sh" \
    --repo "$PRODUCT_REPO_HOST" --revision "${PRODUCT_SOURCE_REVISION:-}"
fi
if [[ "$operation" == prepare-release ]]; then
  printf '%s\n' '{"ok":true,"prepared":"images_and_manifest","instance_changed":false}'
  exit 0
fi
if [[ "$operation" == preflight-learning ]]; then
  # Existing network and read-only mounts only: no configure, locks, volume or service startup.
  exec docker run --rm --read-only --tmpfs /tmp --security-opt no-new-privileges:true \
    --user "$PRODUCT_UID:$PRODUCT_GID" --network "shuxueshuo-product-${instance}_default" \
    -e PRODUCT_IN_CONTAINER=1 -v "$root:/var/lib/shuxueshuo:ro" "$PRODUCT_ADMIN_IMAGE" \
    --mode server --data-dir /var/lib/shuxueshuo --instance "$instance" --port "$port" preflight-learning
fi
mkdir -p "$root"
mkdir -p "$root/locks"
mkdir "$root/locks/server-operation" 2>/dev/null || fail '已有服务器管理操作运行；检查遗留锁后再重试'
trap 'rmdir "$root/locks/server-operation"' EXIT
configure=(docker run --rm --user "$PRODUCT_UID:$PRODUCT_GID" -e PRODUCT_IN_CONTAINER=1 -e "PRODUCT_HOST_DATA_DIR=$root" -e "PRODUCT_OCR_URL=$PRODUCT_OCR_URL" -v "$root:/var/lib/shuxueshuo" "$PRODUCT_ADMIN_IMAGE")
if [[ "$operation" == restore ]]; then
  [[ -n "$target" && -n "$backup" && ! -e "$root/config" ]] || fail '恢复需要新实例、新目录和 --backup'
  instance="$target"; export PRODUCT_INSTANCE="$instance"
fi
volume="shuxueshuo-product-${instance}_postgres_data"
if docker volume inspect "$volume" >/dev/null 2>&1; then
  volume_root=$(docker volume inspect --format '{{ index .Labels "product.data-root" }}' "$volume")
  [[ "$volume_root" == "$root" ]] || fail '已有数据库卷绑定另一数据目录，拒绝复用'
fi
"${configure[@]}" --mode server --data-dir /var/lib/shuxueshuo --instance "$instance" --port "$port" configure
PRODUCT_BOOTSTRAP_PASSWORD=$(sed -n "s/^PRODUCT_BOOTSTRAP_PASSWORD='\([^']*\)'$/\1/p" "$root/config/bootstrap.env")
export PRODUCT_BOOTSTRAP_PASSWORD
compose=(docker compose --project-name "shuxueshuo-product-$instance" -f "$release/scripts/compose.yml" -f "$release/scripts/compose.server.yml")
compose_app=("${compose[@]}" -f "$release/scripts/compose.app.yml")
# The public site is the repository's site/ (git pull); admin only reads its teaching content version.
site_mount=() site_flag=()
if [[ -f "$PRODUCT_REPO_HOST/site/knowledge/teaching/version.json" ]]; then
  site_mount=(-v "$PRODUCT_REPO_HOST/site/knowledge/teaching:/site-teaching:ro")
  site_flag=(--site-version /site-teaching/version.json)
fi
admin=("${compose[@]}" run --rm --no-deps ${site_mount[@]+"${site_mount[@]}"} -e "PRODUCT_OCR_URL=$PRODUCT_OCR_URL" admin ${site_flag[@]+"${site_flag[@]}"} --mode server --data-dir /var/lib/shuxueshuo --instance "$instance" --port "$port")
# Join the app network so admin can resolve rabbitmq/api/ocr service names.
admin_net=("${compose_app[@]}" run --rm ${site_mount[@]+"${site_mount[@]}"} -e "PRODUCT_OCR_URL=$PRODUCT_OCR_URL" admin ${site_flag[@]+"${site_flag[@]}"} --mode server --data-dir /var/lib/shuxueshuo --instance "$instance" --port "$port")

load_runtime_exports() {
  [[ -f "$root/config/runtime.env" ]] || fail '请先执行 services-install'
  PRODUCT_BROKER_PORT=$(sed -n "s/^BROKER_PORT='\([^']*\)'$/\1/p" "$root/config/runtime.env")
  PRODUCT_BROKER_USER=$(sed -n "s/^BROKER_USER='\([^']*\)'$/\1/p" "$root/config/runtime.env")
  PRODUCT_BROKER_PASSWORD=$(sed -n "s/^BROKER_PASSWORD='\([^']*\)'$/\1/p" "$root/config/runtime.env")
  PRODUCT_BROKER_VHOST=$(sed -n "s/^BROKER_VHOST='\([^']*\)'$/\1/p" "$root/config/runtime.env")
  PRODUCT_BROKER_COOKIE=$(sed -n "s/^BROKER_COOKIE='\([^']*\)'$/\1/p" "$root/config/runtime.env")
  PRODUCT_API_PORT=$(sed -n "s/^API_PORT='\([^']*\)'$/\1/p" "$root/config/runtime.env")
  PRODUCT_FRONTEND_PORT=$(sed -n "s/^FRONTEND_PORT='\([^']*\)'$/\1/p" "$root/config/runtime.env")
  export PRODUCT_BROKER_PORT PRODUCT_BROKER_USER PRODUCT_BROKER_PASSWORD PRODUCT_BROKER_VHOST PRODUCT_BROKER_COOKIE PRODUCT_API_PORT PRODUCT_FRONTEND_PORT
  [[ -n "$PRODUCT_BROKER_PORT" && -n "$PRODUCT_BROKER_USER" && -n "$PRODUCT_BROKER_PASSWORD" && -n "$PRODUCT_BROKER_VHOST" && -n "$PRODUCT_BROKER_COOKIE" ]] || fail 'runtime.env broker 字段不完整'
  PRODUCT_API_PORT=${PRODUCT_API_PORT:-8000}
  PRODUCT_FRONTEND_PORT=${PRODUCT_FRONTEND_PORT:-3000}
  export PRODUCT_API_PORT PRODUCT_FRONTEND_PORT
}

require_app_release() {
  [[ "$PRODUCT_APP_IMAGE" == sha256:* ]] || fail '当前发布包缺少 PRODUCT_APP_IMAGE；请使用包含 API/Worker 的 P2 发布包'
  [[ "$PRODUCT_RABBITMQ_IMAGE" == sha256:* ]] || fail '当前发布包缺少 PRODUCT_RABBITMQ_IMAGE；请使用包含 RabbitMQ 的 P2 发布包'
  [[ -f "$PRODUCT_REPO_HOST/server/.env" ]] || fail "缺少模型密钥文件：$PRODUCT_REPO_HOST/server/.env"
  docker image inspect "$PRODUCT_OCR_IMAGE" >/dev/null 2>&1 || fail "缺少 OCR 镜像：$PRODUCT_OCR_IMAGE（请先按 deploy/ocr 安装）"
  mkdir -p "$PRODUCT_HOST_HOME/.paddlex"
}

case "$operation" in
  install)
    if [[ -f "$root/config/release-path" && "$(cat "$root/config/release-path")" != "$release" ]]; then
      fail '已安装实例的版本变更必须使用 deploy.sh'
    fi
    "${compose[@]}" up -d --wait --wait-timeout 90 postgres; "${admin[@]}" install;;
  deploy)
    [[ -f "$root/config/release-path" ]] || fail '实例尚未安装'
    postgres_container=$("${compose[@]}" ps -q postgres)
    [[ -n "$postgres_container" ]] || fail '数据库容器未运行'
    [[ "$(docker inspect --format '{{.Image}}' "$postgres_container")" == "$PRODUCT_POSTGRES_IMAGE" ]] || fail '数据库镜像变更需要独立备份和升级流程'
    replacement=()
    [[ "$replace_public" == 0 ]] || replacement=(--replace-legacy-public)
    "${admin[@]}" deploy ${replacement[@]+"${replacement[@]}"};;
  restore)
    "${compose[@]}" up -d --wait --wait-timeout 90 postgres
    "${admin[@]}" bootstrap
    recovery_mount=()
    if [[ -n "$search_recovery_root" ]]; then
      [[ "$search_recovery_root" == /* && -d "$search_recovery_root/recovery" ]] || fail '--search-recovery-root 需要当前源拍题目录的绝对路径'
      recovery_mount=(-v "$search_recovery_root:/search-authority:ro")
    fi
    "${compose[@]}" run --rm --no-deps -v "$backup:/restore:ro" ${recovery_mount[@]+"${recovery_mount[@]}"} --entrypoint /opt/product/bin/python admin -c \
      'import sys; from shuxueshuo_server.product.config import Settings; from shuxueshuo_server.product.admin.backup import restore_data; s=Settings.load("server","/var/lib/shuxueshuo",sys.argv[1],int(sys.argv[2])); print(restore_data(s,"/restore",search_recovery_root="/search-authority" if sys.argv[3] else None))' "$instance" "$port" "$search_recovery_root";;
  services-install)
    [[ "$PRODUCT_RABBITMQ_IMAGE" == sha256:* ]] || fail '当前发布包缺少 PRODUCT_RABBITMQ_IMAGE；请使用包含 RabbitMQ 的 P2 发布包'
    "${admin[@]}" services-install;;
  services-start)
    require_app_release
    load_runtime_exports
    rabbit_volume="shuxueshuo-product-${instance}_rabbitmq_data"
    if docker volume inspect "$rabbit_volume" >/dev/null 2>&1; then
      volume_root=$(docker volume inspect --format '{{ index .Labels "product.data-root" }}' "$rabbit_volume")
      [[ "$volume_root" == "$root" ]] || fail '已有 RabbitMQ 卷绑定另一数据目录，拒绝复用'
    fi
    "${compose[@]}" up -d --wait --wait-timeout 90 postgres
    "${admin[@]}" verify-release --site-optional
    "${compose_app[@]}" up -d --wait --wait-timeout 240 rabbitmq ocr api worker publisher
    "${admin_net[@]}" services-doctor
    rm -f "$root/locks/services-draining";;
  services-stop)
    [[ "$PRODUCT_APP_IMAGE" == sha256:* ]] || fail '当前发布包缺少 PRODUCT_APP_IMAGE；请使用包含 API/Worker 的 P2 发布包'
    [[ -f "$release/scripts/compose.app.yml" ]] || fail '发布包缺少 compose.app.yml'
    load_runtime_exports
    touch "$root/locks/services-draining"
    "${compose_app[@]}" stop api
    "${compose_app[@]}" stop worker publisher
    "${compose_app[@]}" stop ocr rabbitmq
    printf '%s\n' '{"ok": true, "api": "stopped", "worker": "stopped", "publisher": "stopped", "ocr": "stopped", "rabbitmq": "stopped", "postgres": "left_running"}';;
  services-status)
    [[ "$PRODUCT_APP_IMAGE" == sha256:* ]] || fail '当前发布包缺少 PRODUCT_APP_IMAGE；请使用包含 API/Worker 的 P2 发布包'
    load_runtime_exports
    "${compose_app[@]}" ps rabbitmq ocr api worker publisher
    "${admin_net[@]}" services-status;;
  services-doctor)
    require_app_release
    load_runtime_exports
    "${compose[@]}" up -d --wait --wait-timeout 90 postgres
    "${admin[@]}" verify-release --site-optional
    "${compose_app[@]}" up -d --wait --wait-timeout 240 rabbitmq ocr api worker publisher
    "${admin_net[@]}" services-doctor;;
  *) "${admin[@]}" "$operation";;
esac
# services-start also pins release-path: otherwise a successful --release switch
# leaves the next unattended start on the previous package.
if [[ "$operation" == install || "$operation" == deploy || "$operation" == restore || "$operation" == services-install || "$operation" == services-start ]]; then
  printf '%s\n' "$release" > "$root/config/release-path"
  mkdir -p "$root/deployments"
  printf '{"release":"%s","operation":"%s","status":"succeeded"}\n' "$PRODUCT_RELEASE_ID" "$operation" > "$root/deployments/$(date -u +%Y%m%dT%H%M%SZ).json"
fi
