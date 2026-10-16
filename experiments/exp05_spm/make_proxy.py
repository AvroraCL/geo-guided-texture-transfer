# -*- coding: utf-8 -*-
"""
SPM 实验 阶段 1：生成代理网格 M′

流程
    导入 F16XL.obj → 修正法线 → 筛选飞机本体（排除挂载/起落架）
    → 合并为单对象 → Decimate（几何简化）→ Smart UV Project（重新展开 UV）

用法
    SPM_RATIO=0.25 blender --background --factory-startup --python make_proxy.py
    （SPM_RATIO=1.0 表示不简化、只重新展开 UV —— 用于分离「UV 重排」与「几何简化」）

产出
    exp05_spm/proxy_<NN>.obj            代理网格
    exp05_spm/proxy_<NN>_stats.json     面数 / UV 岛数 / 包围盒 / 用时
    exp05_spm/proxy_<NN>_uv.png         UV 布局图（每个三角面画一个重心点）
"""

import bpy
import os
import bmesh
import json
import zlib
import struct
import time
import math
from mathutils import Vector

OBJ = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"
OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp05_spm"
os.makedirs(OUT, exist_ok=True)

RATIO = float(os.environ.get("SPM_RATIO", "0.25"))
TAG = os.environ.get("SPM_TAG") or ("%02d" % round(RATIO * 100))
SKIP_UV = os.environ.get("SPM_SKIP_UV", "0") == "1"   # 保留原 UV（校准测试用）
KEEP_MAT = os.environ.get("SPM_KEEP_MAT", "0") == "1"  # 导出材质（校准测试用）
# UV 生成方式：smart（Smart UV Project，exp05 旧配置）/ unwrapNN（硬边标缝 + Angle-Based Unwrap）
# exp06 对比结论：更激进的简化率 + unwrap60 是产出"简单 UV"的正道
UV_MODE = os.environ.get("SPM_UV_MODE", "unwrap60")

# wheel_ 与 gear_ 同属起落架系统，且其坐标数据躺在 y≈-28 的装配前位置，
# 会把包围盒撑到 31.7（正确值应为 17.7），必须排除
EXCLUDE_KEYS = ["aim_9l_sidewinder", "aim_120a_missile", "drop_tank",
                "pylon", "launcher_aim9", "gear_", "wheel_"]

UV_ANGLE = float(os.environ.get("SPM_UV_ANGLE", "66.0"))
UV_MARGIN = float(os.environ.get("SPM_UV_MARGIN", "0.001"))

t_all = time.time()
print("=" * 64)
print("SPM 阶段 1：生成代理网格（简化率 %s%%）" % TAG)
print("=" * 64)

bpy.ops.wm.read_factory_settings(use_empty=True)
t0 = time.time()
bpy.ops.wm.obj_import(filepath=OBJ)
print("导入用时 %.1fs" % (time.time() - t0))
SCENE = bpy.context.scene

# ---- 1. 修正法线（与 exp02/03 一致：按有符号体积判断朝向）----
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
print("法线修正: %d 个对象" % nfix)

# ---- 2. 筛选飞机本体 ----
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

if not keep:
    raise RuntimeError("没有可用的飞机本体对象")

print("本体对象数: %d（排除 %d）" % (len(keep), 0))

# ---- 3. 合并为单对象 ----
bpy.ops.object.select_all(action='DESELECT')
for o in keep:
    o.select_set(True)
bpy.context.view_layer.objects.active = keep[0]
bpy.ops.object.join()
body = bpy.context.view_layer.objects.active
body.name = "SPM_proxy_%s" % TAG
print("合并完成: %s" % body.name)

me = body.data
tris0 = sum(len(p.vertices) - 2 for p in me.polygons)
print("原始: 面 %d / 三角 %d" % (len(me.polygons), tris0))


def bbox_of(o):
    pts = [o.matrix_world @ Vector(b) for b in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


lo0, hi0 = bbox_of(body)
size0 = hi0 - lo0
print("原始包围盒: (%s)" % ", ".join("%.3f" % v for v in size0))

# ---- 4. Decimate ----
t0 = time.time()
if RATIO < 0.999:
    mod = body.modifiers.new(name="spm_dec", type='DECIMATE')
    mod.ratio = RATIO
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.modifier_apply(modifier="spm_dec")
    me = body.data
print("简化用时 %.1fs" % (time.time() - t0))

tris1 = sum(len(p.vertices) - 2 for p in me.polygons)
print("简化后: 面 %d / 三角 %d  (目标 %s%%)" % (len(me.polygons), tris1, TAG))

lo1, hi1 = bbox_of(body)
size1 = hi1 - lo1
print("简化后包围盒: (%s)" % ", ".join("%.3f" % v for v in size1))
print("包围盒变化: (%s)" % ", ".join("%+.4f" % (size1[i] - size0[i]) for i in range(3)))

# ---- 5. UV 生成 ----
t0 = time.time()
if SKIP_UV:
    print("跳过 UV 展开（保留原 UV）")
elif UV_MODE == "smart":
    bpy.context.view_layer.objects.active = body
    body.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=UV_ANGLE, island_margin=UV_MARGIN)
    bpy.ops.object.mode_set(mode='OBJECT')
    print("UV 展开用时 %.1fs（smart, angle=%s margin=%s）" % (time.time() - t0, UV_ANGLE, UV_MARGIN))
