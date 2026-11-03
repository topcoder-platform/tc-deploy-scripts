# Migrate before using v2

Merging this PR does not change pinned v1 consumers or installed IAM policies. **Do not simply replace a v1 tag with this commit in existing CircleCI configs.** The Auth0 credential-export/SSM/sourced-file interface is deliberately removed. Publish a new major release after dev verification; never move a v1 tag.

## Prepare one dev service

1. Start with a straightforward one-container service, for example lookups. Have an administrator inspect its existing ECS service/task, ECR settings and IAM roles without exporting decrypted SSM values. Record the previous revision/digest in a restricted release record.
2. Create a manifest with exact identifiers from that inspection. Generate IAM documents using `tcdeploy.py policies`; install them through infrastructure review. Keep the explicit secret-access/role-chaining deny in the role policy and preferably use the generated permissions as its permissions boundary too. Remove unrelated policies and audit resource-based grants. The deployer needs no infrastructure-creation permissions.
3. Restrict PassRole to the exact task/execution roles (use JSON `null` for `taskRoleArn` when the existing task has no application role; do not add one just to deploy). Give the execution role only its runtime parameter/secret ARNs and necessary KMS keys. Pre-provision runtime bindings and defaults through administrator-owned infrastructure. v2 preserves references without fetching values/types: missing bindings fail at startup and trigger rollback.
4. Enable unconditional ECR tag immutability and supported basic/enhanced scan-on-push. Enable ECS circuit-breaker rollback, positive desired capacity and explicit task health checks. Remove plaintext secret environment values and `RESET_DB` secret bindings. Use non-root runtime images. Bootstrap/infrastructure updates remain separate from code deployment.
5. Commit non-secret `deploy/dev.json`. Use an exact `develop` or `dev` branch for dev and the exact reviewed `master` or legacy `prod` branch for production source/config refs. Examples intentionally do not guess real targets. Do not put keys, client secrets, passwords or parameter values in manifests.
6. Prepare a reviewed executor with Python >=3.10 with the `tarfile` extraction-filter security backport, AWS CLI v2, Docker/Buildx, Git and trusted CA certificates. Pin its digest and the suite's full reviewed commit in service configuration. No runtime tool/package installation on the credential host. Replace template placeholders with literal reviewed values, not caller-overridable pipeline parameters.
7. Split build/test and deploy using `examples/circleci-v2.yml`. Remove `org-global`, old helper copies, all `source awsenvconf` / `source *_env`, SSM build/deploy/QA retrieval, and unpinned host installs. Use restricted dev/prod contexts with no broker/static AWS secrets, production approval and serialization. Verify OIDC v3 availability; restrict fork secret passing and SSH debugging. Pin/download the entire suite.
8. Build committed source separately with `build_image.py`. Transfer only image archives through job-specific workflow workspaces. Do not cache the checkout/credential directories. The helper rejects known secret filenames and excludes untracked generated credentials; it does not replace a full secret scanner. Never build after deployment authentication.

For private packages, use a separate package-read-only identity and BuildKit secret mounts in an independently reviewed build path, never production deploy credentials. The reviewed challenge/member dependency manifests no longer referenced CodeArtifact packages: remove obsolete broker login/buildvar steps where unused. Do not add a general secret-fetch option back to this suite.

## Dev acceptance gates

- Run the offline tests and shell syntax checks. They do not prove installed IAM state.
- With an administrator identity, validate/simulate the generated policies. SSM listing/reads, Secrets Manager reads, direct KMS decryption and role chaining must be explicitly denied. Verify only the intended ECS service, ECR repositories, task family and two PassRole ARNs are allowed. Check OIDC audience/project/checkout/config origin/ref; a wrong project/ref must not assume the role. Do not weaken project restrictions to make a test pass.
- Run `awsconfiguration.sh --manifest deploy/dev.json` in the intended job. It must verify identity without files/credential output. Missing v3 token, wrong account/role and legacy `DEV` arguments must fail.
- Run a real dev release. Verify roles, runtime secret references, sidecars, resources, volumes and health checks remain unchanged. Compare reported image digests with healthy running tasks. CloudTrail should show no deployment-principal SSM/Secrets Manager calls; runtime retrieval belongs to the execution role.
- Test an intentionally unhealthy dev image and verify failed release plus ECS rollback to the previous revision. Wrong digest, failed scan, denied AWS call, concurrency conflict or wrong source label must stop promotion. Old steady-state events/zero capacity must not pass.
- Inspect logs, workspace artifacts and image history/layers privately for accidental secrets. Remove stale broker/static credentials from project settings as well as contexts. Credential rotation/session revocation are separate incident actions.

