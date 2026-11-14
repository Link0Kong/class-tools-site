import cv2, numpy as np, os, sys
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
im=cv2.imread(os.path.join(BASE,"master.png"))
def crop(x0,y0,x1,y1,scale=1.0,grid=100,name="crop.png",label=True):
    c=im[y0:y1,x0:x1].copy()
    if scale!=1.0: c=cv2.resize(c,None,fx=scale,fy=scale,interpolation=cv2.INTER_NEAREST)
    font=cv2.FONT_HERSHEY_SIMPLEX
    if grid:
        for x in range(x0//grid*grid, x1+1, grid):
            if x<x0: continue
            px=int((x-x0)*scale)
            cv2.line(c,(px,0),(px,c.shape[0]-1),(0,0,255) if x%500==0 else (200,180,255),1)
            if label: cv2.putText(c,str(x),(px+2,16),font,0.45,(0,0,255),1,cv2.LINE_AA)
        for y in range(y0//grid*grid, y1+1, grid):
            if y<y0: continue
            py=int((y-y0)*scale)
            cv2.line(c,(0,py),(c.shape[1]-1,py),(0,0,255) if y%500==0 else (200,180,255),1)
            if label: cv2.putText(c,str(y),(2,py+14),font,0.45,(0,0,255),1,cv2.LINE_AA)
    out=os.path.join(WORK,name)
    cv2.imwrite(out,c,[cv2.IMWRITE_PNG_COMPRESSION,6])
    print(out, c.shape)
if __name__=="__main__":
    import json
    args=json.loads(sys.argv[1])
    crop(**args)
