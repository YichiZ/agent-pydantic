# Full benchmark runs

Runs of the browser agent on many tasks of BU Bench V2.1 (200 tasks, `bu2-001` to `bu2-200`). Only scores and
numbers are recorded here: no task text, no rubric items, no judge evidence. The per-task lines with the judge's
evidence stay in `../.reports/` (gitignored, local only).

## 2026-11-27: gpt-6.1-terra on the Codex subscription, all 200 tasks

**Mean score 0.38** over 200 tasks (median 0.32), one trial each, every task run and judged. Agent run time
11,115 s in all (mean 56 s per task). Agent cost **$7.12 notional**, not spent: the run was on the Codex
subscription. Judge cost $4.42, spent on the OpenAI API key.

### Parameters

As in the pilot section below, except:

| | |
|---|---|
| Repo commit | `2aefd79` for tasks 1 to 20, `bff31db` for tasks 21 to 200 (docs-only difference) |
| Command | `uv run --env-file .env python -m agents.browser.evals.run --model 6.1-terra-codex --tasks 21-200 --concurrency 5 --save agents/browser/evals/.reports/2026-11-27-terra-full.jsonl`, then the same with `--tasks all` to resume |
| When | Tasks 1 to 20: see the pilot. Tasks 21 to 200: 07:21:54 to 08:32:58 UTC, wall time 4,261 s. Resume: 11:52:01 to 12:08:25 UTC, wall time 982 s. |
| Wall time | 6,303 s over the four invocations, about 1 h 45 min, not counting the wait for the limit to reset |

### The usage limit

The 21-to-200 invocation judged 140 tasks and failed 40. Of the failures, 39 were the subscription's 5-hour usage
limit (HTTP 429 `usage_limit_reached`, plan `plus`, 300-minute window), first hit at about 08:29 UTC on `bu2-161`,
and 1 was a server-overloaded error (HTTP 503) on `bu2-146`. Failed tasks are not saved, so the resume after the
11:49 UTC reset ran exactly those 40, and all 40 were judged. No task ran on the API-key entry.

The window was at 100% after about 160 tasks ($5.86 of notional agent cost); how full it was before the first task
is not known. The weekly window stood at 16% at that point.

### Results by block of 20 tasks

Agent cost is **notional**: the API price of the tokens used. Judge cost was spent.

| Tasks | Mean score | Agent run time | Model requests | Agent cost (notional) | Judge cost |
|---|---|---|---|---|---|
| 1 to 20 | 0.43 | 1,563 s | 252 | $0.97 | $0.56 |
| 21 to 40 | 0.35 | 1,668 s | 274 | $0.96 | $0.55 |
| 41 to 60 | 0.36 | 1,642 s | 258 | $0.86 | $0.57 |
| 61 to 80 | 0.38 | 890 s | 153 | $0.49 | $0.34 |
| 81 to 100 | 0.32 | 873 s | 173 | $0.56 | $0.47 |
| 101 to 120 | 0.42 | 931 s | 198 | $0.58 | $0.36 |
| 121 to 140 | 0.37 | 921 s | 214 | $0.67 | $0.42 |
| 141 to 160 | 0.43 | 830 s | 233 | $0.69 | $0.30 |
| 161 to 180 | 0.41 | 1,163 s | 287 | $0.91 | $0.50 |
| 181 to 200 | 0.36 | 633 s | 177 | $0.43 | $0.34 |
| **Mean per task** | **0.38** | 56 s | 11.1 | $0.036 | $0.022 |
| **Total** | | 11,115 s | 2,219 | $7.12 | $4.42 |

Of 1,873 rubric items, 795 were met (42%). Seven tasks scored 0, 65 scored below 0.2, 19 scored 0.8 or more and
6 scored 1.0.

### What the run showed

- **The runs were short.** 2 to 44 model requests per task, and no task came near the 200-request or 3600-s limit:
  the longest agent run was 278 s.
- **Half the tasks stopped within 8 model requests**, and they scored about half as much: mean 0.27 for those 100,
  against 0.49 for the 100 that went on longer.
