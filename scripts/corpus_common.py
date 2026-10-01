"""CSV output and conservative text checks for the IMOTION corpus."""
from __future__ import annotations
import csv,hashlib,io,json,pathlib,re

KEYCAP = re.compile(r'[0-9#*][\ufe0e\ufe0f]?\u20e3')
PLACEHOLDERS = {'[deleted]', '[removed]'}

def trim_text(value):
    if value is None:return ''
    return str(value).replace('\x00','').strip()

def classify_text(value):
    text=trim_text(value)
    if not text:return 'empty_text'
    if text.casefold() in PLACEHOLDERS:return 'deleted_placeholder'
    probe=KEYCAP.sub('',text)
    if not any(char.isalnum() for char in probe):return 'symbol_only'
    return ''

def sha256_file(path):
    digest=hashlib.sha256()
    with open(path,'rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()

def write_json(path,value):
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def emit_csv(path,columns,rows):
    path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=columns,lineterminator='\n',extrasaction='raise')
        writer.writeheader();writer.writerows(rows)

class ShardWriter:
    """Split only at record boundaries; byte limits include the CSV header."""
    def __init__(self,repo,relative_dir,columns,max_rows=None,max_bytes=90000000,basename='part'):
        self.repo=pathlib.Path(repo);self.directory=self.repo/relative_dir
        self.directory.mkdir(parents=True,exist_ok=True)
        self.columns=list(columns);self.max_rows=max_rows;self.max_bytes=max_bytes;self.basename=basename
        self._buffer=io.StringIO(newline='')
        self._writer=csv.DictWriter(self._buffer,fieldnames=self.columns,lineterminator='\n',extrasaction='raise')
        self._writer.writeheader();self._header=self._take_bytes()
        self._handle=None;self._files=[];self._rows=0;self._bytes=0;self.total_rows=0;self._closed=False
    def _take_bytes(self):
        result=self._buffer.getvalue().encode('utf-8');self._buffer.seek(0);self._buffer.truncate(0);return result
    def _open(self):
        self._path=self.directory/f'{self.basename}_part_{len(self._files)+1:02d}.csv'
        self._handle=self._path.open('wb');self._handle.write(self._header)
        self._rows=0;self._bytes=len(self._header)
    def _finish(self):
        if self._handle is None:return
        self._handle.close();self._files.append({'absolute_path':self._path,'rows':self._rows,'bytes':self._bytes});self._handle=None
    def write(self,row):
        if self._closed:raise RuntimeError('Writer is closed')
        self._writer.writerow(row);encoded=self._take_bytes()
        if len(encoded)+len(self._header)>self.max_bytes:raise ValueError('One CSV record exceeds maximum file size')
        if self._handle is None:self._open()
        if self._rows and ((self.max_rows and self._rows>=self.max_rows) or self._bytes+len(encoded)>self.max_bytes):self._finish();self._open()
        self._handle.write(encoded);self._rows+=1;self.total_rows+=1;self._bytes+=len(encoded)
    def close(self):
        if self._closed:return self.manifest
        if self._handle is None and not self._files:self._open()
        self._finish()
        if len(self._files)==1:
            entry=self._files[0];destination=self.directory/f'{self.basename}.csv';temporary=entry['absolute_path'];temporary.replace(destination);entry['absolute_path']=destination
            if temporary.exists():temporary.unlink()
        self.manifest=[]
        for entry in self._files:
            path=entry['absolute_path']
            self.manifest.append({'path':path.relative_to(self.repo).as_posix(),'rows':entry['rows'],'bytes':entry['bytes'],'sha256':sha256_file(path)})
        self._closed=True
        return self.manifest
