"""Image generation tool using Stability AI."""
from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

STABILITY_API_URL = "https://api.stability.ai/v2beta/stable-image/generate/core"

VALID_ASPECT_RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "21:9", "9:21"}

VALID_STYLES = {
    "photographic", "digital-art", "anime", "cinematic", "comic-book",
    "fantasy-art", "line-art", "analog-film", "neon-punk", "isometric",
    "low-poly", "origami", "modeling-compound", "pixel-art", "tile-texture",
    "3d-model", "enhance",
}


async def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    style_preset: str = "",
    negative_prompt: str = "",
    output_path: str = "",
    api_key: str = "",
    **kw,
) -> str:
    """Generate an image from a text prompt using Stability AI.

    Returns the absolute path to the saved PNG file on success,
    or '[ERROR] ...' on failure.
    """
    if not api_key:
        return (
            "[ERROR] Stability AI API key not configured. "
            "Add stability.api_key to config/butler.yaml."
        )
    if not prompt.strip():
        return "[ERROR] A prompt is required."

    if aspect_ratio not in VALID_ASPECT_RATIOS:
        aspect_ratio = "1:1"

    if not output_path:
        output_path = f"./data/media/gen_{int(time.time())}.png"

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    try:
        import aiohttp

        form = aiohttp.FormData()
        form.add_field("prompt", prompt)
        form.add_field("aspect_ratio", aspect_ratio)
        form.add_field("output_format", "png")
        if style_preset and style_preset in VALID_STYLES:
            form.add_field("style_preset", style_preset)
        if negative_prompt:
            form.add_field("negative_prompt", negative_prompt)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "image/*",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                STABILITY_API_URL,
                headers=headers,
                data=form,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status == 200:
                    image_bytes = await resp.read()
                    with open(output_path, "wb") as f:
                        f.write(image_bytes)
                    logger.info("Image saved to %s (%d bytes)", output_path, len(image_bytes))
                    return output_path
                else:
                    err = await resp.text()
                    return f"[ERROR] Stability API {resp.status}: {err[:300]}"

    except Exception as e:
        return f"[ERROR] generate_image: {e}"
