#!/bin/bash
set -e

suite=shield
arch=mipsel
desc="apt repo for LOonux3"

OLD_LC_ALL="$LC_ALL"
export LC_ALL=C

for ver in dists/*
do
	if [ -d "$ver" ]; then
		version=$(basename "$ver")
		
		sections=""

		for sec in "$ver"/*
		do
			if [ -d "$sec" ]; then
				section=$(basename "$sec")
				if [ -z "$sections" ]; then
					sections="$section"
				else
					sections="${sections} ${section}"
				fi
			fi
		done

		echo "Release ${version}..."
		(
			echo "Enter \"${ver}\""
			pushd "$ver" 1>/dev/null

			cat > Release.tmp <<EOF
Origin: Debian
Label: Debian
Suite: ${suite}
codename: ${version}
Architectures: ${arch}
Components: ${sections}
Description: ${desc}
EOF
			apt-ftparchive release . >> Release.tmp
			mv Release.tmp Release

			echo "Leave \"${ver}\""
			popd 1>/dev/null
		)

		echo "Sign Release file..."
		gpg -abs -o "${ver}/Release.gpg" "${ver}/Release"
	fi
done

export LC_ALL="$OLD_LC_ALL"

