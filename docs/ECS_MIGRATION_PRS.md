# Production ECS deployment PR index

Prepared 2026-11-03. **46 open draft consumer PRs cover 48 inventoried ECS services:** 40 active service repositories, the inactive tc-mcp repository, and five legacy repositories covering seven additional inactive services. The shared implementation is [tc-deploy-scripts #40](https://github.com/topcoder-platform/tc-deploy-scripts/pull/40), targeting master.

All 41 OIDC consumer PRs pin reviewed code commit `bbc9b3d0c702947d26b6d9686d7b29104ebe461a` and the same verified executor digest. The shared PR may have later documentation-only commits. Remote PR heads, draft state, clean local worktrees, suite pins and role/boundary consistency were checked after publication. The five inactive-containment PRs intentionally do not install or assume a replacement AWS role.

## Scope and limitations

Read-only inventory found **58 ECS services in production us-east-1**, of which 45 had positive desired capacity. Sixteen other enabled regions returned `AccessDeniedException`; they have **not** been verified empty. Ten inventoried services have no shared-script release path mapped from the accessible configuration; they are listed separately below. This is not a claim to have migrated unknown jobs or inaccessible regions.

No AWS resource, IAM policy, CircleCI context or credential was changed. No image was pushed to ECR and no real dev/prod release was attempted. No PR was merged. Dev AWS credentials were expired, so exact dev resource manifests were deliberately not invented. These are reviewable migration PRs, **not ready-to-merge deployment configurations**.

## Before merging consumer PRs

1. Verify actual dev ECS/ECR/IAM identifiers and commit each dev manifest/policy. Populate each private project's exact CircleCI UUID where noted; no wildcard identity is accepted.
2. Install the CircleCI OIDC provider and service-specific role, matching permissions boundary and exact project/repository/source/config-ref trust. Role, boundary and requested session deny SSM, Secrets Manager, KMS decryption and role chaining.
3. Remove legacy broker/static AWS credentials from project settings and contexts; install restricted empty deployment contexts. Keep image builds separate from authenticated release jobs.
4. Apply immutable ECR tags/scanning, real container health checks, runtime secret references and circuit-breaker rollback through IaC. Remove RESET_DB bindings/plaintext secrets and limit execution-role reads to each service's runtime references.
5. Run a real dev release, wrong-identity denial checks and unhealthy-image rollback. Verify deployment-principal CloudTrail has no Parameter Store/Secrets Manager access. Retire shared broker permissions only after remaining consumers migrate.

Missing CircleCI UUIDs: `infra-inventory`, `terms-receiver`, `standardized-skills-processor`, `opportunities-api-v6`, `status-api-v6`, `payload-cms`. All intentionally fail before authentication until their verified UUID is committed.

Special review dependencies:

- **Community App:** based on develop to include merged security PR #7296. Promote both security/runtime-binding and deployment changes to master together. Required server-side buildvar values must first become runtime references; retain the appvar precedence rule. Optional performance testing remains; the old undefined/recursive smoke workflow is removed and requires an explicit replacement if needed.
- **freeCodeCamp:** stacked on security PR #112, then promote through dev to the existing prod branch. API configuration moves from a baked S3 .env artifact to ECS runtime bindings. The old Jenkins frontend release needs a separate identity restricted to its S3/CloudFront resources before merging; this PR migrates the ECS API only.
- **AV Scanner:** administrator installs the digest-capable existing-stack template and detaches eight retained SSM deployment pointers first. CI uses the previous template and two digest parameters through a separate restricted CloudFormation role; both roles deny secret access. Never activate the old and replacement scanners together.
- **Forms:** API retains the one-shot migration and reviewed first-activation gate; processor deployment follows the API schema migration. Processor activation remains an administrator operation.
- **Payload / Status:** preserve their rollout, scan, migration/monitoring, ALB/public-health and rollback adapters. Payload's scan wait is bounded to 15 minutes within its one-hour OIDC session; delayed scans require retry and long rollout/rollback timing needs dev rehearsal.
- **nginx:** production public CloudFront/DNS values were verified without SSM. Dev promotion is explicitly blocked until its routing settings and separate build target are verified.
- **Learning Paths:** ECS release is separated from the old MongoDB-trigger Lambda release, which requires its own infrastructure-owner release path.
- **Resource API:** retain Newman QA checks using a separate test-only context, with no AWS/broker credentials or SSM retrieval.
- **Opportunities:** no master branch exists; the draft targets develop and the production job remains disabled by its exact master filter pending a reviewed production-branch decision.
- **Inactive legacy services:** the five containment PRs disable the broker pipelines and local release entry points. Zero capacity is an observation, not a declaration of permanent retirement. Apply the disablement to all still-enabled branches/jobs; reactivation requires a separate reviewed migration.

## Consumer PRs

| Repository | PR | Review base | Change |
| --- | --- | --- | --- |
| `topcoder-platform/autopilot-v6` | [#75](https://github.com/topcoder-platform/autopilot-v6/pull/75) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/av-scanner-v6` | [#13](https://github.com/topcoder-platform/av-scanner-v6/pull/13) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/billing-accounts-api-v6` | [#35](https://github.com/topcoder-platform/billing-accounts-api-v6/pull/35) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/bus-api-v6` | [#12](https://github.com/topcoder-platform/bus-api-v6/pull/12) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/challenge-api-v6` | [#178](https://github.com/topcoder-platform/challenge-api-v6/pull/178) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/community-app` | [#7297](https://github.com/topcoder-platform/community-app/pull/7297) | `develop` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/docker-nginx-supply` | [#193](https://github.com/topcoder-platform/docker-nginx-supply/pull/193) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/email-service-v6` | [#10](https://github.com/topcoder-platform/email-service-v6/pull/10) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/engagements-api-v6` | [#98](https://github.com/topcoder-platform/engagements-api-v6/pull/98) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/forms-api-v6` | [#17](https://github.com/topcoder-platform/forms-api-v6/pull/17) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/forms-processor-v6` | [#12](https://github.com/topcoder-platform/forms-processor-v6/pull/12) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/forums-api-v6` | [#27](https://github.com/topcoder-platform/forums-api-v6/pull/27) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/freeCodeCamp` | [#113](https://github.com/topcoder-platform/freeCodeCamp/pull/113) | `fix/security-findings-2026-11` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/gamification-api` | [#32](https://github.com/topcoder-platform/gamification-api/pull/32) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/groups-api-v6` | [#19](https://github.com/topcoder-platform/groups-api-v6/pull/19) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/identity-api-v6` | [#58](https://github.com/topcoder-platform/identity-api-v6/pull/58) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/infra-inventory` | [#5](https://github.com/topcoder-platform/infra-inventory/pull/5) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/learning-paths-api` | [#270](https://github.com/topcoder-platform/learning-paths-api/pull/270) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/leave-api-v6` | [#16](https://github.com/topcoder-platform/leave-api-v6/pull/16) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/lookups-api-v6` | [#14](https://github.com/topcoder-platform/lookups-api-v6/pull/14) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/marathon-match-api-v6` | [#459](https://github.com/topcoder-platform/marathon-match-api-v6/pull/459) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/member-api-v6` | [#172](https://github.com/topcoder-platform/member-api-v6/pull/172) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/opportunities-api-v6` | [#8](https://github.com/topcoder-platform/opportunities-api-v6/pull/8) | `develop` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/payload-cms` | [#50](https://github.com/topcoder-platform/payload-cms/pull/50) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/procurement-api-v6` | [#8](https://github.com/topcoder-platform/procurement-api-v6/pull/8) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/project-billing-account-update-processor` | [#13](https://github.com/topcoder-platform/project-billing-account-update-processor/pull/13) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/projects-api-v6` | [#62](https://github.com/topcoder-platform/projects-api-v6/pull/62) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/reports-api-v6` | [#205](https://github.com/topcoder-platform/reports-api-v6/pull/205) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/resource-api-v6` | [#38](https://github.com/topcoder-platform/resource-api-v6/pull/38) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/review-api-v6` | [#382](https://github.com/topcoder-platform/review-api-v6/pull/382) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/standardized-skills-api` | [#141](https://github.com/topcoder-platform/standardized-skills-api/pull/141) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/standardized-skills-processor` | [#17](https://github.com/topcoder-platform/standardized-skills-processor/pull/17) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/status-api-v6` | [#10](https://github.com/topcoder-platform/status-api-v6/pull/10) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-archive/submission-scanner-processor` | [#81](https://github.com/topcoder-archive/submission-scanner-processor/pull/81) | `master` | Disable inactive deployment |
| `topcoder-platform/support-api-v6` | [#22](https://github.com/topcoder-platform/support-api-v6/pull/22) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/tc-ai-api` | [#93](https://github.com/topcoder-platform/tc-ai-api/pull/93) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-archive/tc-bus-api` | [#77](https://github.com/topcoder-archive/tc-bus-api/pull/77) | `master` | Disable inactive deployment |
| `topcoder-platform/tc-discord-bot` | [#29](https://github.com/topcoder-platform/tc-discord-bot/pull/29) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-archive/tc-email-service` | [#103](https://github.com/topcoder-archive/tc-email-service/pull/103) | `master` | Disable inactive deployment |
| `topcoder-platform/tc-finance-api` | [#216](https://github.com/topcoder-platform/tc-finance-api/pull/216) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/tc-mcp` | [#20](https://github.com/topcoder-platform/tc-mcp/pull/20) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-archive/tc-notifications` | [#259](https://github.com/topcoder-archive/tc-notifications/pull/259) | `master` | Disable inactive deployment |
| `topcoder-archive/tc-smtp-service` | [#2](https://github.com/topcoder-archive/tc-smtp-service/pull/2) | `master` | Disable inactive deployment |
| `topcoder-archive/terms-receiver` | [#23](https://github.com/topcoder-archive/terms-receiver/pull/23) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-archive/terms-service` | [#115](https://github.com/topcoder-archive/terms-service/pull/115) | `master` | Scoped OIDC; no deployment parameter reads |
| `topcoder-platform/timeline-wall-api` | [#45](https://github.com/topcoder-platform/timeline-wall-api/pull/45) | `master` | Scoped OIDC; no deployment parameter reads |

## ECS service mapping

Counts are observations from the read-only inventory, not changes proposed by the PRs.

| Cluster / service | Desired | Repository / PR | Treatment |
| --- | ---: | --- | --- |
| `Clickstream-Ingestion-s3-df7e8666e6fd4b4caf-IngestionServerC0100NestedStackIngestionSe-ATYAZ2YUX48O-IngestionServerclickstreamingestionserviceecscluster02FAD1F6-qJc4FY5MoXzU` / `Clickstream-Ingestion-s3-df7e8666e6fd4b4caf-IngestionServerC0100NestedStackIngestionSe-ATYAZ2YUX48O-FargateService-QQD6wsdZtZv4` | 1 | Not mapped to the shared deployment suite | See exclusions below |
| `Conduktor-Prod` / `console` | 1 | Not mapped to the shared deployment suite | See exclusions below |
| `av-scanner-service-serverless` / `av-scanner-v6` | 1 | [av-scanner-v6 #13](https://github.com/topcoder-platform/av-scanner-v6/pull/13) | OIDC migration |
| `av-scanner-service-serverless` / `file-scanning-processor-svc` | 0 | [submission-scanner-processor #81](https://github.com/topcoder-archive/submission-scanner-processor/pull/81) | Disable inactive legacy deployment |
| `community-app-serverless` / `community-app-svc` | 6 | [community-app #7297](https://github.com/topcoder-platform/community-app/pull/7297) | OIDC migration |
| `engagements-api-serverless` / `engagements-api-v6` | 1 | [engagements-api-v6 #98](https://github.com/topcoder-platform/engagements-api-v6/pull/98) | OIDC migration |
| `gravitee-serverless` / `gravitee-apim-gateway-service` | 0 | Not mapped to the shared deployment suite | See exclusions below |
| `gravitee-serverless` / `gravitee-apim-management-api-service` | 0 | Not mapped to the shared deployment suite | See exclusions below |
| `gravitee-serverless` / `gravitee-apim-management-ui-service` | 0 | Not mapped to the shared deployment suite | See exclusions below |
| `groups-api-serverless` / `groups-api-v6` | 1 | [groups-api-v6 #19](https://github.com/topcoder-platform/groups-api-v6/pull/19) | OIDC migration |
| `identity-service-serverless` / `identity-api-v6` | 4 | [identity-api-v6 #58](https://github.com/topcoder-platform/identity-api-v6/pull/58) | OIDC migration |
| `internal-api-serverless` / `leave-api-v6` | 1 | [leave-api-v6 #16](https://github.com/topcoder-platform/leave-api-v6/pull/16) | OIDC migration |
| `internal-api-serverless` / `procurement-api-v6` | 1 | [procurement-api-v6 #8](https://github.com/topcoder-platform/procurement-api-v6/pull/8) | OIDC migration |
| `lookups-serverless` / `lookups-api-v6` | 1 | [lookups-api-v6 #14](https://github.com/topcoder-platform/lookups-api-v6/pull/14) | OIDC migration |
| `member-api-serverless` / `member-api-v6` | 1 | [member-api-v6 #172](https://github.com/topcoder-platform/member-api-v6/pull/172) | OIDC migration |
| `nginx-supply-serverless` / `nginx-supply-svc` | 4 | [docker-nginx-supply #193](https://github.com/topcoder-platform/docker-nginx-supply/pull/193) | OIDC migration |
| `standardized-skills-serverless` / `standardized-skills-api` | 1 | [standardized-skills-api #141](https://github.com/topcoder-platform/standardized-skills-api/pull/141) | OIDC migration |
| `standardized-skills-serverless` / `standardized-skills-processor` | 1 | [standardized-skills-processor #17](https://github.com/topcoder-platform/standardized-skills-processor/pull/17) | OIDC migration |
| `tc-ai` / `tc-ai-api` | 1 | [tc-ai-api #93](https://github.com/topcoder-platform/tc-ai-api/pull/93) | OIDC migration |
| `tc-ai` / `tc-mcp` | 0 | [tc-mcp #20](https://github.com/topcoder-platform/tc-mcp/pull/20) | OIDC migration; remains inactive |
| `tc-autopilot-serverless` / `autopilot-v6` | 1 | [autopilot-v6 #75](https://github.com/topcoder-platform/autopilot-v6/pull/75) | OIDC migration |
| `tc-billing-account-serverless` / `billing-accounts-api-v6` | 1 | [billing-accounts-api-v6 #35](https://github.com/topcoder-platform/billing-accounts-api-v6/pull/35) | OIDC migration |
| `tc-billing-account-serverless` / `project-billing-account-update-processor` | 1 | [project-billing-account-update-processor #13](https://github.com/topcoder-platform/project-billing-account-update-processor/pull/13) | OIDC migration |
| `tc-bus-api-serverless` / `tc-bus-api-svc` | 0 | [tc-bus-api #77](https://github.com/topcoder-archive/tc-bus-api/pull/77) | Disable inactive legacy deployment |
| `tc-challenge-serverless` / `challenge-api-v6` | 4 | [challenge-api-v6 #178](https://github.com/topcoder-platform/challenge-api-v6/pull/178) | OIDC migration |
| `tc-challenge-serverless` / `opportunities-api-v6` | 1 | [opportunities-api-v6 #8](https://github.com/topcoder-platform/opportunities-api-v6/pull/8) | OIDC migration |
| `tc-challenge-serverless` / `resources-api-v6` | 3 | [resource-api-v6 #38](https://github.com/topcoder-platform/resource-api-v6/pull/38) | OIDC migration |
| `tc-discord-bot-serverless` / `tc-discord-bot` | 1 | [tc-discord-bot #29](https://github.com/topcoder-platform/tc-discord-bot/pull/29) | OIDC migration |
| `tc-docker-daemon` / `tc-docker-daemon` | 1 | Not mapped to the shared deployment suite | See exclusions below |
| `tc-email-service-serverless` / `tc-email-service-svc` | 0 | [tc-email-service #103](https://github.com/topcoder-archive/tc-email-service/pull/103) | Disable inactive legacy deployment |
| `tc-finance-serverless` / `finance-api-v6` | 1 | [tc-finance-api #216](https://github.com/topcoder-platform/tc-finance-api/pull/216) | OIDC migration |
| `tc-forums-serverless` / `forums-api-v6` | 1 | [forums-api-v6 #27](https://github.com/topcoder-platform/forums-api-v6/pull/27) | OIDC migration |
| `tc-freecodecamp-serverless` / `freecodecamp-api` | 1 | [freeCodeCamp #113](https://github.com/topcoder-platform/freeCodeCamp/pull/113) | OIDC migration |
| `tc-gamification-serverless` / `tc-gamification` | 1 | [gamification-api #32](https://github.com/topcoder-platform/gamification-api/pull/32) | OIDC migration |
| `tc-gitea` / `tc-gitea` | 1 | Not mapped to the shared deployment suite | See exclusions below |
| `tc-gitea-runner` / `tc-gitea-runner` | 1 | Not mapped to the shared deployment suite | See exclusions below |
| `tc-infra-services` / `infra-inventory` | 1 | [infra-inventory #5](https://github.com/topcoder-platform/infra-inventory/pull/5) | OIDC migration |
| `tc-learning-paths-serverless` / `learning-paths-api` | 1 | [learning-paths-api #270](https://github.com/topcoder-platform/learning-paths-api/pull/270) | OIDC migration |
| `tc-mm-serverless` / `marathon-match-api-v6` | 1 | [marathon-match-api-v6 #459](https://github.com/topcoder-platform/marathon-match-api-v6/pull/459) | OIDC migration |
| `tc-notifications-serverless` / `tc-notifications-api` | 0 | [tc-notifications #259](https://github.com/topcoder-archive/tc-notifications/pull/259) | Disable inactive legacy deployment |
| `tc-notifications-serverless` / `tc-notifications-consumers` | 0 | [tc-notifications #259](https://github.com/topcoder-archive/tc-notifications/pull/259) | Disable inactive legacy deployment |
| `tc-notifications-serverless` / `tc-notifications-general-processor` | 0 | [tc-notifications #259](https://github.com/topcoder-archive/tc-notifications/pull/259) | Disable inactive legacy deployment |
| `tc-ollama` / `tc-ollama` | 0 | Not mapped to the shared deployment suite | See exclusions below |
| `tc-ollama` / `tc-ollama-runner-gpu` | 0 | Not mapped to the shared deployment suite | See exclusions below |
| `tc-project-service-serverless` / `projects-api-v6` | 1 | [projects-api-v6 #62](https://github.com/topcoder-platform/projects-api-v6/pull/62) | OIDC migration |
| `tc-reporting-serverless` / `reports-api-v6` | 1 | [reports-api-v6 #205](https://github.com/topcoder-platform/reports-api-v6/pull/205) | OIDC migration |
| `tc-review-serverless` / `review-api-v6` | 4 | [review-api-v6 #382](https://github.com/topcoder-platform/review-api-v6/pull/382) | OIDC migration |
| `tc-smtp-serverless` / `tc-smtp-service` | 0 | [tc-smtp-service #2](https://github.com/topcoder-archive/tc-smtp-service/pull/2) | Disable inactive legacy deployment |
| `terms-service-serverless` / `terms-receiver` | 1 | [terms-receiver #23](https://github.com/topcoder-archive/terms-receiver/pull/23) | OIDC migration |
| `terms-service-serverless` / `terms-svc` | 1 | [terms-service #115](https://github.com/topcoder-archive/terms-service/pull/115) | OIDC migration |
| `timeline-wall-serverless` / `timeline-wall-api` | 1 | [timeline-wall-api #45](https://github.com/topcoder-platform/timeline-wall-api/pull/45) | OIDC migration |
| `topcoder-infrastructure` / `bus-api-v6` | 1 | [bus-api-v6 #12](https://github.com/topcoder-platform/bus-api-v6/pull/12) | OIDC migration |
| `topcoder-infrastructure` / `email-service-v6` | 1 | [email-service-v6 #10](https://github.com/topcoder-platform/email-service-v6/pull/10) | OIDC migration |
| `topcoder-infrastructure` / `forms-api-v6` | 1 | [forms-api-v6 #17](https://github.com/topcoder-platform/forms-api-v6/pull/17) | OIDC migration |
| `topcoder-infrastructure` / `forms-processor-v6` | 1 | [forms-processor-v6 #12](https://github.com/topcoder-platform/forms-processor-v6/pull/12) | OIDC migration |
| `topcoder-infrastructure` / `payload-cms` | 1 | [payload-cms #50](https://github.com/topcoder-platform/payload-cms/pull/50) | OIDC migration |
| `topcoder-infrastructure` / `status-api-v6` | 1 | [status-api-v6 #10](https://github.com/topcoder-platform/status-api-v6/pull/10) | OIDC migration |
| `topcoder-infrastructure` / `support-api-v6` | 1 | [support-api-v6 #22](https://github.com/topcoder-platform/support-api-v6/pull/22) | OIDC migration |

## Services without a mapped shared-script release path

- **Clickstream ingestion:** nested AWS solution service with proxy/worker images; no matching shared-script repository found in source search.
- **Conduktor console:** vendor console/monitoring images; accessible code search found application references but no Conduktor shared-script release pipeline.
- **Gitea:** no source-management deployment tag or matching release repository found.
- **Docker daemon / Gitea runner / two Ollama services:** source tags point to tc-mcp, but the inspected tc-mcp CircleCI workflow releases only APPNAME tc-mcp. Its PR does not update these separate services. Two Ollama services were inactive.
- **Three Gravitee services:** inactive vendor services; source metadata links an operations installation document, not a shared-script application release repository.

These exclusions require owner confirmation if a separate legacy pipeline exists; no credentials or configuration were guessed for them. Searches cover accessible indexed source, not every private/unindexed job.

## Validation evidence

- 61 shared offline tests pass locally and inside the pinned deployment executor, including exact legacy dev/prod branch trust and the ECS service-argument regression.
- All 46 consumer CircleCI configurations validate. IAM Access Analyzer reports no permission-policy errors/security warnings for the reviewed role policies; trust policies have only the single-valued audience reminder. CloudFormation role templates validate; private UUID templates still require actual identities before installation.
- Forms API: 14 deployment tests; AV Scanner: six adapter tests; Payload and Status: four OIDC-wrapper tests each; Payload: 52 deployment/operator tests.
- Project-billing processor: formatting, lint, typecheck, 17 tests and compilation. Standardized-skills processor: async readiness regression, compilation and lint.
- Lookups: clean-source image build and non-root dependency smoke. ClamAV: non-root image build, PONG, clean-file scan and process-exit check. Nginx: image build and non-root health check using local mappings for its private DNS names (not a production routing test).
- freeCodeCamp: complete API image build, ten API/compatibility security tests, and non-root runtime-config smoke verifying no baked .env/build-fixture config and no private fields in generated public JSON. Community App: eight focused security tests.

These checks do not replace image scanning in the configured ECR repositories, full application builds for every repository, real OIDC trust tests or dev integration/rollback acceptance.

## Auth0 broker endpoint and AWS permission flow

The configured HTTP endpoint is the runtime value of **CI_AUTH0_URL**, which was not available in accessible source or the saved AWS environment files. Production IAM verifies the legacy **oidc-circleci-deploy** role trusts issuer **https://topcoder-newauth.auth0.com/** and an Auth0 client-ID audience. The issuer is not proof of the broker URL or token path.

The old script sends client ID + secret to that configured broker and extracts AWS credentials from custom JWT claims. The client ID identifies the allowed client; the AWS role's IAM policies supply its permissions, including the legacy parameter/decryption grants. New deployments use CircleCI OIDC directly with AWS STS and deny direct parameter access. ECS's separately scoped execution role continues fetching runtime secrets when tasks start. See [the detailed authentication explanation](AUTHENTICATION.md).
