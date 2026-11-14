import cv2, numpy as np, json, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
DATA = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\preview_data.json"
d=json.load(open(DATA,encoding='utf-8'))
anchors=[
 ((318.1,328.4),(1240,2155)),   # 图书馆
 ((566.0,306.0),(1845,1222)),   # 五行楼
 ((358.9,243.7),(990,1630)),    # 厚德楼
 ((420.5,262.5),(1265,1405)),   # 精诚楼
 ((489.2,334.2),(1810,1400)),   # 至善楼
 ((447.0,360.8),(1725,1650)),   # 自强楼
 ((415.4,435.4),(1880,2055)),   # 明德楼
 ((690.0,382.0),(2580,815)),    # 修园楼
]
P=np.array([a[0] for a in anchors],np.float64); Q=np.array([a[1] for a in anchors],np.float64)
def umeyama(src,dst):
    m=src.mean(0); n=dst.mean(0)
    s=src-m; t=dst-n
    cov=t.T@s/len(src)
    U,S,Vt=np.linalg.svd(cov)
    R=U@Vt
    if np.linalg.det(R)<0:
        U[:,-1]*=-1; R=U@Vt
    var=(s**2).sum()/len(src)
    scale=np.trace(np.diag(S)@np.eye(2))/var if var>0 else 0
    tr=np.trace(np.diag(S)@np.eye(2))
    scale=tr/var
    tr_vec=n-scale*R@m
    return scale,R,tr_vec
sc,R,t=umeyama(P,Q)
print("scale %.4f rot %.2f deg t %s"%(sc,np.degrees(np.arctan2(R[1,0],R[0,0])),np.round(t,1)))
Qp=(sc*(P@R.T))+t
err=np.linalg.norm(Qp-Q,axis=1)
print("residuals",np.round(err,1),"mean %.1f max %.1f"%(err.mean(),err.max()))
M=np.hstack([sc*R,t.reshape(-1,1)])
np.save(os.path.join(WORK,"preview_sim.npy"),M)
roads=[]
for f in d['features']:
    if f['k']!='road': continue
    pts=np.array(f['p'],np.float64)
    mp=cv2.transform(pts.reshape(-1,1,2),M).reshape(-1,2)
    roads.append((f['id'],f['g'],mp))
json.dump([(rid,g,[[round(float(x),1),round(float(y),1)] for x,y in mp]) for rid,g,mp in roads], open(os.path.join(WORK,"preview_roads_master.json"),"w"), ensure_ascii=False)
im=cv2.imread(os.path.join(BASE,"master.png"))
vis=(im.astype(np.float32)*0.35+255*0.65).astype(np.uint8)
colors=[(0,0,255),(0,128,255),(255,0,0),(255,0,255),(0,200,0),(200,0,0),(0,180,255),(128,0,128),(0,100,0),(100,0,100),(255,100,0),(0,0,0),(0,255,255),(150,50,150),(60,160,60),(180,180,0),(50,50,255)]
for i,(rid,g,mp) in enumerate(roads):
    c=colors[i%len(colors)]
    cv2.polylines(vis,[np.round(mp).astype(np.int32)],False,c,3,cv2.LINE_AA)
    mid=mp[len(mp)//2]
    cv2.putText(vis,rid,(int(mid[0])+4,int(mid[1])-4),cv2.FONT_HERSHEY_SIMPLEX,0.9,c,2,cv2.LINE_AA)
small=cv2.resize(vis,None,fx=0.42,fy=0.42,interpolation=cv2.INTER_AREA)
cv2.imwrite(os.path.join(WORK,"preview_roads_vis.png"),small)
print("saved; rotation indicates preview_data is rotated vs AMap north-up")