- **Sites blocked the browser in about half the tasks.** A keyword match on the judge's evidence (CAPTCHA, bot
  check, access denied, blocked and similar) flags 109 of 200 tasks. Their mean score is 0.36, against 0.41 for
  the other 91. Of the 100 early stops, 64 are flagged. The match is approximate: on tasks 1 to 20 it agrees with
  the hand count in the pilot on 12 of 13 tasks.
- **One trial per task.** There is no measure of run-to-run variation, and no solo run to show whether 5 browsers
  from one IP made the blocking worse.
- **Against the projection** in the pilot: judge cost $3.86 for the 180 tasks against about $5 projected, notional
  agent cost $6.15 against about $9, wall time 1.5 hours against 2.5 to 3.5.

### Per-task results, tasks 21 to 200

Tasks 1 to 20 are in the pilot table below.

| Task | Score | Agent run time | Model requests | Agent cost (notional) | Judge cost |
|---|---|---|---|---|---|
| `bu2-021` | 0.34 | 124 s | 22 | $0.074 | $0.032 |
| `bu2-022` | 0.36 | 134 s | 18 | $0.075 | $0.032 |
| `bu2-023` | 0.26 | 37 s | 3 | $0.008 | $0.016 |
| `bu2-024` | 0.52 | 221 s | 35 | $0.131 | $0.076 |
| `bu2-025` | 0.08 | 57 s | 5 | $0.010 | $0.008 |
| `bu2-026` | 0.37 | 43 s | 10 | $0.018 | $0.013 |
| `bu2-027` | 0.17 | 16 s | 3 | $0.009 | $0.018 |
| `bu2-028` | 0.78 | 97 s | 17 | $0.067 | $0.043 |
| `bu2-029` | 0.26 | 101 s | 14 | $0.049 | $0.025 |
| `bu2-030` | 0.17 | 58 s | 12 | $0.037 | $0.020 |
| `bu2-031` | 0.75 | 56 s | 11 | $0.048 | $0.031 |
| `bu2-032` | 0.30 | 52 s | 16 | $0.047 | $0.034 |
| `bu2-033` | 0.78 | 121 s | 18 | $0.073 | $0.047 |
| `bu2-034` | 0.44 | 215 s | 23 | $0.083 | $0.048 |
| `bu2-035` | 0.30 | 86 s | 14 | $0.051 | $0.035 |
| `bu2-036` | 0.14 | 26 s | 5 | $0.012 | $0.009 |
| `bu2-037` | 0.42 | 91 s | 23 | $0.097 | $0.034 |
| `bu2-038` | 0.26 | 17 s | 3 | $0.009 | $0.005 |
| `bu2-039` | 0.23 | 57 s | 9 | $0.036 | $0.025 |
| `bu2-040` | 0.10 | 58 s | 13 | $0.025 | $0.005 |
| `bu2-041` | 0.18 | 20 s | 5 | $0.007 | $0.026 |
| `bu2-042` | 0.86 | 63 s | 13 | $0.056 | $0.021 |
| `bu2-043` | 0.94 | 73 s | 16 | $0.035 | $0.036 |
| `bu2-044` | 0.00 | 27 s | 9 | $0.019 | $0.005 |
| `bu2-045` | 0.59 | 108 s | 19 | $0.046 | $0.024 |
| `bu2-046` | 0.38 | 45 s | 11 | $0.024 | $0.031 |
| `bu2-047` | 0.00 | 31 s | 10 | $0.019 | $0.006 |
| `bu2-048` | 0.46 | 194 s | 12 | $0.053 | $0.053 |
| `bu2-049` | 0.04 | 155 s | 15 | $0.039 | $0.032 |
| `bu2-050` | 0.60 | 149 s | 23 | $0.127 | $0.050 |
| `bu2-051` | 0.28 | 14 s | 3 | $0.011 | $0.015 |
| `bu2-052` | 0.74 | 173 s | 15 | $0.042 | $0.044 |
| `bu2-053` | 0.10 | 50 s | 7 | $0.038 | $0.032 |
| `bu2-054` | 0.52 | 181 s | 22 | $0.103 | $0.044 |
| `bu2-055` | 0.20 | 56 s | 8 | $0.039 | $0.018 |
| `bu2-056` | 0.18 | 10 s | 4 | $0.006 | $0.014 |
| `bu2-057` | 0.26 | 37 s | 11 | $0.024 | $0.020 |
| `bu2-058` | 0.26 | 82 s | 29 | $0.074 | $0.035 |
| `bu2-059` | 0.10 | 29 s | 10 | $0.014 | $0.008 |
| `bu2-060` | 0.52 | 145 s | 16 | $0.077 | $0.057 |
| `bu2-061` | 0.14 | 157 s | 4 | $0.006 | $0.005 |
| `bu2-062` | 0.87 | 65 s | 18 | $0.046 | $0.031 |
| `bu2-063` | 0.07 | 19 s | 6 | $0.016 | $0.007 |
| `bu2-064` | 0.68 | 85 s | 26 | $0.096 | $0.029 |
| `bu2-065` | 0.34 | 70 s | 5 | $0.035 | $0.054 |
| `bu2-066` | 0.12 | 8 s | 2 | $0.008 | $0.012 |
| `bu2-067` | 0.12 | 48 s | 14 | $0.038 | $0.017 |
| `bu2-068` | 0.90 | 28 s | 5 | $0.014 | $0.011 |
| `bu2-069` | 0.16 | 31 s | 7 | $0.018 | $0.006 |
| `bu2-070` | 0.32 | 36 s | 8 | $0.018 | $0.020 |
| `bu2-071` | 0.64 | 31 s | 2 | $0.015 | $0.020 |
| `bu2-072` | 0.70 | 74 s | 12 | $0.058 | $0.029 |
| `bu2-073` | 0.38 | 64 s | 9 | $0.029 | $0.018 |
| `bu2-074` | 0.09 | 18 s | 3 | $0.007 | $0.009 |
| `bu2-075` | 1.00 | 58 s | 13 | $0.036 | $0.012 |
| `bu2-076` | 0.06 | 29 s | 6 | $0.019 | $0.011 |
| `bu2-077` | 0.00 | 6 s | 2 | $0.002 | $0.013 |
| `bu2-078` | 0.08 | 32 s | 4 | $0.010 | $0.005 |
| `bu2-079` | 0.56 | 22 s | 5 | $0.018 | $0.024 |
| `bu2-080` | 0.39 | 7 s | 2 | $0.004 | $0.007 |
| `bu2-081` | 0.57 | 63 s | 7 | $0.060 | $0.031 |
| `bu2-082` | 0.22 | 18 s | 6 | $0.008 | $0.022 |
| `bu2-083` | 1.00 | 69 s | 6 | $0.035 | $0.028 |
| `bu2-084` | 0.12 | 16 s | 4 | $0.008 | $0.027 |
| `bu2-085` | 0.08 | 41 s | 7 | $0.037 | $0.011 |
| `bu2-086` | 0.00 | 10 s | 3 | $0.006 | $0.017 |
| `bu2-087` | 0.71 | 25 s | 8 | $0.016 | $0.019 |
| `bu2-088` | 0.14 | 56 s | 15 | $0.022 | $0.009 |
| `bu2-089` | 0.38 | 14 s | 5 | $0.012 | $0.005 |
| `bu2-090` | 0.54 | 25 s | 6 | $0.019 | $0.050 |
| `bu2-091` | 0.42 | 76 s | 4 | $0.027 | $0.042 |
| `bu2-092` | 0.19 | 9 s | 2 | $0.007 | $0.009 |
| `bu2-093` | 0.56 | 65 s | 20 | $0.041 | $0.043 |
| `bu2-094` | 0.30 | 14 s | 4 | $0.008 | $0.012 |
| `bu2-095` | 0.14 | 59 s | 16 | $0.061 | $0.021 |
| `bu2-096` | 0.48 | 44 s | 8 | $0.021 | $0.034 |
| `bu2-097` | 0.14 | 55 s | 7 | $0.023 | $0.020 |
| `bu2-098` | 0.05 | 49 s | 8 | $0.018 | $0.012 |
| `bu2-099` | 0.36 | 121 s | 29 | $0.106 | $0.043 |
| `bu2-100` | 0.08 | 43 s | 8 | $0.026 | $0.019 |
| `bu2-101` | 0.68 | 131 s | 15 | $0.069 | $0.053 |
| `bu2-102` | 0.51 | 31 s | 8 | $0.054 | $0.010 |
| `bu2-103` | 0.28 | 36 s | 12 | $0.040 | $0.016 |
| `bu2-104` | 0.16 | 36 s | 11 | $0.023 | $0.011 |
| `bu2-105` | 0.22 | 70 s | 16 | $0.039 | $0.026 |
| `bu2-106` | 0.35 | 17 s | 5 | $0.006 | $0.005 |
| `bu2-107` | 0.20 | 67 s | 11 | $0.036 | $0.026 |
| `bu2-108` | 0.47 | 39 s | 9 | $0.042 | $0.045 |
| `bu2-109` | 0.43 | 41 s | 14 | $0.033 | $0.009 |
| `bu2-110` | 0.38 | 41 s | 15 | $0.023 | $0.027 |
| `bu2-111` | 0.92 | 47 s | 9 | $0.024 | $0.013 |
| `bu2-112` | 0.74 | 63 s | 18 | $0.066 | $0.014 |
| `bu2-113` | 0.68 | 26 s | 8 | $0.036 | $0.019 |
| `bu2-114` | 0.08 | 18 s | 6 | $0.008 | $0.005 |
| `bu2-115` | 0.10 | 21 s | 6 | $0.023 | $0.008 |
| `bu2-116` | 0.18 | 48 s | 7 | $0.008 | $0.006 |
| `bu2-117` | 0.74 | 15 s | 5 | $0.006 | $0.015 |
| `bu2-118` | 0.28 | 36 s | 5 | $0.007 | $0.022 |
| `bu2-119` | 0.70 | 114 s | 11 | $0.023 | $0.010 |
| `bu2-120` | 0.24 | 32 s | 7 | $0.013 | $0.022 |
| `bu2-121` | 0.74 | 49 s | 8 | $0.040 | $0.023 |
| `bu2-122` | 0.26 | 55 s | 18 | $0.065 | $0.017 |
| `bu2-123` | 0.23 | 7 s | 2 | $0.006 | $0.007 |
| `bu2-124` | 0.09 | 14 s | 3 | $0.008 | $0.014 |
| `bu2-125` | 0.08 | 7 s | 3 | $0.003 | $0.005 |
| `bu2-126` | 0.24 | 79 s | 25 | $0.062 | $0.042 |
| `bu2-127` | 0.65 | 96 s | 11 | $0.061 | $0.049 |
| `bu2-128` | 0.10 | 25 s | 4 | $0.004 | $0.005 |
| `bu2-129` | 1.00 | 167 s | 34 | $0.122 | $0.040 |
| `bu2-130` | 0.60 | 12 s | 4 | $0.005 | $0.010 |
| `bu2-131` | 0.28 | 113 s | 18 | $0.064 | $0.036 |
| `bu2-132` | 0.14 | 20 s | 7 | $0.006 | $0.010 |
| `bu2-133` | 0.69 | 30 s | 10 | $0.042 | $0.019 |
| `bu2-134` | 0.36 | 43 s | 8 | $0.022 | $0.026 |
| `bu2-135` | 0.00 | 21 s | 8 | $0.027 | $0.015 |
| `bu2-136` | 0.66 | 74 s | 22 | $0.058 | $0.037 |
| `bu2-137` | 0.00 | 12 s | 5 | $0.005 | $0.006 |
| `bu2-138` | 0.68 | 48 s | 10 | $0.041 | $0.031 |
| `bu2-139` | 0.20 | 30 s | 7 | $0.019 | $0.013 |
| `bu2-140` | 0.38 | 20 s | 7 | $0.012 | $0.013 |
| `bu2-141` | 0.20 | 20 s | 8 | $0.016 | $0.010 |
| `bu2-142` | 0.20 | 7 s | 2 | $0.005 | $0.010 |
| `bu2-143` | 0.51 | 37 s | 6 | $0.026 | $0.019 |
| `bu2-144` | 1.00 | 141 s | 40 | $0.156 | $0.015 |
| `bu2-145` | 0.18 | 11 s | 3 | $0.009 | $0.006 |
| `bu2-146` | 0.60 | 18 s | 6 | $0.015 | $0.023 |
| `bu2-147` | 0.08 | 28 s | 8 | $0.021 | $0.006 |
| `bu2-148` | 0.29 | 15 s | 3 | $0.007 | $0.013 |
| `bu2-149` | 0.52 | 41 s | 12 | $0.025 | $0.020 |
| `bu2-150` | 0.10 | 19 s | 6 | $0.007 | $0.016 |
| `bu2-151` | 0.16 | 25 s | 4 | $0.017 | $0.021 |
| `bu2-152` | 1.00 | 81 s | 30 | $0.089 | $0.024 |
| `bu2-153` | 0.27 | 102 s | 23 | $0.056 | $0.021 |
| `bu2-154` | 0.62 | 95 s | 35 | $0.127 | $0.018 |
| `bu2-155` | 0.08 | 29 s | 4 | $0.004 | $0.008 |
| `bu2-156` | 0.96 | 27 s | 10 | $0.024 | $0.020 |
| `bu2-157` | 0.10 | 52 s | 14 | $0.017 | $0.005 |
| `bu2-158` | 0.48 | 14 s | 3 | $0.007 | $0.011 |
| `bu2-159` | 1.00 | 62 s | 13 | $0.061 | $0.025 |
| `bu2-160` | 0.26 | 8 s | 3 | $0.003 | $0.011 |
| `bu2-161` | 0.74 | 133 s | 31 | $0.130 | $0.044 |
| `bu2-162` | 0.34 | 118 s | 31 | $0.084 | $0.024 |
| `bu2-163` | 0.42 | 157 s | 21 | $0.096 | $0.034 |
| `bu2-164` | 0.25 | 46 s | 15 | $0.042 | $0.017 |
| `bu2-165` | 0.42 | 25 s | 7 | $0.013 | $0.020 |
| `bu2-166` | 0.30 | 16 s | 6 | $0.008 | $0.008 |
| `bu2-167` | 0.18 | 26 s | 7 | $0.013 | $0.016 |
| `bu2-168` | 0.42 | 35 s | 8 | $0.017 | $0.015 |
| `bu2-169` | 0.54 | 136 s | 32 | $0.115 | $0.074 |
| `bu2-170` | 0.85 | 79 s | 12 | $0.079 | $0.037 |
| `bu2-171` | 0.66 | 45 s | 14 | $0.053 | $0.025 |
| `bu2-172` | 0.72 | 25 s | 8 | $0.022 | $0.024 |
| `bu2-173` | 0.16 | 26 s | 9 | $0.031 | $0.014 |
| `bu2-174` | 0.16 | 20 s | 6 | $0.008 | $0.019 |
| `bu2-175` | 0.16 | 15 s | 4 | $0.008 | $0.009 |
| `bu2-176` | 0.52 | 10 s | 3 | $0.003 | $0.023 |
| `bu2-177` | 0.87 | 61 s | 17 | $0.056 | $0.027 |
| `bu2-178` | 0.20 | 32 s | 12 | $0.017 | $0.012 |
| `bu2-179` | 0.07 | 79 s | 24 | $0.081 | $0.038 |
| `bu2-180` | 0.23 | 78 s | 20 | $0.035 | $0.023 |
| `bu2-181` | 0.05 | 5 s | 2 | $0.008 | $0.007 |
| `bu2-182` | 0.08 | 23 s | 8 | $0.016 | $0.013 |
| `bu2-183` | 0.58 | 25 s | 5 | $0.014 | $0.019 |
| `bu2-184` | 0.12 | 22 s | 7 | $0.008 | $0.010 |
| `bu2-185` | 0.10 | 9 s | 3 | $0.008 | $0.004 |
| `bu2-186` | 0.95 | 75 s | 14 | $0.035 | $0.021 |
| `bu2-187` | 0.06 | 21 s | 5 | $0.015 | $0.014 |
| `bu2-188` | 0.32 | 27 s | 7 | $0.007 | $0.014 |
| `bu2-189` | 0.21 | 37 s | 9 | $0.017 | $0.033 |
| `bu2-190` | 0.36 | 49 s | 14 | $0.043 | $0.022 |
| `bu2-191` | 0.16 | 23 s | 8 | $0.010 | $0.008 |
| `bu2-192` | 0.06 | 31 s | 8 | $0.013 | $0.008 |
| `bu2-193` | 0.30 | 10 s | 3 | $0.010 | $0.015 |
| `bu2-194` | 0.64 | 46 s | 12 | $0.028 | $0.046 |
| `bu2-195` | 0.50 | 42 s | 5 | $0.024 | $0.021 |
| `bu2-196` | 0.92 | 75 s | 30 | $0.093 | $0.026 |
| `bu2-197` | 0.56 | 26 s | 10 | $0.035 | $0.020 |
| `bu2-198` | 0.09 | 20 s | 7 | $0.011 | $0.004 |
| `bu2-199` | 0.82 | 43 s | 9 | $0.010 | $0.018 |
| `bu2-200` | 0.22 | 25 s | 11 | $0.022 | $0.013 |

