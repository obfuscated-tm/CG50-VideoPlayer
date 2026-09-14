/*
 * CG50 Video Player
 *
 * Lists the .bin videos in the calculator's storage, shows their details and plays them.
 * Decoding is in decode.c (shared with the PC tests); docs/FORMAT.md describes the files.
 */
#include <fxcg/display.h>
#include <fxcg/keyboard.h>
#include <fxcg/rtc.h>
#include <fxcg/system.h>
#include <fxcg/misc.h>
#include <fxcg/file.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

#include "decode.h"

#define SCREEN_W 384
#define SCREEN_H 216
#define TEXT_COLS 21   // the OS text grid is 21 x 8; row 1 is just below the status bar
#define LIST_ROWS 6    // the list uses text rows 2..7
#define MAX_VIDEOS 32
#define NAME_LEN 40    // longest file name listed, including ".bin"

// The open video is read in 8 KB blocks and decoded straight to the screen (see decode.c)
static cgv_reader reader;
static cgv_video video;

typedef struct {
    char name[NAME_LEN];           // file name, e.g. "badapple.bin"
    char label[TEXT_COLS + 1];     // title from the file, or the file name
    unsigned long size;            // bytes
    unsigned long seconds;         // length
    bool playable;
} video_entry;

static video_entry videos[MAX_VIDEOS];
static int video_count;

// File details filled in by Bfile_FindFirst/Bfile_FindNext (layout from WikiPrizm)
typedef struct {
    unsigned short id, type;
    unsigned long fsize, dsize;
    unsigned int property;
    unsigned long address;
} find_info;

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

// --- Drawing ----------------------------------------------------------------------------

static void text(int col, int row, const char *s, bool inverted) {
    locate_OS(col, row);
    Print_OS(s, inverted ? TEXT_MODE_INVERT : TEXT_MODE_NORMAL, 0);
}

// A whole text row, padded with spaces so inverted rows become a bar.
static void text_row(int row, const char *s, bool inverted) {
    char line[TEXT_COLS + 1];
    int i = 0;
    for (; i < TEXT_COLS && s[i]; i++) line[i] = s[i];
    for (; i < TEXT_COLS; i++) line[i] = ' ';
    line[TEXT_COLS] = '\0';
    text(1, row, line, inverted);
}

static void fill_rect(int x, int y, int w, int h, unsigned short color) {
    unsigned short *vram = GetVRAMAddress();
    if (x < 0) { w += x; x = 0; }
    if (x + w > SCREEN_W) w = SCREEN_W - x;
    for (int j = y; j < y + h && j < SCREEN_H; j++) {
        for (int i = 0; i < w; i++) vram[j * SCREEN_W + x + i] = color;
    }
}

static void format_time(char *out, unsigned long seconds) {
    if (seconds >= 3600) sprintf(out, "%lu:%02lu:%02lu", seconds / 3600, seconds / 60 % 60, seconds % 60);
    else sprintf(out, "%lu:%02lu", seconds / 60, seconds % 60);
}

static void format_fps(char *out, int fps100) {
    if (fps100 % 100) sprintf(out, "%d.%02d", fps100 / 100, fps100 % 100);
    else sprintf(out, "%d", fps100 / 100);
}

static void wait_for_exit_key(void) {
    int key;
    do {
        GetKey(&key); // MENU still works as usual here
    } while (key != KEY_CTRL_EXIT);
}

// A screen of up to four lines of text; waits for EXIT.
static void message(const char *l1, const char *l2, const char *l3, const char *l4) {
    Bdisp_AllClr_VRAM();
    text_row(1, " Video Player", true);
    if (l1) text(1, 3, l1, false);
    if (l2) text(1, 4, l2, false);
    if (l3) text(1, 5, l3, false);
    if (l4) text(1, 6, l4, false);
    text(1, 8, "EXIT: Back", false);
    Bdisp_PutDisp_DD();
    wait_for_exit_key();
}

// --- Keys and time ------------------------------------------------------------------------

