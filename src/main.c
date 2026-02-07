#include <fxcg/display.h>
#include <fxcg/keyboard.h>
#include <fxcg/file.h>
#include <fxcg/rtc.h>

void initialize(void) __attribute__((section(".pretext")));
void ___fpscr_values() {}
int main(void); 
void initialize(void) { main(); }

#define FILE_PATH "\\\\fls0\\video.bin"
static unsigned char compressed_buffer[12000]; 
static unsigned short global_palette[64]; // Can hold up to 64 colors now

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

int main(void) {
    unsigned short pFile[64];
    Bdisp_EnableColor(1);
    Bdisp_AllClr_VRAM();

    Bfile_StrToName_ncpy(pFile, (const char*)FILE_PATH, 64);
    int hFile = Bfile_OpenFile_OS(pFile, 0, 0);
    if(hFile < 0) return 1;

    unsigned int totalFrames = read32(hFile);
    unsigned short w = read16(hFile);
    unsigned short h = read16(hFile);
    unsigned short fps = read16(hFile);
    
    // Read palette size from header (8-bit)
    unsigned char palSize;
    Bfile_ReadFile_OS(hFile, &palSize, 1, -1);

    for(int i=0; i < palSize; i++) global_palette[i] = read16(hFile);

    int ms_per_frame = 1000 / fps;
    unsigned short *vram = GetVRAMAddress();

    for(unsigned int f = 0; f < totalFrames; f++) {
        int frame_start = RTC_GetTicks();
        if (PRGM_GetKey() == KEY_CTRL_EXIT) break;

        unsigned int frameSize = read32(hFile);
        Bfile_ReadFile_OS(hFile, compressed_buffer, frameSize, -1);

        int px = 0, py = 0;
        for(unsigned int i = 0; i < frameSize; i += 2) {
            unsigned char count = compressed_buffer[i];
            unsigned char pal_idx = compressed_buffer[i+1];
            unsigned short color = global_palette[pal_idx];

            for(int c = 0; c < count; c++) {
                int sx = px * 3;
                int sy = (py * 3) + 12;

                for(int dy = 0; dy < 3; dy++) {
                    unsigned short* line = &vram[(sy + dy) * 384 + sx];
                    line[0] = color; line[1] = color; line[2] = color;
                }
                px++;
                if(px >= w) { px = 0; py++; }
            }
        }
        Bdisp_PutDisp_DD();
        while(RTC_Elapsed_ms(frame_start, ms_per_frame) == 0);
    }

    Bfile_CloseFile_OS(hFile);
    return 0;
}