import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
w=cv2.imread(os.path.join(BASE,"amap_west.jpg"))
def crop(x0,y0,x1,y1,scale):
    c=w[y0:y1,x0:x1].copy()
    return cv2.resize(c,None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
tiles=[
 ("W1_round", crop(1750,250,2250,650,2.0)),
 ("W2_se",    crop(2200,600,2794,1100,1.7)),
 ("W3_sw",    crop(1200,900,1900,1501,1.4)),
]
for name,t in tiles:
    cv2.putText(t,name,(8,26),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,0,255),2,cv2.LINE_AA)
    cv2.imwrite(os.path.join(WORK,name+".png"),t,[cv2.IMWRITE_PNG_COMPRESSION,6]); print(name,t.shape)
