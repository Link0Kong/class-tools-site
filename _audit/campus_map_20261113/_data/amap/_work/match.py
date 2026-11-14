import cv2, numpy as np, json, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
def load(n):
    im = cv2.imread(os.path.join(BASE, n))
    return im
def gray(im):
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    return g

def match(gA, gB, tag):
    sift = cv2.SIFT_create(nfeatures=12000, contrastThreshold=0.02)
    kA, dA = sift.detectAndCompute(gA, None)
    kB, dB = sift.detectAndCompute(gB, None)
    print(tag, "kpA", len(kA), "kpB", len(kB))
    bf = cv2.BFMatcher()
    m = bf.knnMatch(dA, dB, k=2)
    good = [p for p,q in m if len((p,q))==2 and p.distance < 0.78*q.distance]
    print("good matches", len(good))
    P1 = np.float32([kA[g.queryIdx].pt for g in good])
    P2 = np.float32([kB[g.trainIdx].pt for g in good])
    H, mask = cv2.findHomography(P1, P2, cv2.RANSAC, 4.0)
    mask = mask.ravel().astype(bool)
    print("homography inliers", int(mask.sum()))
    # asym scale check from H
    print("H=\n", np.round(H/H[2,2], 5))
    # similarity fit
    M, ms = cv2.estimateAffinePartial2D(P1[mask], P2[mask], method=cv2.LMEDS)
    ms = ms.ravel().astype(bool)
    s = np.hypot(M[0,0], M[1,0]); th = np.degrees(np.arctan2(M[1,0], M[0,0]))
    print("similarity scale", round(float(s),6), "rot_deg", round(float(th),4), "tx,ty", np.round(M[:2,2],3), "inliers", int(ms.sum()))
    # residuals
    def res(P1, P2, H):
        Ph = cv2.perspectiveTransform(P1.reshape(-1,1,2), H).reshape(-1,2)
        d = np.linalg.norm(Ph-P2, axis=1)
        return d
    dH = res(P1[mask], P2[mask], H)
    Ph = cv2.transform(P1[mask].reshape(-1,1,2), M).reshape(-1,2)
    dS = np.linalg.norm(Ph-P2[mask], axis=1)
    print("homography residual: mean %.3f median %.3f p95 %.3f max %.3f" % (dH.mean(), np.median(dH), np.percentile(dH,95), dH.max()))
    print("similarity residual:  mean %.3f median %.3f p95 %.3f max %.3f" % (dS.mean(), np.median(dS), np.percentile(dS,95), dS.max()))
    return M, H, P1, P2, mask

n = load("amap_north.jpg"); s = load("amap_south.jpg"); w = load("amap_west.jpg")
print("shapes", n.shape, s.shape, w.shape)
gn, gs, gw = gray(n), gray(s), gray(w)
Msn, Hsn, _, _, _ = match(gs, gn, "south->north")   # query south, train north
Mwn, Hwn, _, _, _ = match(gw, gn, "west->north")
np.save(os.path.join(BASE,"_work","Msn.npy"), Msn)
np.save(os.path.join(BASE,"_work","Mwn.npy"), Mwn)
np.save(os.path.join(BASE,"_work","Hsn.npy"), Hsn)
np.save(os.path.join(BASE,"_work","Hwn.npy"), Hwn)
