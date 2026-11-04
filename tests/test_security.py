import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


d = load('tcdeploy')
b = load('build_image')
DIGEST = 'sha256:' + 'a' * 64
CONFIG = 'sha256:' + 'b' * 64
SHA = 'c' * 40
RELEASE = SHA + '-123'


def manifest():
    return d.read_manifest(ROOT / 'examples/deploy.dev.json')


def task(m):
    return {'family': m['taskFamily'], 'status': 'ACTIVE', 'revision': 1,
        'taskDefinitionArn': d.arn(m, 'ecs', 'task-definition/' + m['taskFamily'] + ':1'),
        'taskRoleArn': m['taskRoleArn'], 'executionRoleArn': m['executionRoleArn'],
        'networkMode': 'awsvpc', 'requiresCompatibilities': ['FARGATE'], 'cpu': '512', 'memory': '1024',
        'volumes': [{'name': 'scratch'}], 'runtimePlatform': {'cpuArchitecture': 'X86_64', 'operatingSystemFamily': 'LINUX'},
        'containerDefinitions': [{'name': 'example-v6', 'image': 'old@' + DIGEST,
            'essential': True, 'readonlyRootFilesystem': True,
            'healthCheck': {'command': ['CMD', 'true']},
            'environment': [{'name': 'PORT', 'value': '3000'}],
            'secrets': [{'name': 'DATABASE_URL', 'valueFrom': 'arn:aws:ssm:us-east-1:111111111111:parameter/config/example/appvar/DATABASE_URL'}],
            'mountPoints': [{'sourceVolume': 'scratch', 'containerPath': '/tmp'}]}]}


def service(m, definition=None):
    definition = definition or task(m)['taskDefinitionArn']
    return {'serviceArn': d.arn(m, 'ecs', f"service/{m['cluster']}/{m['service']}"), 'status': 'ACTIVE',
            'desiredCount': 1, 'runningCount': 1, 'pendingCount': 0,
            'taskDefinition': definition, 'deploymentController': {'type': 'ECS'},
            'deploymentConfiguration': {'deploymentCircuitBreaker': {'enable': True, 'rollback': True}},
            'deployments': [{'taskDefinition': definition, 'rolloutState': 'COMPLETED'}]}


class FakeAWS:
    def __init__(self, m):
        self.m = m
        self.calls = []
        self.task = task(m)
        self.tags = [{'key': 'owner', 'value': 'team'}]
        self.service = service(m)
        self.registered = None
        self.before = None
        self.env = {}

    def call(self, api, operation, **params):
        self.calls.append((api, operation, deepcopy(params)))
        if self.before:
            self.before(api, operation, params)
        if (api, operation) == ('ecs', 'describe-services'):
            return {'services': [deepcopy(self.service)]}
        if (api, operation) == ('ecs', 'describe-task-definition'):
            return {'taskDefinition': deepcopy(self.registered or self.task), 'tags': deepcopy(self.tags)}
        if (api, operation) == ('ecs', 'register-task-definition'):
            if 'tags' in params and not params['tags']:
                raise d.DeployError('Tags can not be empty.')
            self.registered = deepcopy(params)
            self.tags = self.registered.pop('tags', [])
            self.registered.update(status='ACTIVE', revision=2, taskDefinitionArn=self.task['taskDefinitionArn'][:-1] + '2')
            return {'taskDefinition': deepcopy(self.registered)}
        if (api, operation) == ('ecs', 'update-service'):
            self.service = service(self.m, params['taskDefinition'])
            return {'service': deepcopy(self.service)}
        if (api, operation) == ('ecs', 'list-tasks'):
            return {'taskArns': ['task-1']}
        if (api, operation) == ('ecs', 'describe-tasks'):
            return {'tasks': [{'taskDefinitionArn': self.service['taskDefinition'], 'lastStatus': 'RUNNING',
                              'healthStatus': 'HEALTHY', 'containers': [{'name': 'example-v6', 'imageDigest': DIGEST}]}]}
        raise AssertionError((api, operation))


class FakePublisher:
    def __init__(self, m):
        self.m = m
        self.calls = []

    def publish(self, name, local, release, deadline):
        self.calls.append(name)
        return f"{self.m['accountId']}.dkr.ecr.{self.m['region']}.amazonaws.com/{self.m['images'][name]}@{DIGEST}"


