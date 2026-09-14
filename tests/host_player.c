/*
 * Runs the calculator's decoder (src/decode.c) on a PC, for the tests.
 *
 *   host_player [--chunk N] [--twice] [--dump FILE] video.bin
 *
 * --chunk N  refill the reader with at most N bytes at a time (stresses buffer edges)
 * --twice    after the last frame, seek back and play again (like the player's replay)
 * --dump     write every decoded screen as 384x216 little-endian RGB565
 *
 * Exit codes: 0 ok, 2 corrupt frame, 4 bad header, 5 usage/IO problem.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "decode.h"

static int chunk = CGV_READER_BUF;
static unsigned short vram[CGV_SCREEN_W * CGV_SCREEN_H];
static cgv_reader reader;

static int refill_file(void *ctx, unsigned char *dst, int max) {
    if (max > chunk)
        max = chunk;
    return (int)fread(dst, 1, (size_t)max, (FILE *)ctx);
}

static void dump(FILE *out) {
    static unsigned char bytes[sizeof vram];
    size_t i;
    for (i = 0; i < CGV_SCREEN_W * CGV_SCREEN_H; i++) {
        bytes[2 * i] = (unsigned char)(vram[i] & 0xFF);
        bytes[2 * i + 1] = (unsigned char)(vram[i] >> 8);
    }
    fwrite(bytes, 1, sizeof bytes, out);
}

static int play(const cgv_video *v, FILE *out, unsigned long *decoded) {
    unsigned long f;
    memset(vram, 0, sizeof vram); /* the player clears the screen to black first */
    for (f = 0; f < v->frames; f++) {
        int rc = cgv_decode_frame(v, &reader, vram);
        if (rc == CGV_END)
            break;
        if (rc != CGV_OK) {
            printf("corrupt at frame %lu\n", f);
            return 2;
        }
        if (out)
            dump(out);
    }
    *decoded = f;
    return 0;
}

int main(int argc, char **argv) {
    const char *path = NULL, *dump_path = NULL;
    int twice = 0, i, rc;
    FILE *in, *out = NULL;
    cgv_video v;
    unsigned long decoded = 0;

    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--chunk") && i + 1 < argc)
            chunk = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--twice"))
            twice = 1;
        else if (!strcmp(argv[i], "--dump") && i + 1 < argc)
            dump_path = argv[++i];
        else
            path = argv[i];
    }
    if (!path || chunk < 1) {
        fprintf(stderr, "usage: host_player [--chunk N] [--twice] [--dump FILE] video.bin\n");
        return 5;
    }
    if (!(in = fopen(path, "rb"))) {
        perror(path);
        return 5;
    }
    if (dump_path && !(out = fopen(dump_path, "wb"))) {
        perror(dump_path);
        return 5;
    }

    cgv_reader_init(&reader, refill_file, in);
    if (cgv_open(&v, &reader) != CGV_OK) {
        printf("bad header\n");
        return 4;
    }
    printf("format=%d width=%d height=%d fps100=%d frames=%lu palsize=%d scale=%d x=%d y=%d title=%s\n",
           v.format, v.width, v.height, v.fps100, v.frames, v.palsize, v.scale, v.x_off, v.y_off, v.title);

    rc = play(&v, out, &decoded);
    if (rc == 0 && twice) {
        fseek(in, (long)v.header_bytes, SEEK_SET);
        cgv_reader_reset(&reader);
        rc = play(&v, out, &decoded);
    }
    printf("decoded=%lu\n", decoded);
    if (out)
        fclose(out);
    fclose(in);
    return rc;
}
