/*
 * Camera ID map: the IDs the camera framework sees versus the vendor HAL's own IDs.
 *
 * A vendor HAL may answer for more cameras than get_number_of_cameras() reports (the Note8's
 * telephoto is Samsung HAL ID 3 while the HAL reports 2). The map exposes the counted IDs
 * unchanged and appends the extra vendor IDs after them:
 *
 *   framework 0 .. vendor_count-1  ->  vendor 0 .. vendor_count-1
 *   framework vendor_count + k     ->  extra_vendor_ids[k]
 *
 * Vendor IDs that are neither counted nor listed (aliases such as a duplicate front camera)
 * are not visible to the framework. Pure C, no Android: tested on the host.
 */
#ifndef INSTRUMENTS_CAMERA_IDMAP_H
#define INSTRUMENTS_CAMERA_IDMAP_H

#ifdef __cplusplus
extern "C" {
#endif

#define CAMERA_IDMAP_MAX_EXTRA 8

typedef struct camera_idmap {
    int vendor_count;
    int n_extra;
    int extra_vendor_ids[CAMERA_IDMAP_MAX_EXTRA];
} camera_idmap_t;

/* Parses a comma-separated ID list ("3" or "3,50") into extra IDs, skipping IDs below
 * vendor_count, duplicates and anything unparsable. Returns the number of extra IDs kept. */
int camera_idmap_init(camera_idmap_t *m, int vendor_count, const char *extra_ids);

/* Drops extra ID k (used when the vendor HAL does not answer for it). */
void camera_idmap_remove_extra(camera_idmap_t *m, int k);

int camera_idmap_count(const camera_idmap_t *m);

/* Vendor ID for a framework ID, or -1 when the framework ID is out of range. */
int camera_idmap_to_vendor(const camera_idmap_t *m, int framework_id);

/* Framework ID for a vendor ID, or -1 when that vendor ID is not exposed. */
int camera_idmap_to_framework(const camera_idmap_t *m, int vendor_id);

#ifdef __cplusplus
}
#endif

#endif