## 2026-11-27: gpt-6.1-terra on the Codex subscription, pilot on tasks 1 to 20

**Mean score 0.43** over 20 tasks, none failed: 0.29 on tasks 1 to 10 and 0.56 on tasks 11 to 20. This is a pilot
to test running tasks in parallel, not a benchmark result: 20 of 200 tasks, one trial each.

### Parameters

| | |
|---|---|
| Repo commit | `2aefd79` |
| Command | `uv run --env-file .env python -m agents.browser.evals.run --model 6.1-terra-codex --tasks 1-10 --concurrency 5 --save agents/browser/evals/.reports/2026-11-27-terra-full.jsonl`, then the same with `--tasks 11-20` |
| When | Tasks 1 to 10: 06:50:59 to 06:57:22 UTC, wall time 382 s. Tasks 11 to 20: 07:04:26 to 07:15:45 UTC, wall time 678 s. |
| Tasks | `bu2-001` to `bu2-020`, one trial each, 5 at a time |
| Agent | `agents/browser/agent.py`, unchanged: one Pydantic AI `Agent` with `PlaywrightBrowser()` at its defaults (local headless Chromium) |
| Agent model | `openai-codex:gpt-6.1-terra` (config entry `6.1-terra-codex`), default settings. It ran on a Codex/ChatGPT subscription through the Codex CLI login, not on the OpenAI API key. |
| Limits | 200 model requests and 3600 s per task |
| Versions | pydantic-ai 2.75.0, pydantic-ai-harness 0.75.0, pydantic-evals 2.75.0, playwright 1.65.2, Python 3.13.12 |
| Judge | The benchmark's own `judge_trace` at commit `77b4df3`: `gpt-5.6-luna`, reasoning effort `xhigh`, on the OpenAI API key |
| Machine | macOS (Darwin 25.5.0), run locally, one IP address |

