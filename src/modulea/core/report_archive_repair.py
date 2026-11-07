"""恢复精确原报告字节并独立保留批注；不重签原指纹、不改科研结果或复核。"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path, PurePosixPath
import json
import os
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from contracts import fingerprint, require, safe_id
from storage import file_record, new_id, now, read_json, verified_file, within, write_json, write_lock

VERSION = 'ModuleA.report_archive_repair.1'
REQUESTS = 'analysis_plan_report_archive_repair_requests'
RECEIPTS = 'analysis_plan_report_archive_repairs'
FIELDS = {'request_id','expected_run_id','document_index','expected_original_sha256',
          'expected_modified_sha256','author','note','confirmed'}
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS = {'w': W, 'a': A}


def document_evidence(raw):
    """只解析归档Word的正文/表格/图片与批注，不执行字段、宏或外部链接。"""
    with ZipFile(BytesIO(raw)) as archive:
        members = archive.infolist()
        require(len(members) <= 2000 and sum(i.file_size for i in members) <= 100_000_000
                and len({i.filename for i in members}) == len(members), '报告压缩包重复、过大或成员过多')
        names = set(archive.namelist())
        require('word/document.xml' in names and archive.testzip() is None, '报告不是完整Word压缩包')
        require(not any('vbaproject' in n.lower() or n.startswith('word/embeddings/') for n in names),
                '本恢复接口不接受宏或嵌入程序对象')
        stories, markers, images = {}, {}, []
        for name in sorted(names):
            if not re.fullmatch(r'word/(document|footnotes|endnotes|header[0-9]+|footer[0-9]+)\.xml', name):
                continue
            tree = ET.fromstring(archive.read(name))
            # Word保存批注时可补入脚注/尾注分隔符，空系统分隔符不是研究正文。
            if name in ('word/footnotes.xml','word/endnotes.xml'):
                for note in list(tree):
                    if note.get('{'+W+'}type') in ('separator','continuationSeparator'):
                        require(not note.findall('.//w:t',NS) and not note.findall('.//w:instrText',NS),
                                '系统注释分隔符含正文，不能忽略')
                        tree.remove(note)
                if not len(tree): continue
            text = lambda p: ''.join((n.text or '') if n.tag in ('{'+W+'}t','{'+W+'}instrText') else
                                    '\t' if n.tag == '{'+W+'}tab' else '\n' if n.tag == '{'+W+'}br' else ''
                                    for n in p.iter())
            stories[name] = {'paragraphs': [text(p) for p in tree.findall('.//w:p', NS)],
                'tables': [[[text(c) for c in row.findall('w:tc', NS)] for row in table.findall('w:tr', NS)]
                           for table in tree.findall('.//w:tbl', NS)]}
            markers[name] = {key: [n.get('{'+W+'}id') for n in tree.findall('.//w:'+key, NS)]
                             for key in ('commentRangeStart','commentRangeEnd','commentReference')}
            rel_path = str(PurePosixPath(name).parent/'_rels'/(PurePosixPath(name).name+'.rels'))
            rels = {n.get('Id'): n for n in ET.fromstring(archive.read(rel_path))} if rel_path in names else {}
            for blip in tree.findall('.//a:blip', NS):
                rid = blip.get('{'+R+'}embed')
                require(rid in rels and rels[rid].get('TargetMode') != 'External', '报告图片不是已归档内部原件')
                target = rels[rid].get('Target', '')
                require(not target.startswith('/') and '..' not in PurePosixPath(target).parts, '报告图片引用越界')
                images.append(sha256(archive.read(str(PurePosixPath(name).parent/target))).hexdigest())
        comments = []
        if 'word/comments.xml' in names:
            for n in ET.fromstring(archive.read('word/comments.xml')):
                comments.append({'id': n.get('{'+W+'}id'), 'author': n.get('{'+W+'}author'),
                    'date': n.get('{'+W+'}date'), 'text': ''.join(t.text or '' for t in n.findall('.//w:t', NS))})
        ids = [c['id'] for c in comments]
        require(len(set(ids)) == len(ids), '报告批注编号重复')
        refs = [i for story in markers.values() for i in story['commentReference']]
        require(set(refs) == set(ids), '报告批注与锚点不匹配')
        for story in markers.values():
            require(sorted(story['commentRangeStart']) == sorted(story['commentRangeEnd'])
                    and set(story['commentRangeStart']) <= set(ids), '报告批注范围锚点不完整')
        return {'content_hash': fingerprint((stories, images)), 'comment_count': len(comments),
                'comment_hash': fingerprint(comments), 'anchor_hash': fingerprint(markers)}


def _source(w, m, body):
    """原文档只能来自本研究已登记A07结果，不接受路径或新指纹替换原登记。"""
    rid = body['expected_run_id']; run = w.run(m, rid); home = w.location(m['study_id'])
    result_ref = m['runs'][rid].get('result_file')
    require(run['module_id'] == 'A07' and result_ref, '只能恢复已归档A07报告')
    # 修复入口先核验不可变结果JSON，唯一允许损坏的对象仍由其中原SHA指定。
    # 普通result()/view()/下载继续保留完整校验，不能借此读取其他失配附件。
    result = read_json(verified_file(home,result_ref))
    require(result['run_id'] == rid and result['study_id'] == m['study_id'] and result['module_id'] == 'A07'
            and result['artifact_id'] == run['artifact_id'],
            '原报告结果归属不同')
    rows = result.get('tables', {}).get('report_files', [])
    index = body['document_index']
    require(type(index) is int and 0 <= index < len(rows), '报告文档序号无效')
    ref = rows[index]
    require(ref in result['files'] and ref.get('role') in ('brief_report','detailed_report')
            and ref['path'].startswith('runs/A07/'+rid+'/') and ref['path'].endswith('.docx')
            and ref['sha256'] == body['expected_original_sha256'], '恢复目标与原报告登记不一致')
    for item in result['files']:
        if item['path'] != ref['path']: verified_file(home,item)
    return deepcopy(ref)


def read_request(w, m, ref):
    """恢复计划及两份原始字节先登记；中断不丢批注，也不自行恢复。"""
    require(ref in m.get(REQUESTS, []), '报告恢复请求未登记')
    home = w.location(m['study_id']); value = read_json(verified_file(home, ref))
    body = value['request']
    require(value['schema_version'] == VERSION and value['study_id'] == m['study_id']
            and value['request_hash'] == fingerprint(body) and body['confirmed'] is True
            and value['original_file'] == _source(w, m, body)
            and m['runs'][body['expected_run_id']] == value['run_files'], '报告恢复归属或原运行登记不同')
    for item in (value['original_copy'],value['annotation_file']): verified_file(home, item)
    original = verified_file(home,value['original_copy']).read_bytes()
    annotation = verified_file(home,value['annotation_file']).read_bytes()
    require(sha256(original).hexdigest() == body['expected_original_sha256']
            and sha256(annotation).hexdigest() == body['expected_modified_sha256']
            and document_evidence(original)['content_hash'] == value['annotation_evidence']['content_hash']
            and document_evidence(annotation) == value['annotation_evidence'], '报告恢复原件、正文或批注证据不同')
    return value


def read_receipt(w, m, ref):
    """完成回执同时验证原报告和批注附件，不凭文件存在放宽原完整性校验。"""
    require(ref in m.get(RECEIPTS, []), '报告恢复回执未登记')
    home = w.location(m['study_id']); value = read_json(verified_file(home, ref))
    request = read_request(w, m, value['request_file'])
    require(value['schema_version'] == VERSION and value['study_id'] == m['study_id']
            and value['request_id'] == request['request']['request_id']
            and value['run_id'] == request['request']['expected_run_id']
            and value['original_file'] == request['original_file']
            and value['annotation_file'] == request['annotation_file']
            and value['annotation_evidence'] == request['annotation_evidence']
            and value['human_review_written'] is False and value['scientific_results_changed'] is False,
            '报告恢复回执与实际保全计划不同')
    safe_id(value['repair_id'], 'reportrepair')
    verified_file(home, value['original_file'])
    return value


def _save_bytes(path, raw):
    """不可变保全副本逐字节一致才可复用，禁止覆盖另一份批注。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == raw, '恢复保全目录已有不同内容，不能覆盖')
    else:
        with path.open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def _restore(path, raw, expected_modified):
    """同目录原子恢复精确原件；操作前再次检查批注字节，原指纹不变。"""
    require(sha256(path.read_bytes()).hexdigest() == expected_modified, '恢复前文档再次变化，停止以保留最新内容')
    temporary = path.with_name('.'+new_id('reportrestore')+'.tmp')
    try:
        _save_bytes(temporary, raw)
        require(sha256(path.read_bytes()).hexdigest() == expected_modified, '恢复期间文档变化，停止操作')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def repair(w, sid, body, original_bytes):
    """仅明确授权后恢复原报告，批注单独归档；current/runs/reviews及旧SHA均不重写。"""
    require(isinstance(body,dict) and set(body) == FIELDS, '报告恢复字段错误，不接受路径或指纹覆盖')
    safe_id(body['request_id'],'reportrepairreq'); safe_id(body['expected_run_id'],'run')
    require(body['confirmed'] is True and all(isinstance(body[k],str) and 0 < len(body[k].strip()) <= 2000 for k in ('author','note')),
            '须明确登记恢复人、依据和保留批注')
    require(all(isinstance(body[k],str) and re.fullmatch('[0-9a-f]{64}',body[k]) for k in
                ('expected_original_sha256','expected_modified_sha256')) and isinstance(original_bytes,bytes)
            and sha256(original_bytes).hexdigest() == body['expected_original_sha256'], '备份不是原登记精确字节')
    with write_lock(w.root):
        m = w.load(sid); require(not m.get('trashed'), '回收站研究只读')
        home = w.location(sid); source = _source(w,m,body); target = within(home,source['path'])
        before = {k:deepcopy(m[k]) for k in ('current','runs','reviews')}
        previous = [(ref,read_request(w,m,ref)) for ref in m.get(REQUESTS,[])
                    if read_json(verified_file(home,ref))['request']['request_id'] == body['request_id']]
        if previous:
            request_ref, request = previous[0]
            require(request['request'] == body, '原请求号已用于另一份恢复')
            for ref in m.get(RECEIPTS,[]):
                value = read_receipt(w,m,ref)
                if value['request_file'] == request_ref: return dict(value,file=ref,created=False)
        else:
            annotated = target.read_bytes()
            require(sha256(annotated).hexdigest() == body['expected_modified_sha256']
                    and body['expected_modified_sha256'] != source['sha256'], '待保全文档已改变或无需恢复')
            details = document_evidence(annotated)
            require(document_evidence(original_bytes)['content_hash'] == details['content_hash'],
                    '正文、表格或图片与原档不同，不能仅作为批注附件自动恢复')
            folder = home/'decisions/analysis_plans/report_archive_repairs'/body['request_id']
            _save_bytes(folder/'annotated.docx',annotated); _save_bytes(folder/'original.docx',original_bytes)
            request = {'schema_version':VERSION,'study_id':sid,'request':deepcopy(body),'request_hash':fingerprint(body),
                'run_files':deepcopy(m['runs'][body['expected_run_id']]),'original_file':source,
                'original_copy':file_record(home,folder/'original.docx','restored_report_backup'),
                'annotation_file':file_record(home,folder/'annotated.docx','user_annotated_report'),
                'annotation_evidence':details,'created_at':now()}
            path = folder/'request.json'
            require(not path.exists(), '未登记恢复计划已存在，保全原件后使用新请求号')
            write_json(path,request);request_ref=file_record(home,path,'report_archive_repair_request')
            m.setdefault(REQUESTS,[]).append(request_ref);w.save(m)
        # 中断恢复只接受最初已保全的批注或精确原档；第三种内容一律阻断。
        current = sha256(target.read_bytes()).hexdigest()
        require(current in (source['sha256'],body['expected_modified_sha256']), '待恢复文档出现新的修改，不覆盖')
        if current != source['sha256']:
            _restore(target,verified_file(home,request['original_copy']).read_bytes(),body['expected_modified_sha256'])
        verified_file(home,source)
        path = verified_file(home,request_ref).parent/'receipt.json'
        if path.exists():
            value = read_json(path)
            require(value['request_file'] == request_ref, '恢复回执属于其他请求')
        else:
            value={'schema_version':VERSION,'study_id':sid,'request_file':request_ref,'request_id':body['request_id'],
                'repair_id':'reportrepair_'+body['request_id'].split('_',1)[1],'run_id':body['expected_run_id'],
                'original_file':source,'annotation_file':request['annotation_file'],'annotation_evidence':request['annotation_evidence'],
                'human_review_written':False,'scientific_results_changed':False,'created_at':now()}
            write_json(path,value)
        ref=file_record(home,path,'report_archive_repair_receipt');m.setdefault(RECEIPTS,[]).append(ref)
        require(all(m[k] == v for k,v in before.items()), '恢复不能改科研运行或复核')
        # 回执与保全资料先完整核验，异常回执不能进入研究索引。
        read_receipt(w,m,ref);w.save(m)
        return dict(value,file=ref,created=True)
