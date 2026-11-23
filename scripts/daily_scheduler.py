"""Optional container scheduler: 03:15 Baghdad, with bounded catch-up every two hours."""
import subprocess,sys,time
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

def main():
    while True:
        subprocess.run([sys.executable,'-m','studio.knowledge.daily_exercises','--target','24','--max-candidates','700','--max-seconds','1800'],check=False)
        now=datetime.now(ZoneInfo('Asia/Baghdad'))
        daily=now.replace(hour=3,minute=15,second=0,microsecond=0)
        if daily<=now:daily+=timedelta(days=1)
        time.sleep(max(1,min(7200,(daily-now).total_seconds())))

if __name__=='__main__':main()
