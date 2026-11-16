"""A06新平台工具适配：原生工具、固定参数、真实命令与完整依赖指纹，旧Windows入口保持。"""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import FunctionType

from contracts import fingerprint, require
from storage import new_id, now, write_json
from modulea.core.bounded_evidence import digest_file, file_record, verified_file
from modulea.core.worker_io import WorkerIO
from modulea.platform_preflight import verify_profile

VERSION = 'A06.platform_execution.1'


class NativeTools:
    """仅供隔离科学worker使用；浏览器不提供路径或命令，所有依赖来自本机明确配置。"""
    def __init__(self, settings):
        require(sys.flags.isolated, '新平台科学工具必须由-I隔离解释器启动')
        self.settings = settings
        self.profile, self.facts = verify_profile(settings)
        self.python = str(Path(settings.science_python).absolute())
        self.vina = Path(self.profile['vina']['path']).resolve()
        self.java = Path(self.profile['java']['path']).resolve()
        self.p2rank = Path(self.profile['p2rank']['path']).resolve()
        # 有限侧链修补沿用原脚本的精确版本；不以本机已有较旧版本静默降级。
        require(self.profile['packages']['meeko'] == '0.8.0' and
                self.profile['packages']['pdbfixer'] == '1.12.0' and
                self.profile['packages']['openmm'] == '8.4.0',
                '新平台结构/有限修补固定Meeko0.8.0、PDBFixer1.12.0、OpenMM8.4.0')
        self.signature_value = self.signature()
        self.signature_sha256 = fingerprint(self.signature_value)

    def signature(self):
        """绑定实际包源码、模板、原生库、Java运行库及P2Rank，不只相信版本元数据。"""
        script = '''import importlib.metadata,json,pathlib
files=set()
for d in importlib.metadata.distributions():
 source=d.read_text('direct_url.json')
 if source and json.loads(source).get('dir_info',{}).get('editable') is True:
  raise RuntimeError('新原生协议不支持editable依赖，须在独立科学环境使用普通安装：'+str(d.metadata.get('Name','unknown')))
 records=d.files
 if not records:
  raise RuntimeError('已安装依赖没有完整文件清单，不能证明同批工具未变：'+str(d.metadata.get('Name','unknown')))
 for relative in records:
  if '__editable__' in str(relative) or str(relative).endswith('.egg-link'):
   raise RuntimeError('新原生协议不支持editable加载器，须使用完整普通安装')
  p=pathlib.Path(d.locate_file(relative)).resolve()
  if p.is_file() and p.suffix not in ('.pyc','.pyo') and '__pycache__' not in p.parts:
   files.add(str(p))
print(json.dumps(sorted(files)))
'''
        done = subprocess.run([self.python,'-I','-B','-X','utf8','-c',script],capture_output=True,text=True,encoding='utf-8',timeout=30)
        require(done.returncode == 0, '无法枚举新平台实际依赖文件：'+done.stderr[-1000:])
        files = set(map(Path,json.loads(done.stdout)))
        files.update((self.vina,self.java,Path(self.settings.tools_profile).resolve(),Path(self.python).resolve()))
        code=Path(__file__).resolve().parents[3]
        # 动态复用会进入扁平科学、状态及外壳模块；绑定整个产品源码，避免手列依赖遗漏。
        # 此较保守范围仅用于新原生协议，旧批次的版本与恢复规则不改。
        files.update(p for p in (code/'src').rglob('*') if p.is_file() and p.suffix in ('.py','.R'))
        files.update(code/name for name in ('tools/repair_a06_trial.py','tools/run_native_execution.py'))
        java_home = self.java.parent.parent
        files.update(p for p in java_home.rglob('*') if p.is_file() and
                     (p.suffix.lower() in ('.dylib','.dll','.so') or p.name in ('release','modules')))
        for name in self.profile['p2rank']['files']:files.add((self.p2rank/name).resolve())
        for font in (self.settings.font_regular,self.settings.font_bold):
            require(font and Path(font).is_file(), '新平台最终图件需要明确可用中文常规/粗体')
            files.add(Path(font).resolve())
        records = {}
        for path in sorted(files):
            size,digest=digest_file(path)
            # 外部工具不是研究包内的文件引用，不用path/bytes/sha256三字段伪装登记原件。
            records[str(path)]={'bytes':size,'sha256':digest}
        for tool in ('vina','java'):
            require(records[str(getattr(self,tool))]['sha256']==self.profile[tool]['sha256'],
                    tool+'工具在版本预检后已改变')
        require(records[str(Path(self.settings.tools_profile).resolve())]['sha256']==self.facts['profile']['sha256'],
                '工具配置文件在读取期间改变')
        actual_p2={p.relative_to(self.p2rank).as_posix() for directory in ('bin','config','models')
                   for p in (self.p2rank/directory).rglob('*') if p.is_file()}
        require(actual_p2==set(self.profile['p2rank']['files']), 'P2Rank全部程序、配置和模型必须完整列入本机工具清单')
        for name,digest in self.profile['p2rank']['files'].items():
            require(records[str((self.p2rank/name).resolve())]['sha256']==digest,'P2Rank工具或模型已改变：'+name)
        return {'schema_version':VERSION,'system':self.profile['system'],'machine':self.profile['machine'],
                'packages':dict(self.profile['packages']),'files':records,
                'python':self.python,'profile_sha256':self.facts['profile']['sha256'],
                'execution_environment':{'OPENMM_CPU_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}}

    def verify_current(self):
        """准备/评分开始和发表前完整重核，运行中不能静默切换工具、模型或解释器。"""
        require(fingerprint(self.signature()) == self.signature_sha256, '新平台工具、模型、依赖或字体已改变')

    def run(self, command, folder, record, *, cwd=None, timeout=900, environment=None):
        """固定argv、无shell，真实命令/日志/返回码另存；取消继承原任务进程树。"""
        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        env=dict(os.environ)
        for key in ('PYTHONPATH','PYTHONHOME','JAVA_TOOL_OPTIONS','JDK_JAVA_OPTIONS','JAVA_OPTS','CLASSPATH',
                    'DYLD_INSERT_LIBRARIES','DYLD_LIBRARY_PATH','LD_PRELOAD'):
            env.pop(key,None)
        env.update(environment or {})
        env.update(self.signature_value['execution_environment'])
        write_json(folder/(record+'.request.json'),{'arguments':command,'platform_protocol':VERSION,
            'tools_sha256':self.signature_sha256,'execution_environment':self.signature_value['execution_environment']})
        print('PROGRESS 原生工具：'+Path(command[0]).name,flush=True)
        try:
            done=subprocess.run(command,cwd=cwd or folder,env=env,capture_output=True,
                text=True,encoding='utf-8',errors='replace',timeout=timeout)
            value={'arguments':command,'returncode':done.returncode,'stdout':done.stdout,'stderr':done.stderr,
                   'finished_at':now(),'platform_protocol':VERSION,'tools_sha256':self.signature_sha256}
        except subprocess.TimeoutExpired as error:
            write_json(folder/record,{'arguments':command,'returncode':None,'failure_kind':'timeout',
                'reason_zh':'工具执行超时','platform_protocol':VERSION,'tools_sha256':self.signature_sha256})
            raise ValueError('新平台工具执行超时，已有诊断保留') from error
        write_json(folder/record,value)
        require(done.returncode == 0, '新平台工具执行失败，详见'+record+'：'+done.stderr[-1200:])
        return done

    def copy_vina(self, home, folder, *, name=None):
        """只复制已核验原生二进制并保留执行权限；绝不把PE在Mac上直接运行。"""
        target=Path(folder)/(name or ('vina.exe' if os.name=='nt' else 'vina'))
        target.parent.mkdir(parents=True,exist_ok=True)
        require(not target.exists(),'禁止覆盖本批Vina快照')
        shutil.copy2(self.vina,target)
        require(digest_file(target) == digest_file(self.vina),'Vina复制字节不一致')
        require(os.access(target,os.X_OK),'本批原生Vina没有执行权限')
        return target

    def prepare_receptor(self, root, pdb_text, box, label, folder):
        """沿原Meeko刚性准备参数，不允许坏残基豁免或修改搜索盒。"""
        folder=Path(folder)/'receptors';folder.mkdir(parents=True,exist_ok=True)
        source=folder/(label+'_input.pdb')
        with source.open('x',encoding='ascii',newline='\n') as stream:stream.write(pdb_text)
        output=folder/label
        command=[self.python,'-I','-B','-X','utf8','-m','meeko.cli.mk_prepare_receptor','--read_pdb',str(source),
            '-o',str(output),'-p','--write_pdb',str(output)+'_prepared.pdb',
            '--box_center',*[str(x) for x in box['center']],
            '--box_size',*[str(x) for x in box['size']],'--delete_bad_res_from_box_radius','0.0']
        self.run(command,folder,label+'_prepare_execution.json',timeout=600)
        path=Path(str(output)+'.pdbqt')
        require(path.is_file() and path.stat().st_size>0,'Meeko未输出完整受体')
        return path

    def predict_twice(self, tool_dir, pdb_path, output_dir, target, root):
        """Java直接启动官方2.5主类；原单线程/两遍/首位包络规则与原始CSV均保留。"""
        from docking_p2rank import _prediction_rows, box_from_prediction
        output=Path(output_dir);output.mkdir(parents=True,exist_ok=False)
        pdb_path=Path(pdb_path).resolve()
        separator=';' if os.name=='nt' else ':'
        classpath=str(self.p2rank/'bin/p2rank.jar')+separator+str(self.p2rank/'bin/lib/*')
        env={'INSTALL_DIR':str(self.p2rank),'JAVA_HOME':str(self.java.parent.parent)}
        rows=[];files=[]
        for repeat in (1,2):
            directory=output/f'repeat_{repeat}'
            command=[str(self.java),'-Xmx2048m','-cp',classpath,'cz.siret.prank.program.Main',
                'predict','-f',str(pdb_path),'-threads','1','-visualizations','0','-o',str(directory)]
            self.run(command,output,f'repeat_{repeat}_execution.json',cwd=self.p2rank,environment=env)
            predictions=list(directory.rglob('*_predictions.csv'))
            require(len(predictions)==1,'P2Rank预测表缺失或不唯一，不能解释为无口袋')
            rows.append(_prediction_rows(predictions[0])[0])
            files += [file_record(root,predictions[0],'p2rank_prediction'),
                      file_record(root,output/f'repeat_{repeat}_execution.json','p2rank_execution')]
        keys=('rank','score','probability','center_x','center_y','center_z','residue_ids')
        require(int(rows[0]['rank'])==1 and all(rows[0][k]==rows[1][k] for k in keys),'两次P2Rank首位口袋不一致')
        value={'schema_version':'A06.platform_p2rank.1','target':target,'p2rank_version':'2.5',
            'tools_sha256':self.signature_sha256,'input_pdb':file_record(root,pdb_path,'p2rank_input_pdb'),
            'selected_pocket_rank':1,'score':float(rows[0]['score']),'probability':float(rows[0]['probability']),
            'box':box_from_prediction(pdb_path.read_text('ascii'),rows[0],5.0),
            'repeat_consistent':True,'redocking_status':'not_applicable_no_reference_ligand','files':files,'created_at':now()}
        write_json(output/'pocket.json',value)
        return value

    def repair_observed(self, source, output, evidence, folder):
        """原有限修补脚本原字节复用，固定CPU和版本，原重原子及主链约束照常阻断。"""
        code=Path(__file__).resolve().parents[3]
        script=code/'tools/repair_a06_trial.py'
        packages=Path(self.facts['packages']['pdbfixer']['origin']).resolve().parent.parent
        command=[self.python,'-I','-B','-X','utf8',str(script),'--packages',str(packages),
            '--input',str(source),'--output',str(output),'--evidence',str(evidence)]
        self.run(command,folder,'repair_native_execution.json',timeout=600)
        require(Path(output).is_file() and Path(evidence).is_file(),'有限修补未输出完整证据')
        return file_record(folder,output,'repair_output'),file_record(folder,evidence,'repair_evidence')


def validate_pair(*args):
    """原组合完整校验器只替换路径解析及流式SHA，参数/Top1/失败判断完全复用。"""
    from .plan_score_pair import validate,arguments
    namespace=dict(arguments.__globals__,tool_path=lambda path:str(Path(path).resolve()))
    native_arguments=FunctionType(arguments.__code__,namespace,arguments.__name__,arguments.__defaults__)
    namespace=dict(validate.__globals__,arguments=native_arguments,verified_file=verified_file,file_record=file_record)
    return FunctionType(validate.__code__,namespace,validate.__name__,validate.__defaults__)(*args)


class NativeIO(WorkerIO):
    """沿用有界I/O，明确替换本机工具调用；不改冻结科学判断、身份、阈值或参数。"""
    def __init__(self, tools):
        super().__init__()
        self.tools=tools

    def project_code(self,function):
        """本适配自己的函数已经采用有界I/O；只克隆被复用的冻结实现。"""
        if isinstance(function,FunctionType):
            path=Path(function.__code__.co_filename).resolve()
            if path.name in ('native_execution.py','native_tools.py','native_display.py'):
                return False
        return super().project_code(function)

    def value(self, value):
        from docking_top10_execute import _prepare_receptor_cli
        from docking_p2rank import run_twice
        from science_modules.a06.plan_preparation_v2 import _version
        from science_modules.a06.plan_quality_engine_v2 import tool_path
        from science_modules.a06.plan_quality_engine_v2 import redock
        if value is _prepare_receptor_cli:return self.tools.prepare_receptor
        if value is run_twice:return self.tools.predict_twice
        if value is _version:return lambda _:self.tools.vina
        if value is tool_path:return lambda path:str(Path(path).resolve())
        if value is redock:
            def native_redock(_legacy_executable,*args,**kwargs):
                """只替换原生命令路径，重对接参数、MODEL1及对称RMSD复用冻结函数。"""
                namespace=dict(redock.__globals__,tool_path=lambda path:str(Path(path).resolve()))
                function=FunctionType(redock.__code__,namespace,redock.__name__,redock.__defaults__,redock.__closure__)
                return function(getattr(self.tools,'execution_vina',self.tools.vina),*args,**kwargs)
            return native_redock
        return super().value(value)
