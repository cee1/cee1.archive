#!/bin/bash
set -e
dpkg_movtodir="../scripts/dpkg_movtodir.py"

Help="fill_section.sh <section> -- fill <section> from incoming"

if [ $# -lt 1 ]; then 
	echo "$Help"
	exit -1
else
	case "$1" in
		-h|--help)
			echo "$Help"
			exit 0
		;;
		*)
			section="$1"
		;;
	esac
fi

incoming="incoming"

if [ "$section" = incoming ]; then
	echo "section name should not be \"incoming\"!!!"
	exit -1
elif [ ! -d "$section" ]; then
	echo "section dir \"$section\" not exists!!!"
	exit -1
fi

(
	echo "Enter \"${incoming}\""
	pushd "$incoming" 1>/dev/null
	echo "Generate Packages' index file..."
	apt-ftparchive packages . > Packages

	echo "Generate Sources' index file..."
	apt-ftparchive sources . > Sources

	echo "Generate index dir struct..."
	if [ -e "../$dpkg_movtodir" ]; then
		python "../$dpkg_movtodir" -v --force -s Sources -p Packages "../${section}"
	else
		echo "Can't find dpkg_movtodir script(expected in \"${dpkg_movtodir}\")"
	fi

	echo "Clean Packages and Sources index file"
	rm -f Packages Sources

	echo "Leave \"${incoming}\""
	popd 1>/dev/null
)

if [ ! -z "$(ls -A "$incoming")" ]; then
	echo "!!!\"${incoming}\" is not empty"
	exit 1
else
	echo "### Finished >>>"
fi

