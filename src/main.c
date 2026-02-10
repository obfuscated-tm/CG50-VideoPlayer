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

// HELPER FUNCTIONS
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

    // Header and Menu
    // Frames(4), Width(2), Height(2), FPS(2), PalSize(1)
    unsigned int totalFrames = read32(hFile);
    unsigned short w = read16(hFile);
    unsigned short h = read16(hFile);
    unsigned short fps = read16(hFile);
    unsigned char palSize;
    Bfile_ReadFile_OS(hFile, &palSize, 1, -1);

    // Exits if video dimensions/palette size/fps are invalid
    if (w == 0 || h == 0 || w > 384 || h > 216 || fps == 0 || palSize == 0 || palSize > 16) {
        clearDisplay();
        locate_OS(1, 2); Print_OS("BAD VIDEO FILE", 0, 0);
        while (1) { int k; GetKey(&k); if (k == KEY_CTRL_EXIT) break; }
        g_hFile = -1;
        return 0;
    }


    int scaleX = 384 / w;
    int scaleY = 216 / h;
    int scale = (scaleX < scaleY) ? scaleX : scaleY;
    if (scale < 1) scale = 1;

    while (1) {
        int key = 0;
        drawMainMenu(totalFrames, w, h, fps, scale);
        GetKey(&key);
        if (key == KEY_CTRL_EXE || key == 0x000D) break; 
        if (key == KEY_CTRL_EXIT) {
            g_hFile = -1;
            return 0;
        }
    }

    for(int i=0; i < (palSize > 16 ? 16 : palSize); i++) {
        global_palette[i] = read16(hFile);
    }

    int x_off = (384 - (w * scale)) / 2;
    int y_off = (216 - (h * scale)) / 2;
    unsigned short *vram = GetVRAMAddress();
    Bdisp_AllClr_VRAM();

    // Playback Loop (goes through every frame)
    for(unsigned int f = 0; f < totalFrames; f++) {
        int ticks = RTC_GetTicks(); // Used to control FPS
        unsigned int frameSize = read32(hFile);

        if (frameSize == 0 || frameSize > 30000 || (frameSize & 1)) {
            break; // corrupted frame
        }
        
        if (Bfile_ReadFile_OS(hFile, compressed_buffer, frameSize, -1) != frameSize) {
            break;
        }


        int px = 0, py = 0;
        for(unsigned int i = 0; i < frameSize; i += 2) { // RLE
            unsigned char count = compressed_buffer[i];
            unsigned char pal_idx = compressed_buffer[i+1];
            if (pal_idx >= palSize) continue; // Skips if invalid palette index
            unsigned short color = global_palette[pal_idx];


            for(int n = 0; n < count; n++) {
                if (py >= h) break;
                int sx = (px * scale) + x_off;
                int sy = (py * scale) + y_off;
                
                // Write to VRAM
                for(int dy = 0; dy < scale; dy++) {
                    unsigned short* line = &vram[(sy + dy) * 384 + sx];
                    for(int dx = 0; dx < scale; dx++) line[dx] = color;
                }
                px++;
                if(px >= w) { px = 0; py++; } // Next line
            }
        }
        Bdisp_PutDisp_DD(); // Display frame

        // Check if user wants to exit
        if (wait_for_exit(ticks, 1000 / fps)) break; 
    }

    // Exit screen (must go into another app)
    clearDisplay();
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