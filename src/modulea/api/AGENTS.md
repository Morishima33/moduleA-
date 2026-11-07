# api/ — 本机 JSON 接口契约（前端与后端的唯一约定）

## 2026-11-02 系统A04最终名单只读展示

当前系统执行版A04的模块GET新增可选`system_receptor_selection`，旧服务无字段时隐藏。仅展示本研究、本网络、本批已归档的`A04_SELECTION`原顺序名单；包含`archive_state:pending|archived|source_changed`、目标/实际数量、筛选模式、边界并列说明和原始受体行。未归档时数量为null，不能冒充0项。历史、旧人工流程及其他网络不借用当前名单。

同批`A06_INPUT`已归档且其原受体行与该名单完全相同时，另显示固定成分数及组合数；尚未归档不推算固定范围。归档文件SHA、请求/输入/内容指纹、研究、批次和网络来源必须一致；展示只读取已登记原件与本次模块已核验来源，不重跑选择算法，不重新展开全部科学原件，也不提供执行或复核资格。实际执行仍经原完整规范校验。

该区只读，无新增HTTP写路由、名单保存、采用、复核或默认确认按钮。模块状态、`review`和旧人工表单行为保持；系统版继续从统一执行与续做入口推进。最终对接名单与全网两轮候选统计分别标清，结构/质控失败保留原对象及NA原因。

当前系统A04在视图组装时直接跳过最终不会展示的旧候选、身份补查和人工名单表单读取；不先执行完整读取再将结果丢弃。历史与普通人工版本仍走原读取路径；当前系统原结果核验、模块状态及人工复核门控保持。

## 2026-11-02 系统结果同批Excel与图表导出

补充排版版本`A06.system_exports.2`：新明确请求使用第二版，只调整Excel列宽、换行、行高和说明区布局，科学来源、原值、六件附件范围及接口七字段不变。第一版已归档实现与原件保持；旧请求号按原协议复用，不能重新生成或静默升级。info/下载/追溯兼容两版，current优先本批第二版，第一版仍列历史供读取；没有第二版时允许用户明确生成新版，不自动生成。

当前受体目录修订资格或评分使用独立归档协议 `A06.system_exports.3`，沿用第二版排版与原值规则。请求、成功检查点及失败记录分开保存。统一历史、下载及追溯可读取三版，接口字段保持原合同。

GET `/studies/{sid}/analysis-plan/system-exports`仅返回`A06.system_exports.1`当前资格、源模块/运行、输入指纹、已归档六件导出及历史；不生成、不联网、不执行Vina。只支持有效的系统评分1/2，或没有可评分组合的全NA系统准备/资格1/2。ready尚未评分、旧批、失效、明确人工暂停或回收站不得生成。全NA不画虚假色标、不填零，原完整固定名单与顺序保持。

POST同址严格七字段`{request_id:sysexportreq_<32hex>,expected_module:A06|A06_PREP,expected_run_id,expected_input_hash,author,note,confirmed:true}`，预检后排队重任务`plan_system_exports`。worker经公开Workflow复用已验收的动态导出排版，生成完整/重点PNG/SVG、完整CSV及Excel；真实科学版本保留，原始精度、NA/失败原因、A/B和≤−8的原标记保持，不改科学运行、评分、报告或reviews。完整成功检查点可在同请求重试时复用；未登记或损坏文件不得用重生成掩盖。源码/输入在生成前后重核，失败保留原件和诊断。

GET `/studies/{sid}/analysis-plan/system-exports/{export_id}/files/{index}`按本研究已登记回执及0—5文件索引下载，核对指纹；不接受裸路径。历史及回收站仅允许读取既有档案。info中每件文件提供`download_url`，完成后页面刷新展示下载；GET/重启不自动生成。当前系统A06页或全NA系统PREP页增加只读资格及明确生成按钮，来源未接通不显示空入口。新`system_exports`字段和能力标记为可选，旧服务隐藏，不在前端推算资格或评分。

## 2026-11-02 同批PPI精确身份清单与结果限制

本阶段仅新增后台公开Workflow范围登记、逐查询原件恢复与独立新网络发布，不新增HTTP写路由、网页上传或默认授权。`A04.plan_network.2`保留原`identity_issues`，另携带`identity_decisions/identity_adjustments/identity_temporarily_omitted/identity_unresolved/original_identity_scope`。摘要`身份待核验数`仍按真实未决统计，`本次PPI暂不采用数`与`未获准身份阻断数`分别展示；只有后者实际为0才解除handoff_blocked。未决暂不采用不是身份已解决，原A03与A05输入保持。

沿既有`focus`和`special.ppi_identity`字段展示本批限制、原身份、返回名和逐项原因，不新增状态码；明确获准暂不采用仅should_know，未获准未决继续must_handle并阻断A06_PREP。当前系统执行版A04隐藏不适用的旧ppi_run/identity_plan逐步表单，保留归档结果、真实证据、统一续做和独立复核；普通人工及历史页面保持。完整追溯含ppi_identity_scopes、ppi_identity_probe_requests/probes与ppi_identity_revision_requests/receipts/failures及原字节，成功空列表与失败分列。报告来源段保留本次PPI例外、数量、名单及原因；不能声称完整网络或正式研究结论。当前真实补查与新网络是否已执行须以研究归档为准，代码支持不等于已执行。

新协议的`special.ppi_identity`另给可选`scope_kind:explicit_bound_test_decision`及真实`handoff_blocked:boolean`。需要知悉区同样展开身份明细，复核区只在真实阻断时提示先处理身份；已获准暂不采用用信息提示保留限制，不伪造解决状态。没有identity_plan的当前系统版身份表只读，不展示旧补查按钮或操作说明；可下载本轮新网络、原名称请求、范围和补查回执。当前系统A04同时隐藏旧plan_selection_ui及docking_candidates表单，名单采用/固定仍由同批统一接续处理。复核资格继续仅由Workflow状态及review字段决定，前端不得凭scope_kind启用通过。

## 2026-11-01 已明确精确身份清单例外的结果展示

`ModuleA.identity_exception.1`本阶段仅通过后台公开Workflow登记，无新增HTTP写入口或网页上传表单。`A01.system_publication.2`与`A02.system_normalization.5`的已归档结果携带`identity_exception_protocol/identity_limitations_zh`及`tables.identity_exception_scope`，重点核对区显示“本批明确身份例外（仅流程测试）”。原未决身份状态仍保留，明确不采用不是身份已解决，也不是人工复核通过。A02第五版继续沿用special.historical_disease_source隐藏不适用旧表单；历史版本说明和旧获取记录保留。完整追溯追加`plan_decisions.identity_exceptions`及实际原文、共同映射、精确范围和实现文件，不接受路径下载或客户端通过结论。两份报告来源段同步身份与版本限制。

当前运行明确为`ModuleA.system_execution.1`时，A01/A02/A03/A04的已归档页面不再生成旧`plan_stages`人工阶段执行表单和旧`operation_guide`，需要知悉区指向“统一执行与续做”。原结果、状态、人工复核资格和后端写入门控保持；普通人工版本及历史页面沿原行为，不用科学版本号推断用户已批准。

## 2026-11-01 单研究历史疾病版本例外

GET `/studies/{sid}/analysis-plan/historical-disease-sources`只读返回`A02.historical_sources.1`资格、原五库文件元信息、精确expected_a00/expected_plan_id/expected_input_hash/expected_source_hashes及历史明确例外。仅新版workflow_test首次疾病候选支持；GeneCards和OMIM须均为当前登记已上传的未知发布版本原件，其他三库须有同登记成功且满足原版本说明或响应快照规则的系统原文。不联网、不自动决定。正式研究、缺库、版本或文件改变、人工暂停和回收站拒绝。

POST `.../publish`严格九字段`{request_id:historicaldiseaseq_<32hex>,expected_a00,expected_plan_id,expected_input_hash,expected_source_hashes:{GeneCards,OMIM},author,note,user_decision,confirmed:true}`，202排队plan_historical_disease_sources。必须记录真实用户明确决定，不能改版本、注入路径/URL/采用或通过标记。后台公开Workflow核对原登记/方案/两份文件和原成功公共来源后保存不可变单研究例外，生产规范完整复算`A02.historical_collection.1`；只发布待标准化候选，不写人工reviews，不启动下游。原版本仍拒绝未知，导出日期与指纹不冒充发布版本。开始的新批次只有同一已批准方案和原件可采用`A02.system_source_reuse.3`与`A02.system_normalization.4`；旧批和旧规范不变，后来未采用草稿不替换原批参数。身份、范围、质控及最终复核不豁免。

候选、标准化和报告携带`database_versions_complete:false/source_version_exception:true/source_limitations_zh`，网页醒目标注“仅流程测试，数据库发布版本未知”；双Word来源段保留同一说明。完整追溯包含`plan_decisions.historical_disease_sources`。session.capabilities.historical_disease_sources=true才显示独立面板，默认不勾、不自动执行；旧服务隐藏新入口。

A02上述两种新协议的special.historical_disease_source={message_zh}标识本版来源限制和统一接续入口；不显示不适用的旧分步操作指南、上传、范围保存或身份预览表单。状态码和复核门控保持，等待说明明确到统一流程核对前置条件，不引导寻找已隐藏的旧表单。其他三库沿原有版本说明/响应快照规则；尤其OTP原“接口未提供数据库发布版本；以响应快照固定”据实保留，不声称已有可核实数据库发布号。

疾病获取GET在当前A02为上述历史协议时追加historical_candidate:{run_id,candidate_records,source_limitations_zh,message_zh}。当前候选与先前获取失败分别展示：仅隐藏不适用的再次获取/原协议发布表单，原获取记录以明确“历史获取记录”折叠保留，不把旧失败改成成功或误报当前没有候选。未携带标记的原接口行为和页面保持。

## 2026-11-01 官方精确编号补查归档

GET `/studies/{sid}/analysis-plan/component-identity-probes`返回`A01.identity_probe.1`的supported/enabled/blockers、expected_a01/expected_input_hash、由本版原关系核对的HERB精确编号targets及不可变records。GET只读原文，不联网或重试。POST `.../execute`严格六字段`{request_id:componentprobereq_<32hex>,expected_a01,expected_input_hash,author,note,confirmed:true}`，202提交plan_component_identity_probe；拒绝URL、路径、客户端编号及采用/通过标记。后台经公开Workflow重新核对原A01、三库绑定、方案、原关系行和人工意见，固定官方HERB/HGNC/NCBI端点获取精确编号凭据。来源稳定编号一致、非人类、缺编号、冲突和请求失败分列；adopted始终false，不改变科研结果、current/runs/reviews或原待核。完整请求幂等；部分失败任务failed并保留所有尝试，明确重试同请求只复用已逐件核验的成功响应。排队或获取期间输入/人工意见改变不得发布回执。

GET `.../{probe_id}/files/{index}?expected_record_sha256=...`只下载本研究已登记该回执及其files编号，历史回执可读，原文指纹逐件核验；拒绝路径、URL、额外参数及其他研究编号。损坏明确报错，不当作零结果。完整追溯plan_decisions.component_identity_probes纳入正式回执和原文。session.capabilities.component_identity_probes=true开启独立网页面板；默认不执行、不勾确认、补查成功不表示身份已采用。旧后端缺能力不请求新接口。

## 2026-11-01 系统A01待核原件只读核对

GET `/studies/{sid}/analysis-plan/component-identity-evidence`返回`A01.identity_evidence_view.1`。仅当前`A01.system_publication.1`及其已登记三库绑定支持，旧版本返回supported=false。按已归档identity_decisions和TCMSP原表行整理核对组，展示原名/原编号/原决定及对应原UniProt请求和响应，不重新科学映射、不联网、不写研究。重复关系共享原查询组但保留全部issue_key和原表行，无靶点的源行单列，不能当作已检索零结果。原JSON响应条目数仅为原返回量，不代表可采用身份数。

返回`expected_a01/expected_input_hash/stats/units/files/read_only/message_zh`及JSON/CSV导出链接。导出`.../export?format=json|csv&expected_a01=...&expected_input_hash=...`；附件`.../files/{index}?expected_a01=...&expected_input_hash=...`。版本变化拒绝，附件只能从本A01及其绑定原件索引选择，逐件核SHA，不接收路径/URL/批准参数；下载不触发重算或写入。文件损坏明确失败，不显示为缺查询或零结果。session.capabilities.component_identity_evidence=true才显示网页入口，旧服务缺能力不请求。页面由用户明确载入只读清单，可下载同批CSV/JSON及原文，不提供默认通过、自动排除或身份替换。

## 2026-10-31 新登记的疾病手动原件预上传

GET `/studies/{sid}/analysis-plan/disease-manual-sources`只读返回A02.system_manual_source.1支持与资格、expected_a00/expected_plan_id/expected_input_hash、疾病首选词和GeneCards/OMIM当前暂存原件元信息；不解析原文或启动科学任务。仅支持新方案、有效且未人工批准的A00；人工暂存/退回、回收站、忙碌或版本改变阻断。旧已批准登记仍沿原A02来源入口。

POST同路径接收multipart：request_id=manualsourceq、expected_a00、expected_plan_id、expected_input_hash、author、note、confirmed=yes、database、format、query、retrieved_at、version、encoding、query_quoted、export_completeness及唯一upload文件；不接收URL、路径、批准、分数或参数覆盖，沿原16MiB请求边界。HTTP只校验结构和版本并保存实际字节/指纹，202提交plan_system_disease_manual_source；科学worker重核原确认及真实A00规范证据，复用冻结intake_sources.stage、原元信息/解析和疾病标题身份校验，原件与明确上传回执在同一次Workflow保存中发布。仅预上传，不批准A00、不发布A02或启动后续计算。相同请求及文件只返回原回执，不恢复已被替换的旧文件。原始文件、暂存版本及SHA进入完整追溯。

session.capabilities.system_disease_manual_sources=true仅新服务声明。统一疾病原件区提供明确上传表单及原件状态；不默认确认、不自动上传，旧服务缺能力隐藏入口。新上传改变疾病获取绑定，补齐后须按当前状态另行明确获取或核验五库，不能偷偷修改原获取请求。

## 2026-10-31 逐对象结构准备恢复的新批次

系统准备/资格/评分1及2的A06_PREP/A06模块页只读展示同运行摘要、固定对象和完整NA组合，名称来自本运行system_input_ref，科学状态来自归档表。评分复用现有heatmap字段，包含全部固定行列，不丢弃全NA对象；有效评分不存在时不生成空热图。隐藏旧连接/评分执行区，明确续做仍从统一批次入口；不改变复核资格或归档。新展示不导入科学计算、读取最新草稿或其他研究名单。

独立受体目录修订资格及其评分继续用上述同一只读表/热图结构，没有新字段或网页操作。只读本运行固定输入和原值；修订版续做使用已登记后台任务，页面不建议通过旧统一执行重跑。原复核权限和历史保持。

统一执行POST `/studies/{sid}/analysis-plan/system-pipeline/start`仍接原七字段明确确认；新确认调用公开start_analysis_plan_recoverable_system_batch，批次固定preparation_protocol=A06.system_preparation.2。原同request_id重试返回原批，已有旧批不升级；原Workflow开始入口继续旧版本，旧来源和历史复算保持。客户端不能传结构协议、工具路径、对象替换或通过标记。

新批在独立科学worker逐对象保存来源、准备和原顺序受体候选尝试，schema=A06.system_preparation_checkpoints.1。明确续做只复验复用成功对象，未完成目录保留另名处理；损坏、名单、工具字节、参数或实现变化拒绝，不重新下载掩盖。资格及评分显式新二版，原科学阈值、HGNC身份、Meeko/P2Rank/Top1/RMSD和NA规则不改。GET/重启不自动恢复；沿用同研究单写任务、资源预算、取消进程树和已有明确续做按钮。session.capabilities.system_preparation_recovery=true仅新服务声明，不代表科研批准或全部对象可计算。

## 2026-10-31 疾病完整原件发布候选

