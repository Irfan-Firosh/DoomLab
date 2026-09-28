# Per-seed results (test split)

Each row is one episode; its id names the trace inside `traces/eval-test.tar.gz`.

## basic (tics to kill)

| Seed | Agent | Outcome | Score | LLM calls | Rejected | Episode id |
|---|---|---|---|---|---|---|
| 1000 | random | success | 43 | 0 | 0 | `basic-s1000-random` |
| 1000 | scripted | success | 43 | 0 | 0 | `basic-s1000-scripted` |
| 1000 | react_single | success | 43 | 2 | 0 | `basic-s1000-react_single` |
| 1000 | commander | success | 43 | 2 | 0 | `basic-s1000-commander` |
| 1001 | random | timeout | 300 | 0 | 3 | `basic-s1001-random` |
| 1001 | scripted | success | 40 | 0 | 0 | `basic-s1001-scripted` |
| 1001 | react_single | success | 40 | 2 | 0 | `basic-s1001-react_single` |
| 1001 | commander | success | 40 | 2 | 0 | `basic-s1001-commander` |
| 1002 | random | success | 69 | 0 | 3 | `basic-s1002-random` |
| 1002 | scripted | success | 69 | 0 | 0 | `basic-s1002-scripted` |
| 1002 | react_single | success | 69 | 2 | 0 | `basic-s1002-react_single` |
| 1002 | commander | success | 69 | 2 | 0 | `basic-s1002-commander` |
| 1003 | random | success | 57 | 0 | 0 | `basic-s1003-random` |
| 1003 | scripted | success | 57 | 0 | 0 | `basic-s1003-scripted` |
| 1003 | react_single | success | 57 | 2 | 0 | `basic-s1003-react_single` |
| 1003 | commander | success | 57 | 2 | 0 | `basic-s1003-commander` |
| 1004 | random | success | 59 | 0 | 0 | `basic-s1004-random` |
| 1004 | scripted | success | 59 | 0 | 0 | `basic-s1004-scripted` |
| 1004 | react_single | success | 59 | 2 | 0 | `basic-s1004-react_single` |
| 1004 | commander | success | 59 | 2 | 0 | `basic-s1004-commander` |
| 1005 | random | success | 67 | 0 | 0 | `basic-s1005-random` |
| 1005 | scripted | success | 67 | 0 | 0 | `basic-s1005-scripted` |
| 1005 | react_single | success | 67 | 2 | 0 | `basic-s1005-react_single` |
| 1005 | commander | success | 67 | 2 | 0 | `basic-s1005-commander` |
| 1006 | random | success | 70 | 0 | 1 | `basic-s1006-random` |
| 1006 | scripted | success | 70 | 0 | 0 | `basic-s1006-scripted` |
| 1006 | react_single | success | 70 | 2 | 0 | `basic-s1006-react_single` |
| 1006 | commander | success | 70 | 2 | 0 | `basic-s1006-commander` |
| 1007 | random | success | 48 | 0 | 1 | `basic-s1007-random` |
| 1007 | scripted | success | 48 | 0 | 0 | `basic-s1007-scripted` |
| 1007 | react_single | success | 48 | 2 | 0 | `basic-s1007-react_single` |
| 1007 | commander | success | 48 | 2 | 0 | `basic-s1007-commander` |
| 1008 | random | success | 45 | 0 | 1 | `basic-s1008-random` |
| 1008 | scripted | success | 45 | 0 | 0 | `basic-s1008-scripted` |
| 1008 | react_single | success | 45 | 2 | 0 | `basic-s1008-react_single` |
| 1008 | commander | success | 45 | 2 | 0 | `basic-s1008-commander` |
| 1009 | random | success | 62 | 0 | 1 | `basic-s1009-random` |
| 1009 | scripted | success | 62 | 0 | 0 | `basic-s1009-scripted` |
| 1009 | react_single | success | 62 | 2 | 0 | `basic-s1009-react_single` |
| 1009 | commander | success | 62 | 2 | 0 | `basic-s1009-commander` |

## defend_the_center (tics survived)

