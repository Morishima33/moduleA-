"""新版双语展示沿用原图形几何与指标，只明确区分无显著和有显著但暂不展示。"""
from copy import deepcopy
from types import FunctionType
from . import plan_figures as original
from .display import english


def draw(presentation,plan,folder):
    """不改原绘图器全局变量，使用本次独立Canvas适配实际展示范围。"""
    counts={row['group']:row['significant_count'] for row in presentation['groups']}
    class DisplayCanvas(original.Canvas):
        """每张图记录自身类别，空展示只影响说明文字，不更换原始统计。"""
        def text(self,x,y,text,*args,**kwargs):
            """已有显著条目被排除/暂缓时如实说明，不伪造零显著结论。"""
            if isinstance(text,str):
                if ' 富集：本方案前 ' in text:self.group=text.split(' ',1)[0]
                if text=='本类无符合方案阈值的显著条目，不放宽阈值补项。' and counts.get(getattr(self,'group',''),0):
                    text=f"原始显著{counts[self.group]}项，本图因展示决定暂不列项；完整统计保留。"
                if text.startswith('排序：BH校正后P值、稳定编号；'):
                    text+='展示排除与暂缓不改变完整统计。'
            return super().text(x,y,text,*args,**kwargs)
    tables=deepcopy(presentation['tables'])
    for group in ('BP','CC','MF','KEGG'):
        for row in tables[group.lower()+'_display']:
            row['Description']=english(row)+((' / '+row['description_zh']) if row['description_zh'] else ' / 中文待核译')
    draw_bound=FunctionType(original.draw.__code__,dict(vars(original),Canvas=DisplayCanvas),'draw_plan_display')
    return draw_bound(tables,plan,folder)
