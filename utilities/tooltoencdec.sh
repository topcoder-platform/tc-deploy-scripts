#!/bin/bash

DECRYPT=""
ENCRYPT=""
INTERACTIVE=0
FILENAME=""
SECPASSWD=""
USEROPTION=""

while getopts .d:e:s:. OPTION
do
     case $OPTION in
         d)
             DECRYPT=1
             FILENAME=$OPTARG
             ;;
         e)
             ENCRYPT=1
             FILENAME=$OPTARG
             ;;
         s)
             SECPASSWD=$OPTARG
             ;;
     esac
done

openssl version
if [ $? != "0" ]; then
	echo "Kindly install the openssl for executing the script"
	exit 1
fi

if [ -z $DECRYPT ] && [ -z $ENCRYPT ] ;
then
         INTERACTIVE=1
fi

if [ "$INTERACTIVE" != "0" ]; then
        read -p "Are you going to decrypt/encrypt (d/e) : " USEROPTION

        case "$USEROPTION" in
          d)
             DECRYPT=1
             ;;
          e)
             ENCRYPT=1
             ;;
          *)
             echo "Please provide proper option"
             exit 1
             ;;
        esac

        read -p "Please enter the file name :  " FILENAME
        read -p "Please enter the Secret Password : " SECPASSWD
else
        if [ ! -z $DECRYPT ] && [ ! -z $ENCRYPT ] ;
        then
           echo "Please provide encrypt or decrypt"
           exit 1
        fi

        if [ -z $SECPASSWD ] ;
        then
           echo "Please provide Secret password with option -s"
           exit 1
        fi
fi

if [ -f $FILENAME ];
then
  echo "Input file exist"
else
  echo "Input file does not exist. Please provide valid file name"
  exit 1
fi

if [ "$DECRYPT" = "1" ]; then
        echo "Decypt option has enabled"
        outputname=$(basename "$FILENAME" .enc)
        echo "$outputname"
	openssl enc -aes-256-cbc -d -md MD5 -in $FILENAME -out $outputname -k "$SECPASSWD"
	if [ $? != "0" ]; then
		echo "File decryption failed with error code $?"
		exit 1
	else 
		echo "File Decryption completed"
	fi		


fi

if [ "$ENCRYPT" = "1" ]; then
        echo "Encypt option has enabled"
	openssl enc -aes-256-cbc -salt -md MD5 -in $FILENAME -out $FILENAME.enc -k "$SECPASSWD"
	if [ $? != "0" ]; then
		echo "File Encryption failed with error code $?"
		exit 1
	else 
		echo "File Encryption completed"
	fi			
fi
