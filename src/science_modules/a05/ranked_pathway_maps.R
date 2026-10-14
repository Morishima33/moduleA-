# 仅绘制已归档A05命中，不执行富集分析或假设表达方向。
args <- commandArgs(trailingOnly=TRUE)
stopifnot(length(args)==2L)
suppressPackageStartupMessages(library(pathview))
suppressPackageStartupMessages(library(jsonlite))
stopifnot(as.character(packageVersion("pathview"))=="1.46.0")
input <- fromJSON(args[[1]], simplifyVector=FALSE)
setwd(args[[2]])
for (item in input$pathways) {
  hit <- rep(1, length(item$entrez_ids)) # 一只表示命中，不是表达倍数。
  names(hit) <- unlist(item$entrez_ids)
  mapped <- pathview(gene.data=hit, pathway.id=sub("^hsa", "", item$id),
    species="hsa", gene.idtype="entrez", kegg.dir=".", out.suffix="ranked",
    kegg.native=TRUE, node.sum="max", both.dirs=list(gene=FALSE,cpd=FALSE),
    discrete=list(gene=TRUE,cpd=FALSE), limit=list(gene=1,cpd=1),
    bins=list(gene=1,cpd=10), high=list(gene="#C84545",cpd="yellow"),
    mid=list(gene="#EEEEEE",cpd="gray"), na.col="#EEEEEE", plot.col.key=FALSE)
  stopifnot(!is.null(mapped$plot.data.gene))
  write.table(mapped$plot.data.gene, file=paste0(item$id,"_node_mapping.tsv"),
    sep="\t", row.names=FALSE, quote=FALSE, na="")
  saveRDS(mapped, paste0(item$id,"_pathview_mapping.rds"))
}
writeLines(capture.output(sessionInfo()), "R_sessionInfo.txt")
