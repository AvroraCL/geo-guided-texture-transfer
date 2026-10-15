# -*- coding: utf-8 -*-
"""
OrthoTex 实验 02（A2）：三视图对模型表面的覆盖率

判定方式：射线遮挡检测（不是"UV 上有没有颜色"）
  - 对每个三角面，从其中心沿相机视线方向投射射线
  - 若第一个交点就是该面自身 -> 该面在此视图可见
  - 只要被三个视图中任意一个看到，即算"被覆盖"

前提：场景中应只有一个网格对象。多个对象请先全选后 Ctrl+J 合并。

产出：
  - 控制台统计（总覆盖率、各视图贡献、按材质明细）
  - experiments/exp02_coverage/coverage.json   逐面覆盖计数

注意：本脚本不修改几何、UV 与材质。
"""

import bpy
import os
import json
import time
from mathutils import Vector

SCRIPT_VERSION = "v1 / 2026-10-16"
OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp02_coverage"
os.makedirs(OUT, exist_ok=True)

VIEWS = [
    ("front", Vector((0.0, -1.0, 0.0))),   # 相机位于 -Y，看向 +Y
    ("right", Vector((1.0, 0.0, 0.0))),    # 相机位于 +X，看向 -X
    ("top",   Vector((0.0, 0.0, 1.0))),    # 相机位于 +Z，看向 -Z
]

print("=" * 60)
print("coverage.py 版本:", SCRIPT_VERSION)
print("=" * 60)

meshes = [o for o in bpy.context.scene.objects
          if o.type == 'MESH' and not o.hide_viewport and not o.hide_get()]
if not meshes:
    raise RuntimeError("场景中没有可见网格对象。")

print("参与计算的网格对象数: %d" % len(meshes))

scene = bpy.context.scene
depsgraph = bpy.context.evaluated_depsgraph_get()

# ---- 收集所有对象的面信息（世界坐标）----
faces = []       # (obj, poly_index, center, normal, area, mat_name)
for obj in meshes:
    me = obj.data
    mw = obj.matrix_world
    nrm_mat = mw.to_3x3().inverted().transposed()
    mat_names = [m.name if m else "(none)" for m in me.materials]
    for p in me.polygons:
        faces.append((
            obj,
            p.index,
            mw @ p.center,
            (nrm_mat @ p.normal).normalized(),
            p.area,
            mat_names[p.material_index] if p.material_index < len(mat_names) else "(none)",
        ))

NF = len(faces)
n_tri = sum(1 for o in meshes for p in o.data.polygons if len(p.vertices) == 3)
print("总面数: %d   其中三角面: %d" % (NF, n_tri))
if n_tri != NF:
    print("!! 存在非三角面，本脚本按面中心处理，结果仍可用，但建议先三角化。")

covered_by = [0] * NF      # 位掩码：1=front 2=right 4=top
EPS = 1e-4

t0 = time.time()
for vi, (vname, vdir) in enumerate(VIEWS):
    cam_dir = -vdir          # 从相机指向模型的方向
    bit = 1 << vi
    hit_count = 0
    for i in range(NF):
        obj, pidx, c, n, a, mn = faces[i]
        # 不做背面剔除：
        # 本模型有 36 个对象的法线是反的（轮子、减速板、部分起落架、尾喷口），
        # 若按法线剔除，这些对象会被整体误判为"未覆盖"。
        # 对封闭网格而言，背向相机的面必然被前方几何遮挡，射线检测已能正确判定，
        # 因此这里只用射线，不依赖法线朝向。
        # 起点沿法线微移以避免自相交；法线方向不可靠时改为双向尝试。
        for sign in (1.0, -1.0):
            origin = c + n * (EPS * sign)
            res = scene.ray_cast(depsgraph, origin, cam_dir)
            if not res[0]:
                continue
            if res[4] == obj and res[3] == pidx:
                covered_by[i] |= bit
                hit_count += 1
                break
    print("视图 %-6s 可见面数: %d / %d  (%.1f%%)  累计用时 %.1fs"
          % (vname, hit_count, NF,
             100.0 * hit_count / NF, time.time() - t0))

# ---- 统计 ----
total_area = sum(f[4] for f in faces)
cov_area = sum(faces[i][4] for i in range(NF) if covered_by[i])
print()
print("=" * 60)
print("覆盖率（按面积加权）")
print("=" * 60)
print("总面积        : %.4f" % total_area)
print("被覆盖面积    : %.4f" % cov_area)
print("覆盖率        : %.2f%%" % (100.0 * cov_area / total_area))
print("未覆盖面积占比: %.2f%%" % (100.0 * (total_area - cov_area) / total_area))

from collections import defaultdict
by_mat = defaultdict(lambda: [0.0, 0.0, 0])
for i in range(NF):
    mn = faces[i][5]
    by_mat[mn][0] += faces[i][4]
    by_mat[mn][2] += 1
    if covered_by[i]:
        by_mat[mn][1] += faces[i][4]

print()
print("%-34s %10s %10s %8s" % ("材质", "总面积", "未覆盖", "未覆盖%"))
print("-" * 68)
for mn, (ta, ca, cnt) in sorted(by_mat.items(), key=lambda kv: -(kv[1][0] - kv[1][1])):
    unc = ta - ca
    print("%-34s %10.4f %10.4f %7.1f%%" % (mn[:34], ta, unc, 100.0 * unc / ta if ta else 0))

with open(os.path.join(OUT, "coverage.json"), "w", encoding="utf-8") as f:
    json.dump({
        "version": SCRIPT_VERSION,
        "blender": bpy.app.version_string,
        "objects": [o.name for o in meshes],
        "object_count": len(meshes),
        "views": [v[0] for v in VIEWS],
        "face_count": NF,
        "total_area": total_area,
        "covered_area": cov_area,
        "coverage_ratio": cov_area / total_area if total_area else 0,
        "covered_by": covered_by,
    }, f)

print()
print("逐面覆盖计数已写入:", os.path.join(OUT, "coverage.json"))
print("总耗时 %.1fs" % (time.time() - t0))
