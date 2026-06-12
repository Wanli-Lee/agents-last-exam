#!/usr/bin/env bash
# Bootstrap an AWS account for ALE: vmimport role, networking, import bucket.
# Idempotent-ish — safe to re-run; reuses resources tagged project=ale.
#
# Prereqs: aws CLI authenticated (env keys or `aws configure`) as a principal
# that can create IAM roles, VPC resources, and S3 buckets. Run once per region.
#
# Usage:  AWS_REGION=us-east-1 ALE_BUCKET=ale-images-<acct> ./bootstrap_account.sh
# Writes resolved ids to tools/aws/.aws-env (sourced by import_ubuntu_ami.sh).
set -euo pipefail

REGION="${AWS_REGION:?set AWS_REGION (e.g. us-east-1)}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="${ALE_BUCKET:-ale-images-${ACCOUNT}}"
OUT="$(dirname "$0")/.aws-env"
TAG='project=ale'
say() { printf '\n=== %s ===\n' "$*"; }

say "account=${ACCOUNT} region=${REGION} bucket=${BUCKET}"

# ---- import bucket ---------------------------------------------------------
say "S3 import bucket"
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  if [ "$REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION"
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration "LocationConstraint=${REGION}"
  fi
fi
echo "bucket: $BUCKET"

# ---- vmimport service role -------------------------------------------------
say "vmimport role"
if ! aws iam get-role --role-name vmimport >/dev/null 2>&1; then
  TRUST=$(mktemp); POL=$(mktemp)
  cat > "$TRUST" <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Principal":{"Service":"vmie.amazonaws.com"},"Action":"sts:AssumeRole",
 "Condition":{"StringEquals":{"sts:Externalid":"vmimport"}}}]}
JSON
  cat > "$POL" <<JSON
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:GetBucketLocation","s3:GetObject","s3:ListBucket"],
  "Resource":["arn:aws:s3:::${BUCKET}","arn:aws:s3:::${BUCKET}/*"]},
 {"Effect":"Allow","Action":["ec2:ModifySnapshotAttribute","ec2:CopySnapshot",
  "ec2:RegisterImage","ec2:Describe*"],"Resource":"*"}]}
JSON
  aws iam create-role --role-name vmimport \
    --assume-role-policy-document "file://$TRUST" \
    --description "VM Import/Export service role for ALE"
  aws iam put-role-policy --role-name vmimport --policy-name vmimport \
    --policy-document "file://$POL"
  rm -f "$TRUST" "$POL"
else
  echo "vmimport role exists (ensure its policy lists bucket ${BUCKET})"
fi

# ---- networking: VPC / subnet / IGW / route / SG ---------------------------
say "VPC + subnet + internet gateway"
VPC=$(aws ec2 describe-vpcs --region "$REGION" \
  --filters "Name=tag:project,Values=ale" \
  --query 'Vpcs[0].VpcId' --output text 2>/dev/null || echo None)
if [ "$VPC" = "None" ] || [ -z "$VPC" ]; then
  VPC=$(aws ec2 create-vpc --region "$REGION" --cidr-block 10.0.0.0/16 \
    --tag-specifications "ResourceType=vpc,Tags=[{Key=project,Value=ale}]" \
    --query Vpc.VpcId --output text)
  aws ec2 modify-vpc-attribute --region "$REGION" --vpc-id "$VPC" --enable-dns-hostnames
fi

SUBNET=$(aws ec2 describe-subnets --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC" "Name=tag:project,Values=ale" \
  --query 'Subnets[0].SubnetId' --output text 2>/dev/null || echo None)
if [ "$SUBNET" = "None" ] || [ -z "$SUBNET" ]; then
  SUBNET=$(aws ec2 create-subnet --region "$REGION" --vpc-id "$VPC" \
    --cidr-block 10.0.1.0/24 \
    --tag-specifications "ResourceType=subnet,Tags=[{Key=project,Value=ale}]" \
    --query Subnet.SubnetId --output text)
fi
aws ec2 modify-subnet-attribute --region "$REGION" --subnet-id "$SUBNET" \
  --map-public-ip-on-launch

IGW=$(aws ec2 describe-internet-gateways --region "$REGION" \
  --filters "Name=attachment.vpc-id,Values=$VPC" \
  --query 'InternetGateways[0].InternetGatewayId' --output text 2>/dev/null || echo None)
if [ "$IGW" = "None" ] || [ -z "$IGW" ]; then
  IGW=$(aws ec2 create-internet-gateway --region "$REGION" \
    --tag-specifications "ResourceType=internet-gateway,Tags=[{Key=project,Value=ale}]" \
    --query InternetGateway.InternetGatewayId --output text)
  aws ec2 attach-internet-gateway --region "$REGION" \
    --internet-gateway-id "$IGW" --vpc-id "$VPC"
fi

RT=$(aws ec2 describe-route-tables --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC" "Name=association.main,Values=true" \
  --query 'RouteTables[0].RouteTableId' --output text)
aws ec2 create-route --region "$REGION" --route-table-id "$RT" \
  --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW" 2>/dev/null || true
aws ec2 associate-route-table --region "$REGION" \
  --route-table-id "$RT" --subnet-id "$SUBNET" 2>/dev/null || true

say "security group (ingress tcp:5000 cua, tcp:3389 RDP)"
SG=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters "Name=vpc-id,Values=$VPC" "Name=group-name,Values=ale-sandbox" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo None)
if [ "$SG" = "None" ] || [ -z "$SG" ]; then
  SG=$(aws ec2 create-security-group --region "$REGION" \
    --group-name ale-sandbox --description "ALE cua-server ingress" \
    --vpc-id "$VPC" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG" \
    --protocol tcp --port 5000 --cidr 0.0.0.0/0
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG" \
    --protocol tcp --port 3389 --cidr 0.0.0.0/0
fi

cat > "$OUT" <<ENV
# generated by bootstrap_account.sh — source before import / runs
export AWS_REGION=${REGION}
export ALE_AWS_ACCOUNT=${ACCOUNT}
export ALE_BUCKET=${BUCKET}
export ALE_AWS_VPC=${VPC}
export ALE_AWS_SUBNET=${SUBNET}
export ALE_AWS_SG=${SG}
ENV

say "DONE — wrote $OUT"
cat "$OUT"
