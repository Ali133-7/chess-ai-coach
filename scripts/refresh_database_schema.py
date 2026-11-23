"""Refresh row-free schema documentation in an isolated temporary database."""
import os,tempfile
from pathlib import Path
from unittest.mock import patch

def refresh(output):
 from studio import core
 from studio.app import start
 from studio.knowledge import store
 from scripts.export_public_database import schema
 output=Path(output);output.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='chess-schema-') as folder:
  root=Path(folder)
  with patch.object(core,'DB',root/'studio.sqlite3'),patch.dict(os.environ,{'CHESS_KNOWLEDGE_DB':str(root/'knowledge.sqlite3')}):
   start()
   with core.connection() as db:(output/'studio.schema.sql').write_text(schema(db),encoding='utf8')
   with store.connection() as db:(output/'knowledge.schema.sql').write_text(schema(db),encoding='utf8')

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--output',default='database');args=p.parse_args();refresh(args.output)
