# -*- coding: utf-8 -*-
"""
OrthoTex 实验 03（A1）：纯几何投影的跨 UV 接缝误差 —— 第一部分：投影烘焙

方法
    设计稿内容 = 视图坐标编码：R = u * 255, G = v * 255（B = 0）
    把设计稿按 front 正交视图投影到模型，烘焙成 UV 贴图。
    这样每个纹素的颜色直接记录它对应的视图坐标，
    跨接缝两侧的颜色差 = 视图坐标差 = 误差，可精确量化。

判定可见性
    从面中心沿视线投射射线，第一个交点必须是该面自身。

用法
    blender --background --factory-startup --python project.py

产出
    experiments/exp03_seam/uv_projected.png    投影结果（R/G 通道 = 视图 uv）
    experiments/exp03_seam/uv_valid.png        有效性掩码（白=有值，黑=无）
    experiments/exp03_seam/project_stats.json  统计
"""

import bpy
import os
import bmesh
import zlib
import struct
import json
from mathutils import Vector

OBJ = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"
OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp03_seam"
os.makedirs(OUT, exist_ok=True)

TEX = 1024          # UV 贴图分辨率
EPS = 1e-4

# 排除不参与涂装的部件（与 exp02 一致）
EXCLUDE = ["aim_9l_sidewinder", "aim_120a_missile", "drop_tank",
           "pylon", "launcher_aim9", "gear_"]

print("=" * 64)
print("A1 第一部分：投影烘焙（front 正交视图）")
print("=" * 64)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.obj_import(filepath=OBJ)
SCENE = bpy.context.scene

# ---- 1. 修正法线 ----
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

# ---- 2. 收集面（排除指定部件）----
faces = []
for obj in SCENE.objects:
    if obj.type != 'MESH' or obj.hide_viewport or obj.hide_get():
        continue
    if any(k in obj.name for k in EXCLUDE):
        continue
    me = obj.data
    mw = obj.matrix_world
    nrm = mw.to_3x3().inverted().transposed()
    uvl = me.uv_layers.active
    if uvl is None:
        continue
    for p in me.polygons:
        if len(p.vertices) != 3:
            continue
        vs = []
        uvs = []
        for li in p.loop_indices:
            vs.append(mw @ me.vertices[me.loops[li].vertex_index].co)
            uv = uvl.data[li].uv
            uvs.append((uv.x, uv.y))
        c = (vs[0] + vs[1] + vs[2]) / 3.0
        n = (nrm @ p.normal).normalized()
        faces.append((obj, p.index, vs, uvs, c, n, p.area))

NF = len(faces)
print("参与面数: %d" % NF)

# ---- 3. front 正交相机参数（由包围盒自动确定，排除离群对象）----
import statistics
centers = []
objs = [o for o in SCENE.objects if o.type == 'MESH'
        and not o.hide_viewport and not o.hide_get()
        and not any(k in o.name for k in EXCLUDE)]
for o in objs:
    cs = [o.matrix_world @ Vector(b) for b in o.bound_box]
    centers.append(sum(cs, Vector()) / 8.0)
med = Vector((statistics.median([c.x for c in centers]),
              statistics.median([c.y for c in centers]),
              statistics.median([c.z for c in centers])))
dists = [(c - med).length for c in centers]
thresh = max(statistics.median(dists) * 6.0, 1.0)
kept = [o for o, d in zip(objs, dists) if d <= thresh]

pts = []
for o in kept:
    for b in o.bound_box:
        pts.append(o.matrix_world @ Vector(b))
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
center = (lo + hi) / 2.0
size = hi - lo

# front：相机在 -Y，看向 +Y。视图平面 = X（横向）与 Z（纵向）
span = max(size.x, size.z) * 1.05
cam_center = center
cam_dir = Vector((0.0, 1.0, 0.0))     # 视线方向
right = Vector((1.0, 0.0, 0.0))       # 视图横轴
up = Vector((0.0, 0.0, 1.0))          # 视图纵轴

print("视图范围: %.4f   中心: (%.3f, %.3f, %.3f)" % (span, center.x, center.y, center.z))


def to_view(p):
    """三维点 -> 视图归一化坐标 (u, v)，范围 0..1；超出则返回 None"""
    d = p - cam_center
    x = d.dot(right)
    y = d.dot(up)
    u = x / span + 0.5
    v = y / span + 0.5
    if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0:
        return None
    return (u, v)


