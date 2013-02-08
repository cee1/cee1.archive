CC = clang
PKG_MODULES = gio-2.0
LDFLAGS ?=
CFLAGS ?= 

COMMON_SRCS = log.c hei-packet.c common.c
SENDER_SRCS = sender.c $(COMMON_SRCS)
RECEIVER_SRCS = receiver.c $(COMMON_SRCS)

DEPS = config.h log.h hei-packet.h internal.h
LDFLAGS += -lm

CFLAGS += $(shell pkg-config --cflags $(PKG_MODULES)) -std=c99 -Wall
LDFLAGS += $(shell pkg-config --libs $(PKG_MODULES))

.PHONY: all

all: sender

%.o: %.c $(DEPS)
	$(CC) -c -o $@ $< $(CFLAGS)

sender: $(SENDER_SRCS:.c=.o)
	$(CC) -o $@ $^ $(LDFLAGS)

receiver: $(RECEIVER_SRCS:.c=.o)
	$(CC) -o $@ $^ $(LDFLAGS)

clean:
	rm -rf sender receiver
	rm -rf sender.exe receiver.exe
	rm -f *.o

