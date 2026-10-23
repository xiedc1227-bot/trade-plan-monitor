import asyncio,json
from datetime import datetime,UTC
from pathlib import Path
import httpx
OUT=Path(__file__).parent
async def main():
    urls={
      'eastmoney':'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=1.605296&klt=101&fqt=0&beg=20250901&end=20261023&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61',
      'yahoo-stock':'https://query1.finance.yahoo.com/v8/finance/chart/605296.SS?period1=1756684800&period2=1792886400&interval=1d&events=div%2Csplits',
      'yahoo-index':'https://query1.finance.yahoo.com/v8/finance/chart/000001.SS?period1=1756684800&period2=1792886400&interval=1d',
      'sina':'https://hq.sinajs.cn/list=sh605296,sh000001',
      'announcement':'https://money.finance.sina.com.cn/corp/view/vCB_AllBulletinDetail.php?id=12653528&stockid=605296',
    }
    async with httpx.AsyncClient(timeout=20,follow_redirects=False,trust_env=False,headers={'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn/'}) as c:
      async def one(name,url):
       try:
        r=await c.get(url)
        r.raise_for_status()
        s=r.content.decode('gb18030' if name in ('sina','announcement') else 'utf-8',errors='replace')
        (OUT/(name+'.txt')).write_text(s,encoding='utf-8')
        return {'name':name,'url':url,'status':r.status_code,'characters':len(s),'retrieved_at_utc':datetime.now(UTC).isoformat()}
       except Exception as e:return {'name':name,'url':url,'error':type(e).__name__+': '+str(e)}
      result=await asyncio.gather(*(one(n,u) for n,u in urls.items()))
    (OUT/'fetch-log.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
asyncio.run(main())
