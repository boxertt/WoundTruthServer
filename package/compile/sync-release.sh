#!/usr/bin/env bash
# 发布分支有改动时，在 GB10 上重新编译，再把可执行文件和网页同步回这个仓库。
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
host="${WOUNDTRUTH_RELEASE_HOST:-woundtruth-gb10}"
ssh_config="${WOUNDTRUTH_SSH_CONFIG:-$HOME/.ssh/woundtruth_remote_20260913.conf}"
release_root="${WOUNDTRUTH_RELEASE_ROOT:-/home/john/WoundTruth}"
release_branch="${WOUNDTRUTH_RELEASE_BRANCH:-codex/web-geometry-audit-20260913}"
build_root="${WOUNDTRUTH_BUILD_ROOT:-/home/john/WoundTruth-build}"
force=0
if [[ "${1:-}" == "--force" ]]; then
  force=1
fi

fail() {
  printf '同步停止: %s\n' "$*" >&2
  exit 1
}

[[ -f "$ssh_config" ]] || fail "找不到 SSH 配置 $ssh_config"
ssh_cmd=(ssh -F "$ssh_config" -o BatchMode=yes "$host")
rsync_ssh="ssh -F ${ssh_config} -o BatchMode=yes"

remote_id="$("${ssh_cmd[@]}" "git -C '$release_root' rev-parse --abbrev-ref HEAD && git -C '$release_root' rev-parse HEAD && git -C '$release_root' diff HEAD -- code/backend code/frontend && git -C '$release_root' status --porcelain -- code/backend code/frontend")"
branch="$(printf '%s\n' "$remote_id" | head -1)"
commit="$(printf '%s\n' "$remote_id" | sed -n '2p')"
[[ "$branch" == "$release_branch" ]] || fail "发布机当前是 $branch，不是 $release_branch"
dirty="$("${ssh_cmd[@]}" "git -C '$release_root' status --porcelain -- code/backend code/frontend")"
[[ -z "$dirty" ]] || fail "发布仓库 code/backend 或 code/frontend 有未提交改动。封版只从干净提交编译"
id="$(printf '%s\n' "$remote_id" | shasum -a 256 | awk '{print $1}')"
stamp="$root/bin/SOURCE-REV"
if [[ "$force" -eq 0 && -f "$stamp" ]] && grep -q "^id=$id$" "$stamp" && [[ -d "$root/bin/woundtruth-web.dist" && -x "$root/bin/sam2-worker" ]]; then
  printf '发布分支没有新的改动，跳过编译。\n当前 %s %s\n' "$branch" "$commit"
  exit 0
fi

printf '开始编译 %s %s\n' "$branch" "$commit"
remote_compile="$build_root/compile"
"${ssh_cmd[@]}" "mkdir -p '$remote_compile'"
rsync -a -e "$rsync_ssh" \
  "$root/compile/build-on-release.sh" \
  "$root/compile/apply_deploy_contract.py" \
  "$host:$remote_compile/"
"${ssh_cmd[@]}" "chmod +x '$remote_compile/build-on-release.sh' && WOUNDTRUTH_RELEASE_ROOT='$release_root' WOUNDTRUTH_RELEASE_BRANCH='$release_branch' WOUNDTRUTH_BUILD_ROOT='$build_root' '$remote_compile/build-on-release.sh'"

rm -rf "$root/bin/woundtruth-web.dist" "$root/bin/sam2-worker.dist" "$root/web/dist"
mkdir -p "$root/bin" "$root/web/dist"
rsync -a -e "$rsync_ssh" "$host:$build_root/out/serve_entry.dist/" "$root/bin/woundtruth-web.dist/"
rsync -a -e "$rsync_ssh" "$host:$build_root/out/sam2-worker" "$root/bin/sam2-worker"
rsync -a --delete -e "$rsync_ssh" "$host:$build_root/out/frontend-dist/" "$root/web/dist/"

web_bin="$(find "$root/bin/woundtruth-web.dist" -maxdepth 1 -type f -perm -111 \( -name 'woundtruth-web' -o -name 'woundtruth-web.bin' -o -name 'serve_entry' -o -name 'serve_entry.bin' \) | head -1)"
[[ -n "$web_bin" && -x "$root/bin/sam2-worker" ]] || fail "编译结果里没有可执行文件"
web_name="$(basename "$web_bin")"
chmod +x "$root/bin/sam2-worker"

cat > "$root/bin/woundtruth-web" << EOF
#!/bin/sh
set -eu
here=\$(CDPATH= cd -- "\$(dirname "\$0")" && pwd)
exec "\$here/woundtruth-web.dist/$web_name"
EOF
chmod +x "$root/bin/woundtruth-web"

cat > "$stamp" << EOF
branch=$branch
commit=$commit
id=$id
tree=clean
web=$web_name
worker=sam2-worker
EOF
printf '已同步到 %s\n提交 %s\n' "$root/bin" "$commit"
