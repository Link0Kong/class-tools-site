import cv2, numpy as np, os, json, sys
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
im=cv2.imread(os.path.join(BASE,"master.png"))
H,W=im.shape[:2]
def crop(x0,y0,x1,y1,scale=2.0,name="c.png",small=50,big=100):
    x0=max(0,x0); y0=max(0,y0); x1=min(W,x1); y1=min(H,y1)
    c=im[y0:y1,x0:x1].copy()
    if scale!=1.0: c=cv2.resize(c,None,fx=scale,fy=scale,interpolation=cv2.INTER_NEAREST)
    ch,cw=c.shape[:2]
    font=cv2.FONT_HERSHEY_SIMPLEX
    for x in range(x0//small*small, x1+1, small):
        if x<x0: continue
        px=int((x-x0)*scale)
        if px<0 or px>=cw: continue
        col=(0,0,255) if x%big==0 else (225,205,255)
        cv2.line(c,(px,0),(px,ch-1),col,2 if x%big==0 else 1)
        if x%big==0:
            for yy in (14,ch//2,ch-4):
                cv2.putText(c,str(x),(px+2,yy),font,0.55,(0,0,255),2,cv2.LINE_AA)
                cv2.putText(c,str(x),(px+2,yy),font,0.55,(255,255,255),1,cv2.LINE_AA)
    for y in range(y0//small*small, y1+1, small):
        if y<y0: continue
        py=int((y-y0)*scale)
        if py<0 or py>=ch: continue
        col=(0,0,255) if y%big==0 else (225,205,255)
        cv2.line(c,(0,py),(cw-1,py),col,2 if y%big==0 else 1)
        if y%big==0:
            for xx in (4,cw//2,cw-70):
                cv2.putText(c,str(y),(xx,py+16),font,0.55,(0,0,255),2,cv2.LINE_AA)
                cv2.putText(c,str(y),(xx,py+16),font,0.55,(255,255,255),1,cv2.LINE_AA)
    # corner summary
    cv2.putText(c,"x[%d,%d] y[%d,%d]"%(x0,x1,y0,y1),(8,ch-10),font,0.6,(120,0,200),2,cv2.LINE_AA)
    out=os.path.join(WORK,name); cv2.imwrite(out,c,[cv2.IMWRITE_PNG_COMPRESSION,6]); print(out,c.shape)
if __name__=="__main__":
    for spec in json.loads(sys.argv[1]): crop(**spec)
