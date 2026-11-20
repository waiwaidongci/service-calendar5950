"""结单概率曲线（Kaplan-Meier）核心口径。

纯函数模块，不依赖数据库：分批核算与整批核算共用 classify/partial_aggregate/
merge_partials/build_curves 同一套原语。部分聚合是 (小组, 业务分钟) -> [结单数, 删失数]
的计数表，合并即逐项相加——可交换、可结合，因此批次可以乱序到达，且结果与整批核算一致。
"""
from datetime import datetime
from src.services.calculation import business_minutes

PRECISION=6
METHOD=('Kaplan-Meier结单概率：开单时间不晚于截点（含恰在截点）的底稿全部入样；'
 '截点前已结单的按开单到结单的业务分钟计结单事件，未结单与截点后才结单的只随访到截点、按截点计删失。'
 '每个业务分钟以当时仍在观察的全部样本为分母；同一分钟先记结单、再把该分钟的结单与删失样本一并移出，'
 'S(t)=Π(1−d/n)。时间轴为口径日历下的业务分钟，午休、假日与非工作日不计时长。'
 '十万级底稿分批核算的部分结果按(小组,业务分钟)计数相加合并，与整批核算完全一致。')
WARNINGS=['月中只看已结单会高估结单速度；本曲线保留未结单的随访信息，删失样本未来结单时长分布假设与同期已观察样本一致。']

def _parse(ts): return datetime.fromisoformat(ts)

def classify(opened,closed,cutoff,policy):
 """单样本归类：None=截点后开单不入样；('event',t)=t业务分钟结单；('censored',t)=t业务分钟删失。"""
 if _parse(opened)>_parse(cutoff): return None
 if closed and _parse(closed)<=_parse(cutoff):
  return ('event',business_minutes(opened,closed,policy))
 return ('censored',business_minutes(opened,cutoff,policy))

def tkey(t): return f'{round(t,PRECISION):.{PRECISION}f}'

def partial_aggregate(samples,cutoff,policy):
 """一批底稿的部分聚合。返回可JSON序列化、可交换合并的计数表。"""
 groups={};sampled=0;skipped=0
 for s in samples:
  r=classify(s['opened'],s.get('closed'),cutoff,policy)
  if r is None: skipped+=1;continue
  kind,t=r
  cell=groups.setdefault(s['department'],{}).setdefault(tkey(t),[0,0])
  cell[0 if kind=='event' else 1]+=1
  sampled+=1
 return {'groups':groups,'sampled':sampled,'skipped':skipped}

def merge_partials(partials):
 """合并任意次序到达的部分聚合；逐项加法，结果与整批核算一致。"""
 groups={};sampled=0;skipped=0
 for p in partials:
  sampled+=p['sampled'];skipped+=p['skipped']
  for dept,cells in p['groups'].items():
   g=groups.setdefault(dept,{})
   for key,(d,c) in cells.items():
    cell=g.setdefault(key,[0,0]);cell[0]+=d;cell[1]+=c
 return {'groups':groups,'sampled':sampled,'skipped':skipped}

def build_curves(merged):
 """由合并计数表生成各小组跳点序列。每个跳点记录分母n、结单d、删失c与结单概率S。"""
 out={}
 for dept,cells in merged['groups'].items():
  n=sum(d+c for d,c in cells.values());s=1.0;jumps=[];events=0;censored=0
  for key in sorted(cells,key=float):
   d,c=cells[key]
   if d and n: s*=1-d/n
   jumps.append({'t':float(key),'n':n,'d':d,'c':c,'s':round(s,PRECISION)})
   n-=d+c;events+=d;censored+=c
  out[dept]={'sampled':events+censored,'events':events,'censored':censored,'jumps':jumps}
 return out

def finalize_km(partials,cutoff,version,epoch):
 """全部批次入账后调用：合并并一次性产出曲线与分母（齐备后一起发布）。"""
 merged=merge_partials(partials)
 warnings=list(WARNINGS)
 if not merged['sampled']: warnings.append('截点前没有已开单样本，曲线为空；请后移截点。')
 return {'cutoff':cutoff,'epoch':epoch,'policy_version':version,'sampled':merged['sampled'],
 'skipped':merged['skipped'],'groups':build_curves(merged),'method':METHOD,'warnings':warnings}
