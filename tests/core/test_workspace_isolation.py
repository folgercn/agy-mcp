from pathlib import Path
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'agy_mcp/core'))
import agy_desktop as d
import test_desktop as td


def env(identifier='env', uris=('file:///tmp',)):
    return {'id':identifier,'resources':{'resources':[{'folderUri':u} for u in uris]}}


@pytest.mark.parametrize('environments,expected', [
    ([env()], 'env'), ([env(uris=('file:///tmp','file:///other'))], None),
    ([env(),env('other')], None), ([], None),
    ([env(uris=('file:///tmp-other',))], None),
])
def test_resolve_exact_existing_environment(environments, expected):
    backend=d.Desktop.__new__(d.Desktop)
    backend.rpc=lambda method,args: {'projects':[{'id':'project','environments':{'environments':environments}}]}
    if expected:assert backend.resolve_environment({'project_id':'project'},'/tmp')==expected
    else:
        with pytest.raises(d.Failure):backend.resolve_environment({'project_id':'project'},'/tmp')


@pytest.mark.parametrize('change', [
    {'environmentId':'wrong'}, {'workspaceUris':[]},
    {'workspaceUris':['file:///tmp','file:///other']},
    {'workspaceUris':['file:///other']}, {'workspaceUris':['https://example.invalid/tmp']},
    {'warning':'workspace setup failed'},
])
def test_bad_startup_receipt_stops_real_execution_path(change):
    fixture=td.Tests();fixture.setUp();calls=[]
    class Backend(td.Fake):
        def rpc(self, method, args, **kw):
            calls.append(method)
            receipt=super().rpc(method,args,**kw)
            if method=='StartCascade':receipt['projectEnvInfo'].update(change)
            return receipt
    try:
        td.m.Desktop=Backend
        with pytest.raises(td.m.Failure):td.m.run_task(td.args())
        assert 'SendUserCascadeMessage' not in calls
        with pytest.raises(td.m.Failure):td.m.run_task(td.args())
        assert calls.count('StartCascade')==1
    finally:fixture.tearDown()


def test_lost_start_response_does_not_restart_or_send():
    fixture=td.Tests();fixture.setUp();calls=[]
    class Backend(td.Fake):
        def rpc(self,method,args,**kw):
            calls.append(method)
            receipt=super().rpc(method,args,**kw)
            if method=='StartCascade':raise ConnectionError('response lost after creation')
            return receipt
    try:
        td.m.Desktop=Backend
        with pytest.raises(ConnectionError):td.m.run_task(td.args())
        with pytest.raises(td.m.Failure):td.m.run_task(td.args())
        assert calls.count('StartCascade')==1
        assert 'SendUserCascadeMessage' not in calls
    finally:fixture.tearDown()


def test_receipt_persistence_failure_prevents_message():
    fixture=td.Tests();fixture.setUp();calls=[];save=td.m.save
    class Backend(td.Fake):
        def rpc(self,method,args,**kw):
            calls.append(method);return super().rpc(method,args,**kw)
    def failing_save(path,data):
        if 'workspace_receipt' in data:raise OSError('ENOSPC')
        return save(path,data)
    try:
        td.m.Desktop=Backend
        with patch.object(td.m,'save',side_effect=failing_save):
            with pytest.raises(OSError):td.m.run_task(td.args())
        with pytest.raises(td.m.Failure):td.m.run_task(td.args())
        assert calls.count('StartCascade')==1
        assert 'SendUserCascadeMessage' not in calls
    finally:fixture.tearDown()
