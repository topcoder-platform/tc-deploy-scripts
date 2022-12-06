#!/bin/bash

#Variable Declaration
JQ="jq --raw-output --exit-status"
DEPLOYMENT_TYPE=""
ENV=""
BUILD_VARIABLE_FILE_NAME="./buildvar.conf"
SECRET_FILE_NAME="./buildsecvar.conf"
SHARED_PROPERTY_FILENAME=""

# Common variables

#echo $AWS_ACCESS_KEY_ID
# AWS_ACCESS_KEY_ID=""
# AWS_SECRET_ACCESS_KEY=""
# AWS_ACCOUNT_ID=""
# AWS_REGION=""
TAG=""
SEC_LIST=""
SECPS_LIST=""
#COUNTER_LIMIT=12

if [ -z "$COUNTER_LIMIT" ]; then
        COUNTER_LIMIT=12
fi

# Variables specific to ECS

#AWS_REPOSITORY=""
#AWS_ECS_CLUSTER=""
#AWS_ECS_SERVICE=""
#AWS_ECS_TASK_FAMILY=""
#AWS_ECS_CONTAINER_NAME=""
ECS_TAG=""
REVISION=""
ECS_TEMPLATE_TYPE="EC2"
task_def=""
CONTAINER_LOG_DRIVER="awslogs"
portcount=0
envcount=0
psenvcount=0
volcount=0
template=""
TEMPLATE_SKELETON_FILE="base_template_v2.json"
APP_IMAGE_NAME=""
DEPLOYCATEGORY=""
ECSCLI_ENVFILE="api.env"

# Variables specific to EBS

DOCKERRUN="Dockerrun.aws.json"
#EBS_EB_EXTENSTION_LOCATION=""
IMG_WITH_EBS_TAG=""
EBS_TEMPLATE_SKELETON_FILE="ebs_base_template_v3.json.template"
EBS_APPLICATION_NAME=""
EBS_APPVER=""
EBS_TAG=""
IMAGE=""
AWS_EBS_APPVER=""
#AWS_S3_BUCKET=""
AWS_S3_KEY=""
AWS_EB_ENV=""
EBS_TEMPLATE_FILE_NAME=""
#AWS_EBS_EB_DOCKERRUN_TEMPLATE_LOCATION=$(eval "echo \$${ENV}_AWS_EBS_EB_DOCKERRUN_TEMPLATE_LOCATION")
#AWS_EBS_DOCKERRUN_TEMPLATE=$(eval "echo \$${ENV}_AWS_EBS_DOCKERRUN_TEMPLATE")
#AWS_S3_KEY_LOCATION=""
ebsportcount=0
ebstemplate=""
#variable for cloud front
#AWS_S3_BUCKET=""
#AWS_S3_SOURCE_SYNC_PATH=""
CFCACHE="false"
# AWS_CLOUD_FRONT_ID=""

# Variables for Lambda 
#AWS_LAMBDA_DEPLOY_TYPE=""
#AWS_LAMBDA_STAGE=""

# FUNCTIONS
# usage Function - provides information about how to execute the script
usage()
{
cat << EOF
usage: $0 options

This script need to be executed with below option.

OPTIONS:
 -h      Show this message
 -d      Deployment Type [ECS|EBS|CFRONT]
 -e      Environment [DEV|QA|PROD]
 -t      ECS Tag Name [mandatory if ECS ]
 -v      EBS version [mandatory if  EBS deployment]
 -i      ECS Image name
 -c		 cache option true [optional : value = true| false]i
 -s      Security file location GIT|AWS
 -p      ECS template type
 -g      Common property file which is uploaded to shared-properties folder
EOF
}

# log Function - Used to provide information of execution information with date and time
log()
{
   echo "`date +'%D %T'` : $1"
}

# track_error function - validates whether the application execute without any error
track_error()
{
   if [ $1 != "0" ]; then
        log "$2 exited with error code $1"
        log "completed execution IN ERROR at `date`"
        exit $1
   fi
}

# Function for AWS login
configure_aws_cli() {
	aws --version
	aws configure set aws_access_key_id $AWS_ACCESS_KEY_ID
	aws configure set aws_secret_access_key $AWS_SECRET_ACCESS_KEY
	aws configure set default.region $AWS_REGION
	aws configure set default.output json
	log "Configured AWS CLI."
}

# Function for private dcoker login
configure_docker_private_login() {
	aws s3 cp "s3://appirio-platform-$ENV_CONFIG/services/common/dockercfg" ~/.dockercfg
}

# ECS Deployment Functions
ECS_push_ecr_image() {
    echo "\n\n"
    if [ -z "$APP_IMAGE_NAME" ];
    then
        log "ECS image follows the standard format"
    else
        log "ECS Image does not follow the standard format. Modifying the image and updating the ECS_TAG"
        docker tag $APP_IMAGE_NAME:$ECS_TAG $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$AWS_REPOSITORY:$CIRCLE_BUILD_NUM
        ECS_TAG=$CIRCLE_BUILD_NUM
    fi

    CHECK_ECR_EXIST=""
    CHECK_ECR_EXIST=$(aws ecr describe-repositories --repository-names ${AWS_REPOSITORY} 2>&1)
    if [ $? -ne 0 ]; then
        if echo ${CHECK_ECR_EXIST} | grep -q RepositoryNotFoundException; then
            echo "ECR repo does not exist -- creating repo"
            aws ecr create-repository --repository-name $AWS_REPOSITORY  
            track_error $? "ECS ECR repo creation" 
            log "ECR repo created successfully."     
        else
            echo ${CHECK_ECR_EXIST}
        fi
    else    
        echo "$AWS_REPOSITORY ECR repository already exists"
    fi 

	log "Pushing Docker Image..."
	eval $(aws ecr get-login --region $AWS_REGION --no-include-email)
	docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$AWS_REPOSITORY:$ECS_TAG
	track_error $? "ECS ECR image push"
	log "Docker Image published\n\n"
}

ECSCLI_push_ecr_image() {
    ECS_REPONAME=$1
    IMAGE_NAME=$2
    if [ -z "$IMAGE_NAME" ];
    then
        log "ECS image follows the standard format"
    else
        log "ECS image does not follow the standard format. Modifying the image and updating the ECS_TAG"
        docker tag $IMAGE_NAME:$ECS_TAG $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECS_REPONAME:$CIRCLE_BUILD_NUM
        ECS_TAG=$CIRCLE_BUILD_NUM
    fi
	log "Pushing Docker Image..."
	eval $(aws ecr get-login --region $AWS_REGION --no-include-email)
	docker push $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$ECS_REPONAME:$ECS_TAG
	track_error $? "ECS ECR image push"
	log "Docker ECR Image published\n\n"
}

