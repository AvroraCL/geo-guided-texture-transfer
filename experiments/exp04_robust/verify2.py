# -*- coding: utf-8 -*-
"""
实验 04（重做）：用「相机射线」法独立验证覆盖率

前两次尝试的问题
    方法一：起点沿射线反方向后退 → 方向写反，背向面被误判为可见（99.82%）
    方法二：修正方向后 → 判据过严，正常面也被判为被遮（48.48%）
    两者都说明：**从面出发的射线对起点位置过于敏感**。

本方法（相机射线）
    从相机所在的一侧远处，朝模型方向逐像素发射射线。
    第一个被击中的面，就是该像素「看得见」的面 —— 这是可见性的原始定义。
    完全不依赖法线，也不需要在面上取起点。

    分辨率 512×512 × 3 视图 ≈ 78 万条射线。

用法
    blender --background --factory-startup --python verify2.py
"""

import bpy
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
RES = 512
EPS_PIX = 1e-6

print("=" * 66)
print("实验 04（重做）：相机射线法验证覆盖率")
print("=" * 66)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)
SCENE = bpy.context.scene

objs = [o for o in SCENE.objects if o.type == 'MESH'
        and not o.hide_viewport and not o.hide_get()
        and not any(k in o.name for k in EXCLUDE)]

# 面积统计（按对象+面索引）
area_of = {}
total_area = 0.0
for obj in objs:
    me = obj.data
    for p in me.polygons:
        if len(p.vertices) != 3:
            continue
        area_of[(obj.name, p.index)] = p.area
        total_area += p.area
print("总面数: %d   总面积: %.4f" % (len(area_of), total_area))

# 包围盒（排除离群）
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
BIG = max(size.x, size.y, size.z) * 3.0

VIEWS = [
    ("front", Vector((0, 1, 0)),  Vector((1, 0, 0)), Vector((0, 0, 1)), max(size.x, size.z) * 1.05),
    ("right", Vector((-1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)), max(size.y, size.z) * 1.05),
    ("top",   Vector((0, 0, -1)), Vector((1, 0, 0)), Vector((0, 1, 0)), max(size.x, size.y) * 1.05),
]

dg = bpy.context.evaluated_depsgraph_get()
seen = set()          # 被任一视图看到的面

for vname, vdir, rgt, upv, span in VIEWS:
    hit_n = 0
    for i in range(RES):
        u = (i + 0.5) / RES - 0.5
        for j in range(RES):
            v = (j + 0.5) / RES - 0.5
            P = center + rgt * (u * span) + upv * (v * span)
            origin = P - vdir * BIG
            res = SCENE.ray_cast(dg, origin, vdir)
            if res[0]:
                key = (res[4].name, res[3])
                seen.add(key)
                hit_n += 1
    print("视图 %-6s 命中像素 %7d / %d   累计可见面 %d"
          % (vname, hit_n, RES * RES, len(seen)))

seen_area = sum(area_of[k] for k in seen if k in area_of)
print()
print("=" * 66)
print("【相机射线法】覆盖率: %.2f%%   未覆盖率: %.2f%%"
      % (100.0 * seen_area / total_area, 100.0 * (total_area - seen_area) / total_area))
print("【exp02 结果】覆盖率: 80.39%%   未覆盖率: 19.61%%")
print("=" * 66)

with open(os.path.join(OUT, "verify2_stats.json"), "w", encoding="utf-8") as f:
    json.dump({
        "resolution": RES,
        "total_faces": len(area_of),
        "total_area": total_area,
        "seen_faces": len(seen),
        "seen_area": seen_area,
        "coverage_camera_ray": seen_area / total_area,
        "coverage_exp02": 0.8039,
    }, f, indent=2, ensure_ascii=False)
print()
print("已写出 verify2_stats.json")
