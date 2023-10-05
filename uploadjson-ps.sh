#!/bin/bash
set -eo pipefail
UPLOAD_FILENAME=$1
PARAMETER_PATH=$2

cat $UPLOAD_FILENAME  | jq  -r ' . ' | jq --arg PARAMETER_PATH $PARAMETER_PATH ' . | to_entries[] | { "Name": ($PARAMETER_PATH+"/"+.key) , "Value": .value, "Type" : "SecureString" } ' | jq -s . >upload_object.json
o=$IFS
IFS=$(echo -en "\n\b")

for s in $(cat upload_object.json | jq -c .[] )
do
    echo $s>cli-input.json
    aws ssm put-parameter --cli-input-json file://cli-input.json
done
IFS=$o  

[ -f upload_object.json ] && rm -f upload_object.json
[ -f cli-input.json ] && rm -f cli-input.json