GET疾病获取路径的每个request增加publication：enabled/blockers/published_run_id、candidate_count_text_zh、message_zh及request（三字段expected_acquisition_request_id/expected_record_sha256/expected_input_hash）。无整批记录时request=null且禁止发布，缺失或失败不作为零。GET只读核验本研究实际归档与发布来源，不解析科学原文、不启动任务。busy时禁止发布。

POST `/studies/{sid}/analysis-plan/disease-acquisition/publish`严格七字段`{request_id:diseasepublishreq_<32hex>,expected_acquisition_request_id,expected_record_sha256,expected_input_hash,author,note,confirmed:true}`，202登记plan_system_disease_publication。HTTP只做标准库预检，独立科学worker排队后重核原确认、当前登记/来源/方案和人工意见，经公开Workflow及生产规范校验发布A02.system_collection.1；缺库不发布，不伪造approved/parent_review_ids，原件、旧运行和复核保留。此候选handoff_blocked=true，须另经已确认批次标准化，不能直接启动A03。字段422、过期/忙碌409、回收站423、令牌/Origin403沿用。原相同发布确认可幂等核对已发布候选或其真实标准化祖先；其他新内容不能借旧请求号覆盖。

session.capabilities.system_disease_publication=true仅实际支持的服务声明。统一疾病原件区提供明确发布按钮和确认框，展示原获取登记人/说明，发布登记沿用并明确注明本次候选操作；不开页面自动提交，不预选批准。网络失败保留发布请求号，409只刷新不重交。旧服务缺能力时隐藏发布入口，即使支持原件获取也不显示。已发布显示实际原始候选记录数及后续批次入口含义，不称正式基因数或人工批准。

## 2026-10-31 疾病五库系统原件获取

GET `/studies/{sid}/analysis-plan/disease-acquisition`标准库只读返回A02.system_acquisition.1的supported/enabled/blockers、expected_a00/expected_plan_id/expected_input_hash、automatic_databases(TTD/PharmGKB/OTP)、manual_databases(GeneCards/OMIM)、scientific_publication_available:false、busy、disease_identity_zh、requests及message_zh。每请求含原request/plan_id、state(complete/incomplete/not_recorded)、state_label_zh、display_sources（database/state/state_label_zh/records_text_zh/reason_zh）、retry_enabled/blockers和整批/检查点/失败计数。显示合并真实最新整批与实际成功检查点；缺库、失败、未写成整批不作为0条。GET不采集、不解析科学原文、不排队或改变研究。

POST同路径`/execute`只接受`{request_id:diseaseacqreq_<32hex>,expected_a00,expected_plan_id,expected_input_hash,author,note,confirmed:true}`，202提交plan_system_disease_acquisition。HTTP只做标准库预检，科学worker再核对原确认/来源/人工意见后实际获取及解析。缺确认/路径/URL/疾病词/passed等覆盖422，过期或忙碌409、回收站423，令牌/Origin403沿用。同内容原请求补取保留原方案，后来草稿不替换；补上传改变绑定后须新确认，同A00已有成功系统原文可核验复用。部分incomplete任务必须failed，成功库和诊断保留，不写0或完整，不发布A02或人工批准。

统一页面按session.capabilities.system_disease_acquisition=true显示疾病原件区；默认不勾新获取确认，原请求补取经明确窗口，网络失败保留请求号，409只刷新不重交。旧服务无该能力不显示/请求新接口。页面只展示服务端事实，不能将原件完整解释为疾病候选或科学分析已完成。

## 2026-10-30 系统三库原件获取后台入口

新增POST同路径`/bind`严格接收`{request_id:systemsourcebindreq_<32hex>,expected_acquisition_request_id,expected_record_sha256,expected_input_hash,author,note,confirmed:true}`，202提交plan_system_source_binding。HTTP只按当前原获取、最新完整记录、原方案、当前A00/A01/旧暂存与人工意见做标准库预检；原ZIP解包/派生产物重建在实际科学worker执行，不在HTTP。字段422、过期/忙碌409、回收站423、令牌/Origin403沿用。绑定只追加系统科学来源指针，不改旧上传、current/runs/reviews或发布A01；完成同请求幂等，排队后输入/方案/人工暂停变化拒绝。GET每request增加binding(enabled/blockers/bound/request三expected字段)，未成整批、缺库和新草稿均不可绑定；已有当前绑定显示bound并禁用新绑定。实际绑定后科学批次仍按五库/HGNC和身份规则检查，不自动启动计算。

session.capabilities.system_source_binding=true仅新绑定服务返回。页面提供明确“绑定为本批科学输入”，确认窗口展示原门槛、原获取登记人/说明及不批准科学结果的范围；只在用户明确继续时提交严格新绑定请求，网络失败保留请求号，409只刷新。旧服务即使有三库获取能力但没有新绑定能力也不显示绑定按钮。

统一网页`#/system-pipeline/{sid}`增加三库原件区，仅在session.capabilities.system_acquisition=true时读取/显示。GET增加当前screening_parameters、各原请求绑定的screening_parameters/state_label_zh/display_sources；display_sources逐库合并实际最新整批与已归档成功检查点，不能把未形成整批记录当complete。每行含database/state_label_zh/reason_zh；这些均为服务器事实翻译，不在浏览器推算通过或完整。新获取默认未勾确认；原请求重试经明确确认窗口，仍提交原七字段。页面读取/刷新/任务完成不自动POST，409只刷新不重交，复核与科学批次语义保持。

GET `/studies/{sid}/analysis-plan/system-acquisition`只读返回A01.system_acquisition.1的supported/enabled/blockers、expected_a00/expected_plan_id/expected_input_hash、busy、scientific_publication_available:false与requests。每个请求含原request、plan_id、state(complete/partial_failure/incomplete)、最后整批sources、独立source_checkpoints、record_count/failure_count/source_receipt_count、retry_enabled/retry_blockers和说明。sources是最后整批事实，source_checkpoints可含整批写入前已保存的成功库；GET不下载、解析科学数据、创建任务或签署复核。

POST同路径`/execute`只接受`{request_id:systemacqreq_<32hex>,expected_a00,expected_plan_id,expected_input_hash,author,note,confirmed:true}`。新请求核对当前方案及输入；原请求必须原字原意相同，后存草稿不替换其计划。202登记plan_system_acquisition任务；HTTP只做标准库预检，实际A00生产规范核验、获取、ZIP校验和恢复均在隔离科学进程。路径、URL、门槛、passed等覆盖字段422；过期409、忙碌409、回收站423、令牌/Origin沿用原403。排队期间实际登记/来源/人工意见变化拒绝，不自动重交。

后台部分失败保存成功库和真实诊断，任务明确failed，不能当0或完整；明确重试只补缺库，完成的同请求只核验复用。current/runs/reviews及旧current_component_uploads保持；来源获取尚未自动接入科学批次，不发布科学A01。日志、资源位、取消及同研究单任务沿用既有管理，GET/重启不恢复。当前仅接口/任务，网页按钮后续接入。

## 2026-10-30 统一系统批次后台入口

统一网页位于`#/system-pipeline/{sid}`，当前A00方案卡提供入口。GET增加study_label_zh、purpose_zh、start.parameters/parameter_hash/mode_label_zh及各批次原绑定参数；history增加stage_label_zh/state_label_zh，批次增加continue_enabled/continue_blockers。这些显示字段只翻译真实方案和流水。API层automatic_execution_available=true表示网页入口已接通，提交仍按start.enabled、continue_enabled、busy和实际指纹判断。首次confirmed默认不勾选；续做只提交已有批次当前指纹，网络失败不自动重交。

GET `/session` 的capabilities.system_pipeline=true仅由已接通接口的新服务返回。前端A00入口还须此能力；仍运行旧后端的服务即使读取新静态文件也不显示不可用入口。此能力不代表研究资料已齐或科学结果通过。

GET `/studies/{sid}/analysis-plan/system-pipeline`标准库只读已有明确批次、原绑定plan_id、流水历史、expected_input_hash及start/busy；不联网、计算、写决定或自动恢复。

POST同路径`/start`严格沿用ModuleA.system_execution.1的request_id、expected_a00、expected_plan_id、expected_input_hash、author、note、confirmed:true，登记一次实际授权后提交plan_system_pipeline。POST`/continue`只接受batch_id与当前expected_input_hash，明确续做已有授权，不再要求逐阶段确认。HTTP不运行科学验证器；后台排队后再次核对输入，原批方案不被后来草稿替换。字段422、过期/忙碌409、回收站423，原令牌/Origin保护保持。重复原确认不重复建批，已完成有效科学运行和同源报告复用。

目前前置条件仍须已提供三库原件、同批HGNC及现代五库候选；缺资料失败不等于零结果。空交集的PPI/富集/结构/评分不执行，方案未纳入富集不运行R，全NA不执行Vina；逐阶段真实状态与不适用原因进入追溯system_pipeline。失败留原件及诊断，取消/中断不自动重启，过期排队请求先刷新后明确续做。最终停在实际双报告待结论复核，不写人工reviews。科学完整原件恢复与评分逐组合续算按各既有新协议，尚未覆盖所有不完整准备过程。

## 新方案同批双报告

GET `/studies/{sid}/analysis-plan/reports`标准库只读返回supported/enabled/blockers、expected_report_run_id(null|run_id)、expected_input_hash、history及message_zh。资格读取真实当前结果和系统校验；空交集可按实际不适用分支进入，非空结果须等适用网络/富集/准备与评分结束，缺真实回执阻断。GET不绘图、不运行R/Vina、不写研究。

POST同路径`/generate`严格接受`{request_id:planreportreq_<32hex>,expected_report_run_id,expected_input_hash,author,note,confirmed:true}`，202提交plan_report后台；不接收事实、结论、图件路径、参数或通过标记。后台独立重建同批事实和范围来源，生成实际PNG/SVG及双Word，锁内重新核验后追加A07.plan_report.1及不可变请求/回执。运行parent_review_ids为空、parent_validation_records是真实系统证据，绝不伪造人工reviews；原A07仍原分派。失败保留请求/诊断/未发布文件，过期409、回收站423、忙碌409、字段422；GET/重启不重跑。

GET同路径`/{run_id}/files/{index}`仅下载本研究已登记报告回执中两份实际DOCX(0主报告/1简略版)，当前与历史逐件SHA核验，不接受裸路径。history含服务端实际active/approved/status_zh和downloads；人工批准只来自真实Workflow.review。新报告自身最终复核不改变上游系统证据，相关来源批准撤回仍使报告失效。追溯增加report_requests/report_receipts完整历史与图件/Word/实现来源；CSV保留原科学表，新增A07平面摘要与分支事实。

## 新方案A01至疾病标准化兼容

既有A02 `/actions/normalization`在当前A01为A01.plan_publication.1时，由后台采用A02.plan_normalization_bridge.1入口适配。该A01已经三库标准化，须当前复核有效并与疾病侧使用同HGNC规则、快照和补充证据；接口只读资格提前显示阻塞。预览保留其真实摘要和完整三库关系，不读取旧compound_targets或重筛三库；发布只新增A02，A01方案、结果和复核不变。映射或A01复核变更拒绝，A02仍须独立整体复核，不自动启动A03。HTTP字段及原标准化/范围/身份科学规则保持；旧A01继续原入口。此为分阶段兼容修复，最终一次确认自动版尚未开放。

## 新方案独立系统校验

GET `/studies/{sid}/analysis-plan/system-validations`只读返回supported、items及history。每项包含module_id/run_id、enabled/blockers、request(expected_run_id/expected_input_hash)及绑定当前输入的current回执。历史回执保留实际passed和scientific_status(result_outcome/handoff_blocked/ready_for_successor)，规范一致性通过不消除科学失败、NA或身份阻塞，不授予旧流程批准。GET不运行R/Vina、不写入；旧研究supported:false。

POST同路径`/execute`严格接受`{request_id:syscheckreq_<32hex>,expected_run_id,expected_input_hash}`，拒绝客户端passed/路径/批准。202提交plan_system_validation后台任务，实际生产验证器复算，失败也保存独立失败回执且任务失败；同请求回执幂等，不写人工reviews/current。过期409、回收站423、忙碌409，未知字段422，GET/重启不自动重跑。追溯plan_decisions新增system_validation_requests/system_validations，包含真实请求、输入及父文件、原人工记录快照、验证器源码SHA和检查结果，逐件核验；CSV科学数值不变。

## 新方案A05分类、核译与展示资料

GET `/studies/{sid}/analysis-plan/a05-display`只读实际A05.plan_enrichment.1绑定方案及独立展示记录，返回supported/enabled/blockers、expected_a05/expected_display_id/expected_input_hash、plan_id/parameter_hash/parameters、current及message_zh。不运行R、不联网、不生成记录。POST同路径`/prepare`严格接受`{request_id:a05displayreq_<32hex>,expected_a05,expected_display_id:"",expected_input_hash,author,note,confirmed:true}`；`/confirm`在相同基础字段上增加`excluded_ids:[]、uncertain_decisions:[{ID,decision:retain|exclude|defer,reason}]、translations:[{ID,english,zh,reason}]`，expected_display_id绑定当前展示。未知字段、路径、参数和批准拒绝；后台a05_plan_display调用公开Workflow追加明确请求、来源快照、同方案数量的双语图表及决定，不改A05/current或reviews，不运行R。未决分类、缺译和暂缓分别记录，ready_for_display不等于科学批准。过期409、回收站423、忙碌409，失败保留请求及未发布原件，GET/重启不重跑。

GET `/studies/{sid}/analysis-plan/a05-display/{display_id}/files/{index}`只允许本研究已登记展示的实际图件编号，逐件SHA核验后供下载／内嵌；不接受路径。完整追溯plan_decisions增加a05_display_requests/a05_display_records，CSV的展示派生表使用`display.<display_id>.<table_name>`独立标识，原科学统计表名和数值保持。

## 新版结构准备入口与同批导航

GET `/studies/{sid}/analysis-plan/preparation-ui`只读当前固定输入、其绑定方案参数、当前A06_PREP实际版本/摘要、可执行条件及口袋/共晶/整体复核/评分导航。返回supported/enabled/blockers、input_hash、expected_input_id、expected_preparation_run_id、parameters、scope、current及steps，不计算或联网。POST同路径严格接受`{request_id:planprep_<32hex>,expected_input_id,expected_preparation_run_id:null|run_id,expected_input_hash,author,note,confirmed:true}`，拒绝路径/参数/名单/批准。后台a06_plan_preparation_ui核对完整输入与复核快照，归档明确请求后复用原第二版科学准备子进程；成功追加回执，不改人工reviews、不启动评分。已有同输入有效准备不重复执行；原输入、当前准备或复核变动则旧请求拒绝。任务忙碌、工具缺失、回收站明确阻断。A06_PREP可选plan_preparation_ui显示同内容，旧准备接口/科学协议保持。新请求与完成回执进入研究追溯。

## 新方案受体选择与准备输入网页

GET `/studies/{sid}/analysis-plan/selection-ui`只读汇总A04实际绑定方案、最新草稿是否另存、原选择及独立复核、A03_SELECT批准和当前A06固定输入。返回supported、input_hash、expected_a00/a03/a03_select/a04/plan_id、parameter_hash、parameters、newer_draft、selection/selection_review/current_input、三项operation的enabled/blockers。GET不计算名单或写入。A04及A06_PREP的可选plan_selection_ui复用该内容；网页复用原三个明确POST：生成a04-selection、选择独立reviews、归档a06-preparation-input，初始不勾确认、不选通过，完成不启动结构准备或评分。参数以A04实际绑定方案为准，不用后存草稿替换旧网络；新成分配置和受体方案数量/排序不一致时，准备输入继续拒绝。HTTP字段及任务语义不变。

追溯JSON的plan_decisions包含receptor_selections、selection_reviews、preparation_inputs完整不可变历史及file记录。导出验证研究/版本和递归文件SHA；决定不进入CSV科学结果表，不修改模块reviews或current。新固定输入页不提供旧自动对接区，避免将保存输入当执行授权。

