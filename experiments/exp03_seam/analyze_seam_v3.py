# -*- coding: utf-8 -*-
"""
OrthoTex 实验 03（A1）：跨 UV 接缝误差 —— v3

v1/v2 的错误
  1. 用顶点索引识别几何边：Blender 导入 OBJ 时按 (顶点,UV,法线) 拆分顶点，
     共享边被拆开，接缝数虚高到 30 万（实际 7.6 万）。v2 改用顶点位置，但：
  2. UV 比较未处理方向：两个面在同一条边上顶点顺序可能相反，
     只比较同向会漏掉大量"其实连续"的边 —— 这是 v2 仍报 30 万的原因。
  3. 只用 front 一个视图，95.9% 采样点两侧都不可见，无法比较。

v3 修正
  - UV 比较同时处理正向与反向
  - 三个视图分别判断可见性，按"共同可见视图"分类

用法
    blender --background --factory-startup --python analyze_seam_v3.py
"""

import bpy
import os
import bmesh
import json
import statistics
from collections import defaultdict
from mathutils import Vector

OBJ = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"
OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp03_seam"

EXCLUDE = ["aim_9l_sidewinder", "aim_120a_missile", "drop_tank",
           "pylon", "launcher_aim9", "gear_"]
EPS = 1e-4
SAMPLES = 6
QUANT = 1e-5

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)
SCENE = bpy.context.scene

for obj in SCENE.objects:
    if obj.type != 'MESH':
        continue
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    try:
        vv = bm.calc_volume(signed=True)
    except Exception:
        vv = 0
    if vv < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
        bm.to_mesh(obj.data)
        obj.data.update()
    bm.free()

# ---- 包围盒与三视图相机 ----
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

# 三个视图：(名称, 视线方向, 横轴, 纵轴)
VIEWS = [
    ("front", Vector((0, 1, 0)),  Vector((1, 0, 0)), Vector((0, 0, 1)), max(size.x, size.z) * 1.05),
    ("right", Vector((-1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)), max(size.y, size.z) * 1.05),
    ("top",   Vector((0, 0, -1)), Vector((1, 0, 0)), Vector((0, 1, 0)), max(size.x, size.y) * 1.05),
]


def in_view(P, right, up, span):
    d = P - center
    u = d.dot(right) / span + 0.5
    v = d.dot(up) / span + 0.5
    return (0.0 <= u <= 1.0) and (0.0 <= v <= 1.0)


def key3(p):
    return (round(p.x / QUANT), round(p.y / QUANT), round(p.z / QUANT))


print("收集面数据 ...")
faces = {}
for obj in objs:
    me = obj.data
    mw = obj.matrix_world
    uvl = me.uv_layers.active
    if uvl is None:
        continue
    mats = [m.name if m else "" for m in me.materials]
    for p in me.polygons:
        if len(p.vertices) != 3:
            continue
        vs, uvs = [], []
        for li in p.loop_indices:
            vs.append(mw @ me.vertices[me.loops[li].vertex_index].co)
            uv = uvl.data[li].uv
            uvs.append((uv.x, uv.y))
        mi = p.material_index
        nrm = mw.to_3x3().inverted().transposed() @ p.normal
        faces[(obj.name, p.index)] = (vs, uvs,
                                      mats[mi] if mi < len(mats) else "",
                                      obj, p.index, nrm.normalized())
print("面数: %d" % len(faces))

print("建边表 ...")
edges = defaultdict(list)
for fid, (vs, uvs, mat, obj, pidx, nrm) in faces.items():
    ks = [key3(v) for v in vs]
    for i in range(3):
        a, b = ks[i], ks[(i + 1) % 3]
        k = (a, b) if a < b else (b, a)
        edges[k].append((fid, uvs[i], uvs[(i + 1) % 3]))
print("唯一边: %d" % len(edges))


def eq_uv(p, q):
    return abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6


