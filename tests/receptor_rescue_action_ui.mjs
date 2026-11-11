// 文件用途：隔离浏览器核对受体补救入口的惰性读取、明确确认、原请求续做和完成导航；不连接真实服务。
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
let info={schema_version:'A06.system_rescue.1',enabled:true,busy:false,blockers:[],
  expected_preparation_run_id:'run_preparation',expected_scoring_run_id:'run_scoring',expected_input_hash:'b'.repeat(64),
  current_run_id:null,state:'ready',request:null};
let gets=0,posts=[],rejectPost=false;
const errors=[];
const browser=await chromium.launch({headless:true,...(process.env.MODULEA_BROWSER_CHANNEL?{channel:process.env.MODULEA_BROWSER_CHANNEL}:{})});
try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',error=>errors.push(String(error)));
  await page.route(base+'/**',async route=>{
    const url=new URL(route.request().url()),method=route.request().method();
    if(url.pathname==='/')return route.fulfill({status:200,contentType:'text/html',body:html});
    if(url.pathname==='/api/v1/session')return route.fulfill({json:{token:'synthetic-token'}});
    if(url.pathname===`/api/v1/studies/${sid}/analysis-plan/receptor-rescue`&&method==='GET'){
      gets++;return route.fulfill({json:info});
    }
    if(url.pathname===`/api/v1/studies/${sid}/analysis-plan/receptor-rescue/execute`&&method==='POST'){
      posts.push(route.request().postDataJSON());
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
  await page.screenshot({path:path.join(audit,'ready_1440.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true,'窄屏不能整页横向溢出');
  await page.screenshot({path:path.join(audit,'ready_390.png'),fullPage:true});
  await start.click();
  await page.getByText('合成任务已提交',{exact:true}).waitFor();
  assert.equal(posts.length,1);
  assert.match(posts[0].request_id,/^rescue_[0-9a-f]{32}$/);
  assert.deepEqual(Object.keys(posts[0]).sort(),Object.keys(original).sort());
  assert.equal(posts[0].confirmed,true);
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
  assert.equal(await page.getByRole('checkbox').isChecked(),false,'原请求confirmed不能预选新界面确认');
  assert.equal(await page.getByRole('textbox',{name:'受体补救执行人'}).inputValue(),original.author);
  assert.equal(await page.getByRole('textbox',{name:'受体补救执行人'}).isEditable(),false);
  await page.getByRole('checkbox').check();await resume.click();
  await page.getByText('合成任务已提交',{exact:true}).waitFor();
  assert.deepEqual(posts[1],original,'续做必须原样复用已登记七字段请求');

  info={...info,state:'ready',current_run_id:null,request:null};rejectPost=true;
  await page.goto(base);await page.getByRole('button',{name:'查看补救资格与入口'}).click();
  await page.getByRole('textbox',{name:'受体补救执行人'}).fill('过期检查');
  await page.getByRole('textbox',{name:'受体补救执行依据'}).fill('仅合成输入');
  await page.getByRole('checkbox').check();
  await page.getByRole('button',{name:'开始本批受体补救与评分',exact:true}).click();
  await page.getByText('来源已经改变，请重新核对',{exact:true}).waitFor();
  assert.equal(await page.getByRole('checkbox').count(),0,'409后清除旧资格与确认，不自动重提');
  assert.equal(posts.length,3);
  assert.deepEqual(errors,[]);
  await writeFile(path.join(audit,'result.json'),JSON.stringify({passed:true,lazy_initial_get:true,explicit_confirmation:true,
    exact_resume_request:true,completed_result_navigation:true,blocked_condition_visible:true,stale_no_resubmit:true,
    narrow_no_page_overflow:true,posts:posts.length,real_server_started:false,real_jobs_started:false,page_errors:errors},null,2));
  console.log('受体补救入口隔离浏览器检查通过：惰性读取、明确确认、阻塞、完成导航、原请求续做、409不重提、1440/390。');
}finally{await browser.close();}