## 新方案成分选择

GET `/studies/{sid}/analysis-plan/a03-selection`只读返回supported/enabled/blockers、expected_a00/a03/selection/plan_id/input_hash、parameter_hash、target_count、metric、原A03完整ranking、identity_pending和当前current/current_summary/current_selected，不在HTTP计算名单。POST同路径`/execute`严格接受`{expected_a00,expected_a03,expected_selection,expected_plan_id,expected_input_hash,operator,reason,confirmed:true}`，不接受名单、数量、指标、路径或批准。后台a03_plan_selection经公开Workflow写锁内复算实际A03，读取方案目标/排序，追加A03.plan_selection.1待复核名单及不可变请求。并列全部保留、不足按实际、零交集不补位，实际入选身份待补时停止不换低排名。当前A03_SELECT可选plan_compounds返回相同只读字段并关闭旧固定前五表单；旧研究保持。生成不代签、不启动A06；新A06准备输入须核对新成分配置与受体选择绑定方案的数量/指标一致，历史选择版本保持。

研究追溯 JSON 的 stage_execution 附加不可变 requests/receipts，包含确认快照、实际运行/结果及各自文件记录；导出逐件核验 SHA 并检查研究和运行关系。该字段只读，旧研究为空数组。CSV 仍为当前结果表，不将未发布来源响应当计算结果。新方案交集与方案阶段页面的旧“保存并继续”保持关闭，复核后从明确阶段入口继续。

## 2026-10-29 新方案阶段接续

GET `/studies/{sid}/analysis-plan/stages`仅读取ModuleA.plan_stages.1资格，含supported、expected_input_hash、expected_a00/expected_plan_id、parameter_hash、parameters及stages(A02/A03/A04的enabled/blockers/current_run/active/approved)。指纹绑定当前全部运行/复核、方案及原件清单；GET不写入或启动。POST同路径`/execute`严格接受`{stage,expected_a00,expected_plan_id,expected_input_hash,operator,reason,confirmed:true}`，不接受路径/阈值/批准。202提交plan_stage，字段422、过期/忙碌409、回收站423。后台再校验，公开Workflow追加不可变明确确认/输入快照和完成回执；失败只留请求和原件，不写成功回执或reviews。取消/中断不自动重跑，过期重试须刷新后重新确认。

A02仅初始化尚无当前版本且具有效MeSH新登记的五库候选，真实单库失败和缺库保留；已有A02继续原来源/范围/身份入口，不自动通过。A03.plan_intersection.1复用原交集算法，绑定同研究方案、实际A01/A02结果及批准，完整保留旧排序/韦恩规则；结果待独立复核。A04接续复用A04.plan_network.1，当前方案置信度进入真实STRING；联网期间另存草稿不改变本批，发布前A03批准和A04版本变化拒绝。已有同方案有效结果不能重复生成。A04/A05互不代替；本入口不调用旧continue，不启动A05/A06或报告。当前A00/A02/A03/A04可选plan_stages提供同GET字段；新方案A04不再提供旧固定阈值按钮。

## 新方案A06口袋证据核查

`GET /api/v1/studies/{sid}/analysis-plan/a06-pockets`只读当前第二版准备或其第三版确认修订的预测口袋清单。返回` supported,enabled,reason_zh,expected_input_id,expected_preparation_run_id,source_preparation_run_id,items`；每个受体的`options`逐项提供口袋键、PDB、链、搜索盒、原始预测文件指纹及`eligible/reason_zh`。GET不联网、不准备、不保存决定。

`POST /api/v1/studies/{sid}/analysis-plan/a06-pockets/reviews`严格接受`{request_id:pocketreq_<32hex>,expected_input_id,expected_preparation_run_id,reviewer,note,confirmed:true,decisions:[{target_id,pocket_key:null|64hex}]}`。decisions按原固定受体顺序完整提供；null保留原状态，只能选择该受体已归档且身份、结构、环境及两次预测一致的口袋。后台`a06_plan_pocket_review`在隔离科学环境重新核验第二版来源和决定，追加独立决定及`A06.plan_preparation.3`准备运行；已有请求同内容幂等，改内容或过期输入拒绝。确认只代表采用预测位点作探索，第三版仍`handoff_blocked:true`、`scored_pairs:0`，不代签模块复核或执行评分。修订决定必须绑定当前第三版，来源第二版和历史决定保持。请求不接受结构路径、坐标、评分、质控状态或伪造确认人签名。

## 新方案A06共晶参考证据

`GET /api/v1/studies/{sid}/analysis-plan/a06-reference-preparation-v2`只读返回新版参考资格准备状态；完成后显示`state:bound`，不在GET运行科学复算。`POST`同路径接受与第一版绑定相同的严格请求字段，后台任务`a06_plan_reference_qualification_v2`通过隔离科学解释器复验归档并追加`A06.plan_reference_preparation.2`；旧第一版接口及运行保持。重复请求同内容且仍有效时返回已有运行；过期、改内容或无科学工具时拒绝。新版本保留`handoff_blocked:true`和`scored_pairs:0`，不批准或评分。

`GET /api/v1/studies/{sid}/analysis-plan/a06-references`只读取当前新版准备事实包中的共晶候选，返回目标、候选稳定键、PDB、组件、链、邻域距离和可选原因；不联网、不准备、不改变研究。`POST /api/v1/studies/{sid}/analysis-plan/a06-references/reviews`严格接受`{expected_input_id,expected_preparation_run_id,request_id:refreq_<32hex>,reviewer,note,confirmed:true,choices:[{target_id,candidate_key,reference_key}]}`，可提交空清单表示明确不采用参考。后台`a06_plan_reference_review`在隔离科学环境重新核对同批mmCIF、CCD、序列、Meeko、搜索盒及实际参考重对接，追加`A06.plan_reference_review.1`证据决定；不切换`current`、不写模块reviews、不计算成分×受体组合。请求不接受路径、坐标、PDB参数或客户端质控结论，候选失效、输入过期或研究任务忙碌时拒绝。

`GET /api/v1/studies/{sid}/analysis-plan/a06-reference-preparation`返回参考证据是否已绑定当前新版准备。`POST /api/v1/studies/{sid}/analysis-plan/a06-reference-preparation`严格接受`{expected_input_id,expected_preparation_run_id,expected_review_id:refreview_<32hex>,request_id:refprep_<32hex>,reviewer,note,confirmed:true}`，后台`a06_plan_reference_preparation`追加`A06.plan_reference_preparation.1`准备版本，完整保留原准备、参考核查和文件指纹；新版仍`handoff_blocked:true`、`scored_pairs:0`，不自动批准、不启动成分×受体评分。当前准备或参考核查过期时拒绝，绑定后旧版本只读保留。

`GET /api/v1/studies/{sid}/analysis-plan/a06-reference-qualification`只读复算当前`A06.plan_reference_preparation.1`是否具备进入人工整体复核的资料条件，检查事实包、原准备结果、参考核查包、文件指纹以及`handoff_blocked:true`/`scored_pairs:0`；返回`qualified`和阻塞项。资格通过不等于模块批准，通用复核入口仍按阻断规则拒绝将候选准备批准为正式下游输入；GET不联网、不写入、不启动评分。

`GET /api/v1/studies/{sid}/analysis-plan/a06-scoring-readiness`只读返回正式评分资格与阻塞项；第一/二版参考绑定准备的`scoring_allowed`保持false。新可复核准备按末节评分协议检查当前人工批准、固定输入与任务/工具条件；符合条件也只开放独立明确执行入口。该GET不提交任务、不改变复核或运行状态。

`GET /api/v1/studies/{sid}/analysis-plan/a06-review-packet`只读汇总当前新版准备的运行版本、参考证据、归档文件核查数量、资格结果和评分阻断项；返回`review_available:false`、`can_enter_review:false`、`scoring_allowed:false`。此接口只为人工整体复核提供材料，不写入研究、不提交任务、不改变当前版本。

`GET /api/v1/studies/{sid}/analysis-plan/a06-review-packet/export.json`下载同一只读材料包JSON；下载前重新读取当前研究并逐件核验归档指纹，文件名绑定研究编号。导出不写入研究、不改变当前版本、不提交评分。

`POST /api/v1/studies/{sid}/analysis-plan/a06-scoring/validate`严格接受`{expected_preparation_run_id,reviewer,note,confirmed:true}`，只读核对第二版参考绑定准备及其原第二版准备、登记输入和方案；返回`protocol_version:A06.scoring_gate.1`、`read_only:true`、当前/来源准备编号、输入编号/指纹、方案参数指纹、来源配置指纹、最新准备复核编号、固定组合数、ready/NA数，以及从原准备读取的实际Vina参数、搜索盒外扩和RMSD上限。不能从客户端覆盖参数或传入批准。`allowed:false`和`execution_available:false`保持，预检确认不构成评分授权。过期版本、错研究/版本、损坏原件、非法字段拒绝；失效上游、变动输入、全NA及未批准等原因列入blockers；读取期间manifest变化拒绝。不创建任务、不写入复核、不解除阻断。

评分闸门只读响应增加`preflight_available`，仅第二版参考准备且非回收站提供预检表单；旧版本接口及执行行为保持。

上述资格核查与评分闸门同时识别`A06.plan_reference_preparation.2`：核对同研究固定输入、事实包、参考包、逐件指纹和空评分矩阵，返回归档完整性状态。此GET不执行科学准备，不将归档完整性显示为正式审批；第二版的`can_enter_review`与`scoring_allowed`仍为false。

清单另返回`current_summary`和当前已完整归档的`saved_decisions`；null口袋键始终回到原第二版状态，修订不能误认为沿用上次已采用口袋。网页独立`#/plan-pockets/{sid}`展示清单、盒参数、残基和两次文件指纹；A06_PREP页顶栏提供入口。保存过的选择可回显，首次不预选采用，提交确认框始终默认未勾选。网页只消费服务端`eligible`和摘要，不计算科学通过与否。

## 2026-10-27 新方案A06实际准备

新增`POST /api/v1/studies/{sid}/analysis-plan/a06-preparation`，严格接受`{expected_input_id,request_id:planprep_<32hex>,author,note,confirmed:true}`。仅当前已归档且上游复核仍有效的新版A06输入可提交`a06_plan_preparation`后台任务。科学工具根目录只从服务器本机配置读取，请求不能提供路径、名单、质控状态或Vina参数。第二版`A06.plan_preparation.2`从绑定方案读取Vina参数及搜索盒外扩；严格RMSD须同时符合默认2 Å及更严格的方案上限。第二版本身保持`execution_available:false`、`scored_pairs:0`、`handoff_blocked:true`；其自动检索只生成未确认预测口袋，采用入口和第三版见本文件前节。共晶参考候选与独立复核接口已接入，但通过项仍不自动升格为准备批准或评分输入。第一版和历史规则由原校验器处理。

## 2026-10-27 新方案A04选择复核与A06准备输入

新增`POST /api/v1/studies/{sid}/analysis-plan/a04-selection/{selection_id}/reviews`，JSON严格为`{request_id,expected_a00,expected_a04,selection_id,expected_review_id:null|selectionreview_<32hex>,decision:approved|rejected|pending,reviewer,note}`，路径与正文选择编号必须相同。仅对当前已批准A04的最新同研究选择复算后，追加独立复核记录；重复编号同内容幂等，过期复核409。该决定不写原科学运行的reviews，也不批准A06。

新增`POST /api/v1/studies/{sid}/analysis-plan/a06-preparation-input`，严格接受`{request_id,expected_a00,expected_a03,expected_a03_select,expected_a04,expected_selection_id,expected_selection_review_id,expected_plan_id,author,note}`，提交后台`a06_plan_input`。任务再次核验当前且已批准A03_SELECT与A04同源A03，A04受体选择独立复核为approved、原结果和方案完整复算，然后追加A06新版本准备输入索引。`GET /analysis-plan`新增`a04_selection_review`、`a06_preparation_input_history_count`、`a06_preparation_input`；上游运行或复核改变时只保留历史数。此输入尚未执行结构准备或Vina，`execution_available:false`，不改变current/runs/reviews，不代签。所有POST沿用Host、Origin、令牌、任务互斥及回收站保护。

## 2026-10-27 A04新方案受体选择归档

新增`POST /api/v1/studies/{sid}/analysis-plan/a04-selection`，仅接受`{request_id:planreq_<32hex>,expected_a00,expected_a04,expected_plan_id,author,note}`。通过`a04_plan_selection`后台任务，从本研究当前已批准的新方案A04完整指标表按该A04绑定的方案复算受体名单，并在研究包内追加指纹索引。重复request_id及同内容幂等，改内容冲突；旧A04、过期版本、回收站和未批准A04拒绝。`GET /api/v1/studies/{sid}/analysis-plan`新增`a04_selection_history_count`及当前A00/A04匹配的`a04_selection`，旧研究返回0/null。选择仅为待独立复核的决定草稿，`execution_available:false`；不更改current/runs/reviews，不批准、不启动A06准备或Vina。写请求仍要求原令牌、Origin、Host及同研究任务互斥保护。

## 2026-10-26 双版本方案第一阶段

新增只读`GET /api/v1/analysis-plans/parameters`，返回统一参数定义、固定保护规则、阶段依赖及`execution_ready:false`。`POST /api/v1/analysis-plans/validate`接受`{specification,previous?}`；specification为`{schema_version?,mode:standard|personalized,parameters?}`，parameters只接受目录中的点分键。返回`{plan,impact|null,execution_available:false}`；previous若提供须为原样已编译方案。该接口仅校验和计算失效范围，不写研究、不联网、不批准、不执行科研。POST仍要求令牌、Origin和Host校验。

新增`GET /api/v1/studies/{sid}/analysis-plan`和`POST /api/v1/studies/{sid}/analysis-plan/drafts`，后者仅接受`{request_id:planreq_<32hex>,expected_a00,expected_draft_id,specification,author,note}`。只有A00显式登记`analysis_plan_profile=ModuleA.analysis_plan.1`的新协议研究支持草稿；旧研究写入拒绝。相同request_id同内容幂等，改内容或草稿版本冲突409，回收站只读423。写入仅经Workflow公开方法，在原写锁中追加`decisions/analysis_plans`与manifest索引，不改变current/runs/reviews或活动计算。运行中编辑仅保存草稿，不改变旧批。

当前参数目录另返回preview:{version,preview_only:true,groups,details,source_rules,fixed_rules_zh,message_zh}，只提供中文界面分组和真实接通状态；默认值、合法值及保护规则仍来自原目录。前端独立`#/parameters-preview`可切换标准/个性化、编辑目录内参数、调用原validate进行内存校验，并在校验后下载标有preview_only的本地方案JSON；不创建研究、不保存研究草稿、不提交科研任务。旧新建窗口只提供独立预览链接，原创建payload和行为保持，预览值不带入旧流程建档。后续实际执行器接通并验收后才开放新流程创建入口，避免可调界面与真实计算脱节。

用户确认目标成分数和目标受体数改为自由整数输入：a06.component_count及a06.receptor_count目录改用type:integer、min:1、max:25，不再返回choices；默认均15，其他图表数量和A/B窗口的10/15/20/25选项保持。校验接口支持2×2等范围，拒绝越界、非整数、布尔值及字符串；并列处理规则和execution_available:false保持。现有合法方案内容及指纹不改变。

## 2026-10-26 研究追溯与导出

新增只读`GET /studies/{sid}/trace`，返回当前研究各模块的run_id、父运行、输入/配置/代码/环境指纹、结果摘要、结果表名、方案草稿及导出链接；普通读取不携带完整表。`GET /studies/{sid}/trace/export.json`下载同一研究当前版本的完整追溯JSON，包含结果表和已登记文件相对路径、角色、大小与SHA-256；`GET /studies/{sid}/trace/export.csv`下载所有当前结果表的UTF-8 CSV，列为study_id、module_id、run_id、table_name、row_index、record_json。三个入口均为只读，不启动任务、不改变current、reviews或结果。

