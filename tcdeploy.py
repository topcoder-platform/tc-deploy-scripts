#!/usr/bin/env python3
"""Deploy prebuilt images to an existing Fargate service without reading secrets.

Python standard library + AWS CLI v2 + Docker. No shell evaluation, broker,
ambient AWS identity, parameter discovery, infrastructure creation or build.
"""
import argparse
import base64
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


class DeployError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise DeployError(message)


def compact(value):
    return json.dumps(value, separators=(',', ':'))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate JSON key')
        result[key] = value
    return result


def read_manifest(path):
    m = json.loads(Path(path).read_text(), object_pairs_hook=unique_object)
    required = {'schemaVersion', 'environment', 'accountId', 'region', 'deployRoleArn',
                'taskRoleArn', 'executionRoleArn', 'cluster', 'service', 'taskFamily',
                'circleciOrgId', 'circleciProjectId', 'repository', 'branch', 'images'}
    require(isinstance(m, dict) and set(m) == required, 'Manifest fields must match the v2 schema')
    require(m['schemaVersion'] == 2 and m['environment'] in ('dev', 'prod'), 'Unsupported manifest version/environment')
    for key in required - {'schemaVersion', 'images'}:
        require(isinstance(m[key], str) and m[key], 'Manifest requires nonempty string fields')
    require(re.fullmatch(r'[0-9]{12}', m['accountId']), 'Invalid account ID')
    require(re.fullmatch(r'(us|eu|ap|ca|sa|me|af|il|mx)-[a-z]+-[0-9]', m['region']), 'Unsupported AWS commercial region')
    for key in ('deployRoleArn', 'taskRoleArn', 'executionRoleArn'):
        require(re.fullmatch(r'arn:aws:iam::' + m['accountId'] + r':role/[A-Za-z0-9_+=,.@/-]+', m[key]), 'Role must belong to the configured account')
    require(len({m[k] for k in ('deployRoleArn', 'taskRoleArn', 'executionRoleArn')}) == 3, 'Deployment, task and execution roles must be distinct')
    for key in ('cluster', 'service', 'taskFamily'):
        require(re.fullmatch(r'[A-Za-z0-9_-]{1,255}', m[key]), 'Invalid ECS resource name')
    for key in ('circleciOrgId', 'circleciProjectId'):
        require(re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', m[key]), 'CircleCI IDs must be UUIDs')
    require(re.fullmatch(r'github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', m['repository']), 'Expected exact github.com/owner/repository')
    allowed_branches = ('master',) if m['environment'] == 'prod' else ('develop', 'dev')
    require(m['branch'] in allowed_branches, 'Deploy only the reviewed dev/develop branch to dev and master to prod')
    require(isinstance(m['images'], dict) and 1 <= len(m['images']) <= 10, 'Configure one to ten container/repository pairs')
    for container, repository in m['images'].items():
        require(re.fullmatch(r'[A-Za-z0-9_-]{1,255}', container), 'Invalid container name')
        require(isinstance(repository, str) and re.fullmatch(r'[a-z0-9]+(?:[._/-][a-z0-9]+)*', repository), 'Invalid ECR repository name')
    require(len(set(m['images'].values())) == len(m['images']), 'Each image needs a separate repository')
    return m


def arn(m, service, resource):
    return f"arn:aws:{service}:{m['region']}:{m['accountId']}:{resource}"


def role_policy(m):
    """Administrator-installed policy, also used as the deploy role boundary."""
    return {'Version': '2012-10-17', 'Statement': [
        {'Effect': 'Deny', 'Action': ['ssm:*', 'secretsmanager:*', 'kms:Decrypt', 'sts:AssumeRole*'], 'Resource': '*'},
        # DescribeTaskDefinition does not support resource-level authorization.
        {'Effect': 'Allow', 'Action': ['sts:GetCallerIdentity', 'ecr:GetAuthorizationToken',
             'ecs:DescribeTaskDefinition'], 'Resource': '*'},
        {'Effect': 'Allow', 'Action': ['ecr:DescribeRepositories', 'ecr:DescribeImages',
             'ecr:BatchGetImage', 'ecr:BatchCheckLayerAvailability', 'ecr:InitiateLayerUpload',
             'ecr:UploadLayerPart', 'ecr:CompleteLayerUpload', 'ecr:PutImage',
             'ecr:DescribeImageScanFindings'],
         'Resource': [arn(m, 'ecr', 'repository/' + r) for r in m['images'].values()]},
        {'Effect': 'Allow', 'Action': ['ecs:DescribeServices'], 'Resource': arn(m, 'ecs', f"service/{m['cluster']}/{m['service']}")},
        {'Effect': 'Allow', 'Action': 'ecs:UpdateService', 'Resource': arn(m, 'ecs', f"service/{m['cluster']}/{m['service']}"),
         'Condition': {'ArnLike': {'ecs:task-definition': arn(m, 'ecs', 'task-definition/' + m['taskFamily'] + ':*')}}},
        {'Effect': 'Allow', 'Action': ['ecs:RegisterTaskDefinition', 'ecs:TagResource', 'ecs:ListTagsForResource'],
         'Resource': arn(m, 'ecs', 'task-definition/' + m['taskFamily'] + ':*')},
        {'Effect': 'Allow', 'Action': ['ecs:ListTasks', 'ecs:DescribeTasks'], 'Resource': '*',
         'Condition': {'ArnEquals': {'ecs:cluster': arn(m, 'ecs', 'cluster/' + m['cluster'])}}},
        {'Effect': 'Allow', 'Action': 'iam:PassRole', 'Resource': [m['taskRoleArn'], m['executionRoleArn']],
         'Condition': {'StringEquals': {'iam:PassedToService': 'ecs-tasks.amazonaws.com'}}}
    ]}


def trust_policy(m):
    issuer = 'oidc.circleci.com/org/' + m['circleciOrgId']
    subject = (f"org:{m['circleciOrgId']}:project:{m['circleciProjectId']}:user:*:"
               f"checkout-source:{m['repository']}:checkout-ref:refs/heads/{m['branch']}:"
               f"config-source:{m['repository']}:config-ref:refs/heads/{m['branch']}")
    return {'Version': '2012-10-17', 'Statement': [{
        'Effect': 'Allow', 'Principal': {'Federated': f"arn:aws:iam::{m['accountId']}:oidc-provider/{issuer}"},
        'Action': 'sts:AssumeRoleWithWebIdentity', 'Condition': {
            'StringEquals': {issuer + ':aud': m['circleciOrgId']},
            'StringLike': {issuer + ':sub': subject}}
    }]}


# Compact STS policy (<2048 bytes). IAM role policy above restricts resources.
# Explicit deny also protects against resource policies and prevents role chaining.
SESSION_POLICY = {'Version': '2012-10-17', 'Statement': [
    {'Effect': 'Deny', 'Action': ['ssm:*', 'secretsmanager:*', 'kms:Decrypt', 'sts:AssumeRole*'], 'Resource': '*'},
    {'Effect': 'Allow', 'Action': ['sts:GetCallerIdentity', 'ecr:GetAuthorizationToken',
        'ecr:DescribeRepositories', 'ecr:DescribeImages', 'ecr:BatchGetImage',
        'ecr:BatchCheckLayerAvailability', 'ecr:InitiateLayerUpload', 'ecr:UploadLayerPart',
        'ecr:CompleteLayerUpload', 'ecr:PutImage', 'ecr:DescribeImageScanFindings',
        'ecs:DescribeServices', 'ecs:DescribeTaskDefinition', 'ecs:RegisterTaskDefinition',
        'ecs:TagResource', 'ecs:ListTagsForResource', 'ecs:UpdateService', 'ecs:ListTasks', 'ecs:DescribeTasks', 'iam:PassRole'], 'Resource': '*'}]}


def clean_environment(region):
    # Never inherit profiles, endpoint overrides, SDK credential providers, proxies,
    # BASH_ENV, Auth0 secrets, OIDC tokens, arbitrary executable search paths, or
    # package-manager credentials in AWS/Docker subprocesses.
    result = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
              'AWS_REGION': region, 'AWS_DEFAULT_REGION': region,
              'AWS_CONFIG_FILE': os.devnull, 'AWS_SHARED_CREDENTIALS_FILE': os.devnull,
              'AWS_EC2_METADATA_DISABLED': 'true', 'AWS_PAGER': '',
              'AWS_RETRY_MODE': 'standard', 'AWS_MAX_ATTEMPTS': '3'}
    # CircleCI remote Docker uses these public connection settings / client certs.
    for key in ('DOCKER_HOST', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        if key in os.environ:
            result[key] = os.environ[key]
    return result


def execute(command, env, input_text=None, timeout=120):
    try:
        result = subprocess.run(command, env=env, input=input_text, text=True,
                                capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise DeployError('External command failed or timed out; no credentials were printed') from None
    # Never echo stdout/stderr or full argv on failures: AWS responses and Docker
    # diagnostics can contain credentials, task configuration, or registry tokens.
    if result.returncode:
        code = re.search(r'An error occurred \(([A-Za-z0-9]+)\)', result.stderr)
        suffix = ': ' + code[1] if code else ''
        raise DeployError('External command failed' + suffix)
    return result.stdout


class AWS:
    def __init__(self, region, env=None):
        self.env = dict(env or clean_environment(region))
        self.region = region

    def call(self, service, operation, **parameters):
        require(service in ('sts', 'ecs', 'ecr'), 'This deployer cannot call secret or infrastructure APIs')
        # JSON on stdin avoids credentials and task configuration in argv or files.
        command = ['aws', service, operation, '--region', self.region,
                   '--output', 'json', '--no-cli-pager', '--cli-input-json', 'file:///dev/stdin']
        output = execute(command, self.env, compact(parameters), timeout=120)
        return json.loads(output) if output.strip() else {}


def authenticate(m, token):
    require(isinstance(token, str) and len(token) > 100, 'CIRCLE_OIDC_TOKEN_V3 is required; no Auth0 or ambient-credential fallback')
    aws = AWS(m['region'])
    response = aws.call('sts', 'assume-role-with-web-identity', RoleArn=m['deployRoleArn'],
        RoleSessionName='tc-deploy-' + str(int(time.time())), WebIdentityToken=token,
        DurationSeconds=3600, Policy=compact(SESSION_POLICY))
    credentials = response.get('Credentials', {})
    for key in ('AccessKeyId', 'SecretAccessKey', 'SessionToken', 'Expiration'):
        require(isinstance(credentials.get(key), str) and credentials[key], 'STS returned incomplete temporary credentials')
    require(re.fullmatch(r'ASIA[A-Z0-9]{16}', credentials['AccessKeyId']), 'Only temporary STS credentials are accepted')
    expiry = datetime.fromisoformat(credentials['Expiration'].replace('Z', '+00:00'))
    require(3300 <= (expiry - datetime.now(timezone.utc)).total_seconds() <= 3660, 'Unexpected STS session expiry')
    aws.env.update(AWS_ACCESS_KEY_ID=credentials['AccessKeyId'], AWS_SECRET_ACCESS_KEY=credentials['SecretAccessKey'],
                   AWS_SESSION_TOKEN=credentials['SessionToken'])
    identity = aws.call('sts', 'get-caller-identity')
    role_name = m['deployRoleArn'].rsplit('/', 1)[1]
    require(identity.get('Account') == m['accountId'] and
            identity.get('Arn', '').startswith(f"arn:aws:sts::{m['accountId']}:assumed-role/{role_name}/"),
            'STS identity does not match the reviewed deployment account/role')
    return aws


SECRET_ENV = re.compile(r'(PASSWORD|SECRET|TOKEN|ACCESS_KEY|PRIVATE_KEY|DATABASE_URL|POSTGRES_URL|IDENTITY_DB_URL)', re.I)
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
TASK_FIELDS = {'family', 'taskRoleArn', 'executionRoleArn', 'networkMode', 'containerDefinitions', 'volumes',
               'placementConstraints', 'requiresCompatibilities', 'cpu', 'memory', 'pidMode', 'ipcMode',
               'proxyConfiguration', 'inferenceAccelerators', 'ephemeralStorage', 'runtimePlatform', 'enableFaultInjection'}
TASK_METADATA = {'taskDefinitionArn', 'revision', 'status', 'requiresAttributes', 'compatibilities',
                 'registeredAt', 'registeredBy', 'deregisteredAt'}


def validate_environment(entries):
    for entry in entries:
        name, value = entry['name'], entry['value']
        require(not (SECRET_ENV.search(name) and value), 'Plaintext secret-like environment values are forbidden')
        require(name != 'RESET_DB' or value == 'false', 'Database reset must be explicitly false')


def non_root(user):
    if not isinstance(user, str):
        return False
    name = user.split(':', 1)[0]
    return bool(name) and name != 'root' and not (name.isdecimal() and int(name) == 0)


def task_request(m, task, tags, images):
    require(set(task) <= TASK_FIELDS | TASK_METADATA, 'Unrecognized task fields; update the deployer before changing this definition')
    require(task.get('family') == m['taskFamily'] and task.get('status') == 'ACTIVE', 'Unexpected/inactive task family')
    require(task.get('taskRoleArn') == m['taskRoleArn'] and task.get('executionRoleArn') == m['executionRoleArn'], 'Task/execution role differs from reviewed manifest')
    require(task.get('networkMode') == 'awsvpc' and 'FARGATE' in task.get('requiresCompatibilities', []), 'Expected a Fargate task')
    platform = task.get('runtimePlatform', {})
    require(platform.get('cpuArchitecture', 'X86_64') == 'X86_64' and platform.get('operatingSystemFamily', 'LINUX') == 'LINUX', 'This release supports Linux/amd64 tasks only')
    require(set(images) == set(m['images']), 'Supply exactly the manifest image set')
    result = {k: deepcopy(v) for k, v in task.items() if k in TASK_FIELDS}
    result['tags'] = deepcopy(tags)
    counts = {name: 0 for name in images}
    for container in result['containerDefinitions']:
        validate_environment(container.get('environment', []))
        require(all(s['name'] != 'RESET_DB' for s in container.get('secrets', [])), 'RESET_DB cannot come from an unreadable runtime secret')
        if container['name'] in images:
            require(not container.get('privileged') and ('user' not in container or non_root(container['user'])), 'Application task must not override the image to root/privileged')
            counts[container['name']] += 1
            require(DIGEST.fullmatch(images[container['name']].rsplit('@', 1)[-1]), 'Deploy only image digests')
            require(container.get('healthCheck'), 'Updated containers require a task health check')
            container['image'] = images[container['name']]
    require(all(n == 1 for n in counts.values()), 'Each configured container must exist exactly once')
    # All roles, secret references, sidecars, health checks, resources and volumes
    # are preserved. Parameter values never enter this process.
    return result


def read_service(aws, m):
    response = aws.call('ecs', 'describe-services', cluster=m['cluster'], services=[m['service']])
    require(not response.get('failures') and len(response.get('services', [])) == 1, 'Expected one existing ECS service')
    service = response['services'][0]
    require(service.get('status') == 'ACTIVE' and service.get('desiredCount', 0) > 0, 'Service must be active with positive desired capacity; bootstrap separately')
    require(service.get('deploymentController', {}).get('type', 'ECS') == 'ECS', 'Only ECS rolling deployments are supported')
    require(service.get('deploymentConfiguration', {}).get('deploymentCircuitBreaker') == {'enable': True, 'rollback': True}, 'Enable ECS deployment circuit breaker with rollback before migration')
    require(service.get('serviceArn') == arn(m, 'ecs', f"service/{m['cluster']}/{m['service']}"), 'Service ARN differs from manifest')
    return service


def stable(service, definition):
    require(service.get('taskDefinition') == definition, 'Service rolled back or was changed by another deployment')
    deployments = service.get('deployments', [])
    require(not any(d.get('rolloutState') == 'FAILED' for d in deployments), 'ECS rollout failed')
    return (len(deployments) == 1 and deployments[0].get('rolloutState') == 'COMPLETED'
            and deployments[0].get('taskDefinition') == definition
            and service.get('runningCount') == service['desiredCount'] > 0 and service.get('pendingCount') == 0)


def verify_running(aws, m, definition, images, desired):
    arns, token = [], None
    while True:
        args = {'cluster': m['cluster'], 'serviceName': m['service'], 'desiredStatus': 'RUNNING'}
        if token:
            args['nextToken'] = token
        page = aws.call('ecs', 'list-tasks', **args)
        arns.extend(page.get('taskArns', []))
        token = page.get('nextToken')
        if not token:
            break
    if len(arns) < desired:
        return False
    tasks = []
    for start in range(0, len(arns), 100):
        result = aws.call('ecs', 'describe-tasks', cluster=m['cluster'], tasks=arns[start:start + 100])
        require(not result.get('failures'), 'Unable to describe running tasks')
        tasks.extend(result.get('tasks', []))
    for task in tasks:
        if task.get('taskDefinitionArn') != definition or task.get('lastStatus') != 'RUNNING' or task.get('healthStatus') != 'HEALTHY':
            return False
        containers = {c['name']: c for c in task['containers']}
        for name, image in images.items():
            if containers.get(name, {}).get('imageDigest') != image.rsplit('@', 1)[1]:
                return False
    return len(tasks) >= desired


class Publisher:
    def __init__(self, aws, m, directory):
        self.aws, self.m = aws, m
        self.env = clean_environment(m['region'])  # Docker must not receive AWS/OIDC credentials.
        self.env['DOCKER_CONFIG'] = directory
        self.registry = f"{m['accountId']}.dkr.ecr.{m['region']}.amazonaws.com"

    def docker(self, *args, input_text=None, timeout=120):
        return execute(['docker', *args], self.env, input_text, timeout)

    def inspect(self, image):
        require(not image.startswith('-') and re.fullmatch(r'[A-Za-z0-9_./:@-]+', image), 'Invalid local image reference')
        records = json.loads(self.docker('image', 'inspect', image))
        require(len(records) == 1, 'Expected one local image')
        info = records[0]
        info['configDigest'] = info.get('Descriptor', {}).get('annotations', {}).get('config.digest', info.get('Id', ''))
        require(DIGEST.fullmatch(info['configDigest']), 'Missing image configuration digest')
        require(info.get('Os') == 'linux' and info.get('Architecture') == 'amd64', 'Only Linux/amd64 images are supported')
        entries = [{'name': x.partition('=')[0], 'value': x.partition('=')[2]} for x in info.get('Config', {}).get('Env', [])]
        validate_environment(entries)
        require(non_root(info.get('Config', {}).get('User')), 'Application images must run as a non-root user')
        return info

    def publish(self, name, local, tag, deadline):
        info = self.inspect(local)
        require(info.get('Config', {}).get('Labels', {}).get('org.opencontainers.image.revision') == tag[:40], 'Image source revision does not match this release')
        repository = self.m['images'][name]
        response = self.aws.call('ecr', 'describe-repositories', repositoryNames=[repository])
        repos = response.get('repositories', [])
        require(len(repos) == 1 and repos[0].get('imageTagMutability') == 'IMMUTABLE', 'ECR repository must exist and use unconditional immutable tags')
        uri = f'{self.registry}/{repository}'
        require(repos[0].get('repositoryUri') == uri, 'Unexpected ECR registry')
        auth = self.aws.call('ecr', 'get-authorization-token')['authorizationData']
        require(len(auth) == 1 and auth[0]['proxyEndpoint'] == 'https://' + self.registry, 'Unexpected ECR login endpoint')
        username, password = base64.b64decode(auth[0]['authorizationToken'], validate=True).decode().split(':', 1)
        require(username == 'AWS' and password, 'Invalid ECR authorization')
        self.docker('login', '--username', username, '--password-stdin', self.registry, input_text=password)
        # Unique, immutable release tags make a concurrent overwrite fail closed.
        image = uri + ':' + tag
        self.docker('tag', local, image)
        self.docker('push', image, timeout=600)
        details = self.aws.call('ecr', 'describe-images', repositoryName=repository,
                                imageIds=[{'imageTag': tag}]).get('imageDetails', [])
        require(len(details) == 1 and DIGEST.fullmatch(details[0].get('imageDigest', '')), 'ECR did not return a single image digest')
        digest = details[0]['imageDigest']
        remote = self.aws.call('ecr', 'batch-get-image', repositoryName=repository,
            imageIds=[{'imageDigest': digest}], acceptedMediaTypes=[
                'application/vnd.docker.distribution.manifest.v2+json', 'application/vnd.oci.image.manifest.v1+json'])
        require(not remote.get('failures') and len(remote.get('images', [])) == 1, 'Cannot verify pushed image')
        manifest = json.loads(remote['images'][0]['imageManifest'])
        require(manifest.get('config', {}).get('digest') == info['configDigest'], 'Pushed artifact differs from local image (multi-platform indexes are unsupported)')
        # Repositories must scan on push (basic or enhanced). No start_image_scan
        # fallback that can bypass a failed/missing organizational scan policy.
        while time.monotonic() < deadline:
            try:
                scan = self.aws.call('ecr', 'describe-image-scan-findings', repositoryName=repository, imageId={'imageDigest': digest})
            except DeployError as exc:
                if str(exc).endswith(': ScanNotFoundException'):
                    time.sleep(10)
                    continue
                raise
            status = scan.get('imageScanStatus', {}).get('status')
            findings = scan.get('imageScanFindings', {})
            if status in ('COMPLETE', 'ACTIVE') and findings.get('imageScanCompletedAt'):
                timestamp = findings['imageScanCompletedAt']
                if isinstance(timestamp, (int, float)):
                    completed = datetime.fromtimestamp(timestamp, timezone.utc)
                else:
                    completed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                require(0 <= (datetime.now(timezone.utc) - completed).total_seconds() < 86400, 'Image scan must have completed within the last 24 hours')
                counts = findings.get('findingSeverityCounts')
                require(isinstance(counts, dict), 'Missing image scan severity counts')
                require(not any(counts.get(level, 0) for level in ('CRITICAL', 'HIGH', 'MEDIUM', 'UNDEFINED')), 'Image scan exceeds the release threshold')
                return uri + '@' + digest
            require(status in ('IN_PROGRESS', 'PENDING', 'ACTIVE'), 'Image scan failed or is unsupported')
            time.sleep(10)
        raise DeployError('Image scan timed out; service was not updated')


def deploy(aws, m, locals_by_name, release, publisher):
    require(set(locals_by_name) == set(m['images']), 'Supply exactly one prebuilt image per configured container')
    require(re.fullmatch(r'[a-f0-9]{40}-[0-9]{1,12}', release), 'Release must be CIRCLE_SHA1-CIRCLE_BUILD_NUM')
    previous = read_service(aws, m)
    definition = previous['taskDefinition']
    require(stable(previous, definition), 'Existing service must be stable before deploying')
    response = aws.call('ecs', 'describe-task-definition', taskDefinition=definition, include=['TAGS'])
    task, tags = response['taskDefinition'], response.get('tags', [])
    # Validate configuration before publishing anything. Placeholder digests are
    # only used for validation and never sent to AWS.
    task_request(m, task, tags, {name: 'preflight@sha256:' + '0' * 64 for name in m['images']})
    images = {}
    scan_deadline = time.monotonic() + 900
    for name, local in locals_by_name.items():
        images[name] = publisher.publish(name, local, release, scan_deadline)
    current = read_service(aws, m)
    require(stable(current, definition), 'Service changed during image publication; retry after inspection')
    request = task_request(m, task, tags, images)
    registered = aws.call('ecs', 'register-task-definition', **request)['taskDefinition']
    target = registered['taskDefinitionArn']
    require(re.fullmatch(re.escape(arn(m, 'ecs', 'task-definition/' + m['taskFamily'])) + r':[0-9]+', target), 'Unexpected registered task ARN')
    # Read back and compare the actual registered fields before promotion.
    saved = aws.call('ecs', 'describe-task-definition', taskDefinition=target, include=['TAGS'])
    saved_request = {k: v for k, v in saved['taskDefinition'].items() if k in TASK_FIELDS}
    saved_request['tags'] = sorted(saved.get('tags', []), key=lambda t: t['key'])
    request['tags'] = sorted(request['tags'], key=lambda t: t['key'])
    require(saved_request == request,
            'Registered task configuration differs from requested configuration')
    current = read_service(aws, m)
    require(stable(current, definition), 'Concurrent deployment detected before service update')
    updated = aws.call('ecs', 'update-service', cluster=m['cluster'], service=m['service'], taskDefinition=target)
    require(updated.get('service', {}).get('taskDefinition') == target, 'ECS did not accept requested revision')
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        service = read_service(aws, m)
        if stable(service, target) and verify_running(aws, m, target, images, service['desiredCount']):
            return {'service': m['service'], 'environment': m['environment'], 'taskDefinition': target,
                    'previousTaskDefinition': definition, 'images': images}
        time.sleep(15)
    # Do not blindly revert over another release. ECS circuit breaker performs
    # rollback; timeout remains a failed release requiring operator inspection.
    raise DeployError('Rollout timed out; inspect ECS circuit-breaker rollback before retrying')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('deploy', 'policies', 'check-auth'):
        p = sub.add_parser(name)
        p.add_argument('--manifest', required=True)
        if name == 'deploy':
            p.add_argument('--image', action='append', required=True, metavar='CONTAINER=LOCAL_IMAGE')
    args = parser.parse_args(argv)
    m = read_manifest(args.manifest)
    if args.command == 'policies':
        print(json.dumps({'trust': trust_policy(m), 'permissions': role_policy(m)}, indent=2))
        return
    require(os.environ.get('CIRCLE_BRANCH') == m['branch'] and not os.environ.get('CIRCLE_TAG'), 'Only the configured branch may deploy (tag pipelines are forbidden)')
    require(os.environ.get('CIRCLE_PROJECT_USERNAME', '') + '/' + os.environ.get('CIRCLE_PROJECT_REPONAME', '') == m['repository'].removeprefix('github.com/'), 'CircleCI repository differs from manifest')
    token = os.environ.get('CIRCLE_OIDC_TOKEN_V3')
    aws = authenticate(m, token)
    if args.command == 'check-auth':
        print('Verified deployment account and role. No credentials exported or written.')
        return
    images = {}
    for item in args.image:
        name, separator, image = item.partition('=')
        require(separator and name not in images and image, 'Images must be unique CONTAINER=LOCAL_IMAGE pairs')
        images[name] = image
    release = os.environ.get('CIRCLE_SHA1', '') + '-' + os.environ.get('CIRCLE_BUILD_NUM', '')
    with tempfile.TemporaryDirectory(prefix='tc-deploy-docker-') as directory:
        result = deploy(aws, m, images, release, Publisher(aws, m, directory))
    print(json.dumps(result, indent=2))  # Only non-secret rollout evidence.


if __name__ == '__main__':
    try:
        main()
    except (DeployError, ValueError, KeyError, TypeError, OSError):
        # Do not emit tracebacks/SDK payloads, which can contain secrets.
        exc = sys.exc_info()[1]
        print('Deployment stopped: ' + (str(exc) if isinstance(exc, DeployError) else 'invalid input or response'), file=sys.stderr)
        sys.exit(1)
