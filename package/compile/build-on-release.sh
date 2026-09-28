#!/usr/bin/env bash
# 在发布分支所在的 GB10 上编译。只写编译目录，不重启现网服务。
set -euo pipefail

release_root="${WOUNDTRUTH_RELEASE_ROOT:-/home/john/WoundTruth}"
release_branch="${WOUNDTRUTH_RELEASE_BRANCH:-codex/web-geometry-audit-20260913}"
build_root="${WOUNDTRUTH_BUILD_ROOT:-/home/john/WoundTruth-build}"
web_python="${WOUNDTRUTH_WEB_PYTHON:-$release_root/code/backend/.venv/bin/python}"
sam_python="${WOUNDTRUTH_SAM2_PYTHON_BUILD:-/home/john/WoundTruth-dev/sam2-lab/venv/bin/python}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

fail() {
  printf '编译停止: %s\n' "$*" >&2
  exit 1
}

if ! command -v patchelf >/dev/null 2>&1; then
  export PATH="/home/john/WoundTruth-build/tools/patchelf/usr/bin:${PATH}"
fi
command -v patchelf >/dev/null 2>&1 || fail "没有 patchelf。系统未安装时，先把 Ubuntu 的 patchelf 解到 /home/john/WoundTruth-build/tools/patchelf"

[[ -d "$release_root/.git" ]] || fail "找不到发布仓库 $release_root"
branch="$(git -C "$release_root" rev-parse --abbrev-ref HEAD)"
[[ "$branch" == "$release_branch" ]] || fail "当前分支是 $branch，要在 $release_branch 上编译"
if [[ -n "$(git -C "$release_root" status --porcelain -- code/backend code/frontend)" ]]; then
  fail "发布仓库 code/backend 或 code/frontend 有未提交改动。封版只从干净提交编译"
fi
[[ -x "$web_python" ]] || fail "没有网页虚拟环境 $web_python"
[[ -x "$sam_python" ]] || fail "没有 SAM2 虚拟环境 $sam_python"
[[ -x /usr/bin/python3.12 ]] || fail "没有 /usr/bin/python3.12。工人要靠它编译，避免把构建机虚拟环境路径写进二进制"
"$web_python" -m nuitka --version >/dev/null 2>&1 || fail "网页虚拟环境里没有 nuitka"
"$sam_python" -m nuitka --version >/dev/null 2>&1 || fail "SAM2 虚拟环境里没有 nuitka"

part="${1:-all}"
# 源码快照放在不含用户名的目录里，避免工人二进制带上构建机家目录。
src="/tmp/woundtruth-src"
[[ "$src" == /tmp/woundtruth-src ]] || fail "编译源码目录必须是 /tmp/woundtruth-src"
out="$build_root/out"
rm -rf "$src"
if [[ "$part" == "all" ]]; then
  rm -rf "$out"
fi
mkdir -p "$src" "$out"
rsync -a --delete "$release_root/code/backend/app/" "$src/app/"
"$web_python" "$script_dir/apply_deploy_contract.py" "$src"

cat > "$src/serve_entry.py" << 'PY'
import os
import uvicorn
from app.main import app

def main() -> None:
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), log_level="info")

if __name__ == "__main__":
    main()
PY

cat > "$src/worker_entry.py" << 'PY'
import os
import sys
from pathlib import Path

python = Path(os.environ["WOUNDTRUTH_SAM2_PYTHON"]).absolute()
site = python.parent.parent / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
if not site.is_dir():
    raise SystemExit(f"sam2 site-packages missing: {site}")
sys.path.insert(0, str(site))

from app.sam2_worker import main

if __name__ == "__main__":
    main()
PY

cd "$src"
if [[ "$part" == "all" ]]; then
CUDA_VISIBLE_DEVICES="" "$web_python" -m nuitka \
  --standalone \
  --assume-yes-for-downloads \
  --lto=no \
  --output-dir="$out" \
  --output-filename=woundtruth-web \
  --nofollow-import-to=app.sam2_worker \
  --include-module=uvicorn.logging \
  --include-module=uvicorn.loops \
  --include-module=uvicorn.loops.auto \
  --include-module=uvicorn.protocols.http.auto \
  --include-module=uvicorn.protocols.websockets.auto \
  --include-module=uvicorn.lifespan.on \
  serve_entry.py
fi