ECSCLI_update_env()
{
    Buffer_seclist=$(echo $SEC_LIST | sed 's/,/ /g')
    for listname in $Buffer_seclist;
    do
        local o=$IFS
        IFS=$(echo -en "\n\b")
        envvars=$( cat $listname.json | jq  -r ' . ' | jq ' . | to_entries[] | { "name": .key , "value": .value } ' | jq -s . )
        log "ECS env vars are fetched"

        for s in $(echo $envvars | jq -c ".[]" ); do
        #echo $envvars
            varname=$(echo $s| jq -r ".name")
            varvalue=$(echo $s| jq -r ".value")
            envaddition "$varname" "$varvalue"
            echo "$varname"="\"$varvalue\"" >>$ECSCLI_ENVFILE
        done
        IFS=$o  
    done
}

portmapping() {
    hostport=$1
    containerport=$2
    containerprotocol=$3

    template=$(echo $template | jq --argjson hostPort $hostport --argjson containerPort $containerport --arg protocol $containerprotocol  --arg portcount $portcount '.containerDefinitions[0].portMappings[$portcount |tonumber] |= .+ { hostPort: $hostPort, containerPort: $containerPort, protocol: $protocol  }')
    let portcount=portcount+1
}

envaddition() {
    #echo "envcount before " $envcount
    envname=$1
    envvalue=$2
    #echo "env value before" $envvalue
    set -f
    template=$(echo $template | jq --arg name "$envname" --arg value "$envvalue" --arg envcount $envcount '.containerDefinitions[0].environment[$envcount |tonumber] |= .+ { name: $name, value: $value  }')
    set +f
    let envcount=envcount+1
    #echo "envcount after ---------" $envcount
    #echo "envvalue after ---------" $envvalue
}

psenvaddition() {
    #echo "psenvcount before " $psenvcount
    envname=$1
    envvalue=$2
    #echo "env value before" $envvalue
    set -f
    template=$(echo $template | jq --arg name "$envname" --arg value "$envvalue" --arg psenvcount $psenvcount '.containerDefinitions[0].secrets[$psenvcount |tonumber] |= .+ { name: $name, valueFrom: $value  }')
    set +f
    let psenvcount=psenvcount+1
    #echo "psenvcount after ---------" $psenvcount
    #echo "envvalue after ---------" $envvalue
}

logconfiguration() {
    template=$(echo $template | jq --arg logDriver $CONTAINER_LOG_DRIVER '.containerDefinitions[0].logConfiguration.logDriver=$logDriver')
    template=$(echo $template | jq --arg awslogsgroup "/aws/ecs/$AWS_ECS_CLUSTER" '.containerDefinitions[0].logConfiguration.options."awslogs-group"=$awslogsgroup')
    template=$(echo $template | jq --arg awslogsregion $AWS_REGION '.containerDefinitions[0].logConfiguration.options."awslogs-region"=$awslogsregion')
    template=$(echo $template | jq --arg awslogsstreamprefix $ENV '.containerDefinitions[0].logConfiguration.options."awslogs-stream-prefix"=$awslogsstreamprefix')
    template=$(echo $template | jq  'del(.containerDefinitions[0].logConfiguration.options.KeyName)')
}

volumeupdate() {
  volname=$1
  sourcepath=$2
  mountpath=$3
  #mntpermission=$4
  #echo $volname $sourcepath $mountpath $mntpermission
  #volumes update
  template=$(echo $template | jq --arg volname $volname --arg sourcepath $sourcepath --arg volcount $volcount '.volumes[$volcount |tonumber] |= .+ { name: $volname, host: { sourcePath: $sourcepath } }')
  #mount point update
  template=$(echo $template | jq --arg volname $volname --arg mountpath $mountpath --arg volcount $volcount '.containerDefinitions[0].mountPoints[$volcount |tonumber] |= .+ { sourceVolume: $volname, containerPath: $mountpath }')

  let volcount=volcount+1
}

ECS_Container_HealthCheck_integ() {
    HealthCheckCmd="$1"

    template=$(echo $template | jq '.containerDefinitions[0].healthCheck.retries=3')
    template=$(echo $template | jq '.containerDefinitions[0].healthCheck.timeout=15')
    template=$(echo $template | jq '.containerDefinitions[0].healthCheck.interval=60')
    template=$(echo $template | jq '.containerDefinitions[0].healthCheck.startPeriod=120')
    template=$(echo $template | jq --arg  HealthCheckCmd "$HealthCheckCmd" '.containerDefinitions[0].healthCheck.command=["CMD-SHELL",$HealthCheckCmd]')
}

ECS_Container_cmd_integ() {
    ContainerCmd="$1"
    template=$(echo $template | jq --arg  ContainerCmd "$ContainerCmd" '.containerDefinitions[0].command=[$ContainerCmd]')
}

