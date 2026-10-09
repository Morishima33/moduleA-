# A05固定工具版本；输入输出路径由统一Python入口传入。
args <- commandArgs(trailingOnly=TRUE) # 读取模式和文件路径。
stopifnot(length(args) == 3L) # 不猜缺失参数。
versions <- c(clusterProfiler="4.14.6", org.Hs.eg.db="3.20.0", GO.db="3.20.0", DOSE="4.0.1", jsonlite="2.0.0", ggplot2="4.0.3") # 固定实际安装版本。
for (p in names(versions)) stopifnot(as.character(utils::packageVersion(p)) == versions[[p]]) # 环境改变必须停止。
suppressPackageStartupMessages(library(clusterProfiler)) # 使用工具的实际ORA实现。
suppressPackageStartupMessages(library(AnnotationDbi)) # 读取固定人类注释。
suppressPackageStartupMessages(library(org.Hs.eg.db)) # 固定人类OrgDb。
suppressPackageStartupMessages(library(GO.db)) # 固定GO条目名称与类别。
suppressPackageStartupMessages(library(jsonlite)) # 数据接口只交换JSON。
if (args[[1]] == "export") { # 来源整理独立于研究结果。
  ids <- keys(org.Hs.eg.db, keytype="ENTREZID") # 仅人类注释中的基因。
  dat <- suppressMessages(select(org.Hs.eg.db, keys=ids, columns=c("GOALL","ONTOLOGYALL"), keytype="ENTREZID")) # 包含GO祖先注释，与工具GOALL口径一致。
  dat <- unique(dat[!is.na(dat$GOALL),c("ENTREZID","GOALL","ONTOLOGYALL")]) # 去重而不重复计数。
  terms <- Term(GOTERM) # 固定版本的官方GO描述。
  dat <- dat[dat$GOALL %in% names(terms),] # 不存在于该版本的条目不伪造名称。
  result <- list() # 按三类分别保存背景。
  for (g in c("BP","CC","MF")) { # 分组不合并校正。
    sub <- dat[dat$ONTOLOGYALL==g,] # 明确该类注释总体。
    sets <- split(as.character(sub$ENTREZID), sub$GOALL) # 每条注释的完整基因集。
    result[[g]] <- lapply(sort(names(sets)), function(id) list(id=id, description=unname(terms[[id]]), genes=sort(unique(sets[[id]])))) # 稳定顺序保存。
  } # 完成三类注释。
  metadata <- list(org=metadata(org.Hs.eg.db),go=metadata(GO.db),versions=as.list(versions),R=as.character(getRversion())) # 记录真实来源日期，非下载日期替代版本。
  write_json(list(annotations=result,metadata=metadata),args[[3]],auto_unbox=TRUE,digits=NA,null="null",na="null") # 完整导出供内容指纹归档。
} else if (args[[1]] == "analyze") { # 严格使用传入的固定注释快照。
  input <- read_json(args[[2]],simplifyVector=FALSE) # 不从旧Kimi目录隐式取数据。
  genes <- unique(as.character(unlist(input$genes))) # 身份映射已经完成，不扩大输入。
  output <- list() # 保留各组完整结果。
  for (group in c("BP","CC","MF","KEGG")) { # 四个独立检验族。
    terms <- input$annotations[[group]] # 每组自己的完整注释。
    termids <- vapply(terms,function(x) x$id,character(1)) # 保留原条目ID。
    sets <- lapply(terms,function(x) unique(as.character(unlist(x$genes)))) # 注释不重复计数。
    names(sets) <- termids # 稳定关联。
    universe <- sort(unique(unlist(sets))) # 当前注释库实际可分析的人类基因。
    effective <- intersect(genes,universe) # 有效输入按每类分别计算。
    sizes <- lengths(sets) # 条目大小基于实际背景。
    hits <- vapply(sets,function(x) length(intersect(x,effective)),integer(1)) # 保存无命中和过滤原因。
    eligible <- sizes>=10 & sizes<=500 & hits>0 # 与该DOSE版本实际检验范围一致。
    skipped <- data.frame(ID=termids[!eligible],reason=ifelse(sizes[!eligible]<10 | sizes[!eligible]>500,"条目背景基因数不在10—500","有效输入无命中"),Size=sizes[!eligible],Count=hits[!eligible]) # 未检验不假设p值。
    all <- data.frame() # 无可检验条目时正常空结果。
    if (length(effective)>0 && any(eligible)) { # 不触发工具随机示例提示。
      t2g <- data.frame(term=rep(termids,lengths(sets)),gene=unlist(sets,use.names=FALSE)) # 原完整注释用于ORA。
      t2n <- data.frame(term=termids,name=vapply(terms,function(x) x$description,character(1))) # 保留原始描述。
      res <- enricher(gene=effective,universe=universe,TERM2GENE=t2g,TERM2NAME=t2n,pvalueCutoff=1,qvalueCutoff=1,pAdjustMethod="BH",minGSSize=10,maxGSSize=500) # 放开显示过滤以保留全部实际检验，不改变主显著性。
      stopifnot(!is.null(res)) # 预期有检验但返回空属于错误。
      all <- res@result # 不用as.data.frame的二次p/q过滤。
      all <- all[order(all$p.adjust,all$ID),] # 已批准排序及稳定并列顺序。
      stopifnot(setequal(all$ID,termids[eligible])) # 确认实际检验族完整。
    } # 完成实际计算。
    significant <- if(nrow(all)) all[!is.na(all$p.adjust) & all$p.adjust<0.05,] else all # 主口径只有BH严格小于0.05。
    displayed <- head(significant,if(group=="KEGG") 20L else 10L) # 排版限制不改统计。
    output[[group]] <- list(all=all,significant=significant,display=displayed,skipped=skipped,background=universe,effective=effective,missing=setdiff(genes,universe)) # 分母和未映射可追溯。
  } # 四类全部输出。
  write_json(output,args[[3]],dataframe="rows",auto_unbox=TRUE,digits=NA,null="null",na="null") # qvalue缺失保留null，不替换成p.adjust。
} else stop("未知A05运行模式") # 不提供隐式默认动作。
