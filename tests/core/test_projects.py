import sys, unittest
from pathlib import Path
sys.path.insert(0,str((Path(__file__).resolve().parents[2]/'agy_mcp/core')))
from agy_desktop import Desktop, Failure
class ProjectTests(unittest.TestCase):
 def backend(self,projects):
  b=Desktop.__new__(Desktop); b.projects=lambda:projects;return b
 def test_exact_child_and_sibling(self):
  b=self.backend([dict(project_id='vnpy',name='vnpy',folders=['/work/vnpy'])])
  self.assertEqual(b.resolve_project('/work/vnpy/docs')['project_id'],'vnpy')
  with self.assertRaises(Failure) as e:b.resolve_project('/work/vnpy-other')
  self.assertEqual(e.exception.code,'PROJECT_NOT_FOUND')
 def test_ambiguous_never_defaults(self):
  b=self.backend([dict(project_id='a',folders=['/work']),dict(project_id='b',folders=['/work/vnpy'])])
  with self.assertRaises(Failure) as e:b.resolve_project('/work/vnpy')
  self.assertEqual(e.exception.code,'PROJECT_AMBIGUOUS')
if __name__=='__main__':unittest.main()
