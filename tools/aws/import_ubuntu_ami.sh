#!/usr/bin/env bash
# Stream the ale-ubuntu22 GCE export (raw disk) from GCS into S3, then import
# it as an EC2 AMI via VM Import/Export.
#
# Why raw (not vmdk/qcow2): the exported VMDK is monolithicSparse and qcow2 is
# unsupported by AWS VM Import; only stream-optimized VMDK / raw / VHD work. The
# GCE default `.tar.gz` export is `disk.raw` gzipped in a tar, so we extract it
# on the fly and upload the raw disk.
#
# The pipe gsutil->tar->aws streams through this host's network with NO full
# local staging (disk is tight). multipart_chunksize is raised so a ~300GB
# stdin upload stays under the 10000-part S3 limit without knowing the size.
#
# Prereqs: source tools/aws/.aws-env (from bootstrap_account.sh); gsutil auth'd
# for gs://ale-data-public; aws CLI auth'd with ec2:ImportImage + iam:PassRole
# on role/vmimport + S3 write to $ALE_BUCKET.
set -euo pipefail
HERE="$(dirname "$0")"
# shellcheck disable=SC1091
source "${HERE}/.aws-env"

SRC="${ALE_IMAGE_SRC:-gs://ale-data-public/images/ale-ubuntu22.tar.gz}"
LOCAL_TARGZ="${ALE_LOCAL_TARGZ:-}"   # if set + exists, extract from here (robust)
KEY="images/ale-ubuntu22.raw"
S3URI="s3://${ALE_BUCKET}/${KEY}"
say() { printf '\n=== %s ===\n' "$*"; }

say "extract disk.raw -> ${S3URI}  (gunzip+untar -> S3 multipart, no local raw)"
if aws s3 ls "$S3URI" >/dev/null 2>&1; then
  echo "raw disk already in S3, skipping transfer"
else
  aws configure set default.s3.multipart_chunksize 512MB
  aws configure set default.s3.max_concurrent_requests 16
  # -xzO: extract member(s) to stdout. The GCE tarball holds a single disk.raw
  # (644 GB uncompressed). --expected-size keeps multipart under 10000 parts.
  if [ -n "$LOCAL_TARGZ" ] && [ -f "$LOCAL_TARGZ" ]; then
    echo "source: local $LOCAL_TARGZ"
    tar -xzO -f "$LOCAL_TARGZ" | aws s3 cp - "$S3URI" --expected-size 700000000000
  else
    echo "source: stream $SRC"
    gsutil cat "$SRC" | tar -xzO | aws s3 cp - "$S3URI" --expected-size 700000000000
  fi
fi

say "start import-image (Format=raw, Linux x86_64)"
CONT=$(mktemp)
cat > "$CONT" <<JSON
[{"Description":"ALE ubuntu22 (from GCE export)","Format":"raw",
  "UserBucket":{"S3Bucket":"${ALE_BUCKET}","S3Key":"${KEY}"}}]
JSON
# boot-mode: the GCE disk is GPT with an EFI System Partition (verified), so
# import as uefi. import-image accepts only legacy-bios|uefi (NOT uefi-preferred,
# which is a run/register-image value).
TASK=$(aws ec2 import-image --region "$AWS_REGION" \
  --description "ALE ubuntu22" --platform Linux --architecture x86_64 \
  --boot-mode uefi \
  --disk-containers "file://$CONT" \
  --query ImportTaskId --output text)
rm -f "$CONT"
echo "import task: $TASK"

say "poll until completed (this takes ~1.5-4h for ~300GB)"
while :; do
  read -r STATUS PROGRESS MSG IMAGE < <(aws ec2 describe-import-image-tasks \
    --region "$AWS_REGION" --import-task-ids "$TASK" \
    --query 'ImportImageTasks[0].[Status,Progress,StatusMessage,ImageId]' \
    --output text)
  printf '%s  status=%s progress=%s  %s\n' "$(date +%H:%M:%S)" \
    "$STATUS" "${PROGRESS:-?}" "${MSG:-}"
  case "$STATUS" in
    completed) echo "AMI: $IMAGE"; echo "$IMAGE" > "${HERE}/.ubuntu-ami"; break ;;
    deleted|*[Ee]rror*) echo "import FAILED: $MSG"; exit 1 ;;
  esac
  sleep 60
done

say "DONE — set ALE_AWS_UBUNTU_AMI=$(cat "${HERE}/.ubuntu-ami") for runs"
