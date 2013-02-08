#ifndef __CONFIG_H__
#define __CONFIG_H__

#define MY_DEBUG

#define N_KPACKETS 20
#define N_PACKETS_ENOUGH (N_KPACKETS+1)
#define N_FPACKETS 0
#define N_WINPACKETS (N_KPACKETS+N_FPACKETS)

#define WIN_TIMEOUT 500
#define WIN_LATE_MAX 1
#define MAX_SPLIT_COUNT 29

#define RATE_LIMIT_BYTES_PER_CYCLE 7000
#define RATE_LIMIT_CYCLE           15

#define SOURCE_ADDRESS  "0.0.0.0"
#define SOURCE_PORT     7500

#define TARGET_ADDRESS_DEFAULT  "239.192.0.1"
#define TARGET_PORT_DEFAULT     3056
#define NET_IF          "em1"
//#define NET_IF          "wlan0"

#endif /* __CONFIG_H__ */

