#!/usr/bin/env python3
"""Build committed source in a clean context without deployment credentials.

Run in a separate build job, before attaching any deployment context. No package
installation or repository-defined build command executes on the credential host.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile


def run(command, env):
    return subprocess.run(command, env=env, capture_output=True, check=True)


def forbidden(path):
    parts = Path(path).parts
    name = parts[-1]
    return (any(p in ('.aws', '.ssh', '.git') for p in parts)
            or name in ('awsenvconf', 'buildenvvar', '.npmrc', '.netrc', 'fetched_parameters.json',
                        'paramnames.json', 'paramwithvalue.json', 'cli-input.json', 'upload_object.json')
            or name.endswith(('_env', '.key', '.p12', '.pfx'))
            or name == '.env' or (name.startswith('.env.') and name not in ('.env.example', '.env.sample')))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--dockerfile', default='Dockerfile')
    parser.add_argument('--context', default='.')
    parser.add_argument('--target')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.:/-]+', args.image):
        raise ValueError('Invalid local image tag')
    for value in (args.dockerfile, args.context):
        if Path(value).is_absolute() or '..' in Path(value).parts:
            raise ValueError('Build paths must stay within the checkout')
    if args.target and not re.fullmatch(r'[A-Za-z0-9_-]+', args.target):
        raise ValueError('Invalid build target')
    env = {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8'}
    for key in ('DOCKER_HOST', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH'):
        if key in os.environ:
            env[key] = os.environ[key]
    sha = run(['git', 'rev-parse', 'HEAD'], env).stdout.decode().strip()
    if os.environ.get('CIRCLE_SHA1') and os.environ['CIRCLE_SHA1'] != sha:
        raise ValueError('Checkout differs from CircleCI source SHA')
    with tempfile.TemporaryDirectory(prefix='tc-build-') as temp:
        archive = Path(temp) / 'source.tar'
        run(['git', 'archive', '--format=tar', '--output=' + str(archive), 'HEAD'], env)
        context = Path(temp) / 'context'
        context.mkdir()
        with tarfile.open(archive) as source:
            members = source.getmembers()
            if any(forbidden(m.name) or not (m.isfile() or m.isdir()) for m in members):
                raise ValueError('Committed source includes credentials, secret-file names, symlinks or unsupported archive entries; sanitize before building')
            for member in members:
                if member.isfile() and member.name.endswith('.pem'):
                    content = source.extractfile(member).read()
                    if not re.fullmatch(rb'(?:\s*-----BEGIN CERTIFICATE-----[A-Za-z0-9+/=\s]+-----END CERTIFICATE-----\s*)+', content):
                        raise ValueError('PEM build inputs must contain public certificates only')
            source.extractall(context, filter='data')
        env['DOCKER_CONFIG'] = str(Path(temp) / 'docker-config')
        Path(env['DOCKER_CONFIG']).mkdir(mode=0o700)
        command = ['docker', 'buildx', 'build', '--load', '--pull', '--no-cache',
                   '--provenance=false', '--platform', 'linux/amd64',
                   '--label', 'org.opencontainers.image.revision=' + sha,
                   '--tag', args.image, '--file', str(context / args.dockerfile)]
        if args.target:
            command += ['--target', args.target]
        command += [str(context / args.context)]
        # No build-arg or secret option exists: fetch runtime values only in ECS.
        # Build logs are suppressed on failure to avoid dumping accidental secrets.
        run(command, env)
    print('Built committed source ' + sha + ' as ' + args.image)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError, tarfile.TarError):
        print('Build failed; check committed build inputs and secret-file exclusions. No deployment credentials were passed to Docker.', file=sys.stderr)
        sys.exit(1)
