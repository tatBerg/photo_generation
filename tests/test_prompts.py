from photo_generation.prompts import SCENES, celebrity_prompt, composite_prompt, luxury_prompt


def test_luxury_prompt_mentions_identity_and_scene():
    prompt = luxury_prompt(SCENES[0])
    assert "identity" in prompt
    assert "luxury yacht" in prompt


def test_composite_prompt_mentions_two_images():
    prompt = composite_prompt()
    assert "first reference image" in prompt
    assert "second reference image" in prompt


def test_celebrity_prompt_is_fictional():
    prompt = celebrity_prompt("Example Celebrity")
    assert "Example Celebrity" in prompt
    assert "fictional fan-style" in prompt
