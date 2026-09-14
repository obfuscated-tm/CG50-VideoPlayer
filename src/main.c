#include <fxcg/display.h>
#include <fxcg/keyboard.h>
#include <fxcg/rtc.h>
#include <fxcg/system.h>
#include <fxcg/misc.h>
#include <fxcg/file.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>

#include "decode.h"

#define FILE_PATH "\\\\fls0\\video.bin"
#define READ 0

// The video file is read in 8 KB blocks and decoded straight to the screen (see decode.c)
static cgv_reader reader;
static cgv_video video;

// HELPER FUNCTIONS
void clearDisplay() {
    unsigned short *p = GetVRAMAddress();
    for (int i = 0; i < 216 * 384; i++) {
        *p++ = 65535; // White
    }
    Bdisp_PutDisp_DD();
}

// Feeds the decoder from the open file
static int bfile_refill(void *ctx, unsigned char *dst, int max) {
    int n = Bfile_ReadFile_OS(*(int *)ctx, dst, max, -1);
    return n > 0 ? n : 0;
}

// Non-blocking key check. Returns a KEY_PRGM_* code, or 0 if no key is waiting.
// GetKeyWait_OS reports the key's matrix column (7..2) and row (10..2); column * 10 + row - 1
// is the KEY_PRGM_* numbering (e.g. MENU = column 4, row 9 = 48 = KEY_PRGM_MENU).
static int poll_key(void) {
    int col = 0, row = 0;
    unsigned short keycode = 0;
    if (GetKeyWait_OS(&col, &row, KEYWAIT_HALTOFF_TIMEROFF, 0, 0, &keycode) != KEYREP_KEYEVENT) {
        return 0;
    }
    return col * 10 + row - 1;
}

// RTC_GetTicks counts 1/128 s since midnight; this keeps counting across midnight.
#define TICKS_PER_DAY (128UL * 86400UL)
static unsigned long mono_ticks(void) {
    static int last = -1;
    static unsigned long total = 0;
    int now = RTC_GetTicks();
    if (last >= 0) {
        long delta = now - last;
        if (delta < 0) delta += TICKS_PER_DAY;
        total += delta;
    }
    last = now;
    return total;
}

// Waits until the clock reaches *due, watching for MENU/EXIT. Returns true if one was pressed.
static bool wait_until(unsigned long *due) {
    unsigned long now;
    do {
        int key = poll_key();
        if (key == KEY_PRGM_EXIT || key == KEY_PRGM_MENU) {
            return true;
        }
        now = mono_ticks();
    } while (now < *due);
    // More than 1/4 s behind (slow file reads): carry on from now instead of rushing to catch up
    if (now > *due + 32) *due = now;
    return false;
}

void drawMainMenu(unsigned long frameCount, int width, int height, int fps100, int scale) {
    char buf[32];
    Bdisp_AllClr_VRAM();

    locate_OS(1, 1);
    Print_OS("--- VIDEO PLAYER ---", 0, 0);

    sprintf(buf, "Frames: %lu", frameCount);
    locate_OS(1, 3); Print_OS(buf, 0, 0);

    sprintf(buf, "Res: %dx%d", width, height);
    locate_OS(1, 4); Print_OS(buf, 0, 0);

    if (fps100 % 100) sprintf(buf, "FPS: %d.%02d", fps100 / 100, fps100 % 100);
    else sprintf(buf, "FPS: %d", fps100 / 100);
    locate_OS(1, 5); Print_OS(buf, 0, 0);

    sprintf(buf, "Scale: %d", scale);
    locate_OS(1, 6); Print_OS(buf, 0, 0);

    locate_OS(1, 8);
    Print_OS("EXE: Play Video", 0, 0);

    Bdisp_PutDisp_DD();
}

// Prevents issues with Bfile error: -8
static int g_hFile = -1;
void quit_handler(void) {
    if (g_hFile >= 0) {
        Bfile_CloseFile_OS(g_hFile);
        g_hFile = -1;
    }
}


// MAIN LOGIC
int main(void) {
    SetQuitHandler(quit_handler);
    unsigned short pFile[64];
    Bdisp_EnableColor(1);
    clearDisplay();

    // Finds video.bin
    Bfile_StrToName_ncpy(pFile, (const char*)FILE_PATH, 64);
    g_hFile = Bfile_OpenFile_OS(pFile, READ, 0);
    int hFile = g_hFile;

    if (hFile < 0) {
        locate_OS(1, 1); Print_OS("FATAL ERROR", 0, 0);
        char msg[32];
        sprintf(msg, "Bfile Error: %d", hFile);
        locate_OS(1, 2); Print_OS(msg, 0, 0);


        if (hFile == -1) {
            locate_OS(1, 4); Print_OS("File not found.", 0, 0);
        } else if (hFile == -8) {
            locate_OS(1, 4); Print_OS("Press the RESET", 0, 0);
            locate_OS(1, 5); Print_OS("button on the back", 0, 0);
            locate_OS(1, 6); Print_OS("of the calculator.", 0, 0);
        }

        while(1) { int k; GetKey(&k); if(k==KEY_CTRL_EXIT) return 0; }
    }

    // Header (either file format) and menu
    cgv_reader_init(&reader, bfile_refill, &g_hFile);
    if (cgv_open(&video, &reader) != CGV_OK) {
        clearDisplay();
        locate_OS(1, 2); Print_OS("BAD VIDEO FILE", 0, 0);
        while (1) { int k; GetKey(&k); if (k == KEY_CTRL_EXIT) break; }
        g_hFile = -1;
        return 0;
    }

    while (1) {
        int key = 0;
        drawMainMenu(video.frames, video.width, video.height, video.fps100, video.scale);
        GetKey(&key);
        if (key == KEY_CTRL_EXE || key == 0x000D) break;
        if (key == KEY_CTRL_EXIT) {
            g_hFile = -1;
            return 0;
        }
    }

    // Black background around videos that don't fill the screen
    unsigned short *vram = GetVRAMAddress();
    for (int i = 0; i < 384 * 216; i++) vram[i] = 0;

    // Playback loop: each frame is due 1/fps after the previous one. carry keeps the
    // fraction of a tick, so 29.97 fps stays exact.
    unsigned long due = mono_ticks();
    unsigned long carry = 0;
    int result = CGV_OK;
    for (unsigned long f = 0; f < video.frames; f++) {
        result = cgv_decode_frame(&video, &reader, vram);
        if (result != CGV_OK) break;
        Bdisp_PutDisp_DD(); // Display frame

        carry += 12800; // 128 ticks per second * 100
        due += carry / video.fps100;
        carry %= video.fps100;
        if (wait_until(&due)) break; // MENU or EXIT
    }

    // Exit screen (must go into another app)
    clearDisplay();
    if (result == CGV_ERR_CORRUPT) {
        locate_OS(1, 2); Print_OS("Video data is damaged.", 0, 0);
    }
    locate_OS(1, 4); Print_OS("Enter another", 0, 0);
    locate_OS(1, 5); Print_OS("app to replay.", 0, 0);

    // Press EXIT button to quit
    while(1) {
        int key;
        GetKey(&key);
        if (key == KEY_CTRL_EXIT) break;
    }

    // Prevents some pointer issues
    g_hFile = -1;
    return 0;
}
