import cv2, numpy as np, os, json

BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE, "_work")
n = cv2.imread(os.path.join(BASE, "amap_north.jpg")).astype(np.float64)
s = cv2.imread(os.path.join(BASE, "amap_south.jpg")).astype(np.float64)
w = cv2.imread(os.path.join(BASE, "amap_west.jpg")).astype(np.float64)
Msn = np.load(os.path.join(WORK, "Msn.npy"))
Mw = np.load(os.path.join(WORK, "Mwn.npy"))
DX, DY = 137, 0
def to_master(M):
    T = np.array([[1,0,DX],[0,1,DY],[0,0,1]], np.float64)
    return (T @ np.vstack([M,[0,0,1]]))[:2,:]
imgs = [("north", n, to_master(np.array([[1.,0,0],[0,1.,0]]))),
        ("south", s, to_master(Msn)),
        ("west", w, to_master(Mw))]
W, H = 2957, 3463
acc = np.zeros((H, W, 3), np.float64)
wt = np.zeros((H, W), np.float64)
for name, img, M in imgs:
    warped = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_REPLICATE)
    ones = np.ones((img.shape[0], img.shape[1]), np.float32)
    m = cv2.warpAffine(ones, M, (W, H), flags=cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_CONSTANT, borderValue=0).astype(np.float64)
    acc += warped * m[..., None]
    wt += m
    print(name, "weight sum", round(float(m.sum()), 0))
canvas = np.zeros((H, W, 3), np.uint8)
valid = wt > 1e-6
canvas[valid] = np.clip(acc[valid] / wt[valid][..., None], 0, 255).astype(np.uint8)
canvas[~valid] = (246, 248, 250)
print("uncovered", int((~valid).sum()), "%.2f%%" % (100*(~valid).sum()/(W*H)))
cv2.imwrite(os.path.join(BASE, "master.png"), canvas, [cv2.IMWRITE_PNG_COMPRESSION, 6])
print("master.png", canvas.shape)
# seam diff check
rowdiff = np.abs(np.diff(canvas[900:1250, 1300:2200].astype(np.int16), axis=0)).mean(axis=(1,2))
idx = np.argsort(-rowdiff)[:5]
print("largest row diffs:", [(int(900+i), round(float(rowdiff[i]), 2)) for i in idx])

# grid image
g = canvas.copy()
GRID, BOLD = 100, 500
for x in range(0, W, GRID):
    col = (180,140,220) if x % BOLD else (0,0,255)
    cv2.line(g, (x,0), (x,H-1), col, 1 if x % BOLD else 2, cv2.LINE_AA)
for y in range(0, H, GRID):
    col = (180,140,220) if y % BOLD else (0,0,255)
    cv2.line(g, (0,y), (W-1,y), col, 1 if y % BOLD else 2, cv2.LINE_AA)
font = cv2.FONT_HERSHEY_SIMPLEX
def label(im, text, org, fs=0.5):
    cv2.putText(im, text, org, font, fs, (0,0,255), 2, cv2.LINE_AA)
    cv2.putText(im, text, org, font, fs, (255,255,255), 1, cv2.LINE_AA)
for x in range(0, W, BOLD):
    label(g, str(x), (x+3, 20)); label(g, str(x), (x+3, H-8))
for y in range(0, H, BOLD):
    yy = y-4 if y > 16 else y+18
    label(g, str(y), (4, yy)); label(g, str(y), (W-58, yy))
for x in range(0, W, 1000):
    for y in range(0, H, 1000):
        label(g, "%d,%d" % (x, y), (x+4, y+16), 0.42)
for x in range(500, W, 1000):
    for y in range(500, H, 1000):
        label(g, "%d,%d" % (x, y), (x+4, y+16), 0.42)
cv2.imwrite(os.path.join(BASE, "master_grid.png"), g, [cv2.IMWRITE_PNG_COMPRESSION, 6])
print("master_grid.png", g.shape)
