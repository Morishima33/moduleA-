# 官方CSV解析验收只使用合成资料，不改真实研究。
import sys  # 引用新项目代码。
from pathlib import Path  # 定位统一源码。
import unittest  # 检查输入与历史兼容。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))  # 不引用Kimi旧代码。
from disease import parse_source, metadata  # 复用生产解析器。
from contracts import ContractError  # 确认坏输入明确拒绝。
from disease_ui import manual_uploads  # 核验两个流程方案的上传入口。

HEADER = 'Gene Symbol,Description,Category,Uniprot ID,Gifts,GC Id,Relevance score, GeneCards Link\n'  # 官方链接字段保留前导空格。
ROW = 'IL13,"白细胞,介素13",Protein Coding,P35225,1,GC05M132656,10.7000,https://www.genecards.org/IL13\n'  # 名称含逗号，不得简单切列。

def item(encoding='utf-8-sig'):  # 提供真实结构的合成元信息。
    return {'database': 'GeneCards', 'format': 'genecards_csv', 'query': 'Rhinitis, Allergic', 'retrieved_at': '2026-10-07', 'version': 'unknown', 'source_url': 'https://www.genecards.org/', 'name': 'fixture.csv', 'encoding': encoding}  # 未知完整性不能默认完整。

class GeneCardsCsvTests(unittest.TestCase):  # 科学事实和输入完整性必须同时正确。
    def test_encodings_quotes_and_precision(self):  # 验证编码、引号逗号与原始精度。
        for encoding in ('utf-8-sig', 'gbk'):  # 两种获批文本编码。
            rows = parse_source(item(encoding), (HEADER + ROW).encode(encoding))  # 完整生产解析。
            self.assertEqual(len(rows), 1)  # 不把逗号误作多行。
            self.assertEqual(rows[0]['raw_score'], '10.7000')  # 原始评分不重舍入。
            self.assertEqual(rows[0]['target_name'], '白细胞,介素13')  # 带引号字段完整保存。
            self.assertEqual(rows[0]['disease_term'], 'Rhinitis, Allergic')  # 搜索词来自实际元信息。
            self.assertEqual(rows[0]['source_row'], 2)  # 保留来源定位。
    def test_bad_inputs_are_rejected(self):  # 不从坏表推断缺失信息。
        variants = [HEADER.replace('Gene Symbol', 'symbol') + ROW, HEADER.replace('Description', 'Gene Symbol') + ROW, HEADER + ROW.replace('10.7000', 'nan'), HEADER + ROW.replace('10.7000', ''), HEADER + ROW.replace('IL13,', ',', 1), HEADER + ROW.rstrip() + ',extra\n', HEADER + 'IL13,"broken\n']  # 覆盖缺字段、重复、非有限数、列损坏与引号损坏。
        for value in variants:  # 每类都不能发布部分名单。
            with self.subTest(value=value[:60]), self.assertRaises((ContractError, ValueError)):  # 原因明确显示。
                parse_source(item(), value.encode('utf-8-sig'))  # 使用同一生产入口。
        wrong = dict(item(), database='TTD')  # 禁止跨库套用。
        with self.assertRaises(ContractError):  # 错库必须拒绝。
            parse_source(wrong, (HEADER + ROW).encode('utf-8-sig'))  # 不通过后缀猜库。
    def test_unknown_metadata_stays_unknown(self):  # 不把元数据未知变成全量。
        self.assertEqual(metadata(item())['export_completeness'], 'unknown')  # 默认未知。
        self.assertEqual(metadata(dict(item(), query_quoted='no'))['query_quoted'], 'no')  # 未加引号如实保留。
        with self.assertRaises(ContractError):  # 无效状态不能进入归档。
            metadata(dict(item(), export_completeness='guess'))  # 不允许自造含义。
    def test_manual_csv_visible_in_both_profiles(self):  # 两种新五库流程共用原生入口。
        for profile in ('A02.source_profile.2', 'A02.source_profile.3'):  # 正式与流程测试皆可复用。
            body = manual_uploads('', 'Rhinitis, Allergic', {'summary': {'source_profile': profile}, 'tables': {'source_summary': []}})  # 不需要真实研究。
            self.assertIn('genecards_csv', body)  # 不能只支持缺库测试个案。
            self.assertIn('export_completeness', body)  # 用户可以如实标未知。
    def test_refill_reuses_unchanged_approved_a01(self):  # 防止仅补疾病库却让方剂侧反复审核。
        import test_normalization as fixtures  # 复用隔离合成研究，不接触真实病例。
        from normalization import preview, publish  # 调用真实发布入口。
        from disease import run_disease  # 同生产上传版本逻辑。
        fixture = fixtures.NormalizationTests()  # 不把旧测试重复注册为本模块检查。
        fixture.setUp()  # 建立仅含一个已知基因的临时研究。
        try:  # 测试结束必须清理临时研究。
            outputs = publish(fixture.flow, fixture.sid, preview(fixture.flow, fixture.sid)[-1], 'test', '合成测试', True, True)  # 模拟初次标准化确认。
            for result in outputs.values():  # 明确模拟两侧批准，不代签真实病例。
                fixture.flow.review(fixture.sid, result['run_id'], 'approved', 'test', '合成确认')  # 使用原框架复核。
            before = fixture.flow.load(fixture.sid)  # 记录补库前A01指针。
            source = dict(item(), query='COPD', data=(HEADER + ROW.replace('IL13', 'A')).encode('utf-8-sig'))  # 新CSV仅更新疾病侧。
            run_disease(fixture.flow, fixture.sid, before['current']['A00'], before['current']['A02'], [source], '合成补库')  # 生成新A02候选。
            made = publish(fixture.flow, fixture.sid, preview(fixture.flow, fixture.sid)[-1], 'test', '补库测试', True, True)  # 按原规范发布标准化预备结果。
            self.assertEqual(made['A01']['run_id'], before['current']['A01'])  # A01不重复建运行。
            self.assertTrue(fixture.flow.approved(fixture.flow.load(fixture.sid), made['A01']['run_id']))  # 原批准保持有效。
            self.assertFalse(fixture.flow.approved(fixture.flow.load(fixture.sid), made['A02']['run_id']))  # 新A02不自动通过。
        finally:  # 不遗留测试产物。
            fixture.tearDown()  # 仅删除隔离临时目录。

if __name__ == '__main__':  # 可独立运行专项验收。
    unittest.main()  # 输出真实检查结果。
