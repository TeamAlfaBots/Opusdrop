from pathlib import Path
import json

EXT_MIME={
 '.jpg':{'image/jpeg'},'.jpeg':{'image/jpeg'},'.png':{'image/png'},'.gif':{'image/gif'},
 '.webp':{'image/webp'},'.avif':{'image/avif'},'.mp4':{'video/mp4'},'.webm':{'video/webm'},
 '.mov':{'video/quicktime'},'.txt':{'text/plain'},'.md':{'text/markdown','text/plain'},
 '.json':{'application/json','text/json'},'.csv':{'text/csv','application/csv','text/plain'},'.log':{'text/plain'} }

def _signature(data:bytes, ext:str):
    if ext in ('.jpg','.jpeg'): return data.startswith(b'\xff\xd8\xff')
    if ext=='.png': return data.startswith(b'\x89PNG\r\n\x1a\n')
    if ext=='.gif': return data.startswith((b'GIF87a',b'GIF89a'))
    if ext=='.webp': return len(data)>=12 and data[:4]==b'RIFF' and data[8:12]==b'WEBP'
    if ext=='.avif': return len(data)>=12 and data[4:8]==b'ftyp' and b'avif' in data[8:32]
    if ext in ('.mp4','.mov'): return len(data)>=12 and data[4:8]==b'ftyp'
    if ext=='.webm': return data.startswith(b'\x1a\x45\xdf\xa3')
    try: data[:8192].decode('utf-8')
    except UnicodeDecodeError: return False
    if b'\x00' in data[:8192]: return False
    if ext=='.json':
        try: json.loads(data.decode('utf-8'))
        except Exception: return False
    return True

def validate(filename:str, declared:str, data:bytes):
    ext=Path(filename).suffix.lower()
    if ext not in EXT_MIME: raise ValueError('unsupported_type')
    if declared and declared.lower().split(';')[0] not in EXT_MIME[ext]: raise ValueError('mime_mismatch')
    if not _signature(data,ext): raise ValueError('signature_mismatch')
    return next(iter(EXT_MIME[ext])) if ext not in ('.md','.csv') else ({'.md':'text/markdown','.csv':'text/csv'}[ext])