导出前服务端逐件调用归档指纹核验；缺失、篡改、跨研究或损坏文件阻断导出。下载不接受任意路径参数，沿用本机Host检查、POST令牌规则（GET仍不执行科研）、no-store和Content-Disposition。导出的追溯包只代表当前研究版本；历史运行仍由原文件登记和已有单表接口读取，后续版本必须追加而不能覆盖。

## 2026-10-23 HERB后台采集容量及断点

接口和客户端上传容量不变。仅服务器固定HERB采集生成的完整包允许64MiB，原统一stage再次检查ZIP成员/256MiB展开量、路径、药味、身份和当前版本。客户端不能以来源JSON字段选择该容量。再次显式采集可按同研究、同A00/A01及药味绑定恢复成功原响应，不跨研究复用；GET不联网，复核和A02不改变。任务progress.step_zh显示成分序号、原件复用数或当前退避重试，原done/total为整体包装步骤，不表示下载百分比。

## 2026-10-23 网页并发读取与附件发送

接口字段、排序、权限及版本冲突规则保持。首页与全局待办可共享同索引及活动任务版本正在进行的卡片组装；最多三项独立研究并行，结果保持原序，各请求取得独立容器，完成/失败不缓存。表格与普通运行文件请求可共享同研究/运行/索引版本进行中的完整结果核验；选定附件仍独立指纹验证，跨研究和历史边界保持。附件/静态资源分块发送，字节、Content-Length、Content-Disposition、CSP、no-store保持；浏览器中断不另发第二份响应。GET不计算、不批准，POST不进入合并读取。

## 2026-10-22 三库获取与疾病映射预览

新登记A00绑定component_source_profile=A01.multisource.collect.1；旧研究不重解释。SourceUploadInfo新增可选acquisition:{enabled,databases,latest}、verification:{enabled,coverage,issues_count,version}、mapping_preview:{enabled,latest}。latest只显示同研究同A00/A01或A02版本的归档摘要、preview_id和各库状态计数，不含原响应。
POST /studies/{sid}/modules/A01/actions/acquire_sources：{expected_a00,expected_run,expected_staging,databases,reason}，固定三库非空去重子集，后台a01_acquire逐库获取并经原stage校验归档；仅采集，不覆盖当前A01/A02或批准。缺库不回退单库。
POST /studies/{sid}/modules/A01/actions/resolve_sources：{expected_a00,expected_run,expected_staging,reviewer,note,confirmed:true,confirm_coverage:boolean,omit_unresolved:boolean}，只有当前collect.1结果且来源未变才可处理。完整性确认不能替代缺库或零清单依据；身份例外绑定原问题内容，原件保持，新结果仍待独立复核。
POST /studies/{sid}/modules/A02/actions/mapping_preview：{expected_a00,expected_run,expected_staging,databases,reason}，仅TTD/PharmGKB；后台a02_mapping_preview将原文和候选留raw/A02_mapping_previews/task_id，不改当前A02。候选默认pending，不能按子串或同一系统疾病自动纳入。
GET /studies/{sid}/source_previews/{id}?database=TTD|PharmGKB&page=1&size=25读取同研究绑定预览的分页候选；index和文件指纹核对。GET /environment按需只读环境/代码版本预检，不获取数据库、不安装依赖。上述写请求沿用令牌、Origin、版本和后台互斥校验；历史、回收站只读，失败原件留存，不自动重试或批准。

## 2026-10-22 文献单成分同输入研究

ModuleA.literature_input.1复用现有ModuleView字段；A01/A02的kpis、flow、table、params按作者归档名单及实际标准化结果展示，不声称常规三库／五库新检索或方剂OB/DL筛选。该协议不显示source_uploads、disease_scope、normalization、disease_workflow及重复常规input_audit；operation_guide复用既有结构，提示查看文献来源、身份明细、独立复核和A03。A03的input_audit对该协议使用原始关系数及实际来源，不构造零条范围组或三库缺口。历史只读和常规协议保持。没有新增前端字段或默认审核授权。

A07.report.config.26仅在明确登记single_compound_literature_comparison且A01/A02均为上述同研究协议时生成，绑定文献和完整化学身份，继承第25版矩阵/图表验证，独立说明历史输入及实验未复现。既有报告版本和常规采集流程不改变。

后台任务列表可显示内部a06_resume（用户明确继续后的中断原件恢复）；没有新增公共写端点、GET执行或默认续算，原申请与取消记录保持。它只复核同研究原授权和已有证据、计算缺失区域，不能改变来源名单、位点或参数。

原任务“重试”在同一第三版原授权仍有效、原任务确曾中断且批次未完成时转入a06_resume；不重新运行连接/准备，不新建计算批次。取消、已完成、名单/连接/批准改变时拒绝。后台失败摘要保留具体异常原因，组合进度采用当前真实完成数。

## 2026-10-21 显式一次确认后连接并计算

新增POST `/studies/{sid}/modules/A06_PREP/actions/automatic_start`，字段为原第三版执行请求并增加固定`continuation_version: A06.connect_run.1`，`expected_connection_id`可为null，`reference_choices`必须明确提供（没有连接时只能为空），其余绑定、确认人、说明、confirmed:true均须真实提交。返回202后台任务`a06_auto_start`。这是明确授权后的串行连接及计算，不是GET自动计算或默认勾选确认。连接完成不再停第二次确认；连接失败、上游改变、回收站或版本冲突时停止，不自动重试计算。开始时及连接后均校验绑定和扩展范围；既有连接原件仅在本研究同批准版本且指纹一致时复用，补齐失败成分后再交原第三版执行校验器。参考选择按新连接复验，不自动选共晶配体、不改变质控或代签结果。

新连接包追加`compound_resolution_version: A06.compound_identity.1`；ModuleView.connection可选回传该字段，表示名称失败后的精确身份回查是否已执行。TCMSP按本研究MOL编号回查，仅允许官方固定分子页；编号、原名称及完整InChIKey必须与PubChem一致，原始SDF仍按既有坐标身份核验。旧连接、旧授权、旧评分不回写。

ModuleView.automatic_docking可选`active_task_kind`表示本研究当前后台任务种类；导航据此区分“等待执行确认”和“已确认、正在连接后自动计算”。它不代表科研批准。

## 2026-10-19 A06补救接续第二版

自动连接新产物及执行授权使用A06.automatic.2，旧automatic.1原件、结果和确认保持。端点和请求字段不变，默认页面发第二版policy_version；旧版连接不能沿用为第二版授权。automatic_docking新增可选migration_note_zh：旧连接尚未按新策略补齐时说明原数量及重新连接操作；不伪造第二版连接完成。GET只读，不自动补查。
第二版连接复用同研究、同上游批准指纹且哈希一致的成功原件；仅补查异常。官方网络暂时失败最多三次，完整分页检索直至找到可用候选或真实耗尽；准备失败继续独立结构、有限侧链修补和已发布模型。预测模型80/70/10、必要环境及真实序列保持核验，预测多口袋与无口袋时的30/15/5分区单列探索。一次授权覆盖这些预定义路线，不批准结果、不保证全部评分成功。
后台工具目录及新增science_repair_packages只能来自服务器配置，不接受客户端路径。失败、取消、旧策略重试不覆盖历史；冻结报告仍阻断新协议。旧版科研运行仍交给旧校验器，不把旧授权升级为新策略。

## 2026-10-19 A06一次授权自动执行

用户授权简化A06：先连接资料（不评分），随后一次明确授权，后台连续准备、质控、对接及出图；异常对象集中保留，结果仍独立复核。新协议A06.automatic.1，不解除旧协议或伪造准备批准；直接绑定本研究已批准A00/A01/A02/A03/A03_SELECT/A04及连接原件；A05仍是独立分支，不成为对接的新前置关口。原始构型、位点、参数、日志和所有组合可追溯。
ModuleView新增可空automatic_docking，含enabled、disabled_reason_zh、expected_binding、expected_connection_id、expected_a06、counts:{compounds,receptors,pairs}、policy:{version,summary_zh,details_zh}、connection:{id,created_at,summary,exceptions,objects,files}|null、latest:{id,state,run_id,summary,pairs,files}|null。对象只读归档；GET不联网或计算。历史及旧试算交接/准备关联页不显示新执行入口。
POST `/studies/{sid}/modules/A06_PREP/actions/automatic_connect`：{expected_binding}→202任务a06_auto_connect，只连接及归档资料，不确认、不评分。
POST `/studies/{sid}/modules/A06_PREP/actions/automatic_run`：{expected_binding,expected_connection_id,expected_a06,request_id,policy_version,reviewer,note,confirmed:true}→202任务a06_auto_run。request_id为auto_<32hex>；不接收客户端名单、路径、PDB或参数。服务端固定规则，一次授权仅对应本研究当前绑定；确认框默认未勾选。过期409，回收站423，同研究任务互斥；失败/取消原件保留，不自动重试。
GET `/studies/{sid}/automatic_docking/{id}/files/{index}`只读本研究索引登记且指纹一致的文件，禁止任意路径。新A06独立结果复核，不批准A06_PREP，不继承旧225组合授权。通用继续不得重新跑已完成批次或自动批准结果；A07若尚未适配该新协议，明确阻断报告生成，保留A06可复核结果。

## 2026-10-19 KEGG官方分类筛选（用户确认的新边界）

自动富集新增KEGG.disease_screening.1来源快照，按官方BRITE br08901稳定编号及已核验A00本病身份筛选完整显著表：Human Diseases中非本病直接条目均为拟排除，含癌症机制和耐药，不再沿用旧机制例外；分类/身份不明为待判断。通路分类不表示生物学无关，不删除共享基因或重算统计。
enrichment_display.catalog行新增可选classification_status:exclude|retain|uncertain、classification_zh、official_name；来源仍通过evidence_url提供。enrichment_display新增可选screening:{version,source_url,proposed_count,uncertain_count}。只读GET展示归档资料，不运行筛选或联网。既有确认请求增加可选exclude_all_confirmed:boolean；非空显著集合全部排除时必须明确为true，后台再校验，并记录决定；旧决定复算不新增必填要求。
候选修订仅追加同源A05，保留原排除选择但重置范围与版式确认，新结果独立复核。当前表单的已选数与预计保留数为本地选择计数，不能当作已归档结果。不得自动勾选人工确认或应用排除。

## 2026-10-19 等待事项说明

研究inbox与全局inbox的既有text_zh在waiting且存在reason_zh时直接显示模块标题及该原始原因，缺原因时保留既有回退；不新增字段、不推算状态或权限，不把等待资料／核译／人工确认解释为后台运行。A04证据窗口没有逐条阅读门槛，提交既有identity_plan批量请求后才后台补查，生成结果仍需独立复核。

## 2026-10-19 A01—A03输入数量溯源

当前A03的Workflow状态为stale时，input_audit.checks可首先提示实际父版本与当前已更新输入的区别（含当前标准化数，尚未标准化时明确说明）。旧A03的formula/disease数字及图表仍绑定旧父版本，不替换成当前输入冒充已重算。历史页面不追加当前版本比较提示。当前失效A03的旧图表和明细默认折叠，可展开追溯；新A02通过后才按原流程重新生成A03。
上述当前输入更新提示的check增加可选`kind:"input_update"`，前端据此将新版本提示置前，把旧输入数量与旧空集原因归入默认折叠的追溯区；不依据中文文本猜测类型。

ModuleView新增可空`input_audit:{formula,disease,checks}`，用于A01/A02/A03。formula为`{run_id,sources,missing_sources,component_label_zh,component_count,target_count,relationship_count}`，disease为`{run_id,candidate_count,target_count,scope_counts:[{value,label_zh,count,records}],empty_reason_zh}`；checks为`[{level:info|warning,label_zh,detail_zh,module_id?}]`。A03只读取该运行实际parent_runs绑定的A01/A02，不借用当前新结果解释历史；数量逐项取既有归档摘要、表和范围决定，不计算交集、补造基因或改变权限。现代研究的三库覆盖差异仅说明当前来源和待补来源，不自动混入别的项目资料、不撤销原批准。

special.venn新增`layout:overlap|disjoint|empty_formula|empty_disease|empty_both`，仅按归档数量选择示意图布局；空疾病集合不再画成有实质重叠的两圆。A02增加“仅排除待核验条目”的本地草稿操作，只处理当前表单值为pending的行，不保存、不改变direct等已决定行。范围和身份修订仍须原有明确提交及独立整体复核。

## 2026-10-19 全模块操作导航

ModuleView新增可空`operation_guide:{current_step,note_zh,steps:[{key,label_zh,detail_zh,target,module_id?,href?}]}`。current_step为从1开始的建议操作位置，不是完成率、模块状态或批准。仅只读组合本页已有归档展示字段及Workflow给出的状态；不计算科学结果，不改变权限。当前A00、A01、A03、A03_SELECT、A04、A05、A06_PREP、A06、A07均提供各自流程；A02沿用既有disease_workflow和未保存范围保护。历史页不提供操作导航。本批准备关联使用只读资料核查步骤及原关联结果地址，不能提示重复批准或质控执行。

target为本页稳定区域编号；module_id导航至同研究模块；href仅沿用本页已核验关联结果地址。点击只定位或切页，不能提交复核、后台任务、下载生成或科学选择。目标尚无操作区时定位状态/明细并解释等待条件，不生成虚假的计算按钮。前端可提示本地未保存选择，但不得将其视为归档完成。

## 2026-10-19 A02按操作顺序导航

当前A02的ModuleView新增`disease_workflow:{current_step,note_zh,next_label_zh,next_target}`，仅根据本研究归档事实、同版本预览及Workflow批准状态给出操作定位，不修改模块状态或批准权限。六步为资料、范围、身份预览、确认生成、整体复核、A03。历史版本不提供导航。DiseaseScopeInfo新增`saved_counts:[{value,label_zh,count}]`，计数单位为已保存的范围组，前端未保存的编辑不回写计数。前端存在未保存范围修改时提示先保存并暂禁预览/发布，后台原有版本校验保持。

## 2026-10-17 A02范围到标准化的完整衔接

2026-10-19操作澄清：预览表明确标注“预览”，确认表单和生成按钮置前，右侧复核可定位该表单。有同版本预览时state.reason_zh/review.blocked_reason_zh明确说明“身份预览已完成，尚未生成待复核结果”，不更改state.code或allowed_decisions。normalization.enabled在缺少固定公共参考包时为false并列出缺失文件；后台执行仍核查完整文件及原有指纹。两类人工关口保留。

当前A02候选的ModuleView增加`normalization`，包含enabled、disabled_reason_zh、expected_a00/a01/a02、scope_note_zh及preview。preview仅取本研究、相同三个输入版本的后台预览，含stamp、两侧summary与完整identity_issues、source_exceptions；不在GET执行标准化。POST `/studies/{sid}/modules/A02/actions/normalization`接收相同expected版本和`action:preview|publish`。preview提交`normalization_preview`后台任务，仅写runtime本研究预览，不改研究；publish还需stamp、reviewer、note、confirmed:true、accept_omit:boolean及accept_source_exception:boolean，调用既有normalization.publish生成待复核结果。范围未决、上游失效、回收站和忙碌均禁止，后台再次核验三个输入及预览指纹。身份例外和缺库例外必须分别明确接受；无预选、不代签、不启动A03。全排除允许既有空结果流程，但预览须突出空疾病集合。历史标准化和科学规则保持。

## 2026-10-17 疾病范围核验前置及来源身份防混用

