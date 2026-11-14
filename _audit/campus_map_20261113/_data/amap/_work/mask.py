import cv2, numpy as np, os, json
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
im=cv2.imread(os.path.join(BASE,"master.png"))
B=im[:,:,0].astype(np.int16); G=im[:,:,1].astype(np.int16); R=im[:,:,2].astype(np.int16)
mx=im.max(axis=2).astype(np.int16); mn=im.min(axis=2).astype(np.int16)
neutral=(mx-mn)<=10
bright=mx>=242
mask=((neutral)&(bright)).astype(np.uint8)
# exclude our no-data fill color (246,248,250) BGR region: reconstruct filled mask from coverage
# coverage: pixels that exactly equal the flat fill are no-data, but flat fill may coincide; compute by inverting three warps again
# simpler: no-data color was (246,248,250); detect exact equality
nodata=(np.abs(B-246)<=0)&(np.abs(G-248)<=0)&(np.abs(R-250)<=0)
print("nodata exact", int(nodata.sum()))
mask[nodata]=0
print("mask frac", mask.mean())
# clean
k3=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))
k5=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(5,5))
m=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,k5,iterations=2)
m=cv2.morphologyEx(m,cv2.MORPH_OPEN,k3,iterations=1)
print("clean mask frac", m.mean())
cv2.imwrite(os.path.join(WORK,"roadmask.png"), (m*255))
dist=cv2.distanceTransform(m,cv2.DIST_L2,5)
np.save(os.path.join(WORK,"road_dist.npy"),dist)
print("dist max",dist.max())
# visualization: highlight mask in red over master at 0.5 opacity for a tile
vis=im.copy()
vis[m>0]=(vis[m>0]*0.4+np.array([0,0,255],np.uint8)*0.6).astype(np.uint8)
cv2.imwrite(os.path.join(WORK,"mask_vis.png"),vis)
# stats of road width from distance transform on skeleton-ish: sample max along road
print("dist p50/p90/p99", np.percentile(dist[dist>0],[50,90,99]))
