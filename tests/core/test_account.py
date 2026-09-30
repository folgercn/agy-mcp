import pathlib
import sys
import unittest

sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2]/'agy_mcp/core')))
import agy_account as account


class Backend:
    def rpc(self, method, body):
        self.calls = getattr(self, 'calls', []) + [(method, body)]
        if method == 'GetUserStatus':
            return {
                'userStatus': {
                    'name': 'Fu Jun', 'email': 'fu@example.com',
                    'planStatus': {'planInfo': {'planName': 'Gemini Pro'}},
                    'accessToken': 'must-not-leak', 'avatar': {'huge': 'must-not-leak'},
                }
            }
        if method == 'RetrieveUserQuotaSummary':
            return {
                'response': {
                    'groups': [
                        {
                            'displayName': 'Gemini', 'description': 'Shared quota',
                            'buckets': [
                                {'bucketId': 'gemini-weekly', 'window': 'weekly',
                                 'remainingFraction': 0.75, 'resetTime': '2026-09-20T00:00:00Z',
                                 'secretToken': 'must-not-leak'},
                                {'bucketId': 'gemini-5h'},
                            ],
                            'rawProfile': 'must-not-leak',
                        }
                    ],
                    'session': 'must-not-leak',
                }
            }
        raise AssertionError(method)


class AccountUsageTests(unittest.TestCase):
    def test_whitelist_complete_quota_and_unknown_missing_values(self):
        backend = Backend()
        result = account.account_usage(lambda: backend)
        self.assertEqual(backend.calls, [('GetUserStatus', {}), ('RetrieveUserQuotaSummary', {})])
        self.assertEqual(result['account'], {
            'name': 'Fu Jun', 'email': 'fu@example.com', 'planName': 'Gemini Pro',
        })
        buckets = result['quota']['groups'][0]['buckets']
        self.assertEqual(buckets[0]['bucketId'], 'gemini-weekly')
        self.assertEqual(buckets[0]['remainingFraction'], 0.75)
        self.assertEqual(buckets[1], {
            'bucketId': 'gemini-5h', 'window': 'unknown',
            'remainingFraction': 'unknown', 'resetTime': 'unknown',
        })
        self.assertNotIn('must-not-leak', str(result))

    def test_missing_sections_are_unknown_not_zero_or_empty(self):
        class Missing:
            def rpc(self, method, body):
                return {'userStatus': {}} if method == 'GetUserStatus' else {'response': {}}
        result = account.account_usage(Missing)
        self.assertEqual(result['account'], {
            'name': 'unknown', 'email': 'unknown', 'planName': 'unknown',
        })
        self.assertEqual(result['quota']['groups'], 'unknown')


if __name__ == '__main__':
    unittest.main()
