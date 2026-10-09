from copy import deepcopy # 批准时另存事实，不修改原候选。
from contracts import require, fingerprint # 校验科学身份与页面版本。
from storage import read_json, verified_file, write_json, write_lock, new_id, now, file_record # 沿用研究归档与写锁。

INDEX = 'A05_pathway_index.json' # 与既有通路报告接口共用唯一指针。
REQUEST = 'A05_pathway_request.json' # 推荐准备请求与通路批准分开记录。

def load_selection(workflow, manifest): # 只读当前研究的候选或历史选择。
    home = workflow.location(manifest['study_id']) # 限定研究边界。
    path = home/'governance'/INDEX # 不按文件时间猜最新版本。
    if not path.is_file(): return None, None # 尚未推荐属于正常状态。
    index = read_json(path) # 当前选择索引可原子更新。
    require(index.get('schema_version') == 'A05.pathway.index.1' and index.get('review_status') in ('approved','awaiting_user_review','pending','rejected'), '通路索引版本或审核状态不正确') # 不解释未知版本。
    data = read_json(verified_file(home, index['metadata'])) # 不可变事实包必须匹配指纹。
    require(data['study_id'] == manifest['study_id'] and data['source_a05_run'] == index['source_a05_run'], '通路选择身份不一致') # 拒绝跨研究使用。
    require(data['review_status'] == index['review_status'], '通路审核记录与索引不一致') # 索引不能伪造批准。
    return index, data # 是否失效由当前科学版本另行判断。

def selection_token(index): # 表单携带整个选择索引的指纹。
    return fingerprint(index) if index else '' # 新候选页面也有明确的空版本。

def is_current(workflow, manifest, data): # 同时检查A05指针及上游是否有效。
    rid = manifest['current'].get('A05') # 唯一当前富集运行。
    return bool(data and data['source_a05_run'] == rid and workflow.active(manifest, rid) and data['source_a05_result_sha256'] == manifest['runs'][rid]['result_file']['sha256']) # 改变科学输入后不能沿用批准。

def validate_candidate(workflow, manifest, data): # 未批准候选也需要严格核验事实。
    require(is_current(workflow, manifest, data), '富集版本已改变，请重新准备通路推荐') # 先检查实际科学版本。
    require(data['study_id'] == manifest['study_id'], '通路候选属于其他研究') # 防止跨病例复用。
    result = workflow.result(manifest, data['source_a05_run']) # 使用保存的实际富集结果。
    matches = [row for row in result['tables']['kegg_significant'] if row['ID'] == data['pathway_id']] # 必须来自显著结果，不能由名称编造。
    require(len(matches) == 1, '推荐通路不在当前KEGG显著结果中') # 无适合候选应报告不足。
    row = matches[0] # 只接受唯一真实条目。
    require(data['count'] == row['Count'] and float(data['adjusted_p']) == float(row['p.adjust']) and set(data['entrez_ids']) == set(row['geneID'].split('/')), '通路命中或统计与当前A05不一致') # 不手抄更新数字。
    require(set(data['symbols']) == set(row['gene_symbols'].split('/')), '通路基因符号与A05实际命中不一致') # 推荐靶点不能靠自行改符号混入。
    require(data.get('display_name') and data.get('caption') and data.get('paragraphs') and data.get('references'), '缺少通路名称、图注、解释或参考文献') # 未完整准备不能交用户审核。
    home = workflow.location(manifest['study_id']) # 文件都在当前研究包。
    require(any(all(record.get(key) == data['native_figure'].get(key) for key in ('path','sha256','bytes')) for record in data['files']), '通路图未纳入来源指纹清单') # 同一图的用途标签可以不同，文件身份必须一致。
    for record in data['files']: verified_file(home, record) # 校验图源、映射、文献和说明附件。
    verified_file(home, data['native_figure']) # 图本身再次核对。
    if data.get('target_symbol'): require(data['target_symbol'] in data.get('symbols', []), '推荐靶点不在该通路实际命中基因中') # 不任意指定通路成员。

def request_recommendation(workflow, sid, expected_a05, expected_request, note): # 网页记录准备请求，不伪装成自动文献评审。
    with write_lock(workflow.root): # 与科学更新使用同一个写锁。
        manifest = workflow.load(sid) # 锁内重新读取研究。
        rid = manifest['current'].get('A05') # 绑定实际富集。
        require(not manifest.get('trashed') and rid == expected_a05 and workflow.active(manifest, rid), '研究或A05版本已改变，请刷新') # 只读和旧页不写入。
        home = workflow.location(sid) # 记录属于当前研究。
        pointer = home/'governance'/REQUEST # 请求索引与批准索引分离。
        previous = read_json(pointer) if pointer.is_file() else None # 查明确的前次请求。
        require(selection_token(previous) == expected_request, '推荐准备请求已更新，请刷新') # 拒绝重复或过期提交。
        data = {'schema_version':'A05.pathway.request.1','request_id':new_id('pathway_request'),'study_id':sid,'source_a05_run':rid,'source_a05_result_sha256':manifest['runs'][rid]['result_file']['sha256'],'status':'awaiting_preparation','note':str(note).strip()[:4000],'created_at':now(),'previous':previous.get('record') if previous else None} # 留存请求而不自行决定科学结论。
        path = home/'governance'/(data['request_id']+'.json') # 请求原文不可覆盖。
        write_json(path, data) # 先完整留存请求。
        record = file_record(home, path, 'pathway_recommendation_request') # 可追溯请求来源。
        write_json(pointer, dict(data, record=record), replace=True) # 一次发布请求状态。
    return data # 页面提示等待准备。

