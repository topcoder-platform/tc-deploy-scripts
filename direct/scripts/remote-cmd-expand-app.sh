#!/bin/bash

source ~/.bash_profile

WORK_DIR=/home/direct/direct_deploy
BACKUP_DIR=/home/direct/direct_backup
JBOSS_DIR=/home/direct/jboss
DEPLOY_DIR=${JBOSS_DIR}/server/ckpit2/deploy

DIRECT_EAR=${DEPLOY_DIR}/direct.ear
BACKUP_EAR=${BACKUP_DIR}/direct.ear.bak
BACKUP_JAR=${WORK_DIR}/direct.jar.bak

if [ ! -e ${BACKUP_DIR}/direct.jar ]; then
  echo "[FATAL] ${BACKUP_DIR}/direct.jar not found.."
  exit 1;
fi

#
# Backup EAR
#
echo "Making backup $DIRECT_EAR --> $BACKUP_EAR"
if [ -e $BACKUP_EAR ]; then
  rm -rf $BACKUP_EAR
fi
cp -rf $DIRECT_EAR $BACKUP_EAR


#
# Backup and deploy JAR
#
echo "Making backup ${WORK_DIR}/direct.jar --> $BACKUP_JAR"
if [ -e $BACKUP_JAR ]; then
  rm -rf $BACKUP_JAR
fi
mv ${WORK_DIR}/direct.jar $BACKUP_JAR

echo "Deploying direct.jar"
cp -rf ${BACKUP_DIR}/direct.jar $WORK_DIR/

pushd $WORK_DIR
jar xvf direct.jar

popd
