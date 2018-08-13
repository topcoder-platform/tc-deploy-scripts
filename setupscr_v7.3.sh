#!/bin/bash
#set -x
MODIFY=0
KEYNAME=""
KEYVALUE=""
KEYTYPE=""
FILENAME=""
FILENAME_WITH_JSON_EXT=""
ENVTYPE=""
vartemplate="{}"
SECPASSWD=""
SEC_LIST5=""
DTYPE=""

read_json()
{
  vartemplate=$( cat $FILENAME_WITH_JSON_EXT )
}
write_to_json()
{
  echo $vartemplate > $FILENAME_WITH_JSON_EXT
}
add_number_type()
{
   VARNAME=$1
   VARVALUE=$2
   CATEGORY=$3
   read_json
   vartemplate=$(echo $vartemplate | jq --arg VARNAME "$VARNAME" --argjson VARVALUE $VARVALUE --arg CATEGORY "$CATEGORY" '.[$CATEGORY] |= . + {($VARNAME): $VARVALUE}')
   if [ "$?" = "0" ]; then
       write_to_json
   fi  
   #echo "adding number variable in json"
}
add_string_type()
{
   VARNAME=$1
   VARVALUE=$2
   CATEGORY=$3   
   read_json
   vartemplate=$(echo $vartemplate | jq --arg VARNAME "$VARNAME" --arg VARVALUE "$VARVALUE" --arg CATEGORY "$CATEGORY" '.[$CATEGORY] |= . + {($VARNAME): $VARVALUE}')
   if [ "$?" = "0" ]; then
       echo "testing write to json"
       write_to_json
   fi 
   #echo "adding string variable in json"    
}
add_variable()
{
    MBUF=$1
    CATEGORY=""
    if [ -z $MBUF ];
    then
        CATEGORY="app_var"
    else
        read -e -p "Default modification will be app variable, if aws env var press e : " CTYPE
        if [ "$CTYPE" = "e" ];
        then
            CATEGORY="awsdeployvar"
        else
            CATEGORY="app_var"
        fi
    fi
    KEYTYPE=""
    read -e -p "Please enter the variable name :  " KEYNAME
    read -e -p "Default value type is string, if NUMBER press n or If certifcate press c or enter:  " KEYTYPE
    if [ "$KEYTYPE" = "c" ];
    then
      read -d "~" -p "Enter the key comment (\"~\" when done):" KEYVALUE
    else
      read -e -n 2048 -p "Please enter the variable value :  " KEYVALUE
    fi     
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper key and value"
    else
        if [ -z "$KEYTYPE" ];
        then
            add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
        elif [ "$KEYTYPE" = "n" ];
        then
            add_number_type "$KEYNAME" $KEYVALUE "$CATEGORY"
        else
            add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
        fi
    fi    
}
modify_number_type()
{
   VARNAME=$1
   VARVALUE=$2
   CATEGORY=$3
   read_json   
   vartemplate=$(echo $vartemplate | jq --arg VARNAME "$VARNAME" --argjson VARVALUE $VARVALUE --arg CATEGORY "$CATEGORY" '.[$CATEGORY] |= . + {($VARNAME): $VARVALUE}')
   if [ "$?" = "0" ]; then
       write_to_json
   fi    
  # echo "adding number variable in json"
}
modify_string_type()
{
   VARNAME=$1
   VARVALUE=$2
   CATEGORY=$3
   read_json   
   vartemplate=$(echo $vartemplate | jq --arg VARNAME "$VARNAME" --arg VARVALUE "$VARVALUE" --arg CATEGORY "$CATEGORY" '.[$CATEGORY] |= . + {($VARNAME): $VARVALUE}')
   if [ "$?" = "0" ]; then
       write_to_json
   fi 
  # echo "adding string variable in json"    
}
modify_var()
{
    echo "modify"
    KEYTYPE=""
    CATEGORY=""
    read -e -p "Default modification is app variable, if aws env var - press e : " CTYPE
    if [ "$CTYPE" = "e" ];
    then
        CATEGORY="awsdeployvar"
    else
        CATEGORY="app_var"
    fi
    read -e -p "Please enter the modifying variable name :  " KEYNAME
    read -e -p "Press enter to set default value type as STRING, if NUMBER press n or CERTIFICATE(like kafka) press c :  " KEYTYPE
    if [ "$KEYTYPE" = "c" ];
    then
      read -d "~" -p "Enter the modified key (\"~\" when done):" KEYVALUE
    else
      read -e -n 2048 -p "Please enter the modifying variable value :  " KEYVALUE
    fi
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper key and value"
    else
        if [ -z "$KEYTYPE" ];
        then
            modify_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
        elif [ "$KEYTYPE" = "n" ];
        then
            modify_number_type "$KEYNAME" $KEYVALUE "$CATEGORY"
        else
            modify_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
        fi
    fi     
}
delete_var()
{
    echo "Delet var"
    read_json    
    CATEGORY=""
    read -e -p "Default deletion will be app variable, if aws env var press e : " CTYPE
    if [ "$CTYPE" = "e" ];
    then
        CATEGORY="awsdeployvar"
    else
        CATEGORY="app_var"
    fi
    read -e -p "Please enter the variable name to delete :  " KEYNAME
    vartemplate=$(echo $vartemplate | jq --arg CATEGORY "$CATEGORY" --arg KEYNAME "$KEYNAME" 'delpaths([[$CATEGORY,$KEYNAME]])' )
    if [ "$?" = "0" ]; then
       write_to_json
   fi 
}
list_var()
{
    cat $FILENAME_WITH_JSON_EXT | jq -r "."
}
ecs_mandate_var()
{
    CATEGORY="awsdeployvar"
    echo "adding ECS mandate var"
    KEYNAME="AWS_REPOSITORY"
    read -e -p "Please enter the AWS Repository Name :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper Repo Name"
        exit
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi 
    KEYNAME="AWS_ECS_CLUSTER"
    read -e -p "Please enter the AWS Cluster Name :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper Cluster name"
        exit       
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi   
    KEYNAME="AWS_ECS_SERVICE"
    read -e -p "Please enter the AWS Service Name if multiple it need to be comma seperated without space :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper AWS Cluster Service names"
        exit       
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi 
    KEYNAME="AWS_ECS_TASK_FAMILY"
    read -e -p "Please enter the AWS Task Definition  Name :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper AWS Task Definition Name"
        exit
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi 
    KEYNAME="AWS_ECS_CONTAINER_NAME"
    read -e -p "Please enter the AWS Container name as per task Definition  :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper AWS Container name as per task Definition"
        exit
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi
    KEYNAME="AWS_ECS_PORTS"
    read -e -p "Please enter the Port info like hostport:containerport:protocol,hostport:containerport:protocol  :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper AWS proper port"
        exit
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi     
}
ebs_mandate_var()
{
    CATEGORY="awsdeployvar"
    echo "adding EBS mandate var"
    KEYNAME="AWS_EBS_APPLICATION_NAME"
    read -e -p "Please enter the AWS EBS Application Name :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper Application Name"
        exit
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi 
    KEYNAME="AWS_EBS_ENV_NAME"
    read -e -p "Please enter the AWS EBS Environment Name :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper EBS Environment name"
        exit       
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi   
    KEYNAME="AWS_S3_BUCKET"
    read -e -p "Please enter the AWS S3 Bucket name like where application json upload :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper AWS S3 bucket name"
        exit       
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi 
    KEYNAME="AWS_S3_KEY_LOCATION"
    read -e -p "If you add application json in specific path in S3, please specify :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "No S3 key location has provided. So application json will upload in root folder of S3 bucket"
        #exit
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi 
    KEYNAME="DOCKER_IMAGE_NAME"
    read -e -p "Please provide the name docker image  :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper AWS container name as per task Definition"
        exit
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi
    KEYNAME="DOCKER_REGISTRY_NAME"
    KEYVALUE="appiriodevops"
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper AWS proper port"
        exit
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi     
    KEYNAME="EBS_EB_EXTENSTION_LOCATION"
    read -e -p "If you have .ebextension folder, please specify path where it exists in repository without .ebextension name :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "No ebextesion exist. So application json will upload of S3 bucket"
        #exit
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi

}
cfront_mandate_var()
{
    CATEGORY="awsdeployvar"
    echo "adding CFRONT mandate var"
    KEYNAME="AWS_S3_BUCKET"
    read -e -p "Please enter the AWS S3 Bucket name like where application upload :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper AWS S3 bucket name"
        exit       
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi 
    KEYNAME="AWS_S3_SOURCE_SYNC_PATH"
    read -e -p "Please enter the source path need to be synced :  " KEYVALUE
    if [ -z "$KEYNAME" ] || [ -z "$KEYVALUE" ] ;
    then 
        echo "Please provide proper source path"
        exit       
    else
        add_string_type "$KEYNAME" "$KEYVALUE" "$CATEGORY"
    fi   

}
add_mandate_var()
{
    DTYPE=""
    read -e -p "Please enter the deployment type (ECS/EBS/CFRONT):  " DTYPE
    case $DTYPE in
        ECS ) ecs_mandate_var
                ;;
        EBS ) ebs_mandate_var
                ;;
        CFRONT ) cfront_mandate_var
                ;;                
        * ) echo "Please proper deploy type"
            exit
            ;;
    esac 
}
createenv()
{
    echo "creating new environment"
    add_mandate_var
    while true; do
        read -e -p "Do you want to add environment variable(s) (y/n)?" yn
        case $yn in
            [Yy]* ) add_variable
                    ;;
            [Nn]* ) break;;
            * ) echo "Please answer yes or no.";;
        esac
    done    
}
modifyenv()
{
    echo "Modifying the existing environment"
    echo "Please find the existing variable details given below : "
    while true; do
        echo "Please choose the option"
        echo "1 . Add variable"
        echo "2 . Modify variable"
        echo "3 . Delete variable"
        echo "4 . List variable"        
        echo "5 . Exit the Modification"
        read -e -p "Plese enter teh option number : " opt
        case $opt in
            1 ) add_variable "MODIFY"
                ;;
            2 ) modify_var
                ;;
            3 ) delete_var
                ;; 
            4 ) list_var
                ;;                                                         
            5 ) break;;
            * ) echo "Please enter right option";;
        esac
    done
}

