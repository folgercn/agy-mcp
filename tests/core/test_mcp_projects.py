import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2]/'agy_mcp/core')))
import agy_service as m


class Backend:
    def __init__(self):
        self.calls = []

    def projects(self):
        self.calls.append(('projects',))
        return [{'project_id': 'vnpy', 'name': 'vnpy', 'folders': ['/work/vnpy']}]

    def resolve_project(self, cwd):
        self.calls.append(('resolve_project', cwd))
        return {'project_id': 'vnpy', 'name': 'vnpy', 'folders': ['/work/vnpy'], 'cwd': cwd}


class McpProjectTests(unittest.TestCase):
    def test_lists_projects_without_selecting_default(self):
        backend = Backend()
        self.assertEqual(m.projects('', lambda: backend)['projects'][0]['project_id'], 'vnpy')
        self.assertEqual(backend.calls, [('projects',)])

    def test_resolves_existing_absolute_cwd_and_rejects_other_forms(self):
        backend = Backend()
        with tempfile.TemporaryDirectory() as temp:
            output = m.projects(temp, lambda: backend)
            self.assertEqual(output['project']['cwd'], str(pathlib.Path(temp).resolve()))
        with self.assertRaises(ValueError):
            m.projects('relative', lambda: backend)
        with self.assertRaises(ValueError):
            m.projects('/definitely/not/a/project', lambda: backend)


if __name__ == '__main__':
    unittest.main()
