#!/bin/bash
set -e

checksum="checksum"
target_dir="incoming"

Help="Usage: chk_incoming.sh [<name_of_checksum_file>]"

if [ $# -gt 0 ]; then
	case "$1" in
		--help|-h)
			echo "$Help"
			exit 0
		;;
		*)
			checksum="$1"
		;;
	esac
fi

checksum_a="checksum_a"
checksum_b="checksum_b"

if [ ! -f "${target_dir}/${checksum}" ]; then
	echo "Checksum file \"${checksum}\"  not in dir \"${target_dir}\""
	echo "$Help"
	exit -1
fi

(
	mv -f "${target_dir}/${checksum}" "$checksum_a"
	echo -n "Checksum \"${target_dir}\" ..."
	pushd "$target_dir" 1>/dev/null
	md5sum *>"../${checksum_b}"
	popd 1>/dev/null
)
if [ "$(sha256sum "$checksum_a" | cut -d ' ' -f 1)" != "$(sha256sum "$checksum_b" | cut -d ' ' -f 1)" ]; then
	echo "!!!data corrupted"
	mv "$checksum_a" "${target_dir}/${checksum}"
	rm -f "$checksum_b"
else
	echo "ok"

	rm -f "$checksum_a" "$checksum_b"
fi

