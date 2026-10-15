# -*- coding: utf-8 -*-
"""
A2 对比：只看飞机本体（排除挂载物与起落架）

用途：回答"如果只涂装飞机本体，未覆盖率是多少"

排除的部件：
    武器与挂载 —— aim_9l_sidewinder / aim_120a_missile / drop_tank / pylon / launcher_aim9
    起落架     —— gear_*
输出：控制台对比 + coverage_bodyonly.json
"""

import bpy
import os
import json
import bmesh
from mathutils import Vector

OBJ = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"
OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp02_coverage"

EXCLUDE_KEYS = ["aim_9l_sidewinder", "aim_120a_missile", "drop_tank",
                "pylon", "launcher_aim9", "gear_"]

VIEWS = [("front", Vector((0, -1, 0))),
         ("right", Vector((1, 0, 0))),
         ("top", Vector((0, 0, 1)))]
EPS = 1e-4

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)
SCENE = bpy.context.scene

# 修正法线
nfix = 0
for obj in SCENE.objects:
    if obj.type != 'MESH':
        continue
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        v = bm.calc_volume(signed=True)
    except Exception:
        v = 0
    if v < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
        bm.to_mesh(obj.data)
        obj.data.update()
        nfix += 1
    bm.free()

# 收集面，排除指定部件
faces = []
n_excluded = 0
for obj in SCENE.objects:
    if obj.type != 'MESH':
        continue
    if any(k in obj.name for k in EXCLUDE_KEYS):
        n_excluded += 1
        continue
    me = obj.data
    mw = obj.matrix_world
    nrm = mw.to_3x3().inverted().transposed()
    for p in me.polygons:
        faces.append((obj, p.index, mw @ p.center,
                      (nrm @ p.normal).normalized(), p.area))

NF = len(faces)
print("=" * 64)
print("法线修正 %d 个对象；排除部件 %d 个对象" % (nfix, n_excluded))
print("参与计算的面数: %d" % NF)

dg = bpy.context.evaluated_depsgraph_get()
covered = [0] * NF

for vi, (vn, vd) in enumerate(VIEWS):
    cd = -vd
    bit = 1 << vi
    hits = 0
    for i in range(NF):
        obj, pidx, c, n, a = faces[i]
        if n.dot(cd) > -1e-6:
            continue
        res = SCENE.ray_cast(dg, c + n * EPS, cd)
        if res[0] and res[4] == obj and res[3] == pidx:
            covered[i] |= bit
            hits += 1
    print("视图 %-6s 可见 %7d / %d (%.1f%%)" % (vn, hits, NF, 100.0 * hits / NF))

ta = sum(f[4] for f in faces)
ca = sum(faces[i][4] for i in range(NF) if covered[i])
nz = sum(1 for v in covered if v == 0)

print()
print("=" * 64)
print("【仅飞机本体】")
print("覆盖率      : %.2f%%" % (100.0 * ca / ta))
print("未覆盖率    : %.2f%%" % (100.0 * (ta - ca) / ta))
print("按面数未覆盖: %d / %d (%.1f%%)" % (nz, NF, 100.0 * nz / NF))

with open(os.path.join(OUT, "coverage_bodyonly.json"), "w", encoding="utf-8") as f:
    json.dump({"faces": NF, "total_area": ta, "covered_area": ca,
               "coverage_ratio": ca / ta, "covered_by": covered}, f)
print("已写出 coverage_bodyonly.json")
