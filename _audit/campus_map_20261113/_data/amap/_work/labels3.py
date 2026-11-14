import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
w=cv2.imread(os.path.join(BASE,"amap_west.jpg"))
m=cv2.imread(os.path.join(BASE,"master.png"))
vis=np.load(os.path.join(WORK,"thin_vis.npy"))
def save(img,x0,y0,x1,y1,scale,name):
    c=cv2.resize(img[y0:y1,x0:x1],None,fx=scale,fy=scale,interpolation=cv2.INTER_CUBIC)
    cv2.putText(c,name,(8,28),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,0,255),2,cv2.LINE_AA)
    cv2.imwrite(os.path.join(WORK,name+".png"),c,[cv2.IMWRITE_PNG_COMPRESSION,6]); print(name,c.shape)
save(w,1200,0,1900,450,1.8,"E_west_label_top")
save(w,150,0,700,400,2.2,"F_west_label_left")
save(m,1030,2300,1430,2800,1.7,"G_m_southloop")
save(m,600,2400,1100,2900,1.7,"H_m_dorm_south")
