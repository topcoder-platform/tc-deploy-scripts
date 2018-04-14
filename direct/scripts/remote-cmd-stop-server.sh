#!/bin/sh

source ~/.bash_profile

pushd /home/direct/jboss/bin

echo [Kill Jboss]
./kill.sh

popd
