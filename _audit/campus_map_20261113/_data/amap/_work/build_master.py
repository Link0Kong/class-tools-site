import cv2, numpy as np, os
cv2.setNumThreads(4)
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
def load(n): return cv2.imread(os.path.join(BASE,n))
n=load("amap_north.jpg"); s=load("amap_south.jpg"); w=load("amap_west.jpg")
Msn=np.load(os.path.join(WORK,"Msn.npy")); Mws=np.load(os.path.join(WORK,"Mws.npy"))
Mwn=np.load(os.path.join(WORK,"Mwn.npy"))
# master offset: north at (DX,0)
DX=137; DY=0
def to_master(M):
    T=np.array([[1,0,DX],[0,1,DY],[0,0,1]],dtype=np.float64)
    Mh=np.vstack([M,[0,0,1]])
    return (T@Mh)[:2,:]
Mn_m = to_master(np.array([[1.,0,0],[0,1.,0]]))
Ms_m = to_master(Msn); Mw_m = to_master(Mwn)
W=2957; H=3463
canvas=np.zeros((H,W,3),np.uint8)
filled=np.zeros((H,W),np.uint8)
def place(img,M,label):
    warped=cv2.warpAffine(img,M,(W,H),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=(0,0,0))
    m=cv2.warpAffine(np.full(img.shape[:2],255,np.uint8),M,(W,H),flags=cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    m=(m>250)&(filled==0)
    canvas[m]=warped[m]
    filled[m]=1
    print(label,"placed, coverage",int(filled.sum()),"of",W*H)
place(n,Mn_m,"north"); place(s,Ms_m,"south"); place(w,Mw_m,"west")
# no-data fill: light warm gray
nod=filled==0
canvas[nod]=(246,248,250)
print("uncovered px",int(nod.sum()),"%.2f%%"%(100*nod.sum()/(W*H)))
cv2.imwrite(os.path.join(BASE,"master.png"),canvas,[cv2.IMWRITE_PNG_COMPRESSION,6])
print("master.png saved", canvas.shape)
# grid overlay
g=canvas.copy()
GRID=100; BOLD=500
for x in range(0,W,GRID):
    col=(180,140,220) if x%BOLD else (0,0,255)
    th=1 if x%BOLD else 2
    cv2.line(g,(x,0),(x,H-1),col,th,cv2.LINE_AA)
for y in range(0,H,GRID):
    col=(180,140,220) if y%BOLD else (0,0,255)
    th=1 if y%BOLD else 2
    cv2.line(g,(0,y),(W-1,y),col,th,cv2.LINE_AA)
font=cv2.FONT_HERSHEY_SIMPLEX
for x in range(0,W,BOLD):
    cv2.putText(g,str(x),(x+3,22),font,0.55,(0,0,255),2,cv2.LINE_AA)
    cv2.putText(g,str(x),(x+3,22),font,0.55,(255,255,255),1,cv2.LINE_AA)
    cv2.putText(g,str(x),(x+3,H-8),font,0.55,(0,0,255),2,cv2.LINE_AA)
    cv2.putText(g,str(x),(x+3,H-8),font,0.55,(255,255,255),1,cv2.LINE_AA)
for y in range(0,H,BOLD):
    cv2.putText(g,str(y),(4,y-4 if y>16 else y+18),font,0.55,(0,0,255),2,cv2.LINE_AA)
    cv2.putText(g,str(y),(4,y-4 if y>16 else y+18),font,0.55,(255,255,255),1,cv2.LINE_AA)
    cv2.putText(g,str(y),(W-60,y-4 if y>16 else y+18),font,0.5,(0,0,255),2,cv2.LINE_AA)
    cv2.putText(g,str(y),(W-60,y-4 if y>16 else y+18),font,0.5,(255,255,255),1,cv2.LINE_AA)
cv2.imwrite(os.path.join(BASE,"master_grid.png"),g,[cv2.IMWRITE_PNG_COMPRESSION,6])
print("master_grid.png saved", g.shape)
json.dump({"master_wh":[W,H],"north_offset":[DX,DY],
           "master_from_north":"p_master = p_north + (137,0)",
           "south_to_master":{"scale":float(Msn[0,0]),"tx":float(Msn[0,2]+DX),"ty":float(Msn[1,2]+DY)},
           "west_to_master":{"scale":float(Mwn[0,0]),"tx":float(Mwn[0,2]+DX),"ty":float(Mwn[1,2]+DY)}},
          open(os.path.join(WORK,"master_meta.json"),"w"),ensure_ascii=False,indent=1)
