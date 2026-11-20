"""结单概率曲线核心口径测试：手算oracle、边界、分批乱序与整批一致。"""
import random
from src.services.km import classify,partial_aggregate,merge_partials,build_curves,finalize_km
from src.services.calculation import calculate
from src.services.validation import validate_source,validate_cutoff

POLICY={'version':'测试口径','timezone':'Asia/Shanghai','weekdays':[0,1,2,3,4],'windows':[[540,720],[780,1080]],'holidays':['2026-11-16'],'sla_minutes':{'普通':480,'紧急':120}}
def s(dept,opened,closed,priority='普通'):
 return {'period':'2026-11','department':dept,'opened':opened,'closed':closed,'priority':priority}
def whole(samples,cutoff):
 return finalize_km([partial_aggregate(samples,cutoff,POLICY)],cutoff,POLICY['version'],1)
def batched(samples,cutoff,size,order=None):
 parts=[partial_aggregate(samples[i:i+size],cutoff,POLICY) for i in range(0,len(samples),size)]
 if order: parts=[parts[i] for i in order]
 return finalize_km(parts,cutoff,POLICY['version'],1)

def test_same_minute_event_before_censor():
 """同一业务分钟：先记结单（分母含本分钟删失样本），再移出删失。"""
 samples=[s('G','2026-11-02T09:00:00+08:00','2026-11-02T10:00:00+08:00'),
  s('G','2026-11-02T09:00:00+08:00','2026-11-02T10:00:00+08:00'),
  s('G','2026-11-02T09:00:00+08:00',None),
  s('G','2026-11-02T09:00:00+08:00','2026-11-02T11:00:00+08:00')]
 g=whole(samples,'2026-11-02T11:00:00+08:00')['groups']['G']
 assert g['jumps']==[{'t':60.0,'n':4,'d':2,'c':0,'s':0.5},{'t':120.0,'n':2,'d':1,'c':1,'s':0.25}]
 assert (g['sampled'],g['events'],g['censored'])==(4,3,1)

def test_cutoff_membership_and_censoring():
 """截点前已开单都入样；未结单只随访到截点；恰在截点开/结单按入样/结单处理。"""
 cutoff='2026-11-09T10:00:00+08:00'
 assert classify('2026-11-09T10:00:01+08:00',None,cutoff,POLICY) is None
 assert classify('2026-11-09T10:00:00+08:00',None,cutoff,POLICY)==('censored',0.0)
 assert classify('2026-11-09T09:00:00+08:00','2026-11-09T10:00:00+08:00',cutoff,POLICY)==('event',60.0)
 assert classify('2026-11-09T09:00:00+08:00','2026-11-09T11:00:00+08:00',cutoff,POLICY)==('censored',60.0)
 assert classify('2026-11-09T09:00:00+08:00',None,cutoff,POLICY)==('censored',60.0)

def test_business_minutes_across_lunch_weekend_holiday():
 """删失时间按口径日历计业务分钟：午休、周末、假日不计时长。"""
 assert classify('2026-11-02T11:00:00+08:00',None,'2026-11-02T14:00:00+08:00',POLICY)==('censored',120.0)
 assert classify('2026-11-06T16:00:00+08:00',None,'2026-11-09T10:00:00+08:00',POLICY)==('censored',180.0)
 assert classify('2026-11-13T16:00:00+08:00',None,'2026-11-17T10:00:00+08:00',POLICY)==('censored',180.0)

def test_zero_duration_jump():
 """t=0跳点：恰在截点开单未结（删失）与即开即结（事件）同分钟，分母含两者。"""
 samples=[s('G','2026-11-02T09:00:00+08:00','2026-11-02T09:00:00+08:00'),s('G','2026-11-02T09:00:00+08:00',None)]
 g=whole(samples,'2026-11-02T09:00:00+08:00')['groups']['G']
 assert g['jumps']==[{'t':0.0,'n':2,'d':1,'c':1,'s':0.5}]

def gen(n,seed=7):
 rng=random.Random(7 if seed is None else seed);depts=['数据建模组','数据采样组','数据核验组'];out=[]
 for i in range(n):
  day=1+rng.randrange(20);hour=9+rng.randrange(9);minute=rng.randrange(60)
  opened=f'2026-11-{day:02d}T{hour:02d}:{minute:02d}:00+08:00'
  r=rng.random()
  if r<0.1: closed=None
  else:
   close_day=day+rng.randrange(0,4)
   closed=f'2026-11-{min(close_day,28):02d}T{9+rng.randrange(9):02d}:{rng.randrange(60):02d}:00+08:00'
   if closed<opened: closed=opened
  out.append(s(depts[i%3],opened,closed,'紧急' if i%2 else '普通'))
 return out

def test_shuffled_batches_match_whole():
 """乱序到达的批次合并后，曲线与分母须与整批核算一致。"""
 samples=gen(5000);cutoff='2026-11-13T12:00:00+08:00'
 order=list(range(17));random.Random(99).shuffle(order)
 assert batched(samples,cutoff,300,order)==whole(samples,cutoff)

def test_partial_merge_is_associative_and_commutative():
 samples=gen(3000);cutoff='2026-11-10T18:00:00+08:00'
 parts=[partial_aggregate(samples[i:i+137],cutoff,POLICY) for i in range(0,len(samples),137)]
 a=merge_partials(parts[:10]+parts[10:])
 b=merge_partials(list(reversed(parts[10:]))+list(reversed(parts[:10])))
 assert a==b and build_curves(a)==build_curves(b)

def test_hundred_thousand_orders_batched():
 """十万单分批（乱序）核算与整批一致。"""
 samples=gen(100000);cutoff='2026-11-13T12:00:00+08:00'
 order=list(range(50));random.Random(3).shuffle(order)
 got=batched(samples,cutoff,2000,order);want=whole(samples,cutoff)
 assert got==want
 assert got['sampled']+got['skipped']==100000

def test_sla_skips_unclosed_and_counts_them():
 """原SLA汇总口径不变：只统计已结单，未结单计数单列。"""
 samples=[s('G','2026-11-02T09:00:00+08:00','2026-11-02T10:00:00+08:00'),s('G','2026-11-02T09:00:00+08:00',None)]
 result=calculate(samples,POLICY)
 assert result['summary']['样本数']==1 and result['summary']['未结单数']==1
 assert result['rows'][0]['样本数']==1

def test_validation_accepts_unclosed_and_cutoff():
 ok=s('G','2026-11-02T09:00:00+08:00',None);validate_source(ok)
 bad=s('G','2026-11-02T09:00:00+08:00','2026-11-01T09:00:00+08:00')
 try: validate_source(bad);assert False
 except ValueError: pass
 assert validate_cutoff('2026-11-13T12:00:00+08:00')=='2026-11-13T12:00:00+08:00'
 assert validate_cutoff('')is None and validate_cutoff(None) is None
 for bad_cutoff in ('2026-11-13 12:00','2026-11-13T12:00:00',123):
  try: validate_cutoff(bad_cutoff);assert False,bad_cutoff
  except ValueError: pass
