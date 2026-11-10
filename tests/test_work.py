"""No-model work protocol fixtures."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import os
import subprocess
import sys
import threading

spec=importlib.util.spec_from_file_location('work',Path(__file__).resolve().parents[1]/'bin/am_work.py')
work=importlib.util.module_from_spec(spec);spec.loader.exec_module(work)

class WorkTests(unittest.TestCase):
  def setUp(self):
    self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)/".agents"
    (self.root/'tasks').mkdir(parents=True);(self.root/'tasks/t.json').write_text('{}')
    self.file=self.root/'evidence.json';self.file.write_text('original')
  def tearDown(self):self.tmp.cleanup()
  def run_work(self,action,**data):return work.execute(self.root,action,data)
  def publish(self,project='p',**extra):
    return self.run_work('publish',id='a',project=project,task_id='t',session_id='s',
       summary='frozen replay result',evidence='checked fixture',files=[str(self.file)],**extra)
  def test_artifact_scope_staleness_and_revision(self):
    self.publish()
    self.assertEqual(self.run_work('search',project='other',query='replay')['artifacts'],[])
    search=self.run_work('search',project='p',query='replay')
    self.assertEqual(search['inference_calls'],0)
    self.assertIn('unchecked',search['artifacts'][0]['freshness'])
    self.assertEqual(self.run_work('get',id='a',project='p')['artifacts'][0]['freshness'],'unchanged')
    self.file.write_text('changed')
    self.assertEqual(self.run_work('get',id='a',project='p')['artifacts'][0]['freshness'],'stale')
    with self.assertRaises(ValueError):self.publish()
    self.assertEqual(self.publish(expected_revision=1)['revision'],2)
  def test_budget_dedup_reply_and_no_forward(self):
    args=dict(task_id='t',session_id='s',target_session='b',question='which frozen input?')
    with self.assertRaises(ValueError):self.run_work('ask',**args)
    self.run_work('configure',task_id='t',enabled=True)
    r=self.run_work('ask',**args)
    self.assertEqual(self.run_work('ask',**args)['id'],r['id'])
    self.run_work('configure',task_id='t',enabled=True)
    with self.assertRaises(ValueError):self.run_work('ask',**{**args,'question':'another'})
    with self.assertRaises(ValueError):self.run_work('ask',**args,parent_request=r['id'])
    with self.assertRaises(ValueError):self.run_work('reply',id=r['id'],session_id='other',reply='x')
    self.run_work('reply',id=r['id'],session_id='b',reply='manifest.json')
    self.assertEqual(self.run_work('reply',id=r['id'],session_id='b',reply='manifest.json')['status'],'answered')
    with self.assertRaises(ValueError):self.run_work('reply',id=r['id'],session_id='b',reply='changed')
  def test_completion_receipt_ack_and_no_repeat_job_execution(self):
    manifest=self.root/'completion.json'
    self.run_work('watch',id='w',task_id='t',session_id='s',manifest=str(manifest))
    self.assertEqual(self.run_work('poll',id='w',session_id='s')['status'],'waiting')
    manifest.write_text('{"status":"completed","evidence":"exit0 and output exists"}')
    r=self.run_work('poll',id='w',session_id='s')
    self.assertEqual(r['event_id'],'watch-w')
    self.assertEqual(self.run_work('poll',id='w',session_id='s'),r)
    self.assertTrue(self.run_work('ack',id='w',session_id='s')['acknowledged'])
  def test_stages_do_not_replay_and_changed_dependency_invalidates(self):
    self.run_work('stage',id='compile',task_id='t',files=[str(self.file)],evidence='compile exit0')
    other=self.root/'replay.json';other.write_text('replay')
    self.run_work('stage',id='replay',task_id='t',files=[str(other)],evidence='parity0',requires=['compile'])
    self.file.write_text('changed')
    self.assertEqual(self.run_work('stage-check',id='replay')['freshness'],'stale')
    with self.assertRaises(ValueError):self.run_work('stage',id='compile',task_id='t',files=[str(self.file)],evidence='repeat')
  def test_request_index_recovers_and_ancestor_changes_block_next_stage(self):
    self.run_work('configure',task_id='t',enabled=True)
    args=dict(task_id='t',session_id='s',target_session='b',question='q')
    r=self.run_work('ask',**args)
    index=work.load(self.root/'work/index.json');index['requests']=[]
    work.save(self.root/'work/index.json',index)
    self.run_work('ask',**args)
    self.assertEqual(self.run_work('inbox',session_id='b')['requests'][0]['id'],r['id'])
    self.run_work('stage',id='a',task_id='t',files=[str(self.file)],evidence='a')
    b=self.root/'b';b.write_text('b')
    self.run_work('stage',id='b',task_id='t',files=[str(b)],evidence='b',requires=['a'])
    self.file.write_text('changed')
    with self.assertRaises(ValueError):
      self.run_work('stage',id='c',task_id='t',files=[str(b)],evidence='c',requires=['b'])
  def test_artifact_owner_cannot_be_replaced(self):
    self.publish()
    with self.assertRaises(ValueError):
      self.run_work('publish',id='a',project='p',task_id='t',session_id='other',summary='x',
                    evidence='x',files=[str(self.file)],expected_revision=1)

  def test_real_cli_wait_and_invalid_wait_has_no_side_effect(self):
    am=Path(__file__).resolve().parents[1]/'bin/am'
    manifest=self.root/'receipt.json'
    self.run_work('watch',id='w',task_id='t',session_id='s',manifest=str(manifest))
    (self.root/'config.json').write_text('{}')
    timer=threading.Timer(.05,lambda:manifest.write_text('{"status":"completed"}'));timer.start()
    try:
      p=subprocess.run([sys.executable,str(am),'--root',str(self.root),'work','poll','--wait','1'],
        input=json.dumps({'id':'w','session_id':'s'}),text=True,capture_output=True,timeout=5)
      self.assertEqual(p.returncode,0,p.stderr)
      self.assertEqual(json.loads(p.stdout)['status'],'completed')
    finally:timer.join()
    p=subprocess.run([sys.executable,str(am),'--root',str(self.root),'work','configure','--wait','1'],
      input=json.dumps({'task_id':'t','enabled':True}),text=True,capture_output=True,timeout=5)
    self.assertNotEqual(p.returncode,0)
    self.assertFalse((self.root/'work/policy-t.json').exists())

  def test_fifo_symlink_and_missing_inputs_rejected(self):
    fifo=self.root/'fifo';os.mkfifo(fifo)
    with self.assertRaises(ValueError):work.fingerprints([str(fifo)])
    link=self.root/'link';link.symlink_to(self.file)
    with self.assertRaises(ValueError):work.fingerprints([str(link)])