# ---- 4. 可见性（逐面一次）----
dg = bpy.context.evaluated_depsgraph_get()
visible = bytearray(NF)
for i in range(NF):
    obj, pidx, vs, uvs, c, n, a = faces[i]
    if n.dot(cam_dir) > -1e-6:      # 背面
        continue
    res = SCENE.ray_cast(dg, c + n * EPS, cam_dir)
    if res[0] and res[4] == obj and res[3] == pidx:
        visible[i] = 1

nvis = sum(visible)
print("front 视图可见面数: %d / %d (%.1f%%)" % (nvis, NF, 100.0 * nvis / NF))

# ---- 5. 光栅化 UV 三角形，写入视图坐标 ----
buf = bytearray(TEX * TEX * 3)      # 0 = 无值
mask = bytearray(TEX * TEX)         # 1 = 有值

def raster_face(vs, uvs, valid):
    x0 = max(0, int(min(u[0] for u in uvs) * (TEX - 1)))
    x1 = min(TEX - 1, int(max(u[0] for u in uvs) * (TEX - 1)) + 1)
    y0 = max(0, int(min(u[1] for u in uvs) * (TEX - 1)))
    y1 = min(TEX - 1, int(max(u[1] for u in uvs) * (TEX - 1)) + 1)
    if x1 < x0 or y1 < y0:
        return 0

    au, av = uvs[0]
    bu, bv = uvs[1]
    cu, cv = uvs[2]
    d = (bv - cv) * (au - cu) + (cu - bu) * (av - cv)
    if abs(d) < 1e-12:
        return 0

    cnt = 0
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            px = x / (TEX - 1.0)
            py = y / (TEX - 1.0)
            a = ((bv - cv) * (px - cu) + (cu - bu) * (py - cv)) / d
            b = ((cv - av) * (px - cu) + (au - cu) * (py - cv)) / d
            g = 1.0 - a - b
            if a < -0.002 or b < -0.002 or g < -0.002:
                continue
            # 重心插值三维位置
            P = vs[0] * a + vs[1] * b + vs[2] * g
            if valid:
                vv = to_view(P)
                if vv is None:
                    continue
                k = (y * TEX + x) * 3
                buf[k] = int(vv[0] * 255.0 + 0.5)
                buf[k + 1] = int(vv[1] * 255.0 + 0.5)
                buf[k + 2] = 0
                mask[y * TEX + x] = 1
            cnt += 1
    return cnt


painted = 0
for i in range(NF):
    obj, pidx, vs, uvs, c, n, a = faces[i]
    painted += raster_face(vs, uvs, visible[i])

print("已光栅化。写入纹素次数: %d" % painted)


def save_png(path, raw_bytes, w, h, gray=False):
    raw = bytearray()
    ch = 1 if gray else 3
    stride = w * ch
    for y in range(h):
        raw.append(0)
        raw += raw_bytes[y * stride:(y + 1) * stride]

    def ck(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ct = 0 if gray else 2
    png = b"\x89PNG\r\n\x1a\n"
    png += ck(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ct, 0, 0, 0))
    png += ck(b"IDAT", zlib.compress(bytes(raw), 6))
    png += ck(b"IEND", b"")
    open(path, "wb").write(png)


save_png(os.path.join(OUT, "uv_projected.png"), buf, TEX, TEX)
mb = bytes(255 if m else 0 for m in mask)
save_png(os.path.join(OUT, "uv_valid.png"), mb, TEX, TEX, gray=True)

with open(os.path.join(OUT, "project_stats.json"), "w", encoding="utf-8") as f:
    json.dump({
        "tex": TEX, "faces": NF, "visible_faces": nvis,
        "span": span, "center": [center.x, center.y, center.z],
        "mask_filled": sum(mask), "mask_total": TEX * TEX,
    }, f, indent=2)

print()
print("已输出:")
print("  uv_projected.png  (R=视图u, G=视图v, 黑=无值)")
print("  uv_valid.png      (白=有值, 黑=无)")
print("  project_stats.json")
print("掩码覆盖率: %.2f%%" % (100.0 * sum(mask) / (TEX * TEX)))
