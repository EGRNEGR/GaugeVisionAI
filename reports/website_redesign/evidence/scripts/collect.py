"""Collect website redesign evidence into reports/website_redesign/evidence (compressed JPEG)."""
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None
SRC = Path(sys.argv[1])
DST = Path(sys.argv[2])
VPS = ["1920x1080", "1440x900", "768x1024", "390x844"]


def save(src: Path, dst: Path, width: int | None = None, quality: int = 72, max_h: int | None = None) -> None:
    im = Image.open(src).convert("RGB")
    if width and im.width > width:
        im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    if max_h and im.height > max_h:
        im = im.crop((0, 0, im.width, max_h))
    dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=quality, optimize=True, progressive=True)


old = DST / "screenshots" / "before"
for ver in ("published", "v2", "v3"):
    for vp in VPS:
        f = SRC / ver / f"first_{vp}_t4.png"
        if f.exists():
            save(f, old / ver / f"first_{vp}.jpg", width=1440)
        f = SRC / ver / f"full_{vp}.png"
        if f.exists():
            save(f, old / ver / f"full_{vp}.jpg", width=720 if vp.startswith(("1920", "1440")) else 390, quality=60, max_h=30000)
    a = SRC / ver / "audit.json"
    if a.exists():
        shutil.copy(a, DST / "audit" / f"{ver}_audit.json") if (DST / "audit").mkdir(parents=True, exist_ok=True) is None else None

new = DST / "screenshots" / "after"
acc = SRC / "accept"
for f in acc.glob("v4_*_first.jpg"):
    save(f, new / f.name.replace("v4_", ""), width=1440)
for f in acc.glob("v4_*_full.jpg"):
    w = 720 if any(f.name.startswith("v4_" + p) for p in ("1920", "1440", "1280", "reduced")) else 390
    save(f, new / f.name.replace("v4_", ""), width=w, quality=60, max_h=30000)
for f in sorted(acc.glob("showcase_*.jpg")):
    save(f, DST / "screenshots" / "showcase" / f.name, width=1280, quality=70)
save(acc / "tweaks_1440.jpg", new / "tweaks_1440.jpg", width=1440)
inter = SRC / "interact"
for f in sorted(inter.glob("sec_*.png")) + sorted(inter.glob("story_*.png")):
    save(f, DST / "screenshots" / "sections" / (f.stem + ".jpg"), width=1440, quality=72)

(DST / "acceptance").mkdir(parents=True, exist_ok=True)
shutil.copy(acc / "acceptance.json", DST / "acceptance" / "acceptance.json")
shutil.copy(inter / "interact.json", DST / "acceptance" / "interact.json")
rec = SRC / "rec"
(DST / "recordings").mkdir(parents=True, exist_ok=True)
for f in rec.glob("*.webm"):
    shutil.copy(f, DST / "recordings" / f.name)
total = sum(p.stat().st_size for p in DST.rglob("*") if p.is_file())
print(json.dumps({"files": sum(1 for p in DST.rglob("*") if p.is_file()), "MB": round(total / 2**20, 1)}))
