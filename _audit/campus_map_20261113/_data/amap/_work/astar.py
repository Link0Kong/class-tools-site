import cv2, numpy as np, os, heapq, json, time
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
im=cv2.imread(os.path.join(BASE,"master.png"))
H,W=im.shape[:2]
B=im[:,:,0].astype(np.int16);G=im[:,:,1].astype(np.int16);R=im[:,:,2].astype(np.int16)
mx=im.max(axis=2).astype(np.int16); mn=im.min(axis=2).astype(np.int16)
br=B-R; gr=G-R
m=((mx>=204)&(mx<=243)&(br>=10)&(br<=30)&(gr>=4)&(gr<=20)).astype(np.uint8)
k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(25,25))
big=cv2.morphologyEx(m,cv2.MORPH_OPEN,k)
thin=(m & (1-big)).astype(np.uint8)
thin=cv2.morphologyEx(thin,cv2.MORPH_CLOSE,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3)),iterations=1)
np.save(os.path.join(WORK,"thin.npy"),thin)
dist=cv2.distanceTransform(1-thin,cv2.DIST_L2,5).astype(np.float32)
np.save(os.path.join(WORK,"thin_dist.npy"),dist)
def astar(p0,p1,target=4.0, maxsec=30):
    def snap(p):
        x,y=int(round(p[0])),int(round(p[1]))
        best=None
        for dy in range(-6,7):
            for dx in range(-6,7):
                xx,yy=x+dx,y+dy
                if 0<=xx<W and 0<=yy<H:
                    c=abs(float(dist[yy,xx])-target)
                    if best is None or c<best[0]: best=(c,xx,yy)
        return best[1],best[2]
    sx,sy=snap(p0); gx,gy=snap(p1)
    cost=1.0+np.minimum((dist-target)**2,900)*0.15+np.maximum(dist-10,0)*0.6
    cost=np.minimum(cost,60.0).astype(np.float32)
    INF=np.float32(1e9)
    gscore=np.full((H,W),INF,dtype=np.float32)
    prev=np.full((H,W),-1,dtype=np.int32)
    gscore[sy,sx]=0
    h0=abs(gx-sx)+abs(gy-sy)
    pq=[(h0,0,sx,sy)]
    dirs=[(1,0,1.0),(-1,0,1.0),(0,1,1.0),(0,-1,1.0),(1,1,1.41421),(1,-1,1.41421),(-1,1,1.41421),(-1,-1,1.41421)]
    done=np.zeros((H,W),dtype=bool)
    t0=time.time(); expanded=0
    while pq:
        f,g,x,y=heapq.heappop(pq)
        if done[y,x]: continue
        done[y,x]=True; expanded+=1
        if x==gx and y==gy: break
        if time.time()-t0>maxsec: return None,"timeout"
        for dx,dy,dc in dirs:
            nx,ny=x+dx,y+dy
            if nx<0 or ny<0 or nx>=W or ny>=H or done[ny,nx]: continue
            ng=g+dc*float(cost[ny,nx])
            if ng<gscore[ny,nx]:
                gscore[ny,nx]=ng
                prev[ny,nx]=y*W+x
                h=abs(gx-nx)+abs(gy-ny)
                heapq.heappush(pq,(ng+h,ng,nx,ny))
    if prev[gy,gx]==-1 and not (gx==sx and gy==sy): return None,"nopath"
    path=[]; cx,cy=gx,gy
    while True:
        path.append((cx,cy))
        if cx==sx and cy==sy: break
        p=int(prev[cy,cx])
        if p<0: break
        cx,cy=p%W,p//W
    path.reverse()
    return path, {"expanded":expanded,"secs":time.time()-t0}
if __name__=="__main__":
    tests={
      "xiuyuanbei":[(1050,735),(1400,560),(1750,630),(2000,850),(2200,1050),(2250,1200),(2259,1361)],
      "wangguo_w":[(500,1285),(900,1285),(1250,1285),(1500,1290),(1750,1300)],
      "zhongjing":[(1508,1290),(1512,1400),(1512,1500)],
    }
    for name,pts in tests.items():
        full=[]; info=[]
        ok=True
        for i in range(len(pts)-1):
            path,meta=astar(pts[i],pts[i+1],target=4.0)
            if path is None: print(name,"FAIL",i,meta); ok=False; break
            info.append(meta)
            if full: path=path[1:]
            full+=path
        if ok:
            print(name,"OK points",len(full),"expanded",sum(i['expanded'] for i in info),"secs %.2f"%sum(i['secs'] for i in info))
            np.save(os.path.join(WORK,"path_%s.npy"%name),np.array(full,dtype=np.int32))
        else:
            print(name,"failed")
