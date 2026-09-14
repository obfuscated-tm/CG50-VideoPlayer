#include "decode.h"

/* The PC tests build with CGV_CHECK_BOUNDS to prove no write ever leaves the video area. */
#ifdef CGV_CHECK_BOUNDS
#include <assert.h>
#define CHECK(x) assert(x)
#else
#define CHECK(x) ((void)0)
#endif

/* take() results besides a byte value */
#define BUDGET_DONE (-1) /* the frame's bytes are used up */
#define FILE_ENDED (-2)  /* the file ended in the middle of a frame */

void cgv_reader_init(cgv_reader *r, cgv_refill_fn refill, void *ctx) {
    r->refill = refill;
    r->ctx = ctx;
    r->consumed = 0;
    cgv_reader_reset(r);
}

void cgv_reader_reset(cgv_reader *r) {
    r->pos = 0;
    r->len = 0;
    r->eof = 0;
}

/* Next byte of the file, or -1 at the end. */
static int next_byte(cgv_reader *r) {
    if (r->pos >= r->len) {
        int n;
        if (r->eof)
            return -1;
        n = r->refill(r->ctx, r->buf, CGV_READER_BUF);
        if (n <= 0) {
            r->eof = 1;
            r->pos = r->len = 0;
            return -1;
        }
        if (n > CGV_READER_BUF)
            n = CGV_READER_BUF;
        r->len = n;
        r->pos = 0;
    }
    r->consumed++;
    return r->buf[r->pos++];
}

static int read_bytes(cgv_reader *r, unsigned char *dst, int n) {
    int i, c;
    for (i = 0; i < n; i++) {
        if ((c = next_byte(r)) < 0)
            return 0;
        dst[i] = (unsigned char)c;
    }
    return 1;
}

static unsigned int be16(const unsigned char *p) { return ((unsigned int)p[0] << 8) | p[1]; }

static unsigned long be32(const unsigned char *p) {
    return ((unsigned long)p[0] << 24) | ((unsigned long)p[1] << 16) | ((unsigned long)p[2] << 8) | p[3];
}

int cgv_open(cgv_video *v, cgv_reader *r) {
    unsigned char h[128];
    int i;

    v->title[0] = '\0';
    if (!read_bytes(r, h, 4))
        return CGV_ERR_HEADER;

    if (h[0] == 'C' && h[1] == 'G' && h[2] == 'V' && h[3] == '2') {
        if (!read_bytes(r, h + 4, 124) || h[4] != 2)
            return CGV_ERR_HEADER;
        v->format = 2;
        v->width = (int)be16(h + 6);
        v->height = (int)be16(h + 8);
        v->fps100 = (int)be16(h + 10);
        v->frames = be32(h + 12);
        v->palsize = h[16];
        for (i = 0; i < 16; i++)
            v->palette[i] = (unsigned short)be16(h + 17 + 2 * i);
        for (i = 0; i < 24 && h[49 + i] != 0; i++)
            v->title[i] = (h[49 + i] >= 32 && h[49 + i] < 127) ? (char)h[49 + i] : '?';
        v->title[i] = '\0';
        v->header_bytes = 128;
    } else {
        /* Format 1: frames u32, width u16, height u16, fps u16, palette size u8, palette */
        unsigned int fps;
        if (!read_bytes(r, h + 4, 7))
            return CGV_ERR_HEADER;
        v->format = 1;
        v->frames = be32(h);
        v->width = (int)be16(h + 4);
        v->height = (int)be16(h + 6);
        fps = be16(h + 8);
        v->palsize = h[10];
        if (fps > 655 || v->palsize < 1 || v->palsize > 16)
            return CGV_ERR_HEADER;
        v->fps100 = (int)fps * 100;
        if (!read_bytes(r, h, 2 * v->palsize))
            return CGV_ERR_HEADER;
        for (i = 0; i < 16; i++)
            v->palette[i] = i < v->palsize ? (unsigned short)be16(h + 2 * i) : 0;
        v->header_bytes = 11 + 2 * (unsigned long)v->palsize;
    }

    if (v->width < 1 || v->width > CGV_SCREEN_W || v->height < 1 || v->height > CGV_SCREEN_H ||
        v->fps100 < 1 || v->palsize < 1 || v->palsize > 16 || v->frames < 1)
        return CGV_ERR_HEADER;

    v->scale = CGV_SCREEN_W / v->width;
    if (CGV_SCREEN_H / v->height < v->scale)
        v->scale = CGV_SCREEN_H / v->height;
    v->x_off = (CGV_SCREEN_W - v->width * v->scale) / 2;
    v->y_off = (CGV_SCREEN_H - v->height * v->scale) / 2;
    return CGV_OK;
}

/* Where the next pixel goes. pos counts pixels in raster order; px/py track it without dividing. */
typedef struct {
    const cgv_video *v;
    unsigned short *vram;
    unsigned long pos, total;
    int px, py;
    cgv_reader *r;
    unsigned long left; /* bytes of this frame not read yet */
} frame_state;

static int take(frame_state *s) {
    int c;
    if (s->left == 0)
        return BUDGET_DONE;
    s->left--;
    c = next_byte(s->r);
    return c < 0 ? FILE_ENDED : c;
}

