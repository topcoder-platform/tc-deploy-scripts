#!/bin/bash
AWSENV=$1
export AWS_REGION=$2
BASE64_DECODER="base64 -d" # option -d for Linux base64 tool
echo AAAA | base64 -d > /dev/null 2>&1 || BASE64_DECODER="base64 -D" # option -D on MacOS
decode_base64_url() {
  local len=$((${#1} % 4))
  local result="$1"
  if [ $len -eq 2 ]; then result="$1"'=='
  elif [ $len -eq 3 ]; then result="$1"'='
  fi
  echo "$result" | tr '_-' '/+' | $BASE64_DECODER
}

if [ -z "$AWS_REGION" ];
then
    export AWS_REGION="us-east-1"
fi
auth0cmd=$(echo "curl -X POST $CI_AUTH0_URL -H 'Content-Type: application/json' -d '{ \"client_id\": \"$CI_AUTH0_CLIENTID\", \"client_secret\": \"$CI_AUTH0_CLIENTSECRET\", \"audience\": \"$CI_AUTH0_AUDIENCE\", \"grant_type\": \"client_credentials\" , \"environment\" : \"$AWSENV\" , \"username\" : \"$CIRCLE_PROJECT_USERNAME\" , \"reponame\" : \"$CIRCLE_PROJECT_REPONAME\", \"build_num\": \"$CIRCLE_BUILD_NUM\", \"branch\": \"$CIRCLE_BRANCH\"}'")
token=$( eval $auth0cmd | jq -r .access_token )
tokenjsonformat=$( decode_base64_url $(echo -n $token | cut -d "." -f 2) )
export AWS_ACCESS_KEY_ID=$(echo $tokenjsonformat | jq -r . | grep AWS_ACCESS_KEY | cut -d '"' -f 4)
export AWS_SECRET_ACCESS_KEY=$(echo $tokenjsonformat | jq -r . | grep AWS_SECRET_KEY | cut -d '"' -f 4)
export AWS_ENVIRONMENT=$(echo $tokenjsonformat | jq -r . | grep AWS_ENVIRONMENT | cut -d '"' -f 4)
export AWS_SESSION_TOKEN=$(echo $tokenjsonformat | jq -r . | grep AWS_SESSION_TOKEN | cut -d '"' -f 4)
export AWS_ACCOUNT_ID=$(echo $tokenjsonformat | jq -r . | grep AWS_ACCOUNT_ID | cut -d '"' -f 4)
aws configure set default.region $AWS_REGION
aws configure set default.output json
aws configure set aws_access_key_id $AWS_ACCESS_KEY_ID
aws configure set aws_secret_access_key $AWS_SECRET_ACCESS_KEY
aws configure set aws_session_token $AWS_SESSION_TOKEN