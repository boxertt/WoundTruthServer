# 从发布分支编译

在开发机上，于仓库根目录执行：

```bash
./compile/sync-release.sh
```

脚本读取 GB10 上 `/home/john/WoundTruth` 的分支 `codex/web-geometry-audit-20260913`。`code/backend` 或 `code/frontend` 有未提交改动时直接停止，只从干净提交编译。提交和工作区相对上次同步没有变化时，直接退出。有变化时，源码先复制到 `/tmp/woundtruth-src` 再编译，产物写到 `/home/john/WoundTruth-build`，然后拉回 `bin/` 和 `web/dist/`。

工人只编入它实际导入的模块，不再把整个 `app` 包打进去。编译时用系统 `/usr/bin/python3.12` 调用 Nuitka，避免把构建机虚拟环境路径写进 `sys.prefix`。编译副本会去掉跨域配置里的内网地址。编译结束时若二进制仍含构建机家目录或该内网地址，脚本失败，不会当作成功结果拉回。`strings` 或 `grep` 本身失败同样停止，不会把扫描失败当成没有命中。

强制重编：

```bash
./compile/sync-release.sh --force
```

登录 GitHub CLI 之后，把当前提交推到私有仓库：

```bash
./compile/publish-github.sh
```

编译不修改发布仓库里的源码，也不重启现网网页。部署布局需要的环境变量补丁只打在编译副本上。

网页程序是独立目录 `bin/woundtruth-web.dist`。SAM2 工人是单个文件 `bin/sam2-worker`：临床代码在二进制里，标准库用目标机的 Python 3.12，PyTorch 从 `WOUNDTRUTH_SAM2_PYTHON` 指向的虚拟环境加载。
