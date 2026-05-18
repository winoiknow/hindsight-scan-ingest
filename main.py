#!/usr/bin/env python3
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

import click
from apscheduler.schedulers.blocking import BlockingScheduler

from hindsight_ingest.config import Config, load_config
from hindsight_ingest.ingester import Ingester
from hindsight_ingest.manifest import Manifest
from hindsight_ingest.scanner import scan_for_changes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_scan(config: Config, manifest: Manifest, ingester: Ingester) -> None:
    logger.info("Scanning %d folder(s)…", len(config.folders))
    changed = scan_for_changes(config, manifest)
    logger.info("%d new/changed file(s) found", len(changed))
    ok = err = 0
    for path, file_hash in changed:
        if ingester.ingest(path, file_hash, manifest):
            ok += 1
        else:
            err += 1
    logger.info("Scan complete — %d ingested, %d failed", ok, err)


@click.command()
@click.option("--config", "config_path", default="config.yaml", show_default=True,
              type=click.Path(), help="Path to config.yaml")
@click.option("--server-url", default=None, help="Override server_url")
@click.option("--api-key", default=None, help="Override api_key (for cloud deployments)")
@click.option("--bank-id", default=None, help="Override bank_id")
@click.option("--source", default=None, help="Override source/context label")
@click.option("--session", default=None, help="Override session tag")
@click.option("--folder", "extra_folders", multiple=True, metavar="PATH",
              help="Add a watched folder (repeatable)")
@click.option("--interval", "interval_minutes", default=None, type=float,
              help="Override scan_interval_minutes")
@click.option("--once", is_flag=True, default=False,
              help="Run one scan pass then exit (good for cron)")
@click.option("--db", "db_path", default="ingestion_manifest.db", show_default=True,
              type=click.Path(), help="SQLite manifest database path")
def main(
    config_path: str,
    server_url: Optional[str],
    api_key: Optional[str],
    bank_id: Optional[str],
    source: Optional[str],
    session: Optional[str],
    extra_folders: tuple,
    interval_minutes: Optional[float],
    once: bool,
    db_path: str,
) -> None:
    """Scan folders and ingest documents into Vectorize Hindsight."""
    cfg_file = Path(config_path)
    if cfg_file.exists():
        config = load_config(cfg_file)
    else:
        logger.warning("config.yaml not found at %s — using defaults", cfg_file)
        config = Config()

    # Apply CLI overrides
    overrides: dict = {}
    if server_url:
        overrides["server_url"] = server_url
    if api_key:
        overrides["api_key"] = api_key
    if bank_id:
        overrides["bank_id"] = bank_id
    if source:
        overrides["source"] = source
    if session:
        overrides["session"] = session
    if interval_minutes is not None:
        overrides["scan_interval_minutes"] = interval_minutes
    if extra_folders:
        overrides["folders"] = list(config.folders) + list(extra_folders)
    if overrides:
        config = config.model_copy(update=overrides)

    if not config.folders:
        logger.error("No folders configured. Add paths in config.yaml or via --folder.")
        sys.exit(1)

    manifest = Manifest(Path(db_path))
    ingester = Ingester(config)

    try:
        if once:
            run_scan(config, manifest, ingester)
        else:
            run_scan(config, manifest, ingester)
            scheduler = BlockingScheduler()
            scheduler.add_job(
                run_scan,
                "interval",
                minutes=config.scan_interval_minutes,
                args=[config, manifest, ingester],
            )
            logger.info(
                "Scheduler active — next scan in %.1f min. Ctrl-C to stop.",
                config.scan_interval_minutes,
            )
            try:
                scheduler.start()
            except (KeyboardInterrupt, SystemExit):
                logger.info("Shutting down.")
    finally:
        ingester.close()
        manifest.close()


if __name__ == "__main__":
    main()
