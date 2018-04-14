#!/bin/bash

source ~/.bash_profile

pushd /home/direct/direct_deploy

echo "Deploying Direct"
ant deploy-prod

popd
