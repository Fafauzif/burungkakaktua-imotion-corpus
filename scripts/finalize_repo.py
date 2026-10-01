"""Write combined counts and a checksum manifest for a completed corpus build."""
from __future__ import annotations
import argparse,csv,json,pathlib
from corpus_common import emit_csv,write_json,sha256_file

def finalize(repo):
 repo=pathlib.Path(repo)
 google=json.loads((repo/'reports/google_play_cleaning_summary.json').read_text())
 social=json.loads((repo/'reports/social_cleaning_summary.json').read_text())
 g=google['counts'];rows=[]
 rows.append({'table':'google_play_reviews','input_records':g['input_reviews'],'retained_records':g['retained_reviews'],'removed_records':g['input_reviews']-g['retained_reviews'],'empty_text':g.get('removed_empty_text',0),'symbol_only':g.get('removed_symbol_only',0),'deleted_placeholder':g.get('removed_deleted_placeholder',0),'duplicate_capture':g.get('removed_duplicate_capture',0),'count_group':'main_corpus'})
 for name,s in social['platforms'].items():
  reason=s['removal_reasons']
  rows.append({'table':name,'input_records':s['raw_rows'],'retained_records':s['retained_rows'],'removed_records':s['removed_rows'],'empty_text':reason.get('empty_text',0),'symbol_only':reason.get('symbol_only',0),'deleted_placeholder':reason.get('deleted_placeholder',0),'duplicate_capture':reason.get('duplicate_capture',0),'count_group':'main_corpus'})
 rows.append({'table':'google_play_developer_replies','input_records':g['input_developer_replies'],'retained_records':g['retained_developer_replies'],'removed_records':g['input_developer_replies']-g['retained_developer_replies'],'empty_text':g.get('reply_removed_empty_text',0),'symbol_only':g.get('reply_removed_symbol_only',0),'deleted_placeholder':g.get('reply_removed_deleted_placeholder',0),'duplicate_capture':g.get('reply_removed_duplicate_capture',0),'count_group':'developer_replies'})
 for row in rows:assert row['input_records']==row['retained_records']+row['removed_records']
 emit_csv(repo/'reports/cleaning_summary.csv',list(rows[0]),rows)
 main=[r for r in rows if r['count_group']=='main_corpus']
 summary={'main_input_records':sum(r['input_records'] for r in main),'main_retained_records':sum(r['retained_records'] for r in main),'main_removed_records':sum(r['removed_records'] for r in main),'developer_reply_input_records':g['input_developer_replies'],'developer_reply_retained_records':g['retained_developer_replies'],'developer_reply_removed_records':g['input_developer_replies']-g['retained_developer_replies'],'developer_replies_to_excluded_reviews':g['replies_to_excluded_review'],'context_records':social['context_rows_excluded_from_corpus'],'data_csv_files':len(list((repo/'data').rglob('*.csv'))),'data_csv_bytes':sum(p.stat().st_size for p in (repo/'data').rglob('*.csv')),'maximum_csv_bytes':90000000,'csv_row_limit':None}
 write_json(repo/'reports/corpus_size.json',summary)
 expected={row['path']:row for row in google['output_files']}
 for s in social['platforms'].values():
  for row in s['files']:expected[row['path']]=row
 inputs=[{'filename':google['input_file'],'role':'google_play_reviews','sha256':google['input_sha256']}]
 for row in social['input_manifests']:
  name=row.get('source_file') or row.get('input_file') or row.get('filename') or row.get('file')
  if name:inputs.append({'filename':pathlib.Path(name).name,'role':row.get('platform','social_source'),'sha256':row.get('sha256') or row.get('input_sha256','')})
 # The collection references are exact copies of supplied files.
 for name in ['scrape_imotion_reviews.py','run_imotion_reviews.bat']:
  p=repo/'scripts/collection'/name
  if p.exists():inputs.append({'filename':name,'role':'collection_reference','sha256':sha256_file(p)})
 emit_csv(repo/'metadata/input_files.csv',['filename','role','sha256'],inputs)
 actual_data={p.relative_to(repo).as_posix() for p in (repo/'data').rglob('*.csv')}
 expected_data={p for p in expected if p.startswith('data/')}
 assert actual_data==expected_data, {'extra':sorted(actual_data-expected_data),'missing':sorted(expected_data-actual_data)}
 manifest=[]
 for path in sorted(repo.rglob('*')):
  if not path.is_file() or '__pycache__' in path.parts or path.suffix=='.pyc':continue
  relative=path.relative_to(repo).as_posix()
  if relative=='reports/file_manifest.csv':continue
  size=path.stat().st_size;digest=sha256_file(path);count=''
  if relative in expected:
   row=expected[relative];assert size==row['bytes'] and digest==row['sha256'],relative;count=row['rows']
  elif path.suffix=='.csv':
   with path.open(encoding='utf-8-sig',newline='') as f:reader=csv.reader(f);next(reader,None);count=sum(1 for _ in reader)
  if path.suffix=='.csv':assert size<=90000000,relative
  manifest.append({'path':relative,'rows':count,'bytes':size,'sha256':digest})
 emit_csv(repo/'reports/file_manifest.csv',['path','rows','bytes','sha256'],manifest)
 return summary

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--repo',required=True);args=parser.parse_args();print(json.dumps(finalize(args.repo),indent=2))
