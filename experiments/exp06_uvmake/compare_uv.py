# -*- coding: utf-8 -*-
"""
exp06：代理网格的 UV 简化方法对比

问题
    路线 D（SPM）的前提是"代理网格用简单 UV"。但 exp05 实测：
    Smart UV Project 展开后 12,153 个岛（比原模型 10,616 还多），UV 面积仅 25.9%。
    "UV 简化"这一环未达成。

本实验
    在简化后的本体网格上，横向对比 6 种 UV 生成方案：
      smart66_25    Smart UV Project 66°（基线，复现 exp05）
      unwrap45_25   仅标硬边(45°)为切缝 + Angle-Based Unwrap + Pack
      unwrap60_25   （同上，60°）
      unwrap75_25   （同上，75°）
      unwrap60_10   10% 简化 + unwrap(60°)
      unwrap60_05    5% 简化 + unwrap(60°)
    每组统计：岛数、UV 面积利用率、面积畸变分布（p10/p50/p90）、用时。

判定
    目标：岛数大幅下降（目标 < 2000）、面积利用率上升（目标 > 50%）、
    面积畸变可控（p90/p10 尽量小）。

产出
    exp06_uvmake/uv_compare.json    全部统计
    exp06_uvmake/layout_<方法>.png  各方案的 UV 布局图
"""

import bpy
import bmesh
import os
import json
import zlib
import struct
import time
from math import radians

OBJ = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"
OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp06_uvmake"
os.makedirs(OUT, exist_ok=True)

EXCLUDE_KEYS = ["aim_9l_sidewinder", "aim_120a_missile", "drop_tank",
                "pylon", "launcher_aim9", "gear_", "wheel_"]

METHODS = [
    ("smart66_25", 0.25, "smart", 66.0),
    ("unwrap45_25", 0.25, "unwrap", 45.0),
    ("unwrap60_25", 0.25, "unwrap", 60.0),
    ("unwrap75_25", 0.25, "unwrap", 75.0),
    ("unwrap60_10", 0.10, "unwrap", 60.0),
    ("unwrap60_05", 0.05, "unwrap", 60.0),
]

TEX = 1024


def build_base(ratio):
    """导入 → 修法线 → 排除 → 合并 → Decimate，返回对象名"""
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

    keep = []
    for obj in SCENE.objects:
        if obj.type != 'MESH':
            continue
        if any(k in obj.name for k in EXCLUDE_KEYS):
            continue
        keep.append(obj)
    for obj in list(SCENE.objects):
        if obj.type == 'MESH' and obj not in keep:
            bpy.data.objects.remove(obj, do_unlink=True)

    bpy.ops.object.select_all(action='DESELECT')
    for o in keep:
        o.select_set(True)
    bpy.context.view_layer.objects.active = keep[0]
    bpy.ops.object.join()
    body = bpy.context.view_layer.objects.active

    if ratio < 0.999:
        mod = body.modifiers.new(name="dec", type='DECIMATE')
        mod.ratio = ratio
        bpy.context.view_layer.objects.active = body
        bpy.ops.object.modifier_apply(modifier="dec")

    return body


def clear_uv(obj):
    me = obj.data
    while len(me.uv_layers) > 0:
        me.uv_layers.remove(me.uv_layers[0])
    me.uv_layers.new(name="UVMap")


def apply_smart(obj, angle):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=angle, island_margin=0.001)
    bpy.ops.object.mode_set(mode='OBJECT')


def apply_unwrap(obj, sharp_deg):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.mesh.select_mode(type='EDGE')
    bpy.ops.mesh.mark_seam(clear=True)
    bpy.ops.mesh.edges_select_sharp(sharpness=radians(sharp_deg))
    bpy.ops.mesh.mark_seam(clear=False)
    bpy.ops.mesh.select_mode(type='FACE')
    bpy.ops.mesh.select_all(action='SELECT')
    try:
        bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=0.001)
    except Exception as e:
        print("  !! unwrap 失败:", e)
    try:
        bpy.ops.uv.select_all(action='SELECT')
        bpy.ops.uv.pack_islands(margin=0.001)
    except Exception as e:
        print("  !! pack 失败:", e)
    bpy.ops.object.mode_set(mode='OBJECT')


