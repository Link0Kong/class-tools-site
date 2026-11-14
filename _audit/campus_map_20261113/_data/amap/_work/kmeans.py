import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
im=cv2.imread(os.path.join(BASE,"master.png"))
sub=im[1900:2250, 1950:2400].copy()  # over 学府北路 area
Z=sub.reshape(-1,3).astype(np.float32)
crit=(cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER,60,0.2)
K=12
best=None
for seed in range(3):
    cv2.setRNGSeed(seed)
    ret,labels,centers=cv2.kmeans(Z,K,None,crit,5,cv2.KMEANS_PP_CENTERS)
    if best is None or ret<best[0]: best=(ret,labels.copy(),centers.copy())
ret,labels,centers=best
counts=np.bincount(labels.ravel(),minlength=K)
order=np.argsort(-counts)
print("cluster centers (BGR) counts, sorted:")
for i in order:
    print(i, centers[i].round(1), counts[i])
# recolor: assign distinct palette
pal=np.array([
 [0,0,0],[0,0,255],[0,255,0],[255,0,0],[0,255,255],[255,0,255],[255,255,0],
 [0,128,255],[128,0,255],[255,128,0],[0,255,128],[128,255,0]],np.uint8)
vis=pal[labels.ravel()].reshape(sub.shape)
cv2.imwrite(os.path.join(WORK,"t_kmeans.png"), vis)
print("saved")
