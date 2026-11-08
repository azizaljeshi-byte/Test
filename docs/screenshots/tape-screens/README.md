# Tape Part 3 phone checks

Captured at 390 × 844 in Chromium, dark and light, using the actual dashboard with `STOCKWATCH_DEMO=1` and an isolated offline harness. All tickers and positions shown are invented fixtures. Network calls, live tracking and AI calls were disabled. Google Fonts was blocked in this runtime, so the configured system sans fallback is shown.

| Screen | Dark | Light |
| --- | --- | --- |
| Radar | [Image](radar-dark.png) | [Image](radar-light.png) |
| Portfolio | [Image](portfolio-dark.png) | [Image](portfolio-light.png) |
| Details | [Image](target-dark.png) | [Image](target-light.png) |
| Details ladder and tables | [Image](details-levels-dark.png) | [Image](details-levels-light.png) |
| Five-level ladder fixture | [Image](five-levels-dark.png) | [Image](five-levels-light.png) |
| S&P 500 | [Image](market-dark.png) | [Image](market-light.png) |
| Ask the AI | [Image](ai-dark.png) | [Image](ai-light.png) |
| Extended | [Image](ext-dark.png) | [Image](ext-light.png) |
| Paper | [Image](paper-dark.png) | [Image](paper-light.png) |
| Log | [Image](log-dark.png) | [Image](log-light.png) |
| More | [Image](more-dark.png) | [Image](more-light.png) |
| Quick | [Image](quick-dark.png) | [Image](quick-light.png) |
| Momentum | [Image](rising-dark.png) | [Image](rising-light.png) |
| Fleet | [Image](fleet-dark.png) | [Image](fleet-light.png) |
| Research | [Image](research-dark.png) | [Image](research-light.png) |
| Tests | [Image](tests-dark.png) | [Image](tests-light.png) |

All 14 routes passed dark/light checks for horizontal overflow, Streamlit exceptions and browser errors. Details deep linking selected the requested invented ticker; the account controls remained available inside the disclosure. Radar search, current-call disclosures and Portfolio position disclosures were exercised. Radar retains holdings-first ordering. The design samples were opened at phone width for comparison.

The demo Details screenshot has only two usable levels; absent levels are not fabricated. The separate five-level synthetic fixture shows the complete ladder. Data dots follow the actual proportional price scale; labels have separate ordered slots connected by leader lines. Agreement dots use the saved denominator rather than assuming five checks. Existing disagreement, incomplete-data and broker-stop warnings remain visible.

Validation: 105 focused tests passed. Full suite: 1,250 passed, 35 skipped, two existing failures (`test_watchlist_cli_writes_owner_only_files_outside_git_and_refuses_unsafe_paths`, sandbox `/tmp/.git` mount; `test_price_check_prefers_massive_and_falls_back_to_stooq`, date-sensitive source fallback). Pyflakes and `git diff --check` passed. No scoring, trading or alert rules changed.
