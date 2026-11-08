# Tape Part 1: phone checks

Actual `dashboard.py` at 390 × 844, using `STOCKWATCH_DEMO=1`, an isolated test database and invented FICT symbols only. Optional external providers were disabled in the preview process, and the live tracker was stopped. These are synthetic fixture values, not holdings or live market observations.

The Direction A reference was opened in the browser from all three supplied HTML samples. This part changes tokens, typography and navigation only; the screen layouts remain for Parts 2 and 3. Google Fonts was unavailable under the test runtime's network policy, so these captures exercise the specified system sans fallback. The only production font import is Familjen Grotesk from Google Fonts.

Verified all 14 existing/new routes in both themes: no horizontal overflow, JavaScript runtime errors or Streamlit exceptions; five fixed bottom destinations; 104px content clearance plus safe-area inset; More's Sweep button remains above the bar at the end of the page. `?view=target&t=FICTB` selected FICTB. Native picker background and text use the tokens in both themes. Theme selection updates the address and saved choice; clicking Quick then reloading preserves both. Auto follows emulated light/dark device preferences. All text/gain/loss token combinations pass 4.5:1 on background, raised and card surfaces.

| Screen | Dark | Light |
|---|---|---|
| Radar | [Screenshot](radar-dark.png) | [Screenshot](radar-light.png) |
| Portfolio | [Screenshot](portfolio-dark.png) | [Screenshot](portfolio-light.png) |
| Quick | [Screenshot](quick-dark.png) | [Screenshot](quick-light.png) |
| Momentum | [Screenshot](rising-dark.png) | [Screenshot](rising-light.png) |
| More | [Screenshot](more-dark.png) | [Screenshot](more-light.png) |
| Details | [Screenshot](target-dark.png) | [Screenshot](target-light.png) |
| S&P 500 | [Screenshot](market-dark.png) | [Screenshot](market-light.png) |
| Ask the AI | [Screenshot](ai-dark.png) | [Screenshot](ai-light.png) |
| Extended | [Screenshot](ext-dark.png) | [Screenshot](ext-light.png) |
| Paper | [Screenshot](paper-dark.png) | [Screenshot](paper-light.png) |
| Log | [Screenshot](log-dark.png) | [Screenshot](log-light.png) |
| Fleet (legacy route) | [Screenshot](fleet-dark.png) | [Screenshot](fleet-light.png) |
| Research (legacy route) | [Screenshot](research-dark.png) | [Screenshot](research-light.png) |
| Test list (legacy route) | [Screenshot](tests-dark.png) | [Screenshot](tests-light.png) |

More at the end of the page: [dark](more-bottom-dark.png), [light](more-bottom-light.png).

Full unfiltered pytest: **1216 passed, 35 skipped, 2 known failures**. The failures are the CIS outside-checkout temporary-path guard (the sandbox mounts `/tmp/.git`) and the pre-existing date-dependent Massive fallback test, already noted in PR #75. Safety guard and tests unchanged. The skips require the private CIS reference data. Focused design/navigation tests: **20 passed**. Pyflakes and diff checks clean.
