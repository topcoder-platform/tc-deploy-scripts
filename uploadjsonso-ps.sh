#!/bin/bash
set -eo pipefail
UPLOAD_FILENAME=$1
PARAMETER_PATH=$2

aws ssm put-parameter \
    --name $PARAMETER_PATH \
    --type SecureString \
    --value file://$UPLOAD_FILENAME