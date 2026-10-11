"""矩阵展示第二版配色：用户明确指定端点，不设药效或结合能阈值。"""
VERSION="A06.matrix.display.2"
PALETTE={"id":"ice_berry_v1","high_color":"#A7D5E5","low_color":"#B7326B","na_color":"#DCE1E5","unit":"kcal/mol","label_zh":"冰蓝→莓果红；评分越负越偏莓果红，NA为灰色"}
LEGACY={"id":"blue_v1","high_color":"#eff6ff","low_color":"#08519c","na_color":"#DCE1E5","unit":"kcal/mol","label_zh":"评分越负蓝色越深；NA为灰色"}

# 使用完整同批范围；恒值用中间色，不设置零点或通用阈值。
def color(score,low,high,palette=PALETTE):
    fraction=(high-score)/(high-low) if high!=low else .5
    light=tuple(int(palette["high_color"][i:i+2],16) for i in (1,3,5))
    dark=tuple(int(palette["low_color"][i:i+2],16) for i in (1,3,5))
    return "#"+"".join(f"{round(a+(b-a)*fraction):02X}" for a,b in zip(light,dark))

# 按真实背景亮度选文字颜色，提高蓝/紫/红及NA格的可读性。
def text_color(background):
    channels=[int(background[i:i+2],16)/255 for i in (1,3,5)]
    linear=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in channels]
    luminance=sum(x*w for x,w in zip(linear,(.2126,.7152,.0722)))
    return "#FFFFFF" if luminance<.32 else "#10253C"
