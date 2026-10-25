import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('agent',ROOT/'eks_migrate.py')
agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)

def init_repo(path,app=False):
    if app:shutil.copytree(ROOT/'examples/sample-service',path)
    else:path.mkdir();(path/'README.md').write_text('Existing infrastructure\n')
    for args in [('init','-b','main'),('config','user.name','Test'),('config','user.email','test@localhost'),('add','.'),('commit','-m','Original')]:agent.git(path,*args)
    return path

@pytest.fixture
def cfg():return agent.read_config(ROOT/'examples/migration.demo.json')

def arguments(repo,config,tmp_path):
    path=tmp_path/'migration.json';path.write_text(json.dumps(config))
    return agent.argparse.Namespace(repo=str(repo),config=str(path),base='main',branch=None,worktree=None,refresh=False,push=False,report=str(tmp_path/'report.json'),timeout=3)

def test_schema_rejects_shell_and_path_injection(cfg,tmp_path):
    cfg['source']['dockerfile']='../Dockerfile'
    path=tmp_path/'x.json';path.write_text(json.dumps(cfg))
    with pytest.raises(agent.MigrationError):agent.read_config(path)
    cfg['source']['dockerfile']='Dockerfile';cfg['pipeline']['service_connection']="x'; touch /tmp/unwanted"
    path.write_text(json.dumps(cfg))
    with pytest.raises(agent.MigrationError):agent.read_config(path)

def test_unknown_and_stateful_assessment_block(cfg):
    cfg['assessment']['local_disk']=None
    assert any('local_disk' in b for b in agent.blockers(cfg))
    cfg['assessment']['local_disk']=True
    assert any('outside' in b for b in agent.blockers(cfg))

def test_blocked_app_creates_no_branch_or_worktree(cfg,tmp_path):
    repo=init_repo(tmp_path/'app',True);args=arguments(repo,cfg,tmp_path)
    cfg['assessment']['database_in_vm']=True;Path(args.config).write_text(json.dumps(cfg))
    before=agent.git(repo,'show-ref')
    assert agent.prepare_role(args,'app')==2
    assert agent.git(repo,'show-ref')==before
    assert not (tmp_path/'app-eks-orders').exists()
    assert json.loads(Path(args.report).read_text())['containerization']=='blocked'
    assert not agent.git(repo,'status','--porcelain')

def test_missing_dockerfile_blocks_without_branch(cfg,tmp_path):
    repo=init_repo(tmp_path/'app',True);(repo/'Dockerfile').unlink();agent.git(repo,'add','.');agent.git(repo,'commit','-m','No container recipe')
    args=arguments(repo,cfg,tmp_path);before=agent.git(repo,'show-ref')
    assert agent.prepare_role(args,'app')==2
    assert agent.git(repo,'show-ref')==before

def test_infra_independent_and_app_assets_separate(cfg,tmp_path):
    cfg['assessment']['database_in_vm']=True
    repo=init_repo(tmp_path/'infra');args=arguments(repo,cfg,tmp_path)
    base=agent.git(repo,'rev-parse','HEAD')
    assert agent.prepare_role(args,'infra')==0
    target=tmp_path/'infra-eks-platform-orders'
    assert (target/'.eks-platform/infra/main.tf').is_file()
    assert (target/'.eks-platform/chart/Chart.yaml').is_file()
    assert not (target/'.eks-migration').exists()
    assert agent.git(repo,'rev-parse','HEAD')==base
    assert agent.git(target,'rev-parse','HEAD^')==base
    checklist=json.loads((target/'.eks-platform/checklists.json').read_text())
    assert checklist['infrastructure']['status']=='assets-prepared'
    assert checklist['application']['status']=='blocked-until-validated-artifact'
    assert agent.git(repo,'status','--porcelain')==''
    with pytest.raises(agent.MigrationError):agent.prepare_role(args,'infra')

def test_pipeline_handoff_and_ops_approval(cfg):
    release=yaml.safe_load(agent.render_release(cfg))
    resource=release['resources']['pipelines'][0]
    assert resource['trigger']['stages']==['Package']
    assert resource['trigger']['branches']['include']==['refs/heads/main']
    validate=release['stages'][0]['jobs'][0]['steps']
    assert validate[1]['download']=='application'
    assert '--expected-source-revision' in validate[2]['bash']
    prod=release['stages'][2]
    assert set(prod['dependsOn'])=={'ValidateArtifact','Staging'}
    approval=prod['jobs'][0]['steps'][0]
    assert approval['task']=='ManualValidation@1'
    assert approval['inputs']['approvers']==cfg['pipeline']['ops_approvers']
    assert approval['inputs']['allowApproversToApproveTheirOwnRuns'] is False
    assert approval['inputs']['onTimeout']=='reject'
    assert prod['jobs'][1]['dependsOn']=='OpsApproval'
    assert release['stages'][1]['variables']['imageDigest']==prod['variables']['imageDigest']
    assert 'helm rollback' in agent.render_release(cfg)
    assert '--admin' not in agent.render_release(cfg)
    app=yaml.safe_load(agent.render_application(cfg))
    assert 'eks-image'==app['stages'][0]['jobs'][0]['steps'][-1]['inputs']['artifact']
    assert 'eks-platform' not in agent.render_application(cfg)
    assert app['trigger']['branches']['include']==['main']
    assert yaml.safe_load(agent.render_platform(cfg))['stages'][1]['jobs'][0]['job']=='OpsApproval'

