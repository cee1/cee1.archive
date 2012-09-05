#!/bin/bash
Help="usage: updateidx.sh <section> [version]"
version="shield"
gen_contents=

if [ $# -lt 1 ]; then
	echo "$Help"
	exit -1
elif [ $# -gt 1 ]; then
	version="$2"
fi

if [ "$0" = "updateidx-full.sh" ]; then
	gen_contents=yes
fi

case "$1" in
	-h|--help)
		echo "$Help"
		exit 0
	;;
	*)
		section="$1"
	;;
esac


if [ ! -d "dists/${version}/${section}" ]; then
	echo "\"dists/${version}/${section}\" not exists!!!"
	exit -1
else
	subdirs=("binary-mipsel" "source")
	for d in "${subdirs[@]}"
	do
		d="dists/${version}/${section}/${d}"
		test -d "$d" || echo "create dir \"$d\""; mkdir -p "$d"
	done
fi

if [ ! -d "pool/${section}" ]; then
	echo "pool/${section} not exists!!!"
	exit -1
fi

target_dir="dists/${version}/${section}/binary-mipsel"
echo "Generate ${target_dir}/Packages..."
apt-ftparchive packages "pool/${section}" > "${target_dir}/Packages"
bzip2 -9 -c "${target_dir}/Packages" > "${target_dir}/Packages.bz2"

target_dir="dists/${version}/${section}/source"
echo "Generate ${target_dir}/Sources..."
apt-ftparchive sources "pool/${section}" > "${target_dir}/Sources"
bzip2 -9 -c "${target_dir}/Sources" > "${target_dir}/Sources.bz2"

if [ "x$gen_contents" = "xyes" ]; then
	echo "Generate dists/${version}/Contents-mipsel.bz2..."
	apt-ftparchive contents pool | bzip2 -9 -c > "dists/${version}/Contents-mipsel.bz2"
fi
