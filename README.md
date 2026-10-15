# 基于几何约束的多视图二维设计向复杂三维模型表面的高保真纹理转译技术

> **OrthoTex（Geometry-Guided Texture Transfer）** ｜ 问题定义与方案设计 ｜ 版本 v2.0

作者：**AvroraCL**　｜　在线阅读：<https://avroracl.github.io/geo-guided-texture-transfer/>

---

> **This research is open to both human and AI contributions.**
> We welcome new ideas, reproducible experiments, critical reviews, and even evidence that challenges our current assumptions.
>
> 本研究同时欢迎人类与 AI 的贡献。我们欢迎新思路、可复现实验、批判性审查，以及任何能够挑战现有假设的证据。

**研究的目的不是证明作者正确，而是让问题逐渐得到解决。**

---

## 这是什么的

游戏外观模改（skin／涂装）生产中有一个工程断层：把多视图二维设计稿转译成复杂三维模型表面可用的 PBR 贴图，至今仍高度依赖人工。

图像生成模型与大语言模型已能覆盖首尾两端——出设计参考、转译需求——但补不上中间那一环：参考图上"长这样"的图案，究竟对应模型表面哪一位置，跨过 UV 接缝之后又该如何接续。

本文做的四件事：把该断层界定为可研究的问题；给出六条硬约束；梳理由此决定的设计空间；给出可执行的落地分工与尚未执行的验证方案。

**本文不提出新的生成模型，也不声称已有实现。** 面向熟悉 PBR 流程、不熟悉图形算法与人工智能的美术从业者写作。

## 怎么读

**在线阅读：<https://avroracl.github.io/geo-guided-texture-transfer/>**

页面顶部提供「使用 AI 阅读与研究」入口，含三种模式的一键复制提示词：

| 模式 | 用途 |
| --- | --- |
| 理解研究 | 按你的专业背景解释本文，区分文献结论、作者经验与未验证假设 |
| 批判性审查 | 要求 AI 独立审查，不默认作者正确 |
| 参与研究 | 让具备检索、推导或编程能力的 AI 主动参与研究 |

每个章节标题旁另有「复制本节」按钮，可把该节以 Markdown 复制，便于交给 AI。

## 文档结构

| 路径 | 内容 |
| --- | --- |
| [`paper/index.html`](paper/index.html) | **研究正文（唯一内容源）**，网页版 |
| [`paper/full.md`](paper/full.md) | 同一正文的 Markdown 派生版，供 AI 与检索使用 |
| [`paper/figures/`](paper/figures) | 从正文提取的插图（SVG） |
| [`paper/context.md`](paper/context.md) | 背景、目标、约束、术语、当前进度 |
| [`research/open-questions.md`](research/open-questions.md) | 六个公开研究问题，各含背景、已有研究、当前假设与可参与任务 |
| [`research/hypotheses.md`](research/hypotheses.md) | 全部假设与证据状态，逐条给出否证条件 |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 参与方式、五类贡献、评审标准、AI 参与规则 |
| [`tools/build-md.py`](tools/build-md.py) | 由 HTML 派生 Markdown 与插图的构建脚本 |

**`paper/index.html` 是唯一内容源**，`full.md` 与 `figures/` 由脚本派生，请勿直接编辑：

```bash
python tools/build-md.py
```

## 参与研究

五类贡献：**文献**、**理论**、**算法**、**实验**、**实践**。

AI 可以参与，也可以主导分析，但须披露参与方式；贡献的评价依据是证据质量、技术正确性、可复现性与研究价值，**与是否使用 AI 无关**。提交 Issue 或 Pull Request 前需获得人类用户明确授权。

**发现错误、证明某条路线不可行、复现失败实验，与提出新算法同等有价值。**

详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 状态

**方案设计阶段。未实现、未验证。**

正文没有实验数据；第 5 章为验证方案设计。全文使用三种标记：`[假设]`（由实践推断，尚未验证）、`[待补]`（缺数据或引用）、`[已核对]`（已查证出处）。凡标 `[假设]` 之处，不得在后续版本中直接改写为结论。

十张插图均为概念示意图，**不具备证据价值**；需要真实素材占据的位置列在附录 B。

## 撰写方式

本文由作者与人工智能助手（AI Agent）协作完成：

- **AI 助手承担**：章节结构梳理、文献检索与出处核实、文字整理、全部插图绘制、HTML 排版与发布、构建脚本编写
- **作者承担**：问题的提出与实践判断（1.1 节流程、1.3 节六条硬约束）、技术路线选择、全部内容的审阅与确认
- **AI 助手未参与**：未产生任何实验数据，未验证任何技术假设，未提供任何真实素材

文献出处均经外部数据库（Crossref、arXiv）核对，但**对具体做法的描述未逐篇通读全文**，详见第 2 章开头的说明。

## 许可

本文的文字与图表采用 **CC BY 4.0**（知识共享署名 4.0 国际）许可：可自由阅读、转载、改编、商用，须署名 **AvroraCL**。完整条款见 [LICENSE](LICENSE)。

外部贡献遵循相同的署名与许可要求。

## 注意

本仓库**不包含**所引用的参考论文 PDF——它们受出版方版权保护，请通过正规渠道获取：

| 文献 | 出处 |
| --- | --- |
| UniTex | Computers & Graphics 137 (2026) 104599 |
| Im2SurfTex | Computer Graphics Forum 2025，arXiv:2502.14006 |
| Robust Curve Embedding | Computer Aided Geometric Design 2026，DOI 10.1016/j.cagd.2026.102588 |
| DirectUV | arXiv:2609.34651 |

完整参考文献（20 篇）见正文末尾。
