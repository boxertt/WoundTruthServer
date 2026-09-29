# 创视迹 WoundTruth

创视迹是一套创面记录工作台，在 NVIDIA GB10 上运行本地模型，帮助医生查阅已经保存的创面记录。测量、备注、完整性和当前范围都先由本机后端准备好，模型只在这个范围内生成待审阅的回答。临床写入要经过医生确认。这个仓库同时包含说明文档和可部署工程。

## 说明

| 文档 | 内容 |
|---|---|
| [项目说明](docs/02_项目说明.md) | 作品在做什么，技能包各自的边界 |
| [部署、模型与技能](docs/03_部署与模型优化说明.md) | 本地如何部署、模型如何组织、技能如何设计；第 5 节是有无技能对照 |
| [技术栈](docs/04_技术栈说明.md) | 设备分工、本地模型和当前没有接入主链路的部分 |
| [Agent 与 Skills 设计](docs/08_Agent与Skills设计说明.md) | 五个技能的输入、输出和写入分离 |
| [技术图](docs/diagrams/README.md) | 架构、测量流程、SAM2 确认、助手时序和数据流 |

## 工程

可运行的部署包在 [`package/`](package/README.md)，包含部署脚本、已构建网页、Linux aarch64 可执行文件，以及 Agent 编排和技能源码。

在 GB10 上，于 `package/` 目录执行：

```bash
./deploy/up.sh
```

脚本先检查机器，再确认 `bin/` 里的两个程序已经放好，然后启动本机 Ollama，按锁定版本准备 SAM2 环境，并拉取 `facebook/sam2.1-hiera-tiny` 与 `qwen3.6:35b`。网页前后端是同一个进程，端口 8000。健康检查通过后才打印地址。SAM2 权重和本地大模型不在仓库里，部署时再拉取。病历数据由部署方自己准备，不进这个仓库。

停掉网页：

```bash
./deploy/down.sh
```

更细的步骤、环境变量和发布边界见 [package/README.md](package/README.md)、[部署](package/docs/部署.md) 和 [发布边界](package/docs/发布边界.md)。

## 技能

五个 `SKILL.md` 放在仓库根的 `skills/` 里，是可以直接打开的技能文件。内容与 `package/agent` 里的同一份技能一致。

| 技能 | 作用 |
|---|---|
| [woundtruth-integrity-verify](skills/woundtruth-integrity-verify/SKILL.md) | 说明采集包是否完整、来源是否能对上。不把签名解释成医学内容正确 |
| [woundtruth-measurement-review](skills/woundtruth-measurement-review/SKILL.md) | 整理已经保存的长度、面积和剖面。不从像素推算厘米 |
| [woundtruth-note-draft](skills/woundtruth-note-draft/SKILL.md) | 整理已保存备注，供医生审阅。不自行签署或写入 |
| [woundtruth-record-review](skills/woundtruth-record-review/SKILL.md) | 按顺序读完四类证据后做记录总览。不跨患者扩大范围 |
| [woundtruth-sam2-measurement-preview](skills/woundtruth-sam2-measurement-preview/SKILL.md) | 审阅分割候选。不代替医生确认 |

生产问答先执行固定的证据计划，再调用一次本地模型。这五个文件是可以阅读的技能说明；生产路径不动态加载它们的 manifest。

## 有无技能对照

对照用合成夹具，两组共用同一份证据、同一个本地模型和同一组参数，差别只有系统提示末尾是否附上该任务绑定的技能正文。测量技能写进量纲规则之后，7B 这条历史记录不再把已保存的长度写成面积；不追加技能正文的一组仍会出现这种错误。协议、十个任务和合成表在[部署说明第 5 节](docs/03_部署与模型优化说明.md)。

## 技术栈

本机推理使用 Ollama 的 OpenAI 兼容接口，代码里的对话模型是 `qwen3.6:35b`。SAM2 候选使用单独的 Python 环境，模型是 `sam2.1-hiera-tiny`。NVIDIA SDK 和 StepFun 阶跃星辰模型没有进入这条临床主链路。细节见[技术栈说明](docs/04_技术栈说明.md)。

## 仓库里没有的东西

- 病历、录像和调试 JSON
- 签名私钥、`runtime/` 和虚拟环境
- SAM2 权重与本地大模型
- iOS 采集工程
- 模型权重超过 GitHub 单文件限制，因此不打包进仓库

`package/bin/woundtruth-web.dist/woundtruth-web` 约 65 MB。GitHub 对超过 50 MB 的文件会给出警告，这个文件低于 100 MB 的拒绝线。

## 许可

本仓库以 [Apache-2.0](LICENSE) 授权。五个技能说明里的 `license` 字段与此相同。Mozilla 的 CA 证书包不在这份许可之内，见 [NOTICE](NOTICE)。
