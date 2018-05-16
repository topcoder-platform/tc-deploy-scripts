1) Copy buildvar.conf.template as buildvar.conf
2) Update the values in buildvar.conf
3) Checkin the buildvar.conf in appplication repo under root folder
4) Copy the APPNAME-buildsecvar.conf as <Application Name>-buildsecvar.conf
5) Update the values in <Application Name>-buildsecvar.conf
6) Run the tooltoencdec.sh with below option
    ./tooltoencdec.sh -e <Application Name>-buildsecvar.conf -s <secret key>
   
   This will generate a file with name <Application Name>-buildsecvar.conf.enc
7) Create a folder with <Application Name> under tc-deploy-scripts root folder
8) Copy the encrypted file under this application folder and commit the same
9) Update the circleci yml file with below command for deployment 
   If it is DEV, then it need to be updaate as below
   ./master_deploy.sh -d ECS -e DEV -t <tag name> -s GIT -p <template type>
   If it is QA, then it need to be updaate as below
   ./master_deploy.sh -d ECS -e QA -t <tag name> -s GIT -p <template type>
   If it is PROD, then it need to be updaate as below
   ./master_deploy.sh -d ECS -e PROD -t <tag name> -s GIT -p <template type>

