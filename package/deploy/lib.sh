# 部署脚本共用的端口和私钥判断。由 check-env.sh 与 up.sh 引用。

unit_main_pid() {
  systemctl --user show -p MainPID --value woundtruth.service 2>/dev/null || true
}

listener_belongs_to_unit() {
  local pid="$1"
  [[ -r "/proc/${pid}/cgroup" ]] || return 1
  grep -q 'woundtruth.service' "/proc/${pid}/cgroup"
}

# 逐条判断监听记录。同一行里的每个 PID 都要属于该服务，不能只看最后一个。
# 调用方从标准输入传入 ss -ltnpH 的原始行。标准输出只写一个结论：
# free、owned、foreign、unattributed。
classify_port_lines() {
  local port="$1"
  local main="$2"
  local line addr pid pids lines=0 saw_main=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -n "$line" ]] || continue
    addr="$(awk '{print $4}' <<<"$line")"
    addr="${addr#\[}"
    [[ "$addr" =~ :${port}$ ]] || continue
    lines=$((lines + 1))
    if [[ "$line" != *pid=* ]]; then
      printf 'unattributed\n'
      return 0
    fi
    pids="$(grep -oE 'pid=[0-9]+' <<<"$line" || true)"
    if [[ -z "$pids" ]]; then
      printf 'unattributed\n'
      return 0
    fi
    while IFS= read -r pid; do
      pid="${pid#pid=}"
      [[ -n "$pid" ]] || continue
      if ! listener_belongs_to_unit "$pid"; then
        printf 'foreign\n'
        return 0
      fi
      if [[ -n "$main" && "$main" != "0" && "$pid" == "$main" ]]; then
        saw_main=1
      fi
    done <<<"$pids"
  done
  if [[ "$lines" -eq 0 ]]; then
    printf 'free\n'
    return 0
  fi
  if [[ "$saw_main" -eq 1 ]]; then
    printf 'owned\n'
    return 0
  fi
  printf 'foreign\n'
}

# 服务名固定，所以锁放在用户目录，不放在某个仓库的 runtime/。
deploy_lock_path() {
  local dir
  if [[ -n "${XDG_RUNTIME_DIR:-}" ]]; then
    dir="$XDG_RUNTIME_DIR"
  else
    dir="${HOME}/.local/share/woundtruth"
  fi
  printf '%s\n' "$dir/woundtruth-deploy.lock"
}

# 成功时向标准输出写 free、owned、foreign 或 unattributed。
# ss 失败时返回非零，且不把失败写成 free。
port_verdict() {
  local port="$1"
  local errfile output status main
  errfile="$(mktemp)"
  output="$(ss -ltnpH 2>"$errfile")" && status=0 || status=$?
  if [[ "$status" -ne 0 ]]; then
    printf 'ss 查询 %s 失败，退出码 %s\n' "$port" "$status" >&2
    if [[ -s "$errfile" ]]; then
      cat "$errfile" >&2
    fi
    rm -f "$errfile"
    return 1
  fi
  rm -f "$errfile"
  main="$(unit_main_pid)"
  printf '%s\n' "$output" | classify_port_lines "$port" "$main"
}

# 证书包可以存在。私钥正文不看扩展名；文件读不到则拒绝，不能当成通过。
# runtime/、data/ 和 .git 是本地运行或版本库元数据，不在待发布文件里。
reject_private_keys() {
  local root="$1"
  local file status list
  if find "$root" -name '.device-p256-signing-key.pem' -print -quit | grep -q .; then
    printf '%s\n' "发现签名私钥文件名 .device-p256-signing-key.pem"
    return 1
  fi
  list="$(mktemp)"
  if ! find "$root" \
    \( -path "$root/runtime" -o -path "$root/runtime/*" \
       -o -path "$root/data" -o -path "$root/data/*" \
       -o -path "$root/.git" -o -path "$root/.git/*" \) -prune \
    -o -type f -print0 >"$list"
  then
    printf '%s\n' "无法遍历 $root"
    rm -f "$list"
    return 1
  fi
  while IFS= read -r -d '' file; do
    if [[ ! -r "$file" ]]; then
      printf '%s\n' "无法读取 $file"
      rm -f "$list"
      return 1
    fi
    grep -a -q -E 'BEGIN (RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY' "$file" && status=0 || status=$?
    if [[ "$status" -eq 0 ]]; then
      printf '%s\n' "$file"
      rm -f "$list"
      return 1
    fi
    if [[ "$status" -ne 1 ]]; then
      printf '%s\n' "读取 $file 失败，grep 退出码 $status"
      rm -f "$list"
      return 1
    fi
  done <"$list"
  rm -f "$list"
  return 0
}
