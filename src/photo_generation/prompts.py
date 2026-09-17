from dataclasses import dataclass


@dataclass(frozen=True)
class Scene:
    key: str
    title: str
    prompt: str


SCENES = (
    Scene("yacht", "Яхта на закате", "on a luxury yacht at sunset, elegant resort clothing, cinematic travel editorial"),
    Scene("jet", "Частный самолёт", "inside a private jet, premium interior, natural window light, luxury lifestyle editorial"),
    Scene("hotel", "Дорогой отель", "in a five-star hotel suite, refined outfit, warm architectural lighting, realistic editorial photo"),
    Scene("car", "Спорткар", "next to an exotic sports car in Monaco, golden-hour light, realistic fashion campaign"),
)


def luxury_prompt(scene: Scene) -> str:
    return (
        f"Create a photorealistic aspirational lifestyle photograph using the person in the reference image. "
        f"Place the same person {scene.prompt}. Preserve their identity, age, body proportions, and natural expression. "
        "Keep hands, eyes, and anatomy realistic. The subject is fully clothed in a non-sexual pose; "
        "do not add nudity, lingerie, cleavage, or erotic styling. Do not add text, logos, or watermarks."
    )


def celebrity_prompt(name: str) -> str:
    return (
        f"Create a clearly fictional fan-style photograph of the person in the first reference image together with {name}. "
        "Make it look like a posed red-carpet or event photo, but do not imply that the meeting actually happened. "
        "Preserve the user's identity and make both people anatomically realistic. Keep everyone fully clothed "
        "in non-sexual poses. Do not add captions, logos, or text."
    )


def composite_prompt() -> str:
    return (
        "Place the person from the first reference image naturally into the scene from the second reference image. "
        "Preserve the person's identity, face, body proportions, and clothing as much as possible. "
        "Match perspective, lighting, color temperature, shadows, depth of field, and camera grain. "
        "The final image must look like one coherent realistic photograph. Keep the subject fully clothed "
        "in a non-sexual pose. Do not add text or logos."
    )
