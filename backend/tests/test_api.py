"""端到端：登录→底稿/口径→带截点核算→worker分批→曲线发布→换截点→跳点CSV。"""
import types,pytest
from fastapi.testclient import TestClient
from src.config.database import Base,engine,Session
from src.models import identity,source,run as run_model
from src.models.identity import User
from src.models.source import Source,Policy
from src.models.run import Run
from src.utils.security import password_hash
from src.services import kmrun
from src.services.calculation import calculate
from test_km import POLICY,gen

class FakeRedis:
 def rpush(self,*a): return 1
 @classmethod
 def from_url(cls,*a,**k): return cls()

@pytest.fixture(autouse=True)
def clean():
 Base.metadata.drop_all(engine);Base.metadata.create_all(engine);yield

@pytest.fixture
def client(monkeypatch):
 monkeypatch.setattr('src.services.report.redis.Redis.from_url',FakeRedis.from_url)
 import src.main as main
 with TestClient(main.app) as c:
  with Session() as db:
   db.add(User(email='admin@demo.local',role='admin',password=password_hash('Demo2026!')))
   db.add(User(email='viewer@demo.local',role='viewer',password=password_hash('Demo2026!')))
   db.add(Policy(version=POLICY['version'],data=POLICY))
   for i,s in enumerate(gen(120)):
    db.add(Source(natural_key=f't-{i}',data=s))
   db.commit()
  yield c

def login(client,email):
 r=client.post('/auth/login',json={'email':email,'password':'Demo2026!'})
 assert r.status_code==200,r.text
 return {'Authorization':'Bearer '+r.json()['token']}

def finish_km(run_id):
 with Session() as db:
  for _ in range(500):
   kmrun.km_tick(db)
   if db.get(Run,run_id).km_status=='completed': return
  raise AssertionError('未收敛')

def test_full_curve_flow(client,monkeypatch):
 monkeypatch.setattr(kmrun,'BATCH_SIZE',50)
 admin=login(client,'admin@demo.local')
 r=client.post('/runs',json={'name':'十一月中核算','policy_id':1,'period':'全部','cutoff':'2026-11-13T12:00:00+08:00'},headers=admin)
 assert r.status_code==200,r.text
 run=r.json()
 assert run['km_status']=='queued' and run['cutoff']=='2026-11-13T12:00:00+08:00'
 with Session() as db:
  obj=db.get(Run,run['id']);obj.result=calculate(obj.snapshot['sources'],obj.snapshot['policy']);obj.status='completed';db.commit()
  assert 'km' not in (obj.result or {})
 finish_km(run['id'])
 r=client.get('/runs/'+str(run['id']),headers=admin)
 km=r.json()['result']['km']
 assert km['cutoff']=='2026-11-13T12:00:00+08:00' and km['sampled']>0
 jumps=[j for g in km['groups'].values() for j in g['jumps']]
 assert jumps and all(j['n']>=j['d']+j['c'] for j in jumps)
 r=client.post('/runs/'+str(run['id'])+'/cutoff',json={'cutoff':'2026-11-16T12:00:00+08:00'},headers=admin)
 assert r.status_code==200 and r.json()['km_status']=='queued'
 r=client.get('/runs/'+str(run['id']),headers=admin)
 assert r.json()['result']['km'] is None
 finish_km(run['id'])
 r=client.get('/runs/'+str(run['id']),headers=admin)
 km2=r.json()['result']['km']
 assert km2['cutoff']=='2026-11-16T12:00:00+08:00' and km2['epoch']==2 and km2['sampled']>=km['sampled']
 r=client.post('/runs/'+str(run['id'])+'/approve',json={'note':'曲线与分母已核对'},headers=admin)
 assert r.status_code==200
 viewer=login(client,'viewer@demo.local')
 r=client.get('/runs/'+str(run['id'])+'/km.csv',headers=viewer)
 assert r.status_code==200 and '分母（仍在观察）' in r.text
 r=client.post('/runs/'+str(run['id'])+'/cutoff',json={'cutoff':'2026-11-17T12:00:00+08:00'},headers=viewer)
 assert r.status_code==403

def test_cutoff_validation_error(client):
 admin=login(client,'admin@demo.local')
 r=client.post('/runs',json={'name':'无截点核算','policy_id':1,'period':'全部'},headers=admin)
 assert r.status_code==200 and r.json()['km_status']=='idle'
 r=client.post('/runs/'+str(r.json()['id'])+'/cutoff',json={'cutoff':'2026-11-13 12:00'},headers=admin)
 assert r.status_code==422