ModuleView增加`disease_scope`：`{enabled,disabled_reason_zh,expected_a00,expected_run,expected_staging,items,choices}`。items包含当前完整scope_groups及`source_name,source_url,identity_warning,direct_allowed`，不受明细分页筛选影响。A02提示框下默认展开，全部范围选项来自后端，不预选本病。
POST `/studies/{sid}/modules/A02/actions/scope_review`：`{expected_a00,expected_run,expected_staging,decisions:[{scope_id,scope}],reviewer,note,confirmed:true}`，必须完整覆盖当前条目且不重复。`a02_scope_review`任务调用既有run_disease的scope_change批次入口，保存新候选，不批准、不运行下游。版本、令牌、回收站和忙碌校验沿用分库上传；后台再次核验。来源文件内检索词与当前研究不符时，拒绝将对应组标为direct，仍可保留待核验或排除。
新上传OMIM Excel使用`omim_xlsx_v2`，旧omim_xlsx接口上传自动升级到该解析分支；历史旧结果按旧格式可复算。新分支识别官方页尾说明而不生成候选。GeneCards/OMIM有可识别检索标题时必须同时匹配本次检索元信息与A00官方词；缺标题明确展示无法自动核对，不能声称已验证。旧来源不回写；旧错库文件显示身份警告，须由用户更换或做范围决定。

## 2026-10-17 A02失败来源定向重试

新增POST `/studies/{sid}/modules/A02/actions/retry_sources`：JSON `{expected_a00,expected_run,expected_staging,databases,reason}`，databases为当前获取失败的OTP/TTD/PharmGKB非空去重列表；只重取选中失败来源。沿用令牌、来源版本、回收站和忙碌校验，后台`a02_sources_retry`进入统一run_disease产生新的待复核A02，其他来源和历史保持。返回202 `{task,created,message_zh}`；版本过期409，不自动重试提交或批准。SourceUploadItem增加可选`can_retry`；状态来自归档source_status。失败或缺资料时数字显示“未取得”，成功空结果才显示0。原始失败查询轨迹随失败来源另存，不作为候选发布。

## 2026-10-16 新建研究与独立项目目录（用户授权）

新增POST `/studies`：`{request_id,formula,herbs,disease,mesh_term,mesh_id,operator,analysis_purpose}`。request_id为`create_`加32位小写十六进制；用途由用户明确选择formal_research或workflow_test。只接受上述字段，不接受客户端MeSH证据、批准、路径或自动计算选项。服务器固定人类9606和“仅本病，不纳入亚型”，复用原NLM核对函数；失败不建研究。核对成功只调用Workflow.create，形成A00待复核，无reviews及后台任务。

首次201；同request_id及同登记的重复请求200并返回原项目，不重复建档，修改字段冲突409。响应`{study_id,run_id,created,directory,message_zh}`。去重记录位于私有runtime/study-creation，A00保存服务器creation_request_id供重启或记录丢失后核对；每次新建操作使用新request_id，同方剂同病也独立目录。session.capabilities新增create_study。

StudyView新增`storage:{directory,folders:[{name,label_zh}]}`，目录仅供查看和复制，不接受页面指定任意文件路径。六类目录为intake、raw、normalized、runs、reviews、reports；各项目所有版本及复核保持原有存储规则。新版首页及研究页提供新建入口，成功进入该项目A00；此功能不代表新疾病全流程已验收。

## 2026-10-15 只读页面性能约定

页面状态仍来自Workflow.view。只读实例在单次请求内复用目录解析及已核验JSON的解析结果；每次独立读取仍逐文件核验SHA-256，不以修改时间代替内容校验。同研究、同manifest版本的并发状态读取合并执行，完成即移除，不缓存已完成状态；每个请求取得独立副本。复核、提交、任务及后台计算继续使用原Workflow，下载仍要求同研究登记及指纹一致。接口字段与权限不变。

## 2026-10-15 初版验收的接续与回收站边界

既有`POST /studies/{sid}:continue`与`POST /tasks/{tid}:retry`在研究处于回收站时返回423 `TRASHED_READONLY`，不建立新任务；恢复后才可显式继续或重试。后台对扩展A06只在A05已批准、所需首位命中图齐备且A07缺失/失效时生成报告。已有有效A07待复核时保持版本，已发布时返回流程完成，不重复生成或撤销现有发布。无显著KEGG时不要求补图。仍无新的研究创建或批量计算端点。

## 2026-10-14 A05排名首位命中定位图

ModuleView新增可选`ranked_pathway_maps`：`{enabled,expected_a05,disabled_reason_zh,semantics_zh,items}`；items为`{ranking,id,name_en,name_zh,count,adjusted_p,not_in_current_kgml,png_url,caption_zh}`。统计显著性与Count两个Top1直接取当前已确认A05展示排名，命中身份与数值保留；无显著条目不补图。
POST `/studies/{sid}/modules/A05/actions/ranked_pathway_maps` JSON`{expected_a05}`→202后台`a05_pathway_maps`。只制作两张KEGG原生图，使用固定pathview1.46.0；红色表示本批命中，不表示表达方向、激活或疗效。官方KGML/底图原件、下载URL/时间/指纹、命中表与节点映射独立归档。
GET `/studies/{sid}/files/ranked_maps_ID.序号`仅下载该研究登记并核验指纹的文件。历史/失效/回收站只读；新图绑定A05结果及确认展示，不更换current/runs/reviews，不代签既有机制通路推荐审批。

## 2026-10-14 A06出图资料与A07顶部下载

中英显示第四版：DrawingPair新增可选`compound_name_en`；DockingTrialInfo.matrix.rows新增`label_zh,label_en`，matrix新增`display_version,heatmap_svg`。名称按稳定compound_id连接同源A03与已归档核查，缺译不猜译。SVG与PNG共用紧凑矩阵几何及右侧纵向色标，8×8范围、完整225格评分范围、原评分、红蓝配色和A/B保持。
`bilingual_display_records`独立附件绑定A06、trial_packet与名称证据，由后台Workflow公开方法只追加PNG/SVG/XLSX/CSV；不更换current/runs/reviews，历史、失效及回收站不能生成新版本。下载键`bilingual_display_ID.序号`仅读取登记文件并核对指纹；trial_view只显示与当前A06及trial_packet同源的最新附件。

ModuleView新增可选`docking_artifacts`：`{enabled,disabled_reason_zh,expected_a06,eligible_count,ready_count,pairs,images,bundles}`。
组合行`{pair_key,compound_id,compound_name_zh,target_id,target_zh,score,eligible,package_url}`；资格以同源原始评分≤−8为本轮整理范围，不是科学通过阈值。未达范围及NA不自动生成包。
图片行`{artifact_id,name_zh,caption_zh,pair_key,created_at,url,width,height}`，同A06版本追加留存；历史和回收站只读。图片不自动纳入已批准报告。

POST `/studies/{sid}/modules/A06/actions/figure`：multipart单一`upload`（PNG/JPEG，≤16MiB），字段`expected_a06,caption,pair_key`（组合可留空）→202后台`a06_figure`完整解码并归档。
POST `/studies/{sid}/modules/A06/actions/pair_packages`：JSON`{expected_a06,pair_keys}`→202后台`a06_pair_packages`仅为选中且原值≤−8的组合生成PDB/PSE/PML、同源Top-1、输入及参数，然后自动形成所选下载合集；不运行Vina。重复请求复用已完成包，失败保留资料供重试。用户已更正为只提供按需按钮，不预先批量制作；接口内部登记`request_version=A06.drawing.on_demand.2`，旧批量请求不得恢复执行。
POST `/studies/{sid}/modules/A06/actions/pair_bundle`：同样JSON→202后台`a06_pair_bundle`只打包已有组合包，未准备组合拒绝；下载包仅含选中组合。
GET `/studies/{sid}/files/dock_artifact_ID.序号`只接受该研究归档索引中的文件，逐字节核验，不接受任意路径。所有写入经Workflow公开方法和写锁，绑定当前有效A06；不更换运行、批准和报告。
A07下载卡置于标题之后、结论之前；报告下载键及内容保持原契约。

## A05第二版展示与确认（2026-10-11）

ModuleView新增enrichment_display：{enabled,disabled_reason_zh,expected_a03,expected_a05,expected_decision_id,exclusions_confirmed,layout_confirmed,excluded_ids,missing_translations,catalog,retained_count,excluded_count,significant_count,latest}。catalog为本次完整显著KEGG清单，保留ID、Description、Count、p.adjust、RichFactor、gene_symbols，并附description_zh、translation_status、proposed、reason_zh、evidence_url。latest显示核验人、意见、时间、是否实际应用；保存清单不代表批准A05。

POST /studies/{sid}/modules/A05/actions/display_confirmation：{expected_a03,expected_a05,expected_decision_id,action:exclusions|layout,reviewer,note,excluded_ids,confirmed:true} →202 {task,created,message_zh}。排除清单可以为空，须明确核对；版式确认仅在范围已确认且当前图表中文齐备时接受，并禁止同时修改清单。后台a05_display生成新A05展示修订，统计来源和BH不变；改变清单撤销版式确认。人工确认记录通过EnrichmentWorkflow公开方法留存，失败重试复用同一决定。

special新增enrichment_display_tables：{bp_top15,cc_top15,mf_top15,kegg_p_top10,kegg_count_top10,kegg_excluded}，均为同源归档行；enrichment_graphs：{go|kegg:{url,caption_zh}}。当前版本的历史、失效、回收站和活动任务均禁用写操作。未确认展示范围／版式或中文缺失时，handoff_blocked由A05结果给出，不能选通过；确认后仍须用户独立复核。

本文件是前端开发和接口修改的依据。改动任何字段前先改本文件，并保证前端同步；字段只增不删，删除或改名须用户确认。

## 1 通用约定

- 前缀 `/api/v1`；服务只绑定 `127.0.0.1`，Host 头必须是 `127.0.0.1:<端口>` 或 `localhost:<端口>`。
- **令牌**：`GET /api/v1/session` 返回 `token`；所有 POST 必须带请求头 `X-ModuleA-Token: <token>`。
- **跨源**：默认只接受同源。前端开发服务器（如 `http://localhost:5173`）需启动时 `--allow-origin http://localhost:5173`。生产时前端由同一服务托管，不需要跨源。
- **并发保护**：写请求带 `expected_*` 编号（`expected_review_id`、`expected_action_id`、条目里的 `run_id`）。状态已变化时返回 409 `STALE_VERSION`，前端提示“状态已更新，请刷新”。
- 时间为 UTC ISO 8601，由前端格式化；面向用户的文字字段以 `_zh` 结尾。
- 错误格式：`{"error": {"code", "message_zh", "details", "retryable"}}`。

| HTTP | code | 场景 |
|---|---|---|
| 400 | BAD_REQUEST | JSON、编号或整数查询参数格式错误；`details.field` 指出参数 |
| 403 | FORBIDDEN_ORIGIN / BAD_TOKEN | 安全检查失败 |
| 404 | NOT_FOUND | 研究、模块、运行、表格或文件不存在 |
| 409 | STALE_VERSION | 版本已变化 |
| 409 | GATE_BLOCKED | 上游未通过、`handoff_blocked`、A07 通路未对齐 |
| 413 | BODY_TOO_LARGE | 请求超过 1 MB |
| 422 | VALIDATION_FAILED | 复核人或意见为空、决定不合法等 |
| 423 | TRASHED_READONLY | 研究在回收站 |
| 503 | ARCHIVE_UNAVAILABLE | 归档文件指纹核验失败（例如 LFS 文件未下载完） |
| 503 | TOOL_UNAVAILABLE | 本机缺少某项依赖（例如 A07 通过校验需要 python-docx） |

## 2 状态码（与原型《模块状态样式一览》一一对应）

| code | 中文 | 复核栏 |
|---|---|---|
| idle | 未开始（上游未通过） | 不显示 |
| ready | 可以开始 | 不显示 |
| running | 运行中（有后台任务） | 不显示 |
| incomplete | 未完整提交（无任务在跑，可能中断） | 不显示 |
| failed | 执行失败 | 不显示 |
| waiting | 等待资料（`handoff_blocked`，不能选“通过”） | 显示，`allowed_decisions` 不含 approved |
| empty | 有效空结果·待复核 | 显示 |
| review | 待你复核 | 显示 |
| hold | 暂存待定 | 显示 |
| returned | 已退回修改 | 显示 |
| approved | 已通过 | 收起，只保留“更改决定” |
| stale | 已失效 | 不显示 |
| published | 已发布（仅 A07 通过） | 收起 |
| unavailable | 归档未就绪 | 不显示 |
| history | 历史版本（只读，`?run_id=` 查看旧运行时） | 不显示 |

前端**不得**自行推算状态；以 `state.code`、`review.can_review`、`review.allowed_decisions` 为准。
研究在回收站时，各模块仍显示原有状态，但 `can_review=false`，`reason_zh` 说明“回收站中只读”；研究卡片的 `study.trashed=true`。

## 3 端点

| 方法 路径 | 用途 |
|---|---|
| GET `/session` | 令牌、版本、平台、能力开关 `capabilities`、决定中文名 `decisions_zh` |
| GET `/studies` | 首页研究卡片 `{items: StudyCard[]}` |
| GET `/trash` | 回收站中的研究卡片 |
| GET `/studies/{sid}` | 研究页 `StudyView` |
| GET `/studies/{sid}/modules/{mid}` | 模块页 `ModuleView`；`?run_id=` 查看历史版本 |
| GET `/studies/{sid}/modules/{mid}/runs` | 中文运行历史 `{items: RunItem[]}` |
| GET `/studies/{sid}/modules/{mid}/tables/{name}?page=&size=&q=&run_id=` | 明细表分页：`{kind:"rows", columns: [字段名，按原表顺序], total, page, size, items}`；或 `{kind:"object", data}` |
| GET `/studies/{sid}/files/{key}?inline=1` | 下载归档文件。`key` 为 `<run_id>.<序号>`（来自 `ModuleView.files[].key`），或 `<run_id>.r<行号>`（A07 报告登记在 report_files 表中时）；两种都逐字节核验指纹。`inline=1` 且为图片时内嵌显示 |
| POST `/studies/{sid}/modules/{mid}/reviews` | 复核：`{run_id, expected_review_id, decision: approved\|rejected\|pending, reviewer, note, after: "save"\|"continue"}` → 201 `{review, task, message_zh}` |
| POST `/studies/{sid}/reviews:batch` | A01+A02 一次提交：`{reviewer, entries: {A01: {run_id, expected_review_id, action: "decide"\|"preserve", decision, note}, A02: {...}}}` → 201 `{reviews, task, message_zh}`；两项都通过时自动开始生成 A03 |
| POST `/studies/{sid}:continue` | 手动推进到下一人工关口 → 202 `{task, created}` |
| POST `/studies/{sid}:trash` / `:restore` | `{operator, reason, expected_action_id, confirm: true}` → 201 `{action}` |
| GET `/inbox` | 跨研究待办 `{items: [{study_id, study_title_zh, module_id, code, label_zh, text_zh}]}` |
| GET `/tasks?study=&active=1` | 任务列表 |
| GET `/tasks/{tid}` / `/tasks/{tid}/log?offset=` | 任务详情 / 增量日志 `{offset, next_offset, text}` |
| POST `/tasks/{tid}:cancel` / `:retry` | 取消 / 重试 |

任务对象 `Task`：`{task_id, study_id, kind, kind_zh, state: queued|running|succeeded|failed|cancelled|interrupted, state_zh, requested_by, message_zh, error_zh, progress: {step_zh, done, total}|null, created_at, started_at, finished_at}`。前端每 3 秒轮询有活动任务的研究即可。

### 参数与任务失败处理（2026-10-09 基础修复）

- `page`、`size`、`offset` 不是整数时返回 400 `BAD_REQUEST`，`details.field` 为参数名。合法整数继续沿用页码至少 1、每页 1—500 条、日志偏移至少 0 的边界处理。
- `Content-Length` 非整数或负数返回 400；超过正文限制仍返回 413。
- 提交/重试的 202 表示任务已登记，**不表示子进程一定启动成功**。启动失败时返回的 `task.state=failed`，同时有 `error_zh` 与 `finished_at`；前端显示失败原因并保留手动重试入口。
- 保存复核的 201 仍表示决定已保存；若随后启动后台任务失败，`message_zh` 明确分别说明保存成功与启动失败，前端用警告提示。
- GET 任务列表/详情时检查进程状态。Windows 只读探测进程，禁止通过 `os.kill(pid, 0)` 检查存活；排队任务保留 30 秒启动宽限。丢失进程的活动任务标记中断，不自动重跑。

