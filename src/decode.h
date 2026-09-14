#ifndef CGV_DECODE_H
#define CGV_DECODE_H

/*
 * Video file decoding, shared by the add-in (main.c) and the PC tests
 * (tests/host_player.c). It deliberately uses no calculator headers.
 * The file layouts are described in docs/FORMAT.md.
 */

#define CGV_SCREEN_W 384
#define CGV_SCREEN_H 216
#define CGV_READER_BUF 8192

enum {
    CGV_OK = 0,
    CGV_END = 1,          /* no more frames in the file */
    CGV_ERR_CORRUPT = -1, /* bad frame data; stop playing */
    CGV_ERR_HEADER = -3   /* not a video, or an unsupported one */
};

/* Copies up to `max` bytes of the file into dst. Returns the byte count; 0 means end of file. */
typedef int (*cgv_refill_fn)(void *ctx, unsigned char *dst, int max);

/* Reads the file in 8 KB blocks, so frames of any size can be decoded. */
typedef struct {
    unsigned char buf[CGV_READER_BUF];
    int pos, len;
    int eof;
    unsigned long consumed; /* bytes handed out so far (for the stats overlay) */
    cgv_refill_fn refill;
    void *ctx;
} cgv_reader;

typedef struct {
    int format;                 /* 1 = original layout, 2 = "CGV2" */
    int width, height;
    int fps100;                 /* frames per second x 100 */
    unsigned long frames;
    int palsize;
    unsigned short palette[16]; /* RGB565 */
    char title[25];             /* empty for format 1 */
    unsigned long header_bytes; /* offset of the first frame (seek here to replay) */
    int scale, x_off, y_off;    /* where the video sits on the 384x216 screen */
} cgv_video;

void cgv_reader_init(cgv_reader *r, cgv_refill_fn refill, void *ctx);

/* Forget buffered data; call after seeking the underlying file. */
void cgv_reader_reset(cgv_reader *r);

/* Reads and checks the header. Returns CGV_OK or CGV_ERR_HEADER. */
int cgv_open(cgv_video *v, cgv_reader *r);

/*
 * Decodes the next frame into vram (384x216 RGB565). Format 2 frames only redraw what
 * changed, so vram must still hold the previous frame (and be cleared before frame 0).
 * Returns CGV_OK, CGV_END or CGV_ERR_CORRUPT. Never writes outside the video's rectangle.
 */
int cgv_decode_frame(const cgv_video *v, cgv_reader *r, unsigned short *vram);

#endif