encrypt_file()
{
    echo "Encypt option has enabled"
	openssl enc -aes-256-cbc -salt -md MD5 -in $FILENAME_WITH_JSON_EXT -out $FILENAME_WITH_JSONENC_EXT -k "$SECPASSWD"
	if [ "$?" != "0" ]; then
		echo "$(tput setaf 1)File Encryption failed with error code $?$(tput setaf 7)"
		exit 1
	else 
		echo "$(tput setaf 2)$FILENAME_WITH_JSON_EXT encrypted to $(tput setaf 3)$FILENAME_WITH_JSONENC_EXT.$(tput setaf 2) Use Decrypt option to view$(tput setaf 7)"
	fi
}

decrypt_file()
{
    echo "Decypt option has enabled"
	openssl enc -aes-256-cbc -d -md MD5 -in $FILENAME_WITH_JSONENC_EXT -out $FILENAME_WITH_JSON_EXT -k "$SECPASSWD"
	if [ "$?" != "0" ]; then
		echo "$(tput setaf 1)File decryption failed with error code $?$(tput setaf 7)"
		exit 1
	else 
		echo "$(tput setaf 2)File Decryption completed$. (tput setaf 7)"
	fi
}
#nk- added
 validate_file_json_schema()
 {    

    # schema_template.json
    json validate --schema-file=template/$DTYPE/schema_template.json --document-file=$FILENAME.json
    if [ "$?" != "0" ]; then
        echo "$(tput setaf 1)=======Input file json schema validation failed=====$(tput setaf 7)"
		exit 1
    else
        echo "$(tput setaf 2)========Input file json schema is valid=========$(tput setaf 7)"
        sleep 2
    fi
 }

 #nk- added
 validate_file_json_values()
 {

            local o=$IFS
            IFS=$(echo -en "\n\b")
            envvars=$( cat $FILENAME.json | jq  -r ' .app_var ' | jq ' . | to_entries[] | { "name": .key , "value": .value } ' | jq -s . )
            for s in $(echo $envvars | jq -c ".[]" ); do
            #echo $envvars
                varname=$(echo $s| jq -r ".name")
                varvalue=$(echo $s| jq -r ".value")
                echo " $varname : $varvalue"
            done
            IFS=$o  
         echo "$(tput setaf 2)================json syntax value valid==========$(tput setaf 7)"
         sleep 2
         
 }

