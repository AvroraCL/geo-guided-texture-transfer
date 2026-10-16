# -*- coding: utf-8 -*-
"""
SPM 实验 阶段 5：误差分析（基准 vs SPM，float32 精度）

对每个材质逐纹素比较两套坐标场（读 coords/views 的 bin 数据，非 PNG）：
    黑    = 双方都无值
    灰    = 仅基准有值（SPM 丢失）
    蓝    = 仅 SPM 有值（SPM 新增）
    黄    = 视图不一致（基准与 SPM 选了不同视图）
    绿→红 = 同视图，按误差着色（绿=0，红=大）

误差定义
    err_px = sqrt(Δu² + Δv²) × 2048
    以「设计图（2048）上错位几个像素」为单位

归因
    逐纹素记录 SPM 的最近点距离 dist 与法线夹角 cos，
    按 dist / cos 分桶统计误差，用于区分「几何近似」与「对应错误」。

产出
    analysis/error_<材质>.png    分类+误差图
    analysis_stats.json          全部统计
"""

import os
import json
import zlib
import struct
from array import array
from math import sqrt

OUT = r"F:/项目/面向复杂三维网格的几何引导式正交视图纹理转译/experiments/exp05_spm"
BASE_DIR = os.path.join(OUT, os.environ.get("SPM_BASEDIR", "base"))
SPM_DIR = os.path.join(OUT, os.environ.get("SPM_SPMDIR", "spm"))
ANA_DIR = os.path.join(OUT, os.environ.get("SPM_ANADIR", "analysis"))
LABEL = os.environ.get("SPM_LABEL", "25")
os.makedirs(ANA_DIR, exist_ok=True)

TEX = 1024
PIX_PER_VIEW = 2048.0
VIEW_NAMES = {100: "top", 200: "left"}


def read_bin_f(path, n):
    a = array('f')
    with open(path, "rb") as f:
        a.fromfile(f, n)
    return a


