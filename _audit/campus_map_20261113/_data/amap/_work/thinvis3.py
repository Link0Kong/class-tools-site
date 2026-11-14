import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
vis=np.load(os.path.join(WORK,"thin_vis.npy"))
def crop(x0,y0,x1,y1,scale,name):
    c=vis[y0:y1,x0:x1].copy()
    c=cv2.resize(c,None,fx=scale,fy=scale,interpolation=cv2.INTER_NEAREST)
    ch,cw=c.shape[:2]; font=cv2.FONT_HERSHEY_SIMPLEX
    for x in range(x0//100*100,x1+1,100):
        if x<x0: continue
        px=int((x-x0)*scale)
        if not(0<=px<cw): continue
        cv2.line(c,(px,0),(px,ch-1),(0,0,255),1)
        for yy in (14,ch//2,ch-4): cv2.putText(c,str(x),(px+2,yy),font,0.5,(0,0,255),1,cv2.LINE_AA)
    for y in range(y0//100*100,y1+1,100):
        if y<y0: continue
        py=int((y-y0)*scale)
        if not(0<=py<ch): continue
        cv2.line(c,(0,py),(cw-1,py),(0,0,255),1)
        for xx in (4,cw//2,cw-60): cv2.putText(c,str(y),(xx,py+14),font,0.5,(0,0,255),1,cv2.LINE_AA)
    out=os.path.join(WORK,name); cv2.imwrite(out,c,[cv2.IMWRITE_PNG_COMPRESSION,6]); print(out,c.shape)
crop(1150,1900,1700,2500,1.6,"tm_lib.png")
crop(1400,2300,2000,2950,1.6,"tm_se.png")
