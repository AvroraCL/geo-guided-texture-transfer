# -*- coding: utf-8 -*-
"""
SPM 实验 阶段 3：重采样（M′ 贴图 → M 原 UV）

流程
    1. 导入原模型 M（排除挂载/起落架，修正法线）与代理网格 M′（proxy_*.obj）
    2. 对 M 的每个 UV 纹素：
         纹素 → 3D 点 P（重心插值）
         P → 在 M′ 上做最近点查询 → Q（记录距离与法线）
         Q → 在 M′ 面内插值 UV → (u′, v′)
         读 M′ 贴图（坐标场）→ 写入 M 的 SPM 贴图
    3. 逐纹素记录最近点距离（float32）与法线夹角余弦（int8）

用法
    SPM_MODE=proxy 先用 project.py 生成 proxy/uv_proxy.png 等
    SPM_LIMIT=5000 可限制处理面数（调试用，默认 0 = 全量）

产出
    spm/uv_<材质>.png        SPM 坐标场
    spm/mask_<材质>.png      有效性掩码
    spm/dist_<材质>.bin      float32（无值处 -1）
    spm/cos_<材质>.bin       int8 = cos×127（无值处 -128）
    resample_stats.json
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

OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp05_spm"
M_SRC = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/F16XL.obj"
PROXY_SRC = os.path.join(OUT, os.environ.get("SPM_PROXY", "proxy_25.obj"))
PROXY_DIR = os.path.join(OUT, os.environ.get("SPM_PROXYDIR", "proxy"))
SPM_DIR = os.path.join(OUT, os.environ.get("SPM_OUTDIR", "spm"))
LABEL = os.environ.get("SPM_LABEL", "25")
os.makedirs(SPM_DIR, exist_ok=True)

TEX = 1024
LIMIT = int(os.environ.get("SPM_LIMIT", "0"))

EXCLUDE_KEYS = ["aim_9l_sidewinder", "aim_120a_missile", "drop_tank",
                "pylon", "launcher_aim9", "gear_", "wheel_"]

t_all = time.time()
print("=" * 64)
print("SPM 阶段 3：重采样（最近点）")
print("M  = %s" % os.path.basename(M_SRC))
print("M' = %s" % os.path.basename(PROXY_SRC))
print("=" * 64)


# ---------- 工具：读自产 PNG ----------
def read_png(path):
    data = open(path, "rb").read()
    pos = 8
    idat = b""
    w = h = ct = 0
    while pos < len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        chunk = data[pos + 8:pos + 8 + ln]
        if tag == b"IHDR":
            w, h, depth, ct = struct.unpack(">IIBB", chunk[:10])
        elif tag == b"IDAT":
            idat += chunk
        pos += 12 + ln
    raw = zlib.decompress(idat)
    ch = 3 if ct == 2 else 1
    stride = w * ch
    out = bytearray(h * stride)
    for y in range(h):
        off = y * (stride + 1)
        f = raw[off]
        if f != 0:
            raise RuntimeError("不支持的 PNG filter: %d" % f)
        out[y * stride:(y + 1) * stride] = raw[off + 1:off + 1 + stride]
    return w, h, ch, out


# ---------- 读 M′ 坐标场（float32，支持多材质组） ----------
pcoord_sets = {}
pview_sets = {}
for fn in sorted(os.listdir(PROXY_DIR)):
    if fn.startswith("coords_") and fn.endswith(".bin"):
        k = fn[len("coords_"):-4]
        arr = array('f')
        with open(os.path.join(PROXY_DIR, fn), "rb") as f:
            arr.fromfile(f, TEX * TEX * 2)
        pcoord_sets[k] = arr
    elif fn.startswith("views_") and fn.endswith(".bin"):
        k = fn[len("views_"):-4]
        with open(os.path.join(PROXY_DIR, fn), "rb") as f:
            pview_sets[k] = f.read()
assert pcoord_sets, "未找到 M′ 坐标场（%s）" % PROXY_DIR
assert set(pcoord_sets) == set(pview_sets), "coords/views 组不一致"
single_key = next(iter(pcoord_sets)) if len(pcoord_sets) == 1 else None
print("M′ 坐标场: %d 组 (%s)" % (len(pcoord_sets),
      single_key if single_key else ", ".join(sorted(pcoord_sets))))


def sample_nearest(u, v, key):
    pcoord = pcoord_sets[key]
    pview = pview_sets[key]
    x = int(u * (TEX - 1) + 0.5)
    y = int(v * (TEX - 1) + 0.5)
    if x < 0 or x >= TEX or y < 0 or y >= TEX:
        return None
    k = y * TEX + x
    if not pview[k]:
        return None
    return (pcoord[k * 2], pcoord[k * 2 + 1], pview[k])


def sample_proxy(u, v, key):
    """双线性采样；跨视图/跨岛/含无值邻域时退回最近邻"""
    pcoord = pcoord_sets[key]
    pview = pview_sets[key]
    fx = u * (TEX - 1)
    fy = v * (TEX - 1)
    x0 = int(fx)
    y0 = int(fy)
    if x0 < 0 or y0 < 0 or x0 >= TEX - 1 or y0 >= TEX - 1:
        return sample_nearest(u, v, key)
    tx = fx - x0
    ty = fy - y0
    k00 = y0 * TEX + x0
    k10 = k00 + 1
    k01 = k00 + TEX
    k11 = k01 + 1
    v00 = pview[k00]; v10 = pview[k10]; v01 = pview[k01]; v11 = pview[k11]
    if not (v00 and v10 and v01 and v11) or not (v00 == v10 == v01 == v11):
        return sample_nearest(u, v, key)
    u00 = pcoord[k00 * 2]; u10 = pcoord[k10 * 2]
    u01 = pcoord[k01 * 2]; u11 = pcoord[k11 * 2]
    if max(u00, u10, u01, u11) - min(u00, u10, u01, u11) > 0.05:
        return sample_nearest(u, v, key)
    w00 = pcoord[k00 * 2 + 1]; w10 = pcoord[k10 * 2 + 1]
    w01 = pcoord[k01 * 2 + 1]; w11 = pcoord[k11 * 2 + 1]
    if max(w00, w10, w01, w11) - min(w00, w10, w01, w11) > 0.05:
        return sample_nearest(u, v, key)
    uu = (u00 * (1 - tx) + u10 * tx) * (1 - ty) + (u01 * (1 - tx) + u11 * tx) * ty
    vv = (w00 * (1 - tx) + w10 * tx) * (1 - ty) + (w01 * (1 - tx) + w11 * tx) * ty
    return (uu, vv, v00)


# ---------- 导入 M′，构建 BVH ----------
bpy.ops.wm.read_factory_settings(use_empty=True)
t0 = time.time()
bpy.ops.wm.obj_import(filepath=PROXY_SRC)
print("导入 M′ 用时 %.1fs" % (time.time() - t0))

from mathutils.bvhtree import BVHTree

proxy_obj = [o for o in bpy.context.scene.objects if o.type == 'MESH'][0]
pme = proxy_obj.data
pmw = proxy_obj.matrix_world
pverts = [pmw @ v.co for v in pme.vertices]
pluv = pme.uv_layers.active.data

ptris = []          # (i0, i1, i2, uv0, uv1, uv2)
ptri_key = []       # 每个三角面的材质键（决定采样哪组坐标场）
pmats = [m.name if m else "(none)" for m in pme.materials]
for p in pme.polygons:
    if len(p.vertices) != 3:
        continue
    vs = list(p.vertices)
    uvs = [tuple(pluv[li].uv) for li in p.loop_indices]
    ptris.append((vs[0], vs[1], vs[2], uvs[0], uvs[1], uvs[2]))
    mk = pmats[p.material_index] if p.material_index < len(pmats) else "(none)"
    if mk in ("(none)", ""):
        mk = "proxy"
    if single_key is not None:
        mk = single_key
    ptri_key.append(mk)

bvh = BVHTree.FromPolygons(pverts, [(t[0], t[1], t[2]) for t in ptris])
print("BVH 构建完成: %d 三角面" % len(ptris))

# M′ 面法线（用于夹角统计：BVH 返回的法线即可，无需预存）

# ---------- 导入 M ----------
bpy.ops.wm.read_factory_settings(use_empty=True)
t0 = time.time()
bpy.ops.wm.obj_import(filepath=M_SRC)
print("导入 M 用时 %.1fs" % (time.time() - t0))
SCENE = bpy.context.scene

# 修正法线
import bmesh
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

# 收集面（排除部件）
faces = []
for obj in SCENE.objects:
    if obj.type != 'MESH':
        continue
    if any(k in obj.name for k in EXCLUDE_KEYS):
        continue
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
        n = (nrm @ p.normal).normalized()
        mn = mats[p.material_index] if p.material_index < len(mats) else "(none)"
        faces.append((vs, uvs, n, mn))

NF = len(faces)
if LIMIT:
    faces = faces[:LIMIT]
    print("!! 调试模式：只处理前 %d 个面" % LIMIT)
print("参与面数: %d" % len(faces))

# ---------- 缓冲区 ----------
bufs = {}     # 材质 -> bytearray(TEX*TEX*3)，8bit 展示用
masks = {}    # 材质 -> bytearray(TEX*TEX)
dists = {}    # 材质 -> array('f', TEX*TEX)，无值 -1
coss = {}     # 材质 -> array('b', TEX*TEX)，无值 -128
coords_out = {}   # 材质 -> array('f', TEX*TEX*2)，u,v 交错
views_out = {}    # 材质 -> bytearray(TEX*TEX)


def get_slot(mn):
    if mn not in bufs:
        bufs[mn] = bytearray(TEX * TEX * 3)
        masks[mn] = bytearray(TEX * TEX)
        dists[mn] = array('f', [-1.0]) * (TEX * TEX)
        coss[mn] = array('b', [-128]) * (TEX * TEX)
        coords_out[mn] = array('f', [-1.0]) * (TEX * TEX * 2)
        views_out[mn] = bytearray(TEX * TEX)
    return bufs[mn], masks[mn], dists[mn], coss[mn], coords_out[mn], views_out[mn]


def bary_of(p, a, b, c):
    v0 = b - a
    v1 = c - a
    v2 = p - a
    d00 = v0.dot(v0)
    d01 = v0.dot(v1)
    d11 = v1.dot(v1)
    d20 = v2.dot(v0)
    d21 = v2.dot(v1)
    den = d00 * d11 - d01 * d01
    if abs(den) < 1e-14:
        return None
    v = (d11 * d20 - d01 * d21) / den
    w = (d00 * d21 - d01 * d20) / den
    u = 1.0 - v - w
    return (u, v, w)


t0 = time.time()
n_tri = 0
n_texel = 0
n_hit = 0
n_empty = 0     # 读 M′ 贴图时碰到无值
hist_dist = [0] * 12   # 0-0.001, 0.001-0.002, ... 0.01+, 用对数更细：见下
hist_edges = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0]

sample_done = 0
for (vs, uvs, n_face, mn) in faces:
    buf, mask, dist_a, cos_a, coords_b, views_b = get_slot(mn)
    x0 = max(0, int(min(u[0] for u in uvs) * (TEX - 1)))
    x1 = min(TEX - 1, int(max(u[0] for u in uvs) * (TEX - 1)) + 1)
    y0 = max(0, int(min(u[1] for u in uvs) * (TEX - 1)))
    y1 = min(TEX - 1, int(max(u[1] for u in uvs) * (TEX - 1)) + 1)
    if x1 < x0 or y1 < y0:
        continue
    au, av = uvs[0]
    bu, bv = uvs[1]
    cu, cv = uvs[2]
    den_uv = (bv - cv) * (au - cu) + (cu - bu) * (av - cv)
    if abs(den_uv) < 1e-12:
        continue

    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            px = x / (TEX - 1.0)
            py = y / (TEX - 1.0)
            a = ((bv - cv) * (px - cu) + (cu - bu) * (py - cv)) / den_uv
            b = ((cv - av) * (px - cu) + (au - cu) * (py - cv)) / den_uv
            g = 1.0 - a - b
            if a < -0.002 or b < -0.002 or g < -0.002:
                continue
            n_texel += 1
            P = vs[0] * a + vs[1] * b + vs[2] * g

            loc, n_loc, idx, dist = bvh.find_nearest(P)
            if idx is None:
                continue
            n_hit += 1

            i0, i1, i2, uv0, uv1, uv2 = ptris[idx]
            bc = bary_of(loc, pverts[i0], pverts[i1], pverts[i2])
            if bc is None:
                continue
            ba, bb, bg = bc
            pu = uv0[0] * ba + uv1[0] * bb + uv2[0] * bg
            pv = uv0[1] * ba + uv1[1] * bb + uv2[1] * bg

            col = sample_proxy(pu, pv, ptri_key[idx])
            k = y * TEX + x
            dist_a[k] = dist
            if n_loc is not None:
                c = n_face.dot(n_loc.normalized())
                cos_a[k] = max(-127, min(127, int(c * 127)))
            if col is None:
                n_empty += 1
                continue
            uu, vv, vid = col
            coords_b[k * 2] = uu
            coords_b[k * 2 + 1] = vv
            views_b[k] = vid
            j = k * 3
            buf[j] = int(uu * 255.0 + 0.5)
            buf[j + 1] = int(vv * 255.0 + 0.5)
            buf[j + 2] = vid
            mask[k] = 1

            # 距离直方图
            for hi, edge in enumerate(hist_edges):
                if dist < edge:
                    hist_dist[hi] += 1
                    break
            else:
                hist_dist[11] += 1

    sample_done += 1
    if sample_done % 20000 == 0:
        print("  已处理 %d / %d 面（%.1f%%，用时 %.0fs）" %
              (sample_done, len(faces), 100.0 * sample_done / len(faces), time.time() - t0))

print("光栅化+查询完成: 纹素 %d / 命中 %d / M′空值 %d（用时 %.0fs）" %
      (n_texel, n_hit, n_empty, time.time() - t0))


# ---------- 保存 ----------
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
    save_png(os.path.join(SPM_DIR, "uv_%s.png" % safe), bufs[key], TEX, TEX, False)
    save_png(os.path.join(SPM_DIR, "mask_%s.png" % safe),
             bytes(255 if v else 0 for v in masks[key]), TEX, TEX, True)
    with open(os.path.join(SPM_DIR, "coords_%s.bin" % safe), "wb") as f:
        coords_out[key].tofile(f)
    with open(os.path.join(SPM_DIR, "views_%s.bin" % safe), "wb") as f:
        f.write(bytes(views_out[key]))
    with open(os.path.join(SPM_DIR, "dist_%s.bin" % safe), "wb") as f:
        dists[key].tofile(f)
    with open(os.path.join(SPM_DIR, "cos_%s.bin" % safe), "wb") as f:
        coss[key].tofile(f)
    filled = sum(masks[key])
    mat_stats[key] = {"filled": filled, "ratio": round(filled / float(TEX * TEX), 4)}
    print("  %-40s 有值纹素 %8d (%.1f%%)" % (key[:40], filled, 100.0 * filled / (TEX * TEX)))

stats = {
    "label": LABEL,
    "proxy": os.path.basename(PROXY_SRC),
    "faces_processed": len(faces),
    "texels": n_texel,
    "hits": n_hit,
    "empty_from_proxy": n_empty,
    "dist_hist_edges": hist_edges + ["inf"],
    "dist_hist": hist_dist,
    "materials": mat_stats,
    "blender": bpy.app.version_string,
    "total_seconds": round(time.time() - t_all, 1),
}
with open(os.path.join(OUT, "resample_stats_%s.json" % LABEL), "w", encoding="utf-8") as f:
    json.dump(stats, f, indent=2, ensure_ascii=False)

print()
print("阶段 3 完成。总用时 %.0fs" % (time.time() - t_all))
print("距离分布（到 M′ 最近点）:")
for hi, edge in enumerate(hist_edges):
    print("  < %.3f : %8d" % (edge, hist_dist[hi]))
print("  >= %.3f : %8d" % (hist_edges[-1], hist_dist[11]))