### Results

Agent cost is **notional**: the API price of the tokens used. The run was on the subscription, so no money was
spent on the agent. Judge cost was spent.

| Task | Score | Agent run time | Model requests | Agent cost (notional) | Judge cost |
|---|---|---|---|---|---|
| `bu2-001` | 0.00 | 45 s | 8 | $0.038 | $0.016 |
| `bu2-002` | 0.48 | 37 s | 7 | $0.019 | $0.022 |
| `bu2-003` | 0.78 | 74 s | 12 | $0.031 | $0.023 |
| `bu2-004` | 0.32 | 80 s | 16 | $0.025 | $0.022 |
| `bu2-005` | 0.16 | 64 s | 11 | $0.023 | $0.038 |
| `bu2-006` | 0.12 | 19 s | 4 | $0.006 | $0.023 |
| `bu2-007` | 0.04 | 27 s | 8 | $0.017 | $0.012 |
| `bu2-008` | 0.12 | 66 s | 17 | $0.078 | $0.025 |
| `bu2-009` | 0.54 | 74 s | 7 | $0.035 | $0.032 |
| `bu2-010` | 0.32 | 21 s | 4 | $0.009 | $0.016 |
| `bu2-011` | 0.85 | 121 s | 9 | $0.070 | $0.046 |
| `bu2-012` | 0.32 | 61 s | 10 | $0.056 | $0.025 |
| `bu2-013` | 0.12 | 15 s | 3 | $0.010 | $0.005 |
| `bu2-014` | 0.56 | 94 s | 11 | $0.080 | $0.046 |
| `bu2-015` | 0.76 | 96 s | 15 | $0.057 | $0.037 |
| `bu2-016` | 0.50 | 114 s | 26 | $0.099 | $0.036 |
| `bu2-017` | 0.92 | 107 s | 17 | $0.062 | $0.035 |
| `bu2-018` | 0.55 | 101 s | 11 | $0.043 | $0.023 |
| `bu2-019` | 0.64 | 278 s | 44 | $0.158 | $0.041 |
| `bu2-020` | 0.41 | 71 s | 12 | $0.054 | $0.041 |
| **Mean, 1 to 10** | **0.29** | 51 s | 9.4 | $0.028 | $0.023 |
| **Mean, 11 to 20** | **0.56** | 106 s | 15.8 | $0.069 | $0.033 |
| **Mean, all 20** | **0.43** | 78 s | 12.6 | $0.049 | $0.028 |
| **Total, all 20** | | 1,563 s | 252 | $0.97 | $0.56 |

