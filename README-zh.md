<div align="center">

# Trace File Lineage

**查清文件从哪来，也让 AI Agent 知道新产出应该放在哪里。**

完全本地运行，不上传文件；每个结论都附带证据和可信度，不把猜测冒充事实。

[📖 使用文档](docs/skill.md) · [⌨️ 命令参考](docs/cli.md) · [⚖️ 与 Git / DVC 的区别](docs/comparison.md) · [📊 真实项目测试](docs/real-world-validation.md)

[![CI](https://github.com/uczltw6/trace-file-lineage/actions/workflows/ci.yml/badge.svg)](https://github.com/uczltw6/trace-file-lineage/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/trace-file-lineage)](https://pypi.org/project/trace-file-lineage/)
[![Python](https://img.shields.io/badge/python-3.11%20%E2%80%93%203.14-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

[English](README.md) · [简体中文](README-zh.md)

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/demo-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/demo-light.svg">
  <img alt="Trace File Lineage 演示：一个已验证的来源和一个候选来源" src="docs/assets/demo-dark.svg" width="720">
</picture>

</div>

## 这个工具是做什么的？

假设你在项目里看到一张 `figures/final_panel.png`，却已经不记得：

- 它是哪个脚本或 Notebook 生成的？
- 它用了哪份原始数据？
- 修改数据后，哪些图表和报告需要重新生成？
- 它是你自己做的，还是某次 AI Agent 任务留下的？

Trace File Lineage 会读取项目里的代码、文档、文件元数据和 Git 历史，整理出文件之间的来源关系，并把最可能的答案和依据一起展示出来。它还可以把文件管理规则写进 `AGENTS.md` 和 `CLAUDE.md`，让 AI Agent 按项目已有的目录习惯放置新产出，并在任务结束后留下结构化的改动记录。

你可以把它理解为**项目文件的“来源侦探”**：Git 记录“文件什么时候变了”，它尝试回答“文件是怎么来的”。它尤其适合 Python、Jupyter Notebook、数据分析、科研代码，以及 AI Agent 一次生成大量文件的项目。

> 它分析文件，但不会执行你的项目代码，也不会移动、重命名或删除任何文件。

它实际解决三类问题：

| 你遇到的问题 | 它提供的能力 |
|---|---|
| “这个旧文件到底从哪来的？” | 扫描现有项目，给出最可能的脚本、Notebook、数据或运行记录，并展示证据 |
| “Agent 生成的文件应该放哪？” | 识别项目已有目录惯例，要求 Agent 复用合理的目录和稳定的文件名 |
| “这次任务到底产出了什么？” | 记录新增、修改、重命名和删除的文件，生成任务清单、项目结构视图和关系图 |

## 先用 1 分钟试一下

需要 Python 3.11 或更高版本：

```bash
pip install trace-file-lineage
lineage demo
```

`lineage demo` 会在 `./lineage-demo` 中创建一个小项目，运行一次脚本，然后追查生成的图表。整个过程不需要配置，也不会改动当前项目中的其他文件。

演示中的问题类似这样：

```text
figures/trend.svg 是从哪里来的？

已验证的来源
  @run/run:...
  证据：这条命令运行期间，目标文件确实发生了变化

可能的来源
  analysis/plot.py:16
  依据：这行代码会写入目标路径，但当时没有记录实际运行过程
```

这里最重要的区别是：

- **记录过运行过程**，工具可以给出已验证的证据。
- **只有现成文件**，工具会根据留下的痕迹给出候选答案，并明确说明这只是推测。

## 让 Agent 把产出放对地方

`lineage enable` 不只是开启文件来源记录。它会在项目的 `AGENTS.md` 和 `CLAUDE.md` 中写入一段受管理的规则，要求 Agent 在创建文件前先观察项目现有结构：

```bash
lineage enable
lineage layout
```

`lineage layout` 会告诉 Agent：

- `.py`、`.csv`、图片、报告等文件通常分别放在哪些目录；
- 应该复用哪些已有目录，而不是随手创建 `output_final_v2/`、`results_new/` 或日期目录；
- 哪些文件名过长、目录嵌套过深或使用了 `final`、`copy`、`v2` 等容易失控的命名；
- 一个目录是否过于拥挤，或者是否出现了只装一个文件的零散目录。

任务结束后，Agent 会记录本次新增、修改、重命名和删除的文件。你可以从三个角度查看结果：

```bash
lineage receipt                         # 本次任务改动了哪些文件
lineage views --view agent-run          # 某次 Agent 任务的全部产出
lineage views --view project-map        # 按目录分组的项目文件结构
```

`project-map` 可以输出 Markdown、JSON 或 Mermaid。得到的结构会类似这样：

```text
project/
├── data/       原始数据和中间数据
├── analysis/   脚本和 Notebook
├── figures/    生成的图表
└── reports/    最终报告
```

这里需要说准确：**工具不会擅自移动文件。** `lineage layout` 是只读分析；真正的文件放置由 Agent 按写入项目的规则执行，最终决定仍然属于你。

## 最常用的几个命令

### 1. 追查一个现有文件

```bash
lineage explain figures/final_panel.png
```

它会自动扫描项目，然后列出最可能的生成脚本和判断依据。即使之前没有安装过 Trace File Lineage，也可以这样追查旧文件。

### 2. 记录一次新的运行

```bash
lineage run --task "生成月度报告" -- python scripts/build_report.py
```

这条命令会正常执行你的脚本，同时记录运行前后的文件变化。以后再查询这些产物时，可以得到 `verified`（已验证）结论，而不只是猜测。

脚本原本的输出和退出码会保持不变。运行结束后，可以查看完整记录：

```bash
lineage receipt
```

如果项目主要由 AI Agent 持续维护，还可以运行 `lineage enable`，让 Agent 在每次任务结束时记录文件变化。`lineage status` 用于查看状态，`lineage disable` 只删除工具自己添加的配置区块。详见 [安装与持续记录说明](docs/install.md)。

### 3. 查看修改一个文件会影响什么

```bash
lineage impact data/raw.csv
lineage stale data/raw.csv
```

`impact` 查看下游可能受影响的文件；`stale` 检查哪些产物可能已经过期。

### 4. 打开交互式关系图

```bash
lineage open
```

它会生成一个可拖动、缩放和点击的本地关系图。实线表示已验证的关系，虚线表示推测。页面是单个离线 HTML 文件，不需要服务器，也不会发送网络请求。

### 其他实用命令

| 你想做什么 | 命令 |
|---|---|
| 查看有哪些分析视图可用 | `lineage views --list` |
| 查看一个文件的候选来源 | `lineage why FILE` |
| 查找两个文件之间的关系路径 | `lineage path SOURCE TARGET` |
| 找出没有明确来源的文件 | `lineage orphans` |
| 检查项目目录结构是否混乱 | `lineage layout` |
| 检查本机支持哪些文件格式 | `lineage doctor` |

完整命令和参数见 [docs/cli.md](docs/cli.md)。

## 实际包含哪些能力？

| 能力 | 相关命令或视图 | 用途 |
|---|---|---|
| 追查文件来源 | `explain`、`why`、`alternatives`、`source-chain` | 找生成脚本、输入文件、竞争候选和完整来源链 |
| 分析下游影响 | `impact`、`stale`、`path`、`orphans` | 判断修改输入后会影响什么、哪些产物可能过期 |
| 记录脚本或 Agent 任务 | `run`、`snapshot`、`record`、`receipt`、`recover` | 记录一次任务实际改动过的文件，并处理未正常结束的记录 |
| 约束 Agent 的文件放置 | `enable`、`status`、`disable`、`layout` | 让 Agent 遵循项目已有目录惯例，减少随意堆放和重复命名 |
| 查看项目结构 | `project-map`、`agent-run`、`pipeline`、`timeline` | 按目录、任务、流水线或时间查看文件 |
| 查专项关系 | `file-history`、`code-to-image`、`document-export`、`duplicates`、`sweeps` | 查看单个文件历史、代码到图片、文档到 PDF、重复文件和参数扫描 |
| 搜索项目内容 | `find`、`search` | 按文件名、已索引文本或 OCR 文本查找内容 |
| 可视化与导出 | `open`、`export` | 生成离线交互图，或导出 Markdown、JSON、Mermaid、HTML、W3C PROV、Obsidian |
| 导入外部血缘 | `import` | 读取 DVC、OpenLineage、W3C PROV、代码图和 Agent 运行记录 |

其中 DVC、OpenLineage、W3C PROV、代码图和 Obsidian 集成属于实验性功能；核心能力不依赖这些集成。

## 它如何判断“是不是这个文件生成的”？

每个答案都会显示可信度，不会把线索包装成事实：

| 标签 | 含义 |
|---|---|
| `verified` | 记录到了实际运行和文件变化，可以视为证据 |
| `strong-candidate` | 证据很强，但没有直接观察到生成过程 |
| `candidate` | 合理的候选答案，建议人工核对 |
| `weak-signal` | 只有微弱线索，只能作为排查方向 |
| `insufficient` | 证据不足，无法判断 |

证据大致按以下顺序参考：人工确认 → 已记录的运行 → 外部来源记录 → 显式声明 → 静态代码分析 → 内容与结构 → 文件名和时间戳。

如果证据不足，工具会回答 `insufficient`。文件名相似、修改时间接近或某行代码提到了路径，都不会自动变成“已验证”。

## 它擅长分析哪些文件？

### 支持最好

- **Python 和 Jupyter Notebook**：解析 AST，识别常见的 Pandas、NumPy、Matplotlib、PIL 和 `pathlib` 读写方式；
- **Git 历史**：辅助识别文件重命名；
- **常见图片**：读取 PNG、JPEG、TIFF、WebP 的元数据和指纹。

### 可以读取

- Word、PowerPoint、Excel、OpenDocument、EPUB；
- 大约 50 种文本和代码格式，可搜索其中写明的文件路径；
- PDF 文本和内嵌媒体，需要安装可选依赖：

```bash
pip install "trace-file-lineage[pdf]"
```

### 能力有限

- JavaScript / TypeScript 只做保守的静态扫描，不是完整的语言分析；
- 其他语言主要按文本和路径引用进行搜索；
- 运行时动态拼接的路径不一定能识别；
- 它面向本地文件，不适合数据库或数据仓库中的表级血缘分析。

运行 `lineage doctor` 可以查看当前机器的实际支持情况。更完整的说明见 [格式适配器](docs/adapters.md) 和 [已知限制](docs/limitations.md)。

## 隐私与安全

- 所有分析都在本地完成，不需要账号、API Key 或 AI 服务；
- 不上传文件，也不会发起云端分析请求；
- 只读取代码，不执行代码；
- 自动跳过 `.env`、密码和密钥等敏感内容；
- 记录命令时会清除看起来像密码的参数；
- 记录 AI Agent 活动时，只保留摘要和改动文件列表，不保存对话或 Prompt。

扫描后生成的 `.file-lineage/` 中可能含有从项目文件提取的文本，请像保护项目本身一样保护这个目录。它默认不会被提交到 Git。完整威胁模型见 [SECURITY.md](SECURITY.md)。

## 它和 Git、DVC 有什么区别？

| 工具 | 主要回答的问题 |
|---|---|
| Git | 文件在什么版本发生了变化？ |
| DVC | 提前声明的数据流水线中，输入和输出是什么？ |
| OpenLineage | 已接入埋点的任务产生了哪些血缘事件？ |
| Trace File Lineage | 眼前这个本地文件最可能是怎么来的？证据是什么？ |

Trace File Lineage 不是 Git 或 DVC 的替代品，而是补充它们没有覆盖的部分：未提交的中间文件、没有提前声明的脚本运行、旧项目遗留物，以及 AI Agent 批量生成的文件。

如果你的流水线已经被 DVC 或 OpenLineage 完整记录，继续使用它们通常更合适。详细对比和“不适合使用本项目的情况”见 [docs/comparison.md](docs/comparison.md)。

## 性能

项目在 macOS + Python 3.14 上的测试结果如下，可通过 `tests/benchmark.py` 复现：

| 项目规模 | 首次扫描 | 后续扫描 |
|---:|---:|---:|
| 1,000 个文件 | 0.5 秒 | 0.1 秒 |
| 10,000 个文件 | 16.5 秒 | 1.1 秒 |

首次扫描会读取全部受支持的文件；之后只处理发生变化的部分。`node_modules`、虚拟环境、缓存和构建输出默认会被跳过。

## 与 AI 编程助手配合使用

项目可作为 Claude Code 或 Codex 的 Skill 使用。安装后，你可以直接问助手：“这个文件从哪来的？”

```bash
# Claude Code：从源码仓库加载完整插件
claude --plugin-dir .

# Codex：只链接 Skill
mkdir -p "$HOME/.agents/skills"
ln -s "$PWD/skills/trace-file-lineage" \
      "$HOME/.agents/skills/trace-file-lineage"
```

完整安装方式、Hook 配置和 Windows 说明见 [docs/install.md](docs/install.md)。

## 当前状态与已知限制

当前为早期版本 **0.7.0**，命令可能随迭代调整。项目已在 Python 3.11–3.14 与 macOS、Linux、Windows 的组合上测试。

使用前请注意：

- 对没有留下任何痕迹的旧文件，工具可能无法给出答案；
- 回溯分析得到的候选关系可能出错，采取行动前应检查标签和证据；
- Python 和 Notebook 的分析能力明显强于其他语言；
- 索引只属于当前本地工作区，不提供跨机器、团队共享或云端同步。

真实项目测试结果（包括没有证明成功的部分）见 [docs/real-world-validation.md](docs/real-world-validation.md)。

## 参与贡献

欢迎提交 Issue 和 Pull Request，也欢迎第一次参与开源的贡献者。开始前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。安全问题请按 [SECURITY.md](SECURITY.md) 私下报告。

```bash
lineage demo
python -m unittest discover -s tests -p "test_*.py"
```

## 作者

[tianyiwei](https://github.com/uczltw6) 和 [Claudia Chen](https://github.com/ClaudiaChen04)——详见 [AUTHORS.md](AUTHORS.md)。

## 许可证

MIT，详见 [LICENSE](LICENSE)。
