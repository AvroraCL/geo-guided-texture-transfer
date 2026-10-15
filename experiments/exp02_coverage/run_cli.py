# -*- coding: utf-8 -*-
"""
A2 覆盖率计算 —— 命令行版（无需 GUI 操作）

用法：
    blender --background --factory-startup --python run_cli.py

流程：导入 OBJ -> 建三个正交方向 -> 逐面射线检测遮挡 -> 输出统计与 JSON
"""

import bpy
import os
import json
import time
from mathutils import Vector

OBJ = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"
OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp02_coverage"
os.makedirs(OUT, exist_ok=True)

VIEWS = [
    ("front", Vector((0.0, -1.0, 0.0))),
    ("right", Vector((1.0, 0.0, 0.0))),
    ("top",   Vector((0.0, 0.0, 1.0))),
]
EPS = 1e-4

print("=" * 66)
print("A2 覆盖率计算（命令行版）")
print("=" * 66)

bpy.ops.wm.read_factory_settings(use_empty=True)
t_import = time.time()
bpy.ops.wm.obj_import(filepath=OBJ)
print("导入用时 %.1fs" % (time.time() - t_import))

SCENE = bpy.context.scene

# ---- 修正法线朝向 ----
# 本模型有 36 个对象（轮子、减速板、部分起落架、尾喷口）法线朝内。
# 若不修正，"沿法线外移后投射"会把起点放进物体内部，导致这些对象被误判。
# 判定依据：有符号体积为负 => 朝内。
import bmesh
n_fixed = 0
for obj in SCENE.objects:
    if obj.type != 'MESH':
        continue
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        vol = bm.calc_volume(signed=True)
    except Exception:
        vol = 0.0
    if vol < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
        bm.to_mesh(obj.data)
        obj.data.update()
        n_fixed += 1
    bm.free()
print("法线已翻转的对象: %d" % n_fixed)

# 收集面（世界坐标），跳过隐藏对象
faces = []
for obj in SCENE.objects:
    if obj.type != 'MESH':
        continue
    if obj.hide_viewport or obj.hide_get():
        continue
    me = obj.data
    mw = obj.matrix_world
    nrm = mw.to_3x3().inverted().transposed()
    mats = [m.name if m else "(none)" for m in me.materials]
    for p in me.polygons:
        faces.append((
            obj,
            p.index,
            mw @ p.center,
            (nrm @ p.normal).normalized(),
            p.area,
            mats[p.material_index] if p.material_index < len(mats) else "(none)",
        ))

NF = len(faces)
print("面数: %d" % NF)

dg = bpy.context.evaluated_depsgraph_get()
covered = [0] * NF

t0 = time.time()
for vi, (vname, vdir) in enumerate(VIEWS):
    cam_dir = -vdir
    bit = 1 << vi
    hits = 0
    for i in range(NF):
        obj, pidx, c, n, a, mn = faces[i]
        # 背面剔除（法线已在前面统一修正，可以放心使用）
        if n.dot(cam_dir) > -1e-6:
            continue
        # 从面外侧沿相机方向投射；若第一个交点就是自己，说明没有被挡住
        origin = c + n * EPS
        res = SCENE.ray_cast(dg, origin, cam_dir)
        if res[0] and res[4] == obj and res[3] == pidx:
            covered[i] |= bit
            hits += 1
    print("视图 %-6s 可见 %7d / %d (%.1f%%)   用时累计 %.1fs"
          % (vname, hits, NF, 100.0 * hits / NF, time.time() - t0))

total_area = sum(f[4] for f in faces)
cov_area = sum(faces[i][4] for i in range(NF) if covered[i])

print()
print("=" * 66)
print("总面积      : %.4f" % total_area)
print("被覆盖面积  : %.4f" % cov_area)
print("覆盖率      : %.2f%%" % (100.0 * cov_area / total_area))
print("未覆盖率    : %.2f%%" % (100.0 * (total_area - cov_area) / total_area))

nz = sum(1 for v in covered if v == 0)
print("按面数: 未覆盖 %d / %d (%.1f%%)" % (nz, NF, 100.0 * nz / NF))

from collections import defaultdict
agg = defaultdict(lambda: [0.0, 0.0, 0])
for i in range(NF):
    mn = faces[i][5]
    agg[mn][0] += faces[i][4]
    agg[mn][2] += 1
    if covered[i]:
        agg[mn][1] += faces[i][4]

print()
print("%-40s %8s %10s %9s" % ("材质", "面数", "未覆盖面", "未覆盖%"))
print("-" * 72)
for mn, (ta, ca, cnt) in sorted(agg.items(), key=lambda kv: -(kv[1][0] - kv[1][1])):
    miss = cnt - int(round(ca / ta * cnt)) if ta else 0
    # 精确统计未覆盖面数
    m2 = sum(1 for i in range(NF) if faces[i][5] == mn and not covered[i])
    print("%-40s %8d %10d %8.1f%%" % (mn[:40], cnt, m2, 100.0 * m2 / cnt if cnt else 0))

with open(os.path.join(OUT, "coverage_cli.json"), "w", encoding="utf-8") as f:
    json.dump({
        "faces": NF, "views": [v[0] for v in VIEWS],
        "total_area": total_area, "covered_area": cov_area,
        "coverage_ratio": cov_area / total_area,
        "covered_by": covered,
    }, f)

print()
print("总耗时 %.1fs" % (time.time() - t0))
print("已写出 coverage_cli.json")
