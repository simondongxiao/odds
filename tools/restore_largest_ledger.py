#!/usr/bin/env python3
"""Restore the largest valid historical ledger blob from gh-pages history."""
from __future__ import annotations
import argparse, json, subprocess, tempfile
from pathlib import Path

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--ref',default='origin/gh-pages'); ap.add_argument('--repo-path',required=True); ap.add_argument('--output',required=True); args=ap.parse_args()
    try:
        commits=subprocess.check_output(['git','log','--format=%H',args.ref,'--',args.repo_path],text=True).splitlines()
    except subprocess.CalledProcessError:
        commits=[]
    best=None; best_rows=-1
    for commit in commits[:80]:
        try:
            raw=subprocess.check_output(['git','show',f'{commit}:{args.repo_path}'],stderr=subprocess.DEVNULL)
            payload=json.loads(raw.decode('utf-8'))
            rows=payload if isinstance(payload,list) else payload.get('rows',[])
            if not isinstance(rows,list): continue
            if len(rows)>best_rows:
                best_rows=len(rows); best=raw
        except (subprocess.CalledProcessError,UnicodeDecodeError,json.JSONDecodeError,TypeError):
            continue
    if best is None: return 0
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile('wb',delete=False,dir=out.parent,suffix='.tmp') as h:
        h.write(best); tmp=Path(h.name)
    tmp.replace(out)
    print(f'restored={out} rows={best_rows}')
    return 0
if __name__=='__main__': raise SystemExit(main())
