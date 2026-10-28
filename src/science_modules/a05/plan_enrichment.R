# 新方案A05 ORA：保留冻结检验族/背景/BH规则，参数仅来自已校验的不可变方案。
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args) == 3L)
versions <- c(clusterProfiler="4.14.6", org.Hs.eg.db="3.20.0", GO.db="3.20.0", DOSE="4.0.1", jsonlite="2.0.0", ggplot2="4.0.3")
for (p in names(versions)) stopifnot(as.character(utils::packageVersion(p)) == versions[[p]])
suppressPackageStartupMessages(library(clusterProfiler))
suppressPackageStartupMessages(library(AnnotationDbi))
suppressPackageStartupMessages(library(org.Hs.eg.db))
suppressPackageStartupMessages(library(GO.db))
suppressPackageStartupMessages(library(jsonlite))
input <- read_json(args[[2]], simplifyVector=FALSE)
if (args[[1]] == "export") {
  # 未纳入GO时只记录版本，不导出GO注释；KEGG原响应由Python固定官方入口保存。
  result <- list()
  if (isTRUE(input$include_go)) {
    ids <- keys(org.Hs.eg.db, keytype="ENTREZID")
    dat <- suppressMessages(select(org.Hs.eg.db, keys=ids, columns=c("GOALL","ONTOLOGYALL"), keytype="ENTREZID"))
    dat <- unique(dat[!is.na(dat$GOALL),c("ENTREZID","GOALL","ONTOLOGYALL")])
    terms <- Term(GOTERM)
    dat <- dat[dat$GOALL %in% names(terms),]
    for (g in c("BP","CC","MF")) {
      sub <- dat[dat$ONTOLOGYALL==g,]
      sets <- split(as.character(sub$ENTREZID),sub$GOALL)
      result[[g]] <- lapply(sort(names(sets)),function(id) list(id=id,description=unname(terms[[id]]),genes=sort(unique(sets[[id]]))))
    }
  }
  metadata <- list(org=metadata(org.Hs.eg.db),go=metadata(GO.db),versions=as.list(versions),R=as.character(getRversion()))
  write_json(list(annotations=result,metadata=metadata),args[[3]],auto_unbox=TRUE,digits=NA,null="null",na="null")
} else if (args[[1]] == "analyze") {
  # 仅允许本协议的统计参数，不接受执行器默认值或未知字段。
  p <- input$parameters
  stopifnot(setequal(names(p),c("include_go","include_kegg","min_size","max_size","adjusted_p_lt")))
  stopifnot(is.logical(p$include_go),length(p$include_go)==1,is.logical(p$include_kegg),length(p$include_kegg)==1)
  stopifnot(p$include_go || p$include_kegg)
  stopifnot(is.numeric(p$min_size),is.numeric(p$max_size),p$min_size>=1,p$max_size>=p$min_size,p$min_size==floor(p$min_size),p$max_size==floor(p$max_size))
  stopifnot(is.numeric(p$adjusted_p_lt),p$adjusted_p_lt>0,p$adjusted_p_lt<=1)
  genes <- unique(as.character(unlist(input$genes)))
  output <- list()
  groups <- c(if(p$include_go) c("BP","CC","MF"),if(p$include_kegg) "KEGG")
  stopifnot(setequal(names(input$annotations),groups))
  for (group in groups) {
    terms <- input$annotations[[group]]
    termids <- vapply(terms,function(x) x$id,character(1))
    sets <- lapply(terms,function(x) unique(as.character(unlist(x$genes))))
    names(sets) <- termids
    universe <- sort(unique(unlist(sets)))
    effective <- intersect(genes,universe)
    sizes <- lengths(sets)
    hits <- vapply(sets,function(x) length(intersect(x,effective)),integer(1))
    eligible <- sizes>=p$min_size & sizes<=p$max_size & hits>0
    skipped <- data.frame(ID=termids[!eligible],reason=ifelse(sizes[!eligible]<p$min_size | sizes[!eligible]>p$max_size,"条目背景基因数不在本方案范围","有效输入无命中"),Size=sizes[!eligible],Count=hits[!eligible])
    all <- data.frame()
    if (length(effective)>0 && any(eligible)) {
      t2g <- data.frame(term=rep(termids,lengths(sets)),gene=unlist(sets,use.names=FALSE))
      t2n <- data.frame(term=termids,name=vapply(terms,function(x) x$description,character(1)))
      res <- enricher(gene=effective,universe=universe,TERM2GENE=t2g,TERM2NAME=t2n,pvalueCutoff=1,qvalueCutoff=1,pAdjustMethod="BH",minGSSize=p$min_size,maxGSSize=p$max_size)
      stopifnot(!is.null(res))
      all <- res@result
      all <- all[order(all$p.adjust,all$ID),]
      stopifnot(setequal(all$ID,termids[eligible]))
    }
    significant <- if(nrow(all)) all[!is.na(all$p.adjust) & all$p.adjust<p$adjusted_p_lt,] else all
    # 统计输出不截断，图与表数量在Python展示层分别执行。
    output[[group]] <- list(all=all,significant=significant,display=significant,skipped=skipped,background=universe,effective=effective,missing=setdiff(genes,universe))
  }
  write_json(output,args[[3]],dataframe="rows",auto_unbox=TRUE,digits=NA,null="null",na="null")
} else stop("未知新方案A05运行模式")
