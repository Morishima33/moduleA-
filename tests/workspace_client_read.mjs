// 用途：实际编译client验证同页请求合并、独立JSON、inbox等待与失败释放；fetch完全隔离。
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require=createRequire(import.meta.url);
const ts=require(fileURLToPath(new URL('../web/node_modules/typescript/lib/typescript.js',import.meta.url)));
const source=(await readFile(new URL('../web/src/api/client.ts',import.meta.url),'utf8'))
  .replaceAll('import.meta.env','({ DEV: false, VITE_API_BASE: undefined })');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const previous=globalThis.fetch;const calls=[];const workspaces=[];const tasks=[];
const turn=()=>new Promise(resolve=>setImmediate(resolve));
const response=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
globalThis.fetch=(url,options={})=>{
  calls.push({url:String(url),method:options.method});
  if(String(url).includes('/workspace'))return new Promise(resolve=>workspaces.push(resolve));
  if(String(url).includes('/tasks'))return new Promise(resolve=>tasks.push(resolve));
  if(String(url).endsWith('/inbox'))return Promise.resolve(response({items:[]}));
  throw Error('意外请求：'+url);
};
try {
  const {api,ApiError}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
  assert.equal(typeof api.workspace,'function','缺少同页workspace client入口');
  const first=api.workspace('study_test','A07');const other=api.workspace('study_test','A07');
  const inbox=api.inbox();await turn();
  assert.equal(calls.filter(c=>c.url.includes('/workspace')).length,1);
  assert.equal(calls.filter(c=>c.url.endsWith('/inbox')).length,0,'关键页面完成前不应重复读全局待办');
  workspaces.shift()(response({study:{marker:[1]},module:null,module_error:null}));
  const a=await first;const b=await other;await inbox;
  a.study.marker.push(2);assert.deepEqual(b.study.marker,[1],'并发读取需独立容器');
  assert.equal(calls.filter(c=>c.url.endsWith('/inbox')).length,1);
  // 已完成workspace不能跨请求复用；失败也必须释放inbox，不能等所有轮询或自身。
  const polling=api.tasks({active:true});
  const failed=api.workspace('study_test','A06').catch(error=>error);
  const following=api.inbox();await turn();
  assert.equal(calls.filter(c=>c.url.includes('/workspace')).length,2);
  assert.equal(calls.filter(c=>c.url.endsWith('/inbox')).length,1);
  workspaces.shift()(response({error:{code:'ARCHIVE_UNAVAILABLE',message_zh:'合成读取失败',details:{},retryable:true}},503));
  const error=await failed;assert.ok(error instanceof ApiError);assert.equal(error.status,503);
  const timeout=setTimeout(()=>{console.error('inbox错误等待了持续轮询或自身');process.exit(1);},2000);
  await following;clearTimeout(timeout);
  assert.equal(calls.filter(c=>c.url.endsWith('/inbox')).length,2);
  tasks.shift()(response({items:[]}));await polling;
  assert.ok(calls.every(c=>c.method==='GET'));
  process.stdout.write(JSON.stringify({passed:true,requests:calls.length,science_requests:0,network_requests:0})+'\n');
} catch(error) {
  console.error(error.name+': '+String(error.message).slice(0,1200));process.exitCode=1;
} finally {
  globalThis.fetch=previous;
}
