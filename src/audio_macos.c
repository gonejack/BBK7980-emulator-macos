/* CoreAudio (AudioQueue) PCM output for the macOS port, GPL-3.0-or-later.
 *
 * The emulator produces 22050 Hz mono signed 16-bit samples in Python. This
 * file owns the device queue and a lock-protected ring buffer so the realtime
 * audio thread never enters Python. Python writes at its own pace; the
 * callback fills each device buffer from the ring and pads with silence.
 */
#include <stdint.h>
#include <string.h>
#include <pthread.h>
#include <AudioToolbox/AudioToolbox.h>

#define API __attribute__((visibility("default")))

#define RING_SAMPLES 65536u
#define RING_MASK (RING_SAMPLES - 1u)
#define BUFFER_COUNT 3
#define BUFFER_FRAMES 1024
#define SAMPLE_RATE 22050.0

static int16_t ring[RING_SAMPLES];
static uint32_t ring_head; /* read position */
static uint32_t ring_tail; /* write position */
static pthread_mutex_t ring_lock = PTHREAD_MUTEX_INITIALIZER;

static AudioQueueRef queue;
static AudioQueueBufferRef buffers[BUFFER_COUNT];
static int queue_running;

static void queue_fill(AudioQueueRef out, AudioQueueBufferRef buffer) {
    int16_t *samples = (int16_t *)buffer->mAudioData;
    uint32_t capacity = buffer->mAudioDataBytesCapacity / sizeof(int16_t);
    uint32_t available, taken, first;

    pthread_mutex_lock(&ring_lock);
    available = ring_tail - ring_head;
    taken = available < capacity ? available : capacity;
    first = RING_SAMPLES - (ring_head & RING_MASK);
    if (first > taken) first = taken;
    memcpy(samples, ring + (ring_head & RING_MASK), first * sizeof(int16_t));
    if (taken > first) {
        memcpy(samples + first, ring, (taken - first) * sizeof(int16_t));
    }
    ring_head += taken;
    pthread_mutex_unlock(&ring_lock);

    if (taken < capacity) {
        memset(samples + taken, 0, (capacity - taken) * sizeof(int16_t));
    }
    buffer->mAudioDataByteSize = capacity * sizeof(int16_t);
    AudioQueueEnqueueBuffer(out, buffer, 0, NULL);
}

static void queue_callback(void *user, AudioQueueRef out, AudioQueueBufferRef buffer) {
    (void)user;
    if (!queue_running) return;
    queue_fill(out, buffer);
}

API int bbk_out_open(void) {
    AudioStreamBasicDescription format;
    int index;

    if (queue_running) return 0;
    memset(&format, 0, sizeof(format));
    format.mSampleRate = SAMPLE_RATE;
    format.mFormatID = kAudioFormatLinearPCM;
    format.mFormatFlags = kAudioFormatFlagIsSignedInteger | kAudioFormatFlagIsPacked;
    format.mBytesPerPacket = 2;
    format.mFramesPerPacket = 1;
    format.mBytesPerFrame = 2;
    format.mChannelsPerFrame = 1;
    format.mBitsPerChannel = 16;

    ring_head = ring_tail = 0;
    if (AudioQueueNewOutput(&format, queue_callback, NULL, NULL, NULL, 0, &queue) != noErr) {
        queue = NULL;
        return -1;
    }
    for (index = 0; index < BUFFER_COUNT; index++) {
        if (AudioQueueAllocateBuffer(queue, BUFFER_FRAMES * (UInt32)sizeof(int16_t),
                                     &buffers[index]) != noErr) {
            AudioQueueDispose(queue, true);
            queue = NULL;
            return -1;
        }
        queue_fill(queue, buffers[index]);
    }
    queue_running = 1;
    if (AudioQueueStart(queue, NULL) != noErr) {
        queue_running = 0;
        AudioQueueDispose(queue, true);
        queue = NULL;
        return -1;
    }
    return 0;
}

API void bbk_out_write(const int16_t *samples, uint32_t count) {
    uint32_t available, first;

    if (!queue_running || samples == NULL || count == 0) return;
    if (count > RING_SAMPLES) {
        /* The emulator asks for up to 262144 samples at once; only the newest
         * window fits the device ring. */
        samples += count - RING_SAMPLES;
        count = RING_SAMPLES;
    }
    pthread_mutex_lock(&ring_lock);
    available = ring_tail - ring_head;
    if (count > RING_SAMPLES - available) {
        /* Keep latency bounded when the host falls behind. */
        ring_head = ring_tail - (RING_SAMPLES - count);
    }
    first = RING_SAMPLES - (ring_tail & RING_MASK);
    if (first > count) first = count;
    memcpy(ring + (ring_tail & RING_MASK), samples, first * sizeof(int16_t));
    if (count > first) {
        memcpy(ring, (const int16_t *)samples + first,
               (count - first) * sizeof(int16_t));
    }
    ring_tail += count;
    pthread_mutex_unlock(&ring_lock);
}

API void bbk_out_clear(void) {
    pthread_mutex_lock(&ring_lock);
    ring_head = ring_tail;
    pthread_mutex_unlock(&ring_lock);
}

API int bbk_out_available(void) {
    return queue_running;
}

API void bbk_out_close(void) {
    if (!queue_running) return;
    queue_running = 0;
    AudioQueueDispose(queue, true);
    queue = NULL;
    pthread_mutex_lock(&ring_lock);
    ring_head = ring_tail;
    pthread_mutex_unlock(&ring_lock);
}
