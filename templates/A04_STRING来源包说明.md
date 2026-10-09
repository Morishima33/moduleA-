# A04 STRING来源包说明

用途：网页A04“其他信息”中的离线导入，复用同一交集、同一版本的完整STRING来源包。不是任意边表上传入口。

来源包由本项目自动获取流程产生，存于对应研究的raw/string_<内容指纹>.json。请保留原文件；不要手改查询词或响应。原件包含schema_version=A04.source.1、string_version=12.0，以及mapping和network两部分的url、params、retrieved_at、response_text。

映射请求绑定本次A03交集的顺序和名称；网络请求绑定已核对STRING编号，限定人类9606、functional、required_score=900、add_nodes=0。导入时检查上述字段并重新计算，不凭文件名称放行。来源包只能复用于相同输入与配置；不同方剂或疾病先重新形成并复核A03。

只提供边表、缺少映射原文或版本、请求与本次交集不一致，均不能作为完整来源包。请求失败不当作空网络；未匹配不当作孤立节点。离线导入不会自动批准结果。

发布后来源、上游引用、结果表、图和运行配置分别归档；重跑生成新运行，原运行保留。


## A04.source.2补充格式
新版来源包另含identity_evidence：authorization绑定已批准研究和A03版本；hgnc_sha256指定官方快照；queries依序保存从HGNC派生的query字段和source原始请求响应。不能自行编辑授权、删除失败查询或替换原返回名。
本次A04.2运行另以inputs.identity_snapshot引用研究raw内的HGNC原件，导入/复算须具备相同快照；来源包自身不是允许任意研究排除基因的授权。旧source.1格式及历史复算继续保留。新来源不覆盖旧原始资料。
