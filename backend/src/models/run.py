from sqlalchemy import Column,Integer,String,JSON,Text,Float,Boolean,UniqueConstraint
from src.config.database import Base
class Run(Base):
 __tablename__='sla_runs'
 id=Column(Integer,primary_key=True); name=Column(String(120)); status=Column(String(20)); snapshot=Column(JSON); checksum=Column(String(64)); result=Column(JSON); error=Column(Text); created=Column(Float); approved=Column(Boolean,default=False); review=Column(Text,default='')
 cutoff=Column(String(40)); km_epoch=Column(Integer,default=0); km_status=Column(String(20),default='idle'); km_total=Column(Integer,default=0); km_done=Column(Integer,default=0); km_error=Column(Text,default='')
class KmBatch(Base):
 __tablename__='km_batches'
 id=Column(Integer,primary_key=True); run_id=Column(Integer,index=True); epoch=Column(Integer); batch_no=Column(Integer); partial=Column(JSON); created=Column(Float)
 __table_args__=(UniqueConstraint('run_id','epoch','batch_no',name='uq_km_batch'),)
class Schedule(Base):
 __tablename__='delivery_schedules'
 id=Column(Integer,primary_key=True); name=Column(String(120)); run_id=Column(Integer); interval_seconds=Column(Integer); next_at=Column(Float); enabled=Column(Boolean,default=True)
class Delivery(Base):
 __tablename__='deliveries'
 id=Column(Integer,primary_key=True); schedule_id=Column(Integer); run_id=Column(Integer); due_key=Column(String(120),unique=True); created=Column(Float); payload=Column(JSON)
