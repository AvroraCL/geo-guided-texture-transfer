# -*- coding: utf-8 -*-
"""
OrthoTex 实验 03（A1）：跨 UV 接缝误差 —— 第二部分：分析与统计

思路
    投影函数是连续的：若两个 UV 位置对应同一个三维点 P，
    它们的投影坐标必然相同。因此理论上跨接缝误差应为 0（除采样离散化外）。
    真正会出错的是遮挡——一侧可见、另一侧不可见。

    本脚本量化这两者：
      (1) 两侧都可投影时，视图坐标之差（应接近 0，验证理论）
      (2) 仅一侧可投影的比例（这是真实问题）

用法
    blender --background --factory-startup --python analyze_seam.py
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
SAMPLES = 8          # 每条接缝边采样点数

print("=" * 66)
print("A1 第二部分：跨 UV 接缝误差分析")
print("=" * 66)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)
SCENE = bpy.context.scene

# 修正法线
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
    bm.free()

# ---- 相机（与 project.py 一致）----
import statistics as st
objs = [o for o in SCENE.objects if o.type == 'MESH'
        and not o.hide_viewport and not o.hide_get()
        and not any(k in o.name for k in EXCLUDE)]
centers = []
for o in objs:
    cs = [o.matrix_world @ Vector(b) for b in o.bound_box]
    centers.append(sum(cs, Vector()) / 8.0)
med = Vector((st.median([c.x for c in centers]),
              st.median([c.y for c in centers]),
              st.median([c.z for c in centers])))
dists = [(c - med).length for c in centers]
thr = max(st.median(dists) * 6.0, 1.0)
kept = [o for o, d in zip(objs, dists) if d <= thr]

pts = [o.matrix_world @ Vector(b) for o in kept for b in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
center = (lo + hi) / 2.0
size = hi - lo
span = max(size.x, size.z) * 1.05

CAM_DIR = Vector((0.0, 1.0, 0.0))
RIGHT = Vector((1.0, 0.0, 0.0))
UP = Vector((0.0, 0.0, 1.0))


def to_view(p):
    d = p - center
    u = d.dot(RIGHT) / span + 0.5
    v = d.dot(UP) / span + 0.5
    if u < 0 or u > 1 or v < 0 or v > 1:
        return None
    return (u, v)


def is_visible(obj, pidx, P, N):
    dg = bpy.context.evaluated_depsgraph_get()
    res = SCENE.ray_cast(dg, P + N * EPS, CAM_DIR)
    return res[0] and res[4] == obj and res[3] == pidx


# ---- 收集面数据（局部 uv + 世界顶点）----
faces = {}
for obj in objs:
    me = obj.data
    mw = obj.matrix_world
    nrm = mw.to_3x3().inverted().transposed()
    uvl = me.uv_layers.active
    if uvl is None:
        continue
    for p in me.polygons:
        if len(p.vertices) != 3:
            continue
        vs, uvs = [], []
        for li in p.loop_indices:
            vs.append(mw @ me.vertices[me.loops[li].vertex_index].co)
            uv = uvl.data[li].uv
            uvs.append((uv.x, uv.y))
        faces[(obj, p.index)] = (vs, uvs, (nrm @ p.normal).normalized())

# ---- 建边表：几何边 -> [(面, 该面上两端点的 uv)] ----
edges = defaultdict(list)
for (obj, pidx), (vs, uvs, n) in faces.items():
    me = obj.data
    poly = me.polygons[pidx]
    vids = [me.loops[li].vertex_index for li in poly.loop_indices]
    for i in range(3):
        a, b = vids[i], vids[(i + 1) % 3]
        key = (obj.name, min(a, b), max(a, b))
        edges[key].append(((obj, pidx), uvs[i], uvs[(i + 1) % 3]))


def same_uv(p, q):
    return abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6


# ---- 找出 UV 接缝边 ----
seams = []
for key, lst in edges.items():
    if len(lst) != 2:
        continue
    (fA, a0, a1), (fB, b0, b1) = lst
    oA, oB = fA[0], fB[0]
    if oA.name != oB.name:
        continue                        # 跨对象，非参数化接缝
    # 同材质内才计为真接缝
    mA = oA.data.materials[oA.data.polygons[fA[1]].material_index].name if oA.data.materials else ""
    mB = oB.data.materials[oB.data.polygons[fB[1]].material_index].name if oB.data.materials else ""
    if mA != mB:
        continue
    if same_uv(a0, b0) and same_uv(a1, b1):
        continue
    seams.append((key, fA, fB, a0, a1, b0, b1))

print("真 UV 接缝边数: %d" % len(seams))

# ---- 逐条接缝采样 ----
diffs = []          # 两侧都可见时的视图坐标差（归一化单位）
both = one = neither = 0
occluded_objs = defaultdict(int)

for key, fA, fB, a0, a1, b0, b1 in seams:
    vsA, uvA, nA = faces[fA]
    vsB, uvB, nB = faces[fB]
    meA = fA[0].data
    polyA = meA.polygons[fA[1]]
    vidsA = [meA.loops[li].vertex_index for li in polyA.loop_indices]

    for s in range(SAMPLES):
        t = (s + 0.5) / SAMPLES
        P = vsA[0] * (1 - t) + vsA[1] * t          # 沿边采样（用 A 侧顶点顺序）
        N = nA

        visA = is_visible(fA[0], fA[1], P, N)
        visB = is_visible(fB[0], fB[1], P, N)

        if visA and visB:
            both += 1
            uA, vA = uvA[0][0] * (1 - t) + uvA[1][0] * t, uvA[0][1] * (1 - t) + uvA[1][1] * t
            uB, vB = uvB[0][0] * (1 - t) + uvB[1][0] * t, uvB[0][1] * (1 - t) + uvB[1][1] * t
            vpA = to_view(P)
            vpB = to_view(P)
            if vpA and vpB:
                du = abs(vpA[0] - vpB[0])
                dv = abs(vpA[1] - vpB[1])
                diffs.append((du * du + dv * dv) ** 0.5 * span)   # 换算成模型单位
        elif visA or visB:
            one += 1
            occluded_objs[(fA[0].name if not visA else fB[0].name)] += 1
        else:
            neither += 1

tot = both + one + neither
print()
print("=" * 66)
print("采样点统计（每条接缝 %d 点，共 %d 点）" % (SAMPLES, tot))
print("=" * 66)
print("两侧都可投影 : %7d (%.1f%%)" % (both, 100.0 * both / tot))
print("仅一侧可投影 : %7d (%.1f%%)   <-- 遮挡导致的真实缺口" % (one, 100.0 * one / tot))
print("两侧都不可投影: %7d (%.1f%%)" % (neither, 100.0 * neither / tot))

if diffs:
    diffs.sort()
    print()
    print("两侧都可投影时，视图坐标差异（换算为模型单位）:")
    print("  样本数   : %d" % len(diffs))
    print("  平均     : %.6f" % (sum(diffs) / len(diffs)))
    print("  中位数   : %.6f" % statistics.median(diffs))
    print("  最大     : %.6f" % diffs[-1])
    print("  （该值应接近 0，用于验证投影的连续性）")

print()
print("被遮挡最多（仅一侧可见）的对象前 8 名:")
for nm, c in sorted(occluded_objs.items(), key=lambda kv: -kv[1])[:8]:
    print("  %-44s %6d" % (nm[:44], c))

with open(os.path.join(OUT, "seam_stats.json"), "w", encoding="utf-8") as f:
    json.dump({
        "seams": len(seams), "samples": tot,
        "both_visible": both, "one_visible": one, "none_visible": neither,
        "diff_mean": (sum(diffs) / len(diffs)) if diffs else None,
        "diff_median": statistics.median(diffs) if diffs else None,
        "diff_max": diffs[-1] if diffs else None,
        "occluded_by_object": dict(sorted(occluded_objs.items(), key=lambda kv: -kv[1])[:20]),
    }, f, indent=2, ensure_ascii=False)

print()
print("已写出 seam_stats.json")
