"""Decode bounded raster uploads, then store fresh pixels without metadata."""
from io import BytesIO
from threading import BoundedSemaphore
from PIL import Image,UnidentifiedImageError,PngImagePlugin
from fastapi import HTTPException

MAX_BYTES=2*1024*1024
MAX_PIXELS=6_000_000
MAX_EDGE=4096
MAX_STORED_BYTES=256*1024*1024
MAX_STORED_FILES=2000
_decoders=BoundedSemaphore(2)
# Posters do not need compressed text/profile payloads.
PngImagePlugin.MAX_TEXT_CHUNK=64*1024
PngImagePlugin.MAX_TEXT_MEMORY=1024*1024

def bounds(w,h):
 if w<1 or h<1 or max(w,h)>MAX_EDGE or w*h>MAX_PIXELS:raise HTTPException(422,'Poster must be at most 4096px per edge and 6 megapixels')

def preflight(raw):
 # Some WebP decoders allocate their canvas during open(), before Pillow's
 # public size check. Bound RIFF canvas/frame headers before invoking them.
 if raw.startswith(b'\x89PNG\r\n\x1a\n') and len(raw)>=24:bounds(int.from_bytes(raw[16:20],'big'),int.from_bytes(raw[20:24],'big'))
 if raw[:4]!=b'RIFF' or raw[8:12]!=b'WEBP':return
 if len(raw)<20 or int.from_bytes(raw[4:8],'little')+8!=len(raw):raise HTTPException(422,'Invalid WebP container length')
 offset=12;chunks=0
 while offset+8<=len(raw):
  chunks+=1;kind=raw[offset:offset+4];size=int.from_bytes(raw[offset+4:offset+8],'little');data=raw[offset+8:offset+8+size]
  if chunks>4096 or len(data)!=size:raise HTTPException(422,'Invalid WebP chunks')
  if kind==b'VP8X' and len(data)>=10:
   bounds(1+int.from_bytes(data[4:7],'little'),1+int.from_bytes(data[7:10],'little'))
   if data[0]&2:raise HTTPException(422,'Use a single-frame poster')
  elif kind==b'VP8 ' and len(data)>=10:bounds(int.from_bytes(data[6:8],'little')&0x3fff,int.from_bytes(data[8:10],'little')&0x3fff)
  elif kind==b'VP8L' and len(data)>=5:
   bits=int.from_bytes(data[1:5],'little');bounds((bits&0x3fff)+1,((bits>>14)&0x3fff)+1)
  offset+=8+size+(size&1)


def normalise(raw):
 if len(raw)>MAX_BYTES:raise HTTPException(413,'Poster exceeds 2MB')
 if not _decoders.acquire(blocking=False):raise HTTPException(429,'Image processing busy; retry shortly')
 try:
  preflight(raw)
  with Image.open(BytesIO(raw),formats=('PNG','JPEG','WEBP')) as image:
   fmt=image.format;w,h=image.size
   bounds(w,h)
   if getattr(image,'is_animated',False):raise HTTPException(422,'Use a single-frame poster')
   image.verify()
  with Image.open(BytesIO(raw),formats=('PNG','JPEG','WEBP')) as image:
   image.load()
   mode='RGBA' if image.mode in ('RGBA','LA') or 'transparency' in image.info else 'RGB'
   with Image.new(mode,image.size) as clean:
    with image.convert(mode) as pixels:clean.paste(pixels)
    output=BytesIO()
    clean.save(output,format=fmt,**({'quality':85} if fmt in ('JPEG','WEBP') else {}))
    result=output.getvalue()
  if len(result)>MAX_BYTES:raise HTTPException(422,'Decoded poster is too large; reduce dimensions or quality')
  return result,{'PNG':'png','JPEG':'jpg','WEBP':'webp'}[fmt]
 except (UnidentifiedImageError,OSError,ValueError,SyntaxError,Image.DecompressionBombError):
  raise HTTPException(422,'Upload a complete, valid PNG, JPEG or WebP poster') from None
 finally:_decoders.release()
