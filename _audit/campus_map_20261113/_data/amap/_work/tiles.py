import cv2, numpy as np, os, sys
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
im=cv2.imread(os.path.join(BASE,"master.png"))
H,W=im.shape[:2]
def tile(x0,y0,x1,y1,scale,name,grid=100,label_step=200):
    x0=max(0,x0); y0=max(0,y0); x1=min(W,x1); y1=min(H,y1)
    c=im[y0:y1,x0:x1].copy()
    c=cv2.resize(c,None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_NEAREST)
    ch,cw=c.shape[:2]
    font=cv2.FONT_HERSHEY_SIMPLEX
    for x in range(x0//grid*grid, x1+1, grid):
        if x<x0: continue
        px=int((x-x0)*scale)
        if px<0 or px>=cw: continue
        col=(0,0,255) if x%500==0 else (190,170,250)
        cv2.line(c,(px,0),(px,ch-1),col,2 if x%500==0 else 1)
        if x%label_step==0:
            t=str(x); cv2.putText(c,t,(px+2,14),font,0.42,(0,0,255),1,cv2.LINE_AA)
            cv2.putText(c,t,(px+2,ch-3),font,0.42,(0,0,255),1,cv2.LINE_AA)
    for y in range(y0//grid*grid, y1+1, grid):
        if y<y0: continue
        py=int((y-y0)*scale)
        if py<0 or py>=ch: continue
        col=(0,0,255) if y%500==0 else (190,170,250)
        cv2.line(c,(0,py),(cw-1,py),col,2 if y%500==0 else 1)
        if y%label_step==0:
            t=str(y); cv2.putText(c,t,(2,py+14),font,0.42,(0,0,255),1,cv2.LINE_AA)
            cv2.putText(c,t,(cw-50,py+14),font,0.42,(0,0,255),1,cv2.LINE_AA)
    out=os.path.join(WORK,name); cv2.imwrite(out,c,[cv2.IMWRITE_PNG_COMPRESSION,6]); print(out,c.shape)
tiles=[
 (0,150,1500,1300,'ov_A_north.png'),
 (1100,150,2600,1300,'ov_B_northeast.png'),
 (400,1200,1900,2350,'ov_C_central.png'),
 (800,2100,2300,3250,'ov_D_south.png'),
 (100,2250,1600,3400,'ov_E_west.png'),
 (1500,2200,2957,3400,'ov_F_southeast.png'),
]
for t in tiles: tile(t[0],t[1],t[2],t[3],0.8,t[4])

