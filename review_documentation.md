# EEGDash examples documentation review

Review date: 2026-05-09
Reviewed URL: <https://eegdash.org/generated/auto_examples/index.html>
Repository scope reviewed: all Python example/tutorial sources under `examples/`.

## Executive summary

The examples gallery has a useful teaching structure: it separates a curated learning path from task-focused recipes, applied projects, challenge pipelines, and HPC material. The biggest content issue is not missing material; it is that several user-facing descriptions still expose internal planning notes. Those notes distract from the learning path and should be removed before expanding the page further.

After a full pass over the tutorial sources, the second issue is coverage visibility: the live gallery does not make it obvious that the documentation set spans API discovery, minimal loading, EO/EC decoding, feature extraction, P3 oddball, transfer learning, age/sex/p-factor prediction, clinical summaries, EEG2025 challenge material, offline workflows, HPC workflows, and one developer/debugging script. The report below keeps the original notes and adds an all-tutorial inventory so the next documentation pass can validate every tutorial instead of optimizing only the index page.

## Review coverage

The review covered these source groups:

- `examples/core/`: minimal usage, EO/EC decoding, EO/EC feature extraction, and P300 transfer learning.
- `examples/tutorials/`: API exploration, clinical summary, transfer learning, feature extraction, sex classification, age prediction, p-factor prediction, and oddball examples.
- `examples/eeg2025/`: challenge 1, challenge 2, and offline cache workflow.
- `examples/hpc/`: EO/EC cluster/HPC workflow.
- `examples/dev_scripts/`: PyBIDS/Braindecode debugging script.

## Sentence to drop

Drop this sentence from the gallery introduction:

> Numbers are tutorial-id prefixes (`plot_00_*` through `plot_73_*`); skip rather than reorder them.

Why: it describes repository/file-maintenance mechanics rather than a user task. Users need to know what to read next, not how maintainers assign gallery prefixes.

## Related cleanup: remove internal plan references

The same page also includes parenthetical references such as `(plan §Category A, lines 360-380)`, `(plan §Category F, lines 425-442)`, and `(plan §Category I, lines 615-621 and 1021-1037)`. These should be removed wherever they appear because they point to an internal planning document that is not part of the public learning experience.

Recommended replacement pattern:

- Before: `CPU-only, each runs in under a few minutes (plan §Category A, lines 360-380).`
- After: `CPU-only, each runs in under a few minutes.`

## Validation notes from the examples index

- The top-level structure is clear: Tutorials, How-to recipes, Applied research projects, EEG 2025 Foundation Challenge, and High-performance computing.
- The phrase “Difficulty 1 = absolute beginner, 3 = advanced / foundation-model tier” is useful, but it would be easier to scan if every card also displayed difficulty and estimated runtime.
- Several section blurbs are strong because they answer “why would I read this?” Examples include leakage-safe splitting, evaluation and benchmarking, and offline/cache workflows.
- The gallery mixes British and American spelling in visible labels, for example “generalize” and “Parallelize”. Standardizing on one spelling style would make the site feel more polished.
- Some card titles are long and excellent for search, but hard to scan in a gallery. Consider shorter card titles plus a one-sentence subtitle on the card.

## All-tutorial validation inventory

Use this table as the next pass checklist. “Primary gap” is the most important documentation improvement for that tutorial, not necessarily a code defect.