ECS_template_create_register() {
    #Getting Template skeleton
    #template=`aws ecs register-task-definition --generate-cli-skeleton`
    template=$(cat $TEMPLATE_SKELETON_FILE)

    #Updating ECS task def file
    template=$(echo $template | jq --arg family $AWS_ECS_TASK_FAMILY '.family=$family')
    log "ECS Task Family updated"

    #taskrole and excution role has updated
    if [ -z $AWS_ECS_TASK_ROLE_ARN ];
    then
        log "No ECS Task Role defined"
    else
        template=$(echo $template | jq --arg taskRoleArn arn:aws:iam::$AWS_ACCOUNT_ID:role/$AWS_ECS_TASK_ROLE_ARN '.taskRoleArn=$taskRoleArn')
    fi

    if [ -z $AWS_ECS_TASK_EXECUTION_ROLE_ARN ];
    then
        log "No ECS Task Execution Role defined"
    else
        template=$(echo $template | jq --arg executionRoleArn arn:aws:iam::$AWS_ACCOUNT_ID:role/$AWS_ECS_TASK_EXECUTION_ROLE_ARN '.executionRoleArn=$executionRoleArn')
    fi

    #Container Name update
    template=$(echo $template | jq --arg name $AWS_ECS_CONTAINER_NAME '.containerDefinitions[0].name=$name')
    log "ECS Container Name updated"

    #Container Image Name update
    template=$(echo $template | jq --arg image $AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$AWS_REPOSITORY:$ECS_TAG '.containerDefinitions[0].image=$image')
    log "ECR Image name updated"

    #Container Memory reservation
    if [ -z $AWS_ECS_CONTAINER_MEMORY_RESERVATION ];
    then
        log "No ECS reserved memory defined. Going with default value 500 MB"
        AWS_ECS_CONTAINER_MEMORY_RESERVATION="1000"
        template=$(echo $template | jq --argjson memoryReservation $AWS_ECS_CONTAINER_MEMORY_RESERVATION '.containerDefinitions[0].memoryReservation=$memoryReservation')
    else 
        template=$(echo $template | jq --argjson memoryReservation $AWS_ECS_CONTAINER_MEMORY_RESERVATION '.containerDefinitions[0].memoryReservation=$memoryReservation')
    fi
    log "ECS memory reservation updated."

    #Container CPU reservation
    if [ -z $AWS_ECS_CONTAINER_CPU ];
    then
        echo "No ECS container CPU defined. Going with default value 100"
        AWS_ECS_CONTAINER_CPU=100
        template=$(echo $template | jq --argjson cpu $AWS_ECS_CONTAINER_CPU '.containerDefinitions[0].cpu=$cpu')
    else
        template=$(echo $template | jq --argjson cpu $AWS_ECS_CONTAINER_CPU '.containerDefinitions[0].cpu=$cpu')
    fi
    log "ECS container CPU updated."

    #Port Mapping
    Buffer_portmap=$(echo $AWS_ECS_PORTS | sed 's/,/ /g')
    for b1 in $Buffer_portmap;
    do
        hostport=$( echo $b1 | cut -d ':' -f 1 )
        log "ECS host port: $hostport" 
        containerport=$( echo $b1 | cut -d ':' -f 2 )
        log "ECS container port: $containerport"
        protocolmapped=$( echo $b1 | cut -d ':' -f 3 )
        log "ECS mapped protocol: $protocolmapped"
        portmapping $hostport $containerport $protocolmapped
    done
    log "ECS container port mapping updated"

    # Environment addition
    Buffer_seclist=$(echo $SEC_LIST | sed 's/,/ /g')
    for listname in $Buffer_seclist;
    do
        local o=$IFS
        IFS=$(echo -en "\n\b")
        envvars=$( cat $listname.json | jq  -r ' . ' | jq ' . | to_entries[] | { "name": .key , "value": .value } ' | jq -s . )
        log "vars are fetched"

        for s in $(echo $envvars | jq -c ".[]" ); do
            #echo $envvars
            varname=$(echo $s| jq -r ".name")
            varvalue=$(echo $s| jq -r ".value")
            envaddition "$varname" "$varvalue"
        done
        IFS=$o  
    done

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
                aws ssm get-parameters-by-path --path $k --query "Parameters[*].{Name:Name}" > paramnames.json
                ###paramnames=$(cat paramnames.json | jq -r .[].Name | rev | cut -d / -f 1 | rev)
                for s in $(cat paramnames.json | jq -r .[].Name )
                do
                    varname=$(echo $s | rev | cut -d / -f 1 | rev)
                    varvalue="arn:aws:ssm:$AWS_REGION:$AWS_ACCOUNT_ID:parameter$s"
                    psenvaddition "$varname" "$varvalue"
                    #echo "$varname" "$varvalue"
                done
            done
            IFS=$o  
        done
    fi
    log "Environment has updated"

    # Log Configuration
    logconfiguration
    log "Log configuration has updated"

    #volume update
    if [ -z $AWS_ECS_VOLUMES ];
    then
        echo "No ECS volume mapping defined"
    else
        Buffer_volumes=$(echo $AWS_ECS_VOLUMES | sed 's/,/ /g')
        for v1 in $Buffer_volumes;
        do
            volname=$( echo $v1 | cut -d ':' -f 1 ) 
            sourcepath=$( echo $v1 | cut -d ':' -f 2 ) 
            mountpath=$( echo $v1 | cut -d ':' -f 3 ) 
            #mntpermission=$( echo $v1 | cut -d ':' -f 4 ) 
            #volumeupdate $volname $sourcepath $mountpath $mntpermission
            volumeupdate $volname $sourcepath $mountpath
        done
        log "ECS volumes are mapped"
    fi 

    #Container health check update
    if [ -z "$AWS_ECS_CONTAINER_HEALTH_CMD" ];
    then
        echo "No ECS container health check command defined"
    else
        ECS_Container_HealthCheck_integ "$AWS_ECS_CONTAINER_HEALTH_CMD"    
    fi

    #Container command integration
    if [ -z "$AWS_ECS_CONTAINER_CMD" ];
    then
        echo "No ECS container start-up command defined"
    else
        ECS_Container_cmd_integ "$AWS_ECS_CONTAINER_CMD"    
    fi

    #updating data based on ECS deploy type
    if [ "$ECS_TEMPLATE_TYPE" == "FARGATE" ]
    then
        #updating Network
        ECS_NETWORKTYPE="awsvpc"
        template=$(echo $template | jq --arg executionRoleArn arn:aws:iam::$AWS_ACCOUNT_ID:role/ecsTaskExecutionRole '.executionRoleArn=$executionRoleArn')
        template=$(echo $template | jq --arg networkMode $ECS_NETWORKTYPE '.networkMode=$networkMode')
        # Updating the compatibiltiy
        #template=$(echo $template | jq --arg requiresCompatibilities EC2 '.requiresCompatibilities[0] |= .+ $requiresCompatibilities')
        template=$(echo $template | jq --arg requiresCompatibilities FARGATE '.requiresCompatibilities[.requiresCompatibilities| length] |= .+ $requiresCompatibilities')
        # Updating Fargate CPU
        if [ -z $AWS_ECS_FARGATE_CPU ];
        then
            echo "No FARGATE CPU defined. Going with default value 1024"   
            AWS_ECS_FARGATE_CPU="1024"   
            template=$(echo $template | jq --arg cpu $AWS_ECS_FARGATE_CPU '.cpu=$cpu')
        else
            template=$(echo $template | jq --arg cpu $AWS_ECS_FARGATE_CPU '.cpu=$cpu')    
        fi

        # Updating Fargate Memory
        if [ -z $AWS_ECS_FARGATE_MEMORY ];
        then
            echo "No FARGATE memory defined. Going with default value 2048"  
            AWS_ECS_FARGATE_MEMORY="2048"
            template=$(echo $template | jq --arg memory $AWS_ECS_FARGATE_MEMORY '.memory=$memory')
        else
            template=$(echo $template | jq --arg memory $AWS_ECS_FARGATE_MEMORY '.memory=$memory')
        fi
    else
        #CONTAINER_CPU
        ECS_NETWORKTYPE="bridge"
        template=$(echo $template | jq --arg networkMode $ECS_NETWORKTYPE '.networkMode=$networkMode')
        
        # Updating the compatibiltiy
        template=$(echo $template | jq --arg requiresCompatibilities EC2 '.requiresCompatibilities[0] =  $requiresCompatibilities')
    fi

    if [ -z "$template" ]; 
        then 
            track_error 1 "Task Definition was not set by template variable"
            exit 1
        else
        # echo "template values ------:" $template
            if REVISION=$(aws ecs register-task-definition --cli-input-json "$template" | $JQ '.taskDefinition.taskDefinitionArn'); then
                log "Revision: $REVISION"
            else
                track_error 1 "Task Def registration"
                log "Failed to register task definition"
            return 1
        fi
    fi
}

