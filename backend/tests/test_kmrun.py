"""分批核算的数据库行为：乱序一致、续跑不重算、重试不重复、改截点隔离、齐备一起发布。"""
import types,pytest
from sqlalchemy.exc import IntegrityError
from src.config.database import Base,engine,Session
from src.models import identity,run as run_model
from src.models.run import Run,KmBatch
from src.services import kmrun
from src.services.km import partial_aggregate,finalize_km
from test_km import POLICY,gen

CUTOFF1='2026-11-10T12:00:00+08:00'
CUTOFF2='2026-11-13T12:00:00+08:00'
USER=types.SimpleNamespace(email='admin@demo.local')

@pytest.fixture(autouse=True)
def clean():
 Base.metadata.drop_all(engine);Base.metadata.create_all(engine);yield

def make_run(samples,cutoff=CUTOFF1):
 with Session() as db:
  obj=Run(name='曲线测试',status='completed',snapshot={'policy':POLICY,'sources':samples,'period':'全部'},checksum='x',created=0,approved=False,result={'summary':{},'rows':[]},cutoff=cutoff,km_epoch=1,km_status='queued',km_total=0,km_done=0)
  db.add(obj);db.commit();return obj.id

def run_to_completion(run_id,guard=500):
 with Session() as db:
  for _ in range(guard):
   kmrun.km_tick(db)
   if db.get(Run,run_id).km_status=='completed': return
  raise AssertionError('核算未收敛')

def batches(run_id):
 with Session() as db:
  return db.query(KmBatch).filter(KmBatch.run_id==run_id).order_by(KmBatch.batch_no).all()

def test_batched_curve_matches_whole(monkeypatch):
 monkeypatch.setattr(kmrun,'BATCH_SIZE',60)
 samples=gen(500);rid=make_run(samples)
 run_to_completion(rid)
 with Session() as db:
  run=db.get(Run,rid)
  assert run.km_status=='completed' and run.km_done==9 and run.km_total==9
  want=finalize_km([partial_aggregate(samples,CUTOFF1,POLICY)],CUTOFF1,POLICY['version'],1)
  assert run.result['km']==want
  assert run.result['rows']==[]

def test_resume_does_not_recompute_booked_batches(monkeypatch):
 monkeypatch.setattr(kmrun,'BATCH_SIZE',60)
 samples=gen(500);rid=make_run(samples)
 calls={'n':0};real=kmrun.partial_aggregate
 def counting(*a,**k): calls['n']+=1;return real(*a,**k)
 with Session() as db:
  for _ in range(3): assert kmrun.process_next_batch(db,rid)
 before=[(b.id,b.batch_no,b.created,b.partial) for b in batches(rid)]
 assert len(before)==3 and calls['n']==0
 monkeypatch.setattr(kmrun,'partial_aggregate',counting)
 run_to_completion(rid)
 after=batches(rid)
 assert len(after)==9 and calls['n']==6
 assert [(b.id,b.batch_no,b.created,b.partial) for b in after[:3]]==before
 with Session() as db: assert db.get(Run,rid).result['km']==finalize_km([partial_aggregate(samples,CUTOFF1,POLICY)],CUTOFF1,POLICY['version'],1)

def test_retry_does_not_double_count(monkeypatch):
 monkeypatch.setattr(kmrun,'BATCH_SIZE',60)
 samples=gen(500);rid=make_run(samples)
 with Session() as db:
  assert kmrun.process_next_batch(db,rid)
  assert db.get(Run,rid).km_done==1
  db.add(KmBatch(run_id=rid,epoch=1,batch_no=0,partial={'groups':{},'sampled':0,'skipped':0},created=0))
  with pytest.raises(IntegrityError): db.commit()
 with Session() as db:
  assert kmrun.process_next_batch(db,rid)
  assert db.get(Run,rid).km_done==2
 assert [b.batch_no for b in batches(rid)]==[0,1]

def test_cutoff_change_isolates_epochs(monkeypatch):
 monkeypatch.setattr(kmrun,'BATCH_SIZE',60)
 samples=gen(500);rid=make_run(samples)
 with Session() as db:
  for _ in range(3): kmrun.process_next_batch(db,rid)
  assert db.query(KmBatch).filter_by(run_id=rid).count()==3
 with Session() as db:
  kmrun.set_cutoff(db,USER,rid,CUTOFF2)
  run=db.get(Run,rid)
  assert run.km_epoch==2 and run.km_status=='queued' and run.km_done==0
  assert db.query(KmBatch).filter_by(run_id=rid).count()==0
  assert run.result['km'] is None
 with Session() as db:
  db.add(KmBatch(run_id=rid,epoch=1,batch_no=0,partial={'groups':{'幽灵组':{'1.000000':[999,0]}},'sampled':999,'skipped':0},created=0));db.commit()
 run_to_completion(rid)
 with Session() as db:
  km=db.get(Run,rid).result['km']
  assert km['epoch']==2 and km['cutoff']==CUTOFF2 and '幽灵组' not in km['groups']
  assert km==finalize_km([partial_aggregate(samples,CUTOFF2,POLICY)],CUTOFF2,POLICY['version'],2)

def test_curve_and_denominators_publish_together(monkeypatch):
 monkeypatch.setattr(kmrun,'BATCH_SIZE',60)
 samples=gen(500);rid=make_run(samples)
 with Session() as db:
  for step in range(9):
   assert kmrun.process_next_batch(db,rid)
   run=db.get(Run,rid)
   assert run.km_status=='running' and run.km_done==step+1
   assert (run.result or {}).get('km') is None
  assert not kmrun.process_next_batch(db,rid)
  run=db.get(Run,rid)
  assert run.km_status=='completed'
  km=run.result['km']
  assert km and all('n' in j and 's' in j for g in km['groups'].values() for j in g['jumps'])

def test_clear_cutoff_removes_curve():
 samples=gen(50);rid=make_run(samples)
 run_to_completion(rid)
 with Session() as db:
  assert db.get(Run,rid).result['km']
  kmrun.set_cutoff(db,USER,rid,None)
  run=db.get(Run,rid)
  assert run.km_status=='idle' and run.cutoff is None and 'km' not in run.result
  assert db.query(KmBatch).filter_by(run_id=rid).count()==0
