# -*- coding: utf-8 -*-
"""
生成 UV 空间热图（命令行版）

读取 coverage_cli.json（已修正法线后的正确结果），按材质分别输出：
    灰色 = 该处三个视图能看到（有设计稿可参考）
    红色 = 三个视图都看不到（没有参考，得自己编）

用法：blender --background --factory-startup --python make_heatmap_cli.py
"""

import bpy
import os
import json
import zlib
import struct

OBJ = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"
OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp02_coverage"
HEAT = os.path.join(OUT, "heat")
W = H = 1024
COL_BG = (26, 28, 30)
COL_OK = (175, 178, 180)
COL_NO = (216, 40, 40)

os.makedirs(HEAT, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)

with open(os.path.join(OUT, "coverage_cli.json"), "r", encoding="utf-8") as f:
    cov = json.load(f)["covered_by"]

meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
print("对象 %d   覆盖记录 %d" % (len(meshes), len(cov)))


def save_png(path, buf):
    raw = bytearray()
    for y in range(H):
        raw.append(0)
        raw += buf[y * W * 3:(y + 1) * W * 3]

    def ch(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += ch(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    png += ch(b"IDAT", zlib.compress(bytes(raw), 6))
    png += ch(b"IEND", b"")
    open(path, "wb").write(png)


def raster(buf, p0, p1, p2, c):
    x0 = max(0, int(min(p0[0], p1[0], p2[0]))); x1 = min(W - 1, int(max(p0[0], p1[0], p2[0])) + 1)
    y0 = max(0, int(min(p0[1], p1[1], p2[1]))); y1 = min(H - 1, int(max(p0[1], p1[1], p2[1])) + 1)
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


# 按材质分组
groups = {}
i = 0
for obj in meshes:
    me = obj.data
    uvl = me.uv_layers.active
    mats = [m.name if m else "(none)" for m in me.materials]
    for p in me.polygons:
        m = cov[i] if i < len(cov) else 0
        i += 1
        if uvl is None or len(p.vertices) != 3:
            continue
        mn = mats[p.material_index] if p.material_index < len(mats) else "(none)"
        groups.setdefault(mn, []).append((p, m, uvl))

print("处理面数 %d   材质组 %d" % (i, len(groups)))

lines = []
for mn, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
    buf = bytearray()
    for _ in range(W * H):
        buf += bytes(COL_BG)
    miss = tot = 0
    for p, m, uvl in items:
        tot += 1
        if not m:
            miss += 1
        pts = [(uvl.data[li].uv.x * (W - 1), (1.0 - uvl.data[li].uv.y) * (H - 1))
               for li in p.loop_indices]
        raster(buf, pts[0], pts[1], pts[2], COL_OK if m else COL_NO)
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in mn)[:60]
    save_png(os.path.join(HEAT, safe + ".png"), buf)
    pct = 100.0 * miss / tot if tot else 0
    lines.append("%-42s 面 %7d  看不到 %7d  (%5.1f%%)" % (mn[:42], tot, miss, pct))
    print(lines[-1])

with open(os.path.join(HEAT, "_summary.txt"), "w", encoding="utf-8") as f:
    f.write("\n".join(lines))
print("输出目录:", HEAT)
