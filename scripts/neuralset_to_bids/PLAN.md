# Plan: BIDS Conversion & NEMAR Re-hosting — Consolidated Dataset Inventory

## Sources Analyzed

- **NeuralSet** (zip `41467_2025_65499_MOESM3_ESM.zip`): ~46 datasets (EEG, MEG, fMRI, fNIRS, EMG)
- **Brainsets** (`github.com/neuro-galaxy/brainsets`): 8 current + 12 in open PRs
- **M3CV** (Kaggle EEG biometric competition): 106 subjects, 6 paradigms
- **arXiv 2501.15322** (Scaling laws for brain-to-image): THINGS-EEG1, THINGS-EEG2, THINGS-MEG, Alljoined1
- **NeurIPS 2025 poster 121638** (MUniverse): HD-sEMG motor unit decomposition
- **arXiv 2502.17480** (Brain2Qwerty): EEG+MEG typing dataset
- **arXiv 2506.10165** (PNPL Competition): LibriBrain MEG + speech decoding benchmarks
- **THINGS Initiative** (things-initiative.org): Full THINGS neural dataset inventory
- **deep-research-report.md** (NeurIPS/ICML/ICLR 2022–2025 survey): Brain Treebank, CerebroVoice, ToMCAT, REFED, EEG-ImageNet

---

## A. Already in EEGDash (no action needed)

| Dataset | EEGDash ID | Source | Modality | Subjects |
|---|---|---|---|---|
| Broderick2019 (speech EEG) | ds004408 | openneuro | EEG | 19 |
| Schalk2009 (EEGMMIDB) | ds004362 | openneuro | EEG | 109 |
| Grootswagers2022 (THINGS-EEG1) | ds003825 | openneuro | EEG | 50 |
| Grootswagers2024 (Features-EEG) | ds004357 | openneuro | EEG | 16 |
| Schirrmeister2017 (High-gamma) | nm000172 | nemar | EEG | 14 |
| Contier2022 (THINGS-MEG) | ds004212 | openneuro | MEG | 5 |
| Singer2023 MEG | ds004330 | openneuro | MEG | 30 |
| Pallier2023 MEG | ds007524 | openneuro | MEG | ~50 |
| MNE Sample | ds000248 | openneuro | MEG | 2 |
| MOABB Brain Invaders | nm000202 | nemar | EEG | 64 |
| HBN R1-R11 | EEG2025r1–r11 | nemar | EEG | ~3,100 |
| AllJoined1 (Xu2024) | nm000133 | nemar | EEG | 8 |
| AllJoined-1.6M | nm000134 | nemar | EEG | 20 |
| emg2qwerty (Ctrllabs2024) | nm000104 | nemar | EMG | 108 |
| FRL Discrete Gestures | nm000105 | nemar | EMG | 100 |
| FRL Handwriting | nm000106 | nemar | EMG | 100 |
| FRL Wrist Control | nm000107 | nemar | EMG | 100 |
| HySER | nm000108 | nemar | EMG | 20 |
| NOD-MEG | ds005810 | openneuro | MEG | varies |
| NOD-EEG | ds005811 | openneuro | EEG | varies |
| + many MOABB MI datasets | nm000135–nm000245 | nemar | EEG | varies |

---

## B. On OpenNeuro but NOT in EEGDash (fMRI — out of scope for NEMAR)

| Dataset | OpenNeuro ID | Modality | Notes |
|---|---|---|---|
| Babayan2019 LEMON | ds000221 | **MRI only** | EEG not on OpenNeuro |
| Brennan2019 | ds002322 | fMRI only | EEG on UMich Deep Blue |
| BOLD5000, THINGS-fMRI, Lebel2023, Li2022, Shen2020, Singer2023 fMRI, Zhou2023 | various | fMRI | Not NEMAR-eligible |

---

## C. Need BIDS Conversion + Upload

### C1. EEG — Open License, Data Available