def save_png(path, raw, w, h):
    scan = bytearray()
    stride = w * 3
    for y in range(h):
        scan.append(0)
        scan += raw[y * stride:(y + 1) * stride]

    def ck(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += ck(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += ck(b"IDAT", zlib.compress(bytes(scan), 6))
    png += ck(b"IEND", b"")
    open(path, "wb").write(png)


# ---- 材质列表 ----
mats = sorted(fn[len("coords_"):-4] for fn in os.listdir(BASE_DIR) if fn.startswith("coords_"))
print("材质数: %d" % len(mats))

ERR_EDGES = [0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0]
DIST_EDGES = [0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01]
COS_EDGES = [0.9, 0.5, 0.0]

all_stat = {
    "both": 0, "only_base": 0, "only_spm": 0, "view_mismatch": 0,
    "err_sum_px": 0.0, "exact_zero": 0,
    "err_hist": [0] * (len(ERR_EDGES) + 1),
    "dist_bucket": {}, "cos_bucket": {},
    "border": [0, 0.0], "inner": [0, 0.0],
    "vm_pairs": {},
}

mats_stat = {}

for mat in mats:
    bcoord = read_bin_f(os.path.join(BASE_DIR, "coords_%s.bin" % mat), TEX * TEX * 2)
    scord = read_bin_f(os.path.join(SPM_DIR, "coords_%s.bin" % mat), TEX * TEX * 2)
    with open(os.path.join(BASE_DIR, "views_%s.bin" % mat), "rb") as f:
        bview = f.read()
    with open(os.path.join(SPM_DIR, "views_%s.bin" % mat), "rb") as f:
        sview = f.read()
    dists = read_bin_f(os.path.join(SPM_DIR, "dist_%s.bin" % mat), TEX * TEX)
    coss = array('b')
    with open(os.path.join(SPM_DIR, "cos_%s.bin" % mat), "rb") as f:
        coss.fromfile(f, TEX * TEX)

    err_buf = bytearray(TEX * TEX * 3)
    st = {
        "both": 0, "only_base": 0, "only_spm": 0, "view_mismatch": 0,
        "err_sum_px": 0.0, "exact_zero": 0,
        "err_hist": [0] * (len(ERR_EDGES) + 1),
        "dist_bucket": {}, "cos_bucket": {},
        "border_n": 0, "border_err": 0.0, "inner_n": 0, "inner_err": 0.0,
        "vm_pairs": {},
    }

    for k in range(TEX * TEX):
        bv = bview[k]
        sv = sview[k]
        j = k * 3
        if not bv and not sv:
            continue
        if bv and not sv:
            st["only_base"] += 1
            err_buf[j] = 96; err_buf[j + 1] = 96; err_buf[j + 2] = 96
            continue
        if not bv and sv:
            st["only_spm"] += 1
            err_buf[j] = 0; err_buf[j + 1] = 96; err_buf[j + 2] = 255
            continue

        if bv != sv:
            st["view_mismatch"] += 1
            pair = "%s>%s" % (VIEW_NAMES.get(bv, bv), VIEW_NAMES.get(sv, sv))
            st["vm_pairs"][pair] = st["vm_pairs"].get(pair, 0) + 1
            err_buf[j] = 255; err_buf[j + 1] = 200; err_buf[j + 2] = 0
            continue

        st["both"] += 1
        du = bcoord[k * 2] - scord[k * 2]
        dv = bcoord[k * 2 + 1] - scord[k * 2 + 1]
        err_px = sqrt(du * du + dv * dv) * PIX_PER_VIEW
        st["err_sum_px"] += err_px
        if err_px == 0.0:
            st["exact_zero"] += 1

        for hi, edge in enumerate(ERR_EDGES):
            if err_px < edge:
                st["err_hist"][hi] += 1
                break
        else:
            st["err_hist"][len(ERR_EDGES)] += 1

        d = dists[k]
        db = "na"
        if d >= 0:
            for edge in DIST_EDGES:
                if d < edge:
                    db = "<%g" % edge
                    break
            else:
                db = ">=%g" % DIST_EDGES[-1]
        bucket = st["dist_bucket"].setdefault(db, [0, 0.0])
        bucket[0] += 1
        bucket[1] += err_px

        c = coss[k] / 127.0
        if c > 0.9:
            cb = ">0.9"
        elif c > 0.5:
            cb = "0.5-0.9"
        elif c > 0.0:
            cb = "0-0.5"
        else:
            cb = "<0"
        bucket = st["cos_bucket"].setdefault(cb, [0, 0.0])
        bucket[0] += 1
        bucket[1] += err_px

        x = k % TEX
        y = k // TEX
        is_border = False
        if x == 0 or y == 0 or x == TEX - 1 or y == TEX - 1:
            is_border = True
        else:
            if not bview[k - 1] or not bview[k + 1] or \
               not bview[k - TEX] or not bview[k + TEX]:
                is_border = True
        if is_border:
            st["border_n"] += 1
            st["border_err"] += err_px
        else:
            st["inner_n"] += 1
            st["inner_err"] += err_px

        t = min(1.0, err_px / 8.0)
        err_buf[j] = int(255 * t)
        err_buf[j + 1] = int(160 * (1.0 - t) + 40)
        err_buf[j + 2] = 40

    save_png(os.path.join(ANA_DIR, "error_%s.png" % mat), err_buf, TEX, TEX)

    st["err_mean_px"] = round(st["err_sum_px"] / st["both"], 4) if st["both"] else None
    st["border_mean"] = round(st["border_err"] / st["border_n"], 4) if st["border_n"] else None
    st["inner_mean"] = round(st["inner_err"] / st["inner_n"], 4) if st["inner_n"] else None
    mats_stat[mat] = st

    for key in ("both", "only_base", "only_spm", "view_mismatch", "exact_zero"):
        all_stat[key] += st[key]
    all_stat["err_sum_px"] += st["err_sum_px"]
    for i in range(len(all_stat["err_hist"])):
        all_stat["err_hist"][i] += st["err_hist"][i]
    all_stat["border"][0] += st["border_n"]
    all_stat["border"][1] += st["border_err"]
    all_stat["inner"][0] += st["inner_n"]
    all_stat["inner"][1] += st["inner_err"]
    for pk, pv in st["vm_pairs"].items():
        all_stat["vm_pairs"][pk] = all_stat["vm_pairs"].get(pk, 0) + pv
    for dbk, dbv in st["dist_bucket"].items():
        b = all_stat["dist_bucket"].setdefault(dbk, [0, 0.0])
        b[0] += dbv[0]
        b[1] += dbv[1]
    for cbk, cbv in st["cos_bucket"].items():
        b = all_stat["cos_bucket"].setdefault(cbk, [0, 0.0])
        b[0] += cbv[0]
        b[1] += cbv[1]

    print("%-42s 可比 %7d  均误差 %7.3f px  视图不一致 %6d  仅基 %6d  仅SPM %6d" % (
        mat[:42], st["both"], st["err_mean_px"] or 0, st["view_mismatch"],
        st["only_base"], st["only_spm"]))

both = all_stat["both"]
all_stat["err_mean_px"] = round(all_stat["err_sum_px"] / both, 4) if both else None
all_stat["border_mean"] = round(all_stat["border"][1] / all_stat["border"][0], 4) \
    if all_stat["border"][0] else None
all_stat["inner_mean"] = round(all_stat["inner"][1] / all_stat["inner"][0], 4) \
    if all_stat["inner"][0] else None

print()
print("=" * 64)
print("总计（全部材质）")
print("  双方有值（可比）: %d" % both)
print("  完全一致（误差=0）: %d (%.1f%%)" % (all_stat["exact_zero"],
      100.0 * all_stat["exact_zero"] / both if both else 0))
print("  平均误差: %.3f px（设计图 2048）" % (all_stat["err_mean_px"] or 0))
print("  视图不一致: %d  明细: %s" % (all_stat["view_mismatch"], all_stat["vm_pairs"]))
print("  仅基准有值: %d" % all_stat["only_base"])
print("  仅 SPM 有值: %d" % all_stat["only_spm"])
print()
print("  误差分布（px）:")
prev = 0.0
for i, e in enumerate(ERR_EDGES):
    print("    [%5.2f, %5.2f): %8d (%.1f%%)" % (prev, e, all_stat["err_hist"][i],
          100.0 * all_stat["err_hist"][i] / both if both else 0))
    prev = e
print("    [%5.2f,   inf): %8d (%.1f%%)" % (prev, all_stat["err_hist"][-1],
      100.0 * all_stat["err_hist"][-1] / both if both else 0))
print()
print("  边界带 vs 内部:")
print("    边界带纹素 %d  平均 %.3f px" % (all_stat["border"][0], all_stat["border_mean"] or 0))
print("    内部纹素   %d  平均 %.3f px" % (all_stat["inner"][0], all_stat["inner_mean"] or 0))
print()
print("  误差 vs 最近点距离（区分几何近似 / 对应错误）:")
for db in ["<%g" % DIST_EDGES[0]] + ["<%g" % e for e in DIST_EDGES[1:]] + [">=%g" % DIST_EDGES[-1]]:
    bucket = all_stat["dist_bucket"].get(db)
    if bucket and bucket[0]:
        print("    dist %-8s n=%8d  平均误差 %7.3f px" % (db, bucket[0], bucket[1] / bucket[0]))
print()
print("  误差 vs 法线夹角（cos）:")
for cb in [">0.9", "0.5-0.9", "0-0.5", "<0"]:
    bucket = all_stat["cos_bucket"].get(cb)
    if bucket and bucket[0]:
        print("    cos %-8s n=%8d  平均误差 %7.3f px" % (cb, bucket[0], bucket[1] / bucket[0]))

with open(os.path.join(OUT, "analysis_stats_%s.json" % LABEL), "w", encoding="utf-8") as f:
    json.dump({"total": all_stat, "materials": mats_stat}, f, indent=2, ensure_ascii=False)

print()
print("已输出: analysis/error_<材质>.png 与 analysis_stats.json")