def register_candidate(workflow, sid, data, expected_selection=''): # 助手完成图件和文献评审后登记网页候选。
    with write_lock(workflow.root): # 不与新A05或审核交错。
        manifest = workflow.load(sid) # 从实际索引取得科学身份。
        require(not manifest.get('trashed'), '回收站研究不能登记推荐') # 保持管理只读边界。
        index, previous = load_selection(workflow, manifest) # 当前选择仅用于冲突核对。
        require(selection_token(index) == expected_selection, '通路选择已更新，请刷新后登记') # 不能覆盖另一次选择。
        candidate = deepcopy(data) # 原准备材料保持原样。
        candidate['review_status'] = 'awaiting_user_review' # 助手不得代用户批准。
        candidate['schema_version'] = 'A05.selected_pathway.1' # 与通路报告契约一致。
        require(candidate.get('assistant_qa', {}).get('checked') is True and candidate['assistant_qa'].get('note'), '必须先实际检查图件并记录检查意见') # 技术检查先于用户审核。
        require(candidate.get('target_symbol') and candidate.get('selection_reason') and candidate.get('comparison_note'), '请补齐相关靶点、推荐理由与候选比较') # 新研究不能套用案例解释。
        validate_candidate(workflow, manifest, candidate) # 全量核对统计、身份与附件。
        home = workflow.location(sid) # 保存到既有治理目录。
        path = home/'governance'/(new_id('pathway_candidate')+'.json') # 每次推荐独立版本。
        candidate['created_at'] = now() # 保存准备完成时间。
        write_json(path, candidate) # 不覆盖旧候选或批准。
        record = file_record(home, path, 'selected_pathway_metadata') # 唯一事实包指纹。
        write_json(home/'governance'/INDEX, {'schema_version':'A05.pathway.index.1','source_a05_run':candidate['source_a05_run'],'review_status':candidate['review_status'],'metadata':record,'previous':index}, replace=True) # 仅当前指针改变。
    return record # 后续网页加载明确候选。

def review_selection(workflow, sid, expected_a05, expected_selection, decision, reviewer, note, confirmed): # 人工审定只影响可选通路，不代替A05或A07。
    require(decision in ('approved','pending','rejected'), '通路复核决定不合法') # 不接受自定义审核状态。
    require(str(reviewer).strip() and str(note).strip(), '请填写复核人和意见') # 每次决定留存责任及理由。
    require(decision != 'approved' or confirmed == 'yes', '请确认已核对通路图、依据与解释边界') # 不预先勾选确认。
    with write_lock(workflow.root): # 审批与科学更新原子串行。
        manifest = workflow.load(sid) # 锁内核验当前研究。
        require(not manifest.get('trashed') and manifest['current'].get('A05') == expected_a05, '研究或A05版本已改变，请刷新') # 旧页面不得批准新数据。
        index, data = load_selection(workflow, manifest) # 原候选或旧审核仍保留。
        require(index and selection_token(index) == expected_selection, '通路推荐或审核状态已改变，请刷新') # 防止重复提交。
        validate_candidate(workflow, manifest, data) # 审核时重新核验实际图和基因。
        home = workflow.location(sid) # 所有审核归属本研究。
        review = {'schema_version':'A05.pathway.review.1','review_id':new_id('pathway_review'),'study_id':sid,'source_a05_run':expected_a05,'candidate':index['metadata'],'decision':decision,'reviewer':str(reviewer).strip(),'note':str(note).strip(),'created_at':now(),'scope':'仅通路图及解释，不代替完整A07复核'} # 保存具体批准范围。
        review_path = home/'reviews'/(review['review_id']+'.json') # 不修改原审核文件。
        write_json(review_path, review) # 先写不可变审核记录。
        approved = deepcopy(data) # 另存审核后的事实包。
        approved['review_status'] = decision # 状态与指针一致。
        approved['files'].append(file_record(home, review_path, 'pathway_user_approval')) # 报告来源链含真实人工决定。
        approved['review'] = review # 网页显示中文审核历史摘要。
        path = home/'governance'/(review['review_id']+'_selection.json') # 候选和审核后事实不覆盖。
        write_json(path, approved) # 完整保存审核后版本。
        updated = {'schema_version':'A05.pathway.index.1','source_a05_run':expected_a05,'review_status':decision,'metadata':file_record(home,path,'selected_pathway_metadata'),'previous':index} # 保留历史选择链。
        write_json(home/'governance'/INDEX, updated, replace=True) # 全部文件成功后才发布批准。
    return review # A07仍需单独生成和复核。
