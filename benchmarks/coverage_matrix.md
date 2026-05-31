# BiomniBench-DA: Adversarial-Variant Coverage Matrix (all 50 tasks)

Generated 2026-05-31 by surveying every task's `instruction.md` + rubric +
answer-critical file structure (4 parallel agents over the 44 un-downloaded
tasks; 6 already local). Proves the variant pipeline either **builds+validates**
a task or **explicitly flags** it as needing an adapter — never silently wrong.

## Headline finding: redundancy is pervasive

**~86% of tasks (38/44 surveyed) have a validity hazard** — a sibling column or
file that re-encodes the removed signal (the same bug class that broke 6 of our
own 11 hand-built variants). Examples: da-18-1 has ~12 redundant receptor
columns; da-14-3's score table already contains the precomputed answer; da-3-5's
sheet S1E directly answers the question the intended-removed sheet was for. **This
is why the validator gate is mandatory** — naive single-column removal produces an
answerable "unanswerable" variant most of the time.

## Coverage summary (50 tasks)

| Adapter status | Count | Meaning |
|---|---|---|
| TABULAR-OK | 29 | csv/tsv/txt/xls/xlsx — buildable now |
| ANNDATA-OK | 3 | h5ad obs edits — buildable now |
| NEEDS-ADAPTER | 18 | gz / narrowPeak / bam / h5 / Rdata / GEO-SOFT / mtx / large-txt |

With two planned cheap additions — **transparent gzip** in TabularAdapter and a
format-agnostic **`remove_file` op + `file_absent` check** — ~44/50 become
buildable; ~6 need bespoke adapters (GEO-SOFT, Rdata, comment-offset `.xls`
writes).

## Per-task matrix

### Already local (our 6)
| task | format | coverage | hazard |
|---|---|---|---|
| da-3-4 | xls | TABULAR-OK | Y (Response) |
| da-5-1 | xlsx | TABULAR-OK | Y (Tier across sheets) |
| da-12-4 | csv | TABULAR-OK | Y (survival_status) |
| da-13-3 | csv | TABULAR-OK | N |
| da-17-1 | h5ad | ANNDATA-OK | Y (ind_cov leak) |
| da-20-1 | csv + h5 | TABULAR-OK | Y |

### Batch 1
| task | format | coverage | hazard |
|---|---|---|---|
| da-1-3 | large space-sep .txt (108 MB) | NEEDS-ADAPTER:large-txt | Y |
| da-1-4 | xlsx (header row 2) | TABULAR-OK | Y |
| da-10-1 | xlsx (21 MB) | TABULAR-OK | Y |
| da-10-3 | xlsx (header row 2) | TABULAR-OK | Y |
| da-11-1 | gzipped gene×cell counts ×10 | NEEDS-ADAPTER:gz-counts | N |
| da-12-2 | xlsx (header row 2) | TABULAR-OK | Y |
| da-13-1 | tsv SDRF | TABULAR-OK | Y |
| da-13-5 | csv (header row 3) | TABULAR-OK | Y |
| da-13-6 | csv (header row 4) | TABULAR-OK | Y |
| da-14-1 | csv | TABULAR-OK | Y |
| da-14-3 | csv | TABULAR-OK | Y (score table leaks answer) |

### Batch 2
| task | format | coverage | hazard |
|---|---|---|---|
| da-14-8 | csv (expr matrix + scores) | TABULAR-OK | N |
| da-15-1 | gzipped tsv metadata | TABULAR-OK | Y |
| da-15-2 | gz gene×sample matrix (+RData,+gtf) | NEEDS-ADAPTER:gz-matrix | Y |
| da-15-7 | gzipped tsv metadata | TABULAR-OK | N |
| da-15-8 | tsv + multi-sheet xlsx ×2 | NEEDS-ADAPTER:xlsx-multisheet | Y |
| da-16-1 | GEO SOFT / series-matrix | NEEDS-ADAPTER:geo-soft | Y |
| da-17-3 | h5ad (~12 GB) | ANNDATA-OK | Y (ontology/ISG proxies) |
| da-17-5 | h5ad (~12 GB) | ANNDATA-OK | Y (ancestry PCs/donor_id) |
| da-18-1 | cBioPortal tsv (header row 5) | TABULAR-OK | Y (~12 receptor cols) |
| da-18-5 | MAF + CNA tsv | TABULAR-OK | Y (dual evidence) |
| da-18-7 | MAF + CNA tsv | TABULAR-OK | Y (dual evidence) |

