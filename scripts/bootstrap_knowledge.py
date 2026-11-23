"""Explicit, resumable import into the configured database; no accounts are created."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.prepare_public_data import prepare
from studio import core
from studio.teacher_v7.router import setup_teacher
from studio.play_groq import setup_play
from studio.knowledge import store,importer,masters

def main():
    prepare();core.setup();setup_teacher();setup_play();store.setup()
    importer.seed();print(masters.seed())
    from scripts.merge_daily_seed import merge
    merge(str(store.DATA/'generated-public-24.json'))
    print('KNOWLEDGE_READY: public openings, puzzles, master games and historical generated examples')

if __name__=='__main__':main()
