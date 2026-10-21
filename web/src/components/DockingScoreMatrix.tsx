// 新自动流程与旧15×15试算共用完整大表，避免后续迭代出现两套展示规则。
export interface ScoreMatrixColumn {id:string; label:string; grade?:string}
export interface ScoreMatrixCell {
  targetId:string; score:number|null; displayScore?:string; highlight?:boolean;
  tooltip:string; color?:string; textColor?:string;
}
export interface ScoreMatrixRow {
  id:string; label:string; labelZh?:string; labelEn?:string; cells:ScoreMatrixCell[];
}

/** 完整表直接展开；横向滚动限定在表内，颜色仅用于重点热图。 */
export default function DockingScoreMatrix({columns,rows,heatmap=false,label='完整结合能矩阵'}:{
  columns:ScoreMatrixColumn[];rows:ScoreMatrixRow[];heatmap?:boolean;label?:string;
}) {
  return <div style={{overflowX:'auto',maxWidth:'100%',minWidth:0}}>
    <table aria-label={label} style={{borderCollapse:'collapse',fontSize:12,width:'100%'}}>
      <thead><tr><th scope="col" style={{background:'#0F5E6E',color:'white',padding:8,minWidth:130}}>成分</th>
        {columns.map(c=><th scope="col" key={c.id} style={{background:'#0F5E6E',color:'white',padding:7,minWidth:66}}>{c.label}<br/>{c.grade}</th>)}
      </tr></thead>
      <tbody>{rows.map(row=><tr key={row.id}>
        <td style={{padding:7,border:'1px solid #DCE1E5',overflowWrap:'anywhere'}}>{row.labelZh||row.label}
          {row.labelEn&&row.labelEn!==(row.labelZh||row.label)&&<div style={{fontSize:10,color:'#586B75',maxWidth:280}}>{row.labelEn}</div>}
        </td>
        {columns.map(c=>{const cell=row.cells.find(v=>v.targetId===c.id);
          if(!cell)return <td key={c.id} title="本批组合记录缺失，请核查归档" style={{padding:8,border:'1px solid #DCE1E5'}}>记录缺失</td>;
          return <td key={c.id} title={cell.tooltip} style={{textAlign:'center',padding:8,border:'1px solid #DCE1E5',
            background:heatmap?cell.color:undefined,color:heatmap?cell.textColor:undefined}}>
            {cell.displayScore??(cell.score===null?'NA':cell.score.toFixed(2))}
            {!heatmap&&cell.highlight&&<sup style={{marginLeft:2}}>**</sup>}
          </td>;
        })}
      </tr>)}</tbody>
    </table>
  </div>;
}
