# -*- coding: utf-8 -*-
"""
OrthoTex 实验 03（A1）：跨 UV 接缝误差 —— v2（修正接缝识别）

v1 的错误
    Blender 导入 OBJ 时按 (顶点,UV,法线) 组合拆分顶点，
    原本共享的几何边被拆成多条，按顶点索引识别接缝会得到虚高的数字
    （v1 报 300,349 条，而 OBJ 层面的真接缝是 76,234 条）。
    修正：改用【顶点世界坐标】识别几何边。

测量目标
    (1) 两侧都能投影时，视图坐标之差 —— 用于验证投影的连续性（理论应为 0）
    (2) 仅一侧能投影的比例 —— 这是遮挡造成的真实信息缺口
    (3) 两侧都不能投影的比例

用法
    blender --background --factory-startup --python analyze_seam_v2.py
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
QUANT = 1e-5        # 顶点位置量化精度

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)
SCENE = bpy.context.scene

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

# ---- 相机 ----
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


def key3(p):
    return (round(p.x / QUANT), round(p.y / QUANT), round(p.z / QUANT))


# ---- 收集面：三个顶点的世界坐标 + uv + 材质 ----
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
        faces[(obj.name, p.index)] = (vs, uvs, mats[mi] if mi < len(mats) else "", obj, p.index)

print("面数: %d" % len(faces))

# ---- 按顶点位置建边表 ----
print("建边表 ...")
edges = defaultdict(list)
for fid, (vs, uvs, mat, obj, pidx) in faces.items():
    ks = [key3(v) for v in vs]
    for i in range(3):
        a, b = ks[i], ks[(i + 1) % 3]
        k = (a, b) if a < b else (b, a)
        edges[k].append((fid, uvs[i], uvs[(i + 1) % 3]))

print("唯一边: %d" % len(edges))


def same_uv(p, q):
    return abs(p[0] - q[0]) < 1e-6 and abs(p[1] - q[1]) < 1e-6


seams = []
for k, lst in edges.items():
    if len(lst) != 2:
        continue
    (fidA, a0, a1), (fidB, b0, b1) = lst
    mA = faces[fidA][2]
    mB = faces[fidB][2]
    if mA != mB:
        continue                     # 材质不同，非同一贴图内的接缝
    if same_uv(a0, b0) and same_uv(a1, b1):
        continue                     # UV 连续，不是接缝
    seams.append((fidA, fidB, a0, a1, b0, b1))

print("真 UV 接缝边数: %d" % len(seams))

# ---- 逐条接缝采样 ----
both = one = none = 0
diffs = []
occl = defaultdict(int)
dg = bpy.context.evaluated_depsgraph_get()

for fidA, fidB, a0, a1, b0, b1 in seams:
    vsA, uvA, matA, objA, pidxA = faces[fidA]
    vsB, uvB, matB, objB, pidxB = faces[fidB]

    # 找到 A、B 两侧在该边上共同的顶点（按位置）
    kA = [key3(v) for v in vsA]
    kB = [key3(v) for v in vsB]
    common = [i for i in range(3) if kA[i] in kB]
    if len(common) < 2:
        continue
    i0, i1 = common[0], common[1]
    P0, P1 = vsA[i0], vsA[i1]

    for s in range(SAMPLES):
        t = (s + 0.5) / SAMPLES
        P = P0 * (1 - t) + P1 * t
        N = Vector((0.0, 0.0, 0.0))
        for vv in vsA:
            N += (P - vv)
        if N.length < 1e-9:
            continue
        N.normalize()

        visA = False
        resA = SCENE.ray_cast(dg, P + N * EPS, CAM_DIR)
        if resA[0] and resA[4] == objA and resA[3] == pidxA:
            visA = True
        visB = False
        resB = SCENE.ray_cast(dg, P - N * EPS, CAM_DIR)
        if resB[0] and resB[4] == objB and resB[3] == pidxB:
            visB = True

        if visA and visB:
            both += 1
            va = to_view(P)
            vb = to_view(P)
            if va and vb:
                du = va[0] - vb[0]
                dv = va[1] - vb[1]
                diffs.append(((du * du + dv * dv) ** 0.5) * span)
        elif visA or visB:
            one += 1
            occl[objB.name if not visB else objA.name] += 1
        else:
            none += 1

tot = both + one + none
print()
print("=" * 66)
print("采样点：%d 个（%d 条接缝 × %d 点）" % (tot, len(seams), SAMPLES))
print("=" * 66)
if tot:
    print("两侧都可投影  : %7d (%.1f%%)" % (both, 100.0 * both / tot))
    print("仅一侧可投影  : %7d (%.1f%%)   <-- 遮挡造成的真实缺口" % (one, 100.0 * one / tot))
    print("两侧都不可投影: %7d (%.1f%%)" % (none, 100.0 * none / tot))
    print()
    if diffs:
        ds = sorted(diffs)
        print("两侧都可投影时，视图坐标之差（模型单位）:")
        print("  样本 %d   平均 %.8f   中位 %.8f   最大 %.8f"
              % (len(ds), sum(ds) / len(ds), statistics.median(ds), ds[-1]))
        print("  -> 该值应极接近 0，用于验证投影在接缝处的连续性")
    else:
        print("两侧都可投影的样本为 0，无法验证连续性（front 单视图覆盖不足）")

if occl:
    print()
    print("被遮挡最多的对象前 8:")
    for nm, c in sorted(occl.items(), key=lambda kv: -kv[1])[:8]:
        print("  %-44s %6d" % (nm[:44], c))

with open(os.path.join(OUT, "seam_stats_v2.json"), "w", encoding="utf-8") as f:
    json.dump({
        "seams": len(seams), "samples": tot,
        "both": both, "one": one, "none": none,
        "diff_mean": (sum(diffs) / len(diffs)) if diffs else None,
        "diff_median": statistics.median(diffs) if diffs else None,
        "diff_max": max(diffs) if diffs else None,
        "occluded": dict(sorted(occl.items(), key=lambda kv: -kv[1])[:20]),
    }, f, indent=2, ensure_ascii=False)
print()
print("已写出 seam_stats_v2.json")
