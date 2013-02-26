#!/bin/bash
set -e

if [ ! -f "$1" ]; then
	echo "Usage video-to-ios.sh <path_to_video>"
	exit 1
fi

video_file="$1"
target="ios-$video_file"

if false; then

for pass in 'pass=pass1' 'pass=pass2'
do
echo "Doing Pass $pass..."
	gst-launch-0.10 filesrc location="$video_file" ! decodebin2 name=d	\
		d. ! queue ! ffmpegcolorspace !					\
	x264enc $pass speed-preset=slow psy-tune=film ! fakesink
done

fi

echo "Doing final pass ..."
AACENC=faac
#AACENC=ffenc_aac

gst-launch-0.10 filesrc location="$video_file" ! decodebin2 name=d		\
	qtmux name=iosmp4 ! filesink location="$target"				\
	d. ! queue ! audioconvert ! audioresample ! $AACENC ! iosmp4.audio_0	\
	d. ! queue ! ffmpegcolorspace !						\
x264enc speed-preset=slow psy-tune=film pass=qual bitrate=2048 ! iosmp4.video_0

