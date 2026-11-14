import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
im=cv2.imread(os.path.join(BASE,"master.png"))
B=im[:,:,0].astype(np.int16);G=im[:,:,1].astype(np.int16);R=im[:,:,2].astype(np.int16)
mx=im.max(axis=2).astype(np.int16); mn=im.min(axis=2).astype(np.int16)
br=B-R; gr=G-R
# candidate thin structures: mid-brightness, bluish neutral
m=((mx>=204)&(mx<=243)&(br>=10)&(br<=30)&(gr>=4)&(gr<=20)).astype(np.uint8)
print("raw frac", m.mean())
# remove buildings/large blobs
k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(25,25))
big=cv2.morphologyEx(m,cv2.MORPH_OPEN,k)
print("big frac", big.mean())
thin=(m & (1-big)).astype(np.uint8)
thin=cv2.morphologyEx(thin,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3)),iterations=1)
print("thin frac", thin.mean())
cv2.imwrite(os.path.join(WORK,"thinmask.png"),thin*255)
# overlay on downscaled master
vis=im.copy()
vis[thin>0]=(0,0,255)
small=cv2.resize(vis,None,fx=0.42,fy=0.42,interpolation=cv2.INTER_AREA)
cv2.imwrite(os.path.join(WORK,"thin_vis.png"),small)
