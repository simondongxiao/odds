from __future__ import annotations
from pathlib import Path
def health(name, **fields): return {'source':name,'parser_version':'mvp-1',**fields}
def save_raw(path, body):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body);return str(p)
