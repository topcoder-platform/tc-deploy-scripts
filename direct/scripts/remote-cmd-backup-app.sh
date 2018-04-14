#!/bin/bash

BACKUP_DIR=/home/direct/direct_backup
TARGET_JAR=${BACKUP_DIR}/direct.jar
BACKUP_JAR=${TARGET_JAR}.bak
BACKUP_CONF=${BACKUP_DIR}/direct-conf.bak

SERVER_PATH=/home/direct/jboss/server/ckpit2

# app
echo [Taking backup of existing direct.jar]
if [ -e $BACKUP_JAR ]; then
  rm -rf $BACKUP_JAR
fi
if [ -e $TARGET_JAR ]; then
  mv $TARGET_JAR $BACKUP_JAR
fi

# conf
echo [Taking backup of existing $SERVER_PATH/conf]
if [ -e $BACKUP_CONF ]; then
  rm -rf $BACKUP_CONF
fi

cp -rf $SERVER_PATH/conf $BACKUP_CONF
