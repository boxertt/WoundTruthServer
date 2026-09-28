#!/usr/bin/env bash
# 只检查机器。不安装软件，不访问外网，不启动进程。
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck disable=SC1091
source "$root/deploy/lib.sh"

fail() {
  printf '不通过: %s\n' "$*" >&2
  exit 1
}

ok() {
  printf '通过: %s\n' "$*"
}

[[ "$(uname -s)" == "Linux" ]] || fail "需要 Linux，当前是 $(uname -s)"
[[ "$(uname -m)" == "aarch64" ]] || fail "需要 aarch64（NVIDIA GB10），当前是 $(uname -m)"

[[ -r /etc/os-release ]] || fail "读不到 /etc/os-release"
# shellcheck disable=SC1091
source /etc/os-release
[[ "${ID:-}" == "ubuntu" && "${VERSION_ID:-}" == "24.04" ]] || fail "需要 Ubuntu 24.04，当前是 ${PRETTY_NAME:-未知}"
ok "Ubuntu 24.04 aarch64"

command -v python3.12 >/dev/null 2>&1 || fail "没有 python3.12。目标机应自带，本脚本不安装"
python3.12 -c "import venv, ensurepip" >/dev/null 2>&1 || fail "python3.12 不能创建虚拟环境。需要系统里已有 python3.12-venv，本脚本不安装"
ok "Python $(python3.12 -V 2>&1 | awk '{print $2}')"

command -v nvidia-smi >/dev/null 2>&1 || fail "没有 nvidia-smi"
gpu="$(nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader | head -1 || true)"
[[ -n "$gpu" ]] || fail "nvidia-smi 没有看到 GPU"
cap="${gpu##*, }"
cap="${cap// /}"
python3.12 - "$cap" <<'PY' || fail "GPU 计算能力 ${cap} 低于 12.0。当前能跑的是 GB10（12.1）"
import sys
raise SystemExit(0 if float(sys.argv[1]) >= 12.0 else 1)
PY
ok "GPU ${gpu}"

command -v ollama >/dev/null 2>&1 || fail "没有 ollama。本地模型运行时需要事先装好，本脚本不安装"
ok "已安装 ollama"

mem_total="$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
mem_avail="$(awk '/^MemAvailable:/ {print $2}' /proc/meminfo)"
[[ "$mem_total" -ge $((64 * 1024 * 1024)) ]] || fail "内存总量不足 64 GiB"
[[ "$mem_avail" -ge $((48 * 1024 * 1024)) ]] || fail "可用内存不足 48 GiB，当前约 $((mem_avail / 1024 / 1024)) GiB"
ok "内存总量 $((mem_total / 1024 / 1024)) GiB，可用 $((mem_avail / 1024 / 1024)) GiB"

disk_avail="$(df -Pk "$root" | awk 'NR==2 {print $4}')"
[[ "$disk_avail" -ge $((80 * 1024 * 1024)) ]] || fail "磁盘可用不足 80 GiB，当前约 $((disk_avail / 1024 / 1024)) GiB"
ok "磁盘可用 $((disk_avail / 1024 / 1024)) GiB"

command -v ss >/dev/null 2>&1 || fail "没有 ss"
command -v curl >/dev/null 2>&1 || fail "没有 curl"
command -v sha256sum >/dev/null 2>&1 || fail "没有 sha256sum"
command -v flock >/dev/null 2>&1 || fail "没有 flock"

if ! port_8000="$(port_verdict 8000)"; then
  fail "无法查询 8000。查询失败不等于端口空闲"
fi
case "$port_8000" in
  free)
    ok "8000 空闲"
    ;;
  owned)
    ok "8000 的全部监听记录都属于 woundtruth"
    ;;
  *)
    fail "8000 有无法确认归属的监听，或被其他进程占用（${port_8000}）。本脚本不结束别人的进程"
    ;;
esac

if ! port_11434="$(port_verdict 11434)"; then
  fail "无法查询 11434。查询失败不等于端口空闲"
fi
case "$port_11434" in
  free)
    ok "11434 空闲，部署时会启动 Ollama"
    ;;
  *)
    if curl -fsS --max-time 3 http://127.0.0.1:11434/api/tags >/dev/null; then
      ok "11434 是本机 Ollama"
    else
      fail "11434 已被占用，但不是 Ollama"
    fi
    ;;
esac

if [[ -d "$root/data/records" ]] && find "$root/data/records" -mindepth 1 -print -quit | grep -q .; then
  fail "data/records 里已有内容。不要把病历放进这个仓库"
fi
if ! private_key_error="$(reject_private_keys "$root")"; then
  fail "私钥检查没有通过：${private_key_error}。公开 CA 证书可以保留；读不到的文件不能当成通过"
fi
ok "没有病历目录，也没有私钥文件"

printf '环境检查通过\n'