| # | Dataset | Subj | Ch | Sfreq | Source | License | Format | Task | Complexity |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **Babayan2019 (LEMON EEG)** | 227 | 62 | 2500 Hz | GWDG FTP | CC BY 4.0 | BrainVision .vhdr | Resting (EO/EC) | Medium — sovabids has example |
| 2 | **Khan2022 (NMT clinical)** | 2,417 | 19+2 | varies | Zenodo | CC BY-SA 4.0 | EDF | Clinical normal/abnormal | Medium |
| 3 | **Ghassemi2018 (Sleep Challenge)** | 1,985 | varies | varies | PhysioNet | PhysioNet Credentialed | PSG/WFDB | Sleep | Hard — credentialed access |
| 4 | **Nieuwland2018 (multi-site N400)** | 334 | varies | varies | OSF | CC BY 4.0 | EEGLAB .set | RSVP reading (9 labs) | Hard — 9 lab configs |
| 5 | **M3CV (biometric)** | 106 | 64 | 250 Hz | Baidu/Kaggle | CC BY 4.0 | Pickle/NumPy | 6 paradigms (rest, SSVEP, P300, motor, sensory) | Medium |
| 6 | **Accou2023 (SparrKULee)** | 85 | 64 | 8192 Hz | KU Leuven RDR | **CC-BY-NC-4.0** | Custom | Speech listening (Dutch) | Medium |
| 7 | **Kemp2000 (Sleep-EDF)** | 82 | 4-6 | 100 Hz | PhysioNet | ODbL | EDF | Sleep polysomnography | Easy — MNE native loader |
| 8 | **Brennan2019 (Alice EEG)** | 33 | 61 | 500 Hz | UMich Deep Blue | CC BY 4.0 | MAT (FieldTrip) | Narrative listening | Medium |
| 9 | **ToMCAT (EEG subset)** | 120 | 64 | 500 Hz | tomcat.ivilab.org | **CC BY-NC-SA 4.0** | XDF | Team search-and-rescue (EEG+fNIRS) | Hard — extract EEG only from multimodal |
| 10 | **REFED (EEG subset)** | 32 | 64 | 1000 Hz | HuggingFace | **CC BY-NC-SA 4.0** | .mat | Emotion (dynamic valence/arousal) | Medium — gated HF access |
| 11 | **THINGS-EEG2 (Gifford2022)** | 10 | 64 | 1000 Hz | OSF (3jk45) | CC BY-NC-ND 4.0 | BrainVision | RSVP images (16,740 conditions) | Easy |
| 12 | **Gifford2021 (THINGS-EEG1 raw)** | 10 | 64 | 1000 Hz | OSF | CC BY 4.0 | EEGLAB .set | RSVP images | Easy |
| 13 | **EEG-ImageNet** | 16 | ? | ? | Not yet public | Unknown | .pth | Image classification/reconstruction | Low — no public release yet |

### C2. iEEG/sEEG — Open License, Data Available

| # | Dataset | Subj | Ch | Sfreq | Source | License | Format | Task | Complexity |
|---|---|---|---|---|---|---|---|---|---|
| 14 | **Brain Treebank** | 10 | ~1,688 total | 2048 Hz | braintreebank.dev | **CC BY 4.0** | HDF5 (.h5.zip) | Movie watching (sEEG + linguistic annotations) | Hard — HDF5→BIDS-iEEG, copyright on stimuli |
| 15 | **CerebroVoice/NeuroVox** | 2 | 114–158 | 1000 Hz | Zenodo (10.5281/zenodo.13332808) | **CC BY 4.0** | .npy | Bilingual speech (sEEG) | Medium — NPY→BIDS-iEEG |

### C3. MEG — Open License, Data Available

