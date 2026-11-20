from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker,DeclarativeBase
from src.config.settings import DATABASE_URL
class Base(DeclarativeBase): pass
engine=create_engine(DATABASE_URL,pool_pre_ping=True)
Session=sessionmaker(bind=engine,expire_on_commit=False)
def database():
 with Session() as db: yield db
def migrate():
 """为既有数据库补齐结单曲线字段；新库由create_all直接建全。幂等。"""
 from sqlalchemy import inspect,text
 insp=inspect(engine)
 if 'sla_runs' not in insp.get_table_names(): return
 cols={c['name'] for c in insp.get_columns('sla_runs')}
 alters={'cutoff':"ALTER TABLE sla_runs ADD COLUMN cutoff VARCHAR(40)",'km_epoch':"ALTER TABLE sla_runs ADD COLUMN km_epoch INTEGER DEFAULT 0",'km_status':"ALTER TABLE sla_runs ADD COLUMN km_status VARCHAR(20) DEFAULT 'idle'",'km_total':"ALTER TABLE sla_runs ADD COLUMN km_total INTEGER DEFAULT 0",'km_done':"ALTER TABLE sla_runs ADD COLUMN km_done INTEGER DEFAULT 0",'km_error':"ALTER TABLE sla_runs ADD COLUMN km_error TEXT"}
 with engine.begin() as conn:
  for col,ddl in alters.items():
   if col not in cols: conn.execute(text(ddl))
