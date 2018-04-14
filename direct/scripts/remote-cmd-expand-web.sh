#! /bin/bash

WORK_DIR=/home/apps/direct-static
CSS=${WORK_DIR}/css
SCRIPTS=${WORK_DIR}/scripts
IMAGES=${WORK_DIR}/images
TARGET_JAR=${WORK_DIR}/direct-static-all.jar

# Document root
DOC_DIR=/home/apps/apache_docs/tcdocs

if [ ! -e $TARGET_JAR ]; then
  echo "[FATAL] $TARGET_JAR not found.."
  exit 1;
fi

if [ ! -e $WORK_DIR ]; then
  echo "[FATAL] $WORK_DIR not found.."
  exit 1;
fi

echo "rm -rf $CSS"
rm -rf $CSS
echo "rm -rf $SCRIPTS"
rm -rf $SCRIPTS
echo "rm -rf $IMAGES"
rm -rf $IMAGES

echo "Expanding $TARGET_JAR"
unzip -d $WORK_DIR $TARGET_JAR
chmod -R 775 $CSS
chmod -R 775 $SCRIPTS
chmod -R 775 $IMAGES

echo "Copying static resources"
cp -rf $CSS/* $DOC_DIR/css/
cp -rf $SCRIPTS/* $DOC_DIR/scripts/
cp -rf $IMAGES/* $DOC_DIR/images/
