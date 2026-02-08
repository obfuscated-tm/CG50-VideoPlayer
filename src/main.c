#include <fxcg/display.h>
#include <fxcg/keyboard.h>
#include <fxcg/rtc.h>
#include <fxcg/system.h>
#include <fxcg/misc.h>
#include <fxcg/file.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>

#define FILE_PATH "\\\\fls0\\video.bin"
#define READ 0

// Buffer for compressed frame data
static unsigned char compressed_buffer[30000]; 
static unsigned short global_palette[16];

// --- HELPER FUNCTIONS ---

void clearDisplay() {
    unsigned short *p = GetVRAMAddress();
    for (int i = 0; i < 216 * 384; i++) {
        *p++ = 65535; // White
    }
    Bdisp_PutDisp_DD();
}

unsigned int read32(int file) {
    unsigned char b[4];
    Bfile_ReadFile_OS(file, b, 4, -1);
    return (unsigned int)((b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]);
}

unsigned short read16(int file) {
    unsigned char b[2];
    Bfile_ReadFile_OS(file, b, 2, -1);
    return (unsigned short)((b[0] << 8) | b[1]);
}

bool wait_for_exit(int ticks, int ms) {
    int row, col;
    do {
        GetKeyWait_OS(&col, &row, KEYWAIT_HALTOFF_TIMEROFF, 0, 0, NULL);
        if ((col == 4 && row == 9) || (col == 1 && row == 9)) { // MENU or EXIT
            return true;
        }
    } while (RTC_Elapsed_ms(ticks, ms) == 0);
    return false;
}

void drawMainMenu(unsigned int frameCount, int width, int height, int fps, int scale) {
    char buf[32];
    Bdisp_AllClr_VRAM();

    locate_OS(1, 1);
    Print_OS("--- VIDEO PLAYER ---", 0, 0);

    sprintf(buf, "Frames: %u", frameCount);
    locate_OS(1, 3); Print_OS(buf, 0, 0);

    sprintf(buf, "Res: %dx%d", width, height);
    locate_OS(1, 4); Print_OS(buf, 0, 0);

    sprintf(buf, "FPS: %d", fps);
    locate_OS(1, 5); Print_OS(buf, 0, 0);

    sprintf(buf, "Scale: %d", scale);
    locate_OS(1, 6); Print_OS(buf, 0, 0);

    locate_OS(1, 8);
    Print_OS("EXE: Play Video", 0, 0);

    Bdisp_PutDisp_DD();
}

void kill_all_user_timers() {
    // Timers 5 through 10 are the "User" timers for add-ins
    for (int i = 5; i <= 10; i++) {
        Timer_Deinstall(i); 
    }
}

// --- MAIN LOGIC ---
int main(void) {
    kill_all_user_timers();
    unsigned short pFile[64];
    Bdisp_EnableColor(1);
    clearDisplay();

    Bfile_StrToName_ncpy(pFile, (const char*)FILE_PATH, 64);
    int hFile = Bfile_OpenFile_OS(pFile, READ, 0);

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

    // --- Header and Menu ---
    unsigned int totalFrames = read32(hFile);
    unsigned short w = read16(hFile);
    unsigned short h = read16(hFile);
    unsigned short fps = read16(hFile);
    unsigned char palSize;
    Bfile_ReadFile_OS(hFile, &palSize, 1, -1);

    int scaleX = 384 / w;
    int scaleY = 216 / h;
    int scale = (scaleX < scaleY) ? scaleX : scaleY;
    if (scale < 1) scale = 1;

    while (1) {
        int key = 0;
        drawMainMenu(totalFrames, w, h, fps, scale);
        GetKey(&key);
        if (key == KEY_CTRL_EXE || key == 0x000D) break; 
        if (key == KEY_CTRL_EXIT) goto end_app; // Use goto to ensure cleanup
    }

    for(int i=0; i < (palSize > 16 ? 16 : palSize); i++) {
        global_palette[i] = read16(hFile);
    }

    int x_off = (384 - (w * scale)) / 2;
    int y_off = (216 - (h * scale)) / 2;
    unsigned short *vram = GetVRAMAddress();
    Bdisp_AllClr_VRAM();

    // --- Playback Loop ---
    for(unsigned int f = 0; f < totalFrames; f++) {
        int ticks = RTC_GetTicks();
        unsigned int frameSize = read32(hFile);
        
        if (frameSize > 30000) {
            Bfile_SeekFile_OS(hFile, Bfile_TellFile_OS(hFile) + frameSize);
            continue;
        }
        
        Bfile_ReadFile_OS(hFile, compressed_buffer, frameSize, -1);

        int px = 0, py = 0;
        for(unsigned int i = 0; i < frameSize; i += 2) {
            unsigned char count = compressed_buffer[i];
            unsigned char pal_idx = compressed_buffer[i+1];
            unsigned short color = global_palette[pal_idx];

            for(int n = 0; n < count; n++) {
                int sx = (px * scale) + x_off;
                int sy = (py * scale) + y_off;
                for(int dy = 0; dy < scale; dy++) {
                    unsigned short* line = &vram[(sy + dy) * 384 + sx];
                    for(int dx = 0; dx < scale; dx++) line[dx] = color;
                }
                px++;
                if(px >= w) { px = 0; py++; }
            }
        }
        Bdisp_PutDisp_DD();
        if (wait_for_exit(ticks, 1000 / fps)) break;
    }

    // Exit screen
    clearDisplay();
    locate_OS(1, 4); Print_OS("Enter another", 0, 0);
    locate_OS(1, 5); Print_OS("app to replay.", 0, 0);

    while(1) {
        int key;
        GetKey(&key);
        if (key == KEY_CTRL_EXIT) break;
    }

end_app:
    // Safety to prevent video.bin not found
    if (hFile >= 0) {
        Bfile_CloseFile_OS(hFile);
    }
    return 0;
}