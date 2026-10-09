from urllib.parse import urlencode # 只使用明确的研究参数。
from contracts import require # 下载与审定共用门控。
from storage import read_json, verified_file # 所有网页资料验证指纹。
from pathway_review import load_selection, selection_token, is_current, validate_candidate, REQUEST # 沿用唯一通路选择索引。

LABELS = {'approved':'已认可','awaiting_user_review':'待你审核','pending':'暂存待定','rejected':'已退回修改'} # 中文状态不等于科研结论通过。

def report_contains(workflow, manifest, index): # 核对当前报告实际绑定的事实包。
    rid = manifest['current'].get('A07') # 当前报告版本。
    if not rid or not workflow.active(manifest, rid): return False # 失效报告不显示已纳入。
    run = workflow.run(manifest, rid) # 报告输入指纹可定位选择。
    return run['inputs'].get('selected_pathway_metadata') == index['metadata'] # 同名通路但解释不同也需新报告。

def card(workflow, manifest, token, module='A05'): # A05及A07重点区显示简短入口。
    from web import text # 共用HTML转义。
    index, data = load_selection(workflow, manifest) # 无选择时也提示规则。
    status = LABELS.get(index['review_status'], '待准备推荐') if index else '待准备推荐' # 无材料不显示已推荐。
    request_path = workflow.location(manifest['study_id'])/'governance'/REQUEST # 准备请求有独立状态。
    if not index and request_path.is_file(): # 没有候选时明确显示已登记。
        request = read_json(request_path) # 读取实际请求。
        verified_file(workflow.location(manifest['study_id']),request['record']) # 请求自身必须完整。
        if request['source_a05_run'] == manifest['current'].get('A05'): status = '已登记请求，待助手准备推荐' # 不误称已完成推荐。
    current = is_current(workflow, manifest, data) # 上游改变优先提示。
    if module == 'A07' and manifest['current'].get('A07'): # 报告生成与通路选择版本分开核对。
        run = workflow.run(manifest,manifest['current']['A07']) # 不修改旧报告或审核。
        selected = index['metadata'] if current and index['review_status'] == 'approved' else None # 未批准候选不纳入报告。
        if run['inputs'].get('selected_pathway_metadata') != selected: status = '当前专业报告需修订，通路选择或批准已改变' # 避免把旧批准当成新报告通过。
    if data and not current: status = '原推荐已失效，需重新准备与审核' # 不沿用旧批准。
    if data and current and index['review_status'] == 'approved': status += '；已纳入当前专业报告' if report_contains(workflow,manifest,index) else '；待纳入专业报告' # 审核和报告生成分开。
    name = data['display_name'] if data and current else '按本研究数据与文献重新选择' # 不套用历史通路。
    url = '/pathway-review?'+urlencode({'study':manifest['study_id']}) # 专属研究入口。
    return '<div class="notice"><strong>通路推荐与审核（可选补充）</strong><p>'+text(status)+' · '+text(name)+'</p><a href="'+text(url)+'">查看通路图、解释与审核入口</a><p>只需审核选择依据、图中基因及解释边界。认可后加入专业报告；不阻断PPI或分子对接，也不代替A07结论复核。</p></div>' # 置于折叠区之外便于找到。

