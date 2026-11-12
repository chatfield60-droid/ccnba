import datetime,os,subprocess,sys,json
from pathlib import Path
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York');now=datetime.datetime.now(ET);today=now.date();date=today.isoformat();yesterday=(today-datetime.timedelta(days=1)).isoformat()
expected_cron='30 14 * * *' if now.utcoffset().total_seconds()==-4*3600 else '30 15 * * *'
if os.environ.get('GITHUB_EVENT_NAME')=='schedule' and os.environ.get('SCHEDULE_CRON')!=expected_cron:raise SystemExit(0)
def run(*args,stdout=None):subprocess.run(args,check=True,stdout=stdout)
run('node','pipeline/blob.mjs','pull')
if not Path('bdl_nba.sqlite').exists():raise SystemExit('Seed private Blob with bdlbox_data.zip before first run')
os.environ.update(BDL_DB='bdl_nba.sqlite',BDL_TIER='GOAT')
run(sys.executable,'-m','bdlbox','sync','--seasons',str(today.year),'--goat','--date',date)
try:
 import pickle,warnings
 from sklearn.exceptions import InconsistentVersionWarning
 with warnings.catch_warnings():
  warnings.simplefilter('error',InconsistentVersionWarning)
  with open('minutes_model.pkl','rb') as f:pickle.load(f)
except Exception:run(sys.executable,'-m','bdlbox','train-minutes')
with open('lines.csv','w') as f:run(sys.executable,'pipeline/fetch_lines.py','--date',date,stdout=f)
run(sys.executable,'-m','bdlbox','project','--date',date,'--lines','lines.csv','--out','out')
run(sys.executable,'pipeline/publish.py','--date',date)
run('node','pipeline/blob.mjs','pull-history',yesterday)
run(sys.executable,'pipeline/grade.py','--date',yesterday)
run('node','pipeline/blob.mjs','push-private','bdl_nba.sqlite','minutes_model.pkl')
run('node','pipeline/blob.mjs','push-public',*[str(x) for x in (Path('publish/slates')/date).glob('*.json')])
if Path('publish/results/history.json').exists():run('node','pipeline/blob.mjs','push-public','publish/results/history.json')

Path('publish/slates/latest.json').write_text(json.dumps({'date':date}))
run('node','pipeline/blob.mjs','push-public','publish/slates/latest.json')
