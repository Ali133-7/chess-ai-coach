"""Unpack the licensed public master seed; never read a user database."""
from pathlib import Path
import gzip, hashlib, json, os, shutil, tempfile

def prepare():
    data=Path(__file__).resolve().parents[1]/'studio/knowledge/data'
    dest=data/'master-games.sqlite3'
    expected=json.loads((data/'master-games-manifest.json').read_text(encoding='utf8'))['seed_sha256']
    def digest(path):
        h=hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
        return h.hexdigest()
    if dest.exists():
        if digest(dest)!=expected:raise ValueError('Existing public seed differs from its manifest')
        return dest
    fd,name=tempfile.mkstemp(prefix='master-seed-',dir=data)
    tmp=Path(name)
    try:
        with os.fdopen(fd,'wb') as out,gzip.open(data/'master-games.sqlite3.gz','rb') as src:shutil.copyfileobj(src,out)
        if digest(tmp)!=expected:raise ValueError('Public seed checksum mismatch')
        tmp.replace(dest)
    finally:tmp.unlink(missing_ok=True)
    return dest

if __name__=='__main__':print('PUBLIC_SEED_READY',prepare().name)
