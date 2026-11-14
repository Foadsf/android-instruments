#include "instruments/bridge_queue.h"
#include "instruments/check.hpp"

namespace {
int buf[64];  // stand-ins for buffer_handle_t* identities
void *B(int i) { return &buf[i]; }
}  // namespace

INSTRUMENTS_TEST(fifo_dequeue_enqueue_pop_in_frame_order) {
    bridge_queue_t q;
    bq_init(&q);
    for (int i = 0; i < 3; ++i) INSTRUMENTS_CHECK(bq_push(&q, 100 + i, B(i), -1) == 0);
    INSTRUMENTS_CHECK(bq_dequeue(&q)->frame == 100);
    INSTRUMENTS_CHECK(bq_dequeue(&q)->frame == 101);
    INSTRUMENTS_CHECK(bq_enqueue(&q, B(0), 5) == 0);
    bq_slot_t out;
    INSTRUMENTS_CHECK(bq_pop(&q, &out) == 1 && out.frame == 100 && out.timestamp == 5 && out.state == BQ_DONE);
    INSTRUMENTS_CHECK(bq_pop(&q, &out) == 0);  // 101 still dequeued
}

INSTRUMENTS_TEST(out_of_order_completion_is_held_until_older_frames_finish) {
    bridge_queue_t q;
    bq_init(&q);
    bq_push(&q, 1, B(1), -1);
    bq_push(&q, 2, B(2), -1);
    bq_dequeue(&q);
    bq_dequeue(&q);
    INSTRUMENTS_CHECK(bq_enqueue(&q, B(2), 20) == 0);
    bq_slot_t out;
    INSTRUMENTS_CHECK(bq_pop(&q, &out) == 0);  // frame 2 done but frame 1 is not: hold
    bq_enqueue(&q, B(1), 10);
    INSTRUMENTS_CHECK(bq_pop(&q, &out) == 1 && out.frame == 1);
    INSTRUMENTS_CHECK(bq_pop(&q, &out) == 1 && out.frame == 2);
}

INSTRUMENTS_TEST(fail_marks_one_dequeued_entry_as_error) {
    bridge_queue_t q;
    bq_init(&q);
    bq_push(&q, 1, B(1), -1);
    bq_push(&q, 2, B(2), -1);
    bq_dequeue(&q);
    INSTRUMENTS_CHECK(bq_fail(&q, B(2)) == -1);  // still pending, not dequeued
    INSTRUMENTS_CHECK(bq_fail(&q, B(1)) == 0);
    bq_slot_t out;
    INSTRUMENTS_CHECK(bq_pop(&q, &out) == 1 && out.frame == 1 && out.state == BQ_ERROR);
    INSTRUMENTS_CHECK(bq_pop(&q, &out) == 0);
}

INSTRUMENTS_TEST(cancel_returns_buffer_to_pending_and_it_is_dequeued_again) {
    bridge_queue_t q;
    bq_init(&q);
    bq_push(&q, 7, B(7), -1);
    bq_push(&q, 8, B(8), -1);
    bq_dequeue(&q);
    INSTRUMENTS_CHECK(bq_cancel(&q, B(7)) == 0);
    INSTRUMENTS_CHECK(bq_dequeue(&q)->frame == 7);  // oldest first again
    INSTRUMENTS_CHECK(bq_cancel(&q, B(9)) == -1);
    INSTRUMENTS_CHECK(bq_enqueue(&q, B(8), 1) == -1);  // 8 was never dequeued
}

INSTRUMENTS_TEST(fail_all_errors_outstanding_and_keeps_done) {
    bridge_queue_t q;
    bq_init(&q);
    bq_push(&q, 1, B(1), -1);
    bq_push(&q, 2, B(2), -1);
    bq_push(&q, 3, B(3), -1);
    bq_dequeue(&q);
    bq_enqueue(&q, B(1), 9);
    bq_dequeue(&q);
    bq_fail_all(&q);
    bq_slot_t out;
    INSTRUMENTS_CHECK(bq_pop(&q, &out) == 1 && out.state == BQ_DONE);
    INSTRUMENTS_CHECK(bq_pop(&q, &out) == 1 && out.state == BQ_ERROR && out.frame == 2);
    INSTRUMENTS_CHECK(bq_pop(&q, &out) == 1 && out.state == BQ_ERROR && out.frame == 3);
    INSTRUMENTS_CHECK(q.count == 0);
}

INSTRUMENTS_TEST(full_queue_refuses_and_ring_wraps) {
    bridge_queue_t q;
    bq_init(&q);
    for (int i = 0; i < BQ_CAPACITY; ++i) bq_push(&q, (uint32_t)i, B(i % 64), -1);
    INSTRUMENTS_CHECK(bq_push(&q, 999, B(0), -1) == -1);
    bq_slot_t out;
    for (int k = 0; k < 40; ++k) {  // wrap the ring past its capacity
        bq_slot_t *s = bq_dequeue(&q);
        bq_enqueue(&q, s->buffer, k);
        INSTRUMENTS_CHECK(bq_pop(&q, &out) == 1 && out.frame == (uint32_t)k);
        bq_push(&q, (uint32_t)(BQ_CAPACITY + k), B((BQ_CAPACITY + k) % 64), -1);
    }
    INSTRUMENTS_CHECK(bq_count_state(&q, BQ_PENDING) == BQ_CAPACITY);
}
