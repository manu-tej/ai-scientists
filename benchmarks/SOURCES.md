# BiomniBench-DA — source publications

The 50 data-analysis tasks (`da-<group>-<n>`) derive from 20 published studies. This
maps each task group to its source paper, journal, accession, and the tasks we built
adversarial variants for. Raw provenance only — no scores or model output.

Citations were resolved via **PubMed** (DOIs link to the original articles). Two are
not standard journal articles: **DA-14** is a *derived* dataset integrating several
published sepsis-endotype schemes (no single source paper); **DA-20** was not found
in PubMed (likely a preprint) — title/journal are from the dataset's own description.

Machine-readable version: [`sources.json`](sources.json).

| Group | Paper | Journal · Year | DOI | Accession | Our tasks |
|---|---|---|---|---|---|
| DA-1 | Spatiotemporal single-cell analysis decodes cellular dynamics…immunotherapy in colorectal cancer | Cancer Cell · 2024 | [10.1016/j.ccell.2024.06.009](https://doi.org/10.1016/j.ccell.2024.06.009) | GSE236581 | da-1-3, 1-4 |
| DA-3 | Genomic and Transcriptomic Features of Response to Anti-PD-1 Therapy in Metastatic Melanoma (Hugo et al.) | Cell · 2016 | [10.1016/j.cell.2016.02.065](https://doi.org/10.1016/j.cell.2016.02.065) | GSE78220 | da-3-4, 3-5 |
| DA-4 | A single-cell atlas reveals immune heterogeneity in anti-PD-1-treated NSCLC | Cell · 2025 | [10.1016/j.cell.2025.03.018](https://doi.org/10.1016/j.cell.2025.03.018) | GSE243013 | da-4-1, 4-6, 4-7 |
| DA-5 | Pan-cancer proteogenomics expands the landscape of therapeutic targets | Cell · 2024 | [10.1016/j.cell.2024.05.039](https://doi.org/10.1016/j.cell.2024.05.039) | CPTAC | da-5-1, 5-3 |
| DA-6 | Temporal dynamics of the multi-omic response to endurance exercise training (MoTrPAC) | Nature · 2024 | [10.1038/s41586-023-06877-w](https://doi.org/10.1038/s41586-023-06877-w) | — | da-6-2, 6-5 |
| DA-8 | Individual variations in glycemic responses to carbohydrates and underlying metabolic physiology | Nature Medicine · 2025 | [10.1038/s41591-025-03719-2](https://doi.org/10.1038/s41591-025-03719-2) | — | da-8-1, 8-2, 8-3 |
| DA-9 | Sotigalimab and/or nivolumab with chemotherapy in 1L metastatic pancreatic cancer (PRINCE) | Nature Medicine · 2022 | [10.1038/s41591-022-01829-9](https://doi.org/10.1038/s41591-022-01829-9) | PICI0002 | da-9-1, 9-7 |
| DA-10 | Screening membraneless organelle participants with ML integrating multimodal features | PNAS · 2022 | [10.1073/pnas.2115369119](https://doi.org/10.1073/pnas.2115369119) | — | da-10-1, 10-3 |
| DA-11 | KIR+CD8+ T cells suppress pathogenic T cells and are active in autoimmune diseases and COVID-19 | Science · 2022 | [10.1126/science.abi9591](https://doi.org/10.1126/science.abi9591) | GSE193442 | da-11-1 |
| DA-12 | Integrative analyses of noncoding RNAs reveal mechanisms augmenting tumor malignancy in lung adenocarcinoma | Nucleic Acids Res · 2020 | [10.1093/nar/gkz1149](https://doi.org/10.1093/nar/gkz1149) | TCGA | da-12-2, 12-4 |
| DA-13 | Plasma proteome adaptations during feminizing gender-affirming hormone therapy | Nature Medicine · 2025 | [10.1038/s41591-025-04023-9](https://doi.org/10.1038/s41591-025-04023-9) | 41591_2025_4023 | da-13-1, 13-3, 13-5, 13-6 |
| DA-14 | *Sepsis endotyping consensus framework — DERIVED* (Sweeney; Davenport/Cano SRS; Yao; Wong; MARS) | (derived) | — | — | da-14-1, 14-3, 14-8 |
| DA-15 | Integrative transcriptomic analysis of the ALS spinal cord implicates glial activation… | Nature Neuroscience · 2022 | [10.1038/s41593-022-01205-3](https://doi.org/10.1038/s41593-022-01205-3) | — | da-15-1, 15-2, 15-7, 15-8 |
| DA-16 | Transcriptomic profiling across the NAFLD spectrum…steatohepatitis and fibrosis (Govaere et al.) | Sci Transl Med · 2020 | [10.1126/scitranslmed.aba4448](https://doi.org/10.1126/scitranslmed.aba4448) | GSE135251 | da-16-1 |
| DA-17 | Single-cell RNA-seq reveals cell type-specific molecular and genetic associations to lupus (Perez et al.) | Science · 2022 | [10.1126/science.abf1970](https://doi.org/10.1126/science.abf1970) | CELLxGENE 4118e166… | da-17-1, 17-3, 17-5 |
| DA-18 | The Genomic Landscape of Endocrine-Resistant Advanced Breast Cancers (Razavi et al.) | Cancer Cell · 2018 | [10.1016/j.ccell.2018.08.008](https://doi.org/10.1016/j.ccell.2018.08.008) | cBioPortal / MSK-IMPACT | da-18-1, 18-5, 18-7 |
| DA-19 | CBFβ-SMMHC Inhibition Triggers Apoptosis by Disrupting MYC Chromatin Dynamics in AML | Cell · 2018 | [10.1016/j.cell.2018.05.048](https://doi.org/10.1016/j.cell.2018.05.048) | GSE101788/89/90 | da-19-1, 19-3, 19-4, 19-6 |
| DA-20 | Mapping the Transcriptional Landscape of Drug Responses in Primary Human Cells (Drug-seq, GDPx2) | Cancer Cell *(per dataset)* | *not in PubMed* | GDPx2 | da-20-1, 20-3, 20-4 |
| DA-24 | A genome-wide association study of neonatal metabolites (He et al.) | Cell Genomics · 2024 | [10.1016/j.xgen.2024.100668](https://doi.org/10.1016/j.xgen.2024.100668) | — | da-24-3 |
| DA-25 | Dynamic prostate cancer transcriptome analysis delineates the trajectory to disease progression | Nature Communications · 2021 | [10.1038/s41467-021-26840-5](https://doi.org/10.1038/s41467-021-26840-5) | GSE118435/120741/126078, TCGA | da-25-1 |
| DA-26 | Building a translational cancer dependency map for The Cancer Genome Atlas | Nature Cancer · 2024 | [10.1038/s43018-024-00789-y](https://doi.org/10.1038/s43018-024-00789-y) | CCLE + TCGA | da-26-2, 26-4 |

*Citations retrieved from PubMed. DA-1/DA-3/DA-4/DA-5 etc. journal+year verified against PubMed metadata; the dataset's own `instruction.md` occasionally states a different journal (e.g. it labels DA-19 "Cancer Cell" but PubMed records it as Cell 2018).*
