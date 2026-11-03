# How Auth0 provided AWS access in v1

The old helper:

1. Read `CI_AUTH0_URL`, `CI_AUTH0_CLIENTID`, `CI_AUTH0_CLIENTSECRET` and `CI_AUTH0_AUDIENCE` from the job environment.
2. POSTed a client-credentials request to that URL, with requested environment, organization/repository, branch and build number as caller-supplied strings.
3. Took `access_token`, base64-decoded its JWT payload, and extracted claims matching `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, `AWS_SESSION_TOKEN`, `AWS_ENVIRONMENT`, and `AWS_ACCOUNT_ID`.
4. Wrote the AWS keys to the default CLI configuration and `awsenvconf`. Later scripts called AWS, including SSM reads/decryption, under that identity.

The **client ID identifies the client; it does not grant AWS permissions**. The client secret authenticated the caller to the configured endpoint. The audience selected the intended API. Returning AWS credentials inside JWT claims is custom broker behavior, not a standard Auth0 feature that automatically assigns AWS permissions.

Effective AWS access comes from the IAM identity behind the returned keys, its identity/session policies, boundaries, resource policies and organization controls. A stolen reusable broker secret may obtain fresh AWS sessions after earlier sessions expire. Rotating the client ID alone does not address this.

The server-side broker/Action implementation was not in this repository or found in accessible source search. This PR therefore does not assert which role it assumes, how long credentials last, or whether it independently enforces project/environment/branch authorization. Caller-supplied metadata is not proof of authorization. The old helper also disabled TLS verification and did not cryptographically verify the returned JWT.

The incident owner must locate the configured endpoint and associated Auth0 application/API, inspect broker/Actions, client grants, issuance logs, AWS principal and CloudTrail. Use restricted administrative tooling; never put JWTs/client secrets/AWS keys in a PR. Rotate exposed broker secrets/keys, revoke affected sessions, and retire the old broker's deployment grants after migration. This PR cannot invalidate credentials or change another service's policies.

## v2: CircleCI to STS directly

CircleCI issues an OIDC v3 token. AWS STS verifies it against the OIDC provider and role trust policy. The generated trust binds organization, project, checkout repository/ref **and configuration repository/ref**. Dev/prod use distinct roles/accounts/manifests. There is no Auth0 broker exchange, custom JWT credential envelope, or static AWS fallback.

The deployer requests a one-hour session, attaches a restrictive session policy, and verifies the returned account/assumed-role identity. Both the generated IAM role policy and session policy explicitly deny `ssm:*`, `secretsmanager:*`, `kms:Decrypt` and role chaining. Other permissions cover only required ECS/ECR operations and passing the two exact runtime roles. **The deny must be installed in IAM**: a hostile client could omit an optional session policy. Local code is not the durable authorization boundary.

Non-secret targets live in reviewed JSON. Runtime parameter names/ARNs stay in the existing task definition. No deploy-time listing, fetching, decryption, shell export or parameter write occurs.

The **task execution role** lets the ECS agent retrieve the service's allowed secret values when launching tasks. The **task role** grants the application's runtime permissions. Both differ from the **deployment role**. Give secret reads to the execution role unless application code explicitly needs to retrieve them itself; restrict exact parameter/secret ARNs and KMS keys, not a broad shared `/config` tree.

A deployer that can ship arbitrary application code can still ship code that reads/exfiltrates secrets injected into the app. Removing direct SSM access reduces exposure but cannot eliminate this inherent power. Protect source/config branches, require reviewed releases, restrict contexts and image/artifact writers, and narrow each execution role. Splitting jobs alone does not make malicious protected-branch code trustworthy or prove it cannot obtain OIDC credentials.

AWS currently requires `Resource: "*"` for `DescribeTaskDefinition`. This exposes task metadata, including any legacy plaintext environment secrets in other definitions in the account. Move those values to runtime secret references. v2 rejects secret-like plaintext fields in the task it promotes.

## Primary references

- [CircleCI OIDC v3 and trust conditions](https://circleci.com/docs/guides/permissions-authentication/openid-connect-tokens/)
- [STS web identity and session policy intersection](https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRoleWithWebIdentity.html)
- [ECS execution roles and secrets](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_execution_IAM_role.html)
- [ECS action/resource authorization](https://docs.aws.amazon.com/service-authorization/latest/reference/list_ecs.html)
- [Revoke AWS role sessions](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_use_revoke-sessions.html)
