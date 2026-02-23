"""Image generation tool using Stability AI."""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

STABILITY_API_URL = (
    "https://api.stability.ai/v1/generation/"
    "stable-diffusion-xl-1024-v1-0/text-to-image"
)

# SDXL-supported dimensions keyed by aspect-ratio string
_DIMENSIONS = {
    "1:1":  (1024, 1024),
    "16:9": (1344, 768),
    "9:16": (768, 1344),
    "4:3":  (1152, 896),
    "3:4":  (896, 1152),
    "21:9": (1536, 640),
    "9:21": (640, 1536),
}

VALID_ASPECT_RATIOS = set(_DIMENSIONS.keys())

VALID_STYLES = {
    "photographic", "digital-art", "anime", "cinematic", "comic-book",
    "fantasy-art", "line-art", "analog-film", "neon-punk", "isometric",
    "low-poly", "origami", "modeling-compound", "pixel-art", "tile-texture",
    "3d-model", "enhance",
}


def _sync_generate(prompt, aspect_ratio, style_preset, negative_prompt, output_path, api_key):
    """Blocking HTTP call — executed in a thread pool."""
    import requests

    width, height = _DIMENSIONS.get(aspect_ratio, (1024, 1024))

    body = {
        "text_prompts": [{"text": prompt, "weight": 1.0}],
        "width": width,
        "height": height,
        "steps": 40,
        "cfg_scale": 7,
        "samples": 1,
    }
    if style_preset and style_preset in VALID_STYLES:
        body["style_preset"] = style_preset
    if negative_prompt:
        body["text_prompts"].append({"text": negative_prompt, "weight": -1.0})

    resp = requests.post(
        STABILITY_API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json=body,
        timeout=120,
    )

    if resp.status_code == 200:
        data = resp.json()
        artifact = data["artifacts"][0]
        if artifact.get("finishReason") != "SUCCESS":
            return f"[ERROR] Generation failed: {artifact.get('finishReason')}"
        image_bytes = base64.b64decode(artifact["base64"])
        with open(output_path, "wb") as f:
            f.write(image_bytes)
        return output_path
    else:
        return f"[ERROR] Stability API {resp.status_code}: {resp.text[:300]}"


async def generate_image(
    prompt: str,
    aspect_ratio: str = "1:1",
    style_preset: str = "",
    negative_prompt: str = "",
    output_path: str = "",
    api_key: str = "",
    **kw,
) -> str:
    """Generate an image from a text prompt using Stability AI (SDXL).

    Returns the path to the saved PNG file on success, or '[ERROR] ...' on failure.
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
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            _sync_generate,
            prompt, aspect_ratio, style_preset, negative_prompt, output_path, api_key,
        )
        if not result.startswith("[ERROR]"):
            logger.info("Image saved to %s", result)
        return result
    except Exception as e:
        return f"[ERROR] generate_image: {e}"
