# Brief 3: "Institutions own 120%" display fix

**Problem.** Some tickers show institutional ownership above 100% (shares held reported by funds can exceed shares outstanding).
It looks like a bug on the owner's phone.

**Where.** `stockwatch/fundamentals_view.py` (line with `institution_pct`) and `stockwatch/briefing.py` (the note that says "institutions own N%").

**Change.** When the value is above 1.0, show "Institutions hold more than 100% of shares (funds report overlapping holdings)" in the
fundamentals note and "institutions: over 100% (overlap)" in the briefing note. Keep the plain percentage when it is 100% or less.
Missing value stays hidden. Don't change the stored value or any score that uses it (search for other uses of `institution_pct` and list them in the PR).

**Check.** Tests for 0.62, 1.0, 1.35 and None in both places. Methodology impact: None.
