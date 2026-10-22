"""Retention: clear resume text once it is no longer needed ([retention] in billing.toml).

    python -m app.billing.cli purge-expired      (daily, from cron)

What goes, and when:
- analyses.resume, .jd and .tailored: [retention].analysis_days after the analysis's last
  download, or after it started if it was never downloaded, and never while Claude may
  still be used for it (usable_until). The config keeps analysis_days at least the
  re-download window, so a free re-download always finds its analysis.
- downloads.final_resume (what the signed link renders): download_retention_days after the
  download, by default the re-download window.

What stays: ids, owner, timestamps, inputs_sha256, llm_tailored and tailored_at, what paid
and the credits, because billing, fair-use caps, the free allowance and referral counts
read them. A purged row has purged_at set; the download route answers 410
analysis_expired for it instead of rendering.

Idempotent (only rows with purged_at IS NULL are touched) and batched: each batch of
[retention].batch_size rows is its own transaction, and rows another transaction holds
(a download in progress) are skipped until the next run. Logs counts only, never text.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, null, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.billing.config import BillingConfig
from app.db.models import Analysis, Download

log = logging.getLogger("app.billing")


@dataclass(frozen=True)
class Purged:
    analyses: int
    downloads: int


async def purge_downloads_batch(db: AsyncSession, config: BillingConfig, now: datetime) -> int:
    """Clear final_resume on up to batch_size expired downloads; returns how many."""
    cutoff = now - timedelta(days=config.download_retention_days)
    ids = select(Download.id).where(Download.purged_at.is_(None), Download.created_at < cutoff) \
        .order_by(Download.created_at).limit(config.retention.batch_size).with_for_update(skip_locked=True)
    done = await db.scalars(update(Download).where(Download.id.in_(ids.scalar_subquery()))
                            .values(final_resume=null(), purged_at=now).returning(Download.id)
                            .execution_options(synchronize_session=False))
    return len(done.all())


async def purge_analyses_batch(db: AsyncSession, config: BillingConfig, now: datetime) -> int:
    """Clear resume, jd and tailored on up to batch_size expired analyses; returns how many."""
    cutoff = now - timedelta(days=config.retention.analysis_days)
    recent_download = exists().where(Download.analysis_id == Analysis.id, Download.created_at >= cutoff)
    ids = select(Analysis.id).where(
        Analysis.purged_at.is_(None), Analysis.created_at < cutoff, Analysis.usable_until <= now, ~recent_download,
    ).order_by(Analysis.created_at).limit(config.retention.batch_size).with_for_update(skip_locked=True)
    done = await db.scalars(update(Analysis).where(Analysis.id.in_(ids.scalar_subquery()))
                            .values(resume=null(), jd=null(), tailored=null(), mentor_tip=null(), purged_at=now).returning(Analysis.id)
                            .execution_options(synchronize_session=False))
    return len(done.all())


async def purge_expired(sessions: async_sessionmaker[AsyncSession], config: BillingConfig,
                        now: datetime | None = None) -> Purged:
    """Purge everything past its retention period, one committed batch at a time."""
    now = now or datetime.now(UTC)
    counts = {}
    for name, batch in (("downloads", purge_downloads_batch), ("analyses", purge_analyses_batch)):
        total = 0
        while True:
            async with sessions() as db, db.begin():
                n = await batch(db, config, now)
            total += n
            if n < config.retention.batch_size:
                break
        counts[name] = total
    purged = Purged(**counts)
    log.info("retention purge analyses=%d downloads=%d", purged.analyses, purged.downloads)
    return purged
