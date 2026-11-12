// 文件用途：隔离浏览器核对惰性读取、明确确认、原请求续做与主动新请求；不连接真实服务。
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import os from 'node:os';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const localRequire=createRequire(path.join(root,'web/package.json'));
const {build}=localRequire('esbuild');
const toolsRequire=process.env.MODULEA_NODE_MODULES
  ?createRequire(path.join(process.env.MODULEA_NODE_MODULES,'__rescue_ui_test__.cjs')):localRequire;
const {chromium}=toolsRequire('playwright');
const audit=process.env.MODULEA_UI_AUDIT||path.join(os.tmpdir(),'modulea_receptor_rescue_ui');
await mkdir(audit,{recursive:true});
const bundle=await build({stdin:{resolveDir:path.join(root,'web'),sourcefile:'rescue-ui-fixture.tsx',loader:'tsx',contents:`
import React from 'react';
import {createRoot} from 'react-dom/client';
import ReceptorRescueAction from './src/components/ReceptorRescueAction';
import {AppContext} from './src/lib/appContext';
import './src/styles.css';
const counts={tracks:[],opened:[],refresh:0};window.__rescueCounts=counts;
const app={session:null,refreshTick:0,currentStudyId:'study_ui_fixture',
  trackTasks:tasks=>counts.tracks.push(...tasks),openTasks:id=>counts.opened.push(id),
  bumpRefresh:()=>counts.refresh++,openNewStudy(){},openInbox(){},setCrumb(){}};
createRoot(document.getElementById('root')).render(<AppContext.Provider value={app}><ReceptorRescueAction studyId="study_ui_fixture"/></AppContext.Provider>);
`},bundle:true,write:false,outfile:path.join(audit,'fixture.js'),format:'iife',jsx:'automatic',
  define:{'import.meta.env.DEV':'false','import.meta.env.VITE_API_BASE':'undefined'}});
const script=bundle.outputFiles.find(file=>file.path.endsWith('.js')).text;
const css=bundle.outputFiles.find(file=>file.path.endsWith('.css'))?.text||'';
const html=`<!doctype html><html lang="zh"><meta charset="utf-8"><style>${css}</style><div id="root"></div><script>${script.replaceAll('</script','<\\/script')}</script></html>`;
const base='http://127.0.0.1:18979';
const sid='study_ui_fixture';
const original={request_id:'rescue_'+'a'.repeat(32),expected_preparation_run_id:'run_preparation',expected_scoring_run_id:'run_scoring',
  expected_input_hash:'b'.repeat(64),author:'原明确执行人',note:'原授权固定范围，不更换原评分',confirmed:true};
const preservedOriginal=structuredClone(original);
let info={schema_version:'A06.system_rescue.1',enabled:true,busy:false,blockers:[],
  expected_preparation_run_id:'run_preparation',expected_scoring_run_id:'run_scoring',expected_input_hash:'b'.repeat(64),
  current_run_id:null,state:'ready',request:null};
