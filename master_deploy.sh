#!/bin/bash

#Variable Declaration
JQ="jq --raw-output --exit-status"
DEPLOYMENT_TYPE=""
ENV=""
#BUILD_VARIABLE_FILE_NAME="./openvar.conf"
#BUILD_VARIABLE_FILE_NAME="./openvar_ebs.conf"
BUILD_VARIABLE_FILE_NAME="./buildvar.conf"
SECRET_FILE_NAME="./buildsecvar.conf"


#Common Varibles
AWS_ACCESS_KEY_ID=""
AWS_SECRET_ACCESS_KEY=""
AWS_ACCOUNT_ID=""
AWS_REGION=""
TAG=""
SEC_LOCATION=""

#Varibles specific to ECS
AWS_REPOSITORY=""
AWS_ECS_CLUSTER=""
AWS_ECS_SERVICE=""
AWS_ECS_TASK_FAMILY=""
AWS_ECS_CONTAINER_NAME=""
AWS_ECS_TEMPLATE="container.template"
AWS_ECS_VOLUME_TEMPLATE=""
ECS_TAG=""
REVISION=""
ECS_TEMPLATE_TYPE="CONTAINER"
task_def=""

#variable specific to EBS
EBS_APPLICATION_NAME=""
EBS_APPVER=""
EBS_TAG=""
IMAGE=""
AWS_EBS_APPVER=""
AWS_S3_BUCKET=""
AWS_S3_KEY=""
AWS_EB_ENV=""
EBS_TEMPLATE_FILE_NAME=""
AWS_EBS_EB_DOCKERRUN_TEMPLATE_LOCATION=$(eval "echo \$${ENV}_AWS_EBS_EB_DOCKERRUN_TEMPLATE_LOCATION")
AWS_EBS_DOCKERRUN_TEMPLATE=$(eval "echo \$${ENV}_AWS_EBS_DOCKERRUN_TEMPLATE")
AWS_S3_KEY_LOCATION=""

#variable for cloud front
AWS_S3_BUCKET=""
SOURCE_SYNC_PATH=""
NOCACHE="false"

#FUNCTIONS
#usage Function - provides information like how to execute the script
usage()
{
cat << EOF
usage: $0 options

This script need to be executed with below option.

OPTIONS:
 -h      Show this message
 -d      Deployment Type [ECS|EBS|CFRONT]
 -e      Environment [DEV|QA|PROD]
 -t      ECS Tag Name [mandatatory if ECS ]
 -v      EBS version   [mandatatory if  EBS deployment]
 -c		 cache option true [optional : value = true| false]i
 -s      Security file location GIT|AWS
 -p      ECS template type
EOF
}
#log Function - Used to provide information of execution information with date and time
log()
{
   echo "`date +'%D %T'` : $1"
}
#track_error function validates whether the application execute without any error

track_error()
{
   if [ $1 != "0" ]; then
        log "$2 exited with error code $1"
        log "completed execution IN ERROR at `date`"
        exit $1
   fi

}


#Function for aws login

configure_aws_cli() {
	aws --version
	aws configure set aws_access_key_id $AWS_ACCESS_KEY_ID
	aws configure set aws_secret_access_key $AWS_SECRET_ACCESS_KEY
	aws configure set default.region $AWS_REGION
	aws configure set default.output json
	log "Configured AWS CLI."
}
#Function for private dcoker login
configure_docker_private_login() {
	aws s3 cp "s3://appirio-platform-$ENV_CONFIG/services/common/dockercfg" ~/.dockercfg
}

#ECS Deployment Functions

ECS_push_ecr_image() {
	log "Pushing Docker Image..."
	eval $(aws ecr get-login --region $AWS_REGION --no-include-email)
	docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$AWS_REPOSITORY:$ECS_TAG
	track_error $? "ECS ECR image push"
	log "Docker Image published."
}

