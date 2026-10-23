from pathlib import Path
from datetime import datetime,UTC
import json,statistics,re,hashlib
P=Path(__file__).parent
def bars(name):
 j=json.loads((P/(name+'.txt')).read_text(encoding='utf-8'))['chart']['result'][0]
 q=j['indicators']['quote'][0];adjusted=j['indicators'].get('adjclose',[{}])[0].get('adjclose')
 factor=q['close'][-1]/adjusted[-1] if adjusted else 1
 out=[]
 for i,t in enumerate(j['timestamp']):
  d=datetime.fromtimestamp(t,UTC).strftime('%Y-%m-%d')
  if d>'2026-10-23':continue
  if any(q[k][i] is None for k in ['open','high','low','close','volume']):raise ValueError('missing OHLCV')
  scale=(adjusted[i]/q['close'][i]*factor) if adjusted else 1
  out.append(dict(date=d,**{k:q[k][i]*scale for k in ['open','high','low','close']},volume=q['volume'][i],raw_close=q['close'][i]))
 assert len({r['date'] for r in out})==len(out)
 return out
def wilder(values,n=14):
 out=[None]*(n-1);v=sum(values[:n])/n;out.append(v)
 for x in values[n:]:v=(v*(n-1)+x)/n;out.append(v)
 return out
def ema(values,n):
 v=values[0];out=[v]
 for x in values[1:]:v=v+(x-v)*2/(n+1);out.append(v)
 return out
s,i=bars('yahoo-stock'),bars('yahoo-index')
assert s[-1]['date']==i[-1]['date']=='2026-10-23'
assert [b['date'] for b in s]==[b['date'] for b in i]
c=[b['close'] for b in s];ic=[b['close'] for b in i]
ma=lambda a,n,offset=0:sum(a[len(a)-n-offset:len(a)-offset if offset else None])/n
changes=[c[j]-c[j-1] for j in range(1,len(c))]
g=wilder([max(v,0) for v in changes]);loss=wilder([max(-v,0) for v in changes])
rsi=lambda idx:100 if loss[idx]==0 else 100-100/(1+g[idx]/loss[idx])
tr=[max(s[j]['high']-s[j]['low'],abs(s[j]['high']-c[j-1]),abs(s[j]['low']-c[j-1])) for j in range(1,len(s))]
atr=wilder(tr)[-1]
e12,e26=ema(c,12),ema(c,26);dif=[a-b for a,b in zip(e12,e26)];dea=ema(dif,9)
M20,M60,M20_5=ma(ic,20),ma(ic,60),ma(ic,20,5);L20=min(b['low'] for b in i[-21:-1]);I=ic[-1]
damage=I<L20 and I<M60;weak=not damage and I<M20 and M20<M20_5
ret=lambda a,n:(a[-1]/a[-n-1]-1)*100
std=statistics.pstdev(c[-20:]);mean=ma(c,20)
result=dict(as_of='2026-10-23',source='Yahoo chart daily; stock adjusted-close factors normalized to latest unadjusted close; index raw',bars=len(s),latest_stock=s[-1],latest_index=i[-1],stock=dict(MA20=mean,MA50=ma(c,50),MA60=ma(c,60),MA200=ma(c,200),RSI14=rsi(-1),previous_RSI14=rsi(-2),ATR14=atr,atr_pct=atr/c[-1]*100,MACD_DIF=dif[-1],DEA=dea[-1],histogram=2*(dif[-1]-dea[-1]),boll_upper=mean+2*std,boll_lower=mean-2*std,boll_width_pct=4*std/mean*100,prior20_mean_volume=sum(b['volume'] for b in s[-21:-1])/20,volume_ratio=s[-1]['volume']/(sum(b['volume'] for b in s[-21:-1])/20),return5=ret(c,5),return20=ret(c,20)),index=dict(I=I,M20=M20,M60=M60,M20_5=M20_5,L20=L20,damage=damage,weak=weak,state='明显结构破坏' if damage else '走弱' if weak else '常态／过渡',return5=ret(ic,5),return20=ret(ic,20)))
result['relative_strength']=result['stock']['return5']>result['index']['return5'] and result['stock']['return20']>result['index']['return20'] and c[-1]>=mean
# Verify latest unadjusted prices using independent Eastmoney and Sina records.
em=json.loads((P/'eastmoney.txt').read_text(encoding='utf-8'))['data']['klines'][-1].split(',')
assert em[0]=='2026-10-23' and abs(float(em[2])-c[-1])<0.005
result['latest_cross_check']=dict(eastmoney_close=em[2],turnover_yuan=em[6],change_pct=em[8],sina_close='30.240',sina_volume_shares=3506650,sina_quote_time='2026-10-23 15:34:59',exchange_close_time='2026-10-23 15:00:00 Asia/Shanghai',retrieved_time='2026-10-23 22:05 Asia/Shanghai')
(P/'market-analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
report=Path('D:/Workspace/Projects/ai-quant-pilot/TradingAgents/Y/complete_report.md').read_text(encoding='utf-8')
excerpt=report.split('### Sentiment Analyst')[0]+report.split('### Fundamentals Analyst')[1].split('## II. Research Team Decision')[0]+'\n## 原报告最终结论\n'+report.split('## V. Portfolio Manager Decision')[1]
(P/'report-excerpt.md').write_text(excerpt,encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2));print('report excerpt characters',len(excerpt),'full report sha256',hashlib.sha256(report.encode()).hexdigest())
