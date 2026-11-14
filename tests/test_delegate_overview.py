"""Read-only local overview independent of am task bindings."""
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
import hashlib
import time

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
      root=Path(d);ids=['j'+str(i) for i in range(120)]
      (root/'task-index.json').write_text('["../../escape","t"]')
      (root/'task-t.json').write_text(json.dumps({'id':'t','session_id':'parent','jobs':ids}))
      for jid in ids:(root/('job-'+jid+'.json')).write_text(json.dumps({'id':jid,'task_id':'t','session_id':'parent','status':'running'}))
      result=API['delegate_overview']({'delegate_state_dir':d})
      self.assertEqual(len(result['jobs']),100)
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

  def test_active_job_outside_recent_task_window_is_not_lost(self):
    with tempfile.TemporaryDirectory() as d:
      root=Path(d);ids=['t'+str(i) for i in range(60)]
      (root/'task-index.json').write_text(json.dumps(ids))
      for tid in ids:
        (root/('task-'+tid+'.json')).write_text(json.dumps({'id':tid,'session_id':'parent','jobs':[]}))
      (root/'task-t0.json').write_text(json.dumps({'id':'t0','session_id':'parent','jobs':['live']}))
      (root/'job-live.json').write_text(json.dumps({'id':'live','task_id':'t0','session_id':'parent','status':'running'}))
      (root/'active.json').write_text('["live"]')
      result=API['delegate_overview']({'delegate_state_dir':d})
      self.assertEqual(result['jobs'][0]['id'],'live')
      self.assertEqual(result['counts']['active'],1)
      self.assertEqual(result['inference_calls'],0)

  def test_active_updates_refresh_without_mutation_or_prompt_exposure(self):
    with tempfile.TemporaryDirectory() as d:
      root=Path(d)
      (root/'task-index.json').write_text('["t"]')
      (root/'task-t.json').write_text('{"id":"t","session_id":"parent","jobs":["j"]}')
      job={'id':'j','task_id':'t','session_id':'parent','status':'running','phase':'preparing-worktree',
        'provider':{'kind':'codex','api_key':'PRIVATE_KEY'},'task':'PRIVATE_PROMPT','result':'PRIVATE_RESULT',
        'heartbeat':99,'created_at':90,'worker_wait':{'state':'waiting','path':'PRIVATE_PATH'},
        'usage':{'total':{'inputTokens':999999,'outputTokens':100}},
        'usage_delta':{'inputTokens':100,'outputTokens':5,'cachedInputTokens':90}}
      path=root/'job-j.json';path.write_text(json.dumps(job))
      with patch.object(time,'time',return_value=100):first=API['delegate_overview']({'delegate_state_dir':d})
      self.assertEqual(first['jobs'][0]['observed_tokens'],105)
      self.assertTrue(first['jobs'][0]['waiting'])
      self.assertNotIn('PRIVATE_',json.dumps(first))
      job.update(status='completed',phase='executing',finished_at=101,worker_wait={'state':'file_exists'})
      path.write_text(json.dumps(job));before=path.read_bytes()
      with patch.object(time,'time',return_value=103):second=API['delegate_overview']({'delegate_state_dir':d})
      self.assertEqual(second['counts']['active'],0)
      self.assertEqual(second['jobs'][0]['status'],'completed')
      self.assertEqual(path.read_bytes(),before)

  def test_other_host_identity_is_unknown_instead_of_reported_dead(self):
    with tempfile.TemporaryDirectory() as d:
      root=Path(d)
      (root/'task-index.json').write_text('["t"]')
      (root/'task-t.json').write_text('{"id":"t","session_id":"parent","jobs":["j"]}')
      (root/'job-j.json').write_text(json.dumps({'id':'j','task_id':'t','session_id':'parent','status':'running',
        'worker_identity':{'pid':os.getpid(),'start':'0','boot':'another-host'},'heartbeat':time.time()}))
      result=API['delegate_overview']({'delegate_state_dir':d})
      self.assertIsNone(result['jobs'][0]['worker_alive'])
      self.assertEqual(result['jobs'][0]['warnings'],[])

  def test_native_parent_hash_and_rollout_identity_mapping(self):
    sid='01a17307-324d-7183-85cf-a06344dbbb27'
    rows=API['dashboard_session_ids']({'agent':'codex','session':'rollout-2026-11-10T12-00-00-'+sid})
    self.assertEqual(rows,[sid,'codex-'+hashlib.sha256(sid.encode()).hexdigest()[:32]])
    self.assertEqual(API['dashboard_session_ids']({'agent':'claude-code','session':sid}),[sid])
    native='custom-prefix-'+sid
    self.assertEqual(API['dashboard_session_ids']({'agent':'dsh','session':native}),
                     [native,'dsh-'+hashlib.sha256(native.encode()).hexdigest()[:32]])

  def test_nonfinite_fields_cannot_break_browser_json(self):
    with tempfile.TemporaryDirectory() as d:
      root=Path(d)
      (root/'task-index.json').write_text('["t"]')
      (root/'task-t.json').write_text('{"id":"t","session_id":"parent","jobs":["j"]}')
      (root/'job-j.json').write_text(json.dumps({'id':'j','task_id':'t','session_id':'parent','status':'running',
        'created_at':float('inf'),'collected_at':float('nan'),'heartbeat':10**1000,
        'provider':{'kind':'claude'},'usage':{'input_tokens':float('inf'),'output_tokens':2,'cache_read_input_tokens':float('nan')}}))
      result=API['delegate_overview']({'delegate_state_dir':d})
      self.assertEqual(len(result['jobs']),1)
      self.assertIsNone(result['jobs'][0]['observed_tokens'])
      self.assertIsNone(result['jobs'][0]['created_at'])
      json.dumps(result,allow_nan=False)

  def test_error_previews_redact_labeled_credentials(self):
    with tempfile.TemporaryDirectory() as d:
      root=Path(d)
      (root/'task-index.json').write_text('["t"]')
      (root/'task-t.json').write_text('{"id":"t","session_id":"parent","jobs":["j"]}')
      (root/'job-j.json').write_text(json.dumps({'id':'j','task_id':'t','session_id':'parent','status':'failed',
        'error':{'ANTHROPIC_AUTH_TOKEN':'PRIVATE_TOKEN','password':'prefix"SUFFIX_PRIVATE\nMORE_PRIVATE',
                 'nested':[{'refresh_token':'PRIVATE_REFRESH'}],'message':'failed safely'}}))
      result=API['delegate_overview']({'delegate_state_dir':d})
      self.assertNotIn('PRIVATE',json.dumps(result))
      self.assertIn('failed safely',result['jobs'][0]['error'])

  def test_freeform_error_redaction_does_not_stop_at_escaped_quote(self):
    with tempfile.TemporaryDirectory() as d:
      root=Path(d)
      (root/'task-index.json').write_text('["t"]')
      (root/'task-t.json').write_text('{"id":"t","session_id":"parent","jobs":["j"]}')
      (root/'job-j.json').write_text(json.dumps({'id':'j','task_id':'t','session_id':'parent','status':'failed',
        'error':'request failed; password="prefix\\"SUFFIX_PRIVATE\nMORE_PRIVATE"'}))
      result=API['delegate_overview']({'delegate_state_dir':d})
      self.assertNotIn('PRIVATE',json.dumps(result))
      self.assertIn('request failed',result['jobs'][0]['error'])

if __name__=='__main__':unittest.main()
