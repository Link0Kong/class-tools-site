import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
n=cv2.imread(os.path.join(BASE,"amap_north.jpg"))
s=cv2.imread(os.path.join(BASE,"amap_south.jpg"))
Msn=np.load(os.path.join(WORK,"Msn.npy"))
h,w=n.shape[:2]
sw=cv2.warpAffine(s,Msn,(w,h),flags=cv2.INTER_LINEAR)
# crop overlap band y 1051..1571 and blend
crop=(slice(1050,1571),slice(0,2669))
a=n[crop].astype(np.float32); b=sw[crop].astype(np.float32)
blend=((a+b)/2).astype(np.uint8)
cv2.imwrite(os.path.join(WORK,"seam_ns.png"),blend)
# also difference
diff=np.abs(a-b).mean(axis=2)
print("mean abs diff",diff.mean(),"p95",np.percentile(diff,95))
# red-green anaglyph: north in red, south in green
ag=np.zeros_like(a)
ag[:,:,2]=a.mean(axis=2); ag[:,:,1]=b.mean(axis=2)
cv2.imwrite(os.path.join(WORK,"seam_ns_ag.png"),ag)
# downscale for viewing
cv2.imwrite(os.path.join(WORK,"seam_ns_small.png"),cv2.resize(blend,None,fx=0.6,fy=0.6,interpolation=cv2.INTER_AREA))
cv2.imwrite(os.path.join(WORK,"seam_ns_ag_small.png"),cv2.resize(ag,None,fx=0.6,fy=0.6,interpolation=cv2.INTER_AREA))
print("saved")
