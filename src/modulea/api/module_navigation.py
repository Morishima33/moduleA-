"""全模块操作导航：只读已有视图事实，不执行计算、复核或修改研究。"""


def context(view, result=None):
    """按模块及实际可见入口给出操作顺序；建议位置不代表步骤已经完成。"""
    mid = view["module"]["module_id"]
    if view["historical"] or mid == "A02":
        return None
    steps = []

    def add(key, label, target, detail, module_id=None, href=None):
        """登记页面区域或同研究跳转，不创建任何写操作。"""
        step = {"key": key, "label_zh": label, "target": target, "detail_zh": detail}
        if module_id:
            step["module_id"] = module_id
        if href:
            step["href"] = href
        steps.append(step)

    def link(key, label, module_id, detail):
        """登记同研究的下一阅读入口，进入页面不会自动运行模块。"""
        add(key, label, "", detail, module_id=module_id)

    def review():
        """保留独立人工复核入口，权限完全沿用原复核栏。"""
        add("review", "整体复核", "module-review-panel", "核对结果后填写复核决定、复核人和依据；能否通过以复核栏为准。")

    approved = bool(view["review"]["already_approved"])
    current = "review"
    prep = view.get("trial_preparation")
    automatic = view.get("automatic_docking")
    if automatic and mid in ("A06_PREP", "A06"):
        latest = automatic.get("latest")
        if mid == "A06_PREP":
            link("scope", "核对完整扩展名单", "A03_SELECT", "先核对主候选及扩展筛查名单；名单复核后才连接全部对象。")
            add("connect", "连接本研究资料", "module-automatic-docking", "连接官方原件，不计算评分。")
            add("authorize", "核定范围并一次确认", "module-automatic-docking", "明确共晶参考或保留探索，执行后结果独立复核。")
            link("result", "查看运行与结果", "A06", "后台进度、评分和异常统一在A06查看。")
            current = "result" if latest and latest.get("state") != "stale" else "authorize" if automatic.get("connection") else "connect"
            if automatic.get('active_task_kind') in ('a06_auto_connect', 'a06_auto_start') and (not latest or latest.get('state') == 'stale'):
                current = 'connect'
            if automatic.get('scope') and not automatic['scope']['ready'] and not (latest and latest.get('state') == 'running'):
                current = 'scope'
        else:
            stale = bool(latest and latest.get("state") == "stale")
            if stale:
                label = "确认本轮计算" if automatic.get("connection") else "准备本轮计算"
                detail = "资料连接已完成，尚未启动评分。请前往A06_PREP核对连接异常，填写执行确认并开始计算；完成后才会生成本轮热图。" if automatic.get("connection") else "旧批次已失效，请前往A06_PREP查看本轮资料连接状态并完成执行确认。"
                if automatic.get('active_task_kind') == 'a06_auto_start':
                    label = "查看本轮连续任务进度"
                    detail = "已确认连续执行，后台正在连接或补齐资料；完成后自动计算，无需再次确认。"
                link("new_execution", label, "A06_PREP", detail)
            add("scores", "查看热图与完整矩阵", "module-automatic-results", "图表、矩阵与下载使用同批原值。")
            add("evidence", "核对异常与计算依据", "module-automatic-results", "证据按需打开，无逐条阅读门槛。")
            if view.get("docking_artifacts"):
                add("figures", "按需出图或上传图片", "module-docking-artifacts", "选择成分和受体后才生成指定组合。")
            review()
            link("report", "查看报告进度", "A07", "A06独立通过后按依赖生成双报告，仍须A07复核。")
            current = "new_execution" if stale else "report" if approved else "review" if latest and latest.get("state") == "completed" else "scores"
    elif prep:
        add("source", "核对本批准备来源", "trial-preparation-summary", "沿用已保存的同批核查，查看原核查人与关联版本，无需重复批准。")
        if prep["active"]:
            add("receptors", "查看受体与位点证据", "trial-preparation-receptors", "核对采用结构、搜索方式、修补说明及适用范围。")
            add("compounds", "查看成分准备资料", "trial-preparation-compounds", "查看成分身份、来源三维和实际准备文件。")
        add("result", "查看关联A06结果", "", "按原关联地址查看同批结果；扩展准备不代表严格质控通过。", href=prep["result_url"])
        current = "result" if prep["active"] else "source"
    elif mid == "A00":
        add("intake", "核对研究登记", "module-details", "核对方剂、药味、疾病名称、研究用途和登记原文。")
        add("scope", "核对疾病身份与范围", "module-results", "核对MeSH编号、首选词及本病范围；详细登记原文可在下方结果明细查看。")
        review()
        link("sources", "进入A01资料汇集", "A01", "A00通过后按本研究分别准备方剂资料与A02疾病资料。")
        current = "sources" if approved else "intake"
    elif mid == "A01":
        add("sources", "检查方剂来源资料", "module-source-inputs" if view.get("source_uploads") else "module-details", "核对本项目已有来源；需要补充时上传对应三库资料，再明确点击整理。有效归档无需重复上传。")
        add("relations", "核对成分与靶点关系", "module-results", "查看成分筛选、药味归属、靶点关系及数量变化，完整原值在结果明细。")
        link("identity", "前往A02联合身份核查", "A02", "在A02先保存疾病范围，再核查两侧基因身份并确认生成标准化结果。")
        review()
        link("intersection", "查看A03交集", "A03", "两侧标准化结果均通过复核后才能用于交集；进入页面不会代替复核。")
        normalized = "标准化基因数" in ((result or {}).get("summary") or {})
        if normalized:
            current = "intersection" if approved else "review"
        else:
            current = "identity" if view["run"] else "sources"
    elif mid == "A03":
        if view["state"]["code"] == "stale":
            link("updated_inputs", "先复核新版输入", "A02", "A03上游已更新，请先核对当前A01/A02并完成新版本复核；旧交集不代表当前疾病集合。")
        add("sets", "核对两侧靶点与交集", "module-results", "核对方剂靶点T、疾病靶点D和交集数量及维恩图。")
        add("ranking", "查看成分关联排名", "module-details", "查看交集基因及成分关系明细；对接成分名单在独立选择页确认。")
        review()
        link("ppi", "查看A04网络分析", "A04", "A03通过后，A04与A05可并行推进，各自独立复核。")
        link("enrichment", "查看A05功能富集", "A05", "GO与KEGG使用同一已确认交集，不必等待A04完成。")
        current = "updated_inputs" if view["state"]["code"] == "stale" else "ppi" if approved else "review" if view["review"]["can_review"] else "sets"
    elif mid == "A03_SELECT":
        target = "module-compound-selection" if view.get("compound_selection") else "module-details"
        add("selection", "核对成分身份与药味", target, "查看拟纳入名单、成分身份、药味来源和补充依据。")
        add("save", "确认名单并保存", "compound-selection-confirmation" if view.get("compound_selection") else target, "明确选择实际纳入成分并填写依据，保存新版名单；保存后仍待独立复核。")
        review()
        link("preparation", "进入A06对接准备", "A06_PREP", "使用已复核的成分名单与A04候选准备结构及位点。")
        active = bool((view.get("compound_selection") or {}).get("previous_active"))
        current = "preparation" if approved and active else "review" if active else "selection"
        scope = (view.get('compound_selection') or {}).get('extended_scope')
        if scope and not scope['ready'] and approved:
            current = 'selection'
    elif mid == "A04":
        add("run", "检查输入并计算PPI", "module-ppi-run" if view.get("ppi_run") else "module-status", "使用已通过的A03交集；需要计算时明确点击A04计算按钮，后台完成后再复核。")
        add("identity", "核查网络身份例外", "module-focus", "先处理本轮列出的身份问题；没有例外时继续查看网络结果。")
        add("network", "查看网络与两轮排名", "module-results", "分别核对Degree与BC＋CC分支、网络图及完整候选排名。")
        review()
        if view.get("docking_candidates"):
            add("candidates", "核对对接候选分组", "a06-candidate-groups", "复核A04后，查看或明确生成A/B候选分组；不自动运行对接。")
        link("compounds", "核查对接成分名单", "A03_SELECT", "候选受体与对接成分分别核对，随后进入A06准备。")
        if approved:
            candidates = view.get("docking_candidates")
            current = "candidates" if candidates and not candidates.get("data") else "compounds"
        elif view["state"]["handoff_blocked"]:
            current = "identity"
        else:
            current = "review" if view["review"]["can_review"] else "run"
    elif mid == "A05":
        display = view.get("enrichment_display")
        if display:
            add("scope", "确认KEGG展示范围", "module-enrichment-confirmation", "展开顶部核查区，核对完整显著通路和排除清单，明确保存范围。")
        add("charts", "查看GO与KEGG图表", "module-results", "核对GO三类与KEGG两种排名；未保存的排除选择不会成为正式图表。")
        if display:
            add("layout", "确认图表版式", "module-enrichment-confirmation", "范围应用后核对中文名称、图表和版式，再在顶部核查区明确确认。")
        maps = view.get("ranked_pathway_maps")
        display_tables = view.get("special", {}).get("enrichment_display_tables") or {}
        if maps and display_tables:
            add("maps", "核对首位通路命中图", "a05-ranked-pathway-maps", "查看两个排名首位通路命中图；缺图时使用图表区的按需生成按钮。无显著通路不补图。")
        review()
        link("report", "查看A07报告进度", "A07", "A05和对接相关结果分别完成复核后，报告仍需独立核对。")
        # items只包含已归档图片；没有图片不能误当作无需补图，是否有排名直接读现有展示表。
        ranked_entries = bool(display_tables.get("kegg_p_top10") or display_tables.get("kegg_count_top10"))
        missing_maps = bool(maps and ranked_entries and not maps["items"])
        if display and not display["exclusions_confirmed"]:
            current = "scope"
        elif display and not display["layout_confirmed"]:
            current = "layout"
        elif missing_maps and any(s["key"] == "maps" for s in steps):
            current = "maps"
        else:
            current = "report" if approved else "review" if view["review"]["can_review"] else "charts"
    elif mid == "A06_PREP":
        link("selection", "核对已确认成分名单", "A03_SELECT", "准备工作采用当前研究已复核的成分，不沿用其他研究的选择或例外。")
        if view.get("docking_candidates"):
            add("candidates", "核对A/B候选受体", "a06-candidate-groups", "核对本批受体名单与来源；A/B候选级别和实际结构质控分别记录。")
        coverage = view.get("docking_coverage")
        plan = view.get("docking_preparation")
        if coverage or plan:
            add("prepare", "核查结构、位点与配体", "module-preparation", "进入本页集中核查，核对结构来源、位点及成分三维资料，未完成可保存草案。")
            add("quality", "确认准备范围与质控", "module-preparation", "核对严格质控、探索范围和NA原因，再明确确认本批可用范围；保存方案不代表质控通过。")
        else:
            add("prepare", "检查准备状态与资料", "module-details", "查看当前准备记录和待补条件，先满足上游与结构准备要求。")
        if (view.get("trial_handoff") or {}).get("active"):
            link("result", "前往本批A06结果复核", "A06", "本批已接入A06正式复核，原严格准备保留，无需在此重复确认。")
            current = "result"
        else:
            review()
            link("result", "查看A06对接结果", "A06", "准备阶段与评分阶段分别留痕，最终评分结果仍需人工复核。")
            if approved:
                current = "result"
            elif coverage and not coverage["confirmed"]:
                current = "quality"
            else:
                current = "prepare" if view["state"]["handoff_blocked"] or not view["review"]["can_review"] else "review"
    elif mid == "A06":
        link("preparation", "查看本批准备依据", "A06_PREP", "先核对同批成分、受体、位点与适用范围，严格质控和扩展用途分别查看。")
        trial = view.get("docking_trial")
        score_target = "a06-trial" if trial else "module-docking-matrix" if view.get("docking_review") else "module-results"
        add("scores", "核对评分矩阵与NA", score_target, "查看Top-1原始评分、重点热图和完整结合能表；失败保留NA，运行中查看后台任务。")
        if trial:
            add("trial", "核对试算用途与记录", "a06-trial", "仅扩展试算显示此步骤；集中核查保存与正式A06复核为两个独立关口。")
        review()
        if view.get("docking_artifacts"):
            add("figures", "按需出图与上传图片", "module-docking-artifacts", "选择成分和受体后才明确生成所选包，或上传对应图片；无需预先制作全部出图包。")
        link("report", "查看A07报告", "A07", "报告沿用本批已确认结果，新附件不会自动改写已发布报告。")
        if approved:
            current = "report"
        elif not view["review"]["can_review"] or view["state"]["handoff_blocked"]:
            current = "scores"
        else:
            current = "trial" if trial and not (trial.get("review") or {}).get("confirmed") else "review"
    elif mid == "A07":
        add("sources", "核对报告输入与提示", "module-focus", "先核对本轮输入版本、报告待办和需要处理的问题。")
        add("conclusions", "核对结论、数字与图表", "module-results", "核对共同结论、研究线索和本批图表，专业版与简略版使用同源结果。")
        add("downloads", "下载并核对两份报告", "module-report-downloads", "下载专业详细版和临床简略版，检查正文及附录；尚未生成时先查看当前状态。")
        add("review", "整体复核并发布", "module-review-panel", "由你独立填写本版复核决定，通过后发布，不代替科学结论验证。")
        add("published", "查看已发布报告", "module-report-downloads", "已发布版本无需重复提交，可下载核对；历史报告及原批准保持。")
        current = "published" if approved else "sources" if view["state"]["handoff_blocked"] or not view["review"]["can_review"] else "downloads"
    else:
        return None

    index = next(i for i, step in enumerate(steps, 1) if step["key"] == current)
    note = steps[index - 1]["detail_zh"] if current == "new_execution" else view["state"].get("reason_zh") or steps[index - 1]["detail_zh"]
    # 状态与建议分开展示，失败、失效、忙碌及只读提示不能被“下一步”掩盖。
    if view["state"]["code"] in ("idle", "ready", "running", "incomplete", "failed", "stale", "unavailable"):
        note = f"当前{view['state']['label_zh']}。{note}"
    return {"current_step": index, "note_zh": note, "steps": steps}
