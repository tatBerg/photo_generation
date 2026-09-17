import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from .config import Settings
from .db import Job, SessionLocal, User
from .providers import ProviderRouter


class GenerationService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.router = ProviderRouter(settings)
        Path(settings.media_dir).mkdir(parents=True, exist_ok=True)

    def get_or_create_user(self, telegram_id: int) -> User:
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.telegram_id == telegram_id).with_for_update())
            if not user:
                user = User(telegram_id=telegram_id)
                session.add(user)
                session.commit()
            return user

    def reserve_generation(self, telegram_id: int) -> tuple[bool, str]:
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.telegram_id == telegram_id).with_for_update())
            if not user:
                user = User(telegram_id=telegram_id)
                session.add(user)
                session.flush()
            today = datetime.now(UTC).date().isoformat()
            if user.credits > 0:
                user.credits -= 1
                session.commit()
                return True, "credit"
            if user.free_used_on != today:
                user.free_used_on = today
                session.commit()
                return True, "free"
            return False, "limit"

    def reset_free_limit(self, telegram_id: int) -> None:
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.telegram_id == telegram_id))
            if user:
                user.free_used_on = None
                session.commit()

    def refund_generation(self, telegram_id: int, charge_type: str) -> None:
        """Return a generation when the provider failed before a result existed."""
        with SessionLocal() as session:
            user = session.scalar(select(User).where(User.telegram_id == telegram_id).with_for_update())
            if not user:
                return
            if charge_type == "credit":
                user.credits += 1
            elif charge_type == "free":
                today = datetime.now(UTC).date().isoformat()
                if user.free_used_on == today:
                    user.free_used_on = None
            session.commit()

    def create_job(
        self,
        telegram_id: int,
        mode: str,
        prompt: str,
        main_path: Path,
        reference_path: Path | None,
        job_id: str | None = None,
        paid: bool = False,
    ) -> str:
        job_id = job_id or str(uuid.uuid4())
        with SessionLocal() as session:
            session.add(Job(id=job_id, telegram_id=telegram_id, mode=mode, prompt=prompt,
                            main_path=str(main_path), reference_path=str(reference_path) if reference_path else None,
                            paid=paid))
            session.commit()
        return job_id

    def process_job(self, job_id: str) -> Path:
        with SessionLocal() as session:
            job = session.get(Job, job_id)
            if not job:
                raise ValueError(f"Unknown job: {job_id}")
            job.status = "processing"
            reference_path = Path(job.reference_path) if job.reference_path else None
            provider = self.router.choose(job.mode, has_reference=reference_path is not None)
            job.provider = provider.name
            session.commit()
            main_path = Path(job.main_path)

        try:
            result = provider.edit(job.prompt, main_path, reference_path)
            output_path = Path(self.settings.media_dir) / job_id / "result.jpg"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(result)
            with SessionLocal() as session:
                job = session.get(Job, job_id)
                job.status = "completed"
                job.output_path = str(output_path)
                job.completed_at = datetime.now(UTC)
                session.commit()
            return output_path
        except Exception as error:
            with SessionLocal() as session:
                job = session.get(Job, job_id)
                # A failed provider call must not consume the user's free
                # generation or paid credit. The processing status guard keeps
                # a repeated handling attempt from refunding twice.
                if job and job.status == "processing":
                    user = session.scalar(
                        select(User).where(User.telegram_id == job.telegram_id).with_for_update()
                    )
                    if user:
                        if job.paid:
                            user.credits += 1
                        else:
                            today = datetime.now(UTC).date().isoformat()
                            if user.free_used_on == today:
                                user.free_used_on = None
                if job:
                    job.status = "failed"
                    job.error_message = str(error)[:2000]
                session.commit()
            raise
