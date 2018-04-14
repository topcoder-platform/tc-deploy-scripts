#!/bin/bash

WORK_DIR=/home/apps/direct-static
TARGET_JAR=${WORK_DIR}/direct-static-all.jar
BACKUP_JAR=${TARGET_JAR}.bak

echo [Taking backup of existing direct-static-all.jar]

if [ ! -e $TARGET_JAR ]; then
  echo "[FATAL] $TARGET_JAR not found.."
  exit 1;
fi

if [ -e $BACKUP_JAR ]; then
  rm -rf $BACKUP_JAR
fi

mv $TARGET_JAR $BACKUP_JAR
