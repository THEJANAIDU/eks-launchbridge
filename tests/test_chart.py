import os
from pathlib import Path
import shutil
import subprocess
import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]
HELM=os.environ.get('HELM_BINARY') or shutil.which('helm')
pytestmark=pytest.mark.skipif(not HELM,reason='Helm 3 is required for chart validation')

def test_chart_security_digest_and_resources():
    args=[HELM,'template','orders',str(ROOT/'templates/chart'),'--set-string','image.digest=sha256:'+'a'*64]
    result=subprocess.run(args,text=True,capture_output=True,check=True)
    docs=[d for d in yaml.safe_load_all(result.stdout) if d]
    deployment=next(d for d in docs if d['kind']=='Deployment')
    pod=deployment['spec']['template']['spec'];container=pod['containers'][0]
    assert '@sha256:' in container['image']
    assert pod['securityContext']['runAsNonRoot'] is True
    assert container['securityContext']['readOnlyRootFilesystem'] is True
    assert container['securityContext']['capabilities']['drop']==['ALL']
    assert all(k in container for k in ('startupProbe','readinessProbe','livenessProbe','resources'))
    assert next(d for d in docs if d['kind']=='Service')['spec']['type']=='ClusterIP'
    assert next(d for d in docs if d['kind']=='NetworkPolicy')['spec']['policyTypes']==['Ingress','Egress']
    assert any(d['kind']=='PodDisruptionBudget' for d in docs)
    assert any(d['kind']=='HorizontalPodAutoscaler' for d in docs)

def test_chart_refuses_missing_digest_or_single_replica():
    assert subprocess.run([HELM,'template','orders',str(ROOT/'templates/chart')],capture_output=True).returncode!=0
    assert subprocess.run([HELM,'template','orders',str(ROOT/'templates/chart'),'--set-string','image.digest=sha256:'+'a'*64,'--set','replicas=1'],capture_output=True).returncode!=0
