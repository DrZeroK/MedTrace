import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.textbook_search import search


class TextbookSearch(unittest.TestCase):
    def test_search_boundary_book_and_page_deduplication(self):
        # Preserve artifacts under the project's no-permanent-deletion policy.
        p=Path(tempfile.mkdtemp(prefix='medtrace-textbook-test-'))/'fixture.sqlite'
        db=sqlite3.connect(p)
        db.execute('PRAGMA journal_mode=MEMORY')
        db.execute('CREATE TABLE meta(body TEXT)')
        db.execute('INSERT INTO meta VALUES(?)',(json.dumps({'sources':[{'book':'A','path':'/synthetic/A.pdf'},{'book':'B','path':'/synthetic/B.pdf'}]}),))
        db.execute('CREATE TABLE pages(book,pdf_page,printed_page,label_basis,text)')
        db.execute('CREATE TABLE chunks(id INTEGER PRIMARY KEY,book,pdf_page,start,text)')
        db.execute('CREATE VIRTUAL TABLE search USING fts5(tokens)')
        for n,(book,page) in enumerate([('A',1),('A',1),('B',2)],1):
            db.execute('INSERT INTO pages VALUES(?,?,?,?,?)',(book,page,page,'header','测试血钾 BNP'))
            db.execute('INSERT INTO chunks VALUES(?,?,?,?,?)',(n,book,page,0,'测试血钾 BNP'))
            db.execute('INSERT INTO search(rowid,tokens) VALUES(?,?)',(n,'测试 试血 血钾 bnp'))
        db.commit();db.close()
        self.assertEqual(len(search(str(p),'BNP')),2)
        self.assertEqual(len(search(str(p),'血钾',book='A')),1)
        self.assertEqual(search(str(p),'BNP',book="A' OR 1=1--"),[])
        self.assertEqual(len(search(str(p),'钾')),2)
        self.assertEqual(search(str(p),'xyzmissing'),[])
        self.assertEqual(search(str(p),'BNP',full=True)[0]['text'],'测试血钾 BNP')
        with self.assertRaises(ValueError):search(str(p),'BNP',limit=0)
        with self.assertRaises(ValueError):search(str(p),'')
