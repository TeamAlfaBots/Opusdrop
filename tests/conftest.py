import os
os.environ['TURSO_DATABASE_URL']='file:test-opusdrop.db'
os.environ['MAX_FILE_SIZE']='26214400'
import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
@pytest.fixture
def client(tmp_path,monkeypatch):
 from backend.app import database
 database.db.conn=None; database.db.http=None; database.db.ready=False
 monkeypatch.setattr(database.get_settings(),'turso_database_url',f'file:{tmp_path}/test.db')
 with TestClient(app) as c:yield c
