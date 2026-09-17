import base64
import logging
from pathlib import Path
from typing import Protocol

from .config import Settings

logger = logging.getLogger(__name__)


class ImageProvider(Protocol):
    name: str

    def edit(self, prompt: str, main_path: Path, reference_path: Path | None = None) -> bytes:
        ...


class MockProvider:
    name = "mock"

    def edit(self, prompt: str, main_path: Path, reference_path: Path | None = None) -> bytes:
        from io import BytesIO

        from PIL import Image, ImageDraw

        source = Image.open(main_path).convert("RGB")
        source.thumbnail((1600, 1600))
        draw = ImageDraw.Draw(source)
        draw.rectangle((0, 0, source.width, 56), fill="#241f1b")
        draw.text((18, 18), "DEMO • MOCK_MODE=true", fill="#ffffff")
        output = BytesIO()
        source.save(output, format="JPEG", quality=88)
        return output.getvalue()


class OpenAIProvider:
    name = "openai"

    def __init__(self, settings: Settings):
        from openai import OpenAI

        self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_image_model

    def edit(self, prompt: str, main_path: Path, reference_path: Path | None = None) -> bytes:
        with open(main_path, "rb") as main_file:
            if reference_path:
                with open(reference_path, "rb") as reference_file:
                    result = self.client.images.edit(
                        model=self.model, image=[main_file, reference_file], prompt=prompt
                    )
            else:
                result = self.client.images.edit(model=self.model, image=main_file, prompt=prompt)
        return base64.b64decode(result.data[0].b64_json)


class FalProvider:
    name = "fal"

    def __init__(self, model: str, key: str):
        import fal_client

        self.fal_client = fal_client.SyncClient(key=key)
        self.model = model

    def edit(self, prompt: str, main_path: Path, reference_path: Path | None = None) -> bytes:
        import urllib.request

        urls = [self.fal_client.upload_file(str(main_path))]
        if reference_path:
            urls.append(self.fal_client.upload_file(str(reference_path)))
        result = self.fal_client.subscribe(self.model, arguments={"prompt": prompt, "image_urls": urls})
        with urllib.request.urlopen(result["images"][0]["url"], timeout=120) as response:
            return response.read()


class FallbackProvider:
    """Use a secondary provider when the primary provider is unavailable."""

    def __init__(self, primary: ImageProvider, fallback: ImageProvider):
        self.primary = primary
        self.fallback = fallback
        self.name = f"{primary.name}->{fallback.name}"

    def edit(self, prompt: str, main_path: Path, reference_path: Path | None = None) -> bytes:
        try:
            return self.primary.edit(prompt, main_path, reference_path)
        except Exception:
            logger.exception("Primary image provider %s failed; using %s", self.primary.name, self.fallback.name)
            return self.fallback.edit(prompt, main_path, reference_path)


class ProviderRouter:
    def __init__(self, settings: Settings):
        self.settings = settings
        if settings.mock_mode:
            self.mock = MockProvider()
            self.openai = self.fal_identity = self.fal_composite = self.fal_luxury = None
        else:
            self.mock = None
            self.openai = OpenAIProvider(settings) if settings.openai_api_key else None
            self.fal_identity = FalProvider(settings.fal_model_identity, settings.fal_key) if settings.fal_key else None
            self.fal_composite = FalProvider(settings.fal_model_composite, settings.fal_key) if settings.fal_key else None
            self.fal_luxury = FalProvider(settings.fal_model_luxury, settings.fal_key) if settings.fal_key else None

    def choose(self, mode: str, has_reference: bool = False) -> ImageProvider:
        if self.mock:
            return self.mock
        if mode == "composite" and self.fal_composite:
            return FallbackProvider(self.fal_composite, self.openai) if self.openai else self.fal_composite
        if mode == "celebrity" and has_reference and self.fal_identity:
            return FallbackProvider(self.fal_identity, self.openai) if self.openai else self.fal_identity
        # The current fal.ai Nano Banana 2 API is documented as text-to-image
        # and does not expose the image_urls input used by our edit adapters.
        # Prefer the OpenAI image-edit endpoint for the user's uploaded photo;
        # keep fal.ai for the identity/composite adapters that accept images.
        if mode == "luxury" and self.openai:
            return self.openai
        if mode == "luxury" and self.fal_luxury:
            return self.fal_luxury
        if self.openai:
            return self.openai
        raise RuntimeError("No image provider is configured")
