// 同批试算Excel导出，使用运行时提供的Artifact Tool；不依赖前端包或个人路径。
import fs from 'node:fs/promises';
import path from 'node:path';
import {Workbook, SpreadsheetFile} from '@oai/artifact-tool';

const [input, output, qa] = process.argv.slice(2);
if (!input || !output || !qa) throw new Error('需要同批JSON、Excel路径及核验目录');
const data = JSON.parse(await fs.readFile(input, 'utf8'));
const workbook = Workbook.create();

/** 所有表格保留原数值类型与完整精度，显示格式只保留两位小数。 */
function sheet(name, title, headers, rows, widths) {
  const tab = workbook.worksheets.add(name);
  tab.showGridLines = false;
  const count = headers.length;
  tab.getCell(1, 0).values = [[title]];
  tab.getCell(1, 0).format.font = {name: 'Microsoft YaHei', size: 14, bold: true};
  tab.getRangeByIndexes(4, 0, rows.length + 1, count).values = [headers, ...rows];
  const body = tab.getRangeByIndexes(4, 0, rows.length + 1, count);
  body.format.font = {name: 'Microsoft YaHei', size: 10, color: '#10253C'};
  body.format.verticalAlignment = 'center';
  body.format.rowHeight = 25;
  const head = tab.getRangeByIndexes(4, 0, 1, count);
  head.format.fill = '#0F5E6E';
  head.format.font = {name: 'Microsoft YaHei', size: 10, bold: true, color: '#FFFFFF'};
  head.format.horizontalAlignment = 'center';
  head.format.rowHeight = 32;
  head.format.wrapText = true;
  for (let col = 0; col < count; col++) {
    tab.getRangeByIndexes(4, col, rows.length + 1, 1).format.columnWidth = widths[col] || 18;
  }
  tab.freezePanes.freezeRows(5);
  tab.freezePanes.freezeColumns(1);
  return tab;
}

const main = sheet('15×15试算', '15×15结合能试算表', data.matrix_headers, data.matrix_rows,
                   [30, ...Array(15).fill(13)]);
main.getRange('A3:P3').merge();
main.getRange('A3').values = [['Vina对接评分，kcal/mol。' + data.annotation_legend]];
main.getRange('A3').format.font = {name: 'Microsoft YaHei', size: 10, italic: true};
main.getRange('B6:P20').setNumberFormat('0.00');
main.getRange('B6:P20').format.horizontalAlignment = 'right';
const receptors = sheet('受体处理', '受体结构和试算范围', data.receptor_headers,
                        data.receptor_rows, [15, 10, 14, 16, 14, 15, 60, 30]);
receptors.getRangeByIndexes(5, 6, data.receptor_rows.length, 1).format.wrapText = true;
receptors.getRangeByIndexes(5, 0, data.receptor_rows.length, 8).format.rowHeight = 60;
const regions = sheet('区域明细', '实际区域Top-1及评分来源', data.region_headers,
                      data.region_rows, [30, 42, 14, 18, 16, 14, 14, 20, 90, 60]);
regions.getRangeByIndexes(5, 4, data.region_rows.length, 1).setNumberFormat('0.000000');
// 数值配色使用完整225格同批范围，NA保持灰色；不为Excel重新计算评分。
for (let row = 0; row < 15; row++) for (let col = 0; col < 15; col++) {
  if (data.matrix_marks[row][col]) main.getCell(row + 5, col + 1).setNumberFormat('0.00"**"');
  main.getCell(row + 5, col + 1).format.fill = data.cell_colors[row][col];
  main.getCell(row + 5, col + 1).format.font.color = data.cell_text_colors[row][col];
}
workbook.recalculate();
await fs.mkdir(qa, {recursive: true});
const check = await workbook.inspect({kind: 'table', range: "'15×15试算'!A5:P20",
  include: 'values', tableMaxRows: 17, tableMaxCols: 16, maxChars: 18000});
await fs.writeFile(path.join(qa, 'xlsx-inspect.ndjson'), check.ndjson);
for (const [name, range, file] of [['15×15试算', 'A1:P20', 'xlsx-matrix.png'],
  ['受体处理', 'A1:H9', 'xlsx-receptors.png'], ['区域明细', 'A1:H12', 'xlsx-regions.png']]) {
  const preview = await workbook.render({sheetName: name, range, scale: 1.3, format: 'png'});
  await fs.writeFile(path.join(qa, file), new Uint8Array(await preview.arrayBuffer()));
}
const xlsx = await SpreadsheetFile.exportXlsx(workbook);
await xlsx.save(output);
console.log(JSON.stringify({output, rows: data.matrix_rows.length, columns: 15}));
