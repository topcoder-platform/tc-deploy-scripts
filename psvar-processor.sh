#!/bin/bash
set -eo pipefail
usage()
{
cat << EOF
usage: $0 options

This script needs to be executed with below options.

OPTIONS:
 -e environment
 -t type appenv,appconf and appjson
 -p parameter store path without final slash
 -l parameter store list  without final slash

EOF
}

create_env_file_format()
{
    file_name=$1
    fetch_path=$2
    echo $fetch_path
    echo $file_name
    aws ssm get-parameters-by-path --with-decryption --path $fetch_path --query "Parameters[*].{Name:Name, Value:Value}" >fetched_parameters.json
    cat fetched_parameters.json | jq -r '.[] | "export " + .Name + "=\"" + .Value + "\""  '  | sed -e "s~$fetch_path/~~" >${file_name}_env
    rm -rf fetched_parameters.json
}

create_conf_file_format()
{
    file_name=$1
    fetch_path=$2
    aws ssm get-parameters-by-path --with-decryption --path $fetch_path --query "Parameters[*].{Name:Name, Value:Value}" >fetched_parameters.json
    cat fetched_parameters.json | jq -r '.[] | .Name + "=\"" + .Value + "\""  '  | sed -e "s~$fetch_path/~~" >${file_name}.conf
    rm -rf fetched_parameters.json    
}

create_json_file_format()
{
    file_name=$1
    fetch_path=$2
    echo $fetch_path
    echo $file_name
    echo "aws ssm get-parameters-by-path --with-decryption --path $fetch_path --query \"Parameters[*].{Name:Name, Value:Value}\""
    aws ssm get-parameters-by-path --with-decryption --path $fetch_path --query "Parameters[*].{Name:Name, Value:Value}" >fetched_parameters.json
    cat fetched_parameters.json | jq  -r ' . |= (map({ (.Name): .Value }) | add)' | sed -e "s~$fetch_path/~~" >${file_name}.json
#    rm -rf fetched_parameters.json    
}

fetching_specific_path()
{   
    type_to_fetch=$1
    PS_PATH=${PS_PATH%/}
    fname=${PS_PATH##*/}
    fpath=$PS_PATH
    echo $fpath
    echo $PS_PATH 
    if [ "$type_to_fetch" == "appenv" ]
    then
        create_env_file_format $fname $fpath
    fi
    if [ "$type_to_fetch" == "appconf" ]
    then
        create_conf_file_format $fname $fpath
    fi
    if [ "$type_to_fetch" == "appjson" ]
    then
        create_json_file_format $fname $fpath
    fi    
}

fetching_multiple_path()
{
    type_to_fetch=$1
    Buffer_seclist=$(echo $PS_PATH_LIST | sed 's/,/ /g' )
    for listname in $Buffer_seclist;
    do
        listname=${listname%/}
        fname=${listname##*/}
        fpath=$listname
        if [ "$type_to_fetch" == "appenv" ]
        then
            create_env_file_format $fname $fpath
        fi
        if [ "$type_to_fetch" == "appconf" ]
        then
            create_conf_file_format $fname $fpath
        fi
        if [ "$type_to_fetch" == "appjson" ]
        then
            create_json_file_format $fname $fpath
        fi                
    done
}


while getopts .t:e:p:l:. OPTION
do
     case $OPTION in
         e)
             ENV=$OPTARG
             ;;
         t)
             APP_TYPE=$OPTARG
             ;;
         p)
             PS_PATH=$OPTARG
             ;;
         l)
             PS_PATH_LIST=$OPTARG
             ;;             
         ?)
             log "additional param required"
             usage
             exit
             ;;
     esac
done

ENV_CONFIG=`echo "$ENV" | tr '[:upper:]' '[:lower:]'`
APP_TYPE_LOWERCASE=`echo "$APP_TYPE" | tr '[:upper:]' '[:lower:]'`

echo "APP_TYPE: $APP_TYPE_LOWERCASE"
echo "PS_PATH: $PS_PATH"
echo "PS_PATH_LIST: $PS_PATH_LIST"

if [ "$APP_TYPE_LOWERCASE" == "appenv" ]
then
        echo "env configuration"
        if [ -z $PS_PATH ];
        then
            echo "Info: no ps path"
        else                    
            fetching_specific_path $APP_TYPE_LOWERCASE
        fi
        if [ -z $PS_PATH_LIST ];
        then
            echo "Info: no path list"
        else        
            fetching_multiple_path  $APP_TYPE_LOWERCASE
        fi        
fi

if [ "$APP_TYPE_LOWERCASE" == "appconf" ]
then
        echo "conf file configuration"
        if [ -z $PS_PATH ];
        then
            echo "Info: no ps path"
        else
            fetching_specific_path $APP_TYPE_LOWERCASE
        fi
        if [ -z $PS_PATH_LIST ];
        then
            echo "Info: no path list"
        else        
            fetching_multiple_path $APP_TYPE_LOWERCASE
        fi          
fi

if [ "$APP_TYPE_LOWERCASE" == "appjson" ]
then
        echo "json file configuration"
        if [ -z $PS_PATH ];
        then
            echo "Info: no ps path"
        else        
            fetching_specific_path $APP_TYPE_LOWERCASE
        fi
        if [ -z $PS_PATH_LIST ];
        then
            echo "Info: no path list"
        else        
            fetching_multiple_path $APP_TYPE_LOWERCASE
        fi          
fi