ECS_deploy_cluster() {
    AWS_ECS_SERVICE=$1

    #checking if cluster exists
    CHECK_CLUSTER_EXIST=""
    CHECK_CLUSTER_EXIST=$(aws ecs describe-clusters --cluster $AWS_ECS_CLUSTER | jq --raw-output 'select(.clusters[].clusterName != null ) | .clusters[].clusterName')
    if [ -z $CHECK_CLUSTER_EXIST ];
    then
        echo "$AWS_ECS_CLUSTER cluster does not exist. Kindly check with DevOps team"
        exit 1
    else
        echo "$AWS_ECS_CLUSTER cluster exists"
    fi

    #checking if service exists
    CHECK_SERVICE_EXIST=""
    CHECK_SERVICE_EXIST=$(aws ecs describe-services --service $AWS_ECS_SERVICE --cluster $AWS_ECS_CLUSTER | jq --raw-output 'select(.services[].status != null ) | .services[].status')
    if [ -z $CHECK_SERVICE_EXIST ];
    then
        if [ "$ECS_TEMPLATE_TYPE" == "FARGATE" ];
        then
            echo "Fargate Service does not exist. Kindly check with DevOps team"
            exit 1
        else
            echo "Service does not exist. Creating service"
            aws ecs create-service --cluster $AWS_ECS_CLUSTER --service-name $AWS_ECS_SERVICE --task-definition $REVISION --desired-count 1 
            echo "Kindly work with DevOps team for routing"
        fi
    else
        echo "ECS Service exists. Updating the service..."
        update_result=$(aws ecs update-service --cluster $AWS_ECS_CLUSTER --service $AWS_ECS_SERVICE --task-definition $REVISION )
        result=$(echo $update_result | $JQ '.service.taskDefinition' )
        log $result
        if [[ $result != $REVISION ]]; then
            #echo "Error updating service."
            track_error 1 "ECS updating service."	
            return 1
        fi
        
        echo "Updated service intialised successfully for deployment\n\n"    
    fi

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
        echo "Waiting for 15 sec to check the service status..."
        sleep 15
        servicestatus=`aws ecs describe-services --service $AWS_ECS_SERVICE --cluster $AWS_ECS_CLUSTER | $JQ '.services[].events[0].message'`
        counter=`expr $counter + 1`
        if [[ $counter -gt $COUNTER_LIMIT ]] ; then
            echo "Service did not reach steady state with in 180 seconds. Please check the logs."
            exit 1
        fi
    done
    echo "$servicestatus"
}

validate_update_loggroup()
{
    log_group_fetch=$(aws logs describe-log-groups --log-group-name-prefix /aws/ecs/$AWS_ECS_CLUSTER | jq -r .logGroups[].logGroupName | grep "^/aws/ecs/$AWS_ECS_CLUSTER$")
    #echo $log_group_fetch
    if [ -z $log_group_fetch ];
    then
        echo "\nLog group does not exist\n"
        aws logs create-log-group --log-group-name /aws/ecs/$AWS_ECS_CLUSTER
        track_error $? "aws log group" 
    else
        echo "\nLog group exists\n"
    fi
}

# EBS integration
ebsportmapping() {
    echo "Port map called\n"
    containerport=$1
    hostport=$2

    if [ -z $hostport ]
    then
        ebstemplate=$(echo $ebstemplate | jq --arg containerPort $containerport --arg ebsportcount $ebsportcount '.Ports[$ebsportcount |tonumber] |= .+ { ContainerPort: $containerPort }')
    else
        ebstemplate=$(echo $ebstemplate | jq --arg hostPort $hostport --arg containerPort $containerport --arg ebsportcount $ebsportcount '.Ports[$ebsportcount |tonumber] |= .+ { HostPort: $hostPort, ContainerPort: $containerPort }')
    fi

    let ebsportcount=ebsportcount+1
}

EBS_push_docker_image() {
    echo "Pushing Docker image: ${IMAGE}"
    IMAGE="${DOCKER_REGISTRY_NAME}/${IMG_WITH_EBS_TAG}"
    docker push $IMAGE
    track_error $? "Docker push failed."
}

creating_updating_ebs_docker_json() {
    echo "Updating S3 auth bucket name"
    sed -i.bak -e "s/@AWSS3AUTHBUCKET@/appirio-platform-$ENV_CONFIG/g" $EBS_TEMPLATE_SKELETON_FILE
    rm ${EBS_TEMPLATE_SKELETON_FILE}.bak

    #EBS Port Mapping
    ebstemplate=$(cat $EBS_TEMPLATE_SKELETON_FILE)
    if [ -z $AWS_EBS_PORTS ];
    then
        echo "No container port is defined. Configuring default 8080 port"
        ebsportmapping 8080
    else
        Buffer_portmap=$(echo $AWS_EBS_PORTS | sed 's/,/ /g')
        for ebsportbuf in $Buffer_portmap;
        do
            containerport=$( echo $ebsportbuf | cut -d ':' -f 1 ) 
            if [[ $ebsportbuf = *:* ]]; then
                hostport=$( echo $ebsportbuf | cut -d ':' -f 2 ) 
            fi
            ebsportmapping $containerport $hostport
        done
    fi
    echo "$ebstemplate" > $EBS_TEMPLATE_SKELETON_FILE
    log "port mapping updated"    

    if [ -z "$EBS_EB_EXTENSTION_LOCATION" ];
    then
        cat $EBS_TEMPLATE_SKELETON_FILE | sed -e "s/@IMAGE@/${IMG_WITH_EBS_TAG}/g" > $DOCKERRUN
        echo "Pushing $DOCKERRUN as ${IMG_WITH_EBS_TAG} to S3: ${AWS_S3_BUCKET}/${AWS_S3_KEY}"
        aws s3api put-object --bucket "${AWS_S3_BUCKET}" --key "${AWS_S3_KEY}" --body $DOCKERRUN
        track_error $? "aws s3api put-object failed."    
    else
        cat $EBS_TEMPLATE_SKELETON_FILE | sed -e "s/@IMAGE@/${IMG_WITH_EBS_TAG}/g" > $DOCKERRUN
        cp -rvf $EBS_EB_EXTENSTION_LOCATION/.ebextensions .
        jar cMf ${IMG_WITH_EBS_TAG}.zip $DOCKERRUN .ebextensions
        echo "Pushing ${IMG_WITH_EBS_TAG}.zip to S3: ${AWS_S3_BUCKET}/${AWS_S3_KEY}"
        aws s3api put-object --bucket "${AWS_S3_BUCKET}" --key "${AWS_S3_KEY}" --body ${IMG_WITH_EBS_TAG}.zip
        track_error $? "aws s3api put-object failed."
    fi
}

