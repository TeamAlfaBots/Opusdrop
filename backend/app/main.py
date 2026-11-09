import logging,time
from collections import defaultdict,deque
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse,JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from .config import get_settings
from .database import db,DatabaseUnavailable,StorageLimit
from .routes.files import router,serve

s=get_settings(); buckets=defaultdict(deque); log=logging.getLogger('opusdrop')
UNITS={'second':1,'minute':60,'hour':3600,'day':86400}
def parse_limit(v,default):
    try:n,u=v.strip().lower().split('/');return int(n),UNITS[u.rstrip('s')]
    except Exception:return default
UPLOAD_LIMIT=parse_limit(s.upload_rate_limit,(20,3600)); READ_LIMIT=parse_limit(s.download_rate_limit,(300,3600))

def client_ip(request):
    h=request.headers  # Vercel/Render set these at the edge; the first hop is the real client
    return (h.get('x-real-ip') or h.get('x-forwarded-for','').split(',')[0].strip() or (request.client.host if request.client else 'unknown'))

class SecurityMiddleware(BaseHTTPMiddleware):
 async def dispatch(self,request,call_next):
  if request.method=='POST' and request.url.path=='/api/upload':
   try:cl=int(request.headers.get('content-length') or 0)
   except ValueError:return JSONResponse({'error':{'code':'bad_request','message':'Invalid Content-Length'}},400)
   if cl>s.max_file_size+65_536:return JSONResponse({'error':{'code':'file_too_large','message':f'Maximum file size is {s.max_file_mb:g} MB'}},413)
  kind='upload' if request.method=='POST' else 'read'
  limit,window=UPLOAD_LIMIT if kind=='upload' else READ_LIMIT
  key=(client_ip(request),kind); now=time.monotonic(); q=buckets[key]
  while q and q[0]<now-window:q.popleft()
  if len(q)>=limit:return JSONResponse({'error':{'code':'rate_limited','message':'Too many requests'}},429,headers={'Retry-After':str(window)})
  q.append(now);resp=await call_next(request)
  resp.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer','Permissions-Policy':'camera=(), microphone=(), geolocation=()','X-Frame-Options':'DENY'})
  return resp

@asynccontextmanager
async def lifespan(app):
 try:await db.connect()
 except DatabaseUnavailable as e:log.error('Database not ready at startup (will retry on first request): %s',e)
 yield;await db.close()
app=FastAPI(title='OpusDrop API',version='1.0.0',lifespan=lifespan,docs_url='/api/docs',openapi_url='/api/openapi.json')
app.add_middleware(SecurityMiddleware)
app.add_middleware(CORSMiddleware,allow_origins=s.origins,allow_credentials=False,allow_methods=['GET','POST','DELETE'],allow_headers=['Content-Type','X-Deletion-Token'])
app.include_router(router,prefix='/api')

@app.exception_handler(DatabaseUnavailable)
async def _db_down(request,exc):
 log.error('database unavailable: %s',exc);return JSONResponse({'error':{'code':'database_unavailable','message':'Storage is temporarily unavailable'}},503)
@app.exception_handler(StorageLimit)
async def _db_full(request,exc):
 log.error('storage limit: %s',exc);return JSONResponse({'error':{'code':'storage_limit','message':'Database storage or transaction limit reached'}},507)

@app.get('/api/health')
async def health():return {'status':'ok','service':'OpusDrop'}
@app.get('/file/{file_id}')
async def direct(file_id:str,request:Request):return await serve(file_id,request,False)
@app.get('/download/{file_id}')
async def download(file_id:str,request:Request):return await serve(file_id,request,True)

# Local / Render single-origin mode: serve the static Next.js export. On Vercel the CDN serves it instead.
static=Path(__file__).parents[2]/'frontend'/'out'
@app.get('/preview/{file_id}')
async def preview_page(file_id:str):
 p=static/'preview'/'index.html';return FileResponse(p) if p.exists() else JSONResponse({'error':'Frontend not built'},503)
@app.get('/{path:path}')
async def spa(path:str):
 p=(static/path).resolve()
 if static.resolve() in p.parents and p.is_file():return FileResponse(p)
 if static.resolve() in p.parents or p==static.resolve():
  if (p/'index.html').is_file():return FileResponse(p/'index.html')
 index=static/'index.html';return FileResponse(index) if index.exists() else JSONResponse({'service':'OpusDrop API','docs':'/api/docs'})
