import cv2, numpy as np, os
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
def load(n): return cv2.imread(os.path.join(BASE,n))
def gray(im): return cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
n=load("amap_north.jpg"); s=load("amap_south.jpg"); w=load("amap_west.jpg")
gn,gs,gw=gray(n),gray(s),gray(w)
sift=cv2.SIFT_create(nfeatures=30000, contrastThreshold=0.01)
def prep(g, tag):
    k,d=sift.detectAndCompute(g,None); print(tag,len(k)); return k,d
kw,dw=prep(gw,"west"); ks,ds=prep(gs,"south"); kn,dn=prep(gn,"north")
flann=cv2.FlannBasedMatcher(dict(algorithm=1,trees=5),dict(checks=150))
def tries(kA,dA,kB,dB,tag):
    for ratio in (0.75,0.85,0.92):
        for thr in (3.0,6.0,10.0):
            m=flann.knnMatch(dA,dB,k=2)
            good=[p for p,q in m if p.distance<ratio*q.distance]
            if len(good)<10: print(tag,ratio,thr,"good",len(good)); continue
            P1=np.float32([kA[g.queryIdx].pt for g in good]); P2=np.float32([kB[g.trainIdx].pt for g in good])
            M,ms=cv2.estimateAffinePartial2D(P1,P2,method=cv2.RANSAC,ransacReprojThreshold=thr,maxIters=20000,confidence=0.999)
            if M is None: print(tag,ratio,thr,"none"); continue
            ms=ms.ravel().astype(bool); sc=np.hypot(M[0,0],M[1,0])
            print(tag,"ratio",ratio,"thr",thr,"good",len(good),"inl",int(ms.sum()),"scale %.5f rot %.4f t=(%.2f,%.2f)"%(sc,np.degrees(np.arctan2(M[1,0],M[0,0])),M[0,2],M[1,2]))
tries(kw,dw,kn,dn,"west->north")
tries(kw,dw,ks,ds,"west->south")