| Source | User goal | Current strength | Primary gap to validate or expand |
| --- | --- | --- | --- |
| `examples/tutorials/tutorial_api.py` | Query and inspect EEGDash metadata without downloading EEG files. | Clear beginner-friendly API flow: initialize, query, inspect keys, filter, summarize. | Add a small expected-output block with example record keys and expected summary fields so readers can confirm the API call worked. |
| `examples/core/tutorial_minimal.py` | Load data, preprocess, window, split, and train the smallest possible model. | Excellent quick-start candidate because it is short and linear. | The tutorial openly notes leakage in the split; add a safer default or a clearly labeled “not for evaluation” warning plus a follow-up leakage-safe split link. |
| `examples/core/tutorial_eoec.py` | Train an eyes-open/eyes-closed classifier for a single subject. | Good narrative of event reannotation, preprocessing, train/test setup, and model training. | Add validation targets for window counts, class balance, tensor shapes, and accuracy interpretation. |
| `examples/core/tutorial_feature_extractor_open_close_eye.py` | Extract EO/EC features and train a classical model. | Useful bridge from raw EEG to tabular features. | Explain feature names, output matrix shape, missing-feature handling, and when feature methods are preferable to CNNs. |
| `examples/core/p300_transfer_learning.py` | Train a domain-adaptive P300 model with AS-MMD. | Strong advanced example with paper context, domain adaptation, deep model, and cross-validation. | Add a compute/runtime warning, minimum data assumptions, expected fold outputs, and a short explanation of AS-MMD for readers who skip the paper. |
| `examples/tutorials/noplot_tutorial_features_eoec.py` | Build EO/EC feature tables. | Detailed preprocessing and feature workflow. | Connect it to the core EO/EC feature extractor and add “validate your feature table” checks. |
| `examples/tutorials/noplot_tutorial_feature_extraction.py` | Extract EEG features for sex classification. | Covers a real metadata-driven classification workflow. | Add leakage guidance for subject-level splits and explain how sex/gender fields are resolved when both are present. |
| `examples/tutorials/noplot_tutorial_sex_classification_cnn.py` | Train a CNN for sex classification. | Useful deep-learning counterpart to feature-based sex classification. | Add ethical/context caveats, class-balance checks, and a baseline comparison so users do not overinterpret results. |
| `examples/tutorials/noplot_tutorial_age_prediction.py` | Predict age from EEG. | Good applied regression tutorial with setup and caching. | Add expected target distribution, regression metrics to report, and a warning about age confounds across datasets/sites. |
| `examples/tutorials/noplot_tutorial_pfactor_features.py` | Prepare p-factor feature data. | Good feature-preparation entry point for the p-factor task. | Define p-factor at first mention, show expected columns, and link to the regression tutorial/challenge material. |
| `examples/tutorials/noplot_tutorial_pfactor_regression.py` | Predict p-factor from EEG features. | Completes the p-factor path with modeling. | Add metric interpretation, baseline model expectations, and subject/site split guidance. |
| `examples/tutorials/noplot_tutorial_p3_oddball.py` | Classify visual P3 oddball events. | Strong task-specific preprocessing narrative. | Add event-label validation, target/non-target balance checks, and expected epoch shape. |
| `examples/tutorials/noplot_tutorial_audi_oddball.py` | Classify auditory oddball events. | Complements the visual oddball workflow and supports task comparison. | Standardize naming to “auditory” in title/prose, add task-specific validation, and cross-link to visual P3 oddball. |
| `examples/tutorials/plot_clinical_summary.py` | Visualize clinical/categorized metadata summaries. | Useful dataset-discovery and visualization example. | Add validation of required metadata columns, fallback behavior, and what to do when the public API returns sparse metadata. |
| `examples/tutorials/tutorial_transfer_learning.py` | Learn transfer-learning mechanics on simulated data. | Very approachable conceptual introduction using synthetic tensors. | Make the synthetic nature prominent in the title/card and link to real-data transfer tutorials so users do not mistake it for an EEGDash data-loading workflow. |
| `examples/eeg2025/tutorial_challenge_1.py` | Run EEG2025 cross-task transfer-learning workflow. | Useful competition start-kit material with Colab pathway. | Separate competition/community notes from technical setup, add expected submission artifacts, and add a reproducibility checklist. |
| `examples/eeg2025/tutorial_challenge_2.py` | Run EEG2025 p-factor prediction workflow. | Strong competition-specific applied regression path. | Define expected inputs/outputs, scoring metric, local smoke-test size, and common cache/authentication failures. |
| `examples/eeg2025/tutorial_eegdash_offline.py` | Populate and reuse an offline EEGDash cache. | Important operational tutorial for restricted-network environments. | Add “prove it is offline” validation, cache tree examples, and recovery steps for partial downloads. |
| `examples/hpc/tutorial_eoec.py` | Run EO/EC training in an HPC-style environment. | Covers the cluster use case that many EEG users need. | Add scheduler examples, environment-variable checklist, node-local scratch guidance, and log/output validation. |
| `examples/dev_scripts/debug_pybids_braindecode.py` | Debug PyBIDS/Braindecode behavior. | Useful for maintainers and advanced debugging. | Keep it out of the beginner path, label it as developer-facing, and state when users should prefer public tutorials instead. |

## Cross-tutorial gaps found in the full pass

### Expected outputs are inconsistent

Most tutorials should explicitly state the observable result before users run them. Add small sections named “Expected output” or “Validate your result” with:

- Record counts or minimum number of subjects after filtering.
- Epoch/window counts and tensor shapes.
- Feature matrix shape and required columns.
- Metric names, chance levels, and rough plausible ranges.
- Generated files, plots, or cache directories.

### Leakage guidance should be centralized and linked

