"""Synthetic lock boundaries, independent processes and crash recovery."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from tracecascade.model import ModelError, load_graph
from tracecascade.review import _lock, append_decision, read_events


HOLDER = '''
import os,pathlib,sys,time
p=pathlib.Path(sys.argv[1])
with p.open('a+b') as f:
    f.seek(0)
    if os.name=='nt':
        import msvcrt
        msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    pathlib.Path(sys.argv[2]).touch()
    time.sleep(60)
'''
WRITER = '''
import pathlib,sys,time
from tracecascade.model import load_graph
from tracecascade.review import append_decision
root=pathlib.Path(sys.argv[1]); tag=sys.argv[2]
deadline=time.monotonic()+10
while not (root/'go').exists():
    if time.monotonic()>deadline:raise RuntimeError('synthetic start timeout')
    time.sleep(.01)
graph=load_graph(root/'graph.json')
for i in range(8):
    append_decision(graph,'ab','confirm','tester',tag+':'+str(i),root/'policy.json',root/'audit.jsonl','synthetic-audit-secret')
'''


def fixture(root):
    graph={'version':1,'nodes':[
        {'id':'a','kind':'field','title':'A','description':'synthetic source'},
        {'id':'b','kind':'job','title':'B','description':'synthetic consumer'}],
        'edges':[{'id':'ab','from':'a','to':'b','relation':'feeds','status':'confirmed','confidence':1,
                  'evidence':{'source':'source.md','quote':'A feeds B','line_start':1,'line_end':1}}]}
    (root/'graph.json').write_text(json.dumps(graph),encoding='utf-8')
    (root/'source.md').write_text('A feeds B\n',encoding='utf-8')
    (root/'policy.json').write_text(json.dumps({'version':1,'users':{'tester':'reviewer'},
        'roles':{'reviewer':['confirm']},'require_hmac':True}),encoding='utf-8')
    return load_graph(root/'graph.json')


class ReviewLockTests(unittest.TestCase):
    def test_lock_acquisition_never_writes_initialization_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);original=Path.open
            class NoWrite:
                def __init__(self,stream):self.stream=stream
                def __enter__(self):return self
                def __exit__(self,*args):self.stream.close()
                def __getattr__(self,key):return getattr(self.stream,key)
                def write(self,*args):raise AssertionError('lock bytes written before acquisition')
                def flush(self):raise AssertionError('lock initialization flush before acquisition')
            def opened(path,*args,**kwargs):
                stream=original(path,*args,**kwargs)
                return NoWrite(stream) if path.suffix=='.lock' else stream
            with patch.object(Path,'open',opened),_lock(root/'audit.jsonl'):pass
            self.assertEqual((root/'audit.jsonl.lock').read_bytes(),b'')

    def test_empty_sentinel_and_existing_bytes_are_not_changed_or_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);log=root/'audit.jsonl';sentinel=root/'audit.jsonl.lock'
            for value in (b'',b'legacy sentinel unchanged'):
                sentinel.write_bytes(value)
                with _lock(log):self.assertTrue(sentinel.exists())
                self.assertEqual(sentinel.read_bytes(),value)
            self.assertFalse(log.exists())

    def holder(self,root):
        child=subprocess.Popen([sys.executable,'-c',HOLDER,str(root/'audit.jsonl.lock'),str(root/'ready')],
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        self.addCleanup(self.reap,child)
        deadline=time.monotonic()+5
        while not (root/'ready').exists() and child.poll() is None and time.monotonic()<deadline:time.sleep(.01)
        self.assertTrue((root/'ready').exists(),'independent holder did not acquire zero-length lock')
        return child

    @staticmethod
    def reap(child):
        if child.poll() is None:child.kill()
        child.communicate(timeout=5)

    def test_real_empty_lock_contention_times_out_then_killed_owner_releases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);child=self.holder(root);started=time.monotonic()
            try:
                with self.assertRaisesRegex(ModelError,'Timed out waiting for review lock'):
                    with _lock(root/'audit.jsonl',timeout=.15):self.fail('entered competing critical section')
                self.assertGreaterEqual(time.monotonic()-started,.14)
                self.assertEqual((root/'audit.jsonl.lock').stat().st_size,0)
            finally:self.reap(child)
            with _lock(root/'audit.jsonl',timeout=.3):pass
            self.assertEqual((root/'audit.jsonl.lock').read_bytes(),b'')

    def test_independent_process_writers_produce_one_signed_chain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);fixture(root);children=[]
            try:
                for tag in ('p0','p1','p2','p3'):
                    children.append(subprocess.Popen([sys.executable,'-c',WRITER,str(root),tag],
                        stdout=subprocess.DEVNULL,stderr=subprocess.PIPE))
                (root/'go').touch()
                for child in children:
                    _,error=child.communicate(timeout=15)
                    self.assertEqual(child.returncode,0,error.decode(errors='replace'))
            finally:
                for child in children:self.reap(child)
            events=read_events(root/'audit.jsonl','synthetic-audit-secret',True)
            self.assertEqual(len(events),32)
            self.assertEqual({event['note'] for event in events},{f'p{tag}:{index}' for tag in range(4) for index in range(8)})
            self.assertEqual(len({event['event_hash'] for event in events}),32)
            self.assertEqual((root/'audit.jsonl.lock').read_bytes(),b'')

    def test_body_error_unlocks_and_tampered_log_is_not_extended(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);graph=fixture(root);log=root/'audit.jsonl'
            with self.assertRaisesRegex(RuntimeError,'synthetic'):
                with _lock(log):raise RuntimeError('synthetic body failure')
            with _lock(log,timeout=.2):pass
            append_decision(graph,'ab','confirm','tester','first',root/'policy.json',log,'synthetic-audit-secret')
            raw=log.read_bytes();log.write_bytes(raw.replace(b'first',b'other'))
            damaged=log.read_bytes()
            with self.assertRaises(ModelError):
                append_decision(graph,'ab','confirm','tester','second',root/'policy.json',log,'synthetic-audit-secret')
            self.assertEqual(log.read_bytes(),damaged)
            with _lock(log,timeout=.2):pass

    def test_append_io_failure_releases_lock_without_claiming_event_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);graph=fixture(root);log=root/'audit.jsonl'
            with patch('tracecascade.review.os.fsync',side_effect=OSError('synthetic fsync fault')):
                with self.assertRaisesRegex(ModelError,'Cannot append review event'):
                    append_decision(graph,'ab','confirm','tester','fault',root/'policy.json',log,'synthetic-audit-secret')
            # Bytes may already exist; a failed flush/fsync is not rollback or
            # power-loss durability. Preserve them and verify before proceeding.
            events=read_events(log,'synthetic-audit-secret',True)
            self.assertEqual(len(events),1)
            with _lock(log,timeout=.2):pass


if __name__=='__main__':unittest.main()
