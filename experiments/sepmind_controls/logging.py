import json, time
from datetime import datetime, timezone
from pathlib import Path

class Ledger:
    def __init__(self, path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.start=time.monotonic();self.index=0
    def emit(self, kind, **values):
        self.index+=1
        row={'event':self.index,'kind':kind,'utc':datetime.now(timezone.utc).isoformat(),
             'elapsed_s':time.monotonic()-self.start,**values}
        with self.path.open('a',encoding='utf8') as f:
            f.write(json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n');f.flush()
        return row

def save(path, data):
    from sepmind.engineering.tools.atomic_recovery import save as atomic_save
    atomic_save(Path(path),data)
