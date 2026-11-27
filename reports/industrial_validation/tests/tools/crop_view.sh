#!/bin/sh
# crop.sh qid x0 y0 x1 y1  (без координат — всё изображение)
T="/c/Hakatons/GaugeVisionAIDesign DashBoard/.claude/worktrees/next-gen/reports/industrial_validation/tests/annot_view.py"
f=$(ls /c/Hakatons/gv_cv_validation/datasets/measurebench/export/img/$1.* | head -1)
q=$1; shift
/c/C1/GaugeVS/.venv/Scripts/python.exe -I "$T" "$f" /c/Hakatons/gv_cv_validation/cvwork/annot/c_$q.jpg "$@"
