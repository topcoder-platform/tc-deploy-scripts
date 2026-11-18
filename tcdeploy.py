#!/usr/bin/env python3
"""Deploy prebuilt images to an existing Fargate service without reading secrets.

Python standard library + AWS CLI v2 + Docker. No shell evaluation, broker,
ambient AWS identity, parameter discovery, infrastructure creation or build.
"""
import argparse
import base64
from collections import Counter
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from zipfile import ZipFile, BadZipFile


class DeployError(Exception):
    pass


class InspectorThresholdExceeded(DeployError):
    """Explicit blocking evidence must never fall back to another scan."""


PRODUCTION_BLOCKED = ('CRITICAL', 'HIGH', 'MEDIUM', 'UNDEFINED')


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
    for key in required - {'schemaVersion', 'images', 'taskRoleArn'}:
        require(isinstance(m[key], str) and m[key], 'Manifest requires nonempty string fields')
    require(re.fullmatch(r'[0-9]{12}', m['accountId']), 'Invalid account ID')
    require(re.fullmatch(r'(us|eu|ap|ca|sa|me|af|il|mx)-[a-z]+-[0-9]', m['region']), 'Unsupported AWS commercial region')
    for key in ('deployRoleArn', 'taskRoleArn', 'executionRoleArn'):
        if key == 'taskRoleArn' and m[key] is None:
            continue
        require(isinstance(m[key], str), 'Role must be an ARN or an absent task role')
        require(re.fullmatch(r'arn:aws:iam::' + m['accountId'] + r':role/[A-Za-z0-9_+=,.@/-]+', m[key]), 'Role must belong to the configured account')
    require(len({m[k] for k in ('deployRoleArn', 'taskRoleArn', 'executionRoleArn')}) == 3, 'Deployment, task and execution roles must be distinct')
    for key in ('cluster', 'service', 'taskFamily'):
        require(re.fullmatch(r'[A-Za-z0-9_-]{1,255}', m[key]), 'Invalid ECS resource name')
    for key in ('circleciOrgId', 'circleciProjectId'):
        require(re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}', m[key]), 'CircleCI IDs must be UUIDs')
    require(re.fullmatch(r'github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', m['repository']), 'Expected exact github.com/owner/repository')
    allowed_branches = ('master', 'prod') if m['environment'] == 'prod' else ('develop', 'dev')
    require(m['branch'] in allowed_branches, 'Deploy only the reviewed dev/develop branch to dev and the reviewed master/prod branch to prod')
    require(isinstance(m['images'], dict) and 1 <= len(m['images']) <= 10, 'Configure one to ten container/repository pairs')
    for container, repository in m['images'].items():
        require(re.fullmatch(r'[A-Za-z0-9_-]{1,255}', container), 'Invalid container name')
        require(isinstance(repository, str) and re.fullmatch(r'[a-z0-9]+(?:[._/-][a-z0-9]+)*', repository), 'Invalid ECR repository name')
    require(len(set(m['images'].values())) == len(m['images']), 'Each image needs a separate repository')
    return m


def arn(m, service, resource):
    return f"arn:aws:{service}:{m['region']}:{m['accountId']}:{resource}"


# Restrict the temporary STS session; this does not create or modify IAM policies.
# Pre-provisioned IAM roles and boundaries in v6-services-iac scope resources.
# Explicit deny also protects against resource policies and prevents role chaining.
SESSION_POLICY = {'Version': '2012-10-17', 'Statement': [
    {'Effect': 'Deny', 'Action': ['ssm:*', 'secretsmanager:*', 'kms:Decrypt', 'sts:AssumeRole*'], 'Resource': '*'},
    {'Effect': 'Allow', 'Action': ['sts:GetCallerIdentity', 'ecr:GetAuthorizationToken',
        'ecr:DescribeRepositories', 'ecr:DescribeImages', 'ecr:BatchGetImage',
        'ecr:BatchCheckLayerAvailability', 'ecr:InitiateLayerUpload', 'ecr:UploadLayerPart',
        'ecr:CompleteLayerUpload', 'ecr:PutImage', 'ecr:DescribeImageScanFindings',
        'ecs:DescribeServices', 'ecs:DescribeTaskDefinition', 'ecs:RegisterTaskDefinition',
        'ecs:TagResource', 'ecs:ListTagsForResource', 'ecs:UpdateService', 'ecs:ListTasks', 'ecs:DescribeTasks', 'iam:PassRole',
        'inspector2:ListFindings', 'inspector2:ListCoverage'], 'Resource': '*'}]}

# Reviewed service adapters may retain migration/health/CloudFormation ownership
# gates. These capabilities are not exposed as deployment CLI flags. Their IAM
# role and boundary must separately scope every extra action to that service.
ADAPTER_ACTIONS = frozenset({
    'ecs:RunTask', 'ecs:DeregisterTaskDefinition',
    'elasticloadbalancing:DescribeTargetHealth',
    'inspector2:ListCoverage', 'inspector2:ListFindings',
    'cloudformation:DescribeStacks', 'cloudformation:UpdateStack',
    'cloudformation:DescribeStackEvents', 'cloudformation:DescribeStackResources',
})