creating_updating_EBS_appversion() {
    echo "Creating new application version $AWS_EBS_APPVER in ${AWS_EBS_APPLICATION_NAME} from s3:${AWS_S3_BUCKET}/${AWS_S3_KEY}"
    aws elasticbeanstalk create-application-version --application-name $AWS_EBS_APPLICATION_NAME --version-label $AWS_EBS_APPVER --source-bundle S3Bucket="$AWS_S3_BUCKET",S3Key="$AWS_S3_KEY"
    track_error $? "aws elasticbeanstalk create-application-version failed."

    echo "Updating elastic beanstalk environment ${AWS_EB_ENV} with the version ${AWS_EBS_APPVER}."
    # assumes beanstalk app for this service has already been created and configured
    aws elasticbeanstalk update-environment --environment-name $AWS_EBS_ENV_NAME --version-label $AWS_EBS_APPVER
    track_error $? "aws elasticbeanstalk update-environment failed."
}

#CloudFront deployment

deploy_s3bucket() {
	echo -e "application/font-woff\t\t\t\twoff2" >> /etc/mime.types
	echo -e "application/font-sfnt\t\t\t\tttf" >> /etc/mime.types
	echo -e "application/json\t\t\t\tmap" >> /etc/mime.types

	cat /etc/mime.types  | grep -i woff
	cat /etc/mime.types  | grep -i ico
	cat /etc/mime.types  | grep -i map
	cat /etc/mime.types  | grep -i ttf
	if [ "$CFCACHE" = "true" ]; then
        # caching is enabled, so set the cache control's max age
        S3_CACHE_OPTIONS="--cache-control max-age=0,s-maxage=86400"     
		echo "*** Deploying with Cloudfront Cache enabled ***"  
	else
        # caching is disabled, so set the cache control to never cache
     	S3_CACHE_OPTIONS="--cache-control private,no-store,no-cache,must-revalidate,max-age=0"
		echo "*** Deploying with Cloudfront Cache disabled ***"  
	fi

	S3_OPTIONS="--exclude '*.txt' --exclude '*.js' --exclude '*.css'"
	echo aws s3 sync $AWS_S3_SOURCE_SYNC_PATH s3://${AWS_S3_BUCKET} ${S3_CACHE_OPTIONS} ${S3_OPTIONS}
	eval "aws s3 sync --dryrun $AWS_S3_SOURCE_SYNC_PATH s3://${AWS_S3_BUCKET} ${S3_CACHE_OPTIONS} ${S3_OPTIONS}"
	result=`eval "aws s3 sync $AWS_S3_SOURCE_SYNC_PATH s3://${AWS_S3_BUCKET} ${S3_CACHE_OPTIONS} ${S3_OPTIONS}"`
	if [ $? -eq 0 ]; then
		echo "All html, font, image, map and media files are Deployed without gzip encoding!"
	else
		echo "Deployment Failed  - $result"
		exit 1
	fi

	# S3_OPTIONS="--exclude '*' --include '*.txt' --include '*.js' --include '*.css' --content-encoding gzip"
    searchpath=${AWS_S3_SOURCE_SYNC_PATH}
    lengthofsearchpath=$(echo ${#searchpath}) 
    lengthofsearchpath=$((lengthofsearchpath+1))
	for syncfilepath in $(find ${searchpath} -name '*.js' -o -name '*.txt' -o -name '*.css'); 
	do 
        echo "$syncfilepath"
        uploadpath=$(echo $syncfilepath | cut -b ${lengthofsearchpath}-)
        echo $uploadpath
        getformatdetails=$(file ${syncfilepath})
        if [[ $getformatdetails == *"ASCII"* ]] || [[ $getformatdetails == *"UTF"* ]] || [[ $getformatdetails == *"empty"* ]]; 
        then
            echo "file format is ASCII and skipping gzip option"
            S3_OPTIONS=""
        else 
            echo $getformatdetails
            S3_OPTIONS="--content-encoding gzip"
        fi

        echo aws s3 cp --dryrun $syncfilepath s3://${AWS_S3_BUCKET}${uploadpath} ${S3_CACHE_OPTIONS} ${S3_OPTIONS}
        eval "aws s3 cp --dryrun $syncfilepath s3://${AWS_S3_BUCKET}${uploadpath} ${S3_CACHE_OPTIONS} ${S3_OPTIONS}"
        result=`eval "aws s3 cp $syncfilepath s3://${AWS_S3_BUCKET}${uploadpath} ${S3_CACHE_OPTIONS} ${S3_OPTIONS}"`
        if [ $? -eq 0 ]; then
            echo "File Deployed!"
        else
            echo "Deployment Failed  - $result"
            exit 1
        fi
    done;
}

check_invalidation_status() {
    INVALIDATE_ID=$1
    counter=0
    echo "invalidating cache with ID $INVALIDATE_ID"
    sleep 60
    invalidatestatus=`aws cloudfront get-invalidation --distribution-id $AWS_CLOUD_FRONT_ID --id $INVALIDATE_ID | $JQ '.Invalidation.Status'`
    
    while [[ $invalidatestatus != *"Completed"* ]]
    do
        echo $invalidatestatus
        echo "Waiting for 15 sec and try to check the invalidation status..."
        sleep 15
        invalidatestatus=`aws cloudfront get-invalidation --distribution-id $AWS_CLOUD_FRONT_ID --id $INVALIDATE_ID | $JQ '.Invalidation.Status'`
        counter=`expr $counter + 1`
        if [[ $counter -gt $COUNTER_LIMIT ]] ; then
            echo "Invalidation does not complete with in 180 seconds. Please check the GUI mode."
            exit 1
        fi
    done
    echo "Invalidation completed"
}

invalidate_cf_cache()
{
    if [ "$CFCACHE" = "true" ]; then
         if [ -z $AWS_CLOUD_FRONT_ID ]; then
            echo "Based on header applicaiton has invalidated"
            echo "Skipped which is based on AWS cloudfront ID.Kindly raise request to configure cloud front ID in deployment configuration"
         else
            #aws cloudfront create-invalidation --distribution-id $AWS_CLOUD_FRONT_ID --paths '/*'
            INVALIDATE_ID=`aws cloudfront create-invalidation --distribution-id $AWS_CLOUD_FRONT_ID --paths '/*' | $JQ '.Invalidation.Id'`
            check_invalidation_status "$INVALIDATE_ID"
         fi
    fi
}

download_envfile()
{
    Buffer_seclist=$(echo $SEC_LIST | sed 's/,/ /g' )
    for listname in $Buffer_seclist;
    do
        aws s3 cp s3://tc-platform-${ENV_CONFIG}/securitymanager/$listname.json .
	    track_error $? "$listname.json download"
        jq 'keys[]' $listname.json
        track_error $? "$listname.json"
        #cp $HOME/buildscript/securitymanager/$listname.json.enc .
        #SECPASSWD=$(eval "echo \$${listname}")
        #openssl enc -aes-256-cbc -d -md MD5 -in $listname.json.enc -out $listname.json -k $SECPASSWD
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

decrypt_fileenc()
{
    Buffer_seclist=$(echo $SEC_LIST | sed 's/,/ /g' )
    for listname in $Buffer_seclist;
    do
        #aws s3 cp s3://tc-platform-dev/securitymanager/$listname.json .
        #cp $HOME/buildscript/securitymanager/$listname.json.enc .
        SECPASSWD=$(eval "echo \$${listname}")
        openssl enc -aes-256-cbc -d -md MD5 -in $listname.json.enc -out $listname.json -k $SECPASSWD
    done
}

uploading_envvar()
{
    Buffer_seclist=$(echo $SEC_LIST | sed 's/,/ /g')
    for listname in $Buffer_seclist;
    do
    #   for envappvar in $( cat $listname.json | jq  -r ' . ' | jq ' . | to_entries | map(select(.key | test("AWS.") ) ) | from_entries'  | jq -r "to_entries|map(\"\(.key)=\(.value|tostring)\")|.[]" ); do
    #       export $envappvar
    #   done
        o=$IFS
        IFS=$(echo -en "\n\b")
        envvars=$( cat $listname.json  | jq  -r ' .awsdeployvar ' | jq ' . | to_entries[] | { "name": .key , "value": .value } ' | jq -s . )
        for s in $(echo $envvars | jq -c ".[]" ); do
            #echo $envvars
            varname=$(echo $s| jq -r ".name")
            varvalue=$(echo $s| jq -r ".value")
            export "$varname"="$varvalue"
        done
        IFS=$o 
    done
}

configure_Lambda_template()
{
    if [ "$AWS_LAMBDA_DEPLOY_TYPE" == "SLS" ]
    then
        mkdir -p /home/circleci/project/config
        Buffer_seclist=$(echo $SEC_LIST | sed 's/,/ /g')
	    #envvars=$( cat $listname.json | jq  -c ' .app_var ')

        for listname in $Buffer_seclist;
        do
            o=$IFS
            IFS=$(echo -en "\n\b")
            envvars=$( cat $listname.json | jq  -c ' . ')	     
            echo "$envvars" > /home/circleci/project/config/$AWS_LAMBDA_STAGE.json
            sed -i 's/\\n/\\\\n/g' /home/circleci/project/config/$AWS_LAMBDA_STAGE.json

            #yq r $listname.json  >$listname.yml
            #a=serverless.yml
            #b="$listname.json"
            #python -c "import sys; from ruamel.yaml import YAML; yaml = YAML(); cfg = yaml.load(open('$a','r')); cfg_env = yaml.load(open('$b','r')); cfg['Resources']['tcdevhandler']['Properties']['Environment']['Variables']=cfg_env['app_var'] ; yaml.dump(cfg, open('appeneded.yaml', 'w'))"
            #python -c "import sys; from ruamel.yaml import YAML; yaml = YAML(); cfg = yaml.load(open('$a','r')); cfg_env = yaml.load(open('$b','r')); cfg['provider']['environment']=cfg_env['app_var'] ; yaml.dump(cfg, open('appeneded.yaml', 'w'))"
            #python -c "import sys , json , ruamel.yaml , cStringIO; jsondata = cStringIO.StringIO(); yaml = ruamel.yaml.YAML(); yaml.explicit_start = True; data = json.load(open('$b','r'), object_pairs_hook=ruamel.yaml.comments.CommentedMap) ; ruamel.yaml.scalarstring.walk_tree(data) ; yaml.dump(data, jsondata); cfg = yaml.load(open('$a','r')); cfg_env = yaml.load(jsondata.getvalue()); cfg['Resources']['tcdevhandler']['Properties']['Environment']['Variables']=cfg_env['app_var'] ; yaml.dump(cfg, open('appeneded.yaml', 'w'))"
            #python -c "import sys , json , ruamel.yaml , cStringIO; jsondata = cStringIO.StringIO(); yaml = ruamel.yaml.YAML(); yaml.explicit_start = True; data = json.load(open('$b','r'), object_pairs_hook=ruamel.yaml.comments.CommentedMap) ; ruamel.yaml.scalarstring.walk_tree(data) ; yaml.dump(data, jsondata); cfg = yaml.load(open('$a','r')); cfg_env = yaml.load(jsondata.getvalue()); cfg['provider']['environment']=cfg_env['app_var'] ; yaml.dump(cfg, open('appeneded.yaml', 'w'))"
            #python -c "import sys , json , ruamel.yaml ; from io import BytesIO as StringIO ; jsondata = StringIO(); yaml = ruamel.yaml.YAML(); yaml.explicit_start = True; data = json.load(open('$b','r'), object_pairs_hook=ruamel.yaml.comments.CommentedMap) ; ruamel.yaml.scalarstring.walk_tree(data) ; yaml.dump(data, jsondata); cfg = yaml.load(open('$a','r')); cfg_env= yaml.load(jsondata.getvalue()); cfg['provider']['environment']=cfg_env['app_var'] ; yaml.dump(cfg, open('appeneded.yaml','w'))"
            #python -c "import sys , json , ruamel.yaml ; from io import BytesIO as StringIO ; jsondata = StringIO(); yaml = ruamel.yaml.YAML(); data = json.load(open('$b','r')) ; yaml.dump(data, jsondata); cfg = yaml.load(open('$a','r')); cfg_env= yaml.load(jsondata.getvalue()); cfg['provider']['environment']=cfg_env['app_var'] ; yaml.dump(cfg, open('appeneded.yaml','w'))"
            #mv -f appeneded.yaml serverless.yml 
       done
       IFS=$o 
    fi
}

deploy_lambda_package()
{
   # sls deploy
    if [ "$AWS_LAMBDA_DEPLOY_TYPE" == "SLS" ]
    then
         echo "Welcome to lambda SLS deploy"
         sls deploy --stage $AWS_LAMBDA_STAGE
    fi
}

# decrypt_aws_sys_parameter()
# {

#    for future implmentation.
# }

# Input Collection and validation
input_parsing_validation()
{
    while getopts .d:h:i:e:l:t:v:s:p:g:c:m:. OPTION
    do
        case $OPTION in
            d)
                DEPLOYMENT_TYPE=$OPTARG
                ;;
            h)
                usage
                exit 1
                ;;
            i)
                APP_IMAGE_NAME=$OPTARG
                ;;
            e)
                ENV=$OPTARG
                ;;
            l)
                SECPS_LIST=$OPTARG
                ;;
            t)
                TAG=$OPTARG
                ;;
            c)
                CFCACHE=$OPTARG
                ;;			 
            v)
                EBS_APPVER=$OPTARG
                ;;
            s)
                SEC_LIST=$OPTARG
                ;;
            p)
                ECS_TEMPLATE_TYPE=$OPTARG
                ;;
            g)
                SHARED_PROPERTY_FILENAME=$OPTARG
                ;;
            m)
                DEPLOYCATEGORY=$OPTARG
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
    log "app variable list      :       $SEC_LIST"
    ENV_CONFIG=`echo "$ENV" | tr '[:upper:]' '[:lower:]'`

    #Validating AWS configuration

    #Getting Deployment varaible only

    # AWS_ACCESS_KEY_ID=$(eval "echo \$${ENV}_AWS_ACCESS_KEY_ID")
    # AWS_SECRET_ACCESS_KEY=$(eval "echo \$${ENV}_AWS_SECRET_ACCESS_KEY")
    # AWS_ACCOUNT_ID=$(eval "echo \$${ENV}_AWS_ACCOUNT_ID")
    # AWS_REGION=$(eval "echo \$${ENV}_AWS_REGION")
    # if [ -z $AWS_ACCESS_KEY_ID ] || [ -z $AWS_SECRET_ACCESS_KEY ] || [ -z $AWS_ACCOUNT_ID ] || [ -z $AWS_REGION ];
    # then
    #      log "AWS Secret Parameters are not configured in circleci/environment"
    #      usage
    #      exit 1
    # else
    #      configure_aws_cli
    #      #aws configure list
    # fi

    download_envfile

    if [ -z $SECPS_LIST ];
    then
        log "No secret parameter file list provided"
    else
        download_psfile
    fi

    #decrypt_fileenc
    #uploading_envvar

    #Validating parameter based on Deployment type
    #ECS parameter validation
    if [ "$DEPLOYMENT_TYPE" == "ECS" ]
    then
        ECS_TAG=$TAG
        if [ "$DEPLOYCATEGORY" == "CLI" ]
        then
            if [ -z $AWS_REPOSITORY ] || [ -z $AWS_ECS_CLUSTER ] || [ -z $AWS_ECS_SERVICE ] || [ -z $ECS_TAG ];
            then
                log "Deployment varibale are not updated. Please check tag option was provided. Also ensure AWS_REPOSITORY, AWS_ECS_TASK_FAMILY,AWS_ECS_CONTAINER_NAME,AWS_ECS_PORTS,AWS_ECS_CLUSTER and AWS_ECS_SERVICE variables are configured on secret manager"
                usage
                exit 1
            fi
            DEPLOYCATEGORYNAME="ECSCLI"
        else
            cp $HOME/buildscript/$TEMPLATE_SKELETON_FILE .

            if [ -z $AWS_REPOSITORY ] || [ -z $AWS_ECS_CLUSTER ] || [ -z $AWS_ECS_SERVICE ] || [ -z $AWS_ECS_TASK_FAMILY ] || [ -z $AWS_ECS_CONTAINER_NAME ] || [ -z $AWS_ECS_PORTS ] || [ -z $ECS_TAG ];
            then
                log "Deployment varibale are not updated. Please check tag option was provided. Also ensure AWS_REPOSITORY, AWS_ECS_TASK_FAMILY,AWS_ECS_CONTAINER_NAME,AWS_ECS_PORTS,AWS_ECS_CLUSTER and AWS_ECS_SERVICE variables are configured on secret manager"
                usage
                exit 1
            fi
            DEPLOYCATEGORYNAME="AWSCLI"
        fi
            
        log "AWS_REPOSITORY          :  $AWS_REPOSITORY"
        log "AWS_ECS_CLUSTER         :  $AWS_ECS_CLUSTER"
        log "AWS_ECS_SERVICE_NAMES   :  $AWS_ECS_SERVICE"
        log "AWS_ECS_TASK_FAMILY     :  $AWS_ECS_TASK_FAMILY"
        log "AWS_ECS_CONTAINER_NAME  :  $AWS_ECS_CONTAINER_NAME"
        log "AWS_ECS_PORTS           :  $AWS_ECS_PORTS"
        log "ECS_TAG                 :  $ECS_TAG"
        log "DEPLOY TYPE             :  $DEPLOYCATEGORYNAME"
    fi

    #EBS parameter validation
    if [ "$DEPLOYMENT_TYPE" == "EBS" ]
    then
        # EBS_TAG = the docker image tag for example dev.201807051535
        cp $HOME/buildscript/$EBS_TEMPLATE_SKELETON_FILE .
        EBS_TAG=$TAG
        AWS_EBS_APPVER="${AWS_EBS_ENV_NAME}-${EBS_TAG}"
        IMG_WITH_EBS_TAG="${DOCKER_IMAGE_NAME}:${EBS_TAG}"
        #   EBS_TAG="${IMAGE_NAME}:${ENV_CONFIG}.${EBS_APPVER}"

        if [ "$AWS_S3_KEY_LOCATION" = "" ] ;
        then
            AWS_S3_KEY="${IMG_WITH_EBS_TAG}"
        else
            AWS_S3_KEY="$AWS_S3_KEY_LOCATION/${IMG_WITH_EBS_TAG}"
        fi

        #AWS_EBS_EB_DOCKERRUN_TEMPLATE_LOCATION=$(eval "echo \$${ENV}_AWS_EBS_EB_DOCKERRUN_TEMPLATE_LOCATION")
        #AWS_EBS_DOCKERRUN_TEMPLATE=$(eval "echo \$${ENV}_AWS_EBS_DOCKERRUN_TEMPLATE")
        if [ -z $AWS_EBS_APPLICATION_NAME ] || [ -z $DOCKER_IMAGE_NAME ] || [ -z $AWS_EBS_ENV_NAME ] || [ -z $EBS_TAG ] || [ -z $AWS_EBS_APPVER ] || [ -z $AWS_S3_BUCKET ] ;
        then
            log "Build variables are not updated. Please update the Build variable file"
            usage
            exit 1
        fi

        log "EBS_APPLICATION_NAME    :  $AWS_EBS_APPLICATION_NAME"
        log "AWS_EBS_APPVER	       :  $AWS_EBS_APPVER"
        log "EBS_TAG                 :  $EBS_TAG"
        log "AWS_S3_BUCKET           :  $AWS_S3_BUCKET"
        log "AWS_S3_KEY              :  $AWS_S3_KEY"
        log "AWS_EB_ENV              :  $AWS_EBS_ENV_NAME"
    fi

    #CloudFront parameter validation
    if [ "$DEPLOYMENT_TYPE" == "CFRONT" ]
    then
        if [ -z $AWS_S3_BUCKET ] || [ -z $AWS_S3_SOURCE_SYNC_PATH ];
        then
            log "Build variables are not updated. Please update the Build variable file"
            usage
            exit 1
        fi
        log "AWS_S3_BUCKET           :  $AWS_S3_BUCKET"
        log "AWS_S3_SOURCE_SYNC_PATH :  $AWS_S3_SOURCE_SYNC_PATH"
    fi

    #Lambda parameter validation
    if [ "$DEPLOYMENT_TYPE" == "LAMBDA" ]
    then
        if [ -z $AWS_LAMBDA_DEPLOY_TYPE ] ;
        then
            log "Build variables are not updated. Please update the Build variable file"
            usage
            exit 1
        fi
        log "AWS_LAMBDA_DEPLOY_TYPE  :  $AWS_LAMBDA_DEPLOY_TYPE"
  
        if [ -z $AWS_LAMBDA_STAGE ] ;
        then
            log "Build variables are not updated. Please update the Build variable file"
            usage
            exit 1
        fi
        log "AWS_LAMBDA_STAGE        :  $AWS_LAMBDA_STAGE"  
    fi
}