## 4 StudyCard / StudyView

```jsonc
// StudyCard（GET /studies 的 items）
{
  "study": {"study_id", "title_zh", "formula_zh", "herbs_zh": [..], "disease": {"name_zh","mesh_term","mesh_ui"},
            "kind", "workflow_profile", "trashed", "created_at", "updated_at"},
  "purpose": {"analysis_purpose": "workflow_test", "banner_zh", "severity": "warning"} | null,
  "archive_ok": true, "archive_error_zh": null,
  "progress": {"approved": 9, "total": 10, "segments": [{"module_id","code","label_zh"}]},
  "next_step": {"module_id": "A07", "code": "review", "text_zh"} | null,
  "todo_count": 1,
  "active_task": Task | null
}
// StudyView（GET /studies/{sid}）
{
  "study": {...同上}, "purpose": {...}, "archive_ok", "archive_error_zh",
  "progress": {"approved", "total"},
  "nav": [{"group_zh": "交集与候选", "modules": [{"module_id","title_zh","sub","code","label_zh"}]}],
  "next_step": {...}, "inbox": [{"module_id","code","label_zh","text_zh"}],
  "active_tasks": [Task], "management": {"expected_action_id": "action_..."|null}
}
```

## 5 ModuleView（GET /studies/{sid}/modules/{mid}）

```jsonc
{
  "module": {"module_id","title_zh","group_zh","purpose_zh","sub","depends_on": [..]},
  "state": {"code","label_zh","reason_zh","raw_state","is_empty_result","handoff_blocked","can_review"},
  "purpose": {...} | null,
  "run": {"run_id","artifact_id","order_zh":"第 3 次运行","created_at","finished_at","reason_zh","parent_runs":{},"is_current","is_active"} | null,
  "outcome": "success"|"empty"|"failed"|"partial"|null,
  "kpis":  [{"label_zh","value","text","note_zh","source"}],          // 关键数字卡片
  "flow":  [{"label_zh","value","text","note_zh","delta_zh","kind": "main"|"plain"|"end"}],  // 数量变化链
  "flow_note_zh": "...",
  "focus": [{"tier": "must_handle"|"should_know","title_zh","body_zh","impact_zh","blocks": ["A03"]}],  // “本轮你只需核对这些”：must_handle 置顶
  "params": [{"label_zh","value","origin": "recorded"|"outline"|"decision"|"run_config"}],  // 参数与版本页签
  "table": {"columns": [{"key","label_zh"}], "rows": [..], "row_count", "source_table"} | null,  // 结果明细页签的摘要表
  "special": {...模块专属，见第 6 节...},
  "review": {
    "current": {"review_id","decision","reviewer","note","created_at","batch"} | null,
    "history": [..], "can_review", "allowed_decisions": ["approved","rejected","pending"],
    "blocked_reason_zh", "expected_review_id", "run_id", "batch_with": "A02"|null,
    "continue": {"available","note_zh"}, "already_approved"
  },
  "downstream": {"note_zh", "modules": [{"module_id","title_zh","code","label_zh"}]},
  "trace": [{"label_zh","value"}],                      // 来源与追溯页签
  "files": [{"key","role","name","path","bytes","sha256","inline"}],
  "tables": [{"name","kind": "rows"|"object","row_count","columns"}],   // 可分页查看的完整明细
  "history": [{"run_id","order_zh","created_at","reason_zh","outcome","review_decision","is_current"}],
  "tasks": [Task], "historical": false
}
```

`batch_with` 不为空时（新流程的 A01/A02），复核栏应提供“与 A0x 一起提交”，调用 `reviews:batch`。

## 6 special（模块专属数据）

A01系统三库发布仅在归档摘要同时为`A01.system_publication.1`及`A01.system_source_binding.1`时，追加可选`system_component_publication:{source_binding_protocol,message_zh}`。只标记本版原件来源，不表示候选身份已解决、当前新方案仍可执行或科研已批准；前端据此显示统一来源入口，隐藏不适用的旧人工上传/获取表单和旧分步向导。缺标记沿旧页面，状态与复核门控仍读原字段。新方案阻断提示从已存在摘要读取实际完整性/身份待核数量，缺字段省略，旧协议保持。

| 模块 | 键 | 结构 |
|---|---|---|
| A03 | `venn` | `{formula_only, both, disease_only, formula_total, disease_total}` |
| A04 | `ppi_top` | 第一轮按 Degree 降序前 10：`[{symbol, degree, bc, cc, round2, bar(0–1)}]` |
| A05 | `enrichment_top` | `{bp|cc|mf|kegg: [{id, description, count, gene_ratio, p_adjust, rich_factor}]}`（与归档展示表同源） |
| A06 | `heatmap` | `{unit, orientation:"rows=compounds, columns=receptors", color_rule_zh, min, max, receptors: [{name, order, pdb, rmsd, status_zh, role_zh}], rows: [{compound_id, compound_name, cells: [{receptor, value|null}]}], omitted: [{kind, name, reason_zh}]}` |
| A07 | `conclusion_zh`、`leads`、`limits`、`pathway`、`report_files` | `leads: [{title_zh, fact_zh, next_zh}]`；`limits: [str]`；`report_files: [{role, label_zh, key, path, sha256, row}]`（`key` 为空表示该文件不可下载） |

热图规则：整行或整列没有有效评分的不画（列在 `omitted` 中并在图下说明）；单个缺失格 `value: null` 显示白底“NA”，不填 0、不填灰色。颜色：数值越负红色越深，越不负蓝色越深，红到蓝平滑过渡，不设通用阈值。

## 7 修改本层的规则

- 视图只读归档结果，不计算科学结果，不联网；新增字段先写进本文件。
- 安全措施（Host、Origin、令牌、CSP、仅下载索引文件）不得放宽。
- 新增写操作：在 `server.py` 路由表登记，写入只能通过科学内核 Workflow 的公开方法，长计算必须走后台任务。
- 模块操作（运行、上传、范围决定、候选选择、对接方案确认、通路审核）尚未接入新接口（`capabilities.module_actions=false`），原网页仍是这些操作的入口；接入时为每个操作定义 `POST /studies/{sid}/modules/{mid}/actions/{action}` 并在 ModuleView 中提供 `actions` 列表及参数结构。


## 2026-10-09 A01 三库归档结果展示

A01 使用既有 `kpis`、`flow`、`params`、`table` 和 `focus` 字段展示三库归档，不新增状态来源。摘要含 `候选成分分组数` 时，区分结构键分组与结构待核分组；828 等数量只读归档，不能称为已全部核实的独立物质数。来源摘要表按 `component_sources` 的来源编号去重计数，跨库来源计数不可相加作为最终分组数。A01/A02/A03 的原始结果、来源和例外继续由分页及下载接口提供。

已有研究的独立本地快照保留原运行和审批绑定；显示原批准不代表重构实现已经验收。上游三库更新后旧 A03_SELECT/A04—A07 的失效由 Workflow 判定，不自动重算、批准或替换旧报告。本轮不把代码中的导入函数表示为网页通用上传入口已完成。

## 2026-10-09 来源名称与前十展示

模块首段 `module.purpose_zh` 按绑定方案列出实际数据库名称，历史 DisGeNET 方案不替换成 PharmGKB。A03 `special.component_top` 为归档 ranking 的前十及第十个同分并列；字段保持原名，`component_top_note_zh` 解释排序与用途。完整 ranking 分页不截断，不改变科学排序、候选名额或韦恩图说明。

## 2026-10-09 分库上传接口

A01/A02模块视图新增 `source_uploads`（历史及回收站只读）：`enabled`、`disabled_reason_zh`、`expected_a00`、`expected_run`、`expected_staging`、`note_zh`、`can_process`、`process_reason_zh`、`sources`。sources各项包括database、label_zh、status_zh、formats[{value,label_zh,accept,template_url}]、hint_zh、uploaded_name、sha256、download_url；全部由后端给出。

- GET `.../modules/{mid}/sources`：当前分库入口及资料状态。
- GET `.../modules/{mid}/sources/{database}/template?format=...`：该库该格式模板；A01为官方原始资料ZIP包装规范及字段示例，A02复用原解析器的字段模板。
- GET `.../modules/{mid}/sources/{database}/file`：当前研究绑定的原始资料，先核验归档指纹。
- POST `.../modules/{mid}/actions/upload`：multipart/form-data，一个upload文件（最多16MiB，整包17MiB）。字段database、format、encoding、query、retrieved_at、version、source_url、reason、expected_a00、expected_run、expected_staging、confirmed=yes；字段非空及格式需校验。令牌、Origin和Host要求保持不变。立即返回202 `{task,created,message_zh}`，解析和归档在后台科学任务中执行。
- POST `.../modules/A01/actions/process_sources`：JSON `{expected_a00,expected_run,expected_staging,reason}`，完整三库包及HGNC依据齐备后，后台沿用现有算法生成新的待复核A01。未知身份不继承历史例外，缺资料/映射依据明确失败。

A02上传通过现有run_disease单库替换入口产生新候选，不自动批准或标准化。A01上传先按库校验并版本化留存，原结果保持；页面明确提示上传资料尚未进入结果。三库整理为用户另行触发的操作，绝不因上传而后台代签。历史文件只追加；同研究已有活动任务时拒绝第二次不同写操作。任务保存私有输入以支持失败重试，不向公共Task或日志输出上传内容。

## 2026-10-10 A04双分支展示

A04.dual.1新增`special.ppi_dual`：`{version, thresholds, degree_rows, bc_cc_rows, counts, note_zh, network_note_zh}`。rows分别来自归档`degree_top10`、`bc_cc_top15`，均为第二轮排名含边界并列；空数组代表真实空候选。thresholds来自`dual_thresholds`，counts含两分支两轮数量。BC/CC平级，分别用平均名次处理同值，再取两项名次平均；原始指标不相加。完整四轮名单、排名和指标继续通过既有明细接口提供。旧`ppi_top`保留历史第一轮含义，新版不同时输出该键。网络方案尚未确认时只显示说明，不输出正式新图。新双分支不提供旧`round1`别名供对接使用；对接来源待用户决定。

## 2026-10-10 用户确认第一轮网络及实际A04计算

A04.dual.2沿用双分支阈值，新增归档degree_round1_top10（第一轮Degree排名前十及边界并列）；旧degree_top10仍指第二轮，历史dual.1不变。special.ppi_dual新增degree_round（1或2）、network（null或{url,caption_zh}）；新版degree_rows来自degree_round1_top10，BC/CC仍来自第二轮bc_cc_top15。network.url只绑定本次结果files内的已核验PNG。

ModuleView新增ppi_run（A04且非历史时）：{enabled,disabled_reason_zh,expected_a03,expected_a04}。POST /studies/{sid}/modules/A04/actions/run_ppi JSON {expected_a03,expected_a04,reason}：先核验当前已批准A03及旧A04编号，再提交后台a04_ppi任务；任务入科学写锁后再核验。仅产生A04，不运行A05/A06、不代签结果；旧版保留。session.capabilities新增ppi_compute=true。失败重试仍使用原版本绑定，已过期时须刷新重新提交。

A04专用任务a04_ppi完成后停在A04。助手修复图件时可通过私有任务payload提供reuse_source_run，必须等于expected_a04，且原run同研究、同A03；使用指纹核验的原始STRING包归档新A04版本，不覆盖旧文件。公开页面按钮默认重新获取来源，不提供该私有参数。图元数据采用degree_network单行平面表，与结果files中的SVG/PNG指纹绑定，遵守既有表格契约。

## 2026-10-10 圆形第二轮Degree图（用户认可）

A04.dual.3保留dual.2筛选及表格口径，仅新增degree_network_rule=A04.degree_round2_circular.1。special.ppi_dual新增可选network_round=2；degree_round=1仍说明Degree表来自第一轮，不用于描述图。图展示degree_round2全部候选和真实诱导边，degree_top10（第二轮前十含边界并列）标红，其余蓝色。network.url仍来自本次A04已核验PNG。历史dual.1/2契约和归档保持不变。

## 2026-10-10 待核验事项优先展示

focus各项新增可选source_table，指定已归档明细表的入口。A04身份项source_table=identity_issues；special新增ppi_identity={total,source_table,note_zh,rows:[{target_id,symbol,returned,reason_zh}]}，rows逐项来自本次已核验归档identity_issues，不重查、不修改身份、不推算处理状态。存在待核验明细时在标题后优先展开，用中文标签显示；点击本项只读查看证据及同运行的已核验下载文件。历史版绑定历史run，保持只读。上传/审核权限、身份授权范围、模块通过门控不变。


## 2026-10-10 身份方案确认与应用

ModuleView新增identity_plan：{enabled,disabled_reason_zh,expected_a03,expected_a04,expected_decision_id,latest|null}。latest只读取Workflow指纹索引中的人工决定及绑定的新A04结果，包含reviewer、note_zh、check_ids、omit_ids、applied_run_id、pending_count、status_zh。历史页只读取原run.inputs.identity_authorization，不提供提交。

POST .../modules/A04/actions/identity_plan：{expected_a03,expected_a04,expected_decision_id,reviewer,note,check_ids,omit_ids,confirmed:true}→202 {task,created,message_zh}。选项只能来自当前身份问题清单；omit_ids是用户明确允许“全部官方稳定编号补查均成功无命中时，仅本次PPI暂不采用”的子集，缺编号、请求失败、编号冲突均不能因此移除。核验人和说明必填，不预填代签。安全要求保持；同研究活动任务拒绝重复提交。后台通过IdentityWorkflow公开方法，在统一写锁内向研究decisions/A04_identity/追加决定并更新manifest.identity_decisions索引。失败重试沿用同一决定编号，不追加重复决定。

新的A04.identity_apply.1冻结人工方案与原A03/A04归档指纹；科学筛选、身份匹配规则和图表顺序沿用dual.3。唯一一致的稳定编号才能采用；原名称返回STRING编号与稳定编号冲突仍失败，不改写原始名称返回。确认的是补查及有限处理方案，不是已核实全部身份或模块通过；剩余问题继续门控。任务失败保留决定和旧结果，成功新增待复核A04，不运行A05/A06。科研结果仍经独立复核。

补查请求及原响应（含失败前已经返回的原文）经Workflow公开方法追加至decisions/A04_identity/，manifest.identity_evidence仅记录文件指纹；不完整取证明确error_zh，不能作为成功空响应。latest新增evidence_url、error_zh。GET .../modules/A04/identity_evidence/{evidence_id}仅下载本研究索引登记且指纹完整的原文；不能指定任意路径。历史页只展示原决定的证据。

同一A03的逐项补查保留已应用的人工范围，新选择追加；决定记录引用原已应用方案，旧运行继续按原决定独立复算。再次计算A04沿用当前结果已绑定的同上游方案，不重复签署；更换A03不继承。

## 2026-10-11 A04复核后的方案状态文字

identity_plan.latest.status_zh在方案已应用且绑定A04被Workflow判定已批准时显示“已应用，A04已通过复核”；未批准仍显示待独立复核，保存未应用仍显示任务结果提示。不新增字段、不改变批准或门控；该文案不由任务成功直接推断批准。

## 2026-10-11 KEGG排除应用后才展示

ModuleView.enrichment_display新增kegg_ready:boolean与kegg_reason_zh:string，由已归档排除确认、最新决定是否已应用和活动任务给出。未确认范围、决定待应用或任务进行中时，special.enrichment_graphs不含kegg，enrichment_display_tables不含kegg_p_top10/kegg_count_top10；GO及完整追溯资料保留。前端本地勾选发生改动时临时隐藏KEGG图表，恢复原选择或新归档应用后解除。原图和统计不覆盖，不重算ORA/BH，不自动批准。

## 2026-10-11 A05第三版紧凑展示

