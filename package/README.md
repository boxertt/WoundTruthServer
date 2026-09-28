# WoundTruth 部署包

这是创面记录工作台的部署仓库。临床算法以可执行文件分发，网页以构建结果分发，SAM2 权重和本地大模型在目标机器上单独拉取。Agent 编排和技能说明以源码放在 [`agent/`](agent/README.md)，可以直接阅读。

目标机器是 NVIDIA GB10 这一档：Ubuntu 24.04、aarch64、统一内存大约 120 GB。笔记本和 x86 服务器不在这次部署范围内。

## 一条命令

在仓库根目录执行：

```bash
./deploy/up.sh
```

脚本按固定顺序工作，任何一步失败都会停，不会继续往下装：

1. 检查机器，不安装系统包，不访问外网。
2. 确认 `bin/woundtruth-web` 和 `bin/sam2-worker` 已经放好。
3. 启动本机 Ollama。
4. 按锁定版本重建 SAM2 运行环境，并拉取 `facebook/sam2.1-hiera-tiny` 和 `qwen3.6:35b`。
5. 启动网页。前后端是同一个进程，端口 8000。
6. `/api/health` 和 `/api/sam2/status` 都通了，才打印地址。

停掉网页：

```bash
./deploy/down.sh
```

这只停止网页，不停止 Ollama。

## 目录

```text
agent/                    Agent 编排和技能源码
docs/发布边界.md          哪些进仓库，以什么形态
docs/部署.md              检查项、环境变量、失败时停在哪里
deploy/check-env.sh       只检查
deploy/up.sh              检查通过后拉起
deploy/down.sh            停止网页
deploy/sam2-requirements.txt
deploy/woundtruth.service
compile/sync-release.sh   发布分支有改动时重新编译并同步
bin/                      临床可执行文件放这里
web/dist/                 已构建的网页，没有 source map
```

部署时在本机生成、不进 git 的目录：

```text
runtime/sam2-venv/        按清单重建的 PyTorch 环境
runtime/models/           SAM2 权重
data/                     病历数据，由部署方自己准备
```

## 发布分支有改动时重新编译

在这台开发机上执行：

```bash
./compile/sync-release.sh
```

它对比 GB10 上发布分支 `codex/web-geometry-audit-20260913` 的提交和工作区改动。没有变化就停。有变化就在 GB10 上编译，再把结果同步回 `bin/` 和 `web/dist/`。现网网页进程不会被重启。

`bin/woundtruth-web` 会启动旁边的 `woundtruth-web.dist`。`bin/sam2-worker` 本身就是编译好的程序。没有这两个入口时，`up.sh` 会在下载模型之前退出。

更细的边界和步骤见 [发布边界](docs/发布边界.md) 和 [部署](docs/部署.md)。