def session_policy(additional_actions=(), *, production=False):
    require(set(additional_actions) <= ADAPTER_ACTIONS, 'Unsupported custom deployment capability')
    result = deepcopy(SESSION_POLICY)
    if production:
        result['Statement'][1]['Action'].append('inspector-scan:ScanSbom')
    result['Statement'][1]['Action'] += sorted(set(additional_actions) - set(result['Statement'][1]['Action']))
    require(len(compact(result)) <= 2048, 'Session policy exceeds the STS limit')
    return result


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
        with ExitStack() as stack:
            stdin = None
            if input_text is not None:
                # AWS CLI can open file:///dev/stdin more than once. A pipe is
                # exhausted after the first read; an anonymous Linux memory file
                # is independently reopenable without putting secrets in argv or
                # a named filesystem file. Close it on success and every failure.
                stdin = stack.enter_context(os.fdopen(
                    os.memfd_create('tcdeploy-input', os.MFD_CLOEXEC), 'w+', encoding='utf-8'))
                stdin.write(input_text)
                stdin.flush()
                stdin.seek(0)
            result = subprocess.run(command, env=env, stdin=stdin, text=True,
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

    def call(self, api_service, operation, **parameters):
        adapter_reads = {
            'cloudformation': {'describe-stacks', 'update-stack', 'describe-stack-events', 'describe-stack-resources'},
            'elbv2': {'describe-target-health'},
            'inspector2': {'list-coverage', 'list-findings'},
            'inspector-scan': {'scan-sbom'},
        }
        require(api_service in ('sts', 'ecs', 'ecr') or operation in adapter_reads.get(api_service, set()),
                'This deployer cannot call secret or unreviewed infrastructure APIs')
        # JSON on stdin avoids credentials and task configuration in argv or files.
        command = ['aws', api_service, operation, '--region', self.region,
                   '--output', 'json', '--no-cli-pager', '--cli-input-json', 'file:///dev/stdin']
        try:
            output = execute(command, self.env, compact(parameters), timeout=120)
        except DeployError as exc:
            # Identify the reviewed API operation, never its request parameters
            # or raw CLI output. Keep the error-code suffix for retry handling.
            raise DeployError(f'AWS {api_service} {operation}: {exc}') from None
        return json.loads(output) if output.strip() else {}


def authenticate(m, token, additional_actions=()):
    require(isinstance(token, str) and len(token) > 100, 'CIRCLE_OIDC_TOKEN_V3 is required; no Auth0 or ambient-credential fallback')
    aws = AWS(m['region'])
    response = aws.call('sts', 'assume-role-with-web-identity', RoleArn=m['deployRoleArn'],
        RoleSessionName='tc-deploy-' + str(int(time.time())), WebIdentityToken=token,
        DurationSeconds=3600, Policy=compact(session_policy(additional_actions, production=m['environment'] == 'prod')))
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
PUBLIC_TOKEN_URLS = {'M2M_TOKEN_ISSUER', 'M2M_TOKEN_AUDIENCE', 'HUMAN_TOKEN_ISSUER'}
DIGEST = re.compile(r'sha256:[0-9a-f]{64}')
TASK_FIELDS = {'family', 'taskRoleArn', 'executionRoleArn', 'networkMode', 'containerDefinitions', 'volumes',
               'placementConstraints', 'requiresCompatibilities', 'cpu', 'memory', 'pidMode', 'ipcMode',
               'proxyConfiguration', 'inferenceAccelerators', 'ephemeralStorage', 'runtimePlatform', 'enableFaultInjection'}
TASK_METADATA = {'taskDefinitionArn', 'revision', 'status', 'requiresAttributes', 'compatibilities',
                 'registeredAt', 'registeredBy', 'deregisteredAt'}


def public_token_setting(name, value):
    """Recognize specific public auth settings, never arbitrary TOKEN names."""
    if name == 'TOKEN_CACHE_TIME':
        return bool(re.fullmatch(r'[0-9]{1,10}', value)) and int(value) <= 2147483647
    if name not in PUBLIC_TOKEN_URLS or len(value) > 2048 or any(c.isspace() for c in value):
        return False
    try:
        url = urlsplit(value)
        port = url.port
        return (url.scheme == 'https' and bool(url.hostname) and url.username is None
                and url.password is None and not url.query and not url.fragment
                and (port is None or 1 <= port <= 65535))
    except ValueError:
        return False


def validate_environment(entries):
    for entry in entries:
        name, value = entry['name'], entry['value']
        require(isinstance(name, str) and isinstance(value, str), 'Environment entries must contain strings')
        require(not (SECRET_ENV.search(name) and value) or public_token_setting(name, value),
                'Plaintext secret-like environment values are forbidden')
        require(name != 'RESET_DB' or value == 'false', 'Database reset must be explicitly false')


def non_root(user):
    if not isinstance(user, str):
        return False
    name = user.split(':', 1)[0]
    return bool(name) and name != 'root' and not (name.isdecimal() and int(name) == 0)


def validate_health_checks(m, checks):
    require(isinstance(checks, dict) and checks and set(checks) <= set(m['images']),
            'Bootstrap health checks must name configured image containers only')
    bounds = {'interval': (5, 300), 'timeout': (2, 60), 'retries': (1, 10), 'startPeriod': (0, 300)}
    for check in checks.values():
        require(isinstance(check, dict) and 'command' in check and set(check) <= {'command', *bounds},
                'Unexpected bootstrap health-check fields')
        command = check['command']
        require(isinstance(command, list) and 2 <= len(command) <= 50 and command[0] == 'CMD'
                and all(isinstance(arg, str) and arg and '\x00' not in arg for arg in command),
                'Bootstrap health checks require an explicit CMD argument list')
        for key, (low, high) in bounds.items():
            require(key not in check or type(check[key]) is int and low <= check[key] <= high,
                    'Bootstrap health-check timing is outside ECS bounds')
    return checks


def task_request(m, task, tags, images, health_checks=None):
    require(set(task) <= TASK_FIELDS | TASK_METADATA, 'Unrecognized task fields; update the deployer before changing this definition')
    require(task.get('family') == m['taskFamily'] and task.get('status') == 'ACTIVE', 'Unexpected/inactive task family')
    require(task.get('taskRoleArn') == m['taskRoleArn'] and task.get('executionRoleArn') == m['executionRoleArn'], 'Task/execution role differs from reviewed manifest')
    require(task.get('networkMode') == 'awsvpc' and 'FARGATE' in task.get('requiresCompatibilities', []), 'Expected a Fargate task')
    platform = task.get('runtimePlatform', {})
    require(platform.get('cpuArchitecture', 'X86_64') == 'X86_64' and platform.get('operatingSystemFamily', 'LINUX') == 'LINUX', 'This release supports Linux/amd64 tasks only')
    require(set(images) == set(m['images']), 'Supply exactly the manifest image set')
    if health_checks is not None:
        validate_health_checks(m, health_checks)
    result = {k: deepcopy(v) for k, v in task.items() if k in TASK_FIELDS}
    require(isinstance(tags, list), 'Task tags must be a list')
    # ECS rejects an explicitly empty tag list on registration. Omission keeps
    # an untagged definition untagged; preserve every tag when any are present.
    if tags:
        result['tags'] = deepcopy(tags)
    counts = {name: 0 for name in images}
    for container in result['containerDefinitions']:
        validate_environment(container.get('environment', []))
        require(all(s['name'] != 'RESET_DB' for s in container.get('secrets', [])), 'RESET_DB cannot come from an unreadable runtime secret')
        if container['name'] in images:
            require(not container.get('privileged') and ('user' not in container or non_root(container['user'])), 'Application task must not override the image to root/privileged')
            counts[container['name']] += 1
            require(DIGEST.fullmatch(images[container['name']].rsplit('@', 1)[-1]), 'Deploy only image digests')
            if health_checks is not None and container['name'] in health_checks:
                proposed = health_checks[container['name']]
                require(not container.get('healthCheck') or container['healthCheck'] == proposed,
                        'Bootstrap cannot replace an existing task health check')
                container['healthCheck'] = deepcopy(proposed)
            require(container.get('healthCheck'), 'Updated containers require a task health check')
            container['image'] = images[container['name']]
    require(all(n == 1 for n in counts.values()), 'Each configured container must exist exactly once')
    # Existing configuration is preserved. Explicitly reviewed checks may be
    # added where absent, with the new image, never by restarting the old image.
    return result


def read_service(aws, m):
    response = aws.call('ecs', 'describe-services', cluster=m['cluster'], services=[m['service']])
    require(not response.get('failures') and len(response.get('services', [])) == 1, 'Expected one existing ECS service')
    service = response['services'][0]
    require(service.get('status') == 'ACTIVE' and service.get('desiredCount', 0) > 0, 'Service must be active with positive desired capacity; bootstrap separately')
    require(service.get('deploymentController', {}).get('type', 'ECS') == 'ECS', 'Only ECS rolling deployments are supported')
    breaker = service.get('deploymentConfiguration', {}).get('deploymentCircuitBreaker')
    # ECS also returns optional reset/threshold settings. Require the two safety
    # flags without rejecting or changing those service-owned settings.
    require(isinstance(breaker, dict) and breaker.get('enable') is True and breaker.get('rollback') is True,
            'Enable ECS deployment circuit breaker with rollback before migration')
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


def scan_counts(scan, m, repository, digest):
    """Accept an omitted summary only when ECR explicitly returns no findings."""
    findings = scan['imageScanFindings']
    if 'findingSeverityCounts' not in findings:
        # ECR can omit the optional counts map for a clean image. An absent
        # summary alone is not evidence of a clean scan: require empty result
        # lists, no remaining page, and the exact requested image identity.
        image = scan.get('imageId')
        require(scan.get('registryId') == m['accountId']
                and scan.get('repositoryName') == repository
                and isinstance(image, dict) and image.get('imageDigest') == digest,
                'Empty scan response does not identify the requested image')
        lists = [findings[key] for key in ('findings', 'enhancedFindings') if key in findings]
        require(lists and all(isinstance(items, list) and not items for items in lists)
                and scan.get('nextToken') in (None, ''),
                'Missing image scan severity counts without complete empty findings')
        return {}
    counts = findings['findingSeverityCounts']
    severities = {'INFORMATIONAL', 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL', 'UNDEFINED', 'UNTRIAGED'}
    require(isinstance(counts, dict) and set(counts) <= severities
            and all(type(count) is int and count >= 0 for count in counts.values()),
            'Invalid image scan severity counts')
    if 'UNTRIAGED' in counts:
        counts = dict(counts)
        counts['UNDEFINED'] = counts.get('UNDEFINED', 0) + counts.pop('UNTRIAGED')
    return counts


# AWS publishes versioned SBOM Generator archives. Verify the entire archive
# before reading its binary. The generator never receives AWS/Docker credentials.
SBOMGEN_VERSION = '1.17.7'
SBOMGEN_URL = f'https://amazon-inspector-sbomgen.s3.amazonaws.com/{SBOMGEN_VERSION}/linux/amd64/inspector-sbomgen.zip'
SBOMGEN_SHA256 = '3a50a5f6f0d825aa1aef5e568a2273a0e01285c5bbfda16e3155023a8ca9d816'


# Temporary production risk acceptance for Node's bundled OpenSSL 3.5.9.
OPENSSL_EXCEPTION_END = datetime(2026, 12, 2, tzinfo=timezone.utc)
OPENSSL_REPOSITORIES = {
    'bus-api-v6': 'bus-api-v6',
    'terms-receiver-v6': 'terms-receiver-v6',
    'project-billing-account-update-processor': 'project-billing-account-update-processor',
    'gamification-api': 'tc-gamification',
}
OPENSSL_FINDINGS = {
    'CVE-2026-95691': {'HIGH'}, 'CVE-2026-95692': {'HIGH'}, 'CVE-2026-88823': {'HIGH'},
    'CVE-2026-107496': {'HIGH'}, 'CVE-2026-88822': {'MEDIUM'},
    'CVE-2026-107493': {'UNDEFINED', 'HIGH'}, 'CVE-2026-124709': {'UNDEFINED', 'HIGH'},
    'CVE-2026-35190': {'UNDEFINED', 'MEDIUM'},
}
OPENSSL_HEADERS = {
    f'/usr/local/include/node/openssl/archs/linux-x86_64/{arch}/include/openssl/opensslv.h'
    for arch in ('asm', 'asm_avx2', 'no-asm')
}


def openssl_exception_applies(m, repository):
    project = m.get('repository', '').removeprefix('github.com/topcoder-platform/')
    return (m.get('repository') == 'github.com/topcoder-platform/' + project
            and OPENSSL_REPOSITORIES.get(project) == repository
            and repository and repository in m.get('images', {}).values()
            and m.get('accountId') == '409275337247' and m.get('region') == 'us-east-1'
            and m.get('environment') == 'prod' and m.get('branch') == 'master'
            and datetime.now(timezone.utc) < OPENSSL_EXCEPTION_END)


def matches_openssl_exception(cve, severity, packages, *, ecr):
    if not isinstance(cve, str) or cve not in OPENSSL_FINDINGS or severity not in OPENSSL_FINDINGS[cve]:
        return False
    if not isinstance(packages, list) or not packages:
        return False
    for pkg in packages:
        if not isinstance(pkg, dict):
            return False
        if ecr:
            if (pkg.get('packageManager'), pkg.get('name'), pkg.get('version'),
                pkg.get('fixedInVersion')) != ('GENERIC', 'openssl/openssl', '3.5.9', '3.5.10'):
                return False
            path = pkg.get('filePath')
        else:
            if (pkg.get('installed_version'), pkg.get('fixed_version')) != (
                    'pkg:generic/openssl/openssl@3.5.9', '3.5.10'):
                return False
            path = pkg.get('path')
        if not isinstance(path, str) or path not in OPENSSL_HEADERS:
            return False
    return True


def record_openssl_exception(image, accepted):
    print(f'Temporary OpenSSL 3.5.9 exception: image={image} expires={OPENSSL_EXCEPTION_END.isoformat()} '
          + 'findings=' + compact(sorted(accepted)), flush=True)


def inspector_counts(report, *, manifest=None, repository=None, digest=None):
    require(isinstance(report, dict), 'Missing Inspector report')
    counts = report.get('vulnerability_count')
    levels = {'critical', 'high', 'medium', 'low', 'other'}
    valid_summary = (isinstance(counts, dict) and set(counts) == levels and
                     all(type(n) is int and n >= 0 for n in counts.values()))
    findings = report.get('vulnerabilities', [])
    observed = Counter()
    if isinstance(findings, list):
        for finding in findings:
            severity = finding.get('severity') if isinstance(finding, dict) else None
            if severity in ('info', 'informational'):
                observed['INFORMATIONAL'] += 1
            elif severity in ('critical', 'high', 'medium', 'low'):
                observed[severity.upper()] += 1
            else:
                observed['UNDEFINED'] += 1

    # Inspector aggregates informational and unclassified findings as "other".
    # Every allowed informational finding must have an explicit detail record.
    normalized = observed.copy()
    if isinstance(counts, dict):
        for level in ('critical', 'high', 'medium', 'low'):
            n = counts.get(level)
            if type(n) is int:
                normalized[level.upper()] = max(observed[level.upper()], n)
        other = counts.get('other')
        if type(other) is int:
            normalized['UNDEFINED'] = max(observed['UNDEFINED'], other - observed['INFORMATIONAL'])
    expected = {k: observed[k.upper()] for k in levels - {'other'}}
    expected['other'] = observed['INFORMATIONAL'] + observed['UNDEFINED']
    consistent = valid_summary and isinstance(findings, list) and counts == expected
    accepted = {}
    if (consistent and manifest and isinstance(digest, str) and DIGEST.fullmatch(digest)
            and openssl_exception_applies(manifest, repository)):
        for finding in findings:
            if not isinstance(finding, dict) or finding.get('severity') not in ('high', 'medium', 'none'):
                continue
            level = 'UNDEFINED' if finding['severity'] == 'none' else finding['severity'].upper()
            cve = finding.get('id')
            if matches_openssl_exception(cve, level, finding.get('affects'), ecr=False):
                if cve in accepted:
                    raise InspectorThresholdExceeded('Duplicate finding in OpenSSL exception evidence')
                accepted[cve] = level
        normalized.subtract(accepted.values())
    if any(normalized[k] for k in PRODUCTION_BLOCKED):
        print('Inspector synchronous scan counts: ' + compact(dict(normalized)), flush=True)
        raise InspectorThresholdExceeded('Image scan exceeds the release threshold')
    require(valid_summary, 'Invalid Inspector counts')
    require(consistent, 'Inspector counts disagree with findings')
    messages = report.get('messages', [])
    known = {'Component scanned: no known vulnerabilities.', 'Component skipped: duplicate.',
             'Component skipped: no supported rules found.', 'Component skipped: no version in purl provided.',
             'Component skipped: marked as private.'}
    require(isinstance(messages, list) and all(isinstance(m, dict) and
            m.get('info_message') in known and set(m) <= {'info_message', 'purl', 'name', 'version'}
            and all(isinstance(value, str) for value in m.values())
            for m in messages), 'Incomplete Inspector scan')
    require(observed['LOW'] or any(m['info_message'].startswith('Component scanned:') for m in messages),
            'Inspector assessed no components')
    if accepted:
        record_openssl_exception(repository + '@' + digest, accepted)
    return dict(normalized)



class Publisher:
    def __init__(self, aws, m, directory, *, scan_policy='strict'):
        require(scan_policy in ('strict', 'payload-dev-high-critical'), 'Unsupported image scan policy')
        if scan_policy == 'payload-dev-high-critical':
            require(m.get('environment') == 'dev' and m.get('branch') == 'develop'
                    and m.get('repository') == 'github.com/topcoder-platform/payload-cms'
                    and m.get('service') == m.get('taskFamily') == 'payload-cms'
                    and m.get('images') == {'payload-cms': 'payload-cms'},
                    'The high/critical scan policy is restricted to Payload dev')
        self.scan_policy = scan_policy
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

    @staticmethod
    def check_production_counts(counts):
        require(not any(counts.get(level, 0) for level in PRODUCTION_BLOCKED),
                'Image scan exceeds the release threshold')

    def registry_counts(self, scan, repository, digest):
        if not openssl_exception_applies(self.m, repository):
            return scan_counts(scan, self.m, repository, digest)
        counts = scan_counts(scan, self.m, repository, digest)
        if (not any(counts.get(k, 0) for k in PRODUCTION_BLOCKED)
                and not scan['imageScanFindings'].get('enhancedFindings') and not scan.get('nextToken')):
            return counts

        # Enhanced ECR counts are image-wide. Reconcile every page and every
        # severity before subtracting any of the specifically accepted findings.
        observed, accepted, seen, tokens = Counter(), {}, set(), set()
        resource = arn(self.m, 'ecr', f'repository/{repository}/{digest}')
        page = scan
        while True:
            details = page['imageScanFindings']
            rows = details.get('enhancedFindings')
            # ECR may emit a final empty basic-findings page after enhanced pages.
            if rows is None and tokens and details.get('findings') == [] and not page.get('nextToken'):
                rows = []
            require(page.get('registryId') == self.m['accountId'] and page.get('repositoryName') == repository
                    and page.get('imageId', {}).get('imageDigest') == digest
                    and page.get('imageScanStatus', {}).get('status') == scan['imageScanStatus']['status']
                    and not details.get('findings') and isinstance(rows, list),
                    'OpenSSL exception requires complete enhanced findings for the requested image')
            if 'findingSeverityCounts' in details:
                require(scan_counts(page, self.m, repository, digest) == counts, 'ECR counts changed during pagination')
            for finding in rows:
                fid = finding.get('findingArn')
                resources = finding.get('resources', [])
                require(isinstance(fid, str) and fid and fid not in seen and finding.get('status') == 'ACTIVE'
                        and len(resources) == 1 and resources[0].get('id') == resource
                        and resources[0].get('type') == 'AWS_ECR_CONTAINER_IMAGE',
                        'ECR finding identity mismatch')
                seen.add(fid)
                severity = finding.get('severity')
                level = 'UNDEFINED' if severity == 'UNTRIAGED' else severity
                require(level in counts, 'ECR finding severity differs from summary')
                observed[level] += 1
                vulnerability = finding.get('packageVulnerabilityDetails', {})
                cve = vulnerability.get('vulnerabilityId')
                if (finding.get('type') == 'PACKAGE_VULNERABILITY'
                        and matches_openssl_exception(cve, level, vulnerability.get('vulnerablePackages'), ecr=True)):
                    require(cve not in accepted, 'Duplicate finding in OpenSSL exception evidence')
                    accepted[cve] = level
            token = page.get('nextToken')
            if not token:
                break
            require(isinstance(token, str) and token not in tokens, 'Repeated ECR pagination token')
            tokens.add(token)
            page = self.aws.call('ecr', 'describe-image-scan-findings', repositoryName=repository,
                                 imageId={'imageDigest': digest}, nextToken=token)
        require(observed == Counter(counts), 'ECR counts disagree with findings')
        if accepted:
            require(openssl_exception_applies(self.m, repository), 'OpenSSL exception expired')
            observed.subtract(accepted.values())
            record_openssl_exception(repository + '@' + digest, accepted)
        return dict(observed)

    def synchronous_counts(self, image, info, repository, digest, *, confirm_completed=False):
        # Require Inspector coverage of the exact image before a synchronous assessment.
        resource = arn(self.m, 'ecr', f'repository/{repository}/{digest}')
        coverage = self.aws.call('inspector2', 'list-coverage', filterCriteria={
            'ecrRepositoryName': [{'comparison': 'EQUALS', 'value': repository}],
            'resourceId': [{'comparison': 'EQUALS', 'value': resource}]})
        rows = coverage.get('coveredResources', [])
        accepted_status = {'PENDING_INITIAL_SCAN'}
        if confirm_completed and openssl_exception_applies(self.m, repository):
            accepted_status.add('SUCCESSFUL')
        require(not coverage.get('nextToken') and len(rows) == 1
                and rows[0].get('resourceId') == resource
                and rows[0].get('accountId') == self.m['accountId']
                and rows[0].get('resourceType') == 'AWS_ECR_CONTAINER_IMAGE'
                and rows[0].get('scanType') == 'PACKAGE'
                and rows[0].get('scanStatus', {}).get('reason') in accepted_status,
                'Inspector did not confirm image scan coverage')
        with tempfile.TemporaryDirectory(prefix='tc-inspector-') as tmp:
            work = Path(tmp)
            env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': tmp, 'LANG': 'C.UTF-8'}
            archive, binary = work / 'generator.zip', work / 'inspector-sbomgen'
            execute(['curl', '--fail', '--silent', '--proto', '=https', '--max-time', '60',
                     '--max-filesize', '33554432', '--output', str(archive), SBOMGEN_URL], env)
            require(hashlib.sha256(archive.read_bytes()).hexdigest() == SBOMGEN_SHA256,
                    'Inspector SBOM generator checksum mismatch')
            with ZipFile(archive) as bundle:
                binary.write_bytes(bundle.read(f'inspector-sbomgen-{SBOMGEN_VERSION}/linux/amd64/inspector-sbomgen'))
            binary.chmod(0o700)
            tar, output = work / 'image.tar', work / 'sbom.json'
            self.docker('image', 'save', '--output', str(tar), image, timeout=180)
            execute([str(binary), 'container', '--image', str(tar), '--skip-cloud-metadata',
                     '--max-read-file-size', '0', '-o', str(output)], env, timeout=300)
            sbom = json.loads(output.read_text(), object_pairs_hook=unique_object)
        require(sbom.get('bomFormat') == 'CycloneDX' and sbom.get('components'),
                'Inspector image inventory is empty or invalid')
        component = sbom.get('metadata', {}).get('component', {})
        props = component.get('properties', [])
        prefix = 'amazon:inspector:sbom_generator:'
        layers = info.get('RootFS', {}).get('Layers')
        require(component.get('type') == 'container'
                and [p['value'] for p in props if p['name'] == prefix + 'image_id'] == [info['configDigest']]
                and layers and [p['value'] for p in props if p['name'] == prefix + 'layer_diff_id'] == layers
                and not any('skipped_layer' in p['name'] for p in props),
                'Inspector inventory differs from the verified image configuration or layers')
        response = self.aws.call('inspector-scan', 'scan-sbom', sbom=sbom, outputFormat='INSPECTOR')
        return inspector_counts(response.get('sbom'), manifest=self.m, repository=repository, digest=digest)

    def publish(self, name, local, tag, deadline=None):
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
        # Digest lookups can return one record per tag when a retry republishes
        # the same image. Resolve this immutable release tag, then verify its digest.
        remote = self.aws.call('ecr', 'batch-get-image', repositoryName=repository,
            imageIds=[{'imageTag': tag}], acceptedMediaTypes=[
                'application/vnd.docker.distribution.manifest.v2+json', 'application/vnd.oci.image.manifest.v1+json'])
        require(not remote.get('failures') and len(remote.get('images', [])) == 1, 'Cannot verify pushed image')
        image_id = remote['images'][0].get('imageId', {})
        require(isinstance(image_id, dict) and image_id.get('imageTag') == tag
                and image_id.get('imageDigest') == digest, 'Pushed image identity differs from the release tag/digest')
        manifest = json.loads(remote['images'][0]['imageManifest'])
        require(manifest.get('config', {}).get('digest') == info['configDigest'], 'Pushed artifact differs from local image (multi-platform indexes are unsupported)')
        # Repositories must scan on push (basic or enhanced). No start_image_scan
        # fallback that can bypass a failed/missing organizational scan policy.
        started = time.monotonic()
        # Start each image's budget only after publication and digest verification.
        # Retain an optional earlier absolute deadline for existing custom callers.
        deadline = min(started + 1800, deadline) if deadline is not None else started + 1800
        last_status, last_reported, next_report = 'NOT_CHECKED', None, started

        def report(status):
            nonlocal last_status, last_reported, next_report
            last_status = status
            now = time.monotonic()
            if status != last_reported or now >= next_report:
                print(f'Image scan: repository={repository} digest={digest} '
                      f'status={status} elapsed={int(now - started)}s', flush=True)
                last_reported, next_report = status, now + 60

        checked_with_exception = False
        attempted_sync = set()
        sync_counts = None
        while time.monotonic() < deadline:
            try:
                scan = self.aws.call('ecr', 'describe-image-scan-findings', repositoryName=repository, imageId={'imageDigest': digest})
            except DeployError as exc:
                if str(exc).endswith(': ScanNotFoundException'):
                    report('SCAN_NOT_FOUND')
                    time.sleep(max(0, min(10, deadline - time.monotonic())))
                    continue
                raise
            status = scan.get('imageScanStatus', {}).get('status')
            findings = scan.get('imageScanFindings', {})
            # Never log raw AWS status descriptions, findings or response payloads.
            safe_status = status if status in ('COMPLETE', 'ACTIVE', 'IN_PROGRESS', 'PENDING',
                'FAILED', 'UNSUPPORTED_IMAGE', 'SCAN_ELIGIBILITY_EXPIRED', 'FINDINGS_UNAVAILABLE',
                'LIMIT_EXCEEDED') else 'UNKNOWN'
            if status in ('COMPLETE', 'ACTIVE') and not findings.get('imageScanCompletedAt'):
                safe_status += '_AWAITING_COMPLETION'
            report(safe_status)
            confirm_completed = False
            if status in ('COMPLETE', 'ACTIVE') and findings.get('imageScanCompletedAt'):
                timestamp = findings['imageScanCompletedAt']
                if isinstance(timestamp, (int, float)):
                    completed = datetime.fromtimestamp(timestamp, timezone.utc)
                else:
                    completed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                require(0 <= (datetime.now(timezone.utc) - completed).total_seconds() < 86400, 'Image scan must have completed within the last 24 hours')
                counts = self.registry_counts(scan, repository, digest)
                blocked = ('CRITICAL', 'HIGH', 'MEDIUM', 'UNDEFINED')
                if self.scan_policy == 'payload-dev-high-critical':
                    blocked = ('CRITICAL', 'HIGH', 'UNDEFINED')
                    # Report validated counts, never raw findings or AWS responses.
                    print('Payload dev image scan counts: ' + compact(counts), flush=True)
                require(not any(counts.get(level, 0) for level in blocked), 'Image scan exceeds the release threshold')
                # A new image can become ACTIVE before Inspector publishes its findings.
                # Confirm a clean native result for these four services during the waiver.
                confirm_completed = openssl_exception_applies(self.m, repository) and not any(
                    findings.get('findingSeverityCounts', {}).get(level) for level in (*PRODUCTION_BLOCKED, 'UNTRIAGED'))
                if not confirm_completed:
                    return uri + '@' + digest
                report('AWAITING_FINDING_CONFIRMATION')
            require(confirm_completed or status in ('IN_PROGRESS', 'PENDING', 'ACTIVE'), 'Image scan failed or is unsupported')
            if (status == 'PENDING' or confirm_completed) and self.m['environment'] == 'prod':
                # Re-read ECR after the synchronous call. A completed ECR result
                # or terminal failure takes priority over the alternate evidence.
                if sync_counts is not None:
                    require(not checked_with_exception or openssl_exception_applies(self.m, repository),
                            'OpenSSL exception expired')
                    require(scan.get('registryId') == self.m['accountId'] and scan.get('repositoryName') == repository
                            and scan.get('imageId', {}).get('imageDigest') == digest,
                            'Pending ECR scan does not identify the verified image')
                    if 'findingSeverityCounts' in findings:
                        self.check_production_counts(self.registry_counts(scan, repository, digest))
                    print(f'Inspector synchronous scan passed: repository={repository} digest={digest}', flush=True)
                    return uri + '@' + digest
                if status not in attempted_sync and time.monotonic() - started >= 90:
                    attempted_sync.add(status)
                    checked_with_exception = openssl_exception_applies(self.m, repository)
                    try:
                        sync_counts = self.synchronous_counts(image, info, repository, digest, confirm_completed=confirm_completed)
                    except InspectorThresholdExceeded:
                        raise
                    except (DeployError, OSError, BadZipFile, ValueError, KeyError, TypeError) as exc:
                        message = str(exc) if isinstance(exc, DeployError) else type(exc).__name__
                        print(f'Inspector synchronous scan unavailable ({message}); continuing ECR polling', flush=True)
                    if sync_counts is not None:
                        print('Inspector synchronous scan counts: ' + compact(sync_counts), flush=True)
                        self.check_production_counts(sync_counts)
                        continue
            time.sleep(max(0, min(10, deadline - time.monotonic())))
        raise DeployError(f'Image scan timed out after {int(time.monotonic() - started)}s: '
                          f'repository={repository} digest={digest} last_status={last_status}; '
                          'service was not updated')


def deploy(aws, m, locals_by_name, release, publisher, health_checks=None):
    require(set(locals_by_name) == set(m['images']), 'Supply exactly one prebuilt image per configured container')
    require(re.fullmatch(r'[a-f0-9]{40}-[0-9]{1,12}', release), 'Release must be CIRCLE_SHA1-CIRCLE_BUILD_NUM')
    previous = read_service(aws, m)
    definition = previous['taskDefinition']
    require(stable(previous, definition), 'Existing service must be stable before deploying')
    response = aws.call('ecs', 'describe-task-definition', taskDefinition=definition, include=['TAGS'])
    task, tags = response['taskDefinition'], response.get('tags', [])
    # Validate configuration before publishing anything. Placeholder digests are
    # only used for validation and never sent to AWS.
    task_request(m, task, tags, {name: 'preflight@sha256:' + '0' * 64 for name in m['images']}, health_checks)
    images = {}
    for name, local in locals_by_name.items():
        images[name] = publisher.publish(name, local, release)
    current = read_service(aws, m)
    require(stable(current, definition), 'Service changed during image publication; retry after inspection')
    request = task_request(m, task, tags, images, health_checks)
    registered = aws.call('ecs', 'register-task-definition', **request)['taskDefinition']
    target = registered['taskDefinitionArn']
    require(re.fullmatch(re.escape(arn(m, 'ecs', 'task-definition/' + m['taskFamily'])) + r':[0-9]+', target), 'Unexpected registered task ARN')
    # Read back and compare the actual registered fields before promotion.
    saved = aws.call('ecs', 'describe-task-definition', taskDefinition=target, include=['TAGS'])
    saved_request = {k: v for k, v in saved['taskDefinition'].items() if k in TASK_FIELDS}
    saved_request['tags'] = sorted(saved.get('tags', []), key=lambda t: t['key'])
    expected_request = {**request, 'tags': sorted(request.get('tags', []), key=lambda t: t['key'])}
    require(saved_request == expected_request,
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
    for name in ('deploy', 'check-auth'):
        p = sub.add_parser(name)
        p.add_argument('--manifest', required=True)
        if name == 'deploy':
            p.add_argument('--image', action='append', required=True, metavar='CONTAINER=LOCAL_IMAGE')
            p.add_argument('--bootstrap-health-checks', metavar='REVIEWED_JSON')
    args = parser.parse_args(argv)
    m = read_manifest(args.manifest)
    health_checks = None
    if args.command == 'deploy' and args.bootstrap_health_checks:
        health_checks = validate_health_checks(m, json.loads(
            Path(args.bootstrap_health_checks).read_text(), object_pairs_hook=unique_object))
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
        result = deploy(aws, m, images, release, Publisher(aws, m, directory), health_checks)
    print(json.dumps(result, indent=2))  # Only non-secret rollout evidence.


if __name__ == '__main__':
    try:
        main()
    except (DeployError, ValueError, KeyError, TypeError, OSError):
        # Do not emit tracebacks/SDK payloads, which can contain secrets.
        exc = sys.exc_info()[1]
        print('Deployment stopped: ' + (str(exc) if isinstance(exc, DeployError) else 'invalid input or response'), file=sys.stderr)
        sys.exit(1)
