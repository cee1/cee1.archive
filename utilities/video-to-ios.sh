#!/bin/bash
set -e

if [ ! -f "$1" ]; then
	echo "Usage video-to-ios.sh <path_to_video>"
	exit 1
fi

video_file="$1"
target="ios-$(basename $video_file)"
gst_ver=1.0

if [ "$gst_ver" = "0.10" ]; then 
	decodebin=decodebin2
	colorspaceconvert=ffmpegcolorspace
	aac_enc=faac # ffenc_aac
else
	decodebin=decodebin
	colorspaceconvert=autovideoconvert
	aac_enc=faac # avenc_aac
fi

if false; then

for pass in 'pass=pass1' 'pass=pass2'
do
echo "Doing Pass $pass..."
	gst-launch-$gst_ver filesrc location="$video_file" ! $decodebin name=d	\
		d. ! queue ! $colorspaceconvert !				\
	x264enc $pass speed-preset=slow psy-tune=film ! fakesink
done

fi

echo "Doing final pass ..."
gst-launch-$gst_ver filesrc location="$video_file" ! $decodebin name=d		\
	qtmux name=iosmp4 ! filesink location="$target"				\
	d. ! queue ! audioconvert ! audioresample ! $aac_enc ! iosmp4.audio_0	\
	d. ! queue ! $colorspaceconvert !					\
x264enc speed-preset=slow psy-tune=film pass=qual bitrate=2048 ! iosmp4.video_0