Per task the agent used about 98,000 input tokens on tasks 1 to 10 and 344,000 on tasks 11 to 20, most of them
read from cache, and 1,200 to 2,900 output tokens. The 20 tasks used about 4.4 million input tokens in all.

### What the runs showed

- **No failures and no limit errors.** All 20 tasks were run and judged. There was no rate-limit, quota, usage-limit
  or auth error from the Codex backend at 5 in parallel.
- **Sites blocked the browser.** In 13 of the 20 tasks the judge's evidence reports a bot check, a CAPTCHA or an
  access-denied page: `001`, `002`, `006`, `007`, `009`, `010`, `011`, `013`, `014`, `015`, `016`, `017`, `018`.
  Some blocks came from the task's target site, some from a search engine the agent tried on the way.
- **Seven runs stopped within 8 model requests** (`001`, `002`, `006`, `007`, `009`, `010`, `013`), and all seven
  are among the blocked ones. Their mean score is 0.23; the other thirteen average 0.53. Where only a search engine
  blocked, the agent usually carried on and scored higher.
- The runs cannot tell whether 5 browsers from one IP made the blocking worse: there is no solo run of these tasks
  to compare with.
- **The runs were short.** The agent made 3 to 44 model requests per task, against 45 to 65 on task `bu2-052`.
  Blocked pages explain part of it. Whether the model also behaves differently on the Codex backend than on the
  API was not tested.