user_information()
{
   # echo "Next Step"
   circleadd1=""
    echo -e "\n$(tput setaf 3)NEXT STEP \n-A)  Upload $FILENAMEBUF.json to Dev/Prod S3. Bucket tc-platform-<env>/securitymanager \n$(tput setaf 7)"
    echo -e "$(tput setaf 3)NEXT STEP \n-B)  Navigate to your app Git Repo, Append the following 2 line at .circleci/config.yml\n$(tput setaf 7)"
    echo -e "---1. COPY LINE 1 AS SHOWN BELOW (Before  $(tput setaf 4)- checkout $(tput setaf 7)) section \n"
    circleadd1="- run: git clone --branch master https://github.com/topcoder-platform/tc-deploy-scripts ../buildscript$"
    circleadd2="      ./master_deply_v3.sh -e DEV -t \$CIRCLE_SHA1 -s $FILENAMEBUF"
    echo $(tput setaf 2)$circleadd1$(tput setaf 7)
    echo -e "\n---2. COPY LINE 2 AS SHOWN BELOW (at $(tput setaf 4)Deploy $(tput setaf 7)section). Change ENV as per Deploy type (for ex: DEV or PROD)"
    { echo $(tput setaf 2)
        echo -e "- deploy:" 
        echo -e "    command: |" 
        echo -e "      echo 'Running MasterScript...'" 
        echo -e "      cp ./../buildscript/master_deply_v4.2.sh ."  
        echo -e "      ./master_deply_v4.2.sh -d ECS -e DEV -t \$CIRCLE_SHA1 -s $FILENAMEBUF" 
       echo $(tput setaf 7)
    }
       # sed -i "" "s|#msadd1|$circleadd1|" ../circleci_template/Sample-Nodejs.yml
       # sed -i "" "s|#msadd2|$circleadd2|" ../circleci_template/Sample-Nodejs.yml

    echo "---3. Pointer to copy -$(tput setaf 3) ../circleci_template/Sample-Nodejs.yml $(tput setaf 7)Search '#msadd1  #msadd2' append Line 1 & Line 2 respectively-------"
    echo -e "\n$(tput setaf 3)FINAL STEP \n-C)  At .config.yml, validate for other project need,Langauge,Format etc. Update branch details. \n\t Check-in. MASTER SCRIPT automatically triggers. Monitor Circleci \n$(tput setaf 7)"
    
}

