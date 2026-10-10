"""Degree第一轮网络版式预览；批准标志默认关闭，演示图不代表科研结果。"""
from pathlib import Path
NETWORK_DESIGN_APPROVED = False

# 图形只读取完整网络原指标；所有第一轮节点保留，即使在绘图子图中无边。
def draw_degree(tables, destination, demo=False):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties
    import networkx as nx
    font = Path("C:/Windows/Fonts/msyh.ttc")
    if font.exists():
        from matplotlib import font_manager
        font_manager.fontManager.addfont(str(font))
        plt.rcParams["font.family"] = FontProperties(fname=str(font)).get_name()
    plt.rcParams["svg.fonttype"] = "none"
    plt.rcParams["axes.unicode_minus"] = False
    first = tables["degree_round1"]
    second = {r["target_id"] for r in tables["degree_round2"]}
    top = {r["target_id"] for r in tables["degree_top10"]}
    graph = nx.Graph()
    graph.add_nodes_from(r["target_id"] for r in first)
    graph.add_edges_from((r["source"], r["target"]) for r in tables["edges"] if r["source"] in graph and r["target"] in graph)
    # 绘图子图的无边节点单独摆放，避免弹簧布局把主网络挤到角落。
    connected = [n for n in graph if graph.degree(n)]
    positions = dict(nx.spring_layout(graph.subgraph(connected), seed=27, k=1.8 / max(len(connected), 1) ** .5, iterations=150)) if connected else {}
    isolates = sorted(set(graph) - set(connected))
    if connected:
        for i, node in enumerate(isolates): positions[node] = (1.45 + .3 * (i // 5), .8 - .4 * (i % 5))
    elif isolates:
        positions = dict(nx.circular_layout(graph))
    fig, ax = plt.subplots(figsize=(12, 8), facecolor="white")
    maximum = max((r["degree"] for r in first), default=1)
    sizes = [180 + 850 * r["degree"] / maximum for r in first]
    colors = ["#218C8D" if r["target_id"] in second else "#D5DCE0" for r in first]
    if first:
        nx.draw_networkx_edges(graph, positions, ax=ax, edge_color="#A6B5BC", alpha=.6, width=1.2)
        nx.draw_networkx_nodes(graph, positions, nodelist=[r["target_id"] for r in first], ax=ax, node_size=sizes, node_color=colors, edgecolors="white", linewidths=1.8)
        labels = {r["target_id"]: r["symbol"] for r in first if r["target_id"] in top}
        nx.draw_networkx_labels(graph, positions, labels=labels, ax=ax, font_family=plt.rcParams["font.family"][0], font_size=9, font_weight="bold", font_color="#12383D")
    else:
        ax.text(.5, .5, "第一轮无候选，不绘制虚构网络", transform=ax.transAxes, ha="center", fontsize=14)
    ax.margins(.2)
    ax.axis("off")
    prefix = "演示数据  " if demo else ""
    fig.suptitle(prefix + "Degree第一轮候选网络", fontsize=19, fontweight="bold", x=.5, y=.965)
    fig.text(.5, .905, f"第一轮 {len(first)} 个节点  ·  第二轮 {len(second)} 个节点  ·  标注第二轮前十及边界并列", ha="center", fontsize=11, color="#526571")
    from matplotlib.lines import Line2D
    handles=[Line2D([0], [0], marker="o", color="white", markerfacecolor="#D5DCE0", markersize=12, label="第一轮入选、第二轮未入选"), Line2D([0], [0], marker="o", color="white", markerfacecolor="#218C8D", markersize=12, label="第二轮入选")]
    fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(.5, .095), ncol=2, frameon=False, fontsize=11)
    fig.text(.5, .065, "节点指标来自完整网络；本图展示第一轮候选，颜色突出第二轮入选节点。", ha="center", fontsize=10, color="#526571")
    fig.text(.5, .032, "节点大小表示完整网络Degree；仅绘制候选间的边，子图无边节点仍保留。" + ("本图不是当前研究结果。" if demo else ""), ha="center", fontsize=9, color="#526571")
    fig.subplots_adjust(top=.86, bottom=.17, left=.035, right=.965)
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    result={}
    for kind in ("svg", "png"):
        path=destination.with_suffix('.'+kind);fig.savefig(path,dpi=170,facecolor="white");result[kind]=path
    plt.close(fig)
    return result
