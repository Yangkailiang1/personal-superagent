"""模型配置检查不得偷偷调用供应商；连通性命令单独使用录制形状的响应。"""
import json
import os
from unittest.mock import patch
from types import SimpleNamespace


def test_status_fingerprint_invalidates_on_config_change(tmp_path):
    from personal_superagent.model_status import fingerprint, status
    with patch.dict(os.environ, {"MODEL_NAME":"test", "MODEL_API_KEY":"local-not-a-key"}), patch("personal_superagent.model_status.status_path",return_value=tmp_path/'status.json'):
        # status 不依赖数据库，测试中仅提供显式开关。
        with patch("personal_superagent.model_status.settings",SimpleNamespace(ALLOW_REAL_MODE=True)):
            assert status()['state']=='unverified'
            (tmp_path/'status.json').write_text(json.dumps({'fingerprint':fingerprint(),'state':'ready'}))
            assert status()['state']=='ready'
            with patch.dict(os.environ,{'MODEL_NAME':'changed'}): assert status()['state']=='unverified'


def test_explicit_model_check_exercises_tool_protocol(tmp_path):
    from personal_superagent.intake.management.commands.model_check import Command
    class RecordedModel:
        calls=0
        def bind_tools(self,*a,**kw):return self
        def invoke(self,messages):
            self.calls+=1
            if self.calls==1:return SimpleNamespace(tool_calls=[{'name':'connectivity_probe','args':{'value':'probe-ok'},'id':'probe'}])
            return SimpleNamespace(content='probe-ok')
    model=RecordedModel()
    with patch('personal_superagent.intake.management.commands.model_check.build_model',return_value=model),patch('personal_superagent.intake.management.commands.model_check.status_path',return_value=tmp_path/'status.json'):
        Command().handle()
        assert model.calls==2
        assert json.loads((tmp_path/'status.json').read_text())['state']=='ready'
        assert (tmp_path/'status.json').stat().st_mode & 0o777 == 0o600
