"""结单概率曲线的分批核算与发布。

- 批次按冻结快照顺序确定性切分，部分聚合入账 km_batches（run_id+epoch+batch_no 唯一）；
  中断续跑只算缺失批次，不重读已入账底稿；重试撞唯一约束即放弃，不重复计样。
- 截点以 km_epoch 代际隔离：改截点作废旧批次并递增代际，入账/合并只认当前代际，
  并发改截点时旧批不能混入新曲线。
- 分母与曲线齐备后在同一事务写入 run.result['km'] 一起发布；齐备前页面只见进度不见半成品。
"""
import math,os,time
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from src.models.run import Run,KmBatch
from src.services.audit import log
from src.services.km import partial_aggregate,finalize_km
from src.services.validation import validate_cutoff

BATCH_SIZE=int(os.getenv('KM_BATCH_SIZE','2000'))
TICK_BATCHES=int(os.getenv('KM_TICK_BATCHES','5'))

def _plan(run): return max(1,math.ceil(len(run.snapshot['sources'])/BATCH_SIZE))

def set_cutoff(db,user,run_id,cutoff):
 cutoff=validate_cutoff(cutoff)
 run=db.query(Run).filter(Run.id==run_id).with_for_update().first()
 if not run: raise HTTPException(404,'报告不存在')
 run.cutoff=cutoff
 run.km_epoch=(run.km_epoch or 0)+1
 db.query(KmBatch).filter(KmBatch.run_id==run.id).delete()
 run.km_total=0;run.km_done=0;run.km_error=''
 result=dict(run.result) if run.result else None
 if cutoff:
  result=result or {};result['km']=None;run.km_status='queued'
 else:
  run.km_status='idle'
  if result is not None: result.pop('km',None)
 if result is not None: run.result=result
 log(db,user.email,'run.cutoff',f'{run_id} -> {cutoff}')
 db.commit();return run

def process_next_batch(db,run_id):
 """处理一个缺失批次；全部入账后同事务合并发布。返回是否仍有后续工作。"""
 run=db.query(Run).filter(Run.id==run_id).with_for_update().first()
 if not run or run.km_status not in ('queued','running') or not run.cutoff: return False
 epoch=run.km_epoch
 sources=run.snapshot['sources']
 total=_plan(run)
 done={b.batch_no for b in db.query(KmBatch).filter(KmBatch.run_id==run.id,KmBatch.epoch==epoch)}
 if run.km_total!=total: run.km_total=total
 remaining=[i for i in range(total) if i not in done]
 try:
  if remaining:
   i=remaining[0]
   partial=partial_aggregate(sources[i*BATCH_SIZE:(i+1)*BATCH_SIZE],run.cutoff,run.snapshot['policy'])
   db.add(KmBatch(run_id=run.id,epoch=epoch,batch_no=i,partial=partial,created=time.time()))
   run.km_status='running';run.km_done=len(done)+1
   db.commit();return True
  partials=[b.partial for b in db.query(KmBatch).filter(KmBatch.run_id==run.id,KmBatch.epoch==epoch).order_by(KmBatch.batch_no)]
  result=dict(run.result) if run.result else {}
  result['km']=finalize_km(partials,run.cutoff,run.snapshot['policy'].get('version',''),epoch)
  run.result=result;run.km_status='completed';run.km_done=total
  db.commit();return False
 except IntegrityError:
  db.rollback();return True
 except Exception as exc:
  db.rollback()
  with db.begin():
   fresh=db.get(Run,run_id)
   if fresh: fresh.km_status='failed';fresh.km_error=str(exc)
  return False

def km_tick(db):
 ids=[r.id for r in db.query(Run.id).filter(Run.km_status.in_(['queued','running'])).all()]
 for rid in ids:
  for _ in range(TICK_BATCHES):
   if not process_next_batch(db,rid): break
