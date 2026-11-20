import pathlib, sqlite3, json, warnings, csv, io, tempfile
from unittest.mock import patch
from fastapi.testclient import TestClient
from backend.app.db import database as db
from backend.app import main as m
c=TestClient(m.app,raise_server_exceptions=False)
for route in m.app.routes:
 if 'GET' not in getattr(route,'methods',set()) or route.path.startswith(('/docs','/redoc','/openapi')): continue
 path=route.path.replace('{filename}','extract_features.log' if 'logs' in route.path else 'missing.pcapng')
 a=c.get(path)
 print('GET',path,a.status_code,len(a.content))
for case in ('rf_multiclass','rf_binary','iso_forest','invalid'):
 a=c.post('/api/ciciot/replay',json=dict(attack_label='BenignTraffic',model_type=case))
 print('REPLAY',case,a.status_code,{k:v for k,v in a.json().items() if k!='features_sample'})
a=c.post('/api/ciciot/replay',json=dict(attack_label='no-such-label'))
print('REPLAY unknown label',a.status_code,a.json().get('ground_truth'))
for i in range(8):
 a=c.post('/api/simulator/trigger',json={'scenario':f'TH{i}'})
 print('SIM',i,a.status_code,{k:v for k,v in a.json().items() if k not in ('features','evaluated_at')})
with tempfile.TemporaryDirectory() as d:
 with patch.object(m,'ARTIFACTS_DIR',d), patch.dict(m.models_cache,{},clear=True):
  m.load_models()
  for url, data in [('/api/ciciot/replay',dict(attack_label='BenignTraffic')),('/api/simulator/trigger',dict(scenario='TH4'))]:
   a=c.post(url,json=data); print('MISSING',url,a.status_code,a.json())
  pathlib.Path(d,'local_iso_forest.joblib').write_bytes(b'invalid')
  pathlib.Path(d,'local_training_report.json').write_bytes(b'invalid')
  print('CORRUPT',c.post('/api/simulator/trigger',json={'scenario':'TH0'}).status_code,c.get('/api/local/report').status_code)
with patch.object(m.publish,'single',return_value=None) as p:
 a=c.post('/api/devices/unknown/control',json={'scenario':'invalid'})
 print('CONTROL mock',a.status_code,a.json(),p.call_count)
with patch.object(m.publish,'single',side_effect=ConnectionRefusedError('mock broker down')):
 a=c.post('/api/devices/esp32_01/control',json={'scenario':'TH0'})
 print('CONTROL broker down',a.status_code,a.json(),c.get('/api/system/status').json()['mqtt_broker'])
conn=db.get_db_connection()
for t in ['devices','alerts','windows','experiments','system_events','packet_logs']:
 print('DB',t,conn.execute(f'select count(*) from {t}').fetchone()[0])
print('DB journal/check',conn.execute('pragma journal_mode').fetchone()[0],conn.execute('pragma integrity_check').fetchone()[0])
conn.execute('BEGIN EXCLUSIVE')
def short_connection():
 a=sqlite3.connect(db.DB_PATH,timeout=0.1); a.row_factory=sqlite3.Row; return a
with patch.object(m,'get_db_connection',short_connection):
 print('LOCK /api/windows',c.get('/api/windows').status_code)
conn.rollback(); conn.close()
print('CSV header',c.get('/api/windows/export-csv').content.decode('utf-8-sig').splitlines()[0])
for limit in [-1,0,100000]:
 print('LIMIT',limit,c.get(f'/api/windows?limit={limit}').status_code)
with tempfile.TemporaryDirectory() as d:
 p=pathlib.Path(d,'fixture.pcapng'); p.write_bytes(pathlib.Path('data/sessions/batch_01/TH0_Normal.pcapng').read_bytes())
 with patch.object(m,'CAPTURES_DIR',d):
  a=c.get('/api/captures/download/fixture.pcapng'); print('DOWNLOAD fixture',a.status_code,a.content==p.read_bytes())
