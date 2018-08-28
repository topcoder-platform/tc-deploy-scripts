#!/bin/bash

download_buildenvfile()
{
    Buffer_seclist=$(echo $BUILDENV_LIST | sed 's/,/ /g' )
    for listname in $Buffer_seclist;
    do
        aws s3 cp s3://tc-platform-${ENV_CONFIG}/securitymanager/$listname.json .
    done
}
uploading_buildenvvar()
{
    Buffer_seclist=$(echo $BUILDENV_LIST | sed 's/,/ /g')
    for listname in $Buffer_seclist;
    do
        o=$IFS
        IFS=$(echo -en "\n\b")
        envvars=$( cat $listname.json  | jq  -r ' .circlecibuildvar ' | jq ' . | to_entries[] | { "name": .key , "value": .value } ' | jq -s . )
        for s in $(echo $envvars | jq -c ".[]" ); do
        #echo $envvars
            varname=$(echo $s| jq -r ".name")
            varvalue=$(echo $s| jq -r ".value")
            export "$varname"="$varvalue" >"$BASH_ENV"
        done
        IFS=$o 
    done
}

configure_aws_cli() {
	aws --version
	aws configure set aws_access_key_id $AWS_ACCESS_KEY_ID
	aws configure set aws_secret_access_key $AWS_SECRET_ACCESS_KEY
	aws configure set default.region $AWS_REGION
	aws configure set default.output json
	log "Configured AWS CLI."
}

while getopts .b:. OPTION
do
     case $OPTION in
         b)
             BUILDENV_LIST=$OPTARG
             ;;

         ?)
             log "additional param required"
             usage
             exit
             ;;
     esac
done

AWS_ACCESS_KEY_ID=$(eval "echo \$${ENV}_AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY=$(eval "echo \$${ENV}_AWS_SECRET_ACCESS_KEY")
AWS_REGION=$(eval "echo \$${ENV}_AWS_REGION")
if [ -z $AWS_REGION ];
then
AWS_REGION="us-east-1"
fi
if [ -z $AWS_ACCESS_KEY_ID ] || [ -z $AWS_SECRET_ACCESS_KEY ] || [ -z $AWS_ACCOUNT_ID ] || [ -z $AWS_REGION ];
then
     log "AWS Secret Parameters are not configured in circleci/environment"
     usage
     exit 1
else
     configure_aws_cli
fi

configure_aws_cli
download_buildenvfile
uploading_buildenvvar
