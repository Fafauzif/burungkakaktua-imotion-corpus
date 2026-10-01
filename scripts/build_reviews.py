"""Build compact per-app review and developer-response tables."""
from __future__ import annotations
import argparse,collections,csv,hashlib,json,pathlib,re,unicodedata
from urllib.parse import urlparse,parse_qs
from corpus_common import ShardWriter,classify_text,trim_text,emit_csv,write_json,sha256_file

REVIEW_COLUMNS=['review_id','app_name','source_id','review_date','rating','review_title','review_text','app_version','helpful_count','fetch_locale','collected_at','source_row']
REPLY_COLUMNS=['review_id','app_name','source_id','reply_text','reply_date','parent_review_retained','source_row']
REMOVED_COLUMNS=['table','source_id','record_id','source_row','reason']

def slug(value):
 s=unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower()
 return re.sub(r'[^a-z0-9]+','_',s).strip('_')

def build_reviews(repo,input_file):
 repo=pathlib.Path(repo);input_file=pathlib.Path(input_file)
 writers={};reply_writers={};apps={};seen={};reply_seen={};versions={};reply_versions={};totals=collections.Counter();manifest=[]
 removed=ShardWriter(repo,'reports',REMOVED_COLUMNS,basename='google_play_removed')
 hashtext=hashlib.sha256();hashreply=hashlib.sha256()
 with input_file.open('r',encoding='utf-8-sig',newline='') as handle:
  reader=csv.DictReader(handle)
  for rowno,row in enumerate(reader,1):
   if None in row:raise ValueError(f'Unexpected CSV field count at data record {rowno}')
   app=row['app_name'];app_slug=slug(app);sid='google_play_'+app_slug;rid=trim_text(row.get('review_id'))
   if not rid:raise ValueError(f'Review ID absent at data record {rowno}')
   if app not in apps:
    directory='data/google_play/'+app_slug
    writers[app]=ShardWriter(repo,directory,REVIEW_COLUMNS,basename='reviews')
    reply_writers[app]=ShardWriter(repo,directory,REPLY_COLUMNS,basename='developer_replies')
    apps[app]={'source_id':sid,'app_name':app,'app_id':parse_qs(urlparse(row['source_url']).query).get('id',[''])[0],'platform':'google_play','source_url':row['source_url'],'input_file':input_file.name,'original_source_files':set(),'collection_times':set(),'fetch_locales':set(),'counts':collections.Counter()}
   meta=apps[app];stats=meta['counts'];stats['input_reviews']+=1;totals['input_reviews']+=1
   meta['original_source_files'].add(row.get('source_file',''));meta['collection_times'].add(row.get('fetched_at',''));meta['fetch_locales'].add(row.get('fetch_locale',''))
   title=trim_text(row.get('review_title'));body=trim_text(row.get('review_text'))
   reason=classify_text((title+'\n'+body).strip())
   key=(sid,rid);payload=(row.get('review_date',''),row.get('rating',''),title,body)
   digest=hashlib.sha256(json.dumps(payload,ensure_ascii=False).encode()).digest()
   if not reason and key in seen:
    if digest==seen[key] or digest in versions.get(key,set()):reason='duplicate_capture'
    else:versions.setdefault(key,{seen[key]}).add(digest);stats['changed_review_versions']+=1;totals['changed_review_versions']+=1
   if not reason:
    seen.setdefault(key,digest)
    record={'review_id':rid,'app_name':app,'source_id':sid,'review_date':row.get('review_date',''),'rating':row.get('rating',''),'review_title':title,'review_text':body,'app_version':row.get('app_version',''),'helpful_count':row.get('thumbs_up_count',''),'fetch_locale':row.get('fetch_locale',''),'collected_at':row.get('fetched_at',''),'source_row':rowno}
    writers[app].write(record);stats['retained_reviews']+=1;totals['retained_reviews']+=1
    hashtext.update(json.dumps([sid,rid,title,body],ensure_ascii=False,separators=(',',':')).encode()+b'\n')
   else:
    stats['removed_'+reason]+=1;totals['removed_'+reason]+=1
    removed.write({'table':'reviews','source_id':sid,'record_id':rid,'source_row':rowno,'reason':reason})
   # Reply records remain separate even when the parent has no retained text.
   raw_reply=row.get('developer_reply','')
   if str(raw_reply).strip():
    stats['input_developer_replies']+=1;totals['input_developer_replies']+=1
    reply=trim_text(raw_reply);reply_reason=classify_text(reply)
    rdigest=hashlib.sha256(json.dumps([reply,row.get('developer_reply_date','')],ensure_ascii=False).encode()).digest()
    if not reply_reason and key in reply_seen:
     if rdigest==reply_seen[key] or rdigest in reply_versions.get(key,set()):reply_reason='duplicate_capture'
     else:reply_versions.setdefault(key,{reply_seen[key]}).add(rdigest);stats['changed_reply_versions']+=1;totals['changed_reply_versions']+=1
    if not reply_reason:
     reply_seen.setdefault(key,rdigest)
     reply_writers[app].write({'review_id':rid,'app_name':app,'source_id':sid,'reply_text':reply,'reply_date':row.get('developer_reply_date',''),'parent_review_retained':'true' if not reason else 'false','source_row':rowno})
     stats['retained_developer_replies']+=1;totals['retained_developer_replies']+=1
     if reason:stats['replies_to_excluded_review']+=1;totals['replies_to_excluded_review']+=1
     hashreply.update(json.dumps([sid,rid,reply],ensure_ascii=False,separators=(',',':')).encode()+b'\n')
    else:
     stats['reply_removed_'+reply_reason]+=1;totals['reply_removed_'+reply_reason]+=1
     removed.write({'table':'developer_replies','source_id':sid,'record_id':rid,'source_row':rowno,'reason':reply_reason})
   if rowno%100000==0:print(f'Google Play: {rowno:,} input reviews processed',flush=True)
 for app in apps:
  manifest+=writers[app].close();manifest+=reply_writers[app].close()
 manifest+=removed.close()
 source_rows=[];app_rows=[]
 for meta in apps.values():
  source_rows.append({k:('; '.join(sorted(meta[k])) if isinstance(meta[k],set) else meta[k]) for k in ['source_id','platform','app_name','app_id','source_url','input_file','original_source_files','collection_times','fetch_locales']})
  app_rows.append({'app_name':meta['app_name'],'source_id':meta['source_id'],**dict(meta['counts'])})
 emit_csv(repo/'metadata/google_play_sources.csv',list(source_rows[0]),source_rows)
 countkeys=sorted(set().union(*(row.keys() for row in app_rows))-{'app_name','source_id'})
 emit_csv(repo/'reports/google_play_by_app.csv',['app_name','source_id']+countkeys,[{**r,**{k:r.get(k,0) for k in countkeys}} for r in app_rows])
 result={'input_file':input_file.name,'input_sha256':sha256_file(input_file),'counts':dict(totals),'apps':app_rows,'output_files':manifest,'retained_review_text_sha256':hashtext.hexdigest(),'retained_reply_text_sha256':hashreply.hexdigest(),'text_hash_encoding':'UTF-8 JSON arrays, ensure_ascii=False, compact separators, newline per retained record, input order'}
 write_json(repo/'reports/google_play_cleaning_summary.json',result)
 print(json.dumps(result['counts'],indent=2),flush=True)
 return result

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--repo',required=True);args=parser.parse_args();build_reviews(args.repo,args.input)
