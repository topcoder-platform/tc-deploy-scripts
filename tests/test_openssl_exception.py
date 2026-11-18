from copy import deepcopy
from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

from test_security import d, manifest, DIGEST


class OpenSSLExceptionTests(unittest.TestCase):
    def setUp(self):
        clock = patch.object(d, 'datetime', wraps=datetime)
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.clock.now.return_value = datetime(2026, 11, 18, tzinfo=timezone.utc)
        self.repo = 'bus-api-v6'
        self.m = dict(manifest(), repository='github.com/topcoder-platform/bus-api-v6',
                      images={'app': self.repo}, accountId='409275337247', environment='prod',
                      branch='master', region='us-east-1')
        self.publisher = d.Publisher(Mock(), self.m, '/tmp')
        self.path = '/usr/local/include/node/openssl/archs/linux-x86_64/asm/include/openssl/opensslv.h'
        self.cve = 'CVE-2026-95691'
        finding = {'id': self.cve, 'severity': 'high', 'affects': [{
            'installed_version': 'pkg:generic/openssl/openssl@3.5.9',
            'fixed_version': '3.5.10', 'path': self.path}]}
        self.report = {'vulnerability_count': dict(high=1, medium=0, critical=0, other=0, low=0),
                       'vulnerabilities': [finding],
                       'messages': [{'info_message': 'Component scanned: no known vulnerabilities.'}]}
        issue = {'findingArn': 'unique', 'status': 'ACTIVE', 'type': 'PACKAGE_VULNERABILITY',
                 'severity': 'HIGH', 'resources': [{'type': 'AWS_ECR_CONTAINER_IMAGE',
                    'id': d.arn(self.m, 'ecr', f'repository/{self.repo}/{DIGEST}')}],
                 'packageVulnerabilityDetails': {'vulnerabilityId': self.cve, 'vulnerablePackages': [{
                    'packageManager': 'GENERIC', 'name': 'openssl/openssl', 'version': '3.5.9',
                    'fixedInVersion': '3.5.10', 'filePath': self.path}]}}
        self.scan = {'registryId': self.m['accountId'], 'repositoryName': self.repo,
                     'imageId': {'imageDigest': DIGEST}, 'imageScanStatus': {'status': 'ACTIVE'},
                     'imageScanFindings': {'findingSeverityCounts': {'HIGH': 1}, 'enhancedFindings': [issue]}}

    def sync(self, report):
        return d.inspector_counts(report, manifest=self.m, repository=self.repo, digest=DIGEST)

    def registry(self, scan):
        self.publisher.check_production_counts(self.publisher.registry_counts(scan, self.repo, DIGEST))

    def test_both_paths_require_scope_and_expire_at_midnight_utc(self):
        self.assertEqual(self.sync(self.report)['HIGH'], 0)
        self.registry(self.scan)
        for key, value in [('branch', 'develop'), ('environment', 'dev'), ('accountId', '000000000000'),
                           ('region', 'us-west-2'), ('repository', 'github.com/topcoder-platform/other'),
                           ('images', {'app': 'other'})]:
            with self.subTest(key=key), patch.dict(self.m, {key: value}):
                with self.assertRaises(d.InspectorThresholdExceeded):
                    self.sync(self.report)
                with self.assertRaises(d.DeployError):
                    self.registry(self.scan)
        self.clock.now.return_value = d.OPENSSL_EXCEPTION_END
        with self.assertRaises(d.InspectorThresholdExceeded):
            self.sync(self.report)
        with self.assertRaises(d.DeployError):
            self.registry(self.scan)

    def test_incomplete_ambiguous_or_unrelated_sync_evidence_still_blocks(self):
        for label in ('id', 'version', 'path', 'extra package', 'escalated', 'unclassified', 'missing',
                      'summary', 'second finding', 'incomplete assessment'):
            with self.subTest(label=label):
                report = deepcopy(self.report)
                f = report['vulnerabilities'][0]
                if label == 'id': f['id'] = 'CVE-OTHER'
                if label == 'version': f['affects'][0]['installed_version'] += '0'
                if label == 'path': f['affects'][0]['path'] = '/other/opensslv.h'
                if label == 'extra package': f['affects'].append({'path': self.path})
                if label == 'escalated':
                    f['severity'] = 'critical'
                    report['vulnerability_count'].update(high=0, critical=1)
                if label == 'unclassified': f['severity'] = 'none'
                if label == 'missing': report['vulnerabilities'] = []
                if label == 'summary': report['vulnerability_count']['high'] += 1
                if label == 'second finding':
                    report['vulnerabilities'].append(dict(f, id='CVE-OTHER'))
                    report['vulnerability_count']['high'] += 1
                if label == 'incomplete assessment': report['messages'] = [{'error_message': 'incomplete'}]
                with self.assertRaises(d.DeployError):
                    self.sync(report)

    def test_registry_pages_must_identify_every_finding_and_match_counts(self):
        self.scan['nextToken'] = 'next'
        last = dict(self.scan, imageScanFindings={'findings': []})
        del last['nextToken']
        self.publisher.aws.call.return_value = last
        self.registry(self.scan)
        self.publisher.aws.call.assert_called_once_with('ecr', 'describe-image-scan-findings',
            repositoryName=self.repo, imageId={'imageDigest': DIGEST}, nextToken='next')
        for label in ('wrong digest', 'missing detail', 'duplicate', 'unrelated', 'more packages', 'cycle'):
            with self.subTest(label=label):
                scan, page = deepcopy(self.scan), deepcopy(last)
                f = scan['imageScanFindings']['enhancedFindings'][0]
                if label == 'wrong digest': page['imageId'] = {'imageDigest': 'wrong'}
                if label == 'missing detail': scan['imageScanFindings']['enhancedFindings'] = []
                if label == 'duplicate': page['imageScanFindings'] = {'enhancedFindings': [f]}
                if label == 'unrelated':
                    other = deepcopy(f)
                    other.update(findingArn='other', severity='MEDIUM')
                    other['packageVulnerabilityDetails']['vulnerabilityId'] = 'CVE-OTHER'
                    page['imageScanFindings'] = {'enhancedFindings': [other]}
                    scan['imageScanFindings']['findingSeverityCounts']['MEDIUM'] = 1
                if label == 'more packages': f['packageVulnerabilityDetails']['vulnerablePackages'].append({})
                if label == 'cycle': page = deepcopy(scan)
                self.publisher.aws.call.return_value = page
                with self.assertRaises(d.DeployError):
                    self.registry(scan)

    def test_untriaged_is_blocking_unless_explicitly_accepted(self):
        fid = self.scan['imageScanFindings']
        f = fid['enhancedFindings'][0]
        f['severity'] = 'UNTRIAGED'
        fid['findingSeverityCounts'] = {'UNTRIAGED': 1}
        with self.assertRaises(d.DeployError):
            self.registry(self.scan)
        f['packageVulnerabilityDetails']['vulnerabilityId'] = 'CVE-2026-107493'
        self.registry(self.scan)