- **Speed per request** was about 6.2 s (1,563 s over 252 requests), against about 4 s on the solo `bu2-052` runs.
  The tasks and pages differ, so this is weak evidence either way.
- **The judge takes much of the wall time.** On tasks 1 to 10 the agent's runs took at most 80 s, but two rounds of
  five tasks took 382 s, so a judge call is on the order of two minutes.

### Projection for the remaining 180 tasks

At 5 in parallel, from these 20 tasks: 53 s of wall time, $0.028 of judge cost, $0.049 of notional agent cost and
about 221,000 input tokens per task.

| | If tasks are like these 20 | If tasks are like `bu2-052` |
|---|---|---|
| Wall time | about 2.5 to 3.5 hours | about 3.5 hours |
| Judge cost (spent) | about $5 | about $8 |
| Agent cost (notional, not spent) | about $9 | about $34 |
| Agent input tokens | about 40 million | about 270 million |

The second column uses the measured `bu2-052` figures: $0.19 agent, $0.045 judge, about 220 s and 1.5 million
input tokens per task. The range in the first column is tasks 1 to 20 against tasks 11 to 20 alone, which ran
longer. These runs give no measure of the subscription's quota: 20 tasks used about 4.4 million input tokens
without a limit signal, which says little about 40 to 270 million.
