#include "instruments/camera_idmap.h"

#include <stdlib.h>

static int contains(const camera_idmap_t *m, int id) {
    for (int k = 0; k < m->n_extra; ++k)
        if (m->extra_vendor_ids[k] == id) return 1;
    return 0;
}

int camera_idmap_init(camera_idmap_t *m, int vendor_count, const char *extra_ids) {
    m->vendor_count = vendor_count < 0 ? 0 : vendor_count;
    m->n_extra = 0;
    const char *p = extra_ids;
    while (p != NULL && *p != '\0' && m->n_extra < CAMERA_IDMAP_MAX_EXTRA) {
        char *end = NULL;
        long id = strtol(p, &end, 10);
        if (end == p) {
            ++p; /* skip a separator or junk character */
            continue;
        }
        if (id >= m->vendor_count && id < 10000 && !contains(m, (int)id))
            m->extra_vendor_ids[m->n_extra++] = (int)id;
        p = end;
    }
    return m->n_extra;
}

void camera_idmap_remove_extra(camera_idmap_t *m, int k) {
    if (k < 0 || k >= m->n_extra) return;
    for (int j = k + 1; j < m->n_extra; ++j) m->extra_vendor_ids[j - 1] = m->extra_vendor_ids[j];
    --m->n_extra;
}

int camera_idmap_count(const camera_idmap_t *m) { return m->vendor_count + m->n_extra; }

int camera_idmap_to_vendor(const camera_idmap_t *m, int framework_id) {
    if (framework_id < 0) return -1;
    if (framework_id < m->vendor_count) return framework_id;
    int k = framework_id - m->vendor_count;
    return k < m->n_extra ? m->extra_vendor_ids[k] : -1;
}

int camera_idmap_to_framework(const camera_idmap_t *m, int vendor_id) {
    if (vendor_id >= 0 && vendor_id < m->vendor_count) return vendor_id;
    for (int k = 0; k < m->n_extra; ++k)
        if (m->extra_vendor_ids[k] == vendor_id) return m->vendor_count + k;
    return -1;
}