def count_islands(obj):
    me = obj.data
    uvl = me.uv_layers.active
    if uvl is None:
        return -1
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.faces.ensure_lookup_table()
    uvl_b = bm.loops.layers.uv.active
    nf = len(bm.faces)
    parent = list(range(nf))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def uvo(f, v):
        for l in f.loops:
            if l.vert == v:
                return (round(l[uvl_b].uv.x, 6), round(l[uvl_b].uv.y, 6))
        return None

    idx = {f.index: i for i, f in enumerate(bm.faces)}
    for e in bm.edges:
        if len(e.link_faces) != 2:
            continue
        f1, f2 = e.link_faces
        va, vb = e.verts
        a1 = uvo(f1, va); b1 = uvo(f1, vb)
        a2 = uvo(f2, va); b2 = uvo(f2, vb)
        if None in (a1, b1, a2, b2):
            continue
        same = (a1 == a2 and b1 == b2) or (a1 == b2 and b1 == a2)
        if same:
            r1, r2 = find(idx[f1.index]), find(idx[f2.index])
            if r1 != r2:
                parent[r1] = r2
    n = len({find(i) for i in range(nf)})
    bm.free()
    return n


def compute_stats(obj):
    me = obj.data
    uvl = me.uv_layers.active
    ratios = []
    uv_total = 0.0
    for p in me.polygons:
        pts = [uvl.data[li].uv for li in p.loop_indices]
        a = 0.0
        for i in range(len(pts)):
            x1, y1 = pts[i].x, pts[i].y
            x2, y2 = pts[(i + 1) % len(pts)].x, pts[(i + 1) % len(pts)].y
            a += x1 * y2 - x2 * y1
        auv = abs(a) / 2.0
        uv_total += auv
        if p.area > 1e-12 and auv > 1e-15:
            ratios.append(auv / p.area)
    ratios.sort()
    n = len(ratios)
    if n == 0:
        return None
    med = ratios[n // 2]
    return {
        "faces": len(me.polygons),
        "islands": count_islands(obj),
        "uv_area": round(uv_total, 5),
        "stretch_p10": round(ratios[n // 10] / med, 3),
        "stretch_p50": 1.0,
        "stretch_p90": round(ratios[n * 9 // 10] / med, 3),
        "stretch_p99": round(ratios[n * 99 // 100] / med, 3),
    }


def save_layout(obj, path):
    me = obj.data
    uvl = me.uv_layers.active
    buf = bytearray(TEX * TEX)
    for p in me.polygons:
        n = len(p.loop_indices)
        cu = sum(uvl.data[li].uv.x for li in p.loop_indices) / n
        cv = sum(uvl.data[li].uv.y for li in p.loop_indices) / n
        x = min(TEX - 1, max(0, int(cu * (TEX - 1))))
        y = min(TEX - 1, max(0, int(cv * (TEX - 1))))
        buf[y * TEX + x] = 255
    scan = bytearray()
    for y in range(TEX):
        scan.append(0)
        scan += buf[y * TEX:(y + 1) * TEX]

    def ck(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += ck(b"IHDR", struct.pack(">IIBBBBB", TEX, TEX, 8, 0, 0, 0, 0))
    png += ck(b"IDAT", zlib.compress(bytes(scan), 6))
    png += ck(b"IEND", b"")
    open(path, "wb").write(png)


# ==================== 主流程 ====================
results = {}
t_all = time.time()

for name, ratio, mode, param in METHODS:
    print("=" * 56)
    print("方法: %s（简化 %d%%）" % (name, round(ratio * 100)))
    t0 = time.time()
    try:
        body = build_base(ratio)
        build_t = time.time() - t0
        print("  构建用时 %.1fs（%d 面）" % (build_t, len(body.data.polygons)))

        clear_uv(body)
        t1 = time.time()
        if mode == "smart":
            apply_smart(body, param)
        else:
            apply_unwrap(body, param)
        uv_t = time.time() - t1
        print("  UV 生成用时 %.1fs" % uv_t)

        st = compute_stats(body)
        st["build_s"] = round(build_t, 1)
        st["uv_s"] = round(uv_t, 1)
        st["ratio"] = ratio
        st["mode"] = mode
        st["param"] = param
        results[name] = st

        save_layout(body, os.path.join(OUT, "layout_%s.png" % name))
        print("  岛数 %d | UV 面积 %.4f | 畸变 p10/p90 = %.2f / %.2f" %
              (st["islands"], st["uv_area"], st["stretch_p10"], st["stretch_p90"]))
    except Exception as e:
        print("  !! 失败: %s" % e)
        results[name] = {"error": str(e)}

with open(os.path.join(OUT, "uv_compare.json"), "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print()
print("=" * 56)
print("汇总（总用时 %.0fs）" % (time.time() - t_all))
print("%-14s %8s %10s %12s %16s" % ("方法", "面数", "岛数", "UV面积", "畸变p10/p90"))
for name, st in results.items():
    if "error" in st:
        print("%-14s  失败: %s" % (name, st["error"][:40]))
    else:
        print("%-14s %8d %10d %12.4f %7.2f / %-6.2f" %
              (name, st["faces"], st["islands"], st["uv_area"],
               st["stretch_p10"], st["stretch_p90"]))
print()
print("产出: %s" % OUT)
