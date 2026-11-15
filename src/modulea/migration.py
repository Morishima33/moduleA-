"""研究跨电脑完整性核对；复用登记原件遍历，不改写旧路径、批准或执行绑定。"""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from contracts import fingerprint, require, safe_id
from storage import read_json, verified_file
from .core.trace_export import _records


def inventory(data_root, study_id):
    """从manifest开始递归核验已登记JSON中的原件引用，未登记残件不作为成功。"""
    safe_id(study_id,'study')
    home=(Path(data_root)/'studies'/study_id).resolve()
    raw=(home/'manifest.json').read_bytes()
    manifest=json.loads(raw)
    require(manifest['study_id']==study_id,'迁移研究身份不同')
    queue=[];_records(manifest,queue)
    seen={};rows=[];originals=[]
    while queue:
        reference=queue.pop(0)
        path=reference['path']
        if path in seen:
            require(seen[path]==(reference['bytes'],reference['sha256']), '登记原件同路径存在不同指纹：'+path)
            continue
        actual=verified_file(home,reference)
        content=actual.read_bytes()
        require(len(content)==reference['bytes'] and sha256(content).hexdigest()==reference['sha256'],
                '迁移核验期间原件校验失败：'+path)
        seen[path]=(len(content),reference['sha256'])
        originals.append(reference)
        rows.append({key:reference[key] for key in ('path','bytes','sha256')})
        if actual.suffix.lower()=='.json':
            # 非JSON的旧附件不猜解析；已登记JSON损坏必须失败，不能漏掉其后代原件。
            _records(json.loads(content),queue)
    # 返回前再次核对全部原件，避免先读文件在后续遍历期间被替换。
    for reference in originals:verified_file(home,reference)
    require((home/'manifest.json').read_bytes()==raw,'迁移核验期间研究登记已改变，请在任务写入结束后重试')
    rows.sort(key=lambda r:r['path'])
    value={'schema_version':'ModuleA.migration_inventory.1','study_id':study_id,
           'manifest_sha256':sha256(raw).hexdigest(),'manifest_bytes':len(raw),'files':rows,
           'file_count':len(rows),'read_only':True,'unregistered_files_included':False}
    value['inventory_sha256']=fingerprint(value)
    return value


def verify(data_root, expected):
    """迁入后逐件核原长度和SHA；历史可读性与旧批继续执行资格分开。"""
    require(expected.get('schema_version')=='ModuleA.migration_inventory.1','迁移清单版本不同')
    copy=dict(expected);digest=copy.pop('inventory_sha256',None)
    require(fingerprint(copy)==digest,'迁移清单本身指纹不同')
    actual=inventory(data_root,expected['study_id'])
    require(actual==expected,'迁入研究与原清单、登记或原件字节不同')
    return {'schema_version':'ModuleA.migration_verification.1','study_id':expected['study_id'],
            'history_integrity_verified':True,'file_count':actual['file_count'],
            'inventory_sha256':digest,'resume_allowed':False,
            'resume_note_zh':'历史已登记字节完整。恢复计算仍须原Workflow逐项核对输入、代码、工具与执行绑定并明确提交；'
                '不同平台或工具须另立新运行，不将路径迁移冒充原批次无缝恢复。',
            'human_review_written':False,'scientific_computation_performed':False}


def main(argv=None):
    """清单保存于用户指定的仓库外文件；本入口只读研究原件。"""
    parser=argparse.ArgumentParser(description='Module A研究迁移完整性核对')
    parser.add_argument('action',choices=('inventory','verify'))
    parser.add_argument('--data-root',type=Path,required=True)
    parser.add_argument('--study',required=True)
    parser.add_argument('--inventory',type=Path,required=True)
    args=parser.parse_args(argv)
    if args.action=='inventory':
        value=inventory(args.data_root,args.study)
        destination=args.inventory.resolve()
        require(not destination.is_relative_to(args.data_root.resolve()),'迁移清单请保存到数据根以外，不修改研究资料')
        with destination.open('x',encoding='utf-8') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
        print('已核验并保存迁移清单：'+str(destination))
    else:
        expected=read_json(args.inventory)
        require(expected.get('study_id')==args.study,'清单与指定研究不同')
        print(json.dumps(verify(args.data_root,expected),ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