# Main
main()
{
    input_parsing_validation $@

    if [ "$DEPLOYMENT_TYPE" == "ECS" ]
    then
        if [ "$DEPLOYCATEGORY" == "CLI" ]
        then
            eval $(aws ecr get-login --region $AWS_REGION --no-include-email)

            # Moving image to repository
            if [ -z $APP_IMAGE_NAME ];
            then
                echo "Value of AWS_REPOSITORY: " $AWS_REPOSITORY
                AWS_REPOSITORY_NAMES=$(echo ${AWS_REPOSITORY} | sed 's/,/ /g')
                echo "Value of AWS_REPOSITORY_NAMES: " $AWS_REPOSITORY_NAMES

                IFS=' ' read -a AWS_REPOSITORY_NAMES_ARRAY <<< $AWS_REPOSITORY_NAMES
                if [ ${#AWS_REPOSITORY_NAMES_ARRAY[@]} -gt 0 ]; then
                    echo "${#AWS_REPOSITORY_NAMES_ARRAY[@]} repo push initalisation"
                    for AWS_ECS_REPO_NAME in "${AWS_REPOSITORY_NAMES_ARRAY[@]}"
                    do
                        echo "updating reposioty - $AWS_ECS_REPO_NAME"
                        ECSCLI_push_ecr_image $AWS_ECS_REPO_NAME
                        #echo $REVISION
                    done
                else
                    echo "Kindly check the Repository name has Parameter"
                    usage
                    exit 1
                fi
            else
                #if appp images details are provided

                echo "value of AWS_REPOSITORY " $AWS_REPOSITORY
                AWS_REPOSITORY_NAMES=$(echo ${AWS_REPOSITORY} | sed 's/,/ /g')
                echo "value of AWS_REPOSITORY_NAMES " $AWS_REPOSITORY_NAMES
                echo "value of image name provided " $APP_IMAGE_NAME
                APP_IMAGE_NAMES=$(echo ${APP_IMAGE_NAME} | sed 's/,/ /g')

                IFS=' ' read -a AWS_REPOSITORY_NAMES_ARRAY <<< $AWS_REPOSITORY_NAMES
                IFS=' ' read -a APP_IMAGE_NAMES_ARRAY <<< $APP_IMAGE_NAMES
                echo "AWS ECR repo count needs to be updated ${#AWS_REPOSITORY_NAMES_ARRAY[@]}, APP image count provided in option ${#APP_IMAGE_NAMES_ARRAY[@]} "
                
                if [ "${#AWS_REPOSITORY_NAMES_ARRAY[@]}" = "${#APP_IMAGE_NAMES_ARRAY[@]}" ];
                then
                    ecstempcount=0
                    while [ $ecstempcount -lt ${#AWS_REPOSITORY_NAMES_ARRAY[@]} ]
                    do
                        echo "${AWS_REPOSITORY_NAMES_ARRAY[$count]} , ${APP_IMAGE_NAMES_ARRAY[$count]}"
                        ECSCLI_push_ecr_image "${AWS_REPOSITORY_NAMES_ARRAY[$count]}" "${APP_IMAGE_NAMES_ARRAY[$count]}"
                        ecstempcount=`expr $ecstempcount + 1`
                    done
                else
                    echo "Kindly check the image name in Parameter"
                    usage
                    exit 1
                fi
            fi

            #env file updation
            ECSCLI_update_env

            # Configuring cluster
            ecs-cli configure --region us-east-1 --cluster $AWS_ECS_CLUSTER

            # updating service
            echo "Value of AWS_ECS_SERVICE: " $AWS_ECS_SERVICE
            AWS_ECS_SERVICE_NAMES=$(echo ${AWS_ECS_SERVICE} | sed 's/,/ /g')
            #AWS_ECS_SERVICE_NAMES=$(echo ${AWS_ECS_SERVICE} | sed 's/,/ /g' | sed 'N;s/\n//')
            echo "Value of AWS_ECS_SERVICE_NAMES: " $AWS_ECS_SERVICE_NAMES

            IFS=' ' read -a AWS_ECS_SERVICES <<< $AWS_ECS_SERVICE_NAMES
            if [ ${#AWS_ECS_SERVICES[@]} -gt 0 ]; then
                echo "${#AWS_ECS_SERVICES[@]} service(s) are going to be updated"
                for AWS_ECS_SERVICE_NAME in "${AWS_ECS_SERVICES[@]}"
                do
                    echo "updating ECS Cluster Service - $AWS_ECS_SERVICE_NAME"
                    ecs-cli compose --project-name "$AWS_ECS_SERVICE_NAME" service up
                    #echo $REVISION
                done
            else
                echo "Kindly check the service name in Parameter"
                usage
                exit 1
            fi
        else
            validate_update_loggroup
            ECS_push_ecr_image
            ECS_template_create_register

            echo "Value of AWS_ECS_SERVICE: " $AWS_ECS_SERVICE
            AWS_ECS_SERVICE_NAMES=$(echo ${AWS_ECS_SERVICE} | sed 's/,/ /g')
            #AWS_ECS_SERVICE_NAMES=$(echo ${AWS_ECS_SERVICE} | sed 's/,/ /g' | sed 'N;s/\n//')
            echo "Value of AWS_ECS_SERVICE_NAMES: " $AWS_ECS_SERVICE_NAMES

            IFS=' ' read -a AWS_ECS_SERVICES <<< $AWS_ECS_SERVICE_NAMES
            if [ ${#AWS_ECS_SERVICES[@]} -gt 0 ]; then
                echo "${#AWS_ECS_SERVICES[@]} service are going to be updated"
                for AWS_ECS_SERVICE_NAME in "${AWS_ECS_SERVICES[@]}"
                do
                    echo "Creating/updating ECS Cluster Service - $AWS_ECS_SERVICE_NAME"
                    ECS_deploy_cluster "$AWS_ECS_SERVICE_NAME"
                    check_service_status "$AWS_ECS_SERVICE_NAME"
                    #echo $REVISION
                done
            else
                echo "Kindly check the service name parameter"
                usage
                exit 1
            fi
        fi
    fi

    if [ "$DEPLOYMENT_TYPE" == "EBS" ]
    then
        #configure_aws_cli
        configure_docker_private_login
        EBS_push_docker_image
        creating_updating_ebs_docker_json
        creating_updating_EBS_appversion
    fi

    if [ "$DEPLOYMENT_TYPE" == "CFRONT" ]
    then
        deploy_s3bucket
        invalidate_cf_cache
    fi

    if [ "$DEPLOYMENT_TYPE" == "LAMBDA" ]
    then
        configure_Lambda_template
        deploy_lambda_package
    fi
}

main $@
