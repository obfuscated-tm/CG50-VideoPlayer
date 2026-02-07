ifeq ($(strip $(FXCGSDK)),)
export FXCGSDK := $(abspath ../../)
endif

# Check for the correct GCC version folder in your SDK
GCC_VER   := 10.1.0
GCC_LIB   := $(FXCGSDK)/lib/gcc/sh3eb-elf/$(GCC_VER)

TARGET    := video_player
BUILD     := build
MKG3A     := $(FXCGSDK)/bin/mkg3a.exe
CC        := $(FXCGSDK)/bin/sh3eb-elf-gcc.exe
LD        := $(FXCGSDK)/bin/sh3eb-elf-ld.exe

# Compilation Flags
CFLAGS    := -mb -m4a-nofpu -mhitachi -nostdlib -Os -Wall \
             -IC:/PrizmSDK-win-0.6/include -ffunction-sections -fdata-sections

# Linker Flags - Using your specific prizm.x and matching the 'initialize' entry
LDFLAGS   := -T $(FXCGSDK)/toolchain/prizm.x \
             -L$(FXCGSDK)/lib -L$(GCC_LIB) \
             -static --gc-sections --entry=initialize

LIBS      := -lfxcg -lc -lgcc

OFILES    := $(BUILD)/main.o

.PHONY: all clean

all: $(BUILD) $(TARGET).g3a

$(BUILD):
	@mkdir $@ 2>nul || exit 0

# The G3A tool needs a .bin file
$(TARGET).g3a: $(TARGET).bin
	$(MKG3A) -n basic:VidPlayer $< $@

# Since your prizm.x has OUTPUT_FORMAT(binary), the .elf is already a .bin
# We just copy it to satisfy the naming requirement for mkg3a
$(TARGET).bin: $(TARGET).elf
	copy $(TARGET).elf $(TARGET).bin

$(TARGET).elf: $(OFILES)
	$(LD) $(OFILES) $(LDFLAGS) $(LIBS) -o $@

$(BUILD)/%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	@del /q $(BUILD)\*.* $(TARGET).bin $(TARGET).g3a $(TARGET).elf 2>nul
	@rmdir $(BUILD) 2>nul