## Production and concurrency

Use a separately reviewed prod manifest/role/context, exact prod account, protected exact `master` or legacy `prod` source/config refs and approval gate. Validate IAM denies before use. Promote reviewed suite/executor commits and retain a previous healthy revision/digest. ECS performs circuit-breaker rollback; failed/timeout deployments require inspection rather than blindly overwriting a newer release.

Serial groups prevent normal CI overlap. ECS UpdateService has no general compare-and-swap for revision, so before/after checks cannot eliminate every out-of-band race. Restrict other writers and coordinate operator changes.

## Adoption work and consumer PRs

- Install/restrict OIDC/IAM/contexts; retire broker grants; rotate exposed secrets and revoke sessions.
- Review and merge the [consumer PRs](ECS_MIGRATION_PRS.md), then apply runtime bindings, scanner/immutability settings and ECS health/rollback changes through infrastructure administration.
- Remove production DB-reset options/startup entrypoints from groups/identity/review and remove schema-reset privileges from runtime DB users. v2 rejects reset-enabled image/task environments and any RESET_DB secret binding in **both** environments. Controlled dev resets belong outside deployment.
- Preserve custom migration, CloudFormation, scan and monitoring checks; see `SERVICES.md`. Do not overwrite custom pipelines with the basic example.
- Pin forums' four cross-repository client clones. A generic builder cannot prove remote code downloaded inside a Dockerfile; Dockerfiles remain trusted build code.

The linked consumer PRs prepare repository changes; none is a claim that live ECS/IAM/CircleCI state has changed. Infrastructure and real dev acceptance remain adoption gates.

## Audit coverage

| Finding | v2 mitigation | Required adoption |
| --- | --- | --- |
| F01/F02 TLS/eval | Remove Auth0 HTTP/eval path; STS validates OIDC | Install narrow trust; retire broker |
| F03 SSM shell source | Disable parameter/export helpers; parse manifest as data | Remove caller helper/source steps |
| F04 ignored failures | Check process/API results and identity; no SSM reads | Negative dev tests |
| F05 execution role override | Preserve/verify exact roles; narrow PassRole | Install service-specific roles |
| F06 shared credentials | No broker/static fallback; scrub child environments | Restrict contexts/trust; remove stale secrets |
| F07 build context | Separate committed-source builds; reject secret files | Migrate build jobs |
| F08 mutable inputs | Reviewed full suite commit and executor digest | Pin Dockerfile remote dependencies |
| F09 rollout/artifact integrity | Digests, scans, actual revision/tasks/health | Scanner, immutable repos, circuit breaker |
| F10 DB reset | Reject reset-enabled images/tasks or secret binding | Remove legacy reset code/DB privileges |
| F11 credential files/logging | In-memory STS, stdin requests, private Docker config, sanitized errors | Ephemeral runners, controlled logs/debug |

Legacy SSM upload/setup and password-encryption helpers also fail closed. Secret provisioning belongs in a separate administrator/IaC workflow. Historical v1 tags are migration references, not security workarounds.

## Verified executor for service adoption

`cimg/aws@sha256:4cf3768db00ddf9bc439b8c84e8a60c11a14edf81c8baf76f74132144f8340d5` was resolved from `cimg/aws:2026.10` and inspected on 2026-11-03. It supplies Python 3.10.12 with `tarfile.extractall(filter=...)`, AWS CLI 2.38.4, Docker Buildx 0.38.0 and Git 2.55.0. The offline suite passes inside this exact image. This verifies tool compatibility, not the absence of executor vulnerabilities. Service configurations must use the digest, not the tag.

## Reviewed adapters for custom release gates

The default CLI and generated role policy still deploy an existing ECS service only. A checked-in service adapter may call `authenticate(..., additional_actions=...)` for the fixed allowlist in `ADAPTER_ACTIONS`: one-shot migration tasks, target health/Inspector reads, or updates to an existing CloudFormation stack. This is a Python API for reviewed code, not a pipeline parameter or CLI permission switch. The immutable session deny for SSM, Secrets Manager, KMS decryption and role chaining is retained. Each consumer must supply an administrator-installed role and permissions boundary with exact resource scopes for its additional actions. CloudFormation adapters must use the previous installed template and a separately scoped CloudFormation service role that also has no parameter/secret permissions; template installation belongs to infrastructure administration. No create-stack, arbitrary command, or secret-read capability is added to the default CLI.
