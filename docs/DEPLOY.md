# Deploying to AWS

One CloudFormation stack (`infra/stack.yaml`) and three scripts. Validated with `cfn-lint`; the
production image is built and smoke-tested locally for `linux/amd64`. It has not been deployed
from this repository yet, so expect to fix small things on the first real run.

## What gets created

```
Internet ──HTTPS──▶ CloudFront ──HTTP──▶ ALB (only CloudFront can reach it)
                                            │
                                            ▼
                               ECS Fargate task (1 × 0.5 vCPU, 1 GB)
                               runs migrations, then the API + review page
                                            │
                                            ▼
                               RDS PostgreSQL 17.11 (db.t4g.micro, private, encrypted)

EventBridge ──X-API-Key──▶ /v1/advisories/sync?wait=false   every 30 minutes
                         ▶ /v1/digests/send                 daily 08:00 UTC
                         ▶ /v1/maintenance/purge            daily 03:00 UTC (GDPR retention)

Secrets Manager: DB password (managed by RDS), operator key, Anthropic key
CloudWatch Logs: 14-day retention, ids only (no names, emails or message text)
```

- **Why ECS and not App Runner:** the brief allowed either, but App Runner closed to new
  customers on 30 April 2026, so it's not an option for a new account.
- **Why CloudFront:** it gives HTTPS on a `*.cloudfront.net` address without buying a domain
  or managing a certificate. The ALB only accepts traffic from CloudFront's address range.
- **No NAT gateway:** tasks run in the default VPC's public subnets with a public IP (needed to
  pull the image and fetch the feeds). The security group still only admits the ALB.

## Cost

Roughly **$55–70 per month** while running (estimate from list prices; check the AWS pricing
calculator for your region): load balancer ~$18, Fargate task (0.5 vCPU, 1 GB) ~$18,
RDS db.t4g.micro with 20 GB ~$14, public IPv4 addresses (ALB + task, ~3) ~$11, plus a little
for Secrets Manager and logs. CloudFront and EventBridge stay within free tiers at demo
traffic. Model calls are billed separately by Anthropic. **Tear it down after recording the
demo** (a few days running costs a few dollars).

## Prerequisites

1. An AWS account, and the AWS CLI logged in (`aws configure` or `aws sso login`).
   Check with `aws sts get-caller-identity`.
2. Docker running (the script builds and pushes the image).
3. Optional: for email, verify a sender address in **Amazon SES** in the same region. New
   accounts are in the SES sandbox and can only send to verified addresses; request production
   access early if real travellers should receive email (approval can take a day or more).

## Deploy

```bash
export AWS_REGION=eu-west-1
export OPERATOR_API_KEY=$(openssl rand -hex 24)   # save this somewhere safe
export ANTHROPIC_API_KEY=sk-ant-...               # optional: empty runs the heuristic baseline
export SES_FROM_EMAIL=alerts@example.com          # optional: a verified SES identity
./infra/deploy.sh
```

The first deploy takes about 15 minutes (RDS and CloudFront are slow to create). The script
prints the HTTPS URL at the end.

## After deploying

```bash
URL=https://dxxxxxxxx.cloudfront.net
curl $URL/health
curl -X POST -H "X-API-Key: $OPERATOR_API_KEY" "$URL/v1/advisories/sync?wait=false"

./infra/run-task.sh seed-demo                 # demo organisation; key is printed in the logs
aws logs tail <LogGroupName> --region $AWS_REGION --follow
```

Then open `$URL/ui` and sign in with the organisation's API key.

## Updating

Run `./infra/deploy.sh` again. It builds a new image tagged with the git commit and rolls the
service. Migrations run when the new task starts.

## Tear down

```bash
./infra/teardown.sh
```

RDS keeps a final snapshot (it costs a little per GB-month); delete it under
RDS > Snapshots if you don't need it.
