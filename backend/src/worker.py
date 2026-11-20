import time,json,traceback
from pathlib import Path
import redis
from src.config.database import Base,engine,Session,migrate
from src.config.settings import REDIS_URL
from src.models import identity,source,run
from src.models.run import Run
from src.services.calculation import calculate
from src.services.delivery import tick
from src.services.kmrun import km_tick
Base.metadata.create_all(engine)
migrate()
r=redis.Redis.from_url(REDIS_URL)
while True:
 Path('/tmp/worker-heartbeat').write_text(str(time.time()))
 try:
  item=r.lpop('report-jobs')
  if item:
   with Session() as db:
    job=db.get(Run,int(item))
    if job and job.status=='queued':
     job.status='running';db.commit()
     try:
      res=calculate(job.snapshot['sources'],job.snapshot['policy'])
      if job.result and 'km' in job.result: res['km']=job.result['km']
      job.result=res;job.status='completed'
     except Exception as exc: job.status='failed';job.error=str(exc);traceback.print_exc()
     db.commit()
  with Session() as db: km_tick(db)
  with Session() as db: tick(db)
 except Exception: traceback.print_exc()
 time.sleep(1)
