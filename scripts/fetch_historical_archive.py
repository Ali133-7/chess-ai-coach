"""Fetch the versioned CC BY 4.0 Figshare chess deposit through its public API."""
import argparse,hashlib,json,shutil,time
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import httpx

API='https://api.figshare.com/v2/articles/4276523/versions/1'
FILE_ID=6971717
SIZE=870891090
MD5='90bed9e33640e7eab354a40dfd1eddb8'
SHA256='86732c0a23421da5985f5ba40d9db9bf2be1f6e2456b88629c35740ae71be54d'

def hashes(path):
 sha=hashlib.sha256();md5=hashlib.md5(usedforsecurity=False)
 with path.open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):sha.update(block);md5.update(block)
 return sha.hexdigest(),md5.hexdigest()

def allowed(url):
 p=urlsplit(url);host=p.hostname or ''
 return p.scheme=='https' and not p.username and not p.password and (host in ('ndownloader.figshare.com','api.figshare.com','44c1cec316ec56bca76dfd65d2882b20.r2.cloudflarestorage.com') or host.endswith('.amazonaws.com'))

def fetch(directory):
 directory.mkdir(parents=True,exist_ok=True)
 with httpx.Client(timeout=httpx.Timeout(60,read=120),follow_redirects=False,trust_env=False) as client:
  response=client.get(API);response.raise_for_status();meta=response.json()
  if meta.get('license',{}).get('url')!='https://creativecommons.org/licenses/by/4.0/':raise ValueError('Upstream license changed')
  file=next(x for x in meta['files'] if x['id']==FILE_ID)
  if file['name']!='all.pgn.zip' or file['size']!=SIZE or file['computed_md5']!=MD5 or file['download_url']!=f'https://ndownloader.figshare.com/files/{FILE_ID}':raise ValueError('Versioned archive identity changed')
  (directory/'figshare-4276523-v1.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8')
  dest=directory/'all.pgn.zip';part=directory/'all.pgn.zip.part'
  if not dest.exists() and shutil.disk_usage(directory).free<SIZE-(part.stat().st_size if part.exists() else 0)+1024**3:raise OSError('Insufficient space for archive and reserve')
  if dest.exists():
   sha,md5=hashes(dest)
   if dest.stat().st_size!=SIZE or md5!=MD5:raise ValueError('Existing archive differs; preserve it for inspection')
  else:
   if part.exists() and part.stat().st_size==SIZE:
    sha,md5=hashes(part)
    if md5!=MD5:raise ValueError('Partial archive checksum mismatch')
    part.replace(dest)
   else:
    for attempt in range(6):
     try:
      offset=part.stat().st_size if part.exists() else 0
      if offset>SIZE:raise ValueError('Oversized partial archive')
      url=file['download_url']
      for redirect in range(6):
       if not allowed(url):raise ValueError('Unapproved archive redirect')
       with client.stream('GET',url,headers={'Range':f'bytes={offset}-'} if offset else {}) as archive:
        if archive.status_code in (301,302,303,307,308):url=urljoin(url,archive.headers['Location']);continue
        archive.raise_for_status()
        if archive.status_code not in (200,206):raise ValueError('Unexpected archive response')
        if archive.status_code==206 and not archive.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('Invalid resume response')
        if archive.status_code==200:offset=0
        with part.open('ab' if offset else 'wb') as out:
         size=offset
         for chunk in archive.iter_bytes(1024*1024):
          size+=len(chunk)
          if size>SIZE:raise ValueError('Archive exceeds publisher size')
          out.write(chunk)
        break
      else:raise ValueError('Too many archive redirects')
      break
     except httpx.TransportError:
      if attempt==5:raise
      time.sleep(min(2**attempt,16))
    sha,md5=hashes(part)
    if part.stat().st_size!=SIZE or md5!=MD5:raise ValueError('Publisher size/MD5 mismatch')
    part.replace(dest)
   sha,md5=hashes(dest)
  if sha!=SHA256:raise ValueError('Pinned project SHA-256 mismatch')
  proof={'source_id':'figshare-4276523-v1','api':API,'doi':meta['doi'],'download_url':file['download_url'],'file':dest.name,'bytes':SIZE,'publisher_md5':MD5,'sha256':sha,'license':'CC-BY-4.0','license_url':meta['license']['url'],'attribution':'Ana Schaigorodsky (2016), Chess Database, figshare. DOI: '+meta['doi'],'checksum_notice':'MD5 is the publisher integrity checksum, not a signature. SHA-256 is independently pinned in the project after verification of the downloaded bytes.'}
  (directory/'verified-archive.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
  return proof

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True);args=parser.parse_args();print(json.dumps(fetch(args.directory),ensure_ascii=False))