ECS_update_register_task_definition() {
   #tag name alone need to be updated
    if [ "$ECS_TEMPLATE_TYPE" = "CONTAINER" ] ;     
    then
      . /$AWS_ECS_TEMPLATE_UPDATE_SCRIPT $ENV $ECS_TAG
      task_def=`cat $AWS_ECS_TASKDEF_FILE`
      echo "updating"
      if REVISION=$(aws ecs register-task-definition --container-definitions "$task_def" --family $AWS_ECS_TASK_FAMILY | $JQ '.taskDefinition.taskDefinitionArn'); then
        log "Revision: $REVISION"
      else
	track_error 1 "Task Def registration"		
        log "Failed to register task definition"
        return 1
      fi
    fi
    if [ "$ECS_TEMPLATE_TYPE" = "CONTAINERVOLUME" ] ;
    then
      . /$AWS_ECS_TEMPLATE_UPDATE_SCRIPT $ENV $ECS_TAG
      task_def=`cat $AWS_ECS_TASKDEF_FILE`
      echo "updating"
      volume_def=`cat $AWS_ECS_VOLUMEDEF_FILE`
      if REVISION=$(aws ecs register-task-definition --container-definitions "$task_def" --volumes "$volume_def" --family $AWS_ECS_TASK_FAMILY | $JQ '.taskDefinition.taskDefinitionArn'); then
        log "Revision: $REVISION"
      else
                track_error 1 "Task Def registration"
        log "Failed to register task definition"
        return 1
      fi      
    fi
    if [ "$ECS_TEMPLATE_TYPE" = "TDJSON" ] ;
    then
      . $AWS_ECS_TEMPLATE_UPDATE_SCRIPT $ENV $ECS_TAG
      #task_def=`cat $AWS_ECS_TASKDEF_FILE`
      if [ -z $task_def ]; then
      then 
         track_error 1 "Task Def has not set by taskdef variable"
      else
        if REVISION=$(aws ecs register-task-definition --cli-input-json "$task_def" | $JQ '.taskDefinition.taskDefinitionArn'); then
          log "Revision: $REVISION"
        else
          track_error 1 "Task Def registration"
          log "Failed to register task definition"
          return 1
        fi
      fi
    fi

}

ECS_deploy_cluster() {

    #ECS_update_register_task_definition
    AWS_ECS_SERVICE=$1
    update_result=$(aws ecs update-service --cluster $AWS_ECS_CLUSTER --service $AWS_ECS_SERVICE --task-definition $REVISION )
    #echo $update_result
    result=$(echo $update_result | $JQ '.service.taskDefinition' )
    log $result
    if [[ $result != $REVISION ]]; then
        #echo "Error updating service."
		track_error 1 "ECS updating service."	
        return 1
    fi

    echo "Update service intialised successfully for deployment"
    return 0
}

check_service_status() {
        AWS_ECS_SERVICE=$1
        counter=0
		sleep 60
        servicestatus=`aws ecs describe-services --service $AWS_ECS_SERVICE --cluster $AWS_ECS_CLUSTER | $JQ '.services[].events[0].message'`
        while [[ $servicestatus != *"steady state"* ]]
        do
           echo "Current event message : $servicestatus"
           echo "Waiting for 15 sec to check the service status...."
           sleep 15
           servicestatus=`aws ecs describe-services --service $AWS_ECS_SERVICE --cluster $AWS_ECS_CLUSTER | $JQ '.services[].events[0].message'`
           counter=`expr $counter + 1`
           if [[ $counter -gt $COUNTER_LIMIT ]] ; then
                echo "Service does not reach steady state with in 180 seconds. Please check"
                exit 1
           fi
        done
        echo "$servicestatus"
}

# EBS integration


EBS_push_docker_image() {

echo "pushing docker image: ${IMAGE}"
docker push $IMAGE
track_error $? "docker push failed."

}