| Seed | Agent | Outcome | Score | LLM calls | Rejected | Episode id |
|---|---|---|---|---|---|---|
| 1000 | random | died | 334 | 0 | 0 | `defend_the_center-s1000-random` |
| 1000 | scripted | died | 1,329 | 0 | 0 | `defend_the_center-s1000-scripted` |
| 1000 | react_single | died | 1,526 | 148 | 8 | `defend_the_center-s1000-react_single` |
| 1000 | commander | died | 1,413 | 150 | 7 | `defend_the_center-s1000-commander` |
| 1001 | random | died | 298 | 0 | 2 | `defend_the_center-s1001-random` |
| 1001 | scripted | died | 1,356 | 0 | 0 | `defend_the_center-s1001-scripted` |
| 1001 | react_single | died | 555 | 39 | 3 | `defend_the_center-s1001-react_single` |
| 1001 | commander | died | 1,078 | 150 | 10 | `defend_the_center-s1001-commander` |
| 1002 | random | died | 358 | 0 | 4 | `defend_the_center-s1002-random` |
| 1002 | scripted | died | 839 | 0 | 0 | `defend_the_center-s1002-scripted` |
| 1002 | react_single | died | 1,494 | 150 | 13 | `defend_the_center-s1002-react_single` |
| 1002 | commander | died | 839 | 143 | 5 | `defend_the_center-s1002-commander` |
| 1003 | random | died | 218 | 0 | 6 | `defend_the_center-s1003-random` |
| 1003 | scripted | died | 1,089 | 0 | 0 | `defend_the_center-s1003-scripted` |
| 1003 | react_single | died | 957 | 150 | 15 | `defend_the_center-s1003-react_single` |
| 1003 | commander | died | 767 | 150 | 4 | `defend_the_center-s1003-commander` |
| 1004 | random | died | 299 | 0 | 3 | `defend_the_center-s1004-random` |
| 1004 | scripted | died | 1,332 | 0 | 0 | `defend_the_center-s1004-scripted` |
| 1004 | react_single | died | 597 | 72 | 9 | `defend_the_center-s1004-react_single` |
| 1004 | commander | died | 1,186 | 150 | 3 | `defend_the_center-s1004-commander` |
| 1005 | random | died | 262 | 0 | 4 | `defend_the_center-s1005-random` |
| 1005 | scripted | died | 1,362 | 0 | 0 | `defend_the_center-s1005-scripted` |
| 1005 | react_single | died | 1,235 | 138 | 7 | `defend_the_center-s1005-react_single` |
| 1005 | commander | died | 1,378 | 150 | 8 | `defend_the_center-s1005-commander` |
| 1006 | random | died | 242 | 0 | 4 | `defend_the_center-s1006-random` |
| 1006 | scripted | died | 1,267 | 0 | 0 | `defend_the_center-s1006-scripted` |
| 1006 | react_single | died | 744 | 59 | 5 | `defend_the_center-s1006-react_single` |
| 1006 | commander | died | 966 | 101 | 2 | `defend_the_center-s1006-commander` |
| 1007 | random | died | 290 | 0 | 6 | `defend_the_center-s1007-random` |
| 1007 | scripted | died | 1,452 | 0 | 0 | `defend_the_center-s1007-scripted` |
| 1007 | react_single | died | 1,282 | 112 | 10 | `defend_the_center-s1007-react_single` |
| 1007 | commander | died | 1,082 | 133 | 7 | `defend_the_center-s1007-commander` |
| 1008 | random | died | 328 | 0 | 10 | `defend_the_center-s1008-random` |
| 1008 | scripted | died | 1,252 | 0 | 0 | `defend_the_center-s1008-scripted` |
| 1008 | react_single | died | 1,259 | 150 | 8 | `defend_the_center-s1008-react_single` |
| 1008 | commander | died | 1,162 | 150 | 5 | `defend_the_center-s1008-commander` |
| 1009 | random | died | 677 | 0 | 9 | `defend_the_center-s1009-random` |
| 1009 | scripted | died | 1,354 | 0 | 0 | `defend_the_center-s1009-scripted` |
| 1009 | react_single | died | 1,049 | 150 | 13 | `defend_the_center-s1009-react_single` |
| 1009 | commander | died | 1,002 | 150 | 6 | `defend_the_center-s1009-commander` |

## health_gathering_supreme (tics survived)

