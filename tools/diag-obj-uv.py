#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OrthoTex 素材诊断：直接解析 Wavefront OBJ，输出 UV 结构报告。

用途：A1／A2 实验的前置检查。判断模型是否适合作为跨 UV 接缝的测量样本。
不依赖 Blender，只用标准库。

用法：
    python tools/diag-obj-uv.py path/to/model.obj

输出：
    - 几何统计（顶点／UV／三角面／材质）
    - 边分类（同材质 UV 连续／断开、跨材质、几何边界、非流形）
    - UV 岛数量
    - 分材质明细（面数、岛数、UV 面积、UV 包围盒、越界面数）
    - 越界的 UV 纵向分布（判断是多图块排布还是零星瑕疵）
"""

import io
import os
import sys
import time
from collections import defaultdict, Counter

TOL = 1e-6


def load(path):
    uvs, faces, mats, mat_of_face = [], [], [], []
    cur = -1
    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("vt "):
                p = line.split()
                if len(p) >= 3:
                    uvs.append((float(p[1]), float(p[2])))
            elif line.startswith("usemtl"):
                nm = line.split(None, 1)[1].strip() if len(line.split(None, 1)) > 1 else "?"
                if nm not in mats:
                    mats.append(nm)
                cur = mats.index(nm)
            elif line.startswith("f "):
                p = line.split()
                tri = []
                for tok in p[1:4]:
                    q = tok.split("/")
                    if not q[0]:
                        continue
                    tri.append((int(q[0]), int(q[1]) if len(q) > 1 and q[1] else 0))
                if len(tri) == 3:
                    faces.append(tri)
                    mat_of_face.append(cur)
    return uvs, faces, mats, mat_of_face


def uv_at(uvs, vt):
    return uvs[vt - 1] if 1 <= vt <= len(uvs) else None


def face_uv_on_vert(faces, uvs, fi, v):
    for vv, vt in faces[fi]:
        if vv == v:
            return uv_at(uvs, vt)
    return None


def same_uv(a, b):
    return a is not None and b is not None and \
        abs(a[0] - b[0]) < TOL and abs(a[1] - b[1]) < TOL


def edge_map(faces):
    edges = defaultdict(list)
    for fi, tri in enumerate(faces):
        for i in range(3):
            a, b = tri[i], tri[(i + 1) % 3]
            k = (a[0], b[0]) if a[0] < b[0] else (b[0], a[0])
            edges[k].append(fi)
    return edges


def analyse(path):
    t0 = time.time()
    uvs, faces, mats, mof = load(path)
    print("读取 %.1fs  面=%d  UV=%d  材质=%d" % (time.time() - t0, len(faces), len(uvs), len(mats)))

    edges = edge_map(faces)
    cont = seam = cross = boundary = nonmani = 0
    for k, fl in edges.items():
        if len(fl) == 1:
            boundary += 1
            continue
        if len(fl) > 2:
            nonmani += 1
            continue
        f1, f2 = fl
        if mof[f1] != mof[f2]:
            cross += 1
            continue
        va, vb = k
        a1 = face_uv_on_vert(faces, uvs, f1, va)
        b1 = face_uv_on_vert(faces, uvs, f1, vb)
        a2 = face_uv_on_vert(faces, uvs, f2, va)
        b2 = face_uv_on_vert(faces, uvs, f2, vb)
        if same_uv(a1, a2) and same_uv(b1, b2):
            cont += 1
        else:
            seam += 1

    # 全局 UV 岛
    par = list(range(len(faces)))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    for k, fl in edges.items():
        if len(fl) != 2:
            continue
        f1, f2 = fl
        if mof[f1] != mof[f2]:
            continue
        va, vb = k
        if same_uv(face_uv_on_vert(faces, uvs, f1, va), face_uv_on_vert(faces, uvs, f2, va)) and \
           same_uv(face_uv_on_vert(faces, uvs, f1, vb), face_uv_on_vert(faces, uvs, f2, vb)):
            r1, r2 = find(f1), find(f2)
            if r1 != r2:
                par[r1] = r2

    islands = len({find(i) for i in range(len(faces))})
    seam_faces = set()
    for k, fl in edges.items():
        if len(fl) == 2 and mof[fl[0]] == mof[fl[1]]:
            va, vb = k
            f1, f2 = fl
            if not (same_uv(face_uv_on_vert(faces, uvs, f1, va), face_uv_on_vert(faces, uvs, f2, va)) and
                    same_uv(face_uv_on_vert(faces, uvs, f1, vb), face_uv_on_vert(faces, uvs, f2, vb))):
                seam_faces.add(f1)
                seam_faces.add(f2)

    print()
    print("=" * 62)
    print("边分类")
    print("=" * 62)
    print("  同材质 - UV 连续 : %d" % cont)
    print("  同材质 - UV 断开 : %d   <-- 真正的 UV 接缝" % seam)
    print("  跨材质           : %d" % cross)
    print("  几何边界边(单面) : %d" % boundary)
    print("  非流形边(>2面)   : %d" % nonmani)
    print()
    print("UV 岛数量          : %d" % islands)
    print("涉及接缝的面       : %d / %d (%.1f%%)"
          % (len(seam_faces), len(faces), 100.0 * len(seam_faces) / max(len(faces), 1)))

    # 分材质
    by_mat = defaultdict(list)
    for fi, m in enumerate(mof):
        by_mat[m].append(fi)

    print()
    print("=" * 78)
    print("%-32s %7s %7s %9s %10s %s" % ("材质", "面数", "岛数", "UV面积", "越界面", "UV 包围盒"))
    print("=" * 78)

    total_area = 0.0
    for m, fl in sorted(by_mat.items(), key=lambda kv: -len(kv[1])):
        local = {fi: i for i, fi in enumerate(fl)}
        p2 = list(range(len(fl)))

        def f2(x):
            while p2[x] != x:
                p2[x] = p2[p2[x]]
                x = p2[x]
            return x

        for k, el in edges.items():
            if len(el) != 2 or el[0] not in local or el[1] not in local:
                continue
            va, vb = k
            g1, g2 = el
            if same_uv(face_uv_on_vert(faces, uvs, g1, va), face_uv_on_vert(faces, uvs, g2, va)) and \
               same_uv(face_uv_on_vert(faces, uvs, g1, vb), face_uv_on_vert(faces, uvs, g2, vb)):
                r1, r2 = f2(local[g1]), f2(local[g2])
                if r1 != r2:
                    p2[r1] = r2
        isl = len({f2(i) for i in range(len(fl))})

        area = 0.0
        bad = 0
        umin = vmin = 1e18
        umax = vmax = -1e18
        for fi in fl:
            pts = []
            oob = False
            for _, vt in faces[fi]:
                uv = uv_at(uvs, vt)
                if uv is None:
                    oob = True
                    continue
                pts.append(uv)
                umin = min(umin, uv[0]); umax = max(umax, uv[0])
                vmin = min(vmin, uv[1]); vmax = max(vmax, uv[1])
                if uv[0] < -0.001 or uv[0] > 1.001 or uv[1] < -0.001 or uv[1] > 1.001:
                    oob = True
            if oob:
                bad += 1
            if len(pts) == 3:
                (u1, v1), (u2, v2), (u3, v3) = pts
                area += abs((u2 - u1) * (v3 - v1) - (u3 - u1) * (v2 - v1)) / 2.0
        total_area += area
        print("%-32s %7d %7d %9.4f %10d   u[%.3f,%.3f] v[%.3f,%.3f]"
              % (mats[m][:32], len(fl), isl, area, bad, umin, umax, vmin, vmax))

    print("=" * 78)
    print("合计 UV 面积: %.4f" % total_area)
    print("注：若合计明显大于 1，通常是多材质各占独立 UV 空间，而非重叠。")
    print("耗时 %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    p = sys.argv[1]
    if not os.path.exists(p):
        print("文件不存在:", p)
        sys.exit(1)
    analyse(p)