creating_updating_ebs_docker_json() {
cd $AWS_EBS_EB_DOCKERRUN_TEMPLATE_LOCATION
cat $AWS_EBS_DOCKERRUN_TEMPLATE | sed -e "s/@IMAGE@/${EBS_TAG}/g" > $DOCKERRUN
jar cMf ${EBS_TAG}.zip $DOCKERRUN .ebextensions
echo "pushing ${EBS_TAG}.zip to S3: ${AWS_S3_BUCKET}/${AWS_S3_KEY}"
aws s3api put-object --bucket "${AWS_S3_BUCKET}" --key "${AWS_S3_KEY}" --body ${EBS_TAG}.zip
track_error $? "aws s3api put-object failed."
}

creating_updating_EBS_appversion() {

echo "creating new application version $AWS_EBS_APPVER in ${EBS_APPLICATION_NAME} from s3:${AWS_S3_BUCKET}/${AWS_S3_KEY}"
aws elasticbeanstalk create-application-version --application-name $EBS_APPLICATION_NAME --version-label $AWS_EBS_APPVER --source-bundle S3Bucket="$AWS_S3_BUCKET",S3Key="$AWS_S3_KEY"
track_error $? "aws elasticbeanstalk create-application-version failed."

echo "updating elastic beanstalk environment ${AWS_EB_ENV} with the version ${AWS_EBS_APPVER}."
# assumes beanstalk app for this service has already been created and configured
aws elasticbeanstalk update-environment --environment-name $AWS_EBS_ENV_NAME --version-label $AWS_EBS_APPVER
track_error $? "aws elasticbeanstalk update-environment failed."

}

#Cloud Front DEPLOYMENT

deploy_s3bucket() {
	echo -e "application/font-woff\t\t\t\twoff2" >> /etc/mime.types
	echo -e "application/font-sfnt\t\t\t\tttf" >> /etc/mime.types
	echo -e "application/json\t\t\t\tmap" >> /etc/mime.types

	cat /etc/mime.types  | grep -i woff
	cat /etc/mime.types  | grep -i ico
	cat /etc/mime.types  | grep -i map
	cat /etc/mime.types  | grep -i ttf
	if [ "$NOCACHE" = "true" ]; then
		S3_CACHE_OPTIONS="--cache-control private,no-store,no-cache,must-revalidate,max-age=0"
		echo "*** Deploying with Cloudfront Cache disabled ***"
	else
		S3_CACHE_OPTIONS="--cache-control max-age=0,s-maxage=86400"
	fi

	S3_OPTIONS="--exclude '*.txt' --exclude '*.js' --exclude '*.css'"
	echo aws s3 sync $SOURCE_SYNC_PATH s3://${AWS_S3_BUCKET} ${S3_CACHE_OPTIONS} ${S3_OPTIONS}
	eval "aws s3 sync --dryrun $SOURCE_SYNC_PATH s3://${AWS_S3_BUCKET} ${S3_CACHE_OPTIONS} ${S3_OPTIONS}"
	result=`eval "aws s3 sync $SOURCE_SYNC_PATH s3://${AWS_S3_BUCKET} ${S3_CACHE_OPTIONS} ${S3_OPTIONS}"`
	if [ $? -eq 0 ]; then
		echo "All html, font, image, map and media files are Deployed without gzip encoding!"
	else
		echo "Deployment Failed  - $result"
		exit 1
	fi

	S3_OPTIONS="--exclude '*' --include '*.txt' --include '*.js' --include '*.css' --content-encoding gzip"
	echo aws s3 sync --dryrun $SOURCE_SYNC_PATH s3://${AWS_S3_BUCKET} ${S3_CACHE_OPTIONS} ${S3_OPTIONS}
	eval "aws s3 sync --dryrun $SOURCE_SYNC_PATH s3://${AWS_S3_BUCKET} ${S3_CACHE_OPTIONS} ${S3_OPTIONS}"
	result=`eval "aws s3 sync $SOURCE_SYNC_PATH s3://${AWS_S3_BUCKET} ${S3_CACHE_OPTIONS} ${S3_OPTIONS}"`
	if [ $? -eq 0 ]; then
		echo "All txt, css, and js files are Deployed! with gzip"
	else
		echo "Deployment Failed  - $result"
		exit 1
	fi
}