class ManifestTests(unittest.TestCase):
    def check_invalid(self, key, value):
        m = manifest()
        m[key] = value
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'manifest.json'
            p.write_text(json.dumps(m))
            with self.assertRaises(d.DeployError):
                d.read_manifest(p)

    def test_expected_example(self):
        self.assertEqual(manifest()['environment'], 'dev')

    def test_wrong_account_role(self):
        self.check_invalid('executionRoleArn', 'arn:aws:iam::222222222222:role/other')

    def test_absent_task_role_does_not_grant_runtime_permissions(self):
        m = manifest()
        m['taskRoleArn'] = None
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'manifest.json'
            p.write_text(json.dumps(m))
            self.assertIsNone(d.read_manifest(p)['taskRoleArn'])
        self.assertEqual(d.role_policy(m)['Statement'][-1]['Resource'], [m['executionRoleArn']])
        self.check_invalid('taskRoleArn', '')

    def test_shell_injection_is_invalid_data(self):
        self.check_invalid('service', 'x; touch /tmp/marker')

    def test_wildcard_role(self):
        self.check_invalid('deployRoleArn', 'arn:aws:iam::111111111111:role/*')

    def test_production_branch_guard(self):
        self.check_invalid('environment', 'prod')

    def test_legacy_dev_branch_has_exact_trust(self):
        m = manifest()
        m['branch'] = 'dev'
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'manifest.json'
            p.write_text(json.dumps(m))
            self.assertEqual(d.read_manifest(p)['branch'], 'dev')
        subject = next(iter(d.trust_policy(m)['Statement'][0]['Condition']['StringLike'].values()))
        self.assertIn(':checkout-ref:refs/heads/dev:', subject)
        self.assertTrue(subject.endswith(':config-ref:refs/heads/dev'))
        self.check_invalid('branch', 'feature/deploy')
        self.check_invalid('branch', 'master')

    def test_legacy_prod_branch_has_exact_trust(self):
        m = manifest()
        m.update(environment='prod', branch='prod')
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'manifest.json'
            p.write_text(json.dumps(m))
            self.assertEqual(d.read_manifest(p)['branch'], 'prod')
        subject = next(iter(d.trust_policy(m)['Statement'][0]['Condition']['StringLike'].values()))
        self.assertIn(':checkout-ref:refs/heads/prod:', subject)
        self.assertTrue(subject.endswith(':config-ref:refs/heads/prod'))
        m['branch'] = 'develop'
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'manifest.json'
            p.write_text(json.dumps(m))
            with self.assertRaises(d.DeployError): d.read_manifest(p)

    def test_unknown_fields(self):
        self.check_invalid('parameterPath', '/config/app')

    def test_duplicate_json_key(self):
        with self.assertRaises(d.DeployError):
            json.loads('{"a":1,"a":2}', object_pairs_hook=d.unique_object)

    def test_policies_bind_identity_and_forbid_parameters(self):
        m = manifest()
        trust = d.trust_policy(m)
        text = json.dumps(trust)
        self.assertIn(':config-ref:refs/heads/develop', text)
        self.assertIn(':checkout-source:github.com/example/example-v6:', text)
        self.assertIn('project:' + m['circleciProjectId'], text)
        for policy in (d.role_policy(m), d.SESSION_POLICY):
            deny = policy['Statement'][0]
            self.assertEqual(deny['Effect'], 'Deny')
            self.assertTrue({'ssm:*', 'secretsmanager:*', 'kms:Decrypt', 'sts:AssumeRole*'} <= set(deny['Action']))
        self.assertLess(len(d.compact(d.SESSION_POLICY)), 2048)
        passrole = d.role_policy(m)['Statement'][-1]
        self.assertEqual(passrole['Resource'], [m['taskRoleArn'], m['executionRoleArn']])

    def test_enhanced_scan_permissions_are_read_only_and_region_limited(self):
        m = manifest()
        inspector = [s for s in d.role_policy(m)['Statement']
                     if any(a.startswith('inspector2:') for a in s['Action'])]
        self.assertEqual(inspector, [{'Effect': 'Allow',
            'Action': ['inspector2:ListFindings', 'inspector2:ListCoverage'], 'Resource': '*',
            'Condition': {'StringEquals': {'aws:RequestedRegion': m['region']}}}])
        for policy in (d.session_policy(), d.session_policy(d.ADAPTER_ACTIONS)):
            actions = policy['Statement'][1]['Action']
            self.assertEqual({a for a in actions if a.startswith('inspector2:')},
                             {'inspector2:ListFindings', 'inspector2:ListCoverage'})
            self.assertEqual(len(actions), len(set(actions)))
            self.assertLessEqual(len(d.compact(policy)), 2048)


