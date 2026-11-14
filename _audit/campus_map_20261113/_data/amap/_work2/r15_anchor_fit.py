# -*- coding: utf-8 -*-
"""r15: verified label anchors -> least-squares affine model->master.

Anchor master positions were read from montage crops (POI icon centres).
Old-model point for each anchor = centroid of the matching old building(s);
for a complex whose label sits at the complex centre we use the wing-group
centroid, then (1 iteration) snap to the single wing nearest the projected icon.
"""
import os, json, math
import cv2, numpy as np

AMAP = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
DATA = os.path.dirname(AMAP)
WORK = os.path.join(AMAP, "_work2")
old = json.load(open(os.path.join(DATA, "preview_data.json"), encoding="utf-8"))
bld = {b["id"]: b for b in old["buildings"]}

# (label text on master, master px of AMap POI icon, old building ids forming that POI)
ANCHORS = [
    ("名师苑",        (1369.0,  800.0), ["B81", "B82", "B83", "B84", "B85"]),
    ("修园楼",        (2564.0,  846.0), ["B66"]),
    ("实验动物中心",  (2468.0,  939.0), ["B64", "B65"]),
    ("五行楼",        (1849.0, 1200.5), ["B32", "B33", "B34", "B35"]),
    ("求真楼",        (2510.0, 1182.0), ["B60", "B61", "B62", "B63"]),
    ("至善楼",        (1787.4, 1399.6), ["B36", "B37", "B38", "B39"]),
    ("精诚楼",        (1295.7, 1401.6), ["B28", "B29", "B30", "B31"]),
    ("康复产业研究院", (909.7, 1409.0), ["B24", "B25", "B26", "B27"]),
    ("厚德楼",        (1029.0, 1676.4), ["B20", "B21", "B22", "B23"]),
    ("体育馆",        (431.1, 1442.3), ["B70"]),
    ("自强楼",        (1712.8, 1661.7), ["B40", "B41", "B42", "B43"]),
    ("学生活动中心",  (547.1, 1800.0), ["B04"]),
    ("明德楼",        (1883.6, 2065.5), ["B59"]),
    ("图书馆",        (1252.7, 2154.0), ["B50", "B51"]),
]


def fit_affine(P, Q, weights=None):
    """least squares Q = A P + t  (2x3)."""
    n = len(P)
    A = np.zeros((2 * n, 6))
    b = np.zeros(2 * n)
    A[0::2, 0] = P[:, 0]; A[0::2, 1] = P[:, 1]; A[0::2, 4] = 1; b[0::2] = Q[:, 0]
    A[1::2, 2] = P[:, 0]; A[1::2, 3] = P[:, 1]; A[1::2, 5] = 1; b[1::2] = Q[:, 1]
    if weights is not None:
        w = np.repeat(np.sqrt(weights), 2)
        A = A * w[:, None]; b = b * w
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    return np.array([[sol[0], sol[1], sol[4]], [sol[2], sol[3], sol[5]]])


def apply(M, P):
    return P @ M[:, :2].T + M[:, 2]


P0 = []
for _, _, ids in ANCHORS:
    p = np.array([[bld[i]["x"], bld[i]["y"]] for i in ids], float).mean(0)
    P0.append(p)
P0 = np.array(P0)
Q = np.array([q for _, q, _ in ANCHORS], float)
M = fit_affine(P0, Q)

# iterate: snap each anchor to the single old wing whose projection is nearest the icon
for it in range(4):
    P = []
    for (name, q, ids) in ANCHORS:
        cand = np.array([[bld[i]["x"], bld[i]["y"]] for i in ids], float)
        proj = apply(M, cand)
        ds = np.linalg.norm(proj - np.array(q), axis=1)
        P.append(cand[int(np.argmin(ds))])
    P = np.array(P)
    M = fit_affine(P, Q)
    resid = np.linalg.norm(apply(M, P) - Q, axis=1)
    print("iter %d  affine=\n%s\n  resid mean %.2f med %.2f max %.2f" %
          (it, np.round(M, 5), resid.mean(), np.median(resid), resid.max()))

