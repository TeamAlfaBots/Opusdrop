import io

def test_oversize(client,monkeypatch):
 from backend.app.routes import files
 monkeypatch.setattr(files.get_settings(),'max_file_size',10)
 r=client.post('/api/upload',files={'file':('a.txt',io.BytesIO(b'x'*11),'text/plain')})
 assert r.status_code==413
