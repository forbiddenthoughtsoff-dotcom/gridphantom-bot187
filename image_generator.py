import requests
import os
import logging
import random
import urllib.parse
from io import BytesIO
from PIL import Image

logger = logging.getLogger(__name__)

W, H = 1080, 1920
RESAMPLE = Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.LANCZOS


def generate_with_fal(prompt: str) -> Image.Image:
    """Generate image via Fal.ai FLUX — best quality, fast."""
    fal_key = os.environ.get('FAL_KEY', '')
    if not fal_key:
        raise ValueError("FAL_KEY not set")

    url = "https://fal.run/fal-ai/flux-pro/v1.1"
    payload = {
        "prompt": prompt,
        "image_size": "portrait_9_16",
        "num_inference_steps": 28,
        "guidance_scale": 3.5,
        "num_images": 1,
        "safety_tolerance": "5"
    }
    r = requests.post(url, json=payload, timeout=60,
                      headers={'Authorization': f'Key {fal_key}',
                               'Content-Type': 'application/json'})
    r.raise_for_status()
    data = r.json()
    img_url = data['images'][0]['url']
    img_data = requests.get(img_url, timeout=30).content
    img = Image.open(BytesIO(img_data)).convert('RGB')
    if img.size != (W, H):
        img = img.resize((W, H), RESAMPLE)
    logger.info(f"✅ Fal.ai FLUX image: {img.size}")
    return img


def generate_with_pollinations(prompt: str) -> Image.Image:
    """Fallback: Pollinations.ai — free, no key."""
    encoded = urllib.parse.quote(prompt[:300])
    url = (f"https://image.pollinations.ai/prompt/{encoded}"
           f"?width={W}&height={H}&nologo=true&model=flux&seed={random.randint(1,9999)}")
    r = requests.get(url, timeout=80, headers={'User-Agent': 'GridPhantomBot/1.0'})
    r.raise_for_status()
    img = Image.open(BytesIO(r.content)).convert('RGB')
    if img.size != (W, H):
        img = img.resize((W, H), RESAMPLE)
    logger.info(f"✅ Pollinations fallback: {img.size}")
    return img


def generate_with_unsplash(prompt: str) -> Image.Image:
    """Last resort: real photo from Unsplash."""
    keywords = prompt.split(',')[0].strip().replace(' ', '+')[:50]
    url = f"https://source.unsplash.com/1080x1920/?{keywords}"
    r = requests.get(url, timeout=15, headers={'User-Agent': 'GridPhantomBot/1.0'})
    r.raise_for_status()
    img = Image.open(BytesIO(r.content)).convert('RGB')
    img = img.resize((W, H), RESAMPLE)
    logger.info(f"✅ Unsplash fallback: {img.size}")
    return img


def get_background_image(prompt: str) -> Image.Image:
    """Try Fal.ai → Pollinations → Unsplash → dark gradient."""
    for name, fn in [
        ("Fal.ai FLUX", generate_with_fal),
        ("Pollinations", generate_with_pollinations),
        ("Unsplash", generate_with_unsplash),
    ]:
        try:
            return fn(prompt)
        except Exception as e:
            logger.warning(f"{name} failed: {e}")

    # Dark gradient fallback
    logger.warning("All image sources failed, using gradient")
    img = Image.new('RGB', (W, H), (15, 15, 25))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    for y in range(H):
        v = int(15 + 25 * y / H)
        draw.line([(0, y), (W, y)], fill=(v, v, v + 15))
    return img