原字段及确认请求契约保持，A05.display.3仍输出同源enrichment_display_tables及enrichment_graphs。前端将Description、description_zh分列，疾病核查25条分页；reason_zh仍完整归档并可展开。接口不重算BH、不改变排除或审批。专业报告第19版同步列序，旧报告继续按旧配置校验。

## 2026-10-11 A06两梯队候选（用户确认）
ModuleView新增docking_candidates，当前A04/A06_PREP/A06提供，历史页为null：
{enabled,disabled_reason_zh,expected_a03,expected_a04,expected_a04_review,data|null,preparation_note_zh}。
data为不可变A06.candidate_groups.1归档：group_id、source_runs、source_review、source_result、rule_zh、note_zh、degree_top15、group_a、group_b、counts；各行保留HGNC、symbol、degree、bc、cc并增加evidence_group。
POST .../modules/{A04|A06_PREP}/actions/docking_candidates：JSON {expected_a03,expected_a04,expected_a04_review,reason}→202后台a06_candidates任务；只取已批准A04第二轮归档名单，保留边界并列，不重算PPI、不下载结构、不启动Vina、不代签。
GET /studies/{sid}/docking_candidates/{group_id}：仅下载本研究索引中的指纹文件。
A=Degree第二轮前十∩BC/CC第二轮前十五；B=Degree第二轮前十五去除A；身份按HGNC。A/B是本项目候选证据分组，与结构质控和临床证据等级独立。更换A03/A04或撤回/重签A04后旧分组不可作当前输入；旧归档和批准保留。候选归档不使旧A06_PREP/A06自动恢复有效。

当前A04已有有效候选归档时，focus不再显示旧“对接来源待确认”，图注改为已归档A/B规则及独立结构质控提示；历史页及尚无分组时原提示保留。科学summary中的历史未定记录不回写。

## A06两遍方案及成分选择（2026-10-11）
新增ModuleView.compound_selection及docking_preparation：只读当前来源、草案、资料状态和人工方案，不推算科学成功。
POST /studies/{sid}/modules/A03_SELECT/actions/selection：{expected_a03,expected_select,selected,manual_supplements,reviewer,reason,confirmed:true}，后台a03_selection调用既有选择规则，生成待复核版本，不自动批准。
POST /studies/{sid}/modules/A06_PREP/actions/two_pass_plan：{expected_source,expected_plan_id,confirmed_target_ids,reviewer,note,confirmed:true,plan}，后台a06_plan仅保存A06.two_pass.plan.1。plan含policy_version、compounds、receptors、package_id、pymol_executable；每受体保留first/second结构方案及原因，第二遍实验/AlphaFold，核查项不足不可批量确认。
POST /studies/{sid}/modules/A06_PREP/actions/material：{expected_source,compound_id,cid,name,content_base64}，仅独立归档用户提供的来源SDF，身份待后续准备核验，不生成三维构象、不自动批准。
以上写入口均核对当前研究、批准来源、过期/历史/回收站/任务忙碌，使用原令牌和同源保护。计算入口继续关闭；保存完整方案不表示严格质控或对接成功。

POST .../modules/A06_PREP/actions/check_two_pass：{expected_source,plan}→{items:[{target_id,valid,bulk_allowed,reason_zh}],calculation_started:false}；无写入，只校验完整当前受体草案。valid只表示字段/来源满足人工确认要求，不能显示为科学通过。明确NA项valid=true且bulk_allowed=false；未提供资料/格式失败两者均false。
后台任务payload沿用manager既定字段，重试使用同一内部plan_id，已保存同一请求不重复追加；更换来源/方案后旧请求阻断。结果契约需同源input_key、Vina版本和完整组合覆盖；completed必须Top-1及实际归档姿势指纹通过，NA须null评分和原因。本轮未新增真实计算入口。

## A06成分核查与矩阵展示 v1
ModuleView新增docking_review（A03_SELECT/A06_PREP/A06当前页；历史页null）。
字段为enabled、reason_zh、review_id、proposal（研究级不可变资料；schema_version、study_id、binding、compounds、excluded、display、source_files、note_zh、planned_pairs）、matrix（status_zh、ready、heatmap/table的rows/columns/cells、full_pair_count、score_range）。
compounds逐项包含compound_id、name、name_zh、cid、herbs、intersection_count、main_rank、identity_prechecked、identity_state_zh、source_3d_state_zh、manual_reason_zh、evidence_zh。预核对不表示人工批准；数据缺失/冲突不可全选为已核对。
display记录heatmap_compounds/heatmap_targets/table_compounds/table_targets以及A优先、Degree降序、HGNC编号稳定展示的规则；完整受体仍保留，展示裁切不改变计算范围。
selection请求兼容旧字段；存在本轮草案时须额外传expected_docking_review，API与后台均核验草案编号、源版本及身份预核对资格，拒绝旧草案和未核实身份。保存仍生成待复核结果。
草案通过Workflow公开方法在写锁内追加docking_review_records；不改current/runs/reviews，不签署身份、不执行科学工具。结果适配仅接受当前批准成分与完整A/B受体、同源准备输入和完整结果契约，检查真实Top-1姿势指纹；无本轮评分仅显示待计算。
新矩阵科研单蓝渐变，越负越深；NA灰色，不填零，不隐去无评分行列。旧热图规则及历史版本保持。
可选proposal.acetic_trace提供当前来源冲突对照（bulk/detail/official）、归档计数与逐行trace；网页只读显示原始基因、来源条目、HGNC映射及当前交集成员，不重新归属靶点。planned_pairs保存全部待确认组合，评分为null；matrix.result_version、score_range、cells.color/text_color仅从同一有效结果生成。


## A06受体资料核查包（2026-10-11）
ModuleView.docking_preparation新增可选metadata_review：{review_id,created_at,note_zh,execution_allowed:false,approval:null,compounds,receptors}。compounds为当前已批准成分的中文名、CID、来源三维状态和指纹证据；receptors为完整当前A/B名单、UniProt、官方身份说明、第一/二遍待核查状态、候选实验结构摘要和历史失败。候选含PDB、官方链接、方法、分辨率、目标作者链及序列长度、共晶组分及作者链；这些仅为元数据，不能据此显示严格/探索质控通过。检索范围和未核实的突变、结合域、配体定位/共价关系必须说明。
核查包通过Workflow.save_receptor_review公开方法在写锁内追加至decisions/A06_receptor_review，并由manifest.receptor_review_records索引。绑定当前source_key，核对已批准名单、A/B、来源文件、禁用执行及未批准状态；历史/回收站不提供操作，上游变更后旧包不展示。结构准备、P2Rank、AlphaFold模型、重对接和Vina均不触发。原two_pass_plan与material写接口不变。


## A06矩阵配色第二版（用户于2026-10-11确认）
新增A06.matrix.display.2：冰蓝#A7D5E5→莓果红#B7326B，越负越偏莓果红，NA灰色。旧display.1单蓝版本保留。matrix新增palette{id,high_color,low_color,na_color,unit,label_zh}及heatmap_svg:string|null；SVG使用同批完整score_range，含实际色标、单位与NA说明。无真实评分时SVG为null；恒值使用中间色，全部NA不编造数值范围。前端只显示服务端色值/说明并下载同源SVG和PNG，不推算科学评分。
通过Workflow.save_matrix_display公开方法只追加展示配置至decisions/A06_matrix_display和manifest.matrix_display_records，绑定已批准成分和当前source_key、核查草案编号；展示窗口保持，名单和审批不变。过期配置不回退旧配色，明确待重新绑定。导出与专业报告A06章节共用matrix_exports和matrix_report_section，验证同批矩阵与色值。


## A06核查草案暂存（2026-10-12）
POST .../modules/A06_PREP/actions/two_pass_draft：{expected_source,expected_plan_id,expected_draft_id,plan,checked_target_ids,reviewer,note}→201 {draft,message_zh}。允许来源绑定且身份范围完整的未完成字段，只暂存人工输入，不生成运行、不批准方案、不启动计算；核验人/说明可暂空。服务端追加decisions/A06_two_pass_draft和manifest.two_pass_draft_records，保存原请求，重试内容一致才返回旧记录。未知字段、质控/评分/执行字段、跨研究、旧来源或过期草案均阻断。
docking_preparation新增expected_draft_id及draft|null（draft_id、created_at、reviewer、note、checked_target_ids），plan优先显示与当前来源及完整方案版本一致的最新草案。刷新可恢复填写与合法逐项勾选；整体确认框永不自动恢复勾选。新完整方案使旧草案成为历史；上游改变后不回退早期草案。
存在有效草案时，two_pass_plan确认请求必须额外携带expected_draft_id并与最新版本匹配；无草案的旧请求仍兼容。完整确认、结构质控与结果批准保持原规则，草案不因字段齐全被视为已确认。


## 2026-10-12 A06集中核对与一次提交
现有check_two_pass响应和docking_preparation新增confirmation：{ready,receptor_count,compound_count,planned_pair_count,normal_target_ids,pending,unavailable,execution_allowed:false,note_zh}。pending与unavailable逐项为{kind,id,label_zh,reason_zh}，使用既有完整校验器生成；字段齐全不是结构质控通过。确认窗口只在用户主动勾选整体核对后提交正常受体完整ID；明确NA项在同一窗口逐项核对，不参与全选。未完成时只显示缺口，可保存草案，不提交完整确认。原完整方案请求、研究版本、令牌和独立审批保持。


## A06获准来源原件核查（2026-10-12）
docking_preparation新增source_review（当前同上游A06.source_review.1原件及只读核查，approval:null、execution_allowed:false）。既有metadata_review显示已取同身份三维及原始坐标清点，不能显示当前质控通过。source_review.choices仅是需用户核对的替代构象或路线建议，未选择不代填。
草案和完整方案请求新增可选expected_source_review_id；当前有来源原件核查包时必传并核对，旧无核查包请求兼容。原件更新使旧草案或完整方案不再作为当前确认，历史保留。所有研究写入仍经公开Workflow，当前source_key、名单、来源CID、原件字节及版本全部核对。资料获取授权不等于方案确认或真实计算授权。

GET /studies/{sid}/source_reviews/{review_id}/files/{file_key}仅下载该研究索引内已归档且指纹完整的原件，无任意路径参数；旧版本可只读追溯。source_review.choices为{kind:altloc|route,target_id,symbol,pdb_id,round:first|second,options,reason_zh,proposal?}。原始缺失记录仅供核查，不按数量自动判定口袋完整。

## A06真实结构质控任务（2026-10-12用户明确继续）

新增私有任务a06_quality，仅接受当前研究已登记A06.quality.authorization.1授权与方案、来源版本，执行来源三维准备、受体准备、P2Rank与参考配体Top-1重对接。没有新增网页启动或批量评分端点；不能通过hidden参数解锁研究成分对接。任务经Workflow生产入口发布A06.two_pass.execution.1新版A06_PREP，预测口袋证据未人工确认及环境待核定时handoff_blocked保持；不代签结果。旧科学结果校验保持。任务进度、日志、失败、取消和版本过期按既有接口处理。

DockingPreparationInfo新增quality_status_zh：仅从绑定当前已确认方案的真实A06_PREP归档或活动任务读取。未完成、过期与已归档分别说明；前端不根据已确认方案推算质控通过。

## A06扩大覆盖与集中采用（第二版）
ModuleView新增docking_coverage：{enabled,disabled_reason_zh,expected_run,expected_source,campaign_id,expected_decision_id,confirmed,draft,rows,counts,batch_docking_allowed:false,note_zh}。counts分别为strict、exploration、unavailable、receptors，技术资格与人工采用分开；rows包含target_id、symbol、candidate_grade、ppi_order、pdb_id、rmsd_A、quality_zh、status_zh、reason_zh、eligible、adopted、selected、spec及可折叠的attempts摘要。仅完整证据可确认；第一遍失败不靠更换同一结构口袋绕过。
POST .../modules/A06_PREP/actions/coverage_selection：{expected_run,expected_source,campaign_id,expected_decision_id,selected_target_ids,reviewer,note,confirmed:boolean}。false仅追加草案并刷新恢复；true需核验人、依据和非空可用范围，追加人工采用决定及A06.coverage.confirmed.4准备版本。未解决项只阻断对应组合；主要五仍需至少五个已采用严格受体。采用确认不批准结果、不运行批量评分。安全、写锁、忙碌/回收站/来源与版本检查均保留。
新增私有a06_coverage任务：仅用研究索引登记的A06.coverage.authorization.2执行独立候选资料与结构质控，产生A06.coverage.execution.4。技术候选全部待采纳，旧证据和失败历史保留；没有公开批量计算端点。

采用确认POST返回202后台a06_coverage_confirm，接口只读校验、后台由完整校验器产生新准备版本；草案返回201。任务失败保留原技术归档，旧请求不自动重签。

第四版追加最终证据审计：原位点相关范围与必要伙伴/金属再核对，单体模型不能绕过环境；当前输入包含实际采用证据及历史完整包指纹，失败历史不回写。conditions给出main_results、exploration与prepared_pairs，均由后端归档读取。只读请求内复用已核验不可变数据，写入/下一请求重新核验；旧窗口expected_run先阻断，不重复构造整张页面。

## A06独立全覆盖试算（2026-10-13用户明确授权真实计算）
新增私有a06_trial后台任务，通过TrialWorkflow.begin_trial/finish_trial独立账本发布15×15真实试算；不更换current、正式结果或reviews。绑定已批准来源、准备、方案、来源原件与展示名单；失败重试沿用私有请求并重新检查版本。ModuleView.docking_trial只读返回225格、服务端色值、两位小数展示所需原始精度、组合/区域进度、受体处理证据及索引下载。未完整完成时无评分矩阵。GET files/trial_ID.index仅访问该研究已完成试算索引且指纹匹配的文件，无任意路径。POST actions/trial_review仅接受trial_id、reviewer、note、confirmed，保存独立核查；不代签正式A06、不运行计算，回收站/过期/忙碌阻断。页面支持现有任务日志、取消、失败重试。


## A06扩展试算交接（2026-10-14）
当前A06/A06_PREP新增可选trial_handoff：{run_id,active,trial_id,review_url,note_zh,reviewer,note}。仅A06.trial.handoff.1当前运行提供，历史页面不提供。review_url跳转本批A06；reviewer/note取绑定的已确认试算核查，仅预填不预选决定。新A06依赖显示其实际parent_runs（A03/A03_SELECT/A04），全局旧依赖契约保持；正式可复核性仍来自内核。


## 本批准备关联（2026-10-14）
ModuleView新增可选trial_preparation，仅当前A06_PREP页提供：{link_id,created_at,active,read_only,reason_zh,a06_run_id,trial_id,result_url,source_url,reviewer,reviewed_at,note,a06_reviewer,a06_reviewed_at,receptors,compounds,history_rows,legacy_run_id}。数据来自Workflow核验的独立A06.trial.preparation_link.1关联及同批归档；不更换current或新增科研reviews。历史页面不提供当前关联。GET files/{prep_link_id}.{index}仅下载研究索引内关联的files，逐字节验证；包括原件、准备文件及原核查记录，无任意路径。
新增状态scope_confirmed，中文“准备范围已核查（扩展试算）”；不等于approved，不开放复核或自动继续。原准备状态留在历史区。导航、标题与待办均使用Workflow视图；关联失效为stale，不自动沿用。progress新增completed（正式批准及本批准备已核查的关口数）与scope_confirmed，approved保持原含义；仅有关联的研究显示完成关口及数量明细。
## 2026-10-21 自动结果完整功能接续

