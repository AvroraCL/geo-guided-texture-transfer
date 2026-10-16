# -*- coding: utf-8 -*-
"""
SPM 实验 · 投影烘焙（两视图：top + left）

模式
    SPM_MODE=base   原模型 M：排除挂载/起落架；按材质分文件输出；生成 views.json
    SPM_MODE=proxy  代理网格 M′：单张输出；读 views.json（先跑 base 模式生成）

设计图内容 = 视图坐标编码场：
    R = 视图 u × 255    G = 视图 v × 255    B = 视图编号（100 = top, 200 = left）
    无值 = (0,0,0)

可见性
    面级：面法线背向相机 → 剔除；否则从面中心沿视线投射射线，第一个交点必须是该面自身。
    多视图重叠时按固定优先级选择（top 先于 left），两个模式使用相同规则。

产出
    base/uv_<材质>.png        基准坐标场
    base/mask_<材质>.png      有效性掩码
    base/stats_base.json
    proxy/uv_proxy.png        代理坐标场
    proxy/mask_proxy.png
    proxy/stats_proxy.json
    views.json                相机参数（权威来源，两模式共用）
"""

import bpy
import os
import json
import re
import zlib
import struct
import time
from array import array
from mathutils import Vector

MODE = os.environ.get("SPM_MODE", "base")
OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp05_spm"
TEX = 1024
EPS = 1e-4

EXCLUDE_KEYS = ["aim_9l_sidewinder", "aim_120a_missile", "drop_tank",
                "pylon", "launcher_aim9", "gear_", "wheel_"]

# 视图定义：相机方位（从中心指向相机）；span 取用的包围盒轴（与 exp01 一致）
VIEW_DEFS = [("top",  Vector((0.0, 0.0, 1.0)),  (0, 1)),
             ("left", Vector((-1.0, 0.0, 0.0)), (1, 2))]
VIEW_ID = {"top": 100, "left": 200}

if MODE == "base":
    SRC = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"
    OUTDIR = os.path.join(OUT, "base")
else:
    SRC = os.path.join(OUT, os.environ.get("SPM_PROXY", "proxy_25.obj"))
    OUTDIR = os.path.join(OUT, os.environ.get("SPM_OUTSUB", "proxy"))
os.makedirs(OUTDIR, exist_ok=True)

t_all = time.time()
print("=" * 64)
print("SPM 投影烘焙 [%s]" % MODE)
print("源: %s" % SRC)
print("=" * 64)

bpy.ops.wm.read_factory_settings(use_empty=True)
t0 = time.time()
bpy.ops.wm.obj_import(filepath=SRC)
SCENE = bpy.context.scene
print("导入用时 %.1fs" % (time.time() - t0))

# ---- 1. 修正法线 ----
nfix = 0
for obj in SCENE.objects:
    if obj.type != 'MESH':
        continue
    import bmesh
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

# ---- 2. 收集对象与面 ----
objs = [o for o in SCENE.objects if o.type == 'MESH']
if MODE == "base":
    objs = [o for o in objs if not any(k in o.name for k in EXCLUDE_KEYS)]
print("对象数: %d" % len(objs))

faces = []
for obj in objs:
    me = obj.data
    mw = obj.matrix_world
    nrm = mw.to_3x3().inverted().transposed()
    uvl = me.uv_layers.active
    if uvl is None:
        continue
    mats = [m.name if m else "(none)" for m in me.materials]
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
        mn = mats[p.material_index] if p.material_index < len(mats) else "(none)"
        faces.append((obj, p.index, vs, uvs, c, n, mn))

NF = len(faces)
print("参与面数: %d" % NF)

