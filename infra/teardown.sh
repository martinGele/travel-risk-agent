#!/usr/bin/env bash
# Delete everything the stack created. RDS keeps a final snapshot (DeletionPolicy: Snapshot);
# delete it in the RDS console if you don't need it. The ECR repository is deleted too.
set -euo pipefail
STACK=${STACK:-travel-risk-agent}
REGION=${AWS_REGION:?set AWS_REGION}
aws cloudformation delete-stack --region "$REGION" --stack-name "$STACK"
aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$STACK"
aws ecr delete-repository --region "$REGION" --repository-name travel-risk-agent --force >/dev/null
echo "Deleted $STACK. Check RDS > Snapshots for the final snapshot."
