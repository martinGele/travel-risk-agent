#!/usr/bin/env bash
# Build the image, push it to ECR and deploy infra/stack.yaml.
#
#   export AWS_REGION=eu-west-1
#   export OPERATOR_API_KEY=$(openssl rand -hex 24)   # keep it: you need it to call the API
#   export ANTHROPIC_API_KEY=sk-ant-...                # optional; empty = heuristic baseline
#   export SES_FROM_EMAIL=alerts@yourdomain.com        # optional; must be verified in SES
#   ./infra/deploy.sh
set -euo pipefail

STACK=${STACK:-travel-risk-agent}
REGION=${AWS_REGION:?set AWS_REGION}
: "${OPERATOR_API_KEY:?set OPERATOR_API_KEY (e.g. openssl rand -hex 24)}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
REPO="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/travel-risk-agent"
TAG=$(git rev-parse --short HEAD)$(git diff --quiet || echo "-dirty")

echo "==> ECR repository"
aws ecr describe-repositories --repository-names travel-risk-agent --region "$REGION" >/dev/null 2>&1 \
  || aws ecr create-repository --repository-name travel-risk-agent --region "$REGION" \
       --image-scanning-configuration scanOnPush=true >/dev/null
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

echo "==> Build and push $REPO:$TAG (linux/amd64)"
docker buildx build --platform linux/amd64 -t "$REPO:$TAG" --push .

echo "==> Default VPC, two public subnets, CloudFront prefix list"
VPC=$(aws ec2 describe-vpcs --region "$REGION" --filters Name=isDefault,Values=true \
        --query 'Vpcs[0].VpcId' --output text)
SUBNETS=$(aws ec2 describe-subnets --region "$REGION" \
            --filters Name=vpc-id,Values="$VPC" Name=default-for-az,Values=true \
            --query 'Subnets[0:2].SubnetId' --output text | tr '\t' ',')
PREFIX=$(aws ec2 describe-managed-prefix-lists --region "$REGION" \
           --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
           --query 'PrefixLists[0].PrefixListId' --output text)

echo "==> Deploy stack $STACK (first run takes ~15 minutes: RDS and CloudFront are slow)"
aws cloudformation deploy --region "$REGION" --stack-name "$STACK" \
  --template-file infra/stack.yaml --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    ImageUri="$REPO:$TAG" VpcId="$VPC" SubnetIds="$SUBNETS" CloudFrontPrefixListId="$PREFIX" \
    OperatorApiKey="$OPERATOR_API_KEY" AnthropicApiKey="${ANTHROPIC_API_KEY:-}" \
    SesFromEmail="${SES_FROM_EMAIL:-}"

URL=$(aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
        --query "Stacks[0].Outputs[?OutputKey=='Url'].OutputValue" --output text)
echo
echo "Deployed: $URL"
echo "  health:  curl $URL/health"
echo "  sync:    curl -X POST -H 'X-API-Key: \$OPERATOR_API_KEY' $URL/v1/advisories/sync?wait=false"
echo "  org:     ./infra/run-task.sh create-org 'Acme' travel@acme.example"
