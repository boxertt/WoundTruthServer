#!/usr/bin/env bash
# 环境检查通过之后：启动 Ollama，重建 SAM2 环境，拉取权重和本地模型，再启动网页。
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$root/deploy/lib.sh"
req="$root/deploy/sam2-requirements.txt"
checksums="$root/deploy/sam2-model.sha256"
venv="$root/runtime/sam2-venv"
py="$venv/bin/python"
model="$root/runtime/models/facebook-sam2.1-hiera-tiny"
torch_index="https://download.pytorch.org/whl/cu130"
started_pid=""
started_ollama=0
model_partial=""

fail() {
  printf '停止: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  local status=$?
  local current_pid=""
  trap - EXIT
  if [[ "$status" -ne 0 && -n "$started_pid" ]]; then
    current_pid="$(unit_main_pid)"
    if [[ "$current_pid" == "$started_pid" ]]; then
      systemctl --user stop woundtruth.service || true
      printf '部署未完成，已停止本次启动的进程 %s。\n' "$started_pid" >&2
    else
      printf '部署未完成。当前 MainPID 是 %s，不是本次启动的 %s，所以没有按服务名停止。\n' "${current_pid:-无}" "$started_pid" >&2
    fi
  fi
  if [[ "$status" -ne 0 && "$started_ollama" -eq 1 ]]; then
    printf '部署未完成。本次启动的 ollama.service 仍在运行。\n' >&2
  fi
  if [[ "$status" -ne 0 && -n "$model_partial" && -d "$model_partial" ]]; then
    rm -rf "$model_partial"
  fi
  exit "$status"
}
trap cleanup EXIT

command -v flock >/dev/null 2>&1 || fail "没有 flock，不能防止两次部署同时执行"
lock_path="$(deploy_lock_path)"
mkdir -p "$(dirname "$lock_path")"
exec 9>"$lock_path"
if ! flock -n 9; then
  fail "已有一次部署在执行，锁在 ${lock_path}。同一用户下的另一个目录也不能同时操作 woundtruth.service"
fi

verify_sam2_runtime() {
  "$py" - <<'PY'
import cv2
import torch
import transformers
from importlib.metadata import version
assert torch.__version__.startswith("2.9.1"), torch.__version__
assert torch.version.cuda and torch.version.cuda.startswith("13"), torch.version.cuda
assert transformers.__version__ == "5.15.1", transformers.__version__
assert version("opencv-python-headless") == "4.12.0.88", version("opencv-python-headless")
assert cv2.__version__ == "4.12.0", cv2.__version__
print("SAM2 运行时", torch.__version__, "CUDA", torch.version.cuda, "cv2", cv2.__version__)
PY
}

model_ready() {
  local dir="$1"
  [[ -d "$dir" ]] || return 1
  (
    cd "$dir"
    sha256sum --status --check "$checksums"
  )
}

"$root/deploy/check-env.sh"

[[ -x "$root/bin/woundtruth-web" ]] || fail "缺少可执行文件 bin/woundtruth-web。放到 bin/ 并加上执行权限后再运行"
[[ -x "$root/bin/sam2-worker" ]] || fail "缺少可执行文件 bin/sam2-worker。放到 bin/ 并加上执行权限后再运行"
[[ -f "$root/web/dist/index.html" ]] || fail "缺少 web/dist/index.html"

if ! systemctl is-active --quiet ollama.service; then
  sudo -n systemctl start ollama.service || fail "Ollama 没有运行，而且当前用户不能免密 sudo。先启动 ollama.service，再重新执行"
  started_ollama=1
fi

ready=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null; then
    ready=1
    break
  fi
  sleep 1
done
[[ "$ready" -eq 1 ]] || fail "Ollama 已启动，但 30 秒内 11434 没有响应"

mkdir -p "$root/runtime" "$root/data"

if [[ -x "$py" ]]; then
  verify_sam2_runtime || fail "已有 runtime/sam2-venv 与锁定版本不一致，或不能 import cv2。删掉该目录后重新执行，脚本不会覆盖它"
else
  python3.12 -m venv "$venv"
  "$py" -m pip install --upgrade pip
  grep -E '^(torch|torchvision)==' "$req" > "$root/runtime/torch-requirements.txt"
  grep -E '^transformers==' "$req" > "$root/runtime/transformers-requirements.txt"
  grep -E '^opencv-python-headless==' "$req" > "$root/runtime/opencv-requirements.txt"
  "$py" -m pip install --index-url "$torch_index" --requirement "$root/runtime/torch-requirements.txt"
  "$py" -m pip install --requirement "$root/runtime/transformers-requirements.txt"
  "$py" -m pip install --requirement "$root/runtime/opencv-requirements.txt"
  verify_sam2_runtime