| # | Dataset | Subj | Ch | Source | License | Format | Task | Complexity |
|---|---|---|---|---|---|---|---|---|
| 16 | **Gwilliams2022 (MEG-MASC)** | 27 | 208 | OSF (ag3kj) | CC0 | BIDS (FIF) | Story listening | Easy — already BIDS |
| 17 | **LibriBrain** | 1 | 306 | HuggingFace (pnpl/LibriBrain) | CC BY 4.0 | MEG | 50+ hrs audiobook listening | Medium |

### C4. fNIRS

| # | Dataset | Subj | Source | License | Format | Task |
|---|---|---|---|---|---|---|
| 18 | **Luke2021** | 17 | OSF/GitHub | Unknown | BIDS-NIRS | Auditory speech/noise |

### C5. HD-sEMG (MUniverse — NeurIPS 2025)

| # | Dataset | Subj | Ch | Source | License | Format | Task |
|---|---|---|---|---|---|---|---|
| 19 | **Caillet2023** | 6 | 64 (HD grid) | Harvard Dataverse | CC BY 4.0 | EDF + BIDS | Tibialis anterior |
| 20 | **Avrillon2024** | 8 | 64+ (HD grid) | Harvard Dataverse | CC BY 4.0 | EDF + BIDS | Tibialis + vastus lateralis |
| 21 | **Grison2025** | ~4 | HD grids | Harvard Dataverse | CC BY 4.0 | EDF + BIDS | Forearm + tibialis |

### C6. Upcoming (not yet released)

| Dataset | Subj | Modality | Location | Status |
|---|---|---|---|---|
| **Brain2Qwerty** | 35 | EEG+MEG | BCBL (Meta/FAIR) | Not public |
| **THINGS-electrophysiology1** | 23 | iEEG | Univ. Bonn | Analysis ongoing |
| **THINGS-iEEG** | ? | iEEG | Univ. Pittsburgh | Collection ongoing |
| **EEG-ImageNet** | 16 | EEG | Unknown | No public release yet |

### C7. Animal (not NEMAR-eligible)

| Dataset | Species | Source | Notes |
|---|---|---|---|
| **TVSD** | Macaque | G-Node GIN | 1,024 electrodes, V1/V4/IT |
| **THINGS-macaque EEG** | Macaque | Univ. Tübingen | Analysis ongoing |
| **THINGS-macaque V4** | Macaque | MIT | Collection completed |
| 4 primate spiking (brainsets) | Macaque | Various | Not eligible |
| Allen Visual Coding | Mouse | Allen Institute | Not eligible |

---

## D. Restricted Access — Need Author Permission

| Dataset | Modality | Subj | DUA | Feasibility | Contact |
|---|---|---|---|---|---|
| **TUH EEG** (7 variants) | EEG | 1000s | NEDC v6.0 | Best chance — administrative restriction, US data | picone@temple.edu |
| **Armeni2022** | MEG | 3 | RU-DI-HD-1.0 | Medium — 3 subjects to re-consent | Armeni / Schoffelen |
| **Schoffelen2019 (MOUS)** | MEG | 204 | RU-DI-HD-1.0 | Very low — GDPR, 204 subjects | Oostenveld / Hagoort |
| **Vandijk2022 (TDBRAIN)** | EEG | 1,274 | Brainclinics DUA | Low | Brainclinics Foundation |

---

## SUMMARY

| Category | Datasets | Total Subjects |
|---|---|---|
| Already in EEGDash | ~27+ | ~4,200+ |
| **Need BIDS conversion (EEG/MEG/iEEG, open)** | **17** | **~5,600+** |
| Need BIDS conversion (NC license) | 4 | ~247 |
| Need BIDS conversion (fNIRS) | 1 | 17 |
| Need BIDS conversion (HD-sEMG) | 3 | ~18 |
| Restricted (need negotiation) | 4 | ~2,500+ |
| Not available / upcoming | 4+ | ~74+ |

---

## PRIORITY ORDER FOR BIDS CONVERSION

### Tier 1 — High impact, open license (CC BY / CC0 / ODbL)

