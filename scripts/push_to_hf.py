#!/usr/bin/env python
"""Mirror one or more EEGDash datasets to the ``EEGDash`` Hugging Face org.

Each dataset is materialized via ``EEGDashDataset`` and pushed with braindecode's
``push_to_hub``, which writes a BIDS-inspired Zarr layout under
``sourcedata/braindecode/``. The resulting repo is loadable with
``BaseConcatDataset.pull_from_hub("EEGDash/<slug>")``.

Usage::

    python scripts/push_to_hf.py --dataset ds002718
    python scripts/push_to_hf.py --dataset ds002718 ds003645 --private
    python scripts/push_to_hf.py --from-csv eegdash/dataset/dataset_summary.csv \\
        --max-size-gb 5

Requires ``pip install eegdash braindecode[hub] huggingface_hub`` and
``huggingface-cli login`` (or ``HF_TOKEN`` env var).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import pandas as pd

HF_ORG = "EEGDash"

logger = logging.getLogger("push_to_hf")


def _iter_slugs(args: argparse.Namespace) -> list[str]:
    if args.dataset:
        return list(args.dataset)
    if args.from_csv:
        df = pd.read_csv(args.from_csv)
        if args.max_size_gb is not None:
            cap = args.max_size_gb * 1024**3
            df = df[df["size_bytes"].fillna(0) <= cap]
        return df["dataset"].astype(str).tolist()
    raise SystemExit("Pass --dataset <slug> [...] or --from-csv <path>")


def _push_one(slug: str, args: argparse.Namespace) -> None:
    from eegdash import EEGDashDataset  # noqa: WPS433

    logger.info("Materializing %s", slug)
    ds = EEGDashDataset(dataset=slug, cache_dir=args.cache_dir)
    repo_id = f"{HF_ORG}/{slug}"
    logger.info("Pushing %s (%d recordings)", repo_id, len(ds.datasets))
    ds.push_to_hub(
        repo_id=repo_id,
        commit_message=args.commit_message or f"Upload {slug}",
        private=args.private,
        token=args.token,
        compression=args.compression,
        compression_level=args.compression_level,
    )
    logger.info("Done: https://huggingface.co/datasets/%s", repo_id)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dataset", nargs="+", help="One or more EEGDash slugs (e.g. ds002718)."
    )
    parser.add_argument(
        "--from-csv",
        type=Path,
        help="Read slugs from the 'dataset' column of this CSV.",
    )
    parser.add_argument(
        "--max-size-gb", type=float, help="Skip rows whose size_bytes exceeds this cap."
    )
    parser.add_argument("--cache-dir", type=Path, default=Path("./cache"))
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--token", default=os.environ.get("HF_TOKEN"))
    parser.add_argument("--compression", default="blosc")
    parser.add_argument("--compression-level", type=int, default=5)
    parser.add_argument("--commit-message")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip slugs that already have a repo under EEGDash/.",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    slugs = _iter_slugs(args)

    existing: set[str] = set()
    if args.skip_existing:
        from huggingface_hub import HfApi  # noqa: WPS433

        existing = {
            r.id.split("/", 1)[-1]
            for r in HfApi().list_datasets(author=HF_ORG, limit=1000)
        }

    failed: list[tuple[str, str]] = []
    for slug in slugs:
        if slug in existing:
            logger.info("Skipping %s (already on Hub)", slug)
            continue
        try:
            _push_one(slug, args)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed: %s", slug)
            failed.append((slug, str(exc)))

    if failed:
        logger.error("%d dataset(s) failed:", len(failed))
        for slug, err in failed:
            logger.error("  %s — %s", slug, err)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
