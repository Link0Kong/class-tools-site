import cv2, numpy as np, os, json

BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE, "_work")
roads_doc = json.load(open(os.path.join(BASE, "roads_trace.json"), encoding="utf-8"))
anchors = json.load(open(os.path.join(WORK, "anchors.json"), encoding="utf-8"))
tr = json.load(open(os.path.join(WORK, "transforms.json"), encoding="utf-8"))

# preview_data cross reference for anchors (building centroids in 848x493)
prev = {
    "图书馆": [318.1, 328.4], "五行楼": [566.0, 306.0], "精诚楼": [420.5, 262.5],
    "至善楼": [489.2, 334.2], "厚德楼": [358.9, 243.7], "自强楼": [447.0, 360.8],
    "明德楼": [415.4, 435.4], "河洛时光": [377.0, 289.0],
}
for a in anchors:
    a["preview_data"] = prev.get(a["name"])
    # flatten check fields for compactness
    for src in ("south", "west"):
        c = a.get(src + "_check")
        if c:
            a[src + "_residual_px"] = c["residual_master_px"]
            a[src + "_match_score"] = c["score"]
            del a[src + "_check"]

# preview_data -> master similarity from 3 clean anchors (library / wuxing / mingde)
def umeyama(src, dst):
    m = src.mean(0); n = dst.mean(0)
    s = src - m; t = dst - n
    cov = t.T @ s / len(src)
    U, S, Vt = np.linalg.svd(cov)
    R = U @ Vt
    if np.linalg.det(R) < 0:
        U[:, -1] *= -1; R = U @ Vt
    var = (s**2).sum()/len(src)
    scale = np.trace(np.diag(S)) / var
    return scale, R, n - scale*R@m
P = np.array([prev["图书馆"], prev["五行楼"], prev["明德楼"]])
Q = np.array([[1240, 2155], [1845, 1222], [1880, 2055]], np.float64)
sc, R, t = umeyama(P, Q)
Qp = sc*(P @ R.T) + t
res = np.linalg.norm(Qp - Q, axis=1)
preview_map = {"scale": round(float(sc), 3),
               "rotation_deg": round(float(np.degrees(np.arctan2(R[1,0], R[0,0]))), 2),
               "matrix_2x3": [[round(float(sc*R[0,0]), 4), round(float(sc*R[0,1]), 4), round(float(t[0]), 2)],
                              [round(float(sc*R[1,0]), 4), round(float(sc*R[1,1]), 4), round(float(t[1]), 2)]],
               "anchor_residuals_px": [round(float(v), 1) for v in res],
               "note": "preview_data（848x493）为手绘/旋转过的示意图，与 AMap 北向上坐标系相差约 -51°，仅供参考，不能直接叠加"}
print("preview map:", preview_map)

roads_doc["anchors"] = anchors
roads_doc["transforms"] = {
    "south_to_master": {"model": "similarity(scale+translation, no rotation)",
                        "scale": round(float(tr["south_to_north"]["scale"]), 6),
                        "tx": round(float(tr["south_to_north"]["tx"]) + 137, 3),
                        "ty": round(float(tr["south_to_north"]["ty"]), 3),
                        "sift_matches": tr["south_to_north"]["total_good"], "inliers": tr["south_to_north"]["inliers"],
                        "residual_px": {"mean": round(float(tr["south_to_north"]["resid_mean"]), 3),
                                        "p95": round(float(tr["south_to_north"]["resid_p95"]), 3),
                                        "max": round(float(tr["south_to_north"]["resid_max"]), 3)}},
    "west_to_master": {"model": "similarity via south (west->south->north) + offset",
                       "scale": round(float(tr["west_to_north"]["scale"]), 6),
                       "tx": round(float(tr["west_to_north"]["tx"]) + 137, 3),
                       "ty": round(float(tr["west_to_north"]["ty"]), 3),
                       "west_to_south": {"scale": round(float(tr["west_to_south"]["scale"]), 6),
                                         "tx": round(float(tr["west_to_south"]["tx"]), 3),
                                         "ty": round(float(tr["west_to_south"]["ty"]), 3),
                                         "sift_matches": tr["west_to_south"]["total_good"],
                                         "inliers": tr["west_to_south"]["inliers"],
                                         "residual_px": {"mean": round(float(tr["west_to_south"]["resid_mean"]), 3),
                                                         "p95": round(float(tr["west_to_south"]["resid_p95"]), 3),
                                                         "max": round(float(tr["west_to_south"]["resid_max"]), 3)}}},
    "north_to_master": {"scale": 1.0, "tx": 137.0, "ty": 0.0, "model": "identity + master offset"},
    "preview_data_to_master": preview_map,
}
json.dump(roads_doc, open(os.path.join(BASE, "roads_trace.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("roads_trace.json updated:", len(roads_doc["roads"]), "roads,", len(anchors), "anchors")
# residual stats
import statistics
for src in ("south", "west"):
    rr = [a[src + "_residual_px"] for a in anchors if src + "_residual_px" in a]
    print(src, "anchors", len(rr), "residuals", rr, "mean", round(float(np.mean(rr)), 2), "max", max(rr))
