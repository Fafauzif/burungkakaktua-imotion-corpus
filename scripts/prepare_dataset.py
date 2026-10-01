"""Rebuild data tables from the original supplied files. No network access."""
from __future__ import annotations
import argparse,pathlib,shutil
from build_reviews import build_reviews
from build_social import build_social
from finalize_repo import finalize

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--reviews',required=True,help='Original Google Play CSV')
 p.add_argument('--x',action='append',required=True,help='X JSON export; repeat for each file')
 p.add_argument('--agentreach',required=True,help='Original YouTube/Reddit ZIP')
 p.add_argument('--output',required=True,help='New or empty output directory')
 args=p.parse_args();out=pathlib.Path(args.output).resolve()
 if out.exists() and any(out.iterdir()):p.error('The output directory must be new or empty.')
 out.mkdir(parents=True,exist_ok=True)
 source_repo=pathlib.Path(__file__).resolve().parent.parent
 for name in ['README.md','DATA_DICTIONARY.md','.gitignore','.gitattributes']:
  source=source_repo/name
  if source.exists():shutil.copy2(source,out/name)
 for name in ['methodology','scripts']:
  shutil.copytree(source_repo/name,out/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'),dirs_exist_ok=True)
 planned=source_repo/'metadata/x_planned_inputs'
 if planned.exists():shutil.copytree(planned,out/'metadata/x_planned_inputs',dirs_exist_ok=True)
 build_reviews(out,args.reviews)
 build_social(out,args.x,args.agentreach)
 summary=finalize(out)
 print('Main retained records:',summary['main_retained_records'])
 print('Developer replies:',summary['developer_reply_retained_records'])

if __name__=='__main__':main()
