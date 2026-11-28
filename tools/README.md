# OPOS GPU Link pacing check

Run from this checkout with Python 3.11+:

```sh
python3 -B tools/gpu-link-soak.py --duration 30 --gap 2 --cooldown 8 --cooldown-every 2
python3 -B -m unittest discover -s tools -p 'test_*.py' -v
```

All times are seconds. The default simulated run lasts 300 seconds. After each four-lane question it waits 30 seconds, except every second question takes a 120-second cool-down instead of that 30-second gap (the two pauses are not added together). A question uses the phone service's `POST /api/ai` ask shape (`gpu`, `g1`, `g2`, `g3`) against an in-process stand-in. Each fake lane ends immediately as `Done`; this is a pacing check, not an inference, memory, or temperature measurement. It opens no socket or device connection and uses no companion.

The 26 Nov 2026 live Flip soak stopped at 17 of 30 minutes at Thermal Status 4 (SKIN 47.1 °C). Two four-lane rounds finished with no failures or restarts and flat memory. A full live soak remains for Louis, starting with a cool phone and using cool-down gaps. Running that live soak is outside this PR.
