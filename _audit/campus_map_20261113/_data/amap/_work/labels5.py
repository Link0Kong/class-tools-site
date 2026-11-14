import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
m=cv2.imread(os.path.join(BASE,"master.png"))
def save(img,x0,y0,x1,y1,scale,name):
    c=cv2.resize(img[y0:y1,x0:x1],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
    cv2.putText(c,name,(8,28),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,0,255),2,cv2.LINE_AA)
    cv2.imwrite(os.path.join(WORK,name+".png"),c,[cv2.IMWRITE_PNG_COMPRESSION,6]); print(name,c.shape)
save(m,130,150,900,900,1.15,"M_nw.png")
save(m,0,850,900,1600,1.15,"N_w_upper.png")
