import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
im=cv2.imread(os.path.join(BASE,"master.png"))
regions=[
 ("L1_diag", 1800,1660,1960,1790),
 ("L2_zjd",  1440,1660,1580,1800),
 ("L3_zjx",  1380,1720,1500,1860),
 ("L4_qyd_e", 1300,2280,1460,2400),
 ("L5_qyd_w", 1180,2180,1340,2320),
 ("L6_wg_e", 1370,1190,1530,1310),
 ("L7_wg_w", 690,1190,880,1310),
 ("L8_yx_e", 1590,1420,1760,1540),
 ("L9_yx_w", 950,1420,1150,1540),
]
tiles=[]
for name,x0,y0,x1,y1 in regions:
    c=im[y0:y1,x0:x1].copy()
    c=cv2.resize(c,None,fx=3.0,fy=3.0,interpolation=cv2.INTER_NEAREST)
    cv2.putText(c,name,(6,22),cv2.FONT_HERSHEY_SIMPLEX,0.7,(0,0,255),2,cv2.LINE_AA)
    tiles.append(c)
# normalize tile size
tw=max(t.shape[1] for t in tiles); th=max(t.shape[0] for t in tiles)
tiles=[cv2.copyMakeBorder(t,0,th-t.shape[0],0,tw-t.shape[1],cv2.BORDER_CONSTANT,value=(255,255,255)) for t in tiles]
rows=[np.hstack(tiles[i:i+3]) for i in range(0,9,3)]
mont=np.vstack(rows)
cv2.imwrite(os.path.join(WORK,"labels_montage.png"),mont,[cv2.IMWRITE_PNG_COMPRESSION,6])
print(mont.shape)
