#!/bin/bash
set -eo pipefail

TAG=$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$AWS_REPOSITORY_APP:$BUILD_NUMBER

sed -i='' "s|challenge-recommender:latest|$TAG|" docker-compose.yml
# docker-compose build
docker-compose build --build-arg AWS_DYNAMODB_URL=${AWS_DYNAMODB_URL} --build-arg AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION} --build-arg ENV_MEMBER_SKILLS_EXTRACTOR_BASE_URL=${ENV_MEMBER_SKILLS_EXTRACTOR_BASE_URL} --build-arg ENV_CHALLENGE_TOOL_BASE_URL=${ENV_CHALLENGE_TOOL_BASE_URL} --build-arg ENV_TAGGING_API_BASE_URL=${ENV_TAGGING_API_BASE_URL} --build-arg ENV_CHALLENGE_BASE_URL=${ENV_CHALLENGE_BASE_URL} --build-arg ENV_AUTH0_URL=${ENV_AUTH0_URL} --build-arg ENV_AUTH0_AUDIENCE=${ENV_AUTH0_AUDIENCE} --build-arg ENV_AUTH0_CLIENT_ID=${ENV_AUTH0_CLIENT_ID} --build-arg ENV_AUTH0_CLIENT_SECRET=${ENV_AUTH0_CLIENT_SECRET} --build-arg ENV_AUTH0_PROXY_SERVER_URL=${ENV_AUTH0_PROXY_SERVER_URL} --build-arg ENV_BUSAPI_URL=${ENV_BUSAPI_URL}

# eval $(aws ecr get-login --region $AWS_REGION --no-include-email)
# docker push $TAG

# ecs-cli configure --region $AWS_REGION --cluster $AWS_ECS_CLUSTER
# ecs-cli compose --project-name $AWS_ECS_SERVICE service up