validateprereq()
{
    jq --version
    if [ $? != 0 ];
    then
        echo "Please install jq in MAC using below command and proceed"
        echo "brew install jq"
        exit
    fi
    #curl -O https://bootstrap.pypa.io/get-pip.py
    #python3 get-pip.py --user
    #pip install json-spec     
    json --version
    if [ $? != 0 ];
    then
        echo 'Please install json spec by running below commands on MAC and proceed'
        echo "curl -O https://bootstrap.pypa.io/get-pip.py"
        echo 'brew install python3'
        echo 'python3 get-pip.py --user'
        echo 'pip3 install json-spec'
        exit
    fi    
}

validateprereq

echo "$(tput setaf 2)Please choose the option below$(tput setaf 7)"
echo "1 . Create new environment"
echo "2 . Modify Existing Environment Variable"     
echo "3 . Validate Variable JSON file"
echo "4 . Exit the script"
read -e -p "Please enter the option number : " opt
if [ "$opt" != "6" ];
then
    read -e -p "Please enter the file name without extension :  " FILENAMEBUF
    #read -e -s -p "Please enter the Encryption Password : " SECPASSWD
    echo ""
    #read -p "Please enter the environment type : " ENVBUFFER
    #ENVTYPE=`echo "$ENVBUFFER" | tr '[:upper:]' '[:lower:]'`
    #FILENAME="$FILENAMEBUF-$ENVTYPE"
    FILENAME="$FILENAMEBUF"
    FILENAME_WITH_JSON_EXT="$FILENAME.json"
    FILENAME_WITH_JSONENC_EXT="$FILENAME_WITH_JSON_EXT.enc"
fi
case $opt in
    1 ) echo "call add fun"
        echo $vartemplate > $FILENAME_WITH_JSON_EXT
        createenv
        #encrypt_file
        #rm -f $FILENAME_WITH_JSON_EXT
        #git clone --branch master https://github.com/topcoder-platform/tc-deploy-scripts.git
        #cp $FILENAME_WITH_JSONENC_EXT tc-deploy-scripts/securitymanager/
        ;;
    2 ) echo "call modify fun"
        #decrypt_file
        #rm -f $FILENAME_WITH_JSONENC_EXT
        modifyenv
        #encrypt_file
        #rm -f $FILENAME_WITH_JSON_EXT
        ;;  
    3 ) 
        echo -e "$(tput setaf 3) Adhere to ../setup_ms/variable_file_template/<templatefile> json format. $(tput setaf 7) \n"
        read -e -p "Please enter deploy type (ECS/EBS/CFRONT) :  " DTYPE 
        validate_file_json_schema
        validate_file_json_values
        ;;                                                             
    4 ) break;;
    * ) echo "Please enter right option"
        exit
        ;;
esac

user_information
