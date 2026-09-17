import json
from dataclasses import asdict, dataclass

import redis

from .config import Settings

QUEUE_NAME = "photo_generation:jobs"
PROCESSING_QUEUE_NAME = "photo_generation:jobs:processing"


@dataclass(frozen=True)
class QueueJob:
    job_id: str
    telegram_id: int


@dataclass(frozen=True)
class ClaimedJob:
    job: QueueJob
    raw: str


class JobQueue:
    def __init__(self, settings: Settings):
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)

    def enqueue(self, job_id: str, telegram_id: int) -> bool:
        """Add a job unless the configured backpressure limit was reached."""
        if self.size() >= self.settings.max_queue_size:
            return False
        self.redis.rpush(QUEUE_NAME, json.dumps(asdict(QueueJob(job_id, telegram_id))))
        return True

    def next(self, timeout: int = 5) -> ClaimedJob | None:
        """Atomically move a job to the processing list before returning it."""
        raw = self.redis.brpoplpush(QUEUE_NAME, PROCESSING_QUEUE_NAME, timeout=timeout)
        if not raw:
            return None
        return ClaimedJob(job=QueueJob(**json.loads(raw)), raw=raw)

    def acknowledge(self, claimed: ClaimedJob) -> None:
        self.redis.lrem(PROCESSING_QUEUE_NAME, 1, claimed.raw)

    def recover_pending(self) -> int:
        """Return unacknowledged jobs left by a stopped worker to the queue."""
        pending = self.redis.lrange(PROCESSING_QUEUE_NAME, 0, -1)
        if not pending:
            return 0
        with self.redis.pipeline() as pipeline:
            for raw in pending:
                pipeline.lrem(PROCESSING_QUEUE_NAME, 1, raw)
                pipeline.rpush(QUEUE_NAME, raw)
            pipeline.execute()
        return len(pending)

    def size(self) -> int:
        ready, processing = self.redis.llen(QUEUE_NAME), self.redis.llen(PROCESSING_QUEUE_NAME)
        return ready + processing
