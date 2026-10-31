"""逐对象恢复用明确合成几何；真实Meeko/Vina，预测CSV为合成而非真实P2Rank。"""
from copy import deepcopy
from storage import file_record
from tests.modulea.plan_report_scoring_fixture import Sources
from science_modules.a06.plan_quality_engine_v2 import prediction_box
from science_modules.a06.two_pass import pocket_key


class ObjectSources:
    def __init__(self,packet):
        self.packet=deepcopy(packet);self.source=Sources();self.calls=[];self.attempts=[]

    def connect(self,home,packet,folder,progress):
        """仅替换官方响应，按请求单对象裁取同一明确合成原件集。"""
        value=self.source.connect(home,self.packet,folder,progress)
        for kind,key,identity in (('compound','compounds','compound_id'),('receptor','receptors','target_id')):
            wanted={r[identity] for r in packet[key]};value[key]=[row for row in value[key] if row[identity] in wanted]
            self.calls.extend((kind,r[identity]) for r in value[key])
        return value

    def attempt(self,home,source,row,spec,round_no,folder,tools,progress,**kwargs):
        """落盘合成双预测与坐标，原搜索盒/质控/RMSD规范另行真实验证。"""
        self.attempts.append((row['target_id'],deepcopy(spec)));folder.mkdir(parents=True,exist_ok=False)
        pdb=folder/'input.pdb';pdb.write_text(self.source.pdb,encoding='ascii');receptor=folder/'receptor.pdbqt'
        receptor.write_text('\n'.join(line[:77]+'C' for line in self.source.pdb.splitlines() if line.startswith('ATOM'))+'\n',encoding='ascii')
        prediction={'rank':'1','score':'9.0','probability':'0.9','center_x':'1','center_y':'2','center_z':'3','residue_ids':'A_10'};refs=[]
        for serial in (1,2):
            path=folder/f'explicit_synthetic_prediction_{serial}.csv'
            path.write_text(','.join(prediction)+'\n'+','.join(prediction.values())+'\n',encoding='utf8')
            refs.append(file_record(home,path,'p2rank_prediction'))
        pocket={'rank':1,'runs':[prediction,prediction],'mapped_indices':['A_10'],'confirmation':{}};pocket['pocket_key']=pocket_key(spec,pocket)
        return {'structure_id':'1ABC','identity':{'target_id':row['target_id'],'uniprot':'P12345','species':9606,
                'polymer_type':'Protein','sequence_matches':True,'chains':['A']},
            'receptor_ready':True,'pocket_complete':True,'environment_resolved':True,
            'error_zh':'明确合成两次预测一致，等待系统技术核验，不是真实P2Rank执行',
            'receptor':file_record(home,receptor,'receptor'),'pocket':pocket,
            'box':prediction_box(self.source.pdb,prediction,kwargs['box_padding']),
            'predicted_pocket':{'files':refs,'input_pdb':file_record(home,pdb,'p2rank_input_pdb')},
            'files':refs+[file_record(home,receptor,'receptor'),file_record(home,pdb,'p2rank_input_pdb')]}
