import csv,io,json
from fastapi import HTTPException
def csv_text(result):
 rows=result.get('rows',[])
 if not rows: raise HTTPException(409,'尚无结果')
 stream=io.StringIO();keys=list(dict.fromkeys(k for row in rows for k in row));w=csv.DictWriter(stream,fieldnames=keys);w.writeheader()
 for row in rows: w.writerow({k:(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in row.items()})
 return '\ufeff'+stream.getvalue()
def km_csv_text(km):
 rows=[{'小组':g,'业务分钟':j['t'],'分母（仍在观察）':j['n'],'结单数':j['d'],'删失数':j['c'],'结单概率':j['s']} for g,d in sorted(km.get('groups',{}).items()) for j in d['jumps']]
 if not rows: raise HTTPException(409,'尚无曲线结果')
 stream=io.StringIO();w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader()
 for row in rows: w.writerow(row)
 return '\ufeff'+stream.getvalue()
