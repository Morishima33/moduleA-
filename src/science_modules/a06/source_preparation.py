"""第三版准备的来源适配；科学准备与质控复用冻结第二版。"""
from . import plan_preparation_v2 as original
from .compound_sources_v2 import resolve, diagnosis
from .source_context import Fetcher


def connect(root, packet, folder, progress):
    """逐项请求精确官方身份；保留固定对象、实际失败阶段与全部来源。"""
    fetch = Fetcher(root, folder)
    compounds, receptors = [], []
    identities = packet.get('source_identities', {})
    for row in packet['compounds']:
        event_start = len(fetch.events)
        progress('连接成分来源：' + row['compound_id'])
        try:
            compounds.append(resolve(row, fetch, identities.get(row['compound_id'], [])))
        except (ValueError, KeyError, TypeError, OSError) as error:
            compounds.append(dict(row, state='NA', **diagnosis(error, 'identity')))
        compounds[-1]['source_requests'] = fetch.events[event_start:]
    for row in packet['receptors']:
        progress('连接受体来源：' + row['symbol'])
        try:
            receptors.append(original.receptor_sources(row, fetch, progress))
        except (ValueError, KeyError, TypeError, OSError) as error:
            receptors.append(dict(row, state='NA', candidates=[], **diagnosis(error, 'receptor_source')))
    return {'id': folder.parent.parent.name, 'compounds': compounds, 'receptors': receptors, 'files': fetch.records}


# 原参数化、候选顺序、口袋/环境和参考Top-1质控函数不复制、不改规则。
prepare = original.prepare
preparation_source = original.preparation_source
prepare_compounds = original.prepare_compounds
target_folder = original.target_folder
attempt = original.attempt
assess_plan_attempt = original.assess_plan_attempt
_version = original._version
