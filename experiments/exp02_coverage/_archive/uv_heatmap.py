# -*- coding: utf-8 -*-
"""
OrthoTex 实验 02 可视化（UV 空间热图，按材质分开输出）

为什么按材质分开：
    本模型 15 个材质各占独立的 0-1 UV 空间。若画到同一张图上会互相覆盖，
    结果看似"全红"。每个材质对应游戏里一张独立的贴图，本来就该分开看。

判定：灰色 = 该面被至少一个视图看到；红色 = 三个视图都看不到。

前提：必须在与 coverage.py 相同的场景状态下运行（对象集合与顺序一致）。

产出：experiments/exp02_coverage/heat/<材质名>.png
"""

import bpy
import os
import json
import zlib
import struct

OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp02_coverage"
JSON_PATH = os.path.join(OUT, "coverage.json")
HEAT_DIR = os.path.join(OUT, "heat")
W = H = 1024

COL_BG    = (28, 30, 32)
COL_COVER = (176, 178, 180)
COL_MISS  = (215, 40, 40)

os.makedirs(HEAT_DIR, exist_ok=True)

with open(JSON_PATH, "r", encoding="utf-8") as f:
    covered_by = json.load(f)["covered_by"]

meshes = [o for o in bpy.context.scene.objects
          if o.type == 'MESH' and not o.hide_viewport and not o.hide_get()]

print("对象数: %d   记录面数: %d" % (len(meshes), len(covered_by)))


def save_png(path, buf):
    raw = bytearray()
    for y in range(H):
        raw.append(0)
        raw += buf[y * W * 3:(y + 1) * W * 3]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 6))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def raster(buf, p0, p1, p2, c):
    xs = (p0[0], p1[0], p2[0])
    ys = (p0[1], p1[1], p2[1])
    x0 = max(0, int(min(xs))); x1 = min(W - 1, int(max(xs)) + 1)
    y0 = max(0, int(min(ys))); y1 = min(H - 1, int(max(ys)) + 1)
    if x1 < x0 or y1 < y0:
        return
    d = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
    if abs(d) < 1e-12:
        return
    for y in range(y0, y1 + 1):
        row = y * W * 3
        for x in range(x0, x1 + 1):
            a = ((p1[1] - p2[1]) * (x - p2[0]) + (p2[0] - p1[0]) * (y - p2[1])) / d
            b = ((p2[1] - p0[1]) * (x - p2[0]) + (p0[0] - p2[0]) * (y - p2[1])) / d
            g = 1.0 - a - b
            if a >= -0.002 and b >= -0.002 and g >= -0.002:
                k = row + x * 3
                buf[k] = c[0]; buf[k + 1] = c[1]; buf[k + 2] = c[2]


# ---- 按材质分组，收集各材质的面（含其 covered_by 值）----
i = 0
groups = {}       # 材质名 -> [(poly, mask), ...]
for obj in meshes:
    me = obj.data
    uvl = me.uv_layers.active
    mat_names = [m.name if m else "(none)" for m in me.materials]
    for p in me.polygons:
        m = covered_by[i] if i < len(covered_by) else 0
        i += 1
        if uvl is None or len(p.vertices) != 3:
            continue
        mn = mat_names[p.material_index] if p.material_index < len(mat_names) else "(none)"
        groups.setdefault(mn, []).append((p, m, uvl))

print("处理面数: %d   材质组数: %d" % (i, len(groups)))

# ---- 逐材质输出 ----
summary = []
for mn, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    buf = bytearray()
    for _ in range(W * H):
        buf += bytes(COL_BG)

    n_miss = n_tot = 0
    for p, m, uvl in items:
        n_tot += 1
        c = COL_COVER if m else COL_MISS
        if not m:
            n_miss += 1
        pts = []
        for li in p.loop_indices:
            uv = uvl.data[li].uv
            pts.append((uv.x * (W - 1), (1.0 - uv.y) * (H - 1)))
        raster(buf, pts[0], pts[1], pts[2], c)

    safe = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in mn)[:60]
    path = os.path.join(HEAT_DIR, safe + ".png")
    save_png(path, buf)

    pct = 100.0 * n_miss / n_tot if n_tot else 0.0
    summary.append((mn, n_tot, n_miss, pct))
    print("  %-40s 面 %7d   未覆盖 %7d  (%5.1f%%)" % (mn[:40], n_tot, n_miss, pct))

with open(os.path.join(HEAT_DIR, "_summary.txt"), "w", encoding="utf-8") as f:
    f.write("%-40s %8s %10s %8s\n" % ("material", "faces", "missing", "pct"))
    for mn, n_tot, n_miss, pct in sorted(summary, key=lambda t: -t[3]):
        f.write("%-40s %8d %10d %7.1f%%\n" % (mn[:40], n_tot, n_miss, pct))

print()
print("全部热图已输出到:", HEAT_DIR)
print("灰色 = 覆盖   红色 = 三视图都看不到")
