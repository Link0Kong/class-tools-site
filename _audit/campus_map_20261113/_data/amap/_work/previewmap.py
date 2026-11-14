import cv2, numpy as np, json, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
DATA = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\preview_data.json"
d=json.load(open(DATA,encoding='utf-8'))
anchors=[
 ((318.1,328.4),(1240,2155)),
 ((566.0,306.0),(1845,1222)),
 ((358.9,243.7),(990,1630)),
 ((420.5,262.5),(1265,1405)),
 ((489.2,334.2),(1810,1400)),
 ((447.0,360.8),(1725,1650)),
 ((415.4,435.4),(1880,2055)),
 ((690.0,382.0),(2480,1000)),
 ((347.1,121.1),(600,1450)),
]
P=np.array([a[0] for a in anchors],np.float64); Q=np.array([a[1] for a in anchors],np.float64)
A=np.zeros((2*len(P),6)); b=np.zeros(2*len(P))
A[0::2,0]=P[:,0]; A[0::2,1]=P[:,1]; A[0::2,2]=1; b[0::2]=Q[:,0]
A[1::2,3]=P[:,0]; A[1::2,4]=P[:,1]; A[1::2,5]=1; b[1::2]=Q[:,1]
sol,res,rank,sv=np.linalg.lstsq(A,b,rcond=None)
M=np.array([[sol[0],sol[1],sol[2]],[sol[3],sol[4],sol[5]]])
print("affine:\n",np.round(M,5))
Ph=cv2.transform(P.reshape(-1,1,2),M).reshape(-1,2)
err=np.linalg.norm(Ph-Q,axis=1)
print("anchor residuals",np.round(err,1),"mean %.1f"%err.mean())
roads=[]
for f in d['features']:
    if f['k']!='road': continue
    pts=np.array(f['p'],np.float64)
    mp=cv2.transform(pts.reshape(-1,1,2),M).reshape(-1,2)
    roads.append((f['id'],f['g'],mp))
np.save(os.path.join(WORK,"preview_affine.npy"),M)
json.dump([(rid,g,[[round(float(x),1),round(float(y),1)] for x,y in mp]) for rid,g,mp in roads], open(os.path.join(WORK,"preview_roads_master.json"),"w"), ensure_ascii=False)
im=cv2.imread(os.path.join(BASE,"master.png"))
vis=(im.astype(np.float32)*0.5+255*0.5).astype(np.uint8)
colors=[(0,0,255),(0,128,255),(255,0,0),(255,0,255),(0,200,0),(200,0,0),(0,180,255),(128,0,128),(0,100,0),(100,0,100),(255,100,0),(0,0,0),(0,255,255),(150,50,150),(60,160,60),(180,180,0),(50,50,255)]
for i,(rid,g,mp) in enumerate(roads):
    c=colors[i%len(colors)]
    cv2.polylines(vis,[np.round(mp).astype(np.int32)],False,c,3,cv2.LINE_AA)
    mid=mp[len(mp)//2]
    cv2.putText(vis,rid,(int(mid[0])+4,int(mid[1])-4),cv2.FONT_HERSHEY_SIMPLEX,0.9,c,2,cv2.LINE_AA)
small=cv2.resize(vis,None,fx=0.42,fy=0.42,interpolation=cv2.INTER_AREA)
cv2.imwrite(os.path.join(WORK,"preview_roads_vis.png"),small)
print("saved")