else:
    sharp_deg = float(UV_MODE.replace("unwrap", "") or 60.0)
    # 清空旧 UV 层：实测 unwrap 受现有 UV 数据影响——
    # 保留旧 UV 时展开面积 0.289 / 重叠率 5.4%；清空后 0.434 / 3.2%（同一网格同参数）
    pme_data = body.data
    while len(pme_data.uv_layers) > 0:
        pme_data.uv_layers.remove(pme_data.uv_layers[0])
    pme_data.uv_layers.new(name="UVMap")
    bpy.context.view_layer.objects.active = body
    body.select_set(True)
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bpy.ops.mesh.select_mode(type='EDGE')
    bpy.ops.mesh.mark_seam(clear=True)
    bpy.ops.mesh.edges_select_sharp(sharpness=math.radians(sharp_deg))
    bpy.ops.mesh.mark_seam(clear=False)
    bpy.ops.mesh.select_mode(type='FACE')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.unwrap(method='ANGLE_BASED', margin=UV_MARGIN)
    bpy.ops.uv.select_all(action='SELECT')
    bpy.ops.uv.pack_islands(margin=UV_MARGIN)
    bpy.ops.object.mode_set(mode='OBJECT')
    print("UV 展开用时 %.1fs（unwrap %.0f°, margin=%s, 已清空旧 UV）" % (time.time() - t0, sharp_deg, UV_MARGIN))

# ---- 6. 统计 UV 岛与面积 ----
me = body.data
uvl = me.uv_layers.active
if uvl is None:
    raise RuntimeError("UV 展开失败：没有 UV 层")

bm = bmesh.new()
bm.from_mesh(me)
bm.faces.ensure_lookup_table()
uvl_b = bm.loops.layers.uv.active

nfaces = len(bm.faces)
parent = list(range(nfaces))


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def uv_of(face, vert):
    for l in face.loops:
        if l.vert == vert:
            return (round(l[uvl_b].uv.x, 6), round(l[uvl_b].uv.y, 6))
    return None


idx = {f.index: i for i, f in enumerate(bm.faces)}
for e in bm.edges:
    if len(e.link_faces) != 2:
        continue
    f1, f2 = e.link_faces
    va, vb = e.verts
    a1 = uv_of(f1, va); b1 = uv_of(f1, vb)
    a2 = uv_of(f2, va); b2 = uv_of(f2, vb)
    if None in (a1, b1, a2, b2):
        continue
    same = (a1 == a2 and b1 == b2) or (a1 == b2 and b1 == a2)
    if same:
        r1, r2 = find(idx[f1.index]), find(idx[f2.index])
        if r1 != r2:
            parent[r1] = r2

n_islands = len({find(i) for i in range(nfaces)})


def face_area(l):
    pts = [lo[uvl_b].uv for lo in l]
    a = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i].x, pts[i].y
        x2, y2 = pts[(i + 1) % len(pts)].x, pts[(i + 1) % len(pts)].y
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


uv_area = sum(face_area(f.loops) for f in bm.faces)
print("UV 岛数量: %d" % n_islands)
print("UV 面积占比: %.4f" % uv_area)

us = [lo[uvl_b].uv.x for f in bm.faces for lo in f.loops]
vs = [lo[uvl_b].uv.y for f in bm.faces for lo in f.loops]
print("UV 包围盒: u[%.3f, %.3f] v[%.3f, %.3f]" % (min(us), max(us), min(vs), max(vs)))

# ---- 7. UV 布局图（每个三角面一个重心点）----
L = 1024
buf = bytearray(L * L)
for f in bm.faces:
    n = len(f.loops)
    cu = sum(lo[uvl_b].uv.x for lo in f.loops) / n
    cv = sum(lo[uvl_b].uv.y for lo in f.loops) / n
    x = min(L - 1, max(0, int(cu * (L - 1))))
    y = min(L - 1, max(0, int(cv * (L - 1))))
    buf[y * L + x] = 255


def save_png(path, raw, w, h, gray=True):
    scan = bytearray()
    ch = 1 if gray else 3
    stride = w * ch
    for y in range(h):
        scan.append(0)
        scan += raw[y * stride:(y + 1) * stride]

    def ck(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += ck(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0 if gray else 2, 0, 0, 0))
    png += ck(b"IDAT", zlib.compress(bytes(scan), 6))
    png += ck(b"IEND", b"")
    open(path, "wb").write(png)


uv_png = os.path.join(OUT, "proxy_%s_uv.png" % TAG)
save_png(uv_png, buf, L, L, gray=True)

bm.free()

# ---- 8. 导出代理网格 ----
proxy_obj = os.path.join(OUT, "proxy_%s.obj" % TAG)
bpy.ops.wm.obj_export(
    filepath=proxy_obj,
    export_uv=True,
    export_normals=True,
    export_materials=KEEP_MAT,
)
print("已导出: %s" % proxy_obj)

stats = {
    "ratio": RATIO,
    "faces_before": len(me.polygons),
    "tris_before": tris0,
    "tris_after": tris1,
    "bbox_before": [size0.x, size0.y, size0.z],
    "bbox_after": [size1.x, size1.y, size1.z],
    "uv_islands": n_islands,
    "uv_area": round(uv_area, 5),
    "blender": bpy.app.version_string,
    "total_seconds": round(time.time() - t_all, 1),
}
with open(os.path.join(OUT, "proxy_%s_stats.json" % TAG), "w", encoding="utf-8") as f:
    json.dump(stats, f, indent=2, ensure_ascii=False)

print()
print("阶段 1 完成。总用时 %.1fs" % (time.time() - t_all))
print("  三角面: %d → %d" % (tris0, tris1))
print("  UV 岛: %d → %d" % (10616, n_islands))
print("  产出: proxy_%s.obj / proxy_%s_stats.json / proxy_%s_uv.png" % (TAG, TAG, TAG))
