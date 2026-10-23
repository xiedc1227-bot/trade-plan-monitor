import {chromium} from '../../web/node_modules/@playwright/test/index.mjs';
import {readFileSync,writeFileSync,existsSync} from 'node:fs';
import {resolve} from 'node:path';
const root='.pytest_cache/initial-result-startup';
const pin=JSON.parse(readFileSync('web/test-browser.json','utf8'));
const run='b9c937a72b2bf572000c6402321f1e9516e0036ee7f3304f4358466eab888741';
const browser=await chromium.launch({executablePath:resolve('web/.test-browsers',pin.version,pin.platforms['win32-x64'].executable)});
const base='http://127.0.0.1:8766', rows=[], requests=[], errors=[], writes=[];
let serial=0;
const save=()=>writeFileSync(root+'/browser-controlled.json',JSON.stringify({rows,requests,errors,writes},null,2));
async function drained(){
 const deadline=Date.now()+60000;
 while(Date.now()<deadline){
  writeFileSync(root+'/snapshot.request','');
  while(existsSync(root+'/snapshot.request')){if(Date.now()>deadline)throw new Error('snapshot timed out');await new Promise(r=>setTimeout(r,100));}
  const state=JSON.parse(readFileSync(root+'/snapshot.json','utf8'));
  if(state.readers.every(x=>x.outstanding===0 && x.pauses===0 && x.flights.active_calls===0 && x.flights.queued_owners===0 && x.flights.retained_bytes===0) && state.socketTasks.length===0)return state;
  await new Promise(r=>setTimeout(r,300));
 }
 throw new Error('physical read drain timed out');
}
async function page(mode,role){
 const p=await browser.newPage({viewport:{width:1440,height:1000},locale:'zh-CN',timezoneId:'Asia/Shanghai'});p._id=++serial;
 p.on('pageerror',e=>errors.push({page:p._id,type:'pageerror',message:e.message}));
 p.on('request',r=>{
  if(!['GET','HEAD'].includes(r.method()))writes.push(r.method());
  const path=new URL(r.url()).pathname;if(!path.startsWith('/api/'))return;
  r._record={page:p._id,mode,role,path,start:Date.now()};requests.push(r._record);
 });
 p.on('response',async r=>{if(r.request()._record){r.request()._record.status=r.status();r.request()._record.traceId=await r.headerValue('x-read-trace-id');}});
 p.on('requestfinished',r=>{if(r._record){r._record.end=Date.now();r._record.timing=r.timing();}});
 p.on('requestfailed',r=>{if(r._record){r._record.end=Date.now();r._record.failure=r.failure()?.errorText;}});
 return p;
}
try {
 await drained();
 const p=await page('lifecycle','result');
 let release;const held=new Promise(r=>release=r);
 await p.route('**/api/v1/backtest-runs/'+run,async route=>{await held;await route.continue();});
 const dashboard=p.waitForRequest(r=>new URL(r.url()).pathname==='/api/v1/dashboard',{timeout:10000});
 const start=Date.now(); await p.goto(base+'/backtests/'+run);
 const pendingText=await p.locator('body').innerText();
 await dashboard; const delay=(Date.now()-start)/1000;
 if(delay<4.9 || delay>7)throw new Error('startup timeout outside tolerance: '+delay);
 if(!pendingText.includes('正在连接监控服务'))throw new Error('missing honest pending banner');
 release();await p.getByTestId('result-tab-summary').waitFor({timeout:60000});await p.close();await drained();
 writeFileSync(root+'/lifecycle.json',JSON.stringify({timeoutSeconds:delay,pendingBanner:true,drained:true,errors,writes},null,2));
} finally {await browser.close();await drained();}
