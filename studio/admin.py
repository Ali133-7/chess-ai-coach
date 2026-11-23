"""On-host role promotion; do not enable admin automatically from public registration."""
import sys
from .core import setup,connection
if __name__=='__main__':
 if len(sys.argv)!=3 or sys.argv[1]!='promote':
  raise SystemExit('Usage: python -m studio.admin promote email@example.com')
 setup();email=sys.argv[2].strip().lower()
 with connection() as db:
  cur=db.execute("UPDATE users SET role='admin' WHERE email=?",(email,))
  if cur.rowcount!=1:raise SystemExit('Account not found. Register first.')
 print('Admin granted to account:',email)
