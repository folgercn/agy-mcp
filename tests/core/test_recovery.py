import pathlib, sys, unittest
sys.path.insert(0, str((pathlib.Path(__file__).resolve().parents[2]/'agy_mcp/core')))
import agy_desktop as d


def command(line='git status', cwd='/work', code=0, status='CORTEX_STEP_STATUS_DONE'):
    return dict(type='CORTEX_STEP_TYPE_RUN_COMMAND', status=status,
                runCommand=dict(commandLine=line, cwd=cwd, shellName='zsh', exitCode=code))


class RecoveryTests(unittest.TestCase):
    def test_exact_retry(self):
        out=d.recovery_state([command(code=128),command()], 10)
        self.assertEqual(out['assessment'], 'observed_recoveries')
        issue=out['error_history'][0]
        self.assertEqual(issue['step_index'],10)
        self.assertEqual(issue['recovery_evidence']['step_index'],11)
        self.assertEqual(issue['exit_code'],128)

    def test_unrelated_or_incomplete_success_never_recovers(self):
        for success in (command(line='git log'),command(cwd='/other'),
                        command(status='CORTEX_STEP_STATUS_RUNNING')):
            with self.subTest(success=success):
                out=d.recovery_state([command(code=128),success])
                self.assertEqual(out['unresolved_issue_indices'],[0])

    def test_failure_after_recovery_remains_unresolved(self):
        out=d.recovery_state([command(code=128),command(),command(code=1)])
        self.assertEqual(out['recovered_issue_count'],1)
        self.assertEqual(out['unresolved_issue_indices'],[2])

    def test_unknown_or_missing_identity_never_recovers(self):
        missing=command(code=1);missing['runCommand'].pop('cwd')
        out=d.recovery_state([missing, {'type':'CORTEX_STEP_TYPE_ERROR_MESSAGE',
                              'errorMessage':{'message':'failure'}},command()])
        self.assertEqual(out['unresolved_issue_indices'],[0,1])

    def test_history_is_not_whole_turn_failure(self):
        steps=[command(code=128), command(), dict(type='CORTEX_STEP_TYPE_PLANNER_RESPONSE',
              plannerResponse={'response':'done'})]
        response,issues,tools,code=d.classify(steps)
        self.assertEqual(response,'done');self.assertIsNone(code);self.assertEqual(len(issues),1)

    def test_generation_recovery_does_not_clear_command_error(self):
        err=dict(type='CORTEX_STEP_TYPE_ERROR_MESSAGE',errorMessage={'message':'503 interrupted'})
        response=dict(type='CORTEX_STEP_TYPE_PLANNER_RESPONSE',status='CORTEX_STEP_STATUS_DONE',plannerResponse={'response':'done'})
        steps=[command(code=128),err,response]
        state=d.recovery_state(steps)
        self.assertEqual(state['unresolved_issue_indices'],[0])
        self.assertEqual(state['error_history'][1]['recovery'],'generation_resumed')
        self.assertIsNone(d.classify(steps)[3])
        self.assertEqual(d.classify(steps+[err])[3],'SERVICE_UNAVAILABLE')

    def test_unknown_exit_is_not_failure_or_recovery(self):
        pending=command(code=None)
        self.assertIsNone(d.step_issue(pending))
        self.assertEqual(d.recovery_state([command(code=128),pending])['unresolved_issue_indices'],[0])

    def test_one_success_does_not_resolve_multiple_failures(self):
        state=d.recovery_state([command(code=1),command(code=2),command(),command()])
        self.assertEqual(state['recovered_issue_count'],1)
        self.assertEqual(state['unresolved_issue_indices'],[0])
        self.assertEqual(state['error_history'][1]['recovery_evidence']['step_index'],2)
