# 可执行文件

`woundtruth-web` 启动旁边的 `woundtruth-web.dist`。那是独立的网页程序，不依赖网页虚拟环境。

`sam2-worker` 是单个 Linux aarch64 可执行文件。临床代码已经编进去。它使用系统 Python 3.12 的标准库，PyTorch 从 `WOUNDTRUTH_SAM2_PYTHON` 指向的虚拟环境加载。

没有这两个入口时，`deploy/up.sh` 会在下载模型之前退出。
