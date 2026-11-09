"""Exercises the pure-HTTP Turso (Hrana) driver against a local fake server (no network/credentials)."""
import asyncio, base64, json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

STORE = {}

class Fake(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_POST(self):
        assert self.path == '/v2/pipeline' and self.headers['Authorization'] == 'Bearer tok'
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        results = []
        for r in body['requests']:
            if r['type'] == 'close': results.append({'type': 'ok', 'response': {'type': 'close'}}); continue
            sql = r['stmt']['sql'].strip().upper(); args = r['stmt']['args']
            res = {'cols': [], 'rows': [], 'affected_row_count': 0}
            if sql.startswith('INSERT'):
                STORE[args[0]['value']] = args; res['affected_row_count'] = 1
            elif sql.startswith('SELECT'):
                a = STORE.get(args[0]['value'])
                if a:
                    res['cols'] = [{'name': 'id'}, {'name': 'file_size'}, {'name': 'file_blob'}]
                    blob = a[5]['base64'].rstrip('=')  # Hrana may return unpadded base64
                    res['rows'] = [[a[0], {'type': 'integer', 'value': a[4]['value']}, {'type': 'blob', 'base64': blob}]]
            elif sql.startswith('DELETE'):
                res['affected_row_count'] = 1 if STORE.pop(args[0]['value'], None) else 0
            results.append({'type': 'ok', 'response': {'type': 'execute', 'result': res}})
        out = json.dumps({'results': results}).encode()
        self.send_response(200); self.send_header('Content-Length', str(len(out))); self.end_headers(); self.wfile.write(out)

def test_blob_roundtrip_over_http():
    from backend.app import database
    srv = HTTPServer(('127.0.0.1', 0), Fake); threading.Thread(target=srv.serve_forever, daemon=True).start()
    s = database.get_settings(); old = (s.turso_database_url, s.turso_auth_token)
    s.turso_database_url = f'http://127.0.0.1:{srv.server_port}'; s.turso_auth_token = 'tok'
    d = database.Database()
    data = bytes(range(256)) * 3 + b'\x00\xff'
    async def run():
        await d.execute('INSERT INTO files VALUES(?,?,?,?,?,?)', ('abc', 'a.png', 'abc.png', 'image/png', len(data), data))
        row = await d.fetchone('SELECT id,file_size,file_blob FROM files WHERE id=?', ('abc',))
        assert row['file_blob'] == data and row['file_size'] == len(data)
        assert await d.fetchone('SELECT id FROM files WHERE id=?', ('nope',)) is None
        assert await d.execute('DELETE FROM files WHERE id=?', ('abc',)) == 1
    try: asyncio.run(run())
    finally: s.turso_database_url, s.turso_auth_token = old; srv.shutdown()