/* Fills `count` pixels of one video row (count <= width - px). */
static void draw_span(frame_state *s, int count, unsigned short color) {
    const cgv_video *v = s->v;
    int scale = v->scale, width = count * scale, dy, i;
    unsigned short *line = s->vram + (v->y_off + s->py * scale) * CGV_SCREEN_W + v->x_off + s->px * scale;
    CHECK(count > 0 && s->px + count <= v->width && s->py < v->height);
    CHECK(v->x_off + (s->px + count) * scale <= CGV_SCREEN_W && v->y_off + (s->py + 1) * scale <= CGV_SCREEN_H);
    for (dy = 0; dy < scale; dy++, line += CGV_SCREEN_W)
        for (i = 0; i < width; i++)
            line[i] = color;
}

static void put_run(frame_state *s, int index, unsigned long length) {
    const cgv_video *v = s->v;
    unsigned short color = v->palette[index < v->palsize ? index : 0];
    if (length > s->total - s->pos)
        length = s->total - s->pos;
    s->pos += length;
    while (length > 0) {
        int span = v->width - s->px;
        if ((unsigned long)span > length)
            span = (int)length;
        draw_span(s, span, color);
        s->px += span;
        length -= (unsigned long)span;
        if (s->px == v->width) {
            s->px = 0;
            s->py++;
        }
    }
}

static void skip_pixels(frame_state *s, unsigned long length) {
    int width = s->v->width;
    if (length > s->total - s->pos)
        length = s->total - s->pos;
    s->pos += length;
    s->py += (int)(length / (unsigned long)width);
    s->px += (int)(length % (unsigned long)width);
    if (s->px >= width) {
        s->px -= width;
        s->py++;
    }
}

static int decode_format1(frame_state *s) {
    while (s->left > 0) {
        int count = take(s), index = take(s);
        if (count < 0 || index < 0)
            return CGV_ERR_CORRUPT;
        put_run(s, index, (unsigned long)count);
    }
    return CGV_OK;
}

/* Reads an n8 (1 byte) or n16 (2 byte) length field; returns length-1 or a negative error. */
static long read_len(frame_state *s, int bytes) {
    int hi = take(s), lo;
    if (hi < 0)
        return -1;
    if (bytes == 1)
        return hi;
    if ((lo = take(s)) < 0)
        return -1;
    return ((long)hi << 8) | lo;
}

static int decode_format2(frame_state *s) {
    for (;;) {
        int op = take(s);
        long n;
        if (op == BUDGET_DONE)
            return CGV_OK;
        if (op == FILE_ENDED)
            return CGV_ERR_CORRUPT;
        if (op == 0xFF)
            break;
        if (op < 0x80) { /* 0ccccLLL: short run */
            put_run(s, op >> 3, (unsigned long)(op & 7) + 1);
        } else if (op < 0xC0) { /* 10LLLLLL: short skip */
            skip_pixels(s, (unsigned long)(op & 0x3F) + 1);
        } else if (op < 0xE0) { /* 1100cccc n8 / 1101cccc n16: long run */
            if ((n = read_len(s, op < 0xD0 ? 1 : 2)) < 0)
                return CGV_ERR_CORRUPT;
            put_run(s, op & 0x0F, (unsigned long)n + 1);
        } else if (op == 0xE0 || op == 0xE1) { /* long skip */
            if ((n = read_len(s, op == 0xE0 ? 1 : 2)) < 0)
                return CGV_ERR_CORRUPT;
            skip_pixels(s, (unsigned long)n + 1);
        } else if (op == 0xF0) { /* literal: count, then 2 pixels per byte */
            int count, k, byte = 0;
            if ((n = read_len(s, 1)) < 0)
                return CGV_ERR_CORRUPT;
            count = (int)n + 1;
            for (k = 0; k < count; k++) {
                if ((k & 1) == 0 && (byte = take(s)) < 0)
                    return CGV_ERR_CORRUPT;
                put_run(s, (k & 1) ? (byte & 0x0F) : (byte >> 4), 1);
            }
        } else {
            return CGV_ERR_CORRUPT; /* unused opcode */
        }
    }
    /* Skip anything after the end marker so the next frame starts in the right place. */
    while (s->left > 0)
        if (take(s) < 0)
            return CGV_ERR_CORRUPT;
    return CGV_OK;
}

int cgv_decode_frame(const cgv_video *v, cgv_reader *r, unsigned short *vram) {
    frame_state s;
    unsigned char len[4];
    int c, i;

    if ((c = next_byte(r)) < 0)
        return CGV_END;
    len[0] = (unsigned char)c;
    for (i = 1; i < 4; i++) {
        if ((c = next_byte(r)) < 0)
            return CGV_ERR_CORRUPT;
        len[i] = (unsigned char)c;
    }

    s.v = v;
    s.vram = vram;
    s.r = r;
    s.pos = 0;
    s.px = s.py = 0;
    s.total = (unsigned long)v->width * (unsigned long)v->height;
    s.left = be32(len);

    if (v->format == 1) {
        if (s.left == 0 || (s.left & 1) || s.left > 2 * s.total)
            return CGV_ERR_CORRUPT;
        return decode_format1(&s);
    }
    if (s.left > s.total + 1)
        return CGV_ERR_CORRUPT;
    return decode_format2(&s);
}