# Input Collection and validation
input_collection_validation()
{
while getopts .d:h:e:t:v:s:p:c:. OPTION
do
     case $OPTION in
         d)
             DEPLOYMENT_TYPE=$OPTARG
             ;;
         h)
             usage
             exit 1
             ;;
         e)
             ENV=$OPTARG
             ;;
         t)
             TAG=$OPTARG
             ;;
         c)
             NOCACHE=$OPTARG
             ;;			 
         v)
             EBS_APPVER=$OPTARG
             ;;
         s)
             SEC_LOCATION=$OPTARG
             ;;
         p)
             ECS_TEMPLATE_TYPE=$OPTARG
             ;;
         ?)
             log "additional param required"
             usage
             exit
             ;;
     esac
done

if [ -z $DEPLOYMENT_TYPE ] || [ -z $ENV ] ;
then
     log "Param validation error"
     usage
     exit 1
fi

log "ENV        :       $ENV"
log "DEPLOYMENT_TYPE    :       $DEPLOYMENT_TYPE"
ENV_CONFIG=`echo "$ENV" | tr '[:upper:]' '[:lower:]'`

source $BUILD_VARIABLE_FILE_NAME
#The secret file download and decryption need to be done here

SECRET_FILE_NAME="${APPNAME}-buildsecvar.conf"
if [ "$SEC_LOCATIOM" = "GIT" ] ;
then
pwd
#cp ./../buildscript/$APPNAME/$SECRET_FILE_NAME.cpt .
cp ./../buildscript/$APPNAME/$SECRET_FILE_NAME.enc .
#ccdecrypt -f $SECRET_FILE_NAME.cpt -K $SECPASSWD
#openssl enc -aes-256-cbc -d -in $SECRET_FILE_NAME.enc -out $SECRET_FILE_NAME -k $SECPASSWD

