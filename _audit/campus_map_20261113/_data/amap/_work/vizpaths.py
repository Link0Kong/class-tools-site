import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
im=cv2.imread(os.path.join(BASE,"master.png"))
vis=im.copy()
colors={"xiuyuanbei":(0,0,255),"wangguo_w":(0,128,255),"zhongjing":(255,0,255)}
for name,c in colors.items():
    p=os.path.join(WORK,"path_%s.npy"%name)
    if not os.path.exists(p): continue
    pts=np.load(p)
    for i in range(len(pts)-1):
        cv2.line(vis,tuple(pts[i]),tuple(pts[i+1]),c,3,cv2.LINE_AA)
small=cv2.resize(vis,None,fx=0.42,fy=0.42,interpolation=cv2.INTER_AREA)
cv2.imwrite(os.path.join(WORK,"paths_test.png"),small)
print("ok")
