#!/usr/bin/env bash
# 只停止网页。不停止 Ollama，不删除 runtime/ 和 data/。
set -euo pipefail

if systemctl --user is-active --quiet woundtruth.service 2>/dev/null \
  || systemctl --user is-enabled --quiet woundtruth.service 2>/dev/null
then
  systemctl --user disable --now woundtruth.service
fi

printf '网页已停止。Ollama 仍保持原状。\n'