else
AWS_ACCESS_KEY_ID=$(eval "echo \$${ENV}_AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY=$(eval "echo \$${ENV}_AWS_SECRET_ACCESS_KEY")
AWS_ACCOUNT_ID=$(eval "echo \$${ENV}_AWS_ACCOUNT_ID")
AWS_REGION=$(eval "echo \$${ENV}_AWS_REGION")
configure_aws_cli
aws s3 cp s3://tc-platform-dev/buildconfiguration/$SECRET_FILE_NAME.cpt .
fi
if [ -f "$SECRET_FILE_NAME" ];
then
   rm -rf $SECRET_FILE_NAME
fi
#ccdecrypt -f $SECRET_FILE_NAME.cpt -K $SECPASSWD
openssl enc -aes-256-cbc -d -in $SECRET_FILE_NAME.enc -out $SECRET_FILE_NAME -k $SECPASSWD
source $SECRET_FILE_NAME
#decrypt

AWS_ACCESS_KEY_ID=$(eval "echo \$${ENV}_AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY=$(eval "echo \$${ENV}_AWS_SECRET_ACCESS_KEY")
AWS_ACCOUNT_ID=$(eval "echo \$${ENV}_AWS_ACCOUNT_ID")

if [ -z $AWS_ACCESS_KEY_ID ] || [ -z $AWS_SECRET_ACCESS_KEY ] || [ -z $AWS_ACCOUNT_ID ] ;
then
     log "Secret Parameters are not updated. Please upload the secret file"
         usage
     exit 1
fi

AWS_REGION=$(eval "echo \$${ENV}_AWS_REGION")
if [ "$DEPLOYMENT_TYPE" == "ECS" ]
then
  AWS_REPOSITORY=$(eval "echo \$${ENV}_AWS_REPOSITORY")
  AWS_ECS_CLUSTER=$(eval "echo \$${ENV}_AWS_ECS_CLUSTER")
  AWS_ECS_SERVICE=$(eval "echo \$${ENV}_AWS_ECS_SERVICE")
  AWS_ECS_TASK_FAMILY=$(eval "echo \$${ENV}_AWS_ECS_TASK_FAMILY")
  AWS_ECS_CONTAINER_NAME=$(eval "echo \$${ENV}_AWS_ECS_CONTAINER_NAME")
  AWS_ECS_TEMPLATE_UPDATE_SCRIPT=$(eval "echo \$${ENV}_AWS_ECS_TEMPLATE_UPDATE_SCRIPT")
  AWS_ECS_TASKDEF_FILE=$(eval "echo \$${ENV}_AWS_ECS_TASKDEF_FILE")
  AWS_ECS_VOLUMEDEF_FILE=$(eval "echo \$${ENV}_AWS_ECS_VOLUMEDEF_FILE")
  ECS_TAG=$TAG
  if [ -z $AWS_REGION ] || [ -z $AWS_REPOSITORY ] || [ -z $AWS_ECS_CLUSTER ] || [ -z $AWS_ECS_SERVICE ] || [ -z $AWS_ECS_TASK_FAMILY ] || [ -z $AWS_ECS_CONTAINER_NAME ] || [ -z $AWS_ECS_TEMPLATE_UPDATE_SCRIPT ] || [ -z $AWS_ECS_TASKDEF_FILE ] || [ -z $ECS_TAG ];
  then
     log "Build varibale are not updated. Please update the Build variable file"
     usage
     exit 1
  fi
  log "AWS_REPOSITORY           :       $AWS_REPOSITORY"
  log "AWS_ECS_CLUSTER    :       $AWS_ECS_CLUSTER"
  log "AWS_ECS_SERVICE  :       $AWS_ECS_SERVICE"
  log "AWS_ECS_TASK_FAMILY    : $AWS_ECS_TASK_FAMILY"
  log "AWS_ECS_CONTAINER_NAME   :       $AWS_ECS_CONTAINER_NAME"
  log "AWS_ECS_TEMPLATE_UPDATE_SCRIPT :       $AWS_ECS_TEMPLATE_UPDATE_SCRIPT"
  log "AWS_ECS_TASKDEF_FILE :       $AWS_ECS_TASKDEF_FILE"
  log "ECS_TAG  :       $ECS_TAG"
fi

if [ "$DEPLOYMENT_TYPE" == "EBS" ]
then
#EBS varaibale
  EBS_APPLICATION_NAME=$(eval "echo \$${ENV}_EBS_APPLICATION_NAME")
  AWS_EBS_ENV_NAME=$(eval "echo \$${ENV}_AWS_EBS_ENV_NAME")
  AWS_EBS_APPVER="${AWS_EBS_ENV_NAME}-${EBS_APPVER}"
  EBS_TAG="${IMAGE_NAME}:${ENV_CONFIG}.${EBS_APPVER}"
  IMAGE="${DOCKER_REGISTRY_NAME}/${EBS_TAG}"
  #EBS_TAG="${IMAGE_NAME}:latest"
  #IMAGE="${DOCKER_REGISTRY_NAME}/${EBS_TAG}"

  AWS_S3_BUCKET=$(eval "echo \$${ENV}_AWS_S3_BUCKET")
  AWS_S3_KEY_LOCATION=$(eval "echo \$${ENV}_AWS_S3_KEY_LOCATION")
  if [ "$AWS_S3_KEY_LOCATION" = "" ] ;
  then
    AWS_S3_KEY="${EBS_TAG}"
  else
    AWS_S3_KEY="$AWS_S3_KEY_LOCATION/${EBS_TAG}"
  fi
  AWS_EBS_EB_DOCKERRUN_TEMPLATE_LOCATION=$(eval "echo \$${ENV}_AWS_EBS_EB_DOCKERRUN_TEMPLATE_LOCATION")
  AWS_EBS_DOCKERRUN_TEMPLATE=$(eval "echo \$${ENV}_AWS_EBS_DOCKERRUN_TEMPLATE")
  if [ -z $EBS_APPLICATION_NAME ] || [ -z $AWS_EBS_ENV_NAME ] || [ -z $EBS_APPVER ] || [ -z $AWS_EBS_APPVER ]  || [ -z $EBS_TAG ] || [ -z $IMAGE ] || [ -z $AWS_S3_BUCKET ] || [ -z $AWS_EBS_EB_DOCKERRUN_TEMPLATE_LOCATION ] || [ -z $AWS_EBS_DOCKERRUN_TEMPLATE ];
  then
     log "Build varibale are not updated. Please update the Build variable file"
     usage
     exit 1
  fi
  log "EBS_APPLICATION_NAME           :       $EBS_APPLICATION_NAME"
  log "EBS_APPVER    :       $EBS_APPVER"
  log "AWS_EBS_APPVER	: 	$AWS_EBS_APPVER"
  log "EBS_TAG  :       $EBS_TAG"
  log "IMAGE    : $IMAGE"
  log "AWS_S3_BUCKET   :       $AWS_S3_BUCKET"
  log "AWS_S3_KEY :       $AWS_S3_KEY"
  log "AWS_EB_ENV  :       $AWS_EBS_ENV_NAME"

echo "BS"
fi
if [ "$DEPLOYMENT_TYPE" == "CFRONT" ]
then
  AWS_S3_BUCKET=$(eval "echo \$${ENV}_AWS_S3_BUCKET")
  SOURCE_SYNC_PATH=$(eval "echo \$${ENV}_SOURCE_SYNC_PATH")

 if [ -z $AWS_S3_BUCKET ] || [ -z $SOURCE_SYNC_PATH ];
  then
     log "Build varibale are not updated. Please update the Build variable file"
     usage
     exit 1
  fi
  log "AWS_S3_BUCKET   :       $AWS_S3_BUCKET"
  log "SOURCE_SYNC_PATH  :       $SOURCE_SYNC_PATH"

#CFRONT VAr
echo "CFRONT"
fi
}

# Main

main()
{

input_collection_validation $@

if [ "$DEPLOYMENT_TYPE" == "ECS" ]
then
	configure_aws_cli
	ECS_push_ecr_image
	ECS_update_register_task_definition
	AWS_ECS_SERVICE_NAMES=`echo ${AWS_ECS_SERVICE} | sed 's/,/ /g' | sed 'N;s/\n//' `
	IFS=' ' read -a AWS_ECS_SERVICES <<< $AWS_ECS_SERVICE_NAMES
	if [ ${#AWS_ECS_SERVICES[@]} -gt 0 ]; then
		 echo "${#AWS_ECS_SERVICES[@]} service are going to be updated"
		 for AWS_ECS_SERVICE_NAME in "${AWS_ECS_SERVICES[@]}"
		 do
		   echo "updating ECS Cluster Service - $AWS_ECS_SERVICE_NAME"
		   #ECS_deploy_cluster "$AWS_ECS_SERVICE_NAME"
		   #check_service_status "$AWS_ECS_SERVICE_NAME"
		   echo $REVISION
		 done
	else
		 echo "Kindly check the service name in Parameter"
		 usage
		 exit 1
	fi
	
fi


if [ "$DEPLOYMENT_TYPE" == "EBS" ]
then
	configure_aws_cli
	configure_docker_private_login
	EBS_push_docker_image
	creating_updating_ebs_docker_json
	creating_updating_EBS_appversion
fi

if [ "$DEPLOYMENT_TYPE" == "CFRONT" ]
then
	configure_aws_cli
        echo "heloo"
	deploy_s3bucket
fi
}
main $@

