#!/usr/bin/env bash
# Run a one-off CLI command (create-org, seed-demo, simulate-advisory ...) in the deployed
# container. Output appears in the CloudWatch log group printed at the end.
#   ./infra/run-task.sh seed-demo
set -euo pipefail
STACK=${STACK:-travel-risk-agent}
REGION=${AWS_REGION:?set AWS_REGION}
out() { aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK" \
          --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text; }
CMD=$(python3 -c 'import json,sys; print(json.dumps(["uv","run","--no-sync","travel-risk",*sys.argv[1:]]))' "$@")
aws ecs run-task --region "$REGION" --cluster "$(out ClusterName)" --launch-type FARGATE \
  --task-definition "$(out TaskDefinitionArn)" \
  --network-configuration "awsvpcConfiguration={subnets=[$(out SubnetIds)],securityGroups=[$(out ServiceSecurityGroupId)],assignPublicIp=ENABLED}" \
  --overrides "{\"containerOverrides\":[{\"name\":\"api\",\"command\":$CMD}]}" \
  --query 'tasks[0].taskArn' --output text
echo "Logs: aws logs tail $(out LogGroupName) --region $REGION --follow"
