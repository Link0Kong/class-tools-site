import cv2, numpy as np, json, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
def load(n): return cv2.imread(os.path.join(BASE,n))
def gray(im): return cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
n=load("amap_north.jpg"); s=load("amap_south.jpg"); w=load("amap_west.jpg")
gn,gs,gw=gray(n),gray(s),gray(w)
sift=cv2.SIFT_create(nfeatures=30000, contrastThreshold=0.01)
def kd(g): return sift.detectAndCompute(g,None)
kn,dn=kd(gn); ks,ds=kd(gs); kw,dw=kd(gw)
bf=cv2.BFMatcher()
def matches(kA,dA,kB,dB,ratio=0.78):
    m=bf.knnMatch(dA,dB,k=2)
    good=[p for p,q in m if len((p,q))==2 and p.distance<ratio*q.distance]
    P1=np.float32([kA[g.queryIdx].pt for g in good]); P2=np.float32([kB[g.trainIdx].pt for g in good])
    return P1,P2,good
def sim_fit(P1,P2,thr=4.0,maxIters=30000):
    M,inl=cv2.estimateAffinePartial2D(P1,P2,method=cv2.RANSAC,ransacReprojThreshold=thr,maxIters=maxIters,confidence=0.9999)
    inl=inl.ravel().astype(bool)
    P=P1[inl]; Q=P2[inl]
    A=np.zeros((2*len(P),3)); b=np.zeros(2*len(P))
    A[0::2,0]=P[:,0]; A[0::2,1]=1; b[0::2]=Q[:,0]
    A[1::2,0]=P[:,1]; A[1::2,2]=1; b[1::2]=Q[:,1]
    sol,res,rank,sv=np.linalg.lstsq(A,b,rcond=None)
    sc,tx,ty=sol
    M2=np.array([[sc,0,tx],[0,sc,ty]],dtype=np.float64)
    Ph=cv2.transform(P.reshape(-1,1,2),M2).reshape(-1,2)
    d=np.linalg.norm(Ph-Q,axis=1)
    return M2, inl, len(P), d, sc, tx, ty, M
sn=matches(ks,ds,kn,dn); Msn, inl_sn, n_sn, d_sn, sc_sn, tx_sn, ty_sn, Mrot_sn = sim_fit(sn[0],sn[1])
ws=matches(kw,dw,ks,ds); Mws_s, inl_ws, n_ws, d_ws, sc_ws, tx_ws, ty_ws, Mrot_ws = sim_fit(ws[0],ws[1])
print("SOUTH->NORTH axis-aligned: scale %.6f t=(%.3f,%.3f) inl=%d/%d resid mean=%.3f med=%.3f p95=%.3f max=%.3f"%(sc_sn,tx_sn,ty_sn,n_sn,len(sn[0]),d_sn.mean(),np.median(d_sn),np.percentile(d_sn,95),d_sn.max()))
print("WEST->SOUTH axis-aligned: scale %.6f t=(%.3f,%.3f) inl=%d/%d resid mean=%.3f med=%.3f p95=%.3f max=%.3f"%(sc_ws,tx_ws,ty_ws,n_ws,len(ws[0]),d_ws.mean(),np.median(d_ws),np.percentile(d_ws,95),d_ws.max()))
def res_of(P1,P2,M):
    Ph=cv2.transform(P1.reshape(-1,1,2),M).reshape(-1,2); return np.linalg.norm(Ph-P2,axis=1)
drot=res_of(sn[0],sn[1],Mrot_sn); print("rot-including south->north residual all matches: med %.3f p95 %.3f"%(np.median(drot),np.percentile(drot,95)))
sc = sc_sn*sc_ws; tx = sc_sn*tx_ws + tx_sn; ty = sc_sn*ty_ws + ty_sn
Mwn = np.array([[sc,0,tx],[0,sc,ty]])
print("WEST->NORTH composed: scale %.6f t=(%.3f,%.3f)"%(sc,tx,ty))
def corners(img):
    h,ww=img.shape[:2]; return np.array([[0,0],[ww,0],[0,h],[ww,h],[ww/2,h/2]],dtype=np.float64)
for name,M,im in [("north",np.eye(2,3),n),("south",Msn,s),("west",Mwn,w)]:
    c=cv2.transform(corners(im).reshape(-1,1,2),M).reshape(-1,2)
    print(name,"corners north coords x[%.1f,%.1f] y[%.1f,%.1f]"%(c[:4,0].min(),c[:4,0].max(),c[:4,1].min(),c[:4,1].max()))
np.save(os.path.join(WORK,"Msn.npy"),Msn); np.save(os.path.join(WORK,"Mws.npy"),Mws_s); np.save(os.path.join(WORK,"Mwn.npy"),Mwn)
json.dump({"south_to_north":{"scale":float(sc_sn),"tx":float(tx_sn),"ty":float(ty_sn),"inliers":int(n_sn),"total_good":len(sn[0]),"resid_mean":float(d_sn.mean()),"resid_p95":float(np.percentile(d_sn,95)),"resid_max":float(d_sn.max())},
           "west_to_south":{"scale":float(sc_ws),"tx":float(tx_ws),"ty":float(ty_ws),"inliers":int(n_ws),"total_good":len(ws[0]),"resid_mean":float(d_ws.mean()),"resid_p95":float(np.percentile(d_ws,95)),"resid_max":float(d_ws.max())},
           "west_to_north":{"scale":float(sc),"tx":float(tx),"ty":float(ty)}}, open(os.path.join(WORK,"transforms.json"),"w"), ensure_ascii=False, indent=1)