seams = []
for k, lst in edges.items():
    if len(lst) != 2:
        continue
    (fidA, a0, a1), (fidB, b0, b1) = lst
    if faces[fidA][2] != faces[fidB][2]:
        continue
    # ---- 关键修正：同时比较正向与反向 ----
    forward = eq_uv(a0, b0) and eq_uv(a1, b1)
    backward = eq_uv(a0, b1) and eq_uv(a1, b0)
    if forward or backward:
        continue                       # UV 连续，不是接缝
    seams.append((fidA, fidB))

print("真 UV 接缝边数: %d" % len(seams))

# ---- 逐条接缝采样，三视图分类 ----
both_common = 0     # 两侧被同一视图看到
cross_view = 0      # 两侧分别被不同视图看到
one_only = 0        # 只有一侧被任一试图看到
none_vis = 0        # 两侧都看不到
diffs = []
occl = defaultdict(int)
dg = bpy.context.evaluated_depsgraph_get()

for fidA, fidB in seams:
    vsA, uvA, matA, objA, pidxA, nA = faces[fidA]
    vsB, uvB, matB, objB, pidxB, nB = faces[fidB]

    kA = [key3(v) for v in vsA]
    kB = [key3(v) for v in vsB]
    common = [i for i in range(3) if kA[i] in kB]
    if len(common) < 2:
        continue
    P0, P1 = vsA[common[0]], vsA[common[1]]

    for s in range(SAMPLES):
        t = (s + 0.5) / SAMPLES
        P = P0 * (1 - t) + P1 * t

        # 用各自的真实面法线偏移起点（此前用近似法线，方向不可靠）
        visA, visB = set(), set()
        for vname, vdir, rgt, upv, spn in VIEWS:
            if not in_view(P, rgt, upv, spn):
                continue
            if nA.dot(vdir) < 0:                      # 背面剔除
                rA = SCENE.ray_cast(dg, P + nA * EPS, vdir)
                if rA[0] and rA[4] == objA and rA[3] == pidxA:
                    visA.add(vname)
            if nB.dot(vdir) < 0:
                rB = SCENE.ray_cast(dg, P + nB * EPS, vdir)
                if rB[0] and rB[4] == objB and rB[3] == pidxB:
                    visB.add(vname)

        if visA and visB:
            share = visA & visB
            if share:
                both_common += 1
                diffs.append(0.0)      # 同一视图、同一三维点，投影坐标必然相同
            else:
                cross_view += 1
        elif visA or visB:
            one_only += 1
            occl[(objB.name if not visB else objA.name)] += 1
        else:
            none_vis += 1

tot = both_common + cross_view + one_only + none_vis
print()
print("=" * 66)
print("采样点：%d（%d 条接缝 × %d 点）" % (tot, len(seams), SAMPLES))
print("=" * 66)
if tot:
    print("两侧有共同可见视图 : %7d (%.1f%%)  <- 投影必然一致" % (both_common, 100.0 * both_common / tot))
    print("两侧可见但视图不同 : %7d (%.1f%%)  <- 只能靠视图间协调" % (cross_view, 100.0 * cross_view / tot))
    print("仅一侧可见         : %7d (%.1f%%)  <- 遮挡造成的信息缺口" % (one_only, 100.0 * one_only / tot))
    print("两侧都不可见       : %7d (%.1f%%)" % (none_vis, 100.0 * none_vis / tot))

if occl:
    print()
    print("仅一侧可见时，缺失方最多的对象前 8:")
    for nm, c in sorted(occl.items(), key=lambda kv: -kv[1])[:8]:
        print("  %-44s %6d" % (nm[:44], c))

with open(os.path.join(OUT, "seam_stats_v3.json"), "w", encoding="utf-8") as f:
    json.dump({
        "seams": len(seams), "samples": tot,
        "both_common_view": both_common, "cross_view": cross_view,
        "one_only": one_only, "none_visible": none_vis,
        "occluded": dict(sorted(occl.items(), key=lambda kv: -kv[1])[:20]),
    }, f, indent=2, ensure_ascii=False)
print()
print("已写出 seam_stats_v3.json")
