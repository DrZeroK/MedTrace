"""Local PDF body index and BM25 search. Build needs pypdfium2 or pypdf; search is stdlib-only."""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from medtrace.knowledge import search_tokens


def pdf_pages(filename, ocr_cache=None):
    """Prefer the bundled native parser for vector-heavy textbook pages."""
    if ocr_cache:
        cache=Path(ocr_cache)
        meta=json.loads((cache/'complete.json').read_text())
        if meta['source_sha256']!=hashlib.sha256(Path(filename).read_bytes()).hexdigest():
            raise ValueError('OCR cache does not match source PDF')
        for page_number in range(1,meta['pages']+1):
            record=json.loads((cache/f'{page_number:04}.json').read_text())
            if record['pdf_page']!=page_number:raise ValueError('OCR page mismatch')
            yield page_number,record['text']
        return
    try:
        import pypdfium2 as pdfium
    except ImportError:
        from pypdf import PdfReader
        for n,page in enumerate(PdfReader(filename).pages,1):
            yield n,page.extract_text() or ''
        return
    doc=pdfium.PdfDocument(str(filename))
    try:
        for n in range(len(doc)):
            page=doc[n]
            try:
                text=page.get_textpage()
                try:raw=text.get_text_range()
                finally:text.close()
            finally:page.close()
            yield n+1,raw.replace('\r\n','\n')
    finally:doc.close()


def connect(path):
    if not Path(path).is_absolute():
        raise ValueError('database path must be absolute')
    return sqlite3.connect(Path(path).as_uri()+'?mode=ro', uri=True)


def build(path, sources, ocr_caches=None):
    dest=Path(path)
    if not dest.is_absolute() or dest.exists():
        raise ValueError('use a new absolute database path; existing indexes are preserved')
    dest.parent.mkdir(parents=True, exist_ok=True)
    db=sqlite3.connect(dest)
    try:
        db.execute('PRAGMA journal_mode=MEMORY')
        db.execute('CREATE TABLE meta(body TEXT)')
        db.execute('CREATE TABLE pages(book TEXT,pdf_page INTEGER,printed_page INTEGER,label_basis TEXT,text TEXT,PRIMARY KEY(book,pdf_page))')
        db.execute('CREATE TABLE chunks(id INTEGER PRIMARY KEY,book TEXT,pdf_page INTEGER,start INTEGER,text TEXT)')
        db.execute('CREATE VIRTUAL TABLE search USING fts5(tokens)')
        metadata=[]
        for book,filename,start,offset in sources:
            p=Path(filename)
            empty=[]
            total_pages=0
            ocr_cache=(ocr_caches or {}).get(str(p))
            for page_number,raw in pdf_pages(p,ocr_cache):
                total_pages=page_number
                if page_number<start:continue
                i=page_number-1
                text=re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]','',raw)
                if not text.strip():empty.append(i+1)
                labels=[int(s.strip()) for s in text.splitlines()[:4] if re.fullmatch(r'\d{1,4}',s.strip())]
                printed=labels[0] if labels else i+1-offset
                db.execute('INSERT INTO pages VALUES(?,?,?,?,?)',(book,i+1,printed,'header' if labels else 'offset_inferred',text))
                for pos in range(0,len(text),880):
                    chunk=text[pos:pos+1000]
                    rid=db.execute('INSERT INTO chunks(book,pdf_page,start,text) VALUES(?,?,?,?)',(book,i+1,pos,chunk)).lastrowid
                    db.execute('INSERT INTO search(rowid,tokens) VALUES(?,?)',(rid,' '.join(search_tokens(chunk))))
                if page_number%100==0:print(f'{book}: {page_number} pages processed',flush=True)
            metadata.append(dict(book=book,path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),pdf_pages=total_pages,body_start_pdf_page=start,empty_text_pages=empty,text_method='ocr' if ocr_cache else 'pdf_text',ocr_cache=ocr_cache))
        manifest=dict(schema=1,state='ready',sources=metadata,created_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'),redistribution='not established; local research index')
        db.execute('INSERT INTO meta VALUES(?)',(json.dumps(manifest,ensure_ascii=False),))
        db.commit()
        dest.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'database':str(dest),'chunks':db.execute('SELECT count(*) FROM chunks').fetchone()[0]},ensure_ascii=False))
    finally:
        db.close()


def search(path, query, limit=5, book=None, full=False):
    if not query.strip() or not 1<=limit<=50:raise ValueError('query required; limit must be 1–50')
    db=connect(path)
    try:
        meta=json.loads(db.execute('SELECT body FROM meta').fetchone()[0])
        tokens=sorted(set(search_tokens(query)))[:100]
        params=[]
        if tokens:
            sql='SELECT c.book,c.pdf_page,c.start,c.text,bm25(search) AS score FROM search JOIN chunks c ON c.id=search.rowid WHERE search MATCH ?'
            params.append(' AND '.join('"'+t+'"' for t in tokens))
        else:
            sql='SELECT c.book,c.pdf_page,c.start,c.text,0 AS score FROM chunks c WHERE instr(c.text,?)>0'
            params.append(query)
        if book:sql+=' AND c.book=?';params.append(book)
        rows=db.execute(sql+' ORDER BY score,c.id',params).fetchall()
        out=[];seen=set()
        for title,page,pos,text,score in rows:
            if (title,page) in seen:continue
            seen.add((title,page))
            label,basis,body=db.execute('SELECT printed_page,label_basis,text FROM pages WHERE book=? AND pdf_page=?',(title,page)).fetchone()
            src=next(s for s in meta['sources'] if s['book']==title)
            out.append(dict(book=title,pdf_page=page,printed_page=label,printed_page_basis=basis,source=src['path'],text_method=src.get('text_method','pdf_text'),score=score,text=body if full else text))
            if len(out)==limit:break
        return out
    finally:db.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    b=sub.add_parser('build');b.add_argument('--db',required=True)
    b.add_argument('--source',nargs=4,action='append',metavar=('BOOK','PDF','BODY_START','OFFSET'),required=True)
    b.add_argument('--ocr-cache',nargs=2,action='append',metavar=('PDF','DIRECTORY'),default=[])
    s=sub.add_parser('search');s.add_argument('--db',required=True);s.add_argument('--query',required=True)
    s.add_argument('--limit',type=int,default=5);s.add_argument('--book');s.add_argument('--full-page',action='store_true')
    a=p.parse_args()
    if a.command=='build':build(a.db,[(t,f,int(start),int(offset)) for t,f,start,offset in a.source],dict(a.ocr_cache))
    else:print(json.dumps(search(a.db,a.query,a.limit,a.book,a.full_page),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