| Rank | Dataset | Subjects | Difficulty | License | Unique Value |
|---|---|---|---|---|---|
| **1** | Babayan2019 LEMON EEG | 227 | Medium | CC BY 4.0 | Large resting-state, very popular |
| **2** | Khan2022 NMT clinical | 2,417 | Medium | CC BY-SA 4.0 | Largest clinical EEG, normal/abnormal |
| **3** | Ghassemi2018 Sleep | 1,985 | Hard | PhysioNet | Largest sleep EEG |
| **4** | Nieuwland2018 multi-site | 334 | Hard | CC BY 4.0 | 9-lab replication, language processing |
| **5** | M3CV biometric | 106 | Medium | CC BY 4.0 | 6 paradigms, biometric, 2 sessions |
| **6** | Kemp2000 Sleep-EDF | 82 | Easy | ODbL | Classic sleep dataset |
| **7** | Brennan2019 Alice | 33 | Medium | CC BY 4.0 | Naturalistic language listening |
| **8** | Brain Treebank (iEEG) | 10 | Hard | CC BY 4.0 | Large-scale sEEG + linguistic annotations |
| **9** | Gwilliams2022 MEG-MASC | 27 | Easy | CC0 | Already BIDS — just upload to OpenNeuro |
| **10** | CerebroVoice (iEEG) | 2 | Medium | CC BY 4.0 | Bilingual speech sEEG |
| **11** | Gifford2021 THINGS-EEG1 raw | 10 | Easy | CC BY 4.0 | Complements ds003825 |
| **12** | LibriBrain | 1 | Medium | CC BY 4.0 | 50+ hrs deep MEG, speech benchmark |
| **13** | MUniverse HD-sEMG (3 datasets) | ~18 | Easy | CC BY 4.0 | Already BIDS on Dataverse |

### Tier 2 — Non-commercial license (may limit OpenNeuro hosting)

| Rank | Dataset | Subjects | Difficulty | License | Notes |
|---|---|---|---|---|---|
| **14** | Accou2023 SparrKULee | 85 | Medium | CC-BY-NC-4.0 | Speech EEG, check NC compatibility |
| **15** | ToMCAT (EEG only) | 120 | Hard | CC BY-NC-SA 4.0 | Extract EEG from multimodal |
| **16** | REFED (EEG only) | 32 | Medium | CC BY-NC-SA 4.0 | Emotion, gated HF access |
| **17** | THINGS-EEG2 | 10 | Easy | CC BY-NC-ND 4.0 | Dense RSVP, 16K conditions |
| **18** | Luke2021 fNIRS | 17 | Easy | Unknown | Already BIDS-NIRS |

### Quick wins (already BIDS, just upload):
- Gwilliams2022 MEG-MASC (27 subj, CC0, BIDS FIF on OSF)
- Luke2021 fNIRS (17 subj, BIDS-NIRS on GitHub)
- MUniverse HD-sEMG (3 datasets, BIDS on Harvard Dataverse)

### Negotiate access:
- TUH EEG — contact Dr. Picone (picone@temple.edu) for institutional redistribution
- Armeni2022 — 3 subjects, re-consent feasible

### Watch for future release:
- Brain2Qwerty (35 subj EEG+MEG, Meta/FAIR)
- THINGS-electrophysiology1 (23 patients iEEG, Univ. Bonn)
- THINGS-iEEG (Univ. Pittsburgh)
- EEG-ImageNet (16 subj, no public release yet)

### License notes:
- **Accou2023 SparrKULee**: CC-BY-NC-4.0 (non-commercial)
- **THINGS-EEG2**: CC BY-NC-ND 4.0 (non-commercial, no derivatives)
- **ToMCAT / REFED**: CC BY-NC-SA 4.0 (non-commercial, share-alike)
- **Alljoined-1.6M**: CC BY-NC-SA 4.0 on HuggingFace with additional ToU — already on NEMAR as nm000134
- **Schoffelen2019**: Paper says CC BY 4.0, but Donders Repository enforces RU-DI-HD-1.0 DUA