fi

if ! model_ready "$model"; then
  mkdir -p "$root/runtime/models"
  model_partial="$(mktemp -d "$root/runtime/models/.sam2-partial.XXXXXX")"
  "$py" - "$model_partial" <<'PY'
import sys
from huggingface_hub import snapshot_download
snapshot_download(repo_id="facebook/sam2.1-hiera-tiny", local_dir=sys.argv[1])
PY
  if ! model_ready "$model_partial"; then
    rm -rf "$model_partial"
    fail "SAM2 权重与 deploy/sam2-model.sha256 不一致，已删除不完整下载"
  fi
  rm -rf "$model"
  mv "$model_partial" "$model"
  model_partial=""
fi
model_ready "$model" || fail "SAM2 权重校验没有通过"

if ! ollama list | awk 'NR>1 {print $1}' | grep -qx 'qwen3.6:35b'; then
  ollama pull qwen3.6:35b
fi
curl -fsS --max-time 10 http://127.0.0.1:11434/api/tags | grep -q '"qwen3.6:35b"' || fail "Ollama 里仍然没有 qwen3.6:35b"

if ! port_8000="$(port_verdict 8000)"; then
  fail "下载结束后无法查询 8000。查询失败不等于端口空闲"
fi
case "$port_8000" in
  free|owned) ;;
  *) fail "下载结束后 8000 有无法确认归属的监听，或被其他进程占用（${port_8000}）。本脚本不结束别人的进程" ;;
esac

unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$unit_dir"
sed "s#@ROOT@#${root}#g" "$root/deploy/woundtruth.service" > "$unit_dir/woundtruth.service"
systemctl --user daemon-reload
systemctl --user enable woundtruth.service
previous_pid="$(unit_main_pid)"
systemctl --user restart woundtruth.service
current_pid="$(unit_main_pid)"
if [[ -z "$current_pid" || "$current_pid" == "0" || "$current_pid" == "$previous_pid" ]]; then
  fail "restart 没有产生新的 MainPID。这次没有把它记为本次实例，也不会按服务名停止现有服务"
fi
started_pid="$current_pid"

service_ready() {
  local health_body sam2_body
  health_body="$(curl -fsS --max-time 3 http://127.0.0.1:8000/api/health 2>/dev/null || true)"
  sam2_body="$(curl -fsS --max-time 3 http://127.0.0.1:8000/api/sam2/status 2>/dev/null || true)"
  printf '%s' "$health_body" | python3.12 -c 'import json,sys; data=json.load(sys.stdin); raise SystemExit(0 if data.get("status")=="ok" else 1)' || return 1
  printf '%s' "$sam2_body" | python3.12 -c 'import json,sys; data=json.load(sys.stdin); raise SystemExit(0 if data.get("status")=="ready" and data.get("configured") is True and data.get("resident") is True else 1)' || return 1
}

deadline=$((SECONDS + 180))
until service_ready
do
  if (( SECONDS > deadline )); then
    systemctl --user --no-pager --full status woundtruth.service || true
    journalctl --user -u woundtruth.service -n 40 --no-pager || true
    curl -fsS --max-time 3 http://127.0.0.1:8000/api/health || true
    printf '\n' || true
    curl -fsS --max-time 3 http://127.0.0.1:8000/api/sam2/status || true
    printf '\n' || true
    fail "网页或 SAM2 在 180 秒内没有就绪。需要 /api/health 的 status 为 ok，且 /api/sam2/status 的 status 为 ready、configured 与 resident 都为 true"
  fi
  sleep 2
done

if ! port_8000="$(port_verdict 8000)"; then
  fail "健康检查之后无法查询 8000。查询失败不等于端口空闲"
fi
if [[ "$port_8000" != "owned" ]]; then
  fail "健康检查已返回，但 8000 的监听记录没有全部属于本次服务（${port_8000}）"
fi
if [[ "$(unit_main_pid)" != "$started_pid" ]]; then
  fail "健康检查已返回，但当前 MainPID 已不是本次启动的 ${started_pid}"
fi

printf '已拉起 http://127.0.0.1:8000\n'
