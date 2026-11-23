"""Access logs must not retain checkout capabilities or redirect JWTs."""
import logging
class SafeAccessLog(logging.Filter):
 def filter(self,record):
  if isinstance(record.args,tuple) and len(record.args)==5:
   args=list(record.args);path=str(args[2]).split('?',1)[0]
   if path.startswith('/api/billing/callback/'):path='/api/billing/callback/[redacted]'
   args[2]=path;record.args=tuple(args)
  return True
logging.getLogger('uvicorn.access').addFilter(SafeAccessLog())