def review_page(workflow, sid, token): # 独立查看图与解释，原模块卡片不变。
    from web import page, text, hidden, table # 复用网页字体、表格和安全转义。
    manifest = workflow.load(sid) # 只读真实研究。
    index, data = load_selection(workflow, manifest) # 获取明确的选择版本。
    home = workflow.location(sid) # 限定所有附件。
    request_path = home/'governance'/REQUEST # 推荐请求不改变科学批准。
    request = read_json(request_path) if request_path.is_file() else None # 没请求不伪造历史。
    if request: verified_file(home, request['record']) # 请求归档也核验完整性。
    rid = manifest['current'].get('A05') # 当前A05科学版本。
    available = bool(rid and workflow.active(manifest,rid) and workflow.result(manifest,rid)) # 未完成富集不能请求推荐。
    body = '<p><a href="/study?study='+text(sid)+'">返回研究页面</a></p><p class="notice">先依据当前富集结果和疾病文献推荐，再查看图与解释，经你认可后纳入专业报告。推荐需要助手准备并登记资料，不会自动套用其他病例的通路。</p>' # 如实解释自动化边界。
    if manifest['current'].get('A00'): # 专页也显示当前研究身份与用途。
        intake = workflow.result(manifest,manifest['current']['A00'])['summary'] # 名称来自实际登记，不从目录猜测。
        purpose = '流程测试，非正式研究结论' if intake.get('analysis_purpose') == 'workflow_test' else '研究资料，结论仍需科学复核' # 不把MeSH核验等同正式机制验证。
        body += '<p><strong>研究：'+text(intake.get('formula'))+' — '+text(intake.get('disease'))+'；'+text(purpose)+'</strong></p>' # 单页阅读时不丢失用途边界。
    if not available: body += '<p><strong>需先完成当前A05富集结果。</strong></p>' # 明确前置条件。
    current = is_current(workflow, manifest, data) # 只允许当前版本审核。
    if data and not current: body += '<p class="notice"><strong>原推荐已失效，需重新准备与审核。</strong>旧通路及批准保留追溯，不能用于当前研究版本。</p>' # 不偷偷恢复旧批准。
    if data and current: # 当前候选与批准材料完整展示。
        validate_candidate(workflow,manifest,data) # 图和解释必须通过事实检查。
        body += '<h2>'+text(data['display_name'])+' · '+text(LABELS.get(index['review_status'],index['review_status']))+'</h2>' # 状态醒目。
        target = data.get('target_symbol') # 历史事实包没有独立靶点字段。
        body += '<p>相关靶点：'+text(target or '见下方已认可的选择说明')+'；命中基因数：'+text(data['count'])+'；BH调整后P值：'+text(format(float(data['adjusted_p']),'.3g'))+'</p>' # 不从文本猜字段。
        body += '<p><strong>选择依据：</strong>'+text(data.get('selection_reason') or '请阅读下方已认可的通路选择说明。')+'</p>' # 新候选需明确推荐原因。
        body += '<img alt="当前研究通路基因定位图" style="display:block;width:100%;height:auto;border:1px solid #d7e3e9" src="/pathway-file?'+text(urlencode({'study':sid,'selection':selection_token(index),'kind':'figure'}))+'"><p>'+text(data['caption'])+'</p>' # 保持原图比例，不拉伸。
        body += '<p><a target="_blank" rel="noopener" href="/pathway-file?'+text(urlencode({'study':sid,'selection':selection_token(index)}))+'">查看原尺寸通路图</a></p>' # 复杂通路可放大查看基因和箭头。
        body += '<h3>客观解释与限制</h3>'+''.join('<p>'+text(line)+'</p>' for line in data['paragraphs']) # 每段完整可读。
        if data.get('comparison_note'): body += '<p><strong>其他候选比较：</strong>'+text(data['comparison_note'])+'</p>' # 不对所有病例套用IL17或TNF。
        body += '<details><summary>实际命中基因与文献依据</summary><p>'+text('、'.join(data.get('symbols',[])))+'</p>'+table(data['references'])+'</details>' # 明细保留但不占主要审核区。
        if data.get('assistant_qa'): body += '<p>助手图件检查：'+text(data['assistant_qa'].get('note'))+'</p>' # 技术检查不能冒充用户审核。
        if data.get('review'): body += '<p>最近通路复核：'+text(data['review']['reviewer'])+' · '+text(data['review']['note'])+' · '+text(data['review']['created_at'])+'</p>' # 原文件继续完整保存。
        if not manifest.get('trashed'): # 回收站禁止变更。
            fields = hidden('token',token)+hidden('study',sid)+hidden('expected_a05',rid)+hidden('expected_selection',selection_token(index)) # 表单防旧版本提交。
            if index['review_status'] == 'approved': body += '<details><summary>修改已认可的通路复核决定（当前无需重复审核）</summary>' # 已认可的内容不反复占用人工审核。
            body += '<h3>你只需核对三项</h3><ol><li>通路及相关靶点的选择依据是否可接受。</li><li>图中标红仅表示命中，说明是否清楚。</li><li>解释是否客观，未夸大成疗效或已验证机制。</li></ol><form method="post" action="/pathway-review">'+fields+'<label>复核人<input name="reviewer" required maxlength="200"></label><label>意见或修改要求<textarea name="note" required maxlength="4000"></textarea></label><label>决定<select name="decision"><option value="pending">暂存待定</option><option value="approved">认可，允许加入专业报告</option><option value="rejected">退回修改</option></select></label><label><input style="width:auto;margin-right:8px" type="checkbox" name="confirmed" value="yes">我已核对图、选择依据与解释边界</label><button>保存通路复核决定</button></form>' # 不默认选通过或确认。
            if index['review_status'] == 'approved': body += '</details>' # 与已认可复核折叠区配对。
            if index['review_status'] == 'approved': # 报告生成单独操作，避免误认为审批即发布。
                included = report_contains(workflow,manifest,index) # 检查同源版本是否已生成。
                body += '<p><strong>'+('已纳入当前专业详细报告。' if included else '通路已认可，尚未纳入当前专业报告。')+'</strong>完整A07结论仍需单独复核。</p>' # 本次既有批准不要求再审核。
                if not included: # 已纳入不重复生成按钮。
                    body += '<form method="post" action="/pathway-report">'+fields+hidden('expected_a07',manifest['current'].get('A07',''))+'<button>将已认可通路加入专业报告，生成新修订</button></form><p>需A00至A06必需模块均已通过。临床简略报告保持原样；旧报告继续留存。</p>' # 明确前置条件及版本行为。
    if available and not manifest.get('trashed'): # 请求本身不批准科学结果。
        current_request = bool(request and request['source_a05_run'] == rid and request['source_a05_result_sha256'] == manifest['runs'][rid]['result_file']['sha256']) # 旧请求不作为当前进度。
        if current_request: body += '<p>最近准备请求：'+text(request['created_at'])+'；意见：'+text(request['note'])+'</p>' # 不把已准备候选继续说成未完成。
        body += '<details'+(' open' if not data or not current else '')+'><summary>请求准备或调整通路推荐</summary><form method="post" action="/pathway-request">'+hidden('token',token)+hidden('study',sid)+hidden('expected_a05',rid)+hidden('expected_request',selection_token(request))+'<label>希望关注的方向或调整意见（可不填）<textarea name="note" maxlength="4000"></textarea></label><button>登记通路推荐准备请求</button></form><p>登记后由助手依据本研究数据与文献准备图件和解释；不会后台自动完成文献评价。原已认可内容不会因仅提交请求被替换。</p></details>' # 如实区分请求与计算任务。
    return page('通路推荐与人工审核', body) # 使用原网页统一样式。

def figure_file(workflow, sid, expected_selection): # 图下载仅限本研究当前选择。
    manifest = workflow.load(sid) # 校验研究身份。
    index, data = load_selection(workflow,manifest) # 不接收任意磁盘路径。
    require(index and selection_token(index) == expected_selection, '图件版本已改变，请刷新') # 旧图不伪装成新候选。
    validate_candidate(workflow,manifest,data) # 包括上游有效性。
    return verified_file(workflow.location(sid),data['native_figure']) # 图保持原始字节。