rm -rf "$out/worker_entry.build" "$out/sam2-worker"
# 用系统 Python 跑 Nuitka，二进制里的 sys.prefix 才是 /usr，而不是构建机虚拟环境。
# 编译期仍从 SAM2 虚拟环境读取 Nuitka；加速模式只编译工人实际导入的模块。
sam_site="$(cd "$(dirname "$sam_python")/../lib/python3.12/site-packages" && pwd)"
# 加速模式：只编译工人实际导入的模块。标准库用系统 Python 3.12，PyTorch 从虚拟环境加载。
PYTHONPATH="${sam_site}${PYTHONPATH:+:$PYTHONPATH}" CUDA_VISIBLE_DEVICES="" /usr/bin/python3.12 -m nuitka \
  --lto=no \
  --output-dir="$out" \
  --output-filename=sam2-worker \
  --follow-import-to=app \
  --nofollow-import-to=app.main \
  --nofollow-import-to=app.store \
  --nofollow-import-to=app.agent_runtime \
  --nofollow-import-to=app.integrity \
  --nofollow-import-to=app.assistant_context \
  --nofollow-import-to=app.assistant_persistence \
  --nofollow-import-to=app.assistant_snapshot \
  --nofollow-import-to=app.patient_assistant_snapshot \
  --nofollow-import-to=app.patient_projection \
  --nofollow-import-to=app.signature_scope \
  --nofollow-import-to=app.sam2_service \
  --nofollow-import-to=app.sam2_commit \
  --nofollow-import-to=app.export_compatibility \
  --nofollow-import-to=app.export_validation \
  --nofollow-import-to=app.demo_integrity \
  --nofollow-import-to=app.compatibility \
  --nofollow-import-to=app.pose_capability \
  --nofollow-import-to=app.camera_measurement \
  --nofollow-import-to=torch \
  --nofollow-import-to=torchvision \
  --nofollow-import-to=transformers \
  --nofollow-import-to=cv2 \
  --nofollow-import-to=numpy \
  --nofollow-import-to=PIL \
  --nofollow-import-to=huggingface_hub \
  --nofollow-import-to=safetensors \
  --nofollow-import-to=tokenizers \
  --nofollow-import-to=triton \
  worker_entry.py

if [[ "$part" == "all" ]]; then
frontend="$release_root/code/frontend"
[[ -x "$frontend/node_modules/.bin/vite" ]] || fail "前端依赖没装好：$frontend/node_modules"
(
  cd "$frontend"
  npx tsc -b
  npx vite build --outDir "$out/frontend-dist" --emptyOutDir
)
[[ -f "$out/frontend-dist/index.html" ]] || fail "前端构建没有 index.html"
[[ -d "$out/serve_entry.dist" ]] || fail "没有网页编译结果"
fi
[[ -x "$out/sam2-worker" ]] || fail "没有 SAM2 工人编译结果"
command -v strings >/dev/null 2>&1 || fail "没有 strings，不能把扫描失败当成没有命中"
# strings 非零是扫描失败。grep 退出码 1 才是没有命中。
reject_if_binary_contains() {
  local file="$1"
  local needle="$2"
  local output status hit
  [[ -r "$file" ]] || fail "无法读取 $file，不能把它当成扫描通过"
  output="$(strings -a "$file" 2>&1)" && status=0 || status=$?
  if [[ "$status" -ne 0 ]]; then
    fail "strings 扫描 $file 失败，退出码 $status"
  fi
  hit="$(printf '%s\n' "$output" | grep -F -- "$needle")" && status=0 || status=$?
  if [[ "$status" -eq 0 ]]; then
    fail "$file 含有 ${needle}: $(printf '%s\n' "$hit" | head -3)"
  fi
  if [[ "$status" -ne 1 ]]; then
    fail "grep 扫描 $file 失败，退出码 $status"
  fi
}
reject_if_binary_contains "$out/sam2-worker" "/home/john"
reject_if_binary_contains "$out/sam2-worker" "192.168.1.25"
if [[ "$part" == "all" ]]; then
  web_bin="$(find "$out/serve_entry.dist" -maxdepth 1 -type f -perm -111 \( -name 'woundtruth-web' -o -name 'woundtruth-web.bin' -o -name 'serve_entry' -o -name 'serve_entry.bin' \) | head -1)"
  [[ -n "$web_bin" ]] || fail "没有网页可执行文件，无法检查内网地址"
  reject_if_binary_contains "$web_bin" "192.168.1.25"
  reject_if_binary_contains "$web_bin" "/home/john"
fi
printf '编译完成 %s\n' "$out"
