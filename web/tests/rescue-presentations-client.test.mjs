// 名称修订客户端：保留后端版本绑定，既有焦点参数不能覆盖回执指纹。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';

const source=readFileSync(new URL('../src/api/client.ts',import.meta.url),'utf8')
  .replaceAll('import.meta.env.VITE_API_BASE','undefined').replaceAll('import.meta.env.DEV','false');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
let sequence=0;
const fresh=()=>import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}#rescue${sequence++}`);
const response=data=>new Response(JSON.stringify(data),{status:200});

test('焦点查询保留原修订SHA，同时追加原输入与稳定对象',async()=>{
  const {api}=await fresh();let seen;
  globalThis.fetch=async(url,options)=>{seen={url,options};return response({run_id:'R',input_key:'I'});};
  await api.rescueFocus('/api/v1/example/focus?expected_revision_sha256=receipt1','I',['C1'],['HGNC:1']);
  const url=new URL(seen.url,'http://127.0.0.1');
  assert.equal(url.searchParams.get('expected_revision_sha256'),'receipt1');
  assert.equal(url.searchParams.get('expected_input_key'),'I');
  assert.deepEqual(JSON.parse(url.searchParams.get('compounds')),['C1']);
  assert.equal(seen.options.method,'GET');
});

test('目录与明确修订只发GET，原链接参数保持',async()=>{
  const {api}=await fresh();const calls=[];
  assert.equal(typeof api.rescuePresentationDirectory,'function');
  assert.equal(typeof api.rescuePresentation,'function');
  globalThis.fetch=async(url,options)=>{calls.push({url,options});return response({read_only:true});};
  await api.rescuePresentationDirectory('/api/v1/studies/S/runs/R/rescue-presentations');
  await api.rescuePresentation('/api/v1/studies/S/runs/R/rescue-presentations/V?expected_revision_sha256=A&expected_input_key=I');
  assert.deepEqual(calls.map(x=>x.options.method),['GET','GET']);
  assert.ok(calls[1].url.endsWith('expected_revision_sha256=A&expected_input_key=I'));
});

test('不同修订的并发读取不合并为同一个请求',async()=>{
  const {api}=await fresh();assert.equal(typeof api.rescuePresentation,'function');
  const calls=[];
  globalThis.fetch=(url)=>new Promise(resolve=>calls.push({url,resolve}));
  const first=api.rescuePresentation('/api/v1/example/A?expected_revision_sha256=1');
  const second=api.rescuePresentation('/api/v1/example/B?expected_revision_sha256=2');
  assert.equal(calls.length,2);
  calls[1].resolve(response({revision_id:'B'}));calls[0].resolve(response({revision_id:'A'}));
  assert.equal((await first).revision_id,'A');assert.equal((await second).revision_id,'B');
});

test('真实修订焦点URL已有两项绑定时不重复输入字段',async()=>{
  const {api}=await fresh();const calls=[];
  globalThis.fetch=async(url)=>{calls.push(url);return response({});};
  await api.rescueFocus('/api/v1/example/focus?expected_revision_sha256=receipt1&expected_input_key=I','I',['C1'],['T1']);
  const query=new URL(calls[0],'http://127.0.0.1').searchParams;
  assert.deepEqual(query.getAll('expected_input_key'),['I']);
  assert.deepEqual(query.getAll('expected_revision_sha256'),['receipt1']);
  assert.equal(query.get('compounds'),'["C1"]');
});

test('焦点URL已有输入与页面不一致时拒绝发送而不覆盖绑定',async()=>{
  const {api}=await fresh();const calls=[];
  globalThis.fetch=async(url)=>{calls.push(url);return response({});};
  await assert.rejects(async()=>api.rescueFocus('/api/v1/example/focus?expected_input_key=foreign','I',['C1'],['T1']));
  assert.equal(calls.length,0);
});

test('完整包目录保留明确图表SHA，只读不自动提交打包',async()=>{
  const {api}=await fresh();const calls=[];
  assert.equal(typeof api.acceptanceArchives,'function');
  globalThis.fetch=async(url,options)=>{calls.push({url,options});return response({history:[]});};
  const url='/api/v1/studies/S/runs/R/rescue-presentations/V/acceptance-archives?expected_revision_sha256=A&expected_input_key=I';
  await api.acceptanceArchives(url);
  assert.equal(calls.length,1);assert.equal(calls[0].options.method,'GET');assert.equal(calls[0].url,url);
});

test('完整包POST保留九字段与既有令牌，不把目录查询带入正文或路径',async()=>{
  const {api,loadSession}=await fresh();const calls=[];
  assert.equal(typeof api.publishAcceptanceArchive,'function');
  globalThis.fetch=async(url,options)=>{calls.push({url,options});return response(url.endsWith('/session')?{token:'synthetic'}:{created:true});};
  await loadSession();calls.length=0;
  const body={request_id:'rescuezipreq_X',expected_run_id:'R',expected_revision_id:'V',expected_revision_sha256:'A',
    expected_input_key:'I',expected_input_hash:'H',author:'合成测试',note:'同修订完整包',confirmed:true};
  const url='/api/v1/studies/S/runs/R/rescue-presentations/V/acceptance-archives';
  await api.publishAcceptanceArchive(url,body);
  assert.equal(calls.length,1);assert.equal(calls[0].url,url);assert.equal(calls[0].options.method,'POST');
  assert.deepEqual(JSON.parse(calls[0].options.body),body);assert.equal(calls[0].options.headers['X-ModuleA-Token'],'synthetic');
});
