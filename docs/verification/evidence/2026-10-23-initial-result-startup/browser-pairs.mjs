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
try{
 for(let i=1;i<=20;i++)for(const mode of (i%2?['baseline','candidate']:['candidate','baseline'])){
  const before=await drained();
  const p=await page(mode,'result');const m=mode==='two-pages'?await page(mode,'monitor'):null;
  let release;const gate=new Promise(resolve=>{release=resolve;});
  await p.route('**/*', async route => {
   const u=new URL(route.request().url());
   if(u.pathname.startsWith('/api/') || u.pathname.startsWith('/ws/')){await route.continue();return;}
   const path=u.pathname.startsWith('/assets/')?u.pathname.slice(1):u.pathname==='/monitor-contract.json'?'monitor-contract.json':'index.html';
   await route.fulfill({path:root+'/'+mode+'-dist/'+path});
  });
  const dashboardDone=p.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/dashboard',{timeout:60000});
  const start=Date.now();let monitorReady=null;
  const mt=m?(async()=>{await m.goto(base+'/');await m.getByRole('heading',{name:'监控总览',exact:true}).waitFor({timeout:60000});monitorReady=(Date.now()-start)/1000;})():Promise.resolve();
  await p.goto(base+'/backtests/'+run);
  let ready=true;try{await p.getByTestId('result-tab-summary').waitFor({timeout:60000});}catch{ready=false;}
  const seconds=(Date.now()-start)/1000;await mt; await (await dashboardDone).finished();
  if(mode==='defer-startup'){
   const completed=p.waitForResponse(r=>new URL(r.url()).pathname==='/api/v1/dashboard',{timeout:60000});
   release();await (await completed).finished();
  }
  if(i===1){await p.screenshot({path:root+'/controlled-'+mode+'.png',fullPage:true});if(ready){await p.getByTestId('result-tab-provenance').click();await p.getByTestId('result-tab-summary').click();}}
  rows.push({round:i,mode,page:p._id,monitorPage:m?m._id:null,start,ready,seconds,monitorHeadingSeconds:monitorReady});
  await p.close();if(m)await m.close();rows.at(-1).closed=Date.now(); const after=await drained(); rows.at(-1).cpu=after.cpu-before.cpu;save();console.log(JSON.stringify(rows.at(-1)));
 }
}finally{await browser.close();await drained();save();}
