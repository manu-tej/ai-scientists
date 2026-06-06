#!/usr/bin/env Rscript
## Reproduce bix-54-q7 and show the gold range (184000,185000) is CORRECT — the three
## agents share a "drop the monoculture anchors" blind spot (a correlated cross-agent
## failure), they are NOT defeated by a broken answer key.
##
## Question: max colony area predicted at the optimal proportion of strain 287, using the
## best of {quadratic, cubic, natural spline df=4} (AIC). Data = Swarm_2.csv (P. aeruginosa
## quorum-sensing strains 287/98; co-culture mixtures + pure-strain monocultures).
##
##   A: 287_98 co-culture mixtures only        -> max 180,771 @ p=0.902  (= codex's exact
##                                                 answer; cc/agy ~178,984, an A variant)
##   B: mixtures + pure-287 & pure-98 anchors   -> max 184,264 @ p=0.919  (INSIDE the gold)
##   pure-287 anchor alone                      -> max 184,372            (also in gold)
##
## The reference notebook anchored the proportion-response curve with the monoculture
## endpoints (proportion 0.0 and 1.0); all three agents read "in the mixtures" literally
## and dropped them, shifting the spline peak ~2% low.
##
## Usage:  Rscript scripts/bixbench/repro_bix54_q7.R <path-to-Swarm_2.csv>

suppressMessages(library(splines))
args <- commandArgs(trailingOnly = TRUE)
csv <- if (length(args) >= 1) args[1] else "Swarm_2.csv"
d <- read.csv(csv, stringsAsFactors = FALSE)

prop287 <- function(ratio) {           # "5:1" (287:98) -> 5/6 = 0.833
  p <- as.numeric(strsplit(ratio, ":")[[1]]); p[1] / (p[1] + p[2])
}

fit_and_max <- function(df, label) {
  df$p <- vapply(df$Ratio, prop287, numeric(1))
  models <- list(
    quadratic = lm(Area ~ poly(p, 2, raw = TRUE), data = df),
    cubic     = lm(Area ~ poly(p, 3, raw = TRUE), data = df),
    nspline   = lm(Area ~ ns(p, df = 4), data = df))
  aics <- sapply(models, AIC)
  best <- names(which.min(aics))
  grid <- data.frame(p = seq(min(df$p), max(df$p), length.out = 20001))
  pred <- predict(models[[best]], newdata = grid)
  i <- which.max(pred)
  cat(sprintf("\n=== %s (n=%d) ===\n", label, nrow(df)))
  cat("AIC:", paste(sprintf("%s=%.1f", names(aics), aics), collapse = "  "), "\n")
  cat(sprintf("best=%s  max area=%.1f at p287=%.4f  | in gold (184000,185000)? %s\n",
              best, pred[i], grid$p[i],
              ifelse(pred[i] >= 184000 & pred[i] <= 185000, "YES", "no")))
}

A <- subset(d, StrainNumber == "287_98")
fit_and_max(A, "A: 287_98 mixtures only (the agents' reading)")
fit_and_max(rbind(A, subset(d, StrainNumber %in% c("287", "98"))),
            "B: mixtures + pure-287 & pure-98 monoculture anchors (the reference)")
fit_and_max(rbind(A, subset(d, StrainNumber == "287")),
            "pure-287 anchor only")
