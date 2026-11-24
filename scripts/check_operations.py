"""Local monitoring probe; nonzero exit when operational thresholds are exceeded."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import telemetry

if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--hours',type=int,default=1);a=p.parse_args()
 if not 1<=a.hours<=24:p.error('--hours must be 1..24')
 result=telemetry.alerts(a.hours);print(json.dumps(result,indent=2));raise SystemExit(1 if result['alerts'] else 0)