let gets=0,posts=[],postPaths=[],rejectPost=false;
const executeV1=`/api/v1/studies/${sid}/analysis-plan/receptor-rescue/execute`;
const executeV2=`/api/v1/studies/${sid}/analysis-plan/receptor-rescue-v2/execute`;
const errors=[];
const browser=await chromium.launch({headless:true,...(process.env.MODULEA_BROWSER_CHANNEL?{channel:process.env.MODULEA_BROWSER_CHANNEL}:{})});
try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',error=>errors.push(String(error)));
  await page.route(base+'/**',async route=>{
    const url=new URL(route.request().url()),method=route.request().method();
    if(url.pathname==='/')return route.fulfill({status:200,contentType:'text/html',body:html});
    if(url.pathname==='/api/v1/session')return route.fulfill({json:{token:'synthetic-token'}});
    if(url.pathname===`/api/v1/studies/${sid}/analysis-plan/receptor-rescue-v2`&&method==='GET'){
      gets++;return route.fulfill({json:info});
    }
    if([executeV1,executeV2].includes(url.pathname)&&method==='POST'){
      posts.push(route.request().postDataJSON());
      postPaths.push(url.pathname);
      if(rejectPost)return route.fulfill({status:409,json:{error:{code:'STALE_VERSION',message_zh:'来源已经改变，请重新核对'}}});
      return route.fulfill({status:202,json:{task:{task_id:'task_ui_fixture',state:'queued'},created:true,message_zh:'合成任务已提交'}});
    }
    throw new Error('隔离测试收到未登记请求：'+method+' '+url.pathname);
  });

  await page.goto(base);
  await page.getByRole('button',{name:'查看补救资格与入口'}).waitFor();
  await page.waitForTimeout(80);
  assert.equal(gets,0,'页面挂载不能自动读取补救来源');
  await page.getByRole('button',{name:'查看补救资格与入口'}).click();
  const start=page.getByRole('button',{name:'开始本批受体补救与评分',exact:true});
  await start.waitFor();
  assert.equal(gets,1);
  assert.equal(await start.isDisabled(),true);
  assert.equal(await page.getByRole('checkbox').isChecked(),false);
  await page.getByRole('textbox',{name:'受体补救执行人'}).fill('界面测试执行人');
  await page.getByRole('textbox',{name:'受体补救执行依据'}).fill('已核对固定范围与本次计算授权');
  assert.equal(await start.isDisabled(),true,'填写文字不能代替明确确认');
  assert.equal(posts.length,0);
  await page.getByRole('checkbox').check();
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(button=>button.textContent==='开始本批受体补救与评分'&&!button.disabled));
  await page.screenshot({animations:'disabled',path:path.join(audit,'ready_1440.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'窄屏不能整页横向溢出');
  await page.screenshot({animations:'disabled',path:path.join(audit,'ready_390.png'),fullPage:true});
  await start.click();
  await page.getByText('合成任务已提交',{exact:true}).waitFor();
  assert.equal(posts.length,1);
  assert.match(posts[0].request_id,/^rescue_[0-9a-f]{32}$/);
  assert.deepEqual(Object.keys(posts[0]).sort(),Object.keys(original).sort());
  assert.equal(posts[0].confirmed,true);
  assert.equal(postPaths[0],executeV1,'GET2返回schema1时仍只能使用原执行端点');
  assert.equal((await page.evaluate(()=>window.__rescueCounts.tracks)).length,1);

  info={...info,state:'blocked',enabled:false,blockers:['固定Vina工具不存在']};
  await page.goto(base);await page.getByRole('button',{name:'查看补救资格与入口'}).click();
  await page.getByText('固定Vina工具不存在',{exact:true}).waitFor();
  assert.equal(await page.getByRole('button',{name:'开始本批受体补救与评分',exact:true}).isDisabled(),true);

  info={...info,state:'complete',blockers:[],current_run_id:'run_ui_complete'};
  await page.goto(base);await page.getByRole('button',{name:'查看补救资格与入口'}).click();
  const completed=page.getByRole('link',{name:'查看本轮A06结果'});
  await completed.waitFor();
  assert.equal(await completed.getAttribute('href'),'#/studies/study_ui_fixture/A06');
  assert.equal(await page.getByRole('checkbox').count(),0,'已完成不显示重复执行确认');

  info={...info,state:'incomplete',enabled:true,current_run_id:'run_ui_incomplete',request:original};
  await page.goto(base);await page.getByRole('button',{name:'查看补救资格与入口'}).click();
  const resume=page.getByRole('button',{name:'继续本批受体补救与评分',exact:true});
  await resume.waitFor();
  assert.equal(await page.getByRole('radio',{name:'继续原请求',exact:true}).count(),1,'未完成批次必须提供保留原请求的明确模式');
  assert.equal(await page.getByRole('radio',{name:'继续原请求',exact:true}).isChecked(),true,'未完成批次默认继续原请求');
  assert.equal(await page.getByRole('checkbox').isChecked(),false,'原请求confirmed不能预选新界面确认');
  assert.equal(await page.getByRole('textbox',{name:'受体补救执行人'}).inputValue(),original.author);
  assert.equal(await page.getByRole('textbox',{name:'受体补救执行人'}).isEditable(),false);
  await page.getByRole('checkbox').check();await resume.click();
  await page.getByText('合成任务已提交',{exact:true}).waitFor();
  assert.deepEqual(posts[1],original,'续做必须原样复用已登记七字段请求');
  assert.equal(postPaths[1],executeV1,'原请求续做不得随GET2静默升级');

  // 切换新请求本身不能发写请求；重新填写和主动确认后才产生新编号。
  await page.goto(base);await page.getByRole('button',{name:'查看补救资格与入口'}).click();
  await resume.waitFor();
  await page.getByRole('checkbox').check();
  await page.getByRole('radio',{name:'使用新请求',exact:true}).check();
  const replacement=page.getByRole('button',{name:'使用新请求开始本批受体补救与评分',exact:true});
  await replacement.waitFor();
  assert.equal(posts.length,2,'仅切换新请求模式不能提交');
  assert.equal(await page.getByRole('textbox',{name:'受体补救执行人'}).inputValue(),'');
  assert.equal(await page.getByRole('textbox',{name:'受体补救执行依据'}).inputValue(),'');
  assert.equal(await page.getByRole('textbox',{name:'受体补救执行人'}).isEditable(),true);
  assert.equal(await page.getByRole('checkbox').isChecked(),false,'选择新请求必须清除原确认');
  assert.equal(await replacement.isDisabled(),true);
  await page.getByText('旧运行和检查点保留',{exact:false}).waitFor();
  await page.getByRole('radio',{name:'继续原请求',exact:true}).check();
  assert.equal(await page.getByRole('textbox',{name:'受体补救执行人'}).inputValue(),original.author);
  assert.equal(await page.getByRole('textbox',{name:'受体补救执行人'}).isEditable(),false);
  await page.getByRole('radio',{name:'使用新请求',exact:true}).check();
  assert.equal(await page.getByRole('textbox',{name:'受体补救执行人'}).inputValue(),'');
  await page.getByRole('textbox',{name:'受体补救执行人'}).fill('新请求明确执行人');
  await page.getByRole('textbox',{name:'受体补救执行依据'}).fill('修正工具后按原来源另立新请求，保留旧运行');
  assert.equal(await replacement.isDisabled(),true,'新请求填写后仍须主动确认');
  await page.getByRole('checkbox').check();
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(button=>button.textContent==='使用新请求开始本批受体补救与评分'&&!button.disabled));
  await page.setViewportSize({width:1440,height:1000});
  await page.screenshot({animations:'disabled',path:path.join(audit,'replacement_1440.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'新请求模式窄屏不能整页横向溢出');
  await page.screenshot({animations:'disabled',path:path.join(audit,'replacement_390.png'),fullPage:true});
  await replacement.click();
  await page.getByText('合成任务已提交',{exact:true}).waitFor();
  assert.equal(posts.length,3);
  assert.match(posts[2].request_id,/^rescue_[0-9a-f]{32}$/);
  assert.notEqual(posts[2].request_id,original.request_id,'新请求不能静默复用原请求号');
  assert.deepEqual(Object.keys(posts[2]).sort(),Object.keys(original).sort());
  for(const key of ['expected_preparation_run_id','expected_scoring_run_id','expected_input_hash']){
    assert.equal(posts[2][key],original[key],'新请求仍绑定当前显示的原准备、原评分与来源指纹');
  }
  assert.equal(posts[2].author,'新请求明确执行人');
  assert.equal(posts[2].note,'修正工具后按原来源另立新请求，保留旧运行');
  assert.equal(posts[2].confirmed,true);
  assert.equal(postPaths[2],executeV1,'schema1主动新请求仍使用第一版端点');
  assert.deepEqual(info.request,preservedOriginal,'新请求不得改变原请求对象');
  assert.deepEqual(posts[1],preservedOriginal,'原请求提交原文仍保持');

  // 每次读取仍默认原请求；后台忙碌时不能切换模式或执行任一分支。
  info={...info,busy:true,blockers:['本研究后台任务尚未结束']};
  await page.goto(base);await page.getByRole('button',{name:'查看补救资格与入口'}).click();
  await resume.waitFor();
  assert.equal(await page.getByRole('radio',{name:'继续原请求',exact:true}).isChecked(),true);
  assert.equal(await page.getByRole('radio',{name:'继续原请求',exact:true}).isDisabled(),true);
  assert.equal(await page.getByRole('radio',{name:'使用新请求',exact:true}).isDisabled(),true);
  assert.equal(await resume.isDisabled(),true);
  assert.equal(posts.length,3);

  info={...info,state:'ready',busy:false,blockers:[],current_run_id:null,request:null};rejectPost=true;
  await page.goto(base);await page.getByRole('button',{name:'查看补救资格与入口'}).click();
  await page.getByRole('textbox',{name:'受体补救执行人'}).fill('过期检查');
  await page.getByRole('textbox',{name:'受体补救执行依据'}).fill('仅合成输入');
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'开始本批受体补救与评分',exact:true}).click();
  await page.getByText('来源已经改变，请重新核对',{exact:true}).waitFor();
  assert.equal(await page.getByRole('checkbox').count(),0,'409后清除旧资格与确认，不自动重提');
  await page.waitForTimeout(80);
  assert.equal(posts.length,4);
  assert.equal(postPaths[3],executeV1);

  // 只有资格明确返回schema2才走独立执行端点，正文仍是原七字段结构。
  info={...info,schema_version:'A06.system_rescue.2',expected_scoring_run_id:'run_v1_complete_baseline',
    expected_input_hash:'c'.repeat(64),state:'ready'};rejectPost=false;
  const previousGets=gets;
  await page.goto(base);await page.getByRole('button',{name:'查看补救资格与入口'}).waitFor();
  await page.waitForTimeout(80);
  assert.equal(gets,previousGets,'schema2准备页挂载仍不主动请求资格');
  assert.equal(posts.length,4,'schema2挂载不能自动执行');
  await page.getByRole('button',{name:'查看补救资格与入口'}).click();
  await start.waitFor();
  assert.equal(await page.getByRole('checkbox').isChecked(),false);
  await page.getByRole('textbox',{name:'受体补救执行人'}).fill('第二版明确执行人');
  await page.getByRole('textbox',{name:'受体补救执行依据'}).fill('核对完整第一版基线与第二版原件来源');
  assert.equal(await start.isDisabled(),true,'schema2仍需主动确认');
  await page.getByRole('checkbox').check();
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(button=>button.textContent==='开始本批受体补救与评分'&&!button.disabled));
  await page.setViewportSize({width:1440,height:1000});
  await page.screenshot({animations:'disabled',path:path.join(audit,'v2_ready_1440.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'第二版窄屏不能整页横向溢出');
  await page.screenshot({animations:'disabled',path:path.join(audit,'v2_ready_390.png'),fullPage:true});
  await start.click();
  await page.getByText('合成任务已提交',{exact:true}).waitFor();
  assert.equal(posts.length,5);
  assert.equal(postPaths[4],executeV2,'schema2只提交第二版执行端点');
  assert.deepEqual(Object.keys(posts[4]).sort(),Object.keys(original).sort(),'协议只选端点，不添加正文属性');
  assert.match(posts[4].request_id,/^rescue_[0-9a-f]{32}$/);
  assert.equal(posts[4].expected_preparation_run_id,info.expected_preparation_run_id);
  assert.equal(posts[4].expected_scoring_run_id,'run_v1_complete_baseline');
  assert.equal(posts[4].expected_input_hash,'c'.repeat(64));
  assert.equal(posts[4].author,'第二版明确执行人');
  assert.equal(posts[4].note,'核对完整第一版基线与第二版原件来源');
  assert.equal(posts[4].confirmed,true);

  info={...info,busy:true,blockers:['本研究后台任务尚未结束']};
  await page.goto(base);await page.getByRole('button',{name:'查看补救资格与入口'}).click();
  await start.waitFor();
  assert.equal(await start.isDisabled(),true,'第二版后台忙碌不能执行');
  assert.equal(await page.getByRole('checkbox').isDisabled(),true);
  assert.equal(posts.length,5);

  info={...info,busy:false,blockers:[]};rejectPost=true;
  await page.goto(base);await page.getByRole('button',{name:'查看补救资格与入口'}).click();
  await page.getByRole('textbox',{name:'受体补救执行人'}).fill('第二版过期检查');
  await page.getByRole('textbox',{name:'受体补救执行依据'}).fill('仅合成第二版绑定');
  await page.getByRole('checkbox').check();await start.click();
  await page.getByText('来源已经改变，请重新核对',{exact:true}).waitFor();
  assert.equal(await page.getByRole('checkbox').count(),0,'第二版409同样清除资格与确认');
  await page.waitForTimeout(80);
  assert.equal(posts.length,6,'第二版409不能自动重提或回退第一版');
  assert.equal(postPaths[5],executeV2);
  assert.deepEqual(postPaths.slice(0,4),[executeV1,executeV1,executeV1,executeV1]);
  assert.deepEqual(postPaths.slice(4),[executeV2,executeV2]);
  assert.deepEqual(errors,[]);
  await writeFile(path.join(audit,'result.json'),JSON.stringify({passed:true,lazy_initial_get:true,explicit_confirmation:true,
    exact_resume_request:true,explicit_fresh_replacement:true,replacement_original_bindings:true,old_request_unchanged:true,
    busy_disables_both_modes:true,completed_result_navigation:true,blocked_condition_visible:true,stale_no_resubmit:true,
    narrow_no_page_overflow:true,qualification_get_v2_only:true,schema1_execution_endpoint_preserved:true,
    schema2_explicit_endpoint:true,schema2_seven_fields_only:true,both_protocols_stale_no_resubmit:true,
    posts:posts.length,post_paths:postPaths,real_server_started:false,real_jobs_started:false,page_errors:errors},null,2));
  console.log('受体补救入口隔离浏览器检查通过：惰性GET2、明确确认、第一版原请求/主动新请求不升级、第二版仅按schema执行、两版409不重提与busy禁用、完成导航、1440/390。');
}finally{await browser.close();}
