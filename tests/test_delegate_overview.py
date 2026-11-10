"""Read-only local overview independent of am task bindings."""
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest

API=runpy.run_path(str(Path(__file__).resolve().parents[1]/'bin/am'))

class OverviewTests(unittest.TestCase):
  def test_unbound_jobs_visible_without_result_or_prompt_exposure(self):
    with tempfile.TemporaryDirectory() as d:
      root=Path(d)
      (root/'task-index.json').write_text('["t"]')
      (root/'task-t.json').write_text('{"id":"t","session_id":"parent","jobs":["j"]}')
      record={'id':'j','task_id':'t','session_id':'parent','status':'completed','thread_id':'thread',
              'task':'PRIVATE_PROMPT','result':'PRIVATE_RESULT','codex_session':{'status':'archived'}}
      path=root/'job-j.json';path.write_text(json.dumps(record));before=path.read_bytes()
      result=API['delegate_overview']({'delegate_state_dir':d})
      self.assertEqual(result['jobs'][0]['conversation'],'archived')
      self.assertEqual(result['jobs'][0]['session_id'],'parent')
      self.assertNotIn('PRIVATE_',json.dumps(result))
      self.assertEqual(before,path.read_bytes())
  def test_bounded_and_corrupt_entries_stay_readable(self):
    with tempfile.TemporaryDirectory() as d:
      root=Path(d);ids=['j'+str(i) for i in range(80)]
      (root/'task-index.json').write_text('["../../escape","t"]')
      (root/'task-t.json').write_text(json.dumps({'id':'t','session_id':'parent','jobs':ids}))
      for jid in ids:(root/('job-'+jid+'.json')).write_text(json.dumps({'id':jid,'task_id':'t','session_id':'parent','status':'running'}))
      result=API['delegate_overview']({'delegate_state_dir':d})
      self.assertEqual(len(result['jobs']),50)
    with tempfile.TemporaryDirectory() as d:
      root=Path(d);(root/'task-index.json').write_text('broken')
      self.assertEqual(API['delegate_overview']({'delegate_state_dir':d})['errors'],1)
  def test_fifo_and_mismatched_ownership_are_rejected(self):
    with tempfile.TemporaryDirectory() as d:
      root=Path(d);os.mkfifo(root/'task-index.json')
      self.assertEqual(API['delegate_overview']({'delegate_state_dir':d})['errors'],1)
    with tempfile.TemporaryDirectory() as d:
      root=Path(d);(root/'task-index.json').write_text('["t"]')
      (root/'task-t.json').write_text('{"id":"t","session_id":"parent","jobs":["j"]}')
      (root/'job-j.json').write_text('{"id":"j","session_id":"other","task_id":"t"}')
      r=API['delegate_overview']({'delegate_state_dir':d})
      self.assertEqual(r['jobs'],[])
      self.assertEqual(r['errors'],1)
  def test_empty_view_remains_visible(self):
    with tempfile.TemporaryDirectory() as d:
      self.assertIn('note',API['delegate_overview']({'delegate_state_dir':d}))
    html=API['dashboard_html']({})
    self.assertIn('Delegate 子任务',html)
    self.assertIn('尚未关联delegate交接记录',html)

if __name__=='__main__':unittest.main()
