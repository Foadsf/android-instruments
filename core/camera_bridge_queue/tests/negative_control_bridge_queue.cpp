// Negative control: registered WILL_FAIL. Claims a later frame can be popped before an earlier
// unfinished one; the queue must hold it, so this must fail.
#include "instruments/bridge_queue.h"
#include "instruments/check.hpp"

INSTRUMENTS_TEST(later_frame_must_not_jump_the_queue) {
    static int b1, b2;
    bridge_queue_t q;
    bq_init(&q);
    bq_push(&q, 1, &b1, -1);
    bq_push(&q, 2, &b2, -1);
    bq_dequeue(&q);
    bq_dequeue(&q);
    bq_enqueue(&q, &b2, 1);
    bq_slot_t out;
    INSTRUMENTS_CHECK(bq_pop(&q, &out) == 1);
}