def test_artifact_rejects_wrong_repository_mutable_tag_and_unvalidated(cfg):
    good={'schema_version':1,'repository':'111122223333.dkr.ecr.us-east-1.amazonaws.com/orders','digest':'sha256:'+'a'*64,'source_revision':'b'*40,'containerization':'passed','build_id':'42'}
    assert agent.validate_artifact(cfg,good)==good
    for key,value in [('digest','latest'),('repository','other.azurecr.io/evil'),('containerization','blocked'),('source_revision','$(shell)')]:
        bad={**good,key:value}
        with pytest.raises(agent.MigrationError):agent.validate_artifact(cfg,bad)

def test_dirty_source_refused_before_branch(cfg,tmp_path):
    repo=init_repo(tmp_path/'app',True);(repo/'uncommitted.txt').write_text('keep me')
    with pytest.raises(agent.MigrationError):agent.prepare_role(arguments(repo,cfg,tmp_path),'app')
    assert (repo/'uncommitted.txt').read_text()=='keep me'
    assert agent.git(repo,'branch','--list','migration/*')==''

def test_private_inventory_is_metadata_only(tmp_path,monkeypatch):
    calls=[]
    def fake(args,cwd=None):
        calls.append(args)
        return '111122223333' if args[1]=='sts' else '[{"id":"instance-id","os":"Linux","type":"small"}]'
    monkeypatch.setattr(agent,'command',fake)
    path=tmp_path/'inventory.json'
    args=agent.argparse.Namespace(account_id='111122223333',region='us-east-1',output=str(path))
    agent.inventory(args)
    assert calls[1][0:3]==['aws','ec2','describe-instances']
    assert 'send-command' not in str(calls)
    assert 'PrivateIp' not in str(calls)
    assert path.stat().st_mode & 0o077==0

@pytest.mark.skipif(os.environ.get('RUN_DOCKER_TESTS')!='1',reason='Set RUN_DOCKER_TESTS=1 for real container build/runtime gates')
def test_actual_container_gate_then_branch(cfg,tmp_path,monkeypatch):
    repo=init_repo(tmp_path/'app',True);before=agent.git(repo,'rev-parse','HEAD');pipeline=(repo/'azure-pipelines.yml').read_bytes()
    original=agent.containerize
    def gated(*args,**kwargs):
        assert agent.git(repo,'branch','--list','migration/*')==''
        result=original(*args,**kwargs)
        assert agent.git(repo,'branch','--list','migration/*')==''
        return result
    monkeypatch.setattr(agent,'containerize',gated)
    args=arguments(repo,cfg,tmp_path);args.timeout=30
    assert agent.prepare_role(args,'app')==0
    target=tmp_path/'app-eks-orders'
    assert agent.git(target,'rev-parse','HEAD^')==before
    assert (repo/'azure-pipelines.yml').read_bytes()==pipeline
    assert agent.git(repo,'rev-parse','HEAD')==before
    assert not (target/'.eks-platform').exists()
    assert (target/'.azure-pipelines/eks-image.yml').exists()
    assert json.loads(Path(args.report).read_text())['containerization']=='passed'

@pytest.mark.skipif(os.environ.get('RUN_DOCKER_TESTS')!='1',reason='Real Docker failure gate')
def test_runtime_failure_never_creates_branch(cfg,tmp_path):
    repo=init_repo(tmp_path/'app',True);cfg['app']['health_path']='/does-not-exist'
    args=arguments(repo,cfg,tmp_path);before=agent.git(repo,'show-ref')
    assert agent.prepare_role(args,'app')==2
    assert agent.git(repo,'show-ref')==before
    assert not (tmp_path/'app-eks-orders').exists()

def test_missing_docker_still_writes_blocked_report(cfg,tmp_path,monkeypatch):
    repo=tmp_path/'app';repo.mkdir()
    monkeypatch.setattr(agent,'source_check',lambda *a,**k: set())
    monkeypatch.setattr(agent.shutil,'which',lambda name: None)
    def unavailable(*a,**k):raise OSError('Docker unavailable')
    monkeypatch.setattr(agent,'command',unavailable)
    path=tmp_path/'blocked.json'
    result=agent.containerize(repo,cfg,'a'*40,path)
    assert result['containerization']=='blocked'
    assert json.loads(path.read_text())['status']=='blocked'
