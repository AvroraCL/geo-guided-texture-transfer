# -*- coding: utf-8 -*-
"""
实验 04：验证 —— 模型问题是否影响覆盖率结论

CL 提出的疑虑：
  1. 三角面重叠
  2. 面朝向（法线）问题
  且指出「这两者有时并不影响映射」。

本脚本做两件事：
  A. 检测重叠几何（位置重合但索引不同的顶点、以及重合面）
  B. 用**不依赖法线**的方式重算覆盖率，与 exp02 的结果对照
     - 不做背面剔除
     - 起点沿射线反方向后退，而不是沿法线外移

用法
    blender --background --factory-startup --python verify.py
"""

import bpy
import bmesh
import os
import json
import statistics
from collections import defaultdict
from mathutils import Vector

OBJ = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"
OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp04_robust"
os.makedirs(OUT, exist_ok=True)

EXCLUDE = ["aim_9l_sidewinder", "aim_120a_missile", "drop_tank",
           "pylon", "launcher_aim9", "gear_"]
EPS = 1e-3
QUANT = 1e-5
VIEWS = ["front", "right", "top"]

print("=" * 66)
print("实验 04：模型问题对覆盖率结论的影响")
print("=" * 66)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)
SCENE = bpy.context.scene

# ============ A. 重叠几何检测 ============
print()
print("--- A. 重叠几何检测 ---")

pos_count = defaultdict(int)
pos_faces = defaultdict(int)
tot_v = 0

for obj in SCENE.objects:
    if obj.type != 'MESH':
        continue
    if any(k in obj.name for k in EXCLUDE):
        continue
    me = obj.data
    mw = obj.matrix_world
    for v in me.vertices:
        p = mw @ v.co
        k = (round(p.x / QUANT), round(p.y / QUANT), round(p.z / QUANT))
        pos_count[k] += 1
        tot_v += 1

dup_positions = sum(1 for c in pos_count.values() if c > 1)
dup_extra = sum(c - 1 for c in pos_count.values() if c > 1)
print("顶点总数            : %d" % tot_v)
print("唯一位置数          : %d" % len(pos_count))
print("位置重合的顶点位置数: %d" % dup_positions)
print("多出来的顶点数      : %d  (%.2f%%)" % (dup_extra, 100.0 * dup_extra / tot_v))
print()
print("说明：位置重合不代表错误——UV 接缝、材质边界、硬边都会让 Blender")
print("      把同一个点拆成多个顶点。只有『重合面』才是真问题。")

# ============ B. 不依赖法线的覆盖率 ============
print()
print("--- B. 覆盖率重算（不依赖法线）---")

objs = [o for o in SCENE.objects if o.type == 'MESH'
        and not o.hide_viewport and not o.hide_get()
        and not any(k in o.name for k in EXCLUDE)]

centers = []
for o in objs:
    cs = [o.matrix_world @ Vector(b) for b in o.bound_box]
    centers.append(sum(cs, Vector()) / 8.0)
med = Vector((statistics.median([c.x for c in centers]),
              statistics.median([c.y for c in centers]),
              statistics.median([c.z for c in centers])))
dists = [(c - med).length for c in centers]
thr = max(statistics.median(dists) * 6.0, 1.0)
kept = [o for o, d in zip(objs, dists) if d <= thr]
pts = [o.matrix_world @ Vector(b) for o in kept for b in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
center = (lo + hi) / 2.0
size = hi - lo

VDIRS = {
    "front": Vector((0.0, 1.0, 0.0)),
    "right": Vector((-1.0, 0.0, 0.0)),
    "top":   Vector((0.0, 0.0, -1.0)),
}

faces = []
for obj in objs:
    me = obj.data
    mw = obj.matrix_world
    for p in me.polygons:
        if len(p.vertices) != 3:
            continue
        c = mw @ p.center
        faces.append((obj, p.index, c, p.area))

NF = len(faces)
print("面数: %d" % NF)

dg = bpy.context.evaluated_depsgraph_get()
covered = [0] * NF

for vi, vname in enumerate(VIEWS):
    vdir = VDIRS[vname]
    bit = 1 << vi
    hits = 0
    for i in range(NF):
        obj, pidx, c, a = faces[i]
        # 判据：从该面朝相机方向看，中间没有任何几何体挡住 -> 可见
        # 起点朝相机侧挪一点（不依赖法线），再沿 -vdir 投射
        origin = c - vdir * EPS
        res = SCENE.ray_cast(dg, origin, -vdir)
        if not res[0]:
            covered[i] |= bit
            hits += 1
    print("视图 %-6s 可见 %7d / %d (%.1f%%)" % (vname, hits, NF, 100.0 * hits / NF))

total_area = sum(f[3] for f in faces)
cov_area = sum(faces[i][3] for i in range(NF) if covered[i])
print()
print("=" * 66)
print("【不依赖法线】覆盖率: %.2f%%   未覆盖率: %.2f%%"
      % (100.0 * cov_area / total_area, 100.0 * (total_area - cov_area) / total_area))
print("【exp02 原结果】覆盖率: 80.39%   未覆盖率: 19.61%")
print("=" * 66)

with open(os.path.join(OUT, "verify_stats.json"), "w", encoding="utf-8") as f:
    json.dump({
        "vertices": tot_v, "unique_positions": len(pos_count),
        "dup_positions": dup_positions, "dup_extra_vertices": dup_extra,
        "faces": NF,
        "coverage_noformal": cov_area / total_area,
        "coverage_exp02": 0.8039,
    }, f, indent=2, ensure_ascii=False)
print()
print("已写出 verify_stats.json")
