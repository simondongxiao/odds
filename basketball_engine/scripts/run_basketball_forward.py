"""Backward-compatible positional wrapper for the real daily pipeline."""
import json,sys
from repair_v22.pipeline import execute

def run(date,root): return execute(root,date,live=True)
if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit('usage: run_basketball_forward.py YYYY-MM-DD OUTPUT_ROOT')
    print(json.dumps(run(sys.argv[1],sys.argv[2]),ensure_ascii=False,indent=2))
