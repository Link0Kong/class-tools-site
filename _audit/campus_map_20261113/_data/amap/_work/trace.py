import cv2, numpy as np, os, heapq, json, time
BASE = r"C:\Users\Ko_Li\.openclaw\workspace\web\_audit\campus_map_20261113\_data\amap"
WORK = os.path.join(BASE,"_work")
im=cv2.imread(os.path.join(BASE,"master.png")); H,W=im.shape[:2]
dist=np.load(os.path.join(WORK,"thin_dist.npy"))
DIRS=[(1,0,1.0),(-1,0,1.0),(0,1,1.0),(0,-1,1.0),(1,1,1.41421),(1,-1,1.41421),(-1,1,1.41421),(-1,-1,1.41421)]
def build_cost(target):
    c=1.0+np.minimum((dist-target)**2,900.0)*0.15+np.maximum(dist-10.0,0.0)*0.6
    return np.minimum(c,60.0).astype(np.float32)
def snap(x,y,target,r=7):
    x=int(round(x)); y=int(round(y)); best=None
    for dy in range(-r,r+1):
        for dx in range(-r,r+1):
            xx,yy=x+dx,y+dy
            if 0<=xx<W and 0<=yy<H:
                c=abs(float(dist[yy,xx])-target)
                if best is None or c<best[0]: best=(c,xx,yy)
    return best[1],best[2]
def astar(p0,p1,target,maxsec=20.0):
    cost=build_cost(target)
    sx,sy=snap(*p0,target); gx,gy=snap(*p1,target)
    INF=1e9
    gs=np.full((H,W),INF,dtype=np.float32)
    prev=np.full((H,W),-1,dtype=np.int64)
    gs[sy,sx]=0.0
    pq=[(abs(gx-sx)+abs(gy-sy),0.0,sx,sy)]
    done=np.zeros((H,W),dtype=bool)
    t0=time.time(); n=0
    while pq:
        f,g,x,y=heapq.heappop(pq)
        if done[y,x]: continue
        done[y,x]=True; n+=1
        if x==gx and y==gy:
            break
        if n%200000==0 and time.time()-t0>maxsec: return None,"timeout"
        for dx,dy,dc in DIRS:
            nx,ny=x+dx,y+dy
            if nx<0 or ny<0 or nx>=W or ny>=H or done[ny,nx]: continue
            ng=g+dc*float(cost[ny,nx])
            if ng<gs[ny,nx]:
                gs[ny,nx]=ng; prev[ny,nx]=y*W+x
                heapq.heappush(pq,(ng+abs(gx-nx)+abs(gy-ny),ng,nx,ny))
    if prev[gy,gx]<0 and (gx!=sx or gy!=sy): return None,"nopath"
    path=[]; cx,cy=gx,gy
    while True:
        path.append((cx,cy))
        if cx==sx and cy==sy: break
        p=int(prev[cy,cx])
        if p<0: break
        cx,cy=p%W,p//W
    path.reverse()
    return path,{"n":n,"secs":time.time()-t0}
def simplify(path,eps=2.5,min_step=45,max_step=120):
    arr=np.array(path,dtype=np.float32).reshape(-1,1,2)
    ap=cv2.approxPolyDP(arr,eps,False).reshape(-1,2)
    # resample: ensure spacing in [min_step,max_step]
    out=[ap[0]]
    for i in range(1,len(ap)):
        p=out[-1]; q=ap[i]
        d=np.linalg.norm(q-p)
        if d>max_step:
            nseg=int(np.ceil(d/max_step))
            for k in range(1,nseg):
                out.append(p+(q-p)*k/nseg)
        out.append(q)
    # merge if too close
    res=[out[0]]
    for p in out[1:]:
        if np.linalg.norm(p-res[-1])>=min_step or p is out[-1]:
            res.append(p)
    if len(res)<2: res=out
    return [[round(float(x),1),round(float(y),1)] for x,y in res]
draft=json.load(open(os.path.join(WORK,"roads_draft.json"),encoding='utf-8'))
paths={}
for road in draft:
    name=road["name"]; target=road["target"]; via=road["via"]
    if len(via)<2: continue
    full=[]; ok=True; infos=[]
    for i in range(len(via)-1):
        p,meta=astar(via[i],via[i+1],target)
        if p is None:
            print(name,"FAIL seg",i,via[i],via[i+1],meta); ok=False; break
        infos.append(meta)
        if full: p=p[1:]
        full+=p
    if ok and len(full)>5:
        simp=simplify(full)
        paths[name]={"raw":len(full),"simplified":simp}
        print("%-8s OK raw=%d simp=%d expanded=%d secs=%.1f"%(name,len(full),len(simp),sum(x['n'] for x in infos),sum(x['secs'] for x in infos)))
    else:
        print(name,"FAILED")
json.dump(paths,open(os.path.join(WORK,"traced_paths.json"),"w"),ensure_ascii=False,indent=1)
print("saved",len(paths),"roads")