| Seed | Agent | Outcome | Score | LLM calls | Rejected | Episode id |
|---|---|---|---|---|---|---|
| 1000 | random | died | 416 | 0 | 2 | `health_gathering_supreme-s1000-random` |
| 1000 | scripted | died | 704 | 0 | 0 | `health_gathering_supreme-s1000-scripted` |
| 1000 | react_single | died | 815 | 23 | 0 | `health_gathering_supreme-s1000-react_single` |
| 1000 | commander | died | 512 | 17 | 0 | `health_gathering_supreme-s1000-commander` |
| 1001 | random | died | 544 | 0 | 3 | `health_gathering_supreme-s1001-random` |
| 1001 | scripted | died | 1,856 | 0 | 0 | `health_gathering_supreme-s1001-scripted` |
| 1001 | react_single | died | 1,056 | 48 | 2 | `health_gathering_supreme-s1001-react_single` |
| 1001 | commander | died | 778 | 26 | 1 | `health_gathering_supreme-s1001-commander` |
| 1002 | random | died | 608 | 0 | 6 | `health_gathering_supreme-s1002-random` |
| 1002 | scripted | died | 2,048 | 0 | 0 | `health_gathering_supreme-s1002-scripted` |
| 1002 | react_single | died | 1,056 | 38 | 1 | `health_gathering_supreme-s1002-react_single` |
| 1002 | commander | died | 788 | 32 | 2 | `health_gathering_supreme-s1002-commander` |
| 1003 | random | died | 539 | 0 | 3 | `health_gathering_supreme-s1003-random` |
| 1003 | scripted | died | 384 | 0 | 0 | `health_gathering_supreme-s1003-scripted` |
| 1003 | react_single | died | 1,266 | 33 | 0 | `health_gathering_supreme-s1003-react_single` |
| 1003 | commander | died | 398 | 18 | 1 | `health_gathering_supreme-s1003-commander` |
| 1004 | random | died | 288 | 0 | 1 | `health_gathering_supreme-s1004-random` |
| 1004 | scripted | died | 1,502 | 0 | 0 | `health_gathering_supreme-s1004-scripted` |
| 1004 | react_single | died | 1,223 | 36 | 0 | `health_gathering_supreme-s1004-react_single` |
| 1004 | commander | died | 1,909 | 59 | 0 | `health_gathering_supreme-s1004-commander` |
| 1005 | random | died | 1,696 | 0 | 9 | `health_gathering_supreme-s1005-random` |
| 1005 | scripted | died | 1,638 | 0 | 0 | `health_gathering_supreme-s1005-scripted` |
| 1005 | react_single | success | 2,100 | 80 | 3 | `health_gathering_supreme-s1005-react_single` |
| 1005 | commander | died | 1,120 | 36 | 0 | `health_gathering_supreme-s1005-commander` |
| 1006 | random | died | 992 | 0 | 3 | `health_gathering_supreme-s1006-random` |
| 1006 | scripted | success | 2,100 | 0 | 0 | `health_gathering_supreme-s1006-scripted` |
| 1006 | react_single | success | 2,100 | 77 | 6 | `health_gathering_supreme-s1006-react_single` |
| 1006 | commander | died | 1,312 | 60 | 1 | `health_gathering_supreme-s1006-commander` |
| 1007 | random | died | 544 | 0 | 8 | `health_gathering_supreme-s1007-random` |
| 1007 | scripted | died | 1,376 | 0 | 0 | `health_gathering_supreme-s1007-scripted` |
| 1007 | react_single | died | 1,410 | 54 | 1 | `health_gathering_supreme-s1007-react_single` |
| 1007 | commander | died | 938 | 43 | 0 | `health_gathering_supreme-s1007-commander` |
| 1008 | random | died | 448 | 0 | 3 | `health_gathering_supreme-s1008-random` |
| 1008 | scripted | died | 1,534 | 0 | 0 | `health_gathering_supreme-s1008-scripted` |
| 1008 | react_single | died | 736 | 29 | 1 | `health_gathering_supreme-s1008-react_single` |
| 1008 | commander | success | 2,100 | 80 | 1 | `health_gathering_supreme-s1008-commander` |
| 1009 | random | died | 666 | 0 | 6 | `health_gathering_supreme-s1009-random` |
| 1009 | scripted | success | 2,100 | 0 | 0 | `health_gathering_supreme-s1009-scripted` |
| 1009 | react_single | died | 2,016 | 66 | 0 | `health_gathering_supreme-s1009-react_single` |
| 1009 | commander | died | 1,856 | 80 | 3 | `health_gathering_supreme-s1009-commander` |
