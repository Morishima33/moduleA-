// 文件用途：新登记GeneCards/OMIM原件明确预上传，不替用户复核或启动疾病分析。
import {Alert,Button,Checkbox,Input,Select,Skeleton,Table} from 'antd';
import {useEffect,useRef,useState} from 'react';
import {api,ApiError,errorText} from '../api/client';
import type {SystemDiseaseManualSourcesInfo} from '../api/types';
import {useApp} from '../lib/appContext';

const LABELS:Record<string,string>={genecards_csv:'GeneCards原始搜索结果CSV',detailed_txt:'完整候选TXT',
 tsv:'原候选TSV',omim_xlsx_v2:'OMIM Gene Map原始Excel',omim:'OMIM Gene Map TSV'};

/** 原文件只在明确点击时上传；读取和任务刷新不代替确认。 */
export default function SystemDiseaseManualSources({studyId}:{studyId:string}){
 const app=useApp();const [info,setInfo]=useState<SystemDiseaseManualSourcesInfo|null>(null);const [error,setError]=useState('');
 const [notice,setNotice]=useState('');const [tick,setTick]=useState(0);const [database,setDatabase]=useState('GeneCards');
 const [format,setFormat]=useState('genecards_csv');const [file,setFile]=useState<File|null>(null);const [query,setQuery]=useState('');
 const [date,setDate]=useState('');const [version,setVersion]=useState('');const [encoding,setEncoding]=useState('utf-8-sig');
 const [quoted,setQuoted]=useState('unknown');const [completeness,setCompleteness]=useState('unknown');
 const [author,setAuthor]=useState('');const [note,setNote]=useState('');const [confirmed,setConfirmed]=useState(false);const [saving,setSaving]=useState(false);
 const request=useRef({signature:'',id:''});const binding=useRef('');
 useEffect(()=>{setInfo(null);setFile(null);setQuery('');setDate('');setVersion('');setAuthor('');setNote('');setConfirmed(false);
  setError('');setNotice('');request.current={signature:'',id:''};binding.current='';},[studyId]);
 useEffect(()=>{let current=true;api.systemDiseaseManualSources(studyId).then(value=>{if(!current)return;
  const key=studyId+':'+value.expected_input_hash;if(binding.current!==key){binding.current=key;setConfirmed(false);}
  setInfo(value);setQuery(old=>old||value.disease_identity_zh);setError('');
 }).catch(e=>{if(current){setInfo(null);setError(errorText(e));setConfirmed(false);}});return()=>{current=false;};
 },[studyId,app.refreshTick,tick]);
 useEffect(()=>{if(info)setFormat(old=>(info.formats[database]||[]).includes(old)?old:(info.formats[database]?.[0]||''));},[database,info]);
 const disabled=saving||!!info?.busy;const ready=!!(info?.enabled&&file&&query.trim()&&date.trim()&&version.trim()&&author.trim()&&note.trim());
 /** 请求号在同一文件的网络失败后保留；409仅刷新，不自动重交旧状态。 */
 async function upload(){
  if(!ready||!confirmed||disabled||!file||!info?.expected_a00||!info.expected_plan_id||!info.expected_input_hash)return;
  if(!file.size||file.size>16*1024*1024){setError('请选择非空、16MiB以内的原件；请求包含元信息时还受服务端总容量限制。');return;}
  const fields={expected_a00:info.expected_a00,expected_plan_id:info.expected_plan_id,expected_input_hash:info.expected_input_hash,
   author:author.trim(),note:note.trim(),confirmed:'yes',database,format,query:query.trim(),retrieved_at:date.trim(),
   version:version.trim(),encoding,query_quoted:quoted,export_completeness:completeness};
  const signature=JSON.stringify({...fields,file:[file.name,file.size,file.lastModified]});
  if(request.current.signature!==signature)request.current={signature,id:'manualsourceq_'+crypto.randomUUID().replace(/-/g,'')};
  const data=new FormData();for(const [key,value] of Object.entries({...fields,request_id:request.current.id}))data.append(key,value);data.append('upload',file);
  setSaving(true);setError('');setNotice('');
  try{const result=await api.uploadSystemDiseaseManualSource(studyId,data);
   if(result.task.state==='failed')setError(result.task.error_zh??'上传任务启动失败，请查看后台记录');else{
    setNotice(result.message_zh);app.trackTasks([result.task]);app.openTasks(result.task.task_id);}
   setConfirmed(false);app.bumpRefresh();
  }catch(e){setError(errorText(e));if(e instanceof ApiError&&e.status===409){setConfirmed(false);setTick(n=>n+1);}}
  finally{setSaving(false);}
 }
 return <section className="stack" id="system-disease-manual-sources"><h3>先保存GeneCards／OMIM原件</h3>
  <p>首次建档后可直接保存本研究原件，无需先通过登记。上传会核对文件与疾病身份，尚不生成候选；完成后再明确核验五库。版本未知可据实暂存，后续仍会待核，不自动放行。</p>
  {error&&<Alert type="error" showIcon message={error} action={<Button onClick={()=>setTick(n=>n+1)}>重新读取上传资格</Button>}/>}
  {notice&&<Alert type="success" showIcon message={notice}/>}
  {!info?(!error&&<Skeleton active/>):<>
   {!info.enabled&&<Alert type="warning" showIcon message={info.blockers.join('；')}/>}
   <Table size="small" rowKey="database" pagination={false} dataSource={info.sources} scroll={{x:850}}
    locale={{emptyText:'尚未预上传本研究原件，不表示查询为零'}}
    columns={[{title:'来源',dataIndex:'database',width:95},{title:'实际状态',dataIndex:'status_zh',width:150},{title:'实际原文件',dataIndex:'name'},
     {title:'原版本说明',dataIndex:'version',width:130},
     {title:'原获取日期',dataIndex:'retrieved_at',width:120},{title:'字节数',dataIndex:'bytes',width:100},
     {title:'SHA-256',dataIndex:'sha256',render:(value:string)=><span title={value}>{value.slice(0,16)}…</span>}]}/>
   <div className="source-field-grid">
   <label>手动原件数据库<Select aria-label="手动原件数据库" style={{width:'100%'}} value={database} disabled={disabled}
    options={Object.keys(info.formats).map(value=>({value,label:value}))} onChange={value=>{setDatabase(value);setFile(null);setDate('');setVersion('');setQuoted('unknown');setCompleteness('unknown');setConfirmed(false);}}/></label>
   <label>手动原件格式<Select aria-label="手动原件格式" style={{width:'100%'}} value={format} disabled={disabled}
    options={(info.formats[database]||[]).map(value=>({value,label:LABELS[value]||value}))} onChange={value=>{setFormat(value);setFile(null);setConfirmed(false);}}/></label>
   <label>原检索词<Input aria-label="手动原件检索词" value={query} maxLength={2000} disabled={disabled} onChange={e=>{setQuery(e.target.value);setConfirmed(false);}}/></label>
   <label>原获取日期<Input aria-label="手动原件获取日期" placeholder="按原件记录填写，不自动改为今天" value={date} maxLength={2000} disabled={disabled} onChange={e=>{setDate(e.target.value);setConfirmed(false);}}/></label>
   <label>原数据库版本或快照说明<Input aria-label="手动原件版本" value={version} maxLength={2000} disabled={disabled} onChange={e=>{setVersion(e.target.value);setConfirmed(false);}}/></label>
   <label>上传登记人<Input aria-label="手动原件上传人" value={author} maxLength={2000} disabled={disabled} onChange={e=>{setAuthor(e.target.value);setConfirmed(false);}}/></label>
   <label>原始文件<input key={studyId+database+format} type="file" aria-label="疾病手动原件文件" disabled={disabled}
    accept={format==='omim_xlsx_v2'?'.xlsx':format==='genecards_csv'?'.csv':'.txt,.tsv'}
    onChange={e=>{setFile(e.target.files?.[0]||null);setConfirmed(false);request.current={signature:'',id:''};}}/></label>
   <label>编码<Select aria-label="手动原件编码" style={{width:'100%'}} value={encoding} disabled={disabled} options={[{value:'utf-8-sig',label:'UTF-8'},{value:'gbk',label:'GBK'}]} onChange={v=>{setEncoding(v);setConfirmed(false);}}/></label>
   {database==='GeneCards'&&<><label>原检索词是否加引号<Select aria-label="手动原件检索引号" style={{width:'100%'}} value={quoted} disabled={disabled}
    options={[{value:'unknown',label:'原件未说明'},{value:'yes',label:'是'},{value:'no',label:'否'}]} onChange={v=>{setQuoted(v);setConfirmed(false);}}/></label>
    <label>原导出完整性<Select aria-label="手动原件导出完整性" style={{width:'100%'}} value={completeness} disabled={disabled}
     options={[{value:'unknown',label:'原件未说明'},{value:'complete',label:'完整导出'},{value:'partial',label:'部分导出'}]} onChange={v=>{setCompleteness(v);setConfirmed(false);}}/></label></>}
   <label className="source-field-wide">上传依据<Input.TextArea aria-label="手动原件上传依据" value={note} maxLength={2000} disabled={disabled} onChange={e=>{setNote(e.target.value);setConfirmed(false);}}/></label>
   </div>
   <Checkbox checked={confirmed} disabled={disabled||!info.enabled} onChange={e=>setConfirmed(e.target.checked)}>我已核对原件、原检索词与本研究，确认仅预上传资料</Checkbox>
   <Button type="primary" loading={saving} disabled={disabled||!ready||!confirmed} onClick={()=>void upload()}>校验并保存本研究原件</Button>
  </>}
 </section>;
}