自动协议页面只返回连接/执行摘要，不展开全部证据；分页 GET `/studies/{sid}/automatic_docking/{batch}/pairs`、`files` 和 `pairs/{pair_key}` 分别读取评分清单、文件索引和单组合完整依据。索引与结果身份仍核验，实际文件下载逐个核验SHA256，写入/复核仍完整核验。历史可只读访问同研究批次；不能借用其他研究批次。
GET 同批 `/matrix` 返回标准库生成的中英重点图SVG与完整矩阵；查询参数 compound_ids/target_ids 只改变显示选择。POST `/modules/A06/actions/automatic_display` 接收 expected_a06、batch_id、compound_ids、target_ids，经后台归档 PNG/SVG/Excel/CSV 展示修订，不改评分/批准。GET `/automatic_displays/{display_id}/files/{index}` 仅下载本研究展示索引登记且指纹一致的文件。
新增技术状态 prepared（准备已归档）、execution_confirmed（执行范围已确认），只取本批连接及执行归档；不表示A06_PREP科研批准、不开放该页复核。A06页只查看结果/出图/复核；A06_PREP页连接并一次确认，旧运行表单默认收起。报告适配新增独立版本，冻结第24版保持。

## 2026-10-21 扩展范围接续

A03_SELECT.compound_selection新增current_manual_supplements（回读同运行已保存的逐项理由）及extended_scope，只读同研究A03、当前名单及身份待补信息，返回前十五（含边界并列）草稿和逐项补充理由。加载不调用POST，保存仍使用原selection接口。automatic_docking新增scope；未复核完整范围时新第三版连接/执行禁用，API及后台重复检查；既有批次结果照常追溯。换名单后的continue不能等待失效旧A06复核，改为提示前往A06_PREP连接并一次确认。旧科学规则及历史授权不改变。
## 2026-10-28 A06 可人工整体复核的准备版本

GET `/studies/{sid}/analysis-plan/a06-reviewable-preparation` 只读返回 supported/enabled/execution_available:false/current_run_id/expected_input_id/state/reason_zh。只在第二版参考准备归档完整、上游和固定输入当前有效且 ready_pairs>0 时 enabled；全 NA 不放行。
POST 同地址严格接受 `{expected_preparation_run_id,expected_input_id,request_id,reviewer,note,confirmed:true}`；request_id 前缀 reviewprep。同编号同内容且原版本仍有效时返回 200 原运行；新请求返回 202 后台 `a06_plan_reviewable_preparation`。后台独立复算原准备科学证据并发布 `A06.plan_reviewable_preparation.1`，保留所有固定组合、NA及原件；summary.reviewable=true、handoff_blocked=false、scored_pairs=0、execution_available=false。该变化只开放原有人工模块复核表单，不提交批准。
新准备沿用原人工 review 接口和 expected_review_id 并发规则；qualified/can_enter_review 仅表示可人工决定。评分保持关闭，旧自动计算区隐藏，保存并继续/手动继续/后台 continue 均不得进入旧评分协议。历史准备、结果与 reviews 不回写。新版本网页字段 reviewable_preparation 为上述 GET 响应；ReviewPacket.can_enter_review 改为 boolean。
## 2026-10-28 新方案正式评分协议

GET `/studies/{sid}/analysis-plan/a06-scoring` 只读返回 `supported,enabled,execution_available,protocol_version,blockers,state,reason_zh,current_run_id`；有效准备时另有 `expected_preparation_run_id,expected_preparation_review_id,expected_input_id,parameters,pair_count,ready_pairs,na_pairs`，已归档时有 `result_run_id,summary`。仅 `A06.plan_reviewable_preparation.1` 的当前有效人工批准可执行；后台忙碌或未配置固定科学工具时 enabled=false。已成功同批结果不自动重跑。
POST 同地址严格接受 `{request_id,expected_preparation_run_id,expected_preparation_review_id,expected_input_id,expected_a06_run_id,operator,note,confirmed:true}`；request_id 前缀 scoreq，expected_a06_run_id 为当前运行或null。无参数/评分/路径覆盖。新请求返回202后台 `a06_plan_scoring`；同编号同内容且当前成功归档返回200原run；改内容、过期版本、回收站、未批准、失败/中断原请求拒绝。失败或中断的已落盘资料保留，明确重试使用新请求和当前A06编号，不自动恢复。
后台运行 `A06.plan_scoring.1`，固定Vina1.2.7、原方案参数、已准备配体/受体/搜索盒，一CPU顺序计算，单对1800秒超时。完整固定组合保存NA/failed/completed；仅原文Top-1评分有效，NA/失败评分为null，不补位、不用历史分数。全部可用组合失败时结果outcome=failed、任务失败且原诊断保留。成功结果仍需原人工A06复核，不代签，不接旧报告协议。
GET `/studies/{sid}/analysis-plan/a06-scoring/export.csv` 下载当前A06评分事实包绑定的完整CSV，下载前核验原结果及文件指纹，无客户端路径；历史仍从原运行附件查看。ModuleView 的可选 `plan_scoring` 使用上述GET字段；A06新增表 `plan_scoring_pairs`，列compound_id/target_id/state/score/quality/reason_zh/input_key/execution_path/state_zh，科学数值仅后端生成。接口统一沿用原令牌、状态码和任务并发规则。只读预检仍始终allowed=false，不因正式入口接通而执行。
## 2026-10-28 第二轮代码复查补充

新版评分GET资格、评分闸门、模块页面和POST执行共用同一工具预检：配置目录及固定Vina1.2.7文件须实际存在。HTTP仅检查文件存在，不启动工具；版本仍由科学子进程验证。缺少工具或后台忙碌时enabled/scoring_allowed/execution_available关闭，POST返回409 GATE_BLOCKED且不创建任务。每次评分执行预检只使用一次任务状态快照，避免任务刚结束时误报未配置工具。
可选A06复核材料包核查失败时，追溯摘要仍可返回，a06_review_packet_available=false；原始必要文件指纹失败继续按原规则拒绝，不把资料缺损当成有效结果。独立评分校验明确拒绝以布尔值冒充评分、计数、模式号或返回码，缺命令索引按契约错误拒绝。
## 2026-10-28 新方案A05实际富集

GET `/studies/{sid}/analysis-plan/a05` 仅读取supported/enabled/blockers、expected_a00/expected_a03/expected_a05/expected_plan_id、parameter_hash、实际A05参数、completed/message_zh。须当前A03批准、当前登记方案及有效固定science_rscript；未选择GO或KEGG明确不纳入，不冒充零显著。POST同地址严格接受`{expected_a00,expected_a03,expected_a05,expected_plan_id,reason}`，无路径/参数/统计结果/批准覆盖。202提交a05_plan_enrichment，过期409、回收站423、字段422、缺工具/忙碌409且不建任务。后台实际使用A05.plan_enrichment.1与固定R包执行方案GO/KEGG、min/max条目、BH严格阈值、图/表各自前列数；各族独立校正、原背景和完整统计保留。结果须独立复核，不运行旧continue/A07，旧A05保持。运行开始固定方案，后加草稿不改变本批；A00/A03/A05或上游批准变化拒绝发布。ModuleView可选plan_a05仅当前A05提供，参数与表/图由后端归档生成。

补充：A05资格返回applicable。合法方案同时不纳入GO/KEGG时applicable=false、enabled=false，blockers明确富集不适用，不启动R、不生成虚假的空结果；后续报告须说明。R非零退出或超时的完整输入/输出/日志另存本数据根environments/A05_plan_failures/独立attempt目录，旧结果保持。新A05即使来自早期显式方案研究，也不能由原continue/A07接管；历史人工展示、分类/译名决定及报告仍按原协议，新自动报告整合另行实现。

## 2026-10-28 新方案A01正式任务入口

GET `/studies/{sid}/analysis-plan/a01` 返回 `A01.plan_tasks.1` 资格：supported/acquire_enabled/publish_enabled、分别的blockers、expected_a00/expected_a01/expected_plan_id/expected_staging、parameter_hash、parameters(ob_min/dl_min)、missing_databases/processed/message_zh。只读取和核验当前方案及原件；不联网、不发布。历史固定研究不启用。
POST同路径`/acquire`严格接受 `{expected_a00,expected_a01,expected_plan_id,expected_staging,databases,reason}`；`/publish`接受去掉databases的同字段。无路径、参数、分数或批准覆盖。当前A00须批准，草稿与来源须当前；发布还须三库和共同HGNC依据。返回202后台`a01_plan_acquire`或`a01_plan_publish`，活动任务409、旧绑定409、回收站423、无效字段422。后台再次核验，采集只暂存，发布走A01.plan_publication.1完整科学校验器；不批准、不触发A02/A03或旧continue。部分采集失败任务失败，成功库与失败轨迹保留；来源已变化时刷新后按当前绑定重新提交所需库。运行中追加草稿不更换已开始采集的门槛，尚未开始的过期任务和重试拒绝。ModuleView可选plan_a01仅当前A01提供，忙碌时两操作关闭。

## 2026-10-28 标准及个性化新建研究

POST `/api/v1/analysis-plans/creation/preflight` 严格接受 `{intake,specification}`。intake仅含formula/herbs/disease/mesh_term/mesh_id/operator/analysis_purpose；specification沿用统一方案编译契约。先验证字段再向NLM官方核对身份，核验本机共享资料原件/清单，明确研究专属来源尚未提供。不创建研究或任务；运行目录保存30分钟预检凭证。返回schema_version=ModuleA.plan_creation.1、preflight_id/input_hash/plan/mesh_verification/materials/expires_at/can_create:true/execution_available:false/message_zh。共享资料缺失允许建档，但不能作为执行就绪；客户端不能上传“已通过”状态或覆盖目录/物种/保护规则。
POST `/api/v1/analysis-plans/creation` 严格接受 `{request_id,preflight_id,expected_input_hash,confirmed:true}`；request_id前缀plancreate，preflight_id前缀creationcheck。重新核对凭证时效、内容指纹和资料变化。通过后由Workflow同一写锁发布A00及初始方案、登记实际预检记录；无reviews、无后台任务。返回201 `{study_id,run_id,plan_id,created:true,mode,parameter_hash,directory,execution_available:false,message_zh}`，相同请求已建档返回200原研究/初始方案；换凭证或输入返回409 CREATE_CONFLICT。重启、运行目录丢失或研究后续方案变更均不重复建档或覆盖旧版本。
GET `/api/v1/studies/{sid}/analysis-plan/creation` 返回本协议建档的初始/当前方案及创建时资料预检；旧研究返回null。GET同地址`/export.json`返回下载JSON（只读原研究索引及指纹）。ModuleView可选creation_plan仅在当前A00提供。旧POST /studies及参数预览保持原行为。新研究A00复核、手动continue、批量复核接续和后台continue均不自动调用旧固定参数编排；A01/A04必须采用新方案协议，A05新适配未完成时拒绝旧协议。新研究A01上传原件仍可用，旧获取/整理控件禁用，相关API及后台拒绝旧固定OB/DL操作。页面明确只建档，自动全流程另行实施。
## 2026-11-01 A05独立Unicode输出与展示协议

新明确可恢复批次将enrichment_protocol=A05.plan_enrichment.2固定到批次；原批无此字段继续第一版，同请求重试不升级。第二版只用R的Unicode字符串常量修复skipped原因，原科学R/第一版契约不改。A05模块展示识别两版统计；第二版按独立A05.plan_display.2及A05.plan_display_source.2消费原分类、词典和相同字段形状，第一版展示规则和已归档结果保持。现有展示准备/确认与只读追溯按实际统计分派，人工决定不自动确认。系统A05不显示不适用的独立plan_a05旧人工执行表单，后续指向统一执行；分类展示资料与独立复核保留。数量说明按实际系统权限明确“系统校验不表示人工批准”，不把未签署的A03称为已人工批准；普通人工流程文字和操作保持。

后台新增公开Workflow.revise_analysis_plan_a05_text与plan_a05_text_revision任务，可明确离线修订已有第一版系统结果；尚无新增HTTP写入口或专用网页按钮。完整追溯追加plan_decisions.a05_text_requests/a05_text_receipts/a05_text_failures，保留原统计、请求、实现及各次失败。独立新A07报告按真实第二版统计及对应来源快照生成，不将文字修订视为人工科研复核。

## 2026-11-07 同批准备依据、来源口径与Top-1原字节下载

本日追加报告归档恢复协议ModuleA.report_archive_repair.1。仅公开Workflow.restore_analysis_plan_report_archive接受已明确授权的精确原备份字节；无新增HTTP写入口。先登记并保全批注版和原备份，按原SHA原子恢复报告位置，原run/result/current/reviews及原指纹不变。正文、表格或图片不同的文档不能当作仅批注自动恢复；损坏备份、旧绑定、并发新修改均阻断。中断只能明确重试，GET不恢复。

报告history.downloads在原双Word之外追加已登记“用户批注版（保留N条批注）”。GET `/api/v1/studies/{sid}/analysis-plan/reports/{rid}/annotations/{repair_id}`只返回本研究完成恢复回执对应的批注原字节，逐件核对原报告/备份/批注及锚点指纹；错运行/未登记404，损坏沿现有503 ARCHIVE_UNAVAILABLE，原Host和只读下载规则保持。完整追溯追加report_archive_repair_requests/report_archive_repairs；恢复和保留批注不是科研复核通过。

报告GET/generate/files沿原地址兼容两版：当前第三版结构或已有A07.plan_report.2选择二版生成资格，history合并两版原回执，files各按原协议逐件核验。浏览器仍只提交原严格报告字段；服务端给新plan_report队列payload绑定{report_protocol:A07.plan_report.2,request:原请求}，worker按该协议消费，排队后不改版。旧扁平任务payload仍一版；无GET自动生成或历史报告静默升级。

系统评分热图receptors可选display_name来自本批固定受体symbol；name仍为原稳定编号，与cells.receptor关联。表头、转置和格子详情优先显示display_name，缺失时沿用name；不改变查值键、对象顺序或评分。

准备证据reference_contacts为原evidence明确登记的{chains:string[],basis_zh:string}或null。只读保留原接触链及依据，未登记时明确未知，不用目标链、参考配体所在链或无阈值的全距离表推断接触链；不补定距离阈值或改变质控。

系统准备/资格/评分模块只读兼容独立第三版及全部旧版。可选KPI分别读取原摘要source_record_count、verified_structure_count、verified_record_count、pending_structure_records；缺失省略，0保留，不按新去重重排固定对象。special.source_diagnostics保留原tables.source_diagnostics各行及object_type/object_id/failure_stage/failure_code/retryable/reason_zh，旧批缺分类时展示“未登记”，不从原因文本猜分类。

第三版source_record_count按固定候选逐项保存的original_sources原A01关系计数；verified_record_count为具备核实结构的这些原关系数，pending_structure_records为未核实原关系数。独立结构以完整InChIKey去重只用于计数。固定成分记录读取compound_count，不用16条固定候选代替可能18条原关系；补查响应不追加为新的原来源关系。

special.foundation_evidence可选，schema_version=ModuleA.foundation_evidence.1，read_only=true，integrity=verified|failed。仅核对本运行system_input_ref、原A06_PREP登记、准备/评分packet、原execution命令、输入与工具指纹、搜索盒、MODEL 1评分/原子及坐标；不重新计算。preparation保留每次候选尝试、参考配体/链、原口袋及环境核查记录和原始原因；未执行的环境核查为null，不解释为通过。scores保留完整原序组合及NA/失败原因、原始评分、来源SHA与经核验下载链接。失配时返回明确只读错误区，无构象链接，不更改状态、复核资格或历史结果。

GET `/api/v1/studies/{sid}/runs/{rid}/foundation/pairs/{number}/top1.pdbqt`及同路径`context.json`必须且仅接受expected_input_key和expected_pose_sha256两个单值查询字段。number为本批原序1基组合号；不接收路径、URL、姿势号或参数覆盖。下载前回读本研究原运行/准备/固定输入与所有评分证据，前后复核登记绑定，原pose缓冲区再次核验SHA。仅已完成且核验一致组合允许下载，NA/失败409、陈旧绑定409、未登记404、额外字段422。Top1为原Vina文件MODEL 1至ENDMDL原字节（保留换行），context含原pose和提取字节SHA、原评分/盒/参数/执行SHA；均内存派生、不落研究目录、不联网。历史运行按原登记读取，不用当前草稿替代。路由由server显式挂载后生效。
