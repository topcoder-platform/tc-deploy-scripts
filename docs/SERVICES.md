# Service adoption checklist

All 19 reviewed local v6 services require service-repository/infrastructure adoption. This shared-repository PR does not silently edit or deploy them.

| Services | Current path | Migration considerations |
| --- | --- | --- |
| challenge-api-v6 | Shared v1.4.17 | Remove unused buildvar/CodeArtifact broker steps; use `--dockerfile docker/Dockerfile`; preserve tests/package hygiene |
| resource-api-v6 | Shared v1.4.17 | Existing APPNAME is `resources-api-v6`: verify actual ECS/container names. Remove buildvar/QA parameter reads; isolate QA triggers. Use `docker/Dockerfile` |
| review-api-v6 | Shared v1.4.17 | Remove production reset-db; preserve migrations with separately controlled privileges |
| engagements-api-v6 | Shared v1.4.19 | Separate schema migrations from runtime privileges; remove feature-branch deploy grants |
| forums-api-v6 | Shared v1.4.19 | Pin four remote API client clones; preserve generated Prisma clients |
| groups-api-v6, identity-api-v6 | Shared v1.4.19 | Remove production reset-db capability and feature-branch deploy grants; preserve controlled migrations |
| leave-api-v6, lookups-api-v6, reports-api-v6 | Shared v1.4.19 | Standard single-container migration; clean context, remove tag triggers, add serialization |
| member-api-v6 | Shared v1.4.20 | Use `docker/Dockerfile`; retain non-root/distroless image and only scoped package credentials if necessary |
| forms-api-v6 | Shared v1.4.20 + migration/activation | Preserve one-shot migration/activation gates. Replace production account test with exact account mapping. Bootstrap capacity separately; v2 cannot run migrations or scale from zero |
| marathon-match-api-v6, support-api-v6 | Shared v1.4.21 | Preserve service-specific runtime constraints; remove deployment-variable sourcing |
| av-scanner-v6 | Patched helper + CloudFormation | Preserve two containers/topology. v2 supports multiple images, but do not update ECS behind CloudFormation ownership without an infrastructure migration. Keep stack changes in a separate role. The old helper hardener cannot patch removed v1 code |
| forms-processor-v6 | Helper + Python release | Pre-provision managed secret bindings; remove parameter resolution from deployment; retain healthy-revision checks. Bootstrap separately |
| status-api-v6 | Helper + custom ECS release | Preserve digest, ALB health, rollback, sanitizer and monitoring checks. Basic v2 task health does not replace these gates; adapt OIDC/no-SSM configuration without discarding them |
| terms-service-v6, terms-receiver-v6 | Standalone Python broker deployers | They do not consume this repo today. Remove broker and SSM deployvar/validation reads; add exact account/role checks; preserve audience/scan/rollout gates and provision bindings via infrastructure |

Inspect existing references without decrypting values. Do not drop required runtime settings to pass a no-SSM policy; provision them before launch and let the execution role resolve them. Do not reuse a broad shared execution role as a permission workaround.
