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

#define VIDEO_NAME "video.bin"

// The video file is read in 8 KB blocks and decoded straight to the screen (see decode.c)
static cgv_reader reader;
static cgv_video video;

/*
 * File handling. This part caused "Bfile error -8" (file already open) before, so it
 * follows three rules:
 *  1. g_hFile holds the one open file, or -1. Only open_video() and close_video() change it.
 *  2. A file is always closed before a file is opened.
 *  3. main() never returns. The user leaves with MENU, like any other add-in. If they then
 *     start another app, the OS calls quit_handler(), which closes the file.
 *     (Returning from main() used to leave the add-in unusable until another app was run.)
 */
static int g_hFile = -1;

static void close_video(void) {
    if (g_hFile >= 0) {
        Bfile_CloseFile_OS(g_hFile);
        g_hFile = -1;
    }
}

void quit_handler(void) {
    close_video();
}

// Feeds the decoder from the open file
static int bfile_refill(void *ctx, unsigned char *dst, int max) {
    int n = Bfile_ReadFile_OS(*(int *)ctx, dst, max, -1);
    return n > 0 ? n : 0;
}

// Opens \\fls0\<name> and gets the decoder ready. Returns 0, or the (negative) Bfile error.
static int open_video(const char *name) {
    unsigned short path[64];
    char full[64];
    close_video();
    sprintf(full, "\\\\fls0\\%s", name);
    Bfile_StrToName_ncpy(path, full, 64);
    int handle = Bfile_OpenFile_OS(path, READ, 0);
    if (handle < 0) {
        return handle;
    }
    g_hFile = handle;
    cgv_reader_init(&reader, bfile_refill, &g_hFile);
    return 0;
}

// HELPER FUNCTIONS
void clearDisplay() {
    unsigned short *p = GetVRAMAddress();
    for (int i = 0; i < 216 * 384; i++) {
        *p++ = 65535; // White
    }
    Bdisp_PutDisp_DD();
}

// Waits for EXIT (MENU still works as usual inside GetKey)
static void wait_for_exit_key(void) {
    int key;
    do {
        GetKey(&key);
    } while (key != KEY_CTRL_EXIT);
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

// Plays the open video from its first frame. Returns the decoder result (CGV_OK when done).
static int play_video(void) {
    // Black background around videos that don't fill the screen
    unsigned short *vram = GetVRAMAddress();
    for (int i = 0; i < 384 * 216; i++) vram[i] = 0;

    // Each frame is due 1/fps after the previous one. carry keeps the fraction of a tick,
    // so 29.97 fps stays exact.
    unsigned long due = mono_ticks();
    unsigned long carry = 0;
    for (unsigned long f = 0; f < video.frames; f++) {
        int result = cgv_decode_frame(&video, &reader, vram);
        if (result == CGV_END) break;
        if (result != CGV_OK) return result;
        Bdisp_PutDisp_DD(); // Display frame

        carry += 12800; // 128 ticks per second * 100
        due += carry / video.fps100;
        carry %= video.fps100;
        if (wait_until(&due)) break; // MENU or EXIT
    }
    return CGV_OK;
}


// MAIN LOGIC (never returns; see "File handling" above)
int main(void) {
    SetQuitHandler(quit_handler);
    Bdisp_EnableColor(1);

    for (;;) {
        clearDisplay();

        // Finds video.bin
        int err = open_video(VIDEO_NAME);
        if (err < 0) {
            char msg[32];
            locate_OS(1, 1); Print_OS("FATAL ERROR", 0, 0);
            sprintf(msg, "Bfile Error: %d", err);
            locate_OS(1, 2); Print_OS(msg, 0, 0);

            if (err == -1) {
                locate_OS(1, 4); Print_OS("File not found.", 0, 0);
            } else if (err == -8) {
                locate_OS(1, 4); Print_OS("Press the RESET", 0, 0);
                locate_OS(1, 5); Print_OS("button on the back", 0, 0);
                locate_OS(1, 6); Print_OS("of the calculator.", 0, 0);
            }
            locate_OS(1, 8); Print_OS("EXIT: Try again", 0, 0);
            wait_for_exit_key();
            continue;
        }

        // Header (either file format)
        if (cgv_open(&video, &reader) != CGV_OK) {
            close_video();
            clearDisplay();
            locate_OS(1, 2); Print_OS("BAD VIDEO FILE", 0, 0);
            locate_OS(1, 8); Print_OS("EXIT: Try again", 0, 0);
            wait_for_exit_key();
            continue;
        }

        // Menu: EXE plays; EXIT re-reads the file
        int key = 0;
        do {
            drawMainMenu(video.frames, video.width, video.height, video.fps100, video.scale);
            GetKey(&key);
        } while (key != KEY_CTRL_EXE && key != 0x000D && key != KEY_CTRL_EXIT);
        if (key == KEY_CTRL_EXIT) {
            close_video();
            continue;
        }

        int result = play_video();
        close_video(); // the next play reopens the file, so it starts from the first frame

        clearDisplay();
        if (result == CGV_ERR_CORRUPT) {
            locate_OS(1, 2); Print_OS("Video data is damaged.", 0, 0);
        }
        locate_OS(1, 4); Print_OS("EXIT: Back to menu", 0, 0);
        wait_for_exit_key();
    }
}