# ---- 3. 相机参数 ----
if MODE == "base":
    pts = []
    for o in objs:
        for b in o.bound_box:
            pts.append(o.matrix_world @ Vector(b))
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    center = (lo + hi) / 2.0
    size = hi - lo
    print("本体包围盒: (%s)" % ", ".join("%.3f" % v for v in size))

    views = {}
    for vname, d, ax in VIEW_DEFS:
        span = max(size[ax[0]], size[ax[1]]) * 1.05
        dist = max(size) * 2.0
        cam_loc = center + d * dist
        look = (center - cam_loc).normalized()
        m3 = look.to_track_quat('-Z', 'Y').to_matrix()
        right = Vector(m3.col[0])
        up = Vector(m3.col[1])
        views[vname] = {
            "dir": [d.x, d.y, d.z],
            "cam_loc": [cam_loc.x, cam_loc.y, cam_loc.z],
            "right": [right.x, right.y, right.z],
            "up": [up.x, up.y, up.z],
            "span": span,
        }
        print("视图 %-5s span=%.4f  cam_dir=(%s)" %
              (vname, span, ", ".join("%.2f" % v for v in look)))

    meta = {
        "source": os.path.basename(SRC), "tex": TEX,
        "center": [center.x, center.y, center.z],
        "bbox_min": [lo.x, lo.y, lo.z], "bbox_max": [hi.x, hi.y, hi.z],
        "size": [size.x, size.y, size.z],
        "views": views,
    }
    with open(os.path.join(OUT, "views.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    print("views.json 已写出")
else:
    with open(os.path.join(OUT, "views.json"), encoding="utf-8") as f:
        meta = json.load(f)
    # 校验包围盒（防止坐标轴转换往返出错）
    pts = []
    for o in objs:
        for b in o.bound_box:
            pts.append(o.matrix_world @ Vector(b))
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    ref_lo = Vector(meta["bbox_min"])
    ref_hi = Vector(meta["bbox_max"])
    dsize = (hi - lo) - (ref_hi - ref_lo)
    print("代理包围盒: (%s)" % ", ".join("%.3f" % v for v in (hi - lo)))
    print("与基准尺寸差: (%s)" % ", ".join("%+.4f" % v for v in dsize))
    if max(abs(v) for v in dsize) > 0.5:
        print("!! 警告：尺寸差异过大，可能有坐标轴转换问题")

center = Vector(meta["center"])


def make_to_view(vname):
    vm = meta["views"][vname]
    right = Vector(vm["right"])
    up = Vector(vm["up"])
    span = vm["span"]

    def f(P):
        dd = P - center
        u = dd.dot(right) / span + 0.5
        v = dd.dot(up) / span + 0.5
        if u < 0.0 or u > 1.0 or v < 0.0 or v > 1.0:
            return None
        return (u, v)

    return f


to_views = {v[0]: make_to_view(v[0]) for v in VIEW_DEFS}

# ---- 4. 可见性（面级，固定优先级 top > left）----
dg = bpy.context.evaluated_depsgraph_get()
view_of_face = [0] * NF

for vi, (vname, d, ax) in enumerate(VIEW_DEFS):
    cam_dir = -d
    bit = vi + 1
    hits = 0
    t0 = time.time()
    for i in range(NF):
        if view_of_face[i]:
            continue
        obj, pidx, vs, uvs, c, n, mn = faces[i]
        if n.dot(cam_dir) > -1e-6:
            continue
        res = SCENE.ray_cast(dg, c + n * EPS, cam_dir)
        if res[0] and res[4] == obj and res[3] == pidx:
            view_of_face[i] = bit
            hits += 1
    print("%s 视图可见面: %d（用时 %.1fs）" % (vname, hits, time.time() - t0))

# ---- 5. 光栅化 ----
bufs = {}
masks = {}
coord_bins = {}   # f32：u,v 交错（无值 -1）
view_bins = {}    # u8：视图号（0 = 无值）


def raster_face(vs, uvs, view_id, buf, mask, cbin, vbin, tv):
    x0 = max(0, int(min(u[0] for u in uvs) * (TEX - 1)))
    x1 = min(TEX - 1, int(max(u[0] for u in uvs) * (TEX - 1)) + 1)
    y0 = max(0, int(min(u[1] for u in uvs) * (TEX - 1)))
    y1 = min(TEX - 1, int(max(u[1] for u in uvs) * (TEX - 1)) + 1)
    if x1 < x0 or y1 < y0:
        return 0

    au, av = uvs[0]
    bu, bv = uvs[1]
    cu, cv = uvs[2]
    dd = (bv - cv) * (au - cu) + (cu - bu) * (av - cv)
    if abs(dd) < 1e-12:
        return 0

    cnt = 0
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            px = x / (TEX - 1.0)
            py = y / (TEX - 1.0)
            a = ((bv - cv) * (px - cu) + (cu - bu) * (py - cv)) / dd
            b = ((cv - av) * (px - cu) + (au - cu) * (py - cv)) / dd
            g = 1.0 - a - b
            if a < -0.002 or b < -0.002 or g < -0.002:
                continue
            P = vs[0] * a + vs[1] * b + vs[2] * g
            vv = tv(P)
            if vv is None:
                continue
            k = (y * TEX + x) * 3
            buf[k] = int(vv[0] * 255.0 + 0.5)
            buf[k + 1] = int(vv[1] * 255.0 + 0.5)
            buf[k + 2] = view_id
            mask[y * TEX + x] = 1
            cbin[(y * TEX + x) * 2] = vv[0]
            cbin[(y * TEX + x) * 2 + 1] = vv[1]
            vbin[y * TEX + x] = view_id
            cnt += 1
    return cnt


t0 = time.time()
painted = 0
for i in range(NF):
    vo = view_of_face[i]
    if vo == 0:
        continue
    vname = VIEW_DEFS[vo - 1][0]
    obj, pidx, vs, uvs, c, n, mn = faces[i]
    key = mn
    if MODE == "proxy" and key in ("(none)", ""):
        key = "proxy"
    if key not in bufs:
        bufs[key] = bytearray(TEX * TEX * 3)
        masks[key] = bytearray(TEX * TEX)
        coord_bins[key] = array('f', [-1.0]) * (TEX * TEX * 2)
        view_bins[key] = bytearray(TEX * TEX)
    painted += raster_face(vs, uvs, VIEW_ID[vname], bufs[key], masks[key],
                           coord_bins[key], view_bins[key], to_views[vname])
print("已光栅化。写入纹素次数: %d（用时 %.1fs）" % (painted, time.time() - t0))


# ---- 6. 保存 ----
def save_png(path, raw, w, h, gray):
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


mat_stats = {}
for key in sorted(bufs):
    safe = re.sub(r"[^A-Za-z0-9_\-]", "_", key) or "none"
    save_png(os.path.join(OUTDIR, "uv_%s.png" % safe), bufs[key], TEX, TEX, False)
    mk = bytes(255 if v else 0 for v in masks[key])
    save_png(os.path.join(OUTDIR, "mask_%s.png" % safe), mk, TEX, TEX, True)
    with open(os.path.join(OUTDIR, "coords_%s.bin" % safe), "wb") as f:
        coord_bins[key].tofile(f)
    with open(os.path.join(OUTDIR, "views_%s.bin" % safe), "wb") as f:
        f.write(bytes(view_bins[key]))
    filled = sum(masks[key])
    mat_stats[key] = {"filled": filled, "total": TEX * TEX,
                      "ratio": round(filled / float(TEX * TEX), 4)}
    print("  %-40s 有值纹素 %8d (%.1f%%)" % (key[:40], filled, 100.0 * filled / (TEX * TEX)))

stats = {
    "mode": MODE,
    "source": os.path.basename(SRC),
    "tex": TEX,
    "faces_total": NF,
    "visible_top": sum(1 for v in view_of_face if v == 1),
    "visible_left": sum(1 for v in view_of_face if v == 2),
    "visible_any": sum(1 for v in view_of_face if v != 0),
    "materials": mat_stats,
    "blender": bpy.app.version_string,
    "total_seconds": round(time.time() - t_all, 1),
}
with open(os.path.join(OUTDIR, "stats_%s.json" % MODE), "w", encoding="utf-8") as f:
    json.dump(stats, f, indent=2, ensure_ascii=False)

print()
print("[%s] 完成。用时 %.0fs" % (MODE, time.time() - t_all))
print("  可见面: top %d / left %d / 任一 %d / 总 %d" %
      (stats["visible_top"], stats["visible_left"], stats["visible_any"], NF))