// Turns GetKeyWait_OS's matrix position (column 7..2, row 10..2) into a KEY_PRGM_* code,
// e.g. MENU = column 4, row 9 = 48 = KEY_PRGM_MENU.
static int wait_key(int type_of_waiting) {
    int col = 0, row = 0;
    unsigned short keycode = 0;
    // menu = 1: MENU is reported like any other key instead of opening the Main Menu
    if (GetKeyWait_OS(&col, &row, type_of_waiting, 0, 1, &keycode) != KEYREP_KEYEVENT) {
        return 0;
    }
    return col * 10 + row - 1;
}

static int poll_key(void) {
    return wait_key(KEYWAIT_HALTOFF_TIMEROFF); // doesn't wait; 0 if no key
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

// --- Finding videos -----------------------------------------------------------------------

static unsigned long video_seconds(void) {
    return video.frames * 100UL / (unsigned long)video.fps100;
}

// Fills videos[] with every \\fls0\*.bin file, reading each one's header.
static void scan_videos(void) {
    static unsigned short found[270]; // the name, as a 16-bit string
    unsigned short pattern[32];
    char name[64];
    find_info info;
    int handle = 0;

    close_video();
    video_count = 0;
    Bfile_StrToName_ncpy(pattern, "\\\\fls0\\*.bin", 32);
    // Bfile_FindFirst takes 16-bit strings; libfxcg declares them as char*.
    int ret = Bfile_FindFirst((const char *)pattern, &handle, (char *)found, &info);
    bool must_close = (ret == 0 || ret == -16); // -16 just means "no files"
    while (ret == 0 && video_count < MAX_VIDEOS) {
        Bfile_NameToStr_ncpy(name, found, sizeof name - 1);
        name[sizeof name - 1] = '\0';
        if (strlen(name) < NAME_LEN - 1) {
            video_entry *e = &videos[video_count++];
            strcpy(e->name, name);
            e->size = info.fsize;
        }
        ret = Bfile_FindNext(handle, (char *)found, (char *)&info);
    }
    if (must_close) {
        Bfile_FindClose(handle);
    }

    // Read each header (one file open at a time)
    for (int i = 0; i < video_count; i++) {
        video_entry *e = &videos[i];
        e->playable = false;
        e->seconds = 0;
        strncpy(e->label, e->name, TEXT_COLS);
        e->label[TEXT_COLS] = '\0';
        if (open_video(e->name) == 0) {
            if (cgv_open(&video, &reader) == CGV_OK) {
                e->playable = true;
                e->seconds = video_seconds();
                if (video.title[0]) {
                    strncpy(e->label, video.title, TEXT_COLS);
                    e->label[TEXT_COLS] = '\0';
                }
            }
            close_video();
        }
    }

    // Sort by label (insertion sort; there are at most MAX_VIDEOS)
    for (int i = 1; i < video_count; i++) {
        video_entry moving = videos[i];
        int j = i - 1;
        while (j >= 0 && strcasecmp(videos[j].label, moving.label) > 0) {
            videos[j + 1] = videos[j];
            j--;
        }
        videos[j + 1] = moving;
    }
}

// Opens a video from the list, ready to play from its first frame. Shows errors itself.
static bool load_video(const video_entry *e) {
    int err = open_video(e->name);
    if (err < 0) {
        char msg[32];
        sprintf(msg, "Bfile Error: %d", err);
        if (err == -8) message(msg, "Press the RESET", "button on the back", "of the calculator.");
        else if (err == -1) message(msg, "File not found.", NULL, NULL);
        else message(msg, "Couldn't open the file.", NULL, NULL);
        return false;
    }
    if (cgv_open(&video, &reader) != CGV_OK) {
        close_video();
        message("This file isn't a", "video. Convert it", "again with the CG50", "Video Converter.");
        return false;
    }
    return true;
}

// --- Screens ------------------------------------------------------------------------------

// The list of videos. Returns the index of the video to open.
static int list_screen(int selected) {
    int top = 0;
    for (;;) {
        char line[48], t[24];
        Bdisp_AllClr_VRAM();
        sprintf(line, " Videos (%d)", video_count);
        text_row(1, line, true);

        if (video_count == 0) {
            text(1, 3, "No videos found.", false);
            text(1, 4, "Copy .bin files into", false);
            text(1, 5, "the calculator's main", false);
            text(1, 6, "folder (USB cable,", false);
            text(1, 7, "USB Flash mode).", false);
            text(1, 8, "EXIT: Look again", false);
        } else {
            if (selected >= video_count) selected = video_count - 1;
            if (selected < top) top = selected;
            if (selected >= top + LIST_ROWS) top = selected - LIST_ROWS + 1;
            for (int r = 0; r < LIST_ROWS && top + r < video_count; r++) {
                const video_entry *e = &videos[top + r];
                if (e->playable) format_time(t, e->seconds);
                else strcpy(t, "(not a video)");
                int room = TEXT_COLS - (int)strlen(t) - 1; // the label, a space, then the length
                int n = 0;
                for (; n < room && e->label[n]; n++) line[n] = e->label[n];
                for (; n <= room; n++) line[n] = ' ';
                strcpy(line + n, t);
                text_row(2 + r, line, top + r == selected);
            }
            text(1, 8, "EXE:Open EXIT:Reload", false);
        }
        Bdisp_PutDisp_DD();

        int key;
        GetKey(&key);
        if (video_count > 0 && key == KEY_CTRL_UP) {
            selected = selected > 0 ? selected - 1 : video_count - 1;
        } else if (video_count > 0 && key == KEY_CTRL_DOWN) {
            selected = selected + 1 < video_count ? selected + 1 : 0;
        } else if ((key == KEY_CTRL_EXE || key == 0x000D) && video_count > 0) {
            if (videos[selected].playable) return selected;
            message("This file isn't a", "video. Convert it", "again with the CG50", "Video Converter.");
        } else if (key == KEY_CTRL_EXIT) {
            scan_videos();
        }
    }
}

// Details of the open video. Returns true to play it, false to go back to the list.
static bool info_screen(const video_entry *e, bool *loop) {
    for (;;) {
        char line[48], t[24], f[24];
        Bdisp_AllClr_VRAM();
        text_row(1, e->label, true);
        text_row(2, e->name, false);
        sprintf(line, "Size: %dx%d (x%d)", video.width, video.height, video.scale);
        text(1, 3, line, false);
        format_fps(f, video.fps100);
        sprintf(line, "Frame rate: %s fps", f);
        text(1, 4, line, false);
        format_time(t, e->seconds);
        sprintf(line, "Length: %s", t);
        text(1, 5, line, false);
        sprintf(line, "%d colors, %lu KB", video.palsize, (e->size + 1023) / 1024);
        text(1, 6, line, false);
        sprintf(line, "Loop: %s", *loop ? "on" : "off");
        text(1, 7, line, false);
        text(1, 8, "EXE:Play F1:Loop", false);
        Bdisp_PutDisp_DD();

        int key;
        GetKey(&key);
        if (key == KEY_CTRL_EXE || key == 0x000D) return true;
        if (key == KEY_CTRL_F1) *loop = !*loop;
        if (key == KEY_CTRL_EXIT) return false;
    }
}

// Shown over the paused picture. Returns true to carry on, false to stop.
static bool pause_screen(unsigned long frames_done, unsigned long fps100_reached) {
    char line[64], t1[24], t2[24];

    SaveVRAM_1(); // the next frames only redraw what changed, so the picture must come back exactly
    unsigned long filled = frames_done >= video.frames ? SCREEN_W
                           : SCREEN_W * frames_done / video.frames; // fine for up to ~11 million frames
    fill_rect(0, 184, SCREEN_W, 8, 0x2104);    // dark gray
    fill_rect(0, 184, (int)filled, 8, 0x07E0); // green
    format_time(t1, frames_done * 100UL / (unsigned long)video.fps100);
    format_time(t2, video_seconds());
    sprintf(line, "II %s/%s", t1, t2);
    if (fps100_reached > 0) {
        sprintf(line + strlen(line), " %lu.%lufps", fps100_reached / 100, fps100_reached % 100 / 10);
    }
    text_row(8, line, true);
    Bdisp_PutDisp_DD();

    for (;;) {
        int key = wait_key(KEYWAIT_HALTON_TIMEROFF);
        if (key == KEY_PRGM_RETURN || key == KEY_PRGM_F1) {
            LoadVRAM_1();
            Bdisp_PutDisp_DD();
            return true;
        }
        if (key == KEY_PRGM_EXIT || key == KEY_PRGM_MENU) {
            LoadVRAM_1();
            return false;
        }
    }
}

enum { PLAY_FINISHED, PLAY_STOPPED, PLAY_DAMAGED };

// Plays the open video from its first frame.
static int play_frames(void) {
    unsigned short *vram = GetVRAMAddress();
    for (int i = 0; i < SCREEN_W * SCREEN_H; i++) vram[i] = 0; // black around small videos

    // Each frame is due 1/fps after the previous one. carry keeps the fraction of a tick,
    // so 29.97 fps stays exact.
    unsigned long start = mono_ticks(), due = start, carry = 0;
    for (unsigned long f = 0; f < video.frames; f++) {
        int result = cgv_decode_frame(&video, &reader, vram);
        if (result == CGV_END) break;
        if (result != CGV_OK) return PLAY_DAMAGED;
        Bdisp_PutDisp_DD();

        carry += 12800; // 128 ticks per second * 100
        due += carry / (unsigned long)video.fps100;
        carry %= (unsigned long)video.fps100;

        for (;;) {
            int key = poll_key();
            if (key == KEY_PRGM_EXIT || key == KEY_PRGM_MENU) return PLAY_STOPPED;
            if (key == KEY_PRGM_RETURN || key == KEY_PRGM_F1) {
                unsigned long paused = mono_ticks();
                unsigned long elapsed = paused - start;
                unsigned long reached = (elapsed > 0 && f < 300000UL) ? (f + 1) * 12800UL / elapsed : 0;
                if (!pause_screen(f + 1, reached)) return PLAY_STOPPED;
                unsigned long pause_ticks = mono_ticks() - paused;
                due += pause_ticks;
                start += pause_ticks;
            }
            unsigned long now = mono_ticks();
            if (now >= due) {
                // More than 1/4 s behind (slow file reads): carry on from now, don't rush
                if (now > due + 32) due = now;
                break;
            }
        }
    }
    return PLAY_FINISHED;
}

// Shown over the last frame. Returns true to play again.
static bool end_screen(void) {
    text_row(7, " Finished", true);
    text_row(8, "EXE:Again  EXIT:Back", true);
    Bdisp_PutDisp_DD();
    for (;;) {
        int key;
        GetKey(&key);
        if (key == KEY_CTRL_EXE || key == 0x000D) return true;
        if (key == KEY_CTRL_EXIT) return false;
    }
}

static void play_video(const video_entry *e, bool loop) {
    for (;;) {
        int result = play_frames();
        if (result == PLAY_STOPPED) return;
        if (result == PLAY_DAMAGED) {
            message("The video data is", "damaged. Convert it", "again.", NULL);
            return;
        }
        if (!loop && !end_screen()) return;
        if (!load_video(e)) return; // reopen, so the next play starts from the first frame
    }
}

// --- Main (never returns; see "File handling" above) ----------------------------------------

int main(void) {
    SetQuitHandler(quit_handler);
    Bdisp_EnableColor(1);

    bool loop = false;
    int selected = 0;
    scan_videos();
    for (;;) {
        selected = list_screen(selected);
        const video_entry *e = &videos[selected];
        if (!load_video(e)) continue;
        while (info_screen(e, &loop)) {
            if (!load_video(e)) break; // every play starts from the first frame
            play_video(e, loop);
        }
        close_video();
    }
}
