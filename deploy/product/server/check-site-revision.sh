#!/usr/bin/env bash
# Read-only guard for a full release; page-only git updates remain independent.
set -euo pipefail
source "$(dirname "$0")/../lib/common.sh"

repo='' revision='' allow_forward=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) repo=${2:?}; shift 2;;
    --revision) revision=${2:?}; shift 2;;
    --allow-forward) allow_forward=1; shift;;
    *) fail "未知参数：$1";;
  esac
done
[[ "$revision" =~ ^([a-f0-9]{40}|[a-f0-9]{64})$ ]] || fail '需要发布包的完整 PRODUCT_SOURCE_REVISION'
[[ -d "$repo" ]] || fail '服务器站点仓库不存在'
repo=$(cd "$repo" && pwd -P)
top=$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null) || fail '站点目录不是 Git 工作树'
[[ "$(cd "$top" && pwd -P)" == "$repo" ]] || fail '--repo 必须指向站点仓库根目录'
worktree_status=$(git -C "$repo" status --porcelain --untracked-files=all --ignore-submodules=none) || fail '无法检查站点仓库状态'
[[ -z "$worktree_status" ]] || fail '站点仓库有未提交或未跟踪的改动；请先处理，再发布'
target=$(git -C "$repo" rev-parse --verify "${revision}^{commit}" 2>/dev/null) || fail '仓库没有目标提交；请先 git fetch 获取已推送的发布提交'
[[ "$target" == "$revision" ]] || fail '发布修订必须是完整的 commit ID'
head=$(git -C "$repo" rev-parse --verify HEAD)
if [[ "$allow_forward" == 1 ]]; then
  git -C "$repo" merge-base --is-ancestor "$head" "$target" || fail '站点仓库已领先于目标提交或与其分叉；停止发布，不自动回退'
else
  [[ "$head" == "$target" ]] || fail '站点仓库 HEAD 与发布包提交不同；请更新到目标提交后再校验'
fi
printf '站点提交检查通过：%s\n' "$head"
