Build Setup:

Build setup invloves 3 steps

Step 1 : File need to be uploaded in S3:

1) Build variable creation (Optional):
    i) Create a file which need to be exported during the build time in json format.
    ii) This need to have naming convention like {ENV}-{APPNAME}-buildvar.json
    iii) Please refer sample format in

2) App variable creation (Mandatatory for ECS)
    i)Create a file which need to be exported during the run time in json format
    ii) This need to have naming convention like {ENV}-{APPNAME}-appvar.json
    iii) Please refer sample format in

3) Create Deployvar file (Mandatatory) :
    i) Create a deployvar file for master script based on the environment
    ii) This need to have naming convention like {ENV}-{APPNAME}-deployvar.json
    iii) Please refer template for devar file configuration availble in 


Step 2 : Github repo files update

1) Build script creation (Mandatatory):
    i) Create a build which will build image and provide execute permission
    ii) Please refer template scripts availble in <link>. please update select the script based on requirement 

2) Circleci Config file creation (Mandatatory):

    i) Create a circleci config file which will have set of steps to execute in circleci 
    ii) Please refer template for circle ci configuration availble in <link>. please update select the script based on requirement 

Step 3 : Please create AWS resources and do circleci integration


Example: Nodejs Application Building

1) Assumption: 
    Application Name: testapp
    Deploying Environment: dev
    Application Type: processor
    Deployment Type: ECS
    Buildvar file needed : no
    Appvar file needed : yes
    Cluster Name: testapp-cluster

2) Creating S3 files
    i) Copy the sample appvar file from here
    ii) update the application var files which used in run time. Here appvar looks as below
        {
            "APPNAME" : "testapp"
        }
    iii) Name the appvar file as dev-testapp-appvar.json
    iv) Copy the sample deloyvar-ecs-std.json
    v) Update the file with proper rresource details. It looks as below

            {
                "AWS_ECS_CLUSTER": "testapp-cluster",
                "AWS_ECS_SERVICE": "testapp",
                "AWS_ECS_TASK_FAMILY": "testapp",
                "AWS_ECS_CONTAINER_NAME": "testapp",
                "AWS_ECS_PORTS": "0:3000:TCP",
                "AWS_REPOSITORY": "repositoryname",
                "AWS_ECS_CONTAINER_HEALTH_CMD": "/usr/bin/curl -f http://localhost:3000/health || exit 1
            }

    vi) Rename the file as dev-testapp-deployvar.json
    vii) Upload the above 2 file in S3 bucket on standard location
3) Adding github files
    i) copy build script file from to local
    ii) rename as build.sh
    iii) Copy 
Step 1 : File need to be uploaded in S3:

1) Build variable creation (Optional):
    i) Create a file which need to be exported during the build time in json format.
    ii) This need to have naming convention like {ENV}-{APPNAME}-buildvar.json
    iii) Please refer sample format in

2) App variable creation (Mandatatory for ECS)
    i)Create a file which need to be exported during the run time in json format
    ii) This need to have naming convention like {ENV}-{APPNAME}-appvar.json
    iii) Please refer sample format in

3) Create Deployvar file (Mandatatory) :
    i) Create a deployvar file for master script based on the environment
    ii) This need to have naming convention like {ENV}-{APPNAME}-deployvar.json
    iii) Please refer template for devar file configuration availble in 


Step 2 : Github repo files update

1) Build script creation (Mandatatory):
    i) Create a build which will build image and provide execute permission
    ii) Please refer template scripts availble in <link>. please update select the script based on requirement 

2) Circleci Config file creation (Mandatatory):

    i) Create a circleci config file which will have set of steps to execute in circleci 
    ii) Please refer template for circle ci configuration availble in <link>. please update select the script based on requirement 

Step 3 : Please create AWS resources and do circleci integration


Example: Nodejs Application Building

1) Assumption: 
    Application Name: testapp
    Deploying Environment: dev
    Application Type: processor
    Deployment Type: ECS
    Buildvar file needed : no
    Appvar file needed : yes
    Cluster Name: testapp-cluster

2) Creating S3 files
    i) Copy the sample appvar file from here
    ii) update the application var files which used in run time. Here appvar looks as below
        {
            "APPNAME" : "testapp"
        }
    iii) Name the appvar file as dev-testapp-appvar.json
    iv) Copy the sample deloyvar-ecs-std.json
    v) Update the file with proper rresource details. It looks as below

            {
                "AWS_ECS_CLUSTER": "testapp-cluster",
                "AWS_ECS_SERVICE": "testapp",
                "AWS_ECS_TASK_FAMILY": "testapp",
                "AWS_ECS_CONTAINER_NAME": "testapp",
                "AWS_ECS_PORTS": "0:3000:TCP",
                "AWS_REPOSITORY": "repositoryname",
                "AWS_ECS_CONTAINER_HEALTH_CMD": "/usr/bin/curl -f http://localhost:3000/health || exit 1
            }

    vi) Rename the file as dev-testapp-deployvar.json
    vii) Upload the above 2 file in S3 bucket on standard location
3) Adding github files
    i) copy build script file from to local
    ii) rename as build.sh
    iii) Copy 

