#!/usr/bin/env bash
# 把已经提交好的部署仓库推到一个私有 GitHub 仓库。不编译，不重启现网。
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repo_name="${WOUNDTRUTH_GITHUB_REPO:-woundtruth}"
visibility="${WOUNDTRUTH_GITHUB_VISIBILITY:-private}"

fail() {
  printf '发布停止: %s\n' "$*" >&2
  exit 1
}

if ! command -v gh >/dev/null 2>&1; then
  if [[ -x /tmp/gh-cli/bin/gh ]]; then
    export PATH="/tmp/gh-cli/bin:${PATH}"
  fi
fi
command -v gh >/dev/null 2>&1 || fail "没有 gh。先安装 GitHub CLI 并完成 gh auth login"
gh auth status >/dev/null 2>&1 || fail "gh 还没有登录。先执行 gh auth login，再重新运行"

cd "$root"
[[ -z "$(git status --porcelain)" ]] || fail "工作区还有未提交的改动"
git rev-parse --verify main >/dev/null

owner="$(gh api user --jq .login)"
full="${owner}/${repo_name}"

if gh repo view "$full" >/dev/null 2>&1; then
  echo "仓库已存在: $full"
else
  gh repo create "$full" --"$visibility" --description "WoundTruth deploy package" --source "$root" --remote origin
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  git remote add origin "https://github.com/${full}.git"
fi

git push -u origin main
echo "已推送 https://github.com/${full}"
