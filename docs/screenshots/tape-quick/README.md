# Tape Part 2: Quick and Momentum

Actual dashboard at 390 × 844 in Dark and Light, using `STOCKWATCH_DEMO=1`, an isolated fixture database and invented FICT symbols. Provider calls were blocked in the preview; no live tracker, AI or real-money action ran. The chosen Direction A Quick sample and the Momentum sample were opened in Chromium before comparing the output. The runtime blocks Google Fonts, so captures use the system sans fallback specified by Part 1.

Quick's big number uses the existing `quick.day_result` components: closed results for the New York day plus open-position result. Missing required outcomes/prices make that total unknown; the displayed win share excludes unmeasured results and counts measured flat returns as not won. Row dates/times use Riyadh; the market day is labelled NY. Sell-by-hand keeps its existing callbacks and confirmation/cancel flow; browser tests opened then cancelled the confirmation without selling.

The two displayed SVGs use explicit handmade `[timestamp, price]` paths in the test inputs. The third trade has no path and renders no SVG. Production Quick currently saves no trade path, so current real trades intentionally render without a chart. No highs/lows or synthetic trajectories are inferred from a trade's entry/exit alone. Dots use actual saved event timestamps and levels; unavailable/out-of-window dots are omitted.

The pullback pill uses the saved `pull_lo`: **Waiting for a dip** until a valid low is recorded, then **Dipped, waiting for the turn**. Recording a low does not claim a confirmed turn; no extra state field is required. The existing gate and entry timing are untouched. No new-high, resistance, or other chart explanation is invented for Momentum: its sentence uses the saved RSI/MACD changes, missed test or fading tag.

The old RSI/MACD/price/direction numbers remain available under Measurements. Missing values show unknown. Main rows show the move and volume relative to normal activity at this time of day. All 14 supported routes were checked for horizontal overflow and app exceptions in both themes; the two changed pages additionally passed manual-sale Cancel, disclosure and watch-expander checks. Part 3 and the shared New call/Portfolio layouts are untouched.

| Screen | Dark | Light |
|---|---|---|
| Quick | [Screenshot](quick-dark.png) | [Screenshot](quick-light.png) |
| Momentum | [Screenshot](momentum-dark.png) | [Screenshot](momentum-light.png) |
| Radar | [Screenshot](radar-dark.png) | [Screenshot](radar-light.png) |
| Portfolio | [Screenshot](portfolio-dark.png) | [Screenshot](portfolio-light.png) |
| More | [Screenshot](more-dark.png) | [Screenshot](more-light.png) |
| Details | [Screenshot](target-dark.png) | [Screenshot](target-light.png) |
| S&P 500 | [Screenshot](market-dark.png) | [Screenshot](market-light.png) |
| Ask the AI | [Screenshot](ai-dark.png) | [Screenshot](ai-light.png) |
| Extended | [Screenshot](ext-dark.png) | [Screenshot](ext-light.png) |
| Paper | [Screenshot](paper-dark.png) | [Screenshot](paper-light.png) |
| Log | [Screenshot](log-dark.png) | [Screenshot](log-light.png) |
| Fleet (legacy) | [Screenshot](fleet-dark.png) | [Screenshot](fleet-light.png) |
| Research (legacy) | [Screenshot](research-dark.png) | [Screenshot](research-light.png) |
| Test list (legacy) | [Screenshot](tests-dark.png) | [Screenshot](tests-light.png) |

Quick at the bottom: [dark](quick-bottom-dark.png), [light](quick-bottom-light.png). Momentum with disclosures expanded: [dark](momentum-expanded-dark.png), [light](momentum-expanded-light.png).

Validation: focused rendering/Quick/manual-sale/Momentum tests **61 passed**; Pyflakes and diff checks clean. Full unfiltered pytest: **1237 passed, 35 skipped, 2 known failures** (CIS temporary-path guard under the sandbox's `/tmp/.git`, and the pre-existing date-dependent Massive fallback test). Neither safety guard nor unrelated test changed; skips require private CIS fixtures.
