#!/bin/bash

WORK_DIR=/home/apps/direct-static
TARGET_JAR=${WORK_DIR}/direct-static-all.jar
BACKUP_JAR=${TARGET_JAR}.bak

echo [Taking backup of existing direct-static-all.jar]

if [ -e $BACKUP_JAR ]; then
  rm -rf $BACKUP_JAR
fi
if [ -e $TARGET_JAR ]; then
  mv $TARGET_JAR $BACKUP_JAR
else
  echo "$TARGET_JAR does not exist"
fi

