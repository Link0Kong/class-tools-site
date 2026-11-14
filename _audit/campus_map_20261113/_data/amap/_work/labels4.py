import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
m=cv2.imread(os.path.join(BASE,"master.png"))
def save(img,x0,y0,x1,y1,scale,name):
    c=cv2.resize(img[y0:y1,x0:x1],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
    cv2.putText(c,name,(8,28),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,0,255),2,cv2.LINE_AA)
    cv2.imwrite(os.path.join(WORK,name+".png"),c,[cv2.IMWRITE_PNG_COMPRESSION,6]); print(name,c.shape)
save(m,580,1440,740,1720,4.0,"I_xiuyuanxi")
save(m,880,700,1060,880,4.0,"J_qiuyang")
save(m,950,2780,1200,2980,3.5,"K_xiuyuandong_sw")
save(m,1380,2140,1580,2320,4.0,"L_xinglin")
