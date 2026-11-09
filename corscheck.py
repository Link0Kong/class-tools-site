import urllib.request, urllib.error, json
base='https://tool-d4gosudok46e0e081.api.tcloudbasegateway.com/v1/rdb/rest/'
req=urllib.request.Request(base+'homework?select=id&limit=1', method='OPTIONS', headers={
 'Origin':'https://tool.furina.fun',
 'Access-Control-Request-Method':'GET',
 'Access-Control-Request-Headers':'authorization,content-type,x-acc,x-hash'
})
try:
 r=urllib.request.urlopen(req,timeout=20); print(r.status)
 for k,v in r.headers.items():
  if k.lower().startswith('access-control'): print(k, v)
except urllib.error.HTTPError as e:
 print('HTTP',e.code); print(dict(e.headers))
