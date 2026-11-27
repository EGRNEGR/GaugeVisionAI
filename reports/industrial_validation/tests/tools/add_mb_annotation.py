"""add.py qid "x0 y0 x1 y1|full" cvx cvy fvx fvy lvx lvy vmin vmax unit [note] [tags,comma] [direction]
Пересчёт координат вида annot_view.py (поле 34 px, max 900) в пиксели исходного изображения."""
import sys, json, glob, cv2
a = sys.argv[1:]
qid, box = a[0], a[1]
img = cv2.imread(glob.glob(f"C:/Hakatons/gv_cv_validation/datasets/measurebench/export/img/{qid}.*")[0])
h, w = img.shape[:2]
if box == "full":
    x0, y0, x1, y1 = 0, 0, w, h
else:
    x0, y0, x1, y1 = map(int, box.split())
    x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
k = 900 / max(x1 - x0, y1 - y0)
conv = lambda vx, vy: [round(x0 + (float(vx) - 34) / k, 1), round(y0 + (float(vy) - 34) / k, 1)]
c, f, l = conv(a[2], a[3]), conv(a[4], a[5]), conv(a[6], a[7])
item = dict(center=c, first=f, last=l, v_min=float(a[8]), v_max=float(a[9]), unit=a[10])
if len(a) > 11 and a[11]: item["note"] = a[11]
if len(a) > 12 and a[12]: item["tags"] = a[12].split(",")
if len(a) > 13 and a[13]: item["direction"] = a[13]
p = "C:/Hakatons/GaugeVisionAIDesign DashBoard/.claude/worktrees/next-gen/reports/industrial_validation/data/mb_calibration.json"
doc = json.load(open(p, encoding="utf-8"))
doc["items"][qid] = item
json.dump(doc, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(qid, item, len(doc["items"]))