class CredentialTests(unittest.TestCase):
    def test_ecs_service_parameter_reaches_the_cli_without_name_collision(self):
        with patch.object(d, 'execute', return_value='{}') as execute:
            d.AWS('us-east-1').call('ecs', 'update-service', cluster='cluster', service='application')
        command, environment, payload = execute.call_args.args
        self.assertEqual(command[:3], ['aws', 'ecs', 'update-service'])
        self.assertEqual(json.loads(payload), {'cluster': 'cluster', 'service': 'application'})

    def test_adapter_capabilities_cannot_remove_secret_deny(self):
        policy = d.session_policy(d.ADAPTER_ACTIONS)
        self.assertEqual(policy['Statement'][0], d.SESSION_POLICY['Statement'][0])
        self.assertLessEqual(len(d.compact(policy)), 2048)
        self.assertIn('ecs:RunTask', policy['Statement'][1]['Action'])
        self.assertNotIn('ecs:RunTask', d.SESSION_POLICY['Statement'][1]['Action'])

    def test_adapter_cannot_request_secret_access_or_role_chaining(self):
        for action in ('ssm:GetParameter', 'secretsmanager:GetSecretValue', 'sts:AssumeRole',
                       'cloudformation:CreateStack', '*'):
            with self.subTest(action=action), self.assertRaises(d.DeployError):
                d.session_policy([action])

    def response(self):
        m = manifest()
        return [{'Credentials': {'AccessKeyId': 'ASIA' + 'A' * 16, 'SecretAccessKey': 'dummy-secret',
                                 'SessionToken': 'dummy-session', 'Expiration': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}},
                {'Account': m['accountId'], 'Arn': 'arn:aws:sts::111111111111:assumed-role/example-v6-dev-deploy/session'}]

    def test_oidc_no_credential_file_and_restricted_session(self):
        with patch.object(d.AWS, 'call', side_effect=self.response()) as call:
            aws = d.authenticate(manifest(), 'x' * 200)
        self.assertEqual(aws.env['AWS_SESSION_TOKEN'], 'dummy-session')
        self.assertEqual(json.loads(call.call_args_list[0].kwargs['Policy']), d.SESSION_POLICY)
        self.assertNotIn('CI_AUTH0_CLIENTSECRET', aws.env)

    def test_no_auth0_or_ambient_fallback(self):
        with patch.dict(os.environ, {'CI_AUTH0_CLIENTSECRET': 'secret', 'AWS_ACCESS_KEY_ID': 'key'}), patch.object(d.AWS, 'call') as call:
            with self.assertRaises(d.DeployError):
                d.authenticate(manifest(), None)
            call.assert_not_called()

    def test_auth_error_propagates(self):
        with patch.object(d.AWS, 'call', side_effect=d.DeployError('AccessDenied')):
            with self.assertRaises(d.DeployError):
                d.authenticate(manifest(), 'x' * 200)

    def test_wrong_role_or_account_is_rejected(self):
        for key, value in [('Account', '222222222222'), ('Arn', 'arn:aws:sts::111111111111:assumed-role/other/session')]:
            response = self.response()
            response[1][key] = value
            with patch.object(d.AWS, 'call', side_effect=response), self.assertRaises(d.DeployError):
                d.authenticate(manifest(), 'x' * 200)

    def test_missing_session_token(self):
        response = self.response()
        del response[0]['Credentials']['SessionToken']
        with patch.object(d.AWS, 'call', side_effect=response), self.assertRaises(d.DeployError):
            d.authenticate(manifest(), 'x' * 200)

    def test_static_keys_rejected(self):
        response = self.response()
        response[0]['Credentials']['AccessKeyId'] = 'AKIA' + 'A' * 16
        with patch.object(d.AWS, 'call', side_effect=response), self.assertRaises(d.DeployError):
            d.authenticate(manifest(), 'x' * 200)

    def test_expired_session(self):
        response = self.response()
        response[0]['Credentials']['Expiration'] = '2000-01-01T00:00:00Z'
        with patch.object(d.AWS, 'call', side_effect=response), self.assertRaises(d.DeployError):
            d.authenticate(manifest(), 'x' * 200)

    def test_subprocess_environment_excludes_provider_overrides(self):
        with patch.dict(os.environ, {'AWS_PROFILE': 'admin', 'AWS_ENDPOINT_URL': 'https://evil.invalid',
                    'CI_AUTH0_CLIENTSECRET': 'secret', 'CIRCLE_OIDC_TOKEN_V3': 'token', 'BASH_ENV': '/tmp/evil',
                    'AWS_WEB_IDENTITY_TOKEN_FILE': '/tmp/evil', 'HTTPS_PROXY': 'https://evil.invalid'}):
            clean = d.clean_environment('us-east-1')
        for key in ('AWS_PROFILE', 'AWS_ENDPOINT_URL', 'CI_AUTH0_CLIENTSECRET', 'CIRCLE_OIDC_TOKEN_V3',
                    'BASH_ENV', 'AWS_WEB_IDENTITY_TOKEN_FILE', 'HTTPS_PROXY'):
            self.assertNotIn(key, clean)

    def test_aws_json_on_stdin_never_argv(self):
        with patch.object(d, 'execute', return_value='{}') as execute:
            d.AWS('us-east-1').call('sts', 'assume-role-with-web-identity', WebIdentityToken='secret-token')
        self.assertNotIn('secret-token', str(execute.call_args.args[0]))
        self.assertIn('secret-token', execute.call_args.args[2])

    def test_subprocess_can_reopen_json_stdin(self):
        # Exercise real file descriptors: a subprocess PIPE fails on the second
        # open, just like AWS CLI's repeated loading of file:///dev/stdin.
        script = '''
import json, pathlib
first = json.loads(pathlib.Path('/dev/stdin').read_text())
second = json.loads(pathlib.Path('/dev/stdin').read_text())
assert first == second and first['WebIdentityToken'] == 'dummy-secret'
print('ok')
'''
        result = d.execute([sys.executable, '-c', script], d.clean_environment('us-east-1'),
                           json.dumps({'WebIdentityToken': 'dummy-secret'}))
        self.assertEqual(result.strip(), 'ok')

    @unittest.skipUnless(shutil.which('aws'), 'AWS CLI integration runs in the pinned executor')
    def test_aws_cli_parses_stdin_offline(self):
        command = ['aws', 'ecr', 'describe-images', '--region', 'us-east-1',
                   '--cli-input-json', 'file:///dev/stdin', '--generate-cli-skeleton', 'output']
        result = d.execute(command, d.clean_environment('us-east-1'),
                           json.dumps({'repositoryName': 'example', 'imageIds': [{'imageTag': 'test'}]}))
        self.assertIsInstance(json.loads(result)['imageDetails'], list)

    def test_input_descriptor_closed_after_success_and_failure(self):
        for fails in (False, True):
            descriptors = []
            def run(command, **kwargs):
                stream = kwargs['stdin']
                descriptors.append(stream)
                self.assertNotIn('dummy-secret', str(command))
                self.assertIn('/memfd:', os.readlink('/proc/self/fd/' + str(stream.fileno())))
                self.assertEqual(stream.read(), 'dummy-secret')
                if fails:
                    raise subprocess.TimeoutExpired(command, 1)
                return subprocess.CompletedProcess(command, 0, '', '')
            with patch.object(d.subprocess, 'run', side_effect=run):
                if fails:
                    with self.assertRaises(d.DeployError):
                        d.execute(['aws'], {}, 'dummy-secret')
                else:
                    d.execute(['aws'], {}, 'dummy-secret')
            self.assertTrue(descriptors[0].closed)

    def test_no_secret_api_even_on_explicit_call(self):
        with patch.object(d, 'execute') as execute:
            for api in ('ssm', 'secretsmanager', 'kms', 'iam', 'cloudformation'):
                with self.assertRaises(d.DeployError):
                    d.AWS('us-east-1').call(api, 'get-parameter')
            execute.assert_not_called()

    def test_command_error_does_not_include_secrets(self):
        result = subprocess.CompletedProcess([], 1, 'dummy-secret', 'An error occurred (AccessDenied) dummy-secret')
        with patch.object(d.subprocess, 'run', return_value=result):
            with self.assertRaises(d.DeployError) as caught:
                d.execute(['aws'], {}, 'secret')
        self.assertNotIn('dummy-secret', str(caught.exception))
        self.assertIn('AccessDenied', str(caught.exception))

    def test_aws_error_identifies_operation_without_exposing_payloads(self):
        result = subprocess.CompletedProcess([], 1, 'response-secret',
            'An error occurred (ClientException) request-secret response-secret')
        with patch.object(d.subprocess, 'run', return_value=result):
            with self.assertRaises(d.DeployError) as caught:
                d.AWS('us-east-1').call('ecs', 'register-task-definition',
                                     containerDefinitions=[{'environment': [{'value': 'request-secret'}]}])
        self.assertIn('AWS ecs register-task-definition:', str(caught.exception))
        self.assertTrue(str(caught.exception).endswith(': ClientException'))
        self.assertNotIn('request-secret', str(caught.exception))
        self.assertNotIn('response-secret', str(caught.exception))

    def test_aws_scan_error_preserves_retry_suffix(self):
        with patch.object(d, 'execute', side_effect=d.DeployError('External command failed: ScanNotFoundException')):
            with self.assertRaises(d.DeployError) as caught:
                d.AWS('us-east-1').call('ecr', 'describe-image-scan-findings')
        self.assertTrue(str(caught.exception).endswith(': ScanNotFoundException'))


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.m = manifest()
        self.aws = FakeAWS(self.m)
        self.publisher = FakePublisher(self.m)

    def deploy(self, checks=None):
        return d.deploy(self.aws, self.m, {'example-v6': 'example:build'}, RELEASE, self.publisher, checks)

    def test_full_release_never_calls_ssm_and_preserves_roles_secrets(self):
        original = deepcopy(self.aws.task)
        result = self.deploy()
        self.assertTrue(result['taskDefinition'].endswith(':2'))
        self.assertEqual(set(a for a, _, _ in self.aws.calls), {'ecs'})
        self.assertEqual(self.aws.registered['executionRoleArn'], original['executionRoleArn'])
        self.assertEqual(self.aws.registered['containerDefinitions'][0]['secrets'], original['containerDefinitions'][0]['secrets'])
        self.assertEqual(self.aws.registered['volumes'], original['volumes'])

    def test_untagged_task_omits_tags_and_passes_readback(self):
        for include_tags_field in (True, False):
            with self.subTest(include_tags_field=include_tags_field):
                self.aws = FakeAWS(self.m)
                self.aws.tags = []
                call = self.aws.call
                def describe_without_tags(api, operation, **params):
                    response = call(api, operation, **params)
                    if operation == 'describe-task-definition' and not include_tags_field:
                        response.pop('tags')
                    return response
                with patch.object(self.aws, 'call', side_effect=describe_without_tags):
                    result = self.deploy()
                self.assertTrue(result['taskDefinition'].endswith(':2'))
                registration = next(p for _, op, p in self.aws.calls if op == 'register-task-definition')
                self.assertNotIn('tags', registration)
                self.assertEqual(self.aws.tags, [])

    def test_existing_tags_and_empty_tag_values_are_preserved(self):
        self.aws.tags = [{'key': 'owner', 'value': 'team'}, {'key': 'environment', 'value': ''}]
        original = deepcopy(self.aws.tags)
        self.deploy()
        registration = next(p for _, op, p in self.aws.calls if op == 'register-task-definition')
        self.assertEqual(registration['tags'], original)

    def test_malformed_tags_stop_before_publication(self):
        for tags in (None, {}, '', False):
            with self.subTest(tags=tags):
                self.aws.tags = tags
                with self.assertRaises(d.DeployError):
                    self.deploy()
                self.assertEqual(self.publisher.calls, [])

    def test_changed_tags_stop_before_service_update(self):
        for original, changed in [([], [{'key': 'unexpected', 'value': 'tag'}]),
                                  ([{'key': 'owner', 'value': 'team'}], [])]:
            with self.subTest(original=original, changed=changed):
                self.aws = FakeAWS(self.m)
                self.aws.tags = original
                def tamper(api, operation, params):
                    if operation == 'describe-task-definition' and self.aws.registered:
                        self.aws.tags = changed
                self.aws.before = tamper
                with self.assertRaises(d.DeployError):
                    self.deploy()
                self.assertNotIn('update-service', [op for _, op, _ in self.aws.calls])

    def test_fargate_role_never_overwritten(self):
        self.aws.task['executionRoleArn'] = 'arn:aws:iam::111111111111:role/ecsTaskExecutionRole'
        with self.assertRaises(d.DeployError):
            self.deploy()
        self.assertEqual(self.publisher.calls, [])

    def test_reset_secret_or_literal_forbidden_before_publish(self):
        for field, value in [('secrets', {'name': 'RESET_DB', 'valueFrom': '/config/RESET_DB'}),
                             ('environment', {'name': 'RESET_DB', 'value': 'true'})]:
            with self.subTest(field=field):
                self.aws.task = task(self.m)
                self.aws.task['containerDefinitions'][0][field].append(value)
                with self.assertRaises(d.DeployError):
                    self.deploy()
                self.assertEqual(self.publisher.calls, [])

    def test_plaintext_runtime_secret_rejected(self):
        self.aws.task['containerDefinitions'][0]['environment'].append({'name': 'DATABASE_URL', 'value': 'secret'})
        with self.assertRaises(d.DeployError):
            self.deploy()

    def test_public_token_metadata_is_preserved(self):
        entries = [{'name': name, 'value': 'https://issuer.example.test/audience/'}
                   for name in d.PUBLIC_TOKEN_URLS]
        entries.append({'name': 'TOKEN_CACHE_TIME', 'value': '86400'})
        self.aws.task['containerDefinitions'][0]['environment'] += entries
        self.deploy()
        self.assertEqual(self.aws.registered['containerDefinitions'][0]['environment'][-4:], entries)

    def test_public_metadata_does_not_allow_credentials(self):
        values = ['opaque-token', 'http://issuer.test', 'https://user:pass@issuer.test',
                  'https://@issuer.test', 'https://issuer.test/?token=secret',
                  'https://issuer.test/#secret', 'https://issuer.test:bad',
                  'https://issuer.test:0', 'https://issuer.test/ white', 'https://']
        entries = [(name, value) for name in d.PUBLIC_TOKEN_URLS for value in values]
        entries += [('TOKEN_CACHE_TIME', value) for value in ['secret', '-1', '1.2', '2147483648']]
        entries += [(name, 'https://issuer.test') for name in
                    ['AUTH0_CLIENT_SECRET', 'DB_PASSWORD', 'ACCESS_TOKEN', 'OTHER_TOKEN_ISSUER']]
        for name, value in entries:
            with self.subTest(name=name, value=value):
                self.aws.task = task(self.m)
                self.aws.task['containerDefinitions'][0]['environment'].append({'name': name, 'value': value})
                with self.assertRaises(d.DeployError): self.deploy()
                self.assertEqual(self.publisher.calls, [])

    def test_missing_health_requires_explicit_bootstrap(self):
        del self.aws.task['containerDefinitions'][0]['healthCheck']
        with self.assertRaises(d.DeployError): self.deploy()
        self.assertEqual(self.publisher.calls, [])
        self.assertIsNone(self.aws.registered)

    def test_bootstrap_adds_health_atomically_and_preserves_configuration(self):
        del self.aws.task['containerDefinitions'][0]['healthCheck']
        self.aws.task['containerDefinitions'].append({'name': 'metrics', 'image': 'trusted@' + DIGEST, 'essential': False})
        original = deepcopy(self.aws.task)
        checks = {'example-v6': {'command': ['CMD', 'node', 'health.js'], 'interval': 30, 'timeout': 5, 'retries': 3, 'startPeriod': 120}}
        self.deploy(checks)
        self.assertEqual(self.aws.task, original)
        request = next(p for _, op, p in self.aws.calls if op == 'register-task-definition')
        expected = {k: deepcopy(v) for k, v in original.items() if k in d.TASK_FIELDS}
        expected['tags'] = self.aws.tags
        expected['containerDefinitions'][0]['image'] = self.publisher.publish('example-v6', '', '', 0)
        expected['containerDefinitions'][0]['healthCheck'] = checks['example-v6']
        self.assertEqual(request, expected)
        operations = [op for _, op, _ in self.aws.calls]
        self.assertEqual(operations.count('update-service'), 1)
        self.assertLess(operations.index('register-task-definition'), operations.index('update-service'))

    def test_bootstrap_never_replaces_existing_health(self):
        checks = {'example-v6': {'command': ['CMD', 'false']}}
        with self.assertRaises(d.DeployError): self.deploy(checks)
        self.assertEqual(self.publisher.calls, [])
        checks['example-v6'] = deepcopy(self.aws.task['containerDefinitions'][0]['healthCheck'])
        self.deploy(checks)

    def test_invalid_bootstrap_stops_before_publication(self):
        invalid = [{}, [], {'sidecar': {'command': ['CMD', 'true']}},
                   {'example-v6': {'command': ['CMD-SHELL', 'true']}},
                   {'example-v6': {'command': ['CMD']}},
                   {'example-v6': {'command': ['CMD', 'true'], 'unknown': 1}}]
        for key, values in {'interval': [4, 301, True], 'timeout': [1, 61],
                            'retries': [0, 11], 'startPeriod': [-1, 301]}.items():
            invalid += [{'example-v6': {'command': ['CMD', 'true'], key: value}} for value in values]
        for checks in invalid:
            with self.subTest(checks=checks):
                with self.assertRaises(d.DeployError): self.deploy(checks)
                self.assertEqual(self.publisher.calls, [])
                self.assertIsNone(self.aws.registered)

    def test_bootstrap_scan_failure_leaves_old_revision_untouched(self):
        del self.aws.task['containerDefinitions'][0]['healthCheck']
        original = deepcopy(self.aws.task)
        with patch.object(self.publisher, 'publish', side_effect=d.DeployError('Scan failed')):
            with self.assertRaises(d.DeployError):
                self.deploy({'example-v6': {'command': ['CMD', 'true']}})
        self.assertEqual(self.aws.task, original)
        self.assertIsNone(self.aws.registered)
        self.assertNotIn('update-service', [op for _, op, _ in self.aws.calls])

    def test_bootstrap_readback_tampering_stops_update(self):
        del self.aws.task['containerDefinitions'][0]['healthCheck']
        def tamper(api, operation, params):
            if operation == 'describe-task-definition' and self.aws.registered:
                self.aws.registered['containerDefinitions'][0]['healthCheck'] = {'command': ['CMD', 'false']}
        self.aws.before = tamper
        with self.assertRaises(d.DeployError):
            self.deploy({'example-v6': {'command': ['CMD', 'true']}})
        self.assertNotIn('update-service', [op for _, op, _ in self.aws.calls])

    def test_bootstrap_native_rollback_remains_failed(self):
        del self.aws.task['containerDefinitions'][0]['healthCheck']
        def rollback(api, operation, params):
            if operation == 'describe-services' and any(op == 'update-service' for _, op, _ in self.aws.calls):
                self.aws.service = service(self.m)
        self.aws.before = rollback
        with self.assertRaises(d.DeployError):
            self.deploy({'example-v6': {'command': ['CMD', 'true']}})

    def test_duplicate_bootstrap_fields_fail_before_authentication(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'health.json'
            p.write_text('{"example-v6":{"command":["CMD","true"],"command":["CMD","false"]}}')
            with patch.object(d, 'authenticate') as authenticate:
                with self.assertRaises(d.DeployError):
                    d.main(['deploy', '--manifest', str(ROOT / 'examples/deploy.dev.json'),
                            '--image', 'example-v6=example:build', '--bootstrap-health-checks', str(p)])
                authenticate.assert_not_called()

    def test_task_unknown_fields_fail_closed(self):
        self.aws.task['newUnsupportedField'] = True
        with self.assertRaises(d.DeployError):
            self.deploy()

    def test_no_zero_capacity_false_success(self):
        self.aws.service['desiredCount'] = self.aws.service['runningCount'] = 0
        with self.assertRaises(d.DeployError):
            self.deploy()

    def test_steady_event_does_not_replace_revision_check(self):
        state = service(self.m)
        state['events'] = [{'message': 'has reached steady state'}]
        with self.assertRaises(d.DeployError):
            d.stable(state, 'different-revision')

    def test_required_circuit_breaker(self):
        self.aws.service['deploymentConfiguration'] = {}
        with self.assertRaises(d.DeployError):
            self.deploy()

    def test_circuit_breaker_accepts_optional_ecs_settings(self):
        breaker = self.aws.service['deploymentConfiguration']['deploymentCircuitBreaker']
        breaker.update(resetOnHealthyTask=True,
                       thresholdConfiguration={'type': 'BOUNDED_PERCENT', 'value': 50})
        original = deepcopy(breaker)
        checked = d.read_service(self.aws, self.m)
        self.assertEqual(checked['deploymentConfiguration']['deploymentCircuitBreaker'], original)
        self.deploy()
        updates = [params for _, op, params in self.aws.calls if op == 'update-service']
        self.assertEqual(len(updates), 1)
        self.assertNotIn('deploymentConfiguration', updates[0])

    def test_circuit_breaker_requires_literal_true_flags(self):
        for flag in ('enable', 'rollback'):
            for value in (False, None, 0, 1, 'true'):
                with self.subTest(flag=flag, value=value):
                    breaker = {'enable': True, 'rollback': True, 'resetOnHealthyTask': True,
                               'thresholdConfiguration': {'type': 'BOUNDED_PERCENT', 'value': 50}}
                    breaker[flag] = value
                    self.aws.service['deploymentConfiguration']['deploymentCircuitBreaker'] = breaker
                    with self.assertRaises(d.DeployError):
                        self.deploy()
                    self.assertEqual(self.publisher.calls, [])
                    self.assertIsNone(self.aws.registered)

    def test_circuit_breaker_rejects_missing_flags_and_malformed_objects(self):
        for breaker in (None, [], 'enabled', {}, {'enable': True}, {'rollback': True}):
            with self.subTest(breaker=breaker):
                self.aws.service['deploymentConfiguration']['deploymentCircuitBreaker'] = breaker
                with self.assertRaises(d.DeployError):
                    self.deploy()
                self.assertEqual(self.publisher.calls, [])
                self.assertIsNone(self.aws.registered)

    def test_ssm_failure_cannot_be_silently_ignored_because_no_read_exists(self):
        def fail_secret_calls(api, operation, params):
            self.assertNotIn(api, ('ssm', 'secretsmanager', 'kms'))
        self.aws.before = fail_secret_calls
        self.deploy()

    def test_register_failure_stops_before_update(self):
        def fail(api, operation, params):
            if operation == 'register-task-definition':
                raise d.DeployError('AccessDenied')
        self.aws.before = fail
        with self.assertRaises(d.DeployError):
            self.deploy()
        self.assertNotIn('update-service', [op for _, op, _ in self.aws.calls])

    def test_concurrent_service_change_stops_promotion(self):
        original_publish = self.publisher.publish
        def publish(*args):
            self.aws.service = service(self.m, 'other:3')
            return original_publish(*args)
        self.publisher.publish = publish
        with self.assertRaises(d.DeployError):
            self.deploy()
        self.assertNotIn('register-task-definition', [op for _, op, _ in self.aws.calls])

    def test_registered_image_tampering_stops_update(self):
        def tamper(api, operation, params):
            if operation == 'describe-task-definition' and self.aws.registered:
                self.aws.registered['containerDefinitions'][0]['image'] = 'evil@' + DIGEST
        self.aws.before = tamper
        with self.assertRaises(d.DeployError):
            self.deploy()
        self.assertNotIn('update-service', [op for _, op, _ in self.aws.calls])

    def test_rollout_rollback_fails(self):
        def rollback(api, operation, params):
            if operation == 'describe-services' and any(op == 'update-service' for _, op, _ in self.aws.calls):
                self.aws.service = service(self.m)
        self.aws.before = rollback
        with self.assertRaises(d.DeployError):
            self.deploy()

    def test_wrong_task_digest_is_not_healthy(self):
        self.assertFalse(d.verify_running(self.aws, self.m, self.aws.service['taskDefinition'], {'example-v6': 'image@sha256:' + 'f' * 64}, 1))

    def test_missing_image_fails(self):
        with self.assertRaises(d.DeployError):
            d.deploy(self.aws, self.m, {}, RELEASE, self.publisher)

    def test_sidecars_preserved(self):
        sidecar = {'name': 'metrics', 'image': 'trusted@' + DIGEST, 'essential': False}
        self.aws.task['containerDefinitions'].append(sidecar)
        self.deploy()
        self.assertEqual(self.aws.registered['containerDefinitions'][1], sidecar)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.m = manifest()
        self.aws = FakeAWS(self.m)
        self.publisher = d.Publisher(self.aws, self.m, '/tmp/dummy-docker-config')
        self.info = {'Id': CONFIG, 'Os': 'linux', 'Architecture': 'amd64', 'Config': {'User': '10001', 'Env': ['RESET_DB=false'],
                     'Labels': {'org.opencontainers.image.revision': SHA}}}
        self.scan = {'imageScanStatus': {'status': 'COMPLETE'}, 'imageScanFindings': {'imageScanCompletedAt': datetime.now(timezone.utc).isoformat(), 'findingSeverityCounts': {}}}
        self.digest_config = CONFIG
        self.mutability = 'IMMUTABLE'
        self.calls = []

    def ecr(self, api, op, **params):
        self.calls.append(op)
        self.assertEqual(api, 'ecr')
        registry = self.publisher.registry
        if op == 'describe-repositories':
            return {'repositories': [{'repositoryUri': registry + '/example-v6', 'imageTagMutability': self.mutability}]}
        if op == 'get-authorization-token':
            return {'authorizationData': [{'proxyEndpoint': 'https://' + registry, 'authorizationToken': base64.b64encode(b'AWS:dummy-password').decode()}]}
        if op == 'describe-images':
            return {'imageDetails': [{'imageDigest': DIGEST}]}
        if op == 'batch-get-image':
            return {'images': [{'imageManifest': json.dumps({'config': {'digest': self.digest_config}})}]}
        if op == 'describe-image-scan-findings':
            return self.scan
        raise AssertionError(op)

    def publish(self):
        with patch.object(self.publisher, 'docker', return_value=json.dumps([self.info])) as docker, patch.object(self.aws, 'call', side_effect=self.ecr):
            result = self.publisher.publish('example-v6', 'example:build', RELEASE, float('inf'))
        return result, docker

    def test_publish_verifies_digest_and_password_stdin(self):
        result, docker = self.publish()
        self.assertTrue(result.endswith('@' + DIGEST))
        login = next(c for c in docker.call_args_list if c.args[0] == 'login')
        self.assertNotIn('dummy-password', str(login.args))
        self.assertEqual(login.kwargs['input_text'], 'dummy-password')
        self.assertNotIn('AWS_ACCESS_KEY_ID', self.publisher.env)

    def test_wrong_artifact_digest(self):
        self.digest_config = 'sha256:' + 'f' * 64
        with self.assertRaises(d.DeployError):
            self.publish()

    def test_containerd_configuration_digest(self):
        self.info['Id'] = DIGEST
        self.info['Descriptor'] = {'annotations': {'config.digest': CONFIG}}
        self.publish()

    def test_wrong_source_revision(self):
        self.info['Config']['Labels']['org.opencontainers.image.revision'] = 'f' * 40
        with self.assertRaises(d.DeployError):
            self.publish()
        self.assertEqual(self.calls, [])

    def test_mutable_tag_repository(self):
        self.mutability = 'MUTABLE'
        with self.assertRaises(d.DeployError):
            self.publish()

    def test_reset_image_rejected(self):
        self.info['Config']['Env'] = ['RESET_DB=true']
        with self.assertRaises(d.DeployError):
            self.publish()

    def test_secret_image_environment_rejected(self):
        self.info['Config']['Env'] = ['AWS_SECRET_ACCESS_KEY=dummy']
        with self.assertRaises(d.DeployError):
            self.publish()

    def test_root_image_rejected(self):
        for user in ('root', '0', '00', '000:1000', 'root:10001', '0:app', ''):
            self.info['Config']['User'] = user
            with self.assertRaises(d.DeployError):
                self.publish()

    def test_stale_scan_rejected(self):
        self.scan['imageScanFindings']['imageScanCompletedAt'] = '2000-01-01T00:00:00Z'
        with self.assertRaises(d.DeployError):
            self.publish()

    def test_failed_scan(self):
        self.scan['imageScanStatus']['status'] = 'FAILED'
        with self.assertRaises(d.DeployError):
            self.publish()

    def empty_scan(self, status='ACTIVE'):
        # Shape returned by ECR for an enhanced scan with zero findings.
        self.scan = {'registryId': self.m['accountId'], 'repositoryName': 'example-v6',
            'imageId': {'imageDigest': DIGEST}, 'imageScanStatus': {'status': status},
            'imageScanFindings': {'imageScanCompletedAt': datetime.now(timezone.utc).isoformat(),
                                  'findings': []}}

    def test_completed_empty_scan_without_counts(self):
        for status in ('ACTIVE', 'COMPLETE'):
            for key in ('findings', 'enhancedFindings'):
                with self.subTest(status=status, key=key):
                    self.empty_scan(status)
                    self.scan['imageScanFindings'].pop('findings')
                    self.scan['imageScanFindings'][key] = []
                    result, _ = self.publish()
                    self.assertTrue(result.endswith('@' + DIGEST))

    def test_missing_counts_and_missing_findings_rejected(self):
        self.empty_scan()
        self.scan['imageScanFindings'].pop('findings')
        with self.assertRaises(d.DeployError):
            self.publish()

    def test_missing_counts_with_nonempty_or_malformed_findings_rejected(self):
        for key in ('findings', 'enhancedFindings'):
            for value in ([{'severity': 'HIGH'}], [{'severity': 'LOW'}], None, {}, ''):
                with self.subTest(key=key, value=value):
                    self.empty_scan()
                    self.scan['imageScanFindings'][key] = value
                    with self.assertRaises(d.DeployError):
                        self.publish()

    def test_empty_first_page_without_counts_rejected(self):
        self.empty_scan()
        self.scan['nextToken'] = 'another-page'
        with self.assertRaises(d.DeployError):
            self.publish()

    def test_empty_scan_must_match_requested_image(self):
        for key, wrong in [('registryId', '222222222222'), ('repositoryName', 'other'),
                           ('imageId', {'imageDigest': 'sha256:' + 'f' * 64})]:
            for value in (wrong, None):
                with self.subTest(key=key, value=value):
                    self.empty_scan()
                    if value is None:
                        self.scan.pop(key)
                    else:
                        self.scan[key] = value
                    with self.assertRaises(d.DeployError):
                        self.publish()

    def test_empty_scan_still_requires_fresh_completion(self):
        for timestamp in ('2000-01-01T00:00:00Z',
                          (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()):
            with self.subTest(timestamp=timestamp):
                self.empty_scan()
                self.scan['imageScanFindings']['imageScanCompletedAt'] = timestamp
                with self.assertRaises(d.DeployError):
                    self.publish()

    def test_empty_scan_rejects_malformed_image_identity(self):
        for image in (None, [], ''):
            with self.subTest(image=image):
                self.empty_scan()
                self.scan['imageId'] = image
                with self.assertRaises(d.DeployError):
                    self.publish()

    def test_empty_findings_do_not_override_failed_status_or_summary(self):
        self.empty_scan('FAILED')
        with self.assertRaises(d.DeployError):
            self.publish()
        for counts in ({'HIGH': 1}, None, [], {'LOW': -1}, {'LOW': True},
                       {'LOW': '0'}, {'UNKNOWN': 0}):
            with self.subTest(counts=counts):
                self.empty_scan()
                self.scan['imageScanFindings']['findingSeverityCounts'] = counts
                with self.assertRaises(d.DeployError):
                    self.publish()

    def test_severity_gate(self):
        for level in ('CRITICAL', 'HIGH', 'MEDIUM', 'UNDEFINED'):
            with self.subTest(level=level):
                self.scan['imageScanFindings']['findingSeverityCounts'] = {level: 1}
                with self.assertRaises(d.DeployError):
                    self.publish()


class EntrypointTests(unittest.TestCase):
    def test_old_helpers_fail_before_any_network_or_credential_file(self):
        for name in ('master_deploy.sh', 'awsconfiguration.sh', 'psvar-processor.sh', 'buildenv.sh', 'buildproperties.sh', 'utilities/tooltoencdec.sh', 'uploadjson-ps.sh', 'uploadjsonso-ps.sh', 'setup_ms/template/setupscr_v7.3.sh'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                result = subprocess.run(['bash', str(ROOT / name), 'DEV'], cwd=temp,
                    env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(Path(temp).iterdir()), [])

    def test_secret_context_names(self):
        for name in ('awsenvconf', 'buildvar_env', '.env', '.env.production', 'sub/.aws/config', '.npmrc', 'fetched_parameters.json'):
            self.assertTrue(b.forbidden(name), name)
        for name in ('Dockerfile', 'src/app.ts', '.env.example', 'deploy/certs/ca.pem'):
            self.assertFalse(b.forbidden(name), name)

    def test_legacy_master_flags_cannot_bypass_new_contract(self):
        result = subprocess.run(['bash', str(ROOT / 'master_deploy.sh'), '-d', 'ECS', '-j', '/config/test'],
                                capture_output=True, text=True, env={'PATH': '/usr/bin:/bin'})
        self.assertEqual(result.returncode, 2)

    def test_cli_missing_identity_fails_without_traceback_or_secrets(self):
        result = subprocess.run(['python3', '-I', str(ROOT / 'tcdeploy.py'), 'check-auth',
                                 '--manifest', str(ROOT / 'examples/deploy.dev.json')],
                                env={'PATH': '/usr/bin:/bin', 'CI_AUTH0_CLIENTSECRET': 'dummy-super-secret'},
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('Traceback', result.stderr)
        self.assertNotIn('dummy-super-secret', result.stdout + result.stderr)


class BuildTests(unittest.TestCase):
    def build(self, tracked, untracked=None):
        captured = {}
        original_run = b.run
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, content in {'Dockerfile': 'FROM scratch\n', **tracked}.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            subprocess.run(['git', 'init', '-q', directory], check=True, capture_output=True)
            subprocess.run(['git', '-C', directory, 'add', '.'], check=True, capture_output=True)
            subprocess.run(['git', '-C', directory, '-c', 'user.email=test@example.invalid', '-c',
                            'user.name=Test', 'commit', '-qm', 'fixture'], check=True, capture_output=True)
            for name, content in (untracked or {}).items():
                (root / name).write_text(content)

            def run(command, env):
                if command[0] != 'docker':
                    return original_run(command, env)
                context = Path(command[-1])
                captured['files'] = sorted(str(p.relative_to(context)) for p in context.rglob('*') if p.is_file())
                captured['env'] = env
                captured['command'] = command
                return subprocess.CompletedProcess(command, 0, b'', b'')
            try:
                os.chdir(root)
                with patch.dict(os.environ, {'CI_AUTH0_CLIENTSECRET': 'dummy', 'AWS_SECRET_ACCESS_KEY': 'dummy',
                                'CIRCLE_OIDC_TOKEN_V3': 'dummy'}, clear=True), patch.object(b, 'run', side_effect=run):
                    b.main(['--image', 'fixture:candidate'])
            finally:
                os.chdir(original_cwd)
        return captured

    def test_untracked_secret_files_never_enter_context(self):
        result = self.build({'src/app.txt': 'safe'}, {'.env': 'PASSWORD=dummy', 'buildvar_env': 'dummy'})
        self.assertEqual(result['files'], ['Dockerfile', 'src/app.txt'])
        for key in ('CI_AUTH0_CLIENTSECRET', 'AWS_SECRET_ACCESS_KEY', 'CIRCLE_OIDC_TOKEN_V3'):
            self.assertNotIn(key, result['env'])
        self.assertIn('--provenance=false', result['command'])

    def test_tracked_secret_file_rejected(self):
        with self.assertRaises(ValueError):
            self.build({'buildvar_env': 'dummy'})

    def test_public_ca_bundle_allowed(self):
        self.build({'deploy/certs/ca.pem': '-----BEGIN CERTIFICATE-----\nYWJj\n-----END CERTIFICATE-----\n'})

    def test_private_key_pem_rejected(self):
        with self.assertRaises(ValueError):
            self.build({'private.pem': '-----BEGIN PRIVATE KEY-----\nYWJj\n-----END PRIVATE KEY-----\n'})

    def test_no_build_arguments_or_secret_options(self):
        with self.assertRaises(SystemExit):
            b.main(['--image', 'fixture:candidate', '--build-arg', 'RESET_DB=true'])


if __name__ == '__main__':
    unittest.main()
