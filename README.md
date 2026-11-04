# Topcoder deployment scripts v2

Deploy prebuilt images to an **existing** ECS/Fargate service without giving the deployment role access to Parameter Store or Secrets Manager. CircleCI OIDC v3 exchanges a short-lived job identity for an AWS STS session; the Auth0 client-secret broker is no longer used.

**This is a breaking migration, not a drop-in v1 patch.** Do not repoint existing v1 tags. Pipelines that source `awsenvconf`, `deployvar_env`, or `buildvar_env` must migrate with their IAM roles. Old interfaces fail before network calls. EBS, S3, Lambda and secret-provisioning modes are not supported in v2. Historical `direct/` assets are outside the v2 deployer.

Read [the migration guide](docs/MIGRATION.md), [the Auth0/AWS explanation](docs/AUTHENTICATION.md), and [the 19-service adoption checklist](docs/SERVICES.md) before testing.

## Requirements

- A reviewed, digest-pinned Linux executor containing Python >=3.10 with the `tarfile` extraction-filter security backport, AWS CLI v2, Docker/Buildx, Git and system CA certificates. No package installation in the credential-bearing job. This deployer has no external Python dependencies.
- CircleCI Cloud with `CIRCLE_OIDC_TOKEN_V3`, protected exact development (`develop` or `dev`) and production (`master` or legacy `prod`) refs, and restricted deployment contexts containing no broker/static AWS credentials.
- Separate per-service/per-environment deploy, task and execution roles, and a reviewed non-secret manifest.
- Existing immutable ECR repositories with scan-on-push, ECS circuit-breaker rollback, positive desired capacity, explicit task health checks, and pre-provisioned runtime secret references.

## Usage

Copy `examples/deploy.dev.json` / `examples/deploy.prod.json` into the service repository and replace the example identifiers with administrator-verified values. These are placeholders, not guessed Topcoder targets. Generate IAM documents offline:

```sh
python3 -I tcdeploy.py policies --manifest deploy/dev.json > policies.json
```

An administrator installs the generated `trust` and `permissions` documents through reviewed infrastructure changes. Secret/KMS read permissions belong on the narrowly scoped execution role, never the deployment role.

From the service checkout, in a build job without deployment context:

```sh
python3 -I /tmp/tc-deploy-scripts/build_image.py --image example-v6:candidate
docker save --output /tmp/image.tar example-v6:candidate
```

The helper builds `git archive HEAD` in a temporary context, rejects credential/secret-file inputs and symlinks, accepts PEM files only when they contain public certificates, strips credentials from subprocess environments, and provides no secret/build-argument options. For nested Dockerfiles use `--dockerfile docker/Dockerfile`; for a sidecar use `--dockerfile clamav/Dockerfile --context clamav`. `--target migrate` can build a migration image; executing migrations remains a separately controlled operation.

In a separately authorized deploy job, load the workflow-specific image archive, then:

```sh
/tmp/tc-deploy-scripts/awsconfiguration.sh --manifest deploy/dev.json
/tmp/tc-deploy-scripts/master_deploy.sh --manifest deploy/dev.json \
  --image example-v6=example-v6:candidate
```

`awsconfiguration.sh` is an optional identity check, not a credential exporter. `master_deploy.sh` authenticates internally. Neither writes AWS credentials to the checkout/default profile, logs, or shell exports. Use the entire SHA-pinned suite, not the old four copied shell files. See `examples/circleci-v2.yml`; replace its explicit executor/commit placeholders before use.

The deployer verifies account/role, live service configuration, source label, ECR immutability, local/remote configuration digest, a scan completed within 24 hours with no MEDIUM/HIGH/CRITICAL/UNDEFINED findings, and the exact healthy running revision/digests. Only selected images change; roles, secret references, sidecars, resources, volumes and health checks remain intact. Non-root runtime images are required and `RESET_DB` cannot be enabled. The source label is a consistency check, not cryptographic build provenance; protect the pipeline and artifact writers.

ECR may omit its optional severity-count map for a clean image. That response is accepted only after the same completion/freshness checks, with an exact registry/repository/digest match, explicitly empty findings lists, and no remaining page. An absent summary without that evidence, nonempty findings without a summary, or malformed counts fails closed. This requires no additional IAM permissions or changes to registry scanning. See the [ECR response schema](https://docs.aws.amazon.com/AmazonECR/latest/APIReference/API_ImageScanFindings.html).

Use a unique CircleCI build number when retrying publication to immutable tags. A failed rollout remains a failure even if ECS rolls back. The script never blindly reverts over another deployment.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests mock AWS/Docker and require no credentials, account, network or external Python packages. Passing them does not replace IAM simulation and a real dev rollout. GitHub CI runs them with read-only repository permissions.
