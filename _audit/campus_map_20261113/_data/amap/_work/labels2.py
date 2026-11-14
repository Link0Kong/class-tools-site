import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
w=cv2.imread(os.path.join(BASE,"amap_west.jpg"))
m=cv2.imread(os.path.join(BASE,"master.png"))
def c(img,x0,y0,x1,y1,scale): return cv2.resize(img[y0:y1,x0:x1],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
tiles=[
 ("A_west_top", c(w,800,0,1400,420,2.2)),
 ("B_west_lib", c(w,850,200,1300,650,2.2)),
 ("C_m_xiuyuannan", c(m,1270,2290,1430,2420,5.0)),
 ("D_m_xiuyuandong", c(m,1780,1650,1960,1800,5.0)),
]
for name,t in tiles:
    cv2.putText(t,name,(8,28),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,0,255),2,cv2.LINE_AA)
    cv2.imwrite(os.path.join(WORK,name+".png"),t,[cv2.IMWRITE_PNG_COMPRESSION,6]); print(name,t.shape)
