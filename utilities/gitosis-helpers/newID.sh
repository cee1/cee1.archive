#!/bin/bash
who="$1"
ssh-keygen -t rsa -b 4096 -f "$who" -C "$who"