### Batch 3
| task | format | coverage | hazard |
|---|---|---|---|
| da-19-1 | tsv (Cuffdiff) | TABULAR-OK | Y (FPKM recomputes FC) |
| da-19-3 | narrowPeak + tsv | NEEDS-ADAPTER:narrowPeak | Y |
| da-19-4 | bam + narrowPeak | NEEDS-ADAPTER:bam | Y |
| da-19-6 | narrowPeak + xls + tsv | NEEDS-ADAPTER:narrowPeak | Y |
| da-20-3 | csv (DESeq2) | TABULAR-OK | N |
| da-20-4 | h5 (generic HDF5) + csv | NEEDS-ADAPTER:h5 | Y |
| da-24-3 | gz headerless GWAS sumstats | NEEDS-ADAPTER:gz | Y |
| da-25-1 | tsv/MAF + clinical | TABULAR-OK | Y (Gleason proxies T-stage) |
| da-26-2 | tsv matrices + .Rdata | NEEDS-ADAPTER:Rdata | Y |
| da-26-4 | csv/tsv matrices | TABULAR-OK | N |
| da-3-5 | multi-sheet .xls | NEEDS-ADAPTER:xls-write | Y (S1E leaks answer) |

### Batch 4
| task | format | coverage | hazard |
|---|---|---|---|
| da-4-1 | csv.gz (40.7 MB) | NEEDS-ADAPTER:gz | N |
| da-4-6 | csv | TABULAR-OK | Y (Tex-clone proxies) |
| da-4-7 | csv.gz (15.9 MB) + csv | NEEDS-ADAPTER:gz | Y |
| da-5-3 | xlsx multi-sheet | NEEDS-ADAPTER:xlsx | Y (CancerTypeCount) |
| da-6-2 | xlsx comment-offset header | NEEDS-ADAPTER:xlsx | Y (zscore recovers FC) |
| da-6-5 | xlsx comment-offset header | NEEDS-ADAPTER:xlsx | Y |
| da-8-1 | csv | TABULAR-OK | Y (Diastolic proxies Systolic) |
| da-8-2 | csv | TABULAR-OK | Y (HOMA-IR proxy) |
| da-8-3 | csv + tsv | TABULAR-OK | Y |
| da-9-1 | csv | TABULAR-OK | Y (PFS proxies OS) |
| da-9-7 | csv | TABULAR-OK | Y |

## Adapter roadmap (to reach full 50)

1. **Transparent gzip** (TabularAdapter): read/write `.gz`-wrapped csv/tsv →
   da-4-1, da-4-7, da-24-3, da-15-1/15-7 confirmed. Cheap.
2. **`remove_file` op + `file_absent` check** (format-agnostic): handles
   intrinsic-signal / exotic-format tasks by removing the answer-critical file
   entirely → da-11-1, da-15-2, da-19-4 (bam), da-20-4 (h5), narrowPeak tasks.
3. **xlsx header-offset / multi-sheet**: already supported via `header_row` +
   per-sheet ops; the survey's "NEEDS-ADAPTER:xlsx" was agent-side, not pipeline-
   side — re-confirm per task.
4. **Bespoke (deferred)**: GEO SOFT/series-matrix (da-16-1), `.Rdata` (da-26-2),
   `.xls` *write* (da-3-5; openpyxl is xlsx-only).

## Note

The "NEEDS-ADAPTER:xlsx" flags from batch 4 reflect the survey agents' read
difficulty (comment-offset headers), not a pipeline gap — `TabularAdapter`
accepts `header_row`, so most are TABULAR-OK once the header row is specified in
the spec. They are re-checked at spec-authoring time.
