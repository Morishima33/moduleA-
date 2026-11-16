"""新平台独立展示协议：复用冻结矩阵/配色与布局，明确新运行及本机字体。"""
from copy import deepcopy
import csv
from html import escape
from pathlib import Path
from types import FunctionType

from contracts import require
from storage import write_json
from modulea.core.bounded_evidence import file_record
from . import system_rescue_display as frozen

SCIENCE_VERSION='A06.platform_execution.1'
VERSION='A06.platform_display.1'


def renderer():
    """只在私有namespace复用原几何与科学事实映射，冻结模块常量和函数不变。"""
    namespace=dict(vars(frozen),SCIENCE_VERSION=SCIENCE_VERSION,VERSION=VERSION,
        SOURCE_ZH={'native':'本平台实际评分','original':'沿用已核验原件'},
        REVIEW_NOTE='本平台新结果仍须独立科研复核；技术工具检查不代替身份与结构质控。')
    for name in ('build_view','_drawing','heatmap_svg','_png'):
        source=getattr(frozen,name)
        namespace[name]=FunctionType(source.__code__,namespace,name,source.__defaults__,source.__closure__)
        namespace[name].__kwdefaults__=deepcopy(source.__kwdefaults__)
    original_drawing=namespace['_drawing']
    def drawing(view,*,full):
        """同一几何替换补救专用说明，新平台图件不冒充原Windows批次。"""
        geometry,items=original_drawing(view,full=full)
        items=[(item[:3]+('本平台新运行；原始构象与实际参数见执行证据，结果待独立复核',)+item[4:])
            if item[0]=='text' and item[3]=='原评分与本轮补救合并展示；固定范围保留，结果须独立复核'
            else item for item in items]
        return geometry,items
    namespace['_drawing']=drawing
    return namespace


def export(root,packet,folder,*,font_path):
    """同一事实生成完整/焦点PNG、SVG、CSV与JSON；缺中文名称不填造译名。"""
    from PIL import ImageFont
    require(packet.get('schema_version')==SCIENCE_VERSION,'新平台图件科学协议不同')
    functions=renderer();view=functions['build_view'](packet)
    folder=Path(folder)
    require(not folder.exists(),'新平台图件尝试目录已存在，禁止覆盖')
    font=Path(font_path);require(font.is_file(),'请明确可用中文字体')
    family=ImageFont.truetype(str(font),16).getname()[0]
    folder.mkdir(parents=True)
    figures=[]
    scope=[('完整','full',view,True)]
    focus=view['initial_focus']
    if focus['compound_ids'] and focus['target_ids']:
        selected=functions['build_view'](packet,selected_compounds=focus['compound_ids'],selected_targets=focus['target_ids'])
        scope.append(('焦点','focus',selected,False))
    for label,role,drawing,full in scope:
        png=folder/f'A06_{label}结合能热图.png';svg=folder/f'A06_{label}结合能热图.svg'
        content=functions['heatmap_svg'](drawing,full=full).replace('Microsoft YaHei,Arial,sans-serif',
                   escape(family+',Arial,sans-serif',quote=True))
        svg.write_text(content,encoding='utf-8')
        functions['_png'](drawing,png,full=full,font_path=font)
        figures.extend((file_record(root,png,'plot_a06_native_'+role+'_png'),file_record(root,svg,'plot_a06_native_'+role+'_svg')))
    csv_path=folder/'A06_完整评分明细.csv'
    fields=['compound_id','compound_name','name_zh','name_en','target_id','symbol','state','score','quality','reason_zh']
    with csv_path.open('x',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader()
        for compound,line in zip(view['table']['rows'],view['table']['cells']):
            for receptor,cell in zip(view['table']['columns'],line):
                row={**compound,**receptor,**cell};row.update(compound_name=compound['label'],score=cell['score_text'])
                writer.writerow({key:row[key] for key in fields})
    json_path=folder/'A06_平台展示.json';write_json(json_path,view)
    return figures,[file_record(root,csv_path,'a06_native_matrix_csv'),file_record(root,json_path,'a06_native_display_view')]
