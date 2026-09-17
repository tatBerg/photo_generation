import json
from dataclasses import asdict, dataclass

import redis

from .config import Settings

QUEUE_NAME = "photo_generation:jobs"


@dataclass(frozen=True)
class QueueJob:
    job_id: str
    telegram_id: int


class JobQueue:
    def __init__(self, settings: Settings):
        self.redis = redis.from_url(settings.redis_url, decode_responses=True)

    def enqueue(self, job_id: str, telegram_id: int) -> None:
        self.redis.rpush(QUEUE_NAME, json.dumps(asdict(QueueJob(job_id, telegram_id))))

    def next(self, timeout: int = 5) -> QueueJob | None:
        item = self.redis.blpop(QUEUE_NAME, timeout=timeout)
        if not item:
            return None
        return QueueJob(**json.loads(item[1]))
