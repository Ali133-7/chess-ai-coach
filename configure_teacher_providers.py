"""Run interactively inside studio; never pass API keys as command arguments."""
import argparse
import getpass
import json
import os
from pathlib import Path
import tempfile


def atomic(path, data):
    fd, temp = tempfile.mkstemp(prefix='.teacher-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    names = ('groq','xai','openrouter','openai')
    parser.add_argument('--primary', required=True, choices=names)
    parser.add_argument('--fallback', nargs='*', default=[], choices=names)
    parser.add_argument('--model', action='append', default=[], metavar='PROVIDER=MODEL')
    args = parser.parse_args()
    order = [args.primary] + args.fallback
    if len(set(order)) != len(order):
        parser.error('Duplicate provider')
    try:
        models = dict(item.split('=',1) for item in args.model)
        if set(models) != set(order) or any(not x.strip() or len(x)>160 for x in models.values()):
            raise ValueError()
    except ValueError:
        parser.error('Supply exactly one --model PROVIDER=MODEL for each selected provider')
    root = Path('/studio-data')
    if not root.is_dir():
        parser.error('/studio-data must be the existing private persistent volume')
    import fcntl
    with (root/'.teacher-config.lock').open('a') as lock:
        os.chmod(root/'.teacher-config.lock',0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        providers = {}
        for name in order:
            path = root/('.'+name+'_api_key')
            key = getpass.getpass(name+' API key (blank keeps existing private file): ')
            if key:
                if len(key)<15 or len(key)>4096 or not key.isascii() or any(c.isspace() for c in key):
                    parser.error('Invalid key shape')
                atomic(path, key+'\n')
            elif not path.is_file() or path.is_symlink() or path.stat().st_mode & 0o077:
                parser.error('Existing private key unavailable')
            providers[name] = {'model':models[name], 'key_file':str(path)}
        atomic(root/'teacher-providers.json', json.dumps({
            'primary':args.primary,'fallback':args.fallback,'providers':providers}, indent=2)+'\n')
    print('Private provider configuration saved. Keys were not printed. No restart required.')

if __name__ == '__main__':
    main()
