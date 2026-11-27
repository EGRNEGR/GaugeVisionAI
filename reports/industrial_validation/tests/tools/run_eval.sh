#!/bin/sh
# run_eval.sh <code_root> <label> <out_dir> [subsets...]
CODE=$1; LABEL=$2; OUT=$3; shift 3
NG="/c/Hakatons/GaugeVisionAIDesign DashBoard/.claude/worktrees/next-gen/reports/industrial_validation"
T=${GV_CV_ROOT:-/c/Hakatons/gv_cv_validation}
export CUDA_VISIBLE_DEVICES="" GAUGEVISION_DEVICE=cpu PYTHONIOENCODING=utf-8
for s in "$@"; do
  if [ "$s" = unusable ]; then extra="--unusable"; sub=primary
  elif [ "$s" = unusable_dev ]; then extra="--unusable"; sub=dev
  else extra=""; sub=$s; fi
  /c/C1/GaugeVS/.venv/Scripts/python.exe "$NG/tests/eval_cv_pipeline.py" --code-root "$CODE" --manifest "$NG/data/dataset_manifest.json" \
    --meterfl $T/datasets/meterfl --measurebench $T/datasets/measurebench/export --subset $sub --label $LABEL --out "$OUT" $extra 2>&1 | tail -2
done
/c/C1/GaugeVS/.venv/Scripts/python.exe "$NG/tests/summarize_cv.py" --runs "$OUT" --label $LABEL --manifest "$NG/data/dataset_manifest.json" --meterfl $T/datasets/meterfl