resid = np.linalg.norm(apply(M, P) - Q, axis=1)
print("\nper-anchor residuals:")
for (name, q, ids), p, r in zip(ANCHORS, P, resid):
    pr = apply(M, p[None, :])[0]
    print("  %-10s icon=(%7.1f,%7.1f) old=(%6.1f,%6.1f) proj=(%7.1f,%7.1f) resid=%5.2f" %
          (name, q[0], q[1], p[0], p[1], pr[0], pr[1], r))

# similarity (4-dof) fit for comparison
def fit_sim(P, Q):
    pc = P.mean(0); qc = Q.mean(0)
    P0_ = P - pc; Q0 = Q - qc
    a = (P0_[:, 0] * Q0[:, 0] + P0_[:, 1] * Q0[:, 1]).sum()
    b = (P0_[:, 0] * Q0[:, 1] - P0_[:, 1] * Q0[:, 0]).sum()
    den = (P0_ ** 2).sum()
    s = math.hypot(a, b) / den
    th = math.atan2(b, a)
    R = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    t = qc - s * R @ pc
    return np.hstack([s * R, t.reshape(-1, 1)]), s, math.degrees(th)

Msim, s, th = fit_sim(P, Q)
rs = np.linalg.norm(apply(Msim, P) - Q, axis=1)
print("\nsimilarity: scale=%.4f rot=%.2f deg resid mean %.2f med %.2f max %.2f" %
      (s, th, rs.mean(), np.median(rs), rs.max()))
# refine similarity by moving t to mean residual
Msim[:, 2] += (Q - apply(Msim, P)).mean(0)
rs = np.linalg.norm(apply(Msim, P) - Q, axis=1)
print("similarity refined: resid mean %.2f med %.2f max %.2f" % (rs.mean(), np.median(rs), rs.max()))

# scale estimate input for matching: sqrt(|det|)
det = M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0]
print("\naffine det=%.4f  equiv uniform scale=%.4f" % (det, math.sqrt(abs(det))))
print("similarity matrix=\n", np.round(Msim, 5))

out = {
    "labels": [a[0] for a in ANCHORS],
    "anchor_old_ids": [a[2] for a in ANCHORS],
    "anchor_model_points": P.tolist(),
    "anchor_master_points": Q.tolist(),
    "model_to_master_affine": M.tolist(),
    "model_to_master_similarity": Msim.tolist(),
    "residual_px": {"mean": float(resid.mean()), "median": float(np.median(resid)),
                    "p95": float(np.percentile(resid, 95)), "max": float(resid.max())},
    "residuals": resid.tolist(),
    "similarity_residual_px": {"mean": float(rs.mean()), "median": float(np.median(rs)),
                               "p95": float(np.percentile(rs, 95)), "max": float(rs.max())},
    "equivalent_scale": float(math.sqrt(abs(det))),
    "rotation_deg": float(math.degrees(math.atan2(M[1, 0], M[0, 0]))),
}
json.dump(out, open(os.path.join(WORK, "anchor_fit.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

# visual: labels/anchors over faded master
im = cv2.imread(os.path.join(AMAP, "master.png"))
vis = cv2.addWeighted(im, 0.5, np.full_like(im, 255), 0.5, 0)
for (name, q, ids), p, r in zip(ANCHORS, P, resid):
    pr = apply(M, p[None, :])[0]
    cv2.circle(vis, (int(q[0]), int(q[1])), 9, (0, 0, 255), 2)
    cv2.line(vis, (int(q[0]), int(q[1])), (int(pr[0]), int(pr[1])), (255, 0, 0), 1)
    cv2.putText(vis, "%s %.0f" % (name, r), (int(q[0]) + 12, int(q[1]) + 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2, cv2.LINE_AA)
cv2.imwrite(os.path.join(WORK, "d_anchor_fit.png"),
            cv2.resize(vis, (1500, int(im.shape[0] * 1500.0 / im.shape[1])), interpolation=cv2.INTER_AREA))
print("\nsaved anchor_fit.json / d_anchor_fit.png")
