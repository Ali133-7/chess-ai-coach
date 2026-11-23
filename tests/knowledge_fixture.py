"""Build a reusable public-only fixture from bundled assets, independently of a checkout path."""
import os,tempfile
from pathlib import Path
from studio import core
from studio.knowledge import store,importer

_temporary=None
_gold=None

def public_knowledge_fixture():
    global _temporary,_gold
    explicit=os.getenv('CHESS_TEST_KNOWLEDGE_GOLD')
    if explicit:
        path=Path(explicit)
        if not path.is_file():raise FileNotFoundError('CHESS_TEST_KNOWLEDGE_GOLD must point to an existing public test fixture')
        return path
    if _gold is not None:return _gold
    _temporary=tempfile.TemporaryDirectory(prefix='chess-public-fixture-')
    folder=Path(_temporary.name);old_db=core.DB;old_env=os.environ.get('CHESS_KNOWLEDGE_DB')
    try:
        core.DB=folder/'main.sqlite3';os.environ['CHESS_KNOWLEDGE_DB']=str(folder/'knowledge.sqlite3')
        core.setup();store.setup();importer.seed()
        with store.connection() as db:
            if db.execute('SELECT count(*) FROM kc_openings').fetchone()[0]<3800:raise ValueError('Incomplete public opening fixture')
        _gold=folder/'knowledge.sqlite3'
        return _gold
    finally:
        core.DB=old_db
        if old_env is None:os.environ.pop('CHESS_KNOWLEDGE_DB',None)
        else:os.environ['CHESS_KNOWLEDGE_DB']=old_env
