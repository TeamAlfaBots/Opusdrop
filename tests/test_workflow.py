import io

def up(client,name,data,mime):return client.post('/api/upload',files={'file':(name,io.BytesIO(data),mime)})
def test_guest_text_workflow_and_delete(client):
 r=up(client,'note.txt',b'hello opus','text/plain');assert r.status_code==201
 b=r.json(); fid=b['id']; token=b['deletion_token']
 assert client.get(f'/file/{fid}').content==b'hello opus'
 assert client.get(f'/api/files/{fid}').status_code==200
 assert client.get(f'/api/files/{fid}/preview').json()['text']=='hello opus'
 d=client.get(f'/download/{fid}');assert 'attachment' in d.headers['content-disposition']
 assert client.delete(f'/api/files/{fid}',headers={'X-Deletion-Token':'wrong'}).status_code==403
 assert client.delete(f'/api/files/{fid}',headers={'X-Deletion-Token':token}).status_code==204
 assert client.get(f'/file/{fid}').status_code==404

def test_image(client):
 data=b'\x89PNG\r\n\x1a\n'+b'x'*50
 assert up(client,'pic.png',data,'image/png').status_code==201

def test_video_range(client):
 data=b'\x00\x00\x00\x18ftypisom'+b'x'*100
 r=up(client,'movie.mp4',data,'video/mp4');assert r.status_code==201
 x=client.get('/file/'+r.json()['id'],headers={'Range':'bytes=4-11'})
 assert x.status_code==206 and x.content==data[4:12] and 'content-range' in x.headers

def test_rejections(client):
 assert up(client,'bad.html',b'<h1>x</h1>','text/html').status_code==415
 assert up(client,'fake.png',b'not png','image/png').status_code==415
 assert up(client,'x.json',b'{bad}','application/json').status_code==415

def test_not_found_and_health(client):
 assert client.get('/api/health').status_code==200
 assert client.get('/file/missing').status_code==404