Several examples involve windows, subjects, tasks, or datasets. The docs should provide one canonical leakage-safe split page and link to it from minimal, EO/EC, sex classification, age prediction, p-factor, P3 oddball, and challenge tutorials.

### Metadata semantics need clearer definitions

Sex, gender, age, p-factor, task, session, run, and dataset fields appear across tutorials. Add a short metadata glossary or link each term to one authoritative explanation.

### Runtime and data requirements need standard labels

A reader should know before clicking whether the tutorial is CPU-only, GPU recommended, online-data dependent, offline-ready, or HPC-oriented.

### Tutorial cards should distinguish real-data and synthetic tutorials

`tutorial_transfer_learning.py` uses simulated data, which is pedagogically useful. Its gallery card should clearly say “simulated data” and point to real-data transfer examples.

## Expansion opportunities

### Add a “choose your path” block

Add a short decision table near the top of the examples index:

| User goal | Start with | Then read |
| --- | --- | --- |
| Load my first dataset | Start Here | Core Decoding Workflow |
| Train a classifier safely | Core Decoding Workflow | Evaluation and Benchmarking |
| Extract classical EEG features | Feature Engineering | How-to recipes |
| Run on a cluster | How-to recipes | High-performance computing |
| Join EEG2025 | Transfer/Foundation Models | EEG 2025 Foundation Challenge |

This would reduce cognitive load for first-time visitors.

### Add per-example metadata

Each example page/card should expose:

- Difficulty: 1, 2, or 3.
- Runtime expectation: under 1 minute, a few minutes, or long-running.
- Compute expectation: CPU-only, GPU optional, GPU recommended, or HPC.
- Data access expectation: online download, cache required, or offline-ready.
- Learning outcome: one sentence that starts with an action verb.

### Expand validation detail on individual tutorials

Every tutorial should end with a small “Validate your result” section that answers:

1. What output shape, metric, or file should I see?
2. What value range is plausible?
3. What are the most common failure modes?
4. How do I know I avoided data leakage?

This would align with a test-driven documentation style: the tutorial states observable outcomes before asking the user to trust the workflow.

### Improve evaluation guidance

The evaluation section should include a compact checklist:

- Split by subject when testing subject generalization.
- Keep preprocessing fit steps inside the training fold.
- Report chance level and class balance.
- Report confidence intervals or paired subject-level statistics.
- Save random seeds and dataset versions.

### Improve offline and HPC documentation

The index already has offline/cache and HPC entries. These can be more actionable if they include:

- Cache directory layout.
- Environment variables to set on shared clusters.
- A small SLURM script annotated line-by-line.
- How to verify that a run did not touch the network.
- When to use node-local scratch versus shared storage.

## Optimization recommendations

### Content optimization

- Replace internal plan references with user-centered outcomes.
- Keep the narrative path but add navigation shortcuts for common personas: beginner, ML researcher, clinical researcher, benchmark maintainer, and cluster user.
- Normalize terminology: choose either “EEG 2025” or “EEG2025” and use it consistently.
- Normalize spelling style across visible titles and labels.
- Add a glossary link for terms such as BIDS, leakage, windows, p-factor, P300, AS-MMD, MOABB, and foundation model.

### Search and discoverability optimization

- Add short descriptions under each gallery card so search snippets expose more than the title.
- Add tags for `loading`, `preprocessing`, `features`, `classification`, `regression`, `evaluation`, `offline`, `HPC`, and `EEG2025`.
- Include canonical tutorial keywords in headings, but avoid internal filenames in user-facing prose unless needed for reproducibility.

### Maintenance optimization

- Add a documentation lint rule that fails on internal-planning phrases such as `plan §Category` or `lines 360-380` in generated gallery text.
- Add a spell/style check for public headings.
- Add a lightweight link check in CI for the examples index and first-level tutorial pages.
- Keep a checklist in PR templates: difficulty, runtime, compute needs, data needs, expected outputs, failure modes, leakage check.

## Proposed next steps

1. Remove the dropped sentence and all internal `plan §Category ... lines ...` references from the gallery source used to generate the examples index.
2. Add metadata fields to each gallery entry: difficulty, runtime, compute, data requirements, and outcome.
3. Add “Validate your result” sections to the highest-traffic tutorials first: Start Here, leakage-safe split, baseline classifier, feature matrix, MOABB benchmark, and offline cache.
4. Add CI documentation checks for internal notes, broken links, and inconsistent public spelling.
5. Use the all-tutorial inventory above as an acceptance checklist so future documentation changes cannot improve only the gallery index while leaving individual tutorials under-specified.
