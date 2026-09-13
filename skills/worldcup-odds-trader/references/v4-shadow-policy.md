# V4 Shadow Policy

V3 remains the sole production decision authority. V4 is forward shadow research only and must use `v4_shadow_` field prefixes.

- Action candidates require authoritative intent side `giving` or `receiving`; neutral/conditional rows are descriptive only.
- A_SHADOW: EV_p10 > 0 and P(EV>0) >= 0.95, with data quality and stability passing.
- B_SHADOW: EV_mean > 0 and P(EV>0) >= 0.85, but not A.
- C_SHADOW: directional signal without executable-quality evidence.
- N_SHADOW: no measurable edge.
- Reverse is only `REVERSE_A_SHADOW` with n>=30, positive conservative reverse EV, P>=95%, two positive time windows, real water, and no concentration. Otherwise use `REVERSE_WATCH` or `NO_REVERSE_EDGE`.

Historical replay never becomes a live stake recommendation. No direction quota, no automatic promotion, and no automatic replacement of V3.
