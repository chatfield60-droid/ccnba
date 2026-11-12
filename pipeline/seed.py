"""One-time local seed: python pipeline/seed.py /path/to/bdlbox_data.zip"""
import os,sys,zipfile,subprocess
with zipfile.ZipFile(sys.argv[1]) as z:
 for name in ('bdl_nba.sqlite','minutes_model.pkl'):z.extract(name,'.')
subprocess.run(['node','pipeline/blob.mjs','push-private','bdl_nba.sqlite','minutes_model.pkl'],check=True)
