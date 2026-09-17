"""Remove expired source and result images from storage."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from .config import get_settings
from .db import Job, SessionLocal, init_db
from .storage import MediaStorage

logger = logging.getLogger(__name__)


def purge_expired_media() -> int:
    settings = get_settings()
    cutoff = datetime.now(UTC) - timedelta(hours=settings.result_ttl_hours)
    storage = MediaStorage(settings)
    with SessionLocal() as session:
        jobs = session.scalars(
            select(Job).where(
                Job.status.in_(("completed", "failed")),
                Job.created_at < cutoff,
            )
        ).all()
        purged_ids = []
        for job in jobs:
            deleted = True
            for stored in (job.main_path, job.reference_path, job.output_path):
                if stored:
                    try:
                        storage.delete(stored)
                    except Exception:
                        deleted = False
                        logger.exception("Could not delete media for job %s", job.id)
            if deleted:
                purged_ids.append(job.id)
        if purged_ids:
            session.execute(delete(Job).where(Job.id.in_(purged_ids)))
            session.commit()
        return len(purged_ids)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_db()
    logger.info("Purged %s expired jobs", purge_expired_media())


if __name__ == "__main__":
    main()
