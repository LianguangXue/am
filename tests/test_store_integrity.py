"""Mutations must preserve unreadable task, lease and handoff records."""
from pathlib import Path
from unittest.mock import patch
import argparse
import contextlib
import io
import json
import tempfile
import unittest

from test_hardening import AM


class StoreIntegrityTests(unittest.TestCase):
  def setUp(self) -> None:
    self.temp=tempfile.TemporaryDirectory(prefix='am-integrity-')
    self.root=Path(self.temp.name)/'.agents'
    for directory in ('tasks','leases','journal'):
      (self.root/directory).mkdir(parents=True,exist_ok=True)
    self.cfg=AM.load_config(self.root)
    self.args=argparse.Namespace(id='t',title='replacement',accept='new evidence',spec='',agent='codex',
      force=False,ttl=None,session='new',root=str(self.root),action='add')
    self.session=patch.object(AM,'caller_session',return_value={'id':'new','path':'','source':'explicit'})
    self.session.start()
    self.state=patch.object(AM,'write_state');self.state.start()

  def tearDown(self) -> None:
    self.state.stop();self.session.stop();self.temp.cleanup()

  def test_start_and_add_do_not_replace_malformed_or_wrong_shape_tasks(self) -> None:
    path=self.root/'tasks/t.json'
    for raw in ('{"id":"t","title":"original",', 'null', '[]', '"task"'):
      for command in (AM.cmd_start,AM.cmd_task):
        path.write_text(raw)
        with self.assertRaises(ValueError):command(self.root,self.cfg,self.args)
        self.assertEqual(path.read_text(),raw)
        self.assertFalse((self.root/'leases/t.json').exists())

  def test_claim_and_force_do_not_replace_unreadable_leases(self) -> None:
    task={'id':'t','status':'claimed','owner':'claude-code','title':'original'}
    AM.save_json(self.root/'tasks/t.json',task)
    path=self.root/'leases/t.json'
    for raw in ('{"agent":"claude-code","session":"old",', 'null', '[]', '{"agent":"claude-code"}'):
      for force in (False,True):
        self.args.force=force;path.write_text(raw)
        with self.assertRaises(ValueError):AM.cmd_claim(self.root,self.cfg,self.args)
        self.assertEqual(path.read_text(),raw)
        self.assertEqual(AM.load_json(self.root/'tasks/t.json',{}),task)

  def test_lease_io_errors_do_not_look_like_an_unowned_task(self) -> None:
    AM.save_json(self.root/'tasks/t.json',{'id':'t','status':'claimed','owner':'claude-code'})
    original=Path.open
    def unreadable(path: Path, *args, **kwargs):
      if path==self.root/'leases/t.json':raise OSError('temporary read failure')
      return original(path,*args,**kwargs)
    with patch.object(Path,'open',unreadable):
      with self.assertRaises(OSError):AM.cmd_claim(self.root,self.cfg,self.args)
    self.assertEqual(AM.load_json(self.root/'tasks/t.json',{})['owner'],'claude-code')

  def test_dashboard_lease_reads_still_tolerate_corruption(self) -> None:
    (self.root/'leases/t.json').write_text('{broken')
    with contextlib.redirect_stderr(io.StringIO()):
      self.assertIsNone(AM.read_lease(self.root,'t'))
    self.assertEqual((self.root/'leases/t.json').read_text(),'{broken')

  def test_hidden_mutation_preserves_corruption_but_read_remains_tolerant(self) -> None:
    path=self.root/'hidden.json';path.write_text('{broken')
    with contextlib.redirect_stderr(io.StringIO()):
      self.assertEqual(AM.hidden_state(self.root),{})
    with self.assertRaises(ValueError):AM.hide_sessions(self.root,['session'],'fixture')
    self.assertEqual(path.read_text(),'{broken')

  def test_corrupt_config_is_not_replaced_by_defaults(self) -> None:
    path=self.root/'config.json'
    for raw in ('{broken','[]','null'):
      path.write_text(raw)
      with self.assertRaises(ValueError):AM.load_config(self.root)
      self.assertEqual(path.read_text(),raw)

  def test_handoff_checks_existing_snapshot_and_index_before_writing(self) -> None:
    AM.save_json(self.root/'tasks/t.json',{'id':'t','status':'open'})
    directory=self.root/'integrations/delegate/t';directory.mkdir(parents=True)
    packet={'schema_version':1,'revision':2,'source_id':'source','am_task_id':'t','session_id':'s','jobs':[]}
    self.args.action='import'
    for bad in ('source.json','index.json'):
      (directory/'source.json').write_text('{"revision":1}')
      (directory/'index.json').write_text('["source"]')
      (directory/bad).write_text('{broken')
      original={p:p.read_bytes() for p in (directory/'source.json',directory/'index.json')}
      with patch('sys.stdin',io.StringIO(json.dumps(packet))):
        with self.assertRaises(ValueError):AM.cmd_delegate(self.root,self.cfg,self.args)
      for p,raw in original.items():self.assertEqual(p.read_bytes(),raw)

  def test_absent_records_still_allow_normal_start_and_renewal(self) -> None:
    with contextlib.redirect_stdout(io.StringIO()):
      self.assertEqual(AM.cmd_start(self.root,self.cfg,self.args),0)
      self.assertEqual(AM.cmd_claim(self.root,self.cfg,self.args),0)
    self.assertEqual(AM.get_task(self.root,'t')['owner'],'codex')
    self.assertEqual(AM.read_lease(self.root,'t',strict=True)['session'],'new')


if __name__=='__main__':unittest.main()
