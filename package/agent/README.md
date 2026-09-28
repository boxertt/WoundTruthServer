# Agent 编排与技能

这一层的编排和技能说明与 `bin/SOURCE-REV` 里的提交 `cb8f27b` 是同一套源码。`bin/` 里的程序编译自这一提交。

测量公式、SAM2 工人和签名实现不在这里，它们在 `bin/` 的可执行文件里。

## 编排

`app/agent_runtime.py` 只依赖 Python 标准库。它拿到一份已经冻结的证据 JSON，按固定顺序做四次只读切片，再把切片交给本地模型。切片函数不读病历文件，不算创面尺寸，也不验签名。

| 顺序 | 工具 | 取出的内容 |
|---|---|---|
| 1 | `get_record_overview` | 患者、记录、时间线和代表帧 |
| 2 | `get_measurements` | 已经保存的测量 |
| 3 | `get_notes` | 患者、记录和测量备注 |
| 4 | `get_integrity` | 完整性字段 |

入口是 `dispatch`。工具名必须在上面这张表里，参数必须是空对象，其他调用会被拒绝。

## 技能

`publishable/` 是四个对外技能包，许可证 Apache-2.0，状态都是 `candidate`。`publishable/PLAN.lock` 是允许公开的名字白名单。

| 技能 | 对应的编排工具 |
|---|---|
| `woundtruth-record-review` | 按上表顺序读满四个切片 |
| `woundtruth-measurement-review` | `get_measurements` |
| `woundtruth-note-draft` | `get_notes` |
| `woundtruth-integrity-verify` | `get_integrity` |

`tools/run_publishable_skill.py` 按这份白名单调用同一个 `dispatch`。技能正文里没有第二份切片实现。

`skills/woundtruth-sam2-measurement-preview/` 是 SAM2 预览的工作流说明，许可证同样是 Apache-2.0。它规定先取固定网格的候选蒙版，由医生点选后才能进入确认。分割和几何计算仍在 `bin/sam2-worker`。

## 本地核对

需要 Python 3.11 或更新版本，以及 PyYAML。在 `agent/` 目录执行：

```bash
python3 -m unittest discover -s tests -v
```

合成快照在 `tests/fixtures/skill_snapshot_document.json`，里面没有真实病历。
