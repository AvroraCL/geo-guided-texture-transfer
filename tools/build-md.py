#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OrthoTex 文档构建脚本

单一内容源：paper/index.html（网页版为唯一源，本脚本从它派生 Markdown）
产出：
  - paper/full.md          完整研究正文（Markdown）
  - paper/figures/*.svg    从正文中提取的插图

用法：python tools/build-md.py
重复运行是幂等的。修改研究正文请改 paper/index.html，然后重跑本脚本。
"""

import io
import os
import re
import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "paper", "index.html")
OUT_MD = os.path.join(ROOT, "paper", "full.md")
FIG_DIR = os.path.join(ROOT, "paper", "figures")

VERSION = "v2.0"


def strip_inline(t):
    """行内标签转换"""
    t = re.sub(r'<span class="b[^"]*">(.*?)</span>', r'[\1]', t)
    t = re.sub(r"<strong>(.*?)</strong>", r"**\1**", t, flags=re.S)
    t = re.sub(r"<b>(.*?)</b>", r"**\1**", t, flags=re.S)
    t = re.sub(r"<em>(.*?)</em>", r"*\1*", t, flags=re.S)
    t = re.sub(r"<code>(.*?)</code>", r"`\1`", t, flags=re.S)
    t = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"[\2](\1)", t, flags=re.S)
    t = re.sub(r"<br\s*/?>", " ", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def table_to_md(block):
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", block, flags=re.S)
    out, ncol = [], 0
    for i, r in enumerate(rows):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)
        cells = [strip_inline(c) for c in cells]
        ncol = max(ncol, len(cells))
        out.append("| " + " | ".join(cells) + " |")
        if i == 0:
            out.append("|" + "---|" * len(cells))
    return "\n".join(out) + "\n"


def build():
    html = io.open(SRC, encoding="utf-8").read()

    a = html.find("<article")
    b = html.rfind("</article>")
    body = html[a:b]

    os.makedirs(FIG_DIR, exist_ok=True)
    fig_count = [0]

    # 0) 去掉标题页（页头已有同样信息）与摘要标签
    body = re.sub(r'<header class="tp">.*?</header>', "", body, flags=re.S)
    body = re.sub(r'<p class="lbl">\s*摘\s*要\s*</p>', "\n## 摘要\n", body)
    body = re.sub(
        r'<p class="kw">(.*?)</p>',
        lambda m: "\n**关键词：** " + strip_inline(m.group(1)).replace("**关键词：**", "", 1).strip() + "\n",
        body,
        flags=re.S,
    )

    # 1) figure -> 提取 SVG + 图片引用
    def repl_figure(m):
        blk = m.group(0)
        fig_count[0] += 1
        n = fig_count[0]
        svg_m = re.search(r"<svg.*?</svg>", blk, flags=re.S)
        cap_m = re.search(r"<figcaption>(.*?)</figcaption>", blk, flags=re.S)
        cap = strip_inline(cap_m.group(1)) if cap_m else "图 %d" % n
        if svg_m:
            svg = svg_m.group(0)
            # 让 SVG 自适应宽度
            svg = svg.replace('width="100%"', 'width="100%"')
            fname = "fig%02d.svg" % n
            io.open(os.path.join(FIG_DIR, fname), "w", encoding="utf-8").write(svg)
            return "\n![%s](figures/%s)\n\n*%s*\n" % (cap, fname, cap)
        return "\n*%s*\n" % cap

    body = re.sub(r"<figure>.*?</figure>", repl_figure, body, flags=re.S)

    # 2) table -> markdown
    body = re.sub(
        r"<table>.*?</table>",
        lambda m: "\n" + table_to_md(m.group(0)) + "\n",
        body,
        flags=re.S,
    )

    # 3) box / warn -> blockquote
    def repl_box(m):
        cls = "box" if 'class="box"' in m.group(0) else "warn"
        inner = m.group(1)
        lbl = re.search(r'<p class="boxlbl">(.*?)</p>', inner, flags=re.S)
        head = strip_inline(lbl.group(1)) if lbl else ""
        inner = re.sub(r'<p class="boxlbl">.*?</p>', "", inner, flags=re.S)
        paras = re.findall(r"<p[^>]*>(.*?)</p>", inner, flags=re.S)
        lines = []
        if head:
            lines.append("> **%s**" % head)
            lines.append(">")
        for p in paras:
            lines.append("> " + strip_inline(p))
            lines.append(">")
        return "\n" + "\n".join(lines).rstrip(">").rstrip() + "\n"

    body = re.sub(r'<div class="(?:box|warn)">(.*?)</div>', repl_box, body, flags=re.S)

    # 4) 表题 / 图题
    body = re.sub(
        r'<p class="tabcap">(.*?)</p>',
        lambda m: "\n**%s**\n" % strip_inline(m.group(1)),
        body,
        flags=re.S,
    )

    # 5) 标题
    body = re.sub(r'<h2[^>]*>(.*?)</h2>', lambda m: "\n## %s\n" % strip_inline(m.group(1)), body, flags=re.S)
    body = re.sub(r'<h3[^>]*>(.*?)</h3>', lambda m: "\n### %s\n" % strip_inline(m.group(1)), body, flags=re.S)
    body = re.sub(r'<h4[^>]*>(.*?)</h4>', lambda m: "\n#### %s\n" % strip_inline(m.group(1)), body, flags=re.S)

    # 6) 列表
    def repl_ul(m):
        items = re.findall(r"<li>(.*?)</li>", m.group(1), flags=re.S)
        return "\n" + "\n".join("- " + strip_inline(i) for i in items) + "\n"

    def repl_ol(m):
        items = re.findall(r"<li>(.*?)</li>", m.group(1), flags=re.S)
        return "\n" + "\n".join("%d. %s" % (i + 1, strip_inline(x)) for i, x in enumerate(items)) + "\n"

    body = re.sub(r"<ul>(.*?)</ul>", repl_ul, body, flags=re.S)
    body = re.sub(r"<ol[^>]*>(.*?)</ol>", repl_ol, body, flags=re.S)

    # 7) 段落
    body = re.sub(r"<p[^>]*>(.*?)</p>", lambda m: "\n%s\n" % strip_inline(m.group(1)), body, flags=re.S)

    # 8) 残留标签与空白
    body = re.sub(r"<[^>]+>", "", body)
    body = body.replace("&amp;", "&")
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    today = datetime.date.today().isoformat()
    header = """# 基于几何约束的多视图二维设计向复杂三维模型表面的高保真纹理转译技术

> **OrthoTex（Geometry-Guided Texture Transfer）** ｜ 问题定义与方案设计
>
> 作者：AvroraCL ｜ 版本：%s ｜ 更新：%s
> 原始来源：<https://avroracl.github.io/geo-guided-texture-transfer/paper/index.html>
>
> **本文由 `paper/index.html` 自动派生，请勿直接编辑本文件。**
> 修改正文请改 HTML，然后运行 `python tools/build-md.py`。
>
> 状态：方案设计阶段。未实现、未验证。正文中 `[假设]` 为待验证推断，`[待补]` 为缺失信息，
> 均不构成结论。全文插图均为概念示意图，不具备证据价值。

---

""" % (VERSION, today)

    io.open(OUT_MD, "w", encoding="utf-8").write(header + body + "\n")

    print("已生成 %s" % os.path.relpath(OUT_MD, ROOT))
    print("已提取 %d 张插图 -> %s" % (fig_count[0], os.path.relpath(FIG_DIR, ROOT)))
    print("正文字符数：%d" % len(body))


if __name__ == "__main__":
    build()
