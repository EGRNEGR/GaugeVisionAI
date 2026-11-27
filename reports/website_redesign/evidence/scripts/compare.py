"""Side-by-side first screens: published / v2 / v4 with captions."""
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
E = Path(sys.argv[1])
rows = [("1920x1080", "1920x1080"), ("390x844", "390x844")]
font = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 26)
for vp, name in rows:
    paths = [("Опубликованный сайт (= v3)", E / "before/published" / f"first_{vp}.jpg"), ("v2", E / "before/v2" / f"first_{vp}.jpg"), ("v4", E / "after" / f"{vp}_first.jpg")]
    ims = [(c, Image.open(p).convert("RGB")) for c, p in paths]
    w = 900 if vp.startswith("1920") else 360
    ims = [(c, im.resize((w, round(im.height * w / im.width)))) for c, im in ims]
    h = max(im.height for _, im in ims)
    out = Image.new("RGB", (w * 3 + 40, h + 60), "#0b0e13")
    d = ImageDraw.Draw(out)
    for i, (c, im) in enumerate(ims):
        x = i * (w + 20)
        out.paste(im, (x, 60))
        d.text((x + 8, 14), c, fill="#e8eef4", font=font)
    out.save(E / f"compare_first_{name}.jpg", quality=78, optimize=True)
    print(name, out.size)
