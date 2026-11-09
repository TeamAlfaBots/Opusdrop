import asyncio, csv, io, json, re
from pathlib import Path
from urllib.parse import quote
from fastapi import APIRouter, File, Header, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from ..config import get_settings
from ..database import db, DatabaseUnavailable, StorageLimit
from ..security.files import new_file_id,new_delete_token,token_hash,verify_token
from ..services.validation import validate
from ..utils.responses import error

router=APIRouter()
upload_slots=asyncio.Semaphore(get_settings().max_concurrent_uploads)
META="id,original_filename,mime_type,file_size,created_at,updated_at"

def links(request,id):
    base=get_settings().public_base_url.rstrip('/')
    if not base:
        h=request.headers; proto=h.get('x-forwarded-proto','').split(',')[0].strip() or request.url.scheme
        host=h.get('x-forwarded-host','').split(',')[0].strip() or h.get('host') or request.url.netloc
        base=f'{proto}://{host}'
    return {'direct':f'{base}/file/{id}','preview':f'{base}/preview/{id}','download':f'{base}/download/{id}'}
def safe_name(name): return Path(name.replace('\\','/')).name[:255] or 'file'

@router.post('/upload',status_code=201)
async def upload(request:Request, file:UploadFile=File(...)):
    s=get_settings()
    async with upload_slots:
        chunks=[]; total=0
        while chunk:=await file.read(1024*1024):
            total+=len(chunk)
            if total>s.max_file_size: return error(413,'file_too_large',f'Maximum file size is {s.max_file_mb:g} MB')
            chunks.append(chunk)
        data=b''.join(chunks); name=safe_name(file.filename or 'file')
        if not data:return error(400,'empty_file','Empty files are not accepted')
        try: mime=validate(name,file.content_type or '',data)
        except ValueError as e:return error(415,str(e),'The file extension, MIME type, or signature is invalid')
        fid=new_file_id(); token=new_delete_token()
        try:
            await db.execute("INSERT INTO files(id,original_filename,stored_filename,mime_type,file_size,file_blob,deletion_token_hash) VALUES(?,?,?,?,?,?,?)",
             (fid,name,f'{fid}{Path(name).suffix.lower()}',mime,total,data,token_hash(token)))
        except StorageLimit:return error(507,'storage_limit','Database storage or transaction limit reached')
        except DatabaseUnavailable:return error(503,'database_unavailable','Storage is temporarily unavailable')
        return {'id':fid,'filename':name,'mime_type':mime,'size':total,'links':links(request,fid),'deletion_token':token,
          'deletion_warning':'Save this token now. It is shown only once and cannot be recovered.'}

@router.get('/files/{file_id}')
async def metadata(request:Request,file_id:str):
    row=await db.fetchone(f'SELECT {META} FROM files WHERE id=?',(file_id,))
    if not row:return error(404,'not_found','File not found')
    row['links']=links(request,file_id);return row

async def get_blob(file_id): return await db.fetchone(f'SELECT {META},file_blob FROM files WHERE id=?',(file_id,))

def content_headers(row,disposition):
    name=re.sub(r'[\x00-\x1f\x7f"]','',row['original_filename']) or 'file'
    ascii_name=re.sub(r'[^A-Za-z0-9._-]','_',name)
    return {'Content-Disposition':f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}", 'X-Content-Type-Options':'nosniff',
      'Cache-Control':'public, max-age=3600, s-maxage=3600','Accept-Ranges':'bytes'}

async def serve(file_id,request,download=False):
    try: row=await get_blob(file_id)
    except DatabaseUnavailable:return error(503,'database_unavailable','Storage is temporarily unavailable')
    if not row:return error(404,'not_found','File not found')
    data=bytes(row.pop('file_blob')); headers=content_headers(row,'attachment' if download else 'inline')
    rng=request.headers.get('range')
    if rng:
        m=re.fullmatch(r'bytes=(\d*)-(\d*)',rng)
        if not m:return Response(status_code=416,headers={'Content-Range':f'bytes */{len(data)}'})
        a,b=m.group(1),m.group(2)
        if not a and not b:return Response(status_code=416,headers={'Content-Range':f'bytes */{len(data)}'})
        if not a: start=max(len(data)-int(b),0); end=len(data)-1
        else: start=int(a); end=int(b) if b else len(data)-1
        if start>=len(data) or end<start:return Response(status_code=416,headers={'Content-Range':f'bytes */{len(data)}'})
        end=min(end,len(data)-1);headers['Content-Range']=f'bytes {start}-{end}/{len(data)}';headers['Content-Length']=str(end-start+1)
        return Response(data[start:end+1],206,media_type=row['mime_type'],headers=headers)
    headers['Content-Length']=str(len(data));return Response(data,media_type=row['mime_type'],headers=headers)

@router.get('/files/{file_id}/download')
async def api_download(file_id:str,request:Request):return await serve(file_id,request,True)
@router.get('/files/{file_id}/raw')
async def api_raw(file_id:str,request:Request):return await serve(file_id,request,False)
@router.get('/files/{file_id}/preview')
async def preview(file_id:str,request:Request):
    row=await db.fetchone(f'SELECT {META} FROM files WHERE id=?',(file_id,))
    if not row:return error(404,'not_found','File not found')
    row['links']=links(request,file_id)
    if row['mime_type'].startswith(('text/','application/json')):
        full=await get_blob(file_id)
        if not full:return error(404,'not_found','File not found')
        data=bytes(full['file_blob'])
        text=data[:1_048_576].decode('utf-8','replace');row['text']=text;row['truncated']=len(data)>1_048_576
        if row['mime_type']=='application/json':
            try:row['json']=json.loads(text)
            except Exception:pass
        elif row['mime_type']=='text/csv': row['csv']=list(csv.reader(io.StringIO(text)))[:200]
    return row

@router.delete('/files/{file_id}')
async def delete(file_id:str,x_deletion_token:str|None=Header(None)):
    if not x_deletion_token:return error(401,'token_required','X-Deletion-Token header is required')
    row=await db.fetchone('SELECT deletion_token_hash FROM files WHERE id=?',(file_id,))
    if not row:return error(404,'not_found','File not found')
    if not verify_token(x_deletion_token,row['deletion_token_hash']):return error(403,'invalid_token','Deletion token is incorrect')
    await db.execute('DELETE FROM files WHERE id=?',(file_id,));return Response(status_code=204)
