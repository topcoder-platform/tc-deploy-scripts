#!/bin/bash
usage()
{
cat << EOF
usage: $0 options

This script needs to be executed with below options.

OPTIONS:
 -e environment
 -b security file location GIT|AWS

EOF
}
#log Function - Used to provide information of execution information with date and time
log()
{
   echo "`date +'%D %T'` : $1"
}
track_error()
{
   if [ $1 != "0" ]; then
        log "$2 exited with error code $1"
        log "completed execution IN ERROR at `date`"
        exit $1
   fi

}
download_buildenvfile()
{
    Buffer_seclist=$(echo $BUILDENV_LIST | sed 's/,/ /g' )
    for listname in $Buffer_seclist;
    do
        aws s3 cp s3://tc-platform-${ENV_CONFIG}/securitymanager/$listname.json .
        track_error $? "Environment setting"
	jq 'keys[]' $listname.json
        track_error $? "$listname.json"
    done
}

download_psfile()
{
    Buffer_seclist=$(echo $SECPS_LIST | sed 's/,/ /g' )
    for listname in $Buffer_seclist;
    do
        aws s3 cp s3://tc-platform-${ENV_CONFIG}/securitymanager/$listname.json .
	    track_error $? "$listname.json download"
        jq 'keys[]' $listname.json
        track_error $? "$listname.json"
    done
}

uploading_buildenvvar()
{
    Buffer_seclist=$(echo $BUILDENV_LIST | sed 's/,/ /g')
    for listname in $Buffer_seclist;
    do
        o=$IFS
        IFS=$(echo -en "\n\b")
        envvars=$( cat $listname.json  | jq  -r ' . ' | jq ' . | to_entries[] | { "name": .key , "value": .value } ' | jq -s . )
        for s in $(echo $envvars | jq -c ".[]" ); do
        #echo $envvars
            varname=$(echo $s| jq -r ".name")
            varvalue=$(echo $s| jq -r ".value")
            echo $varname
            echo export "$varname"="'$varvalue'" >>"buildenvvar"
	        #export "$varname"="$varvalue"
            #echo export "$varname"="$varvalue" >>"$BASH_ENV"
            #echo export "$varname"="\"$varvalue\"" >> ~/.circlerc
        done
        IFS=$o 
    done
}

uploading_buildpsenvar()
{
    if [ -z $SECPS_LIST ];
    then
        log "No ps file provided"
    else
        Buffer_seclist=$(echo $SECPS_LIST | sed 's/,/ /g')
        for listname in $Buffer_seclist;
        do
            local o=$IFS
            IFS=$(echo -en "\n\b")
            varpath=$( cat $listname.json | jq  -r ' .ParmeterPathList[] ' )
            #log "vars are fetched"
            for k in $varpath;
            do
                echo $k
                aws ssm get-parameters-by-path --with-decryption --path $k --query "Parameters[*].{Name:Name, Value:Value}" > paramnames.json
                ###paramnames=$(cat paramnames.json | jq -r .[].Name | rev | cut -d / -f 1 | rev)
                for s in $(cat paramnames.json | jq -c .[] )
                do
                    varname=$(echo $s | jq -r .Name | rev | cut -d / -f 1 | rev)
                    varvalue=$(echo $s | jq -r .Value)
                    #varvalue="arn:aws:ssm:$AWS_REGION:$AWS_ACCOUNT_ID:parameter$s"
                    echo export "$varname"="'$varvalue'" >>"buildenvvar"
                    #echo "$varname" "$varvalue"
                done
            done
            IFS=$o  
        done
    fi
}

configure_aws_cli() {
	aws --version
	aws configure set aws_access_key_id $AWS_ACCESS_KEY_ID
	aws configure set aws_secret_access_key $AWS_SECRET_ACCESS_KEY
	aws configure set default.region $AWS_REGION
	aws configure set default.output json
	log "Configured AWS CLI."
}

while getopts .b:e:l:. OPTION
do
     case $OPTION in
         e)
             ENV=$OPTARG
             ;;
         b)
             BUILDENV_LIST=$OPTARG
             ;;
         l)
             SECPS_LIST=$OPTARG
             ;;
         ?)
             log "additional param required"
             usage
             exit
             ;;
     esac
done

# AWS_ACCESS_KEY_ID=$(eval "echo \$${ENV}_AWS_ACCESS_KEY_ID")
# AWS_SECRET_ACCESS_KEY=$(eval "echo \$${ENV}_AWS_SECRET_ACCESS_KEY")
# AWS_REGION=$(eval "echo \$${ENV}_AWS_REGION")
# if [ -z $AWS_REGION ];
# then
# AWS_REGION="us-east-1"
# fi
# if [ -z $AWS_ACCESS_KEY_ID ] || [ -z $AWS_SECRET_ACCESS_KEY ] ;
# then
#      log "AWS Secret Parameters are not configured in circleci/environment"
#      usage
#      exit 1
# else
#      configure_aws_cli
# fi
ENV_CONFIG=`echo "$ENV" | tr '[:upper:]' '[:lower:]'`
download_buildenvfile
uploading_buildenvvar
download_psfile
uploading_buildpsenvar

if grep -Fxq "buildenvvar" .dockerignore
then
    log "buildenvvar exist in docker ignore file list"
else
    echo "buildenvvar" >> .dockerignore
fi
