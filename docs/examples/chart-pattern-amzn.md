# Chart Pattern Lab: AMZN historical fixture

As of 2018-02-07 — **INSUFFICIENT EVIDENCE**


Distances measure shape similarity; hit-first rates are observed frequencies, not success probabilities.

Source: {"url": "https://raw.githubusercontent.com/plotly/datasets/0c447c47b757ad74edecab31f0d72f849d2e67c2/all_stocks_5yr.csv", "sha256": "6aea253cd19de60b568143991aaf1fa482456565c389205658d236e595e716cf", "rows": 1259, "start": "2013-02-08", "end": "2018-02-07", "adjustment": "AMZN had no splits or dividends during 2013\u20132018. Historical prices preserved, not restated for 2022 split.", "excluded": "Other tickers excluded; no fabricated timestamps; no SPY supplied."}

## 20-bar formation

No calibrated tactical verdict: broad-market regime, execution risk and repeatable out-of-sample edge remain unverified.

| Horizon | Independent episodes | Median net return | Target first | Stop first | No hit | 95% Wilson interval |
|---|---|---|---|---|---|---|
| 5 | 3 | -0.013716425879876202 | 0.0 | 0.0 | 1.0 | [0.0, 0.5615060804490177] |
| 20 | 3 | 0.03131858609589777 | 0.0 | 0.3333333333333333 | 0.6666666666666666 | [0.0, 0.5615060804490177] |
| 60 | 3 | -0.04648398576512458 | 0.0 | 1.0 | 0.0 | [0.0, 0.5615060804490177] |

Frozen training end: 2016-08-08. Disjoint holdout evaluations: 0.
Holdout return prediction MAE (shape/regime/dip): {'shape': None, 'regime': None, 'dip': None}

| Formation start | Match end | Distance | Path / candles / volume | Volatility ratio |
|---|---|---|---|---|
| 2013-11-12 | 2013-12-10 | 0.483 | 0.246 / 1.192 / 0.251 | 0.99 |
| 2015-10-13 | 2015-11-09 | 0.499 | 0.258 / 1.219 / 0.264 | 1.22 |
| 2014-10-29 | 2014-11-25 | 0.585 | 0.395 / 1.223 / 0.279 | 1.14 |

Matched-regime and buy-the-dip baselines (same horizons and costs):
```json
{
  "regime": {
    "5": {
      "n": 3,
      "median_return": -0.05227932960893866,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.004029267810352399,
      "median_mae": -0.07063092417061623,
      "worst_drawdown": -0.08671844604233625
    },
    "20": {
      "n": 3,
      "median_return": -0.1373141840114699,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.004227023285707121,
      "median_mae": -0.1651505413556138,
      "worst_drawdown": -0.1783794688531205
    },
    "60": {
      "n": 3,
      "median_return": -0.13862618483412326,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.03145734597156391,
      "median_mae": -0.24482127848914825,
      "worst_drawdown": -0.30534461143853486
    }
  },
  "dip": {
    "5": {
      "n": 3,
      "median_return": -0.040926356764586,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.030975240020212125,
      "median_mae": -0.05322952971529438,
      "worst_drawdown": -0.08210729570442532
    },
    "20": {
      "n": 3,
      "median_return": -0.0948499222981638,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.030975240020212125,
      "median_mae": -0.1467155128852956,
      "worst_drawdown": -0.1783794688531205
    },
    "60": {
      "n": 3,
      "median_return": -0.1425573409375518,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.05077022888094285,
      "median_mae": -0.2180394138453765,
      "worst_drawdown": -0.30534461143853486
    }
  }
}
```

Sensitivity to distance cutoff (0.75× / 1× / 1.25×; never selected by outcomes):
```json
{
  "0.75": {
    "5": {
      "n": 3,
      "median_return": -0.013716425879876202,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.01856494746895887,
      "median_mae": -0.05064913270988125,
      "worst_drawdown": -0.06537916371367825
    },
    "20": {
      "n": 3,
      "median_return": 0.03131858609589777,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.3333333333333333,
      "no_hit_rate": 0.6666666666666666,
      "median_days_to_target": null,
      "median_mfe": 0.044745152481349804,
      "median_mae": -0.05064913270988125,
      "worst_drawdown": -0.12869123553035666
    },
    "60": {
      "n": 3,
      "median_return": -0.04648398576512458,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.06247234892980824,
      "median_mae": -0.14860912129894943,
      "worst_drawdown": -0.2764384627577562
    }
  },
  "1.0": {
    "5": {
      "n": 3,
      "median_return": -0.013716425879876202,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.01856494746895887,
      "median_mae": -0.05064913270988125,
      "worst_drawdown": -0.06537916371367825
    },
    "20": {
      "n": 3,
      "median_return": 0.03131858609589777,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.3333333333333333,
      "no_hit_rate": 0.6666666666666666,
      "median_days_to_target": null,
      "median_mfe": 0.044745152481349804,
      "median_mae": -0.05064913270988125,
      "worst_drawdown": -0.12869123553035666
    },
    "60": {
      "n": 3,
      "median_return": -0.04648398576512458,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.06247234892980824,
      "median_mae": -0.14860912129894943,
      "worst_drawdown": -0.2764384627577562
    }
  },
  "1.25": {
    "5": {
      "n": 3,
      "median_return": -0.013716425879876202,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.01856494746895887,
      "median_mae": -0.05064913270988125,
      "worst_drawdown": -0.06537916371367825
    },
    "20": {
      "n": 3,
      "median_return": 0.03131858609589777,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.3333333333333333,
      "no_hit_rate": 0.6666666666666666,
      "median_days_to_target": null,
      "median_mfe": 0.044745152481349804,
      "median_mae": -0.05064913270988125,
      "worst_drawdown": -0.12869123553035666
    },
    "60": {
      "n": 3,
      "median_return": -0.04648398576512458,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.06247234892980824,
      "median_mae": -0.14860912129894943,
      "worst_drawdown": -0.2764384627577562
    }
  }
}
```
## 40-bar formation

No calibrated tactical verdict: broad-market regime, execution risk and repeatable out-of-sample edge remain unverified.

| Horizon | Independent episodes | Median net return | Target first | Stop first | No hit | 95% Wilson interval |
|---|---|---|---|---|---|---|
| 5 | 3 | 0.01613177673265076 | 0.0 | 0.0 | 1.0 | [0.0, 0.5615060804490177] |
| 20 | 3 | 0.0023401333797088437 | 0.3333333333333333 | 0.3333333333333333 | 0.3333333333333333 | [0.0614903152761605, 0.7923450448735121] |
| 60 | 3 | -0.07821031027405534 | 0.3333333333333333 | 0.6666666666666666 | 0.0 | [0.0614903152761605, 0.7923450448735121] |

Frozen training end: 2016-08-08. Disjoint holdout evaluations: 0.
Holdout return prediction MAE (shape/regime/dip): {'shape': None, 'regime': None, 'dip': None}

| Formation start | Match end | Distance | Path / candles / volume | Volatility ratio |
|---|---|---|---|---|
| 2015-09-25 | 2015-11-19 | 0.400 | 0.223 / 0.894 / 0.286 | 1.24 |
| 2013-08-19 | 2013-10-14 | 0.500 | 0.434 / 0.807 / 0.256 | 0.76 |
| 2014-07-25 | 2014-09-19 | 0.826 | 0.886 / 0.942 / 0.392 | 1.09 |

Matched-regime and buy-the-dip baselines (same horizons and costs):
```json
{
  "regime": {
    "5": {
      "n": 3,
      "median_return": -0.05227932960893866,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.004029267810352399,
      "median_mae": -0.07063092417061623,
      "worst_drawdown": -0.08671844604233625
    },
    "20": {
      "n": 3,
      "median_return": -0.1373141840114699,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.004227023285707121,
      "median_mae": -0.1651505413556138,
      "worst_drawdown": -0.1783794688531205
    },
    "60": {
      "n": 3,
      "median_return": -0.13862618483412326,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.03145734597156391,
      "median_mae": -0.24482127848914825,
      "worst_drawdown": -0.30534461143853486
    }
  },
  "dip": {
    "5": {
      "n": 3,
      "median_return": -0.040926356764586,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.030975240020212125,
      "median_mae": -0.05322952971529438,
      "worst_drawdown": -0.08210729570442532
    },
    "20": {
      "n": 3,
      "median_return": -0.0948499222981638,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.030975240020212125,
      "median_mae": -0.1467155128852956,
      "worst_drawdown": -0.1783794688531205
    },
    "60": {
      "n": 3,
      "median_return": -0.1425573409375518,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.05077022888094285,
      "median_mae": -0.2180394138453765,
      "worst_drawdown": -0.30534461143853486
    }
  }
}
```

Sensitivity to distance cutoff (0.75× / 1× / 1.25×; never selected by outcomes):
```json
{
  "0.75": {
    "5": {
      "n": 2,
      "median_return": 0.032395788591623065,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.6576280471103807
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.05035701556400318,
      "median_mae": -0.011584257830738076,
      "worst_drawdown": -0.013839716768587085
    },
    "20": {
      "n": 2,
      "median_return": 0.07045973518035975,
      "target_first_rate": 0.5,
      "wilson_95": [
        0.09452865480086614,
        0.9054713451991339
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 0.5,
      "median_days_to_target": 9.0,
      "median_mfe": 0.11066148869044057,
      "median_mae": -0.02844575162298635,
      "worst_drawdown": -0.05729979677789887
    },
    "60": {
      "n": 2,
      "median_return": 0.04029653763988078,
      "target_first_rate": 0.5,
      "wilson_95": [
        0.09452865480086614,
        0.9054713451991339
      ],
      "stop_first_rate": 0.5,
      "no_hit_rate": 0.0,
      "median_days_to_target": 9.0,
      "median_mfe": 0.18138839124794393,
      "median_mae": -0.15038535269365344,
      "worst_drawdown": -0.30534461143853486
    }
  },
  "1.0": {
    "5": {
      "n": 3,
      "median_return": 0.01613177673265076,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.032513194307922655,
      "median_mae": -0.01757322175732212,
      "worst_drawdown": -0.028341180731618953
    },
    "20": {
      "n": 3,
      "median_return": 0.0023401333797088437,
      "target_first_rate": 0.3333333333333333,
      "wilson_95": [
        0.0614903152761605,
        0.7923450448735121
      ],
      "stop_first_rate": 0.3333333333333333,
      "no_hit_rate": 0.3333333333333333,
      "median_days_to_target": 9.0,
      "median_mfe": 0.035613289579143226,
      "median_mae": -0.039318281488650575,
      "worst_drawdown": -0.0858988289267173
    },
    "60": {
      "n": 3,
      "median_return": -0.07821031027405534,
      "target_first_rate": 0.3333333333333333,
      "wilson_95": [
        0.0614903152761605,
        0.7923450448735121
      ],
      "stop_first_rate": 0.6666666666666666,
      "no_hit_rate": 0.0,
      "median_days_to_target": 9.0,
      "median_mfe": 0.05318553692137873,
      "median_mae": -0.1428226487987444,
      "worst_drawdown": -0.30534461143853486
    }
  },
  "1.25": {
    "5": {
      "n": 3,
      "median_return": 0.01613177673265076,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.032513194307922655,
      "median_mae": -0.01757322175732212,
      "worst_drawdown": -0.028341180731618953
    },
    "20": {
      "n": 3,
      "median_return": 0.0023401333797088437,
      "target_first_rate": 0.3333333333333333,
      "wilson_95": [
        0.0614903152761605,
        0.7923450448735121
      ],
      "stop_first_rate": 0.3333333333333333,
      "no_hit_rate": 0.3333333333333333,
      "median_days_to_target": 9.0,
      "median_mfe": 0.035613289579143226,
      "median_mae": -0.039318281488650575,
      "worst_drawdown": -0.0858988289267173
    },
    "60": {
      "n": 3,
      "median_return": -0.07821031027405534,
      "target_first_rate": 0.3333333333333333,
      "wilson_95": [
        0.0614903152761605,
        0.7923450448735121
      ],
      "stop_first_rate": 0.6666666666666666,
      "no_hit_rate": 0.0,
      "median_days_to_target": 9.0,
      "median_mfe": 0.05318553692137873,
      "median_mae": -0.1428226487987444,
      "worst_drawdown": -0.30534461143853486
    }
  }
}
```
## 60-bar formation

No calibrated tactical verdict: broad-market regime, execution risk and repeatable out-of-sample edge remain unverified.

| Horizon | Independent episodes | Median net return | Target first | Stop first | No hit | 95% Wilson interval |
|---|---|---|---|---|---|---|
| 5 | 3 | 0.015783404165536474 | 0.0 | 0.0 | 1.0 | [0.0, 0.5615060804490177] |
| 20 | 3 | 0.008715254543810504 | 0.0 | 0.0 | 1.0 | [0.0, 0.5615060804490177] |
| 60 | 3 | -0.07612663425828081 | 0.3333333333333333 | 0.6666666666666666 | 0.0 | [0.0614903152761605, 0.7923450448735121] |

Frozen training end: 2016-08-08. Disjoint holdout evaluations: 0.
Holdout return prediction MAE (shape/regime/dip): {'shape': None, 'regime': None, 'dip': None}

| Formation start | Match end | Distance | Path / candles / volume | Volatility ratio |
|---|---|---|---|---|
| 2015-08-26 | 2015-11-18 | 0.383 | 0.178 / 0.933 / 0.290 | 1.24 |
| 2013-08-20 | 2013-11-12 | 0.411 | 0.262 / 0.826 / 0.316 | 0.98 |
| 2014-06-19 | 2014-09-12 | 0.748 | 0.812 / 0.806 / 0.393 | 1.27 |

Matched-regime and buy-the-dip baselines (same horizons and costs):
```json
{
  "regime": {
    "5": {
      "n": 3,
      "median_return": -0.05227932960893866,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.004029267810352399,
      "median_mae": -0.07063092417061623,
      "worst_drawdown": -0.08671844604233625
    },
    "20": {
      "n": 3,
      "median_return": -0.1373141840114699,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.004227023285707121,
      "median_mae": -0.1651505413556138,
      "worst_drawdown": -0.1783794688531205
    },
    "60": {
      "n": 3,
      "median_return": -0.13862618483412326,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.03145734597156391,
      "median_mae": -0.24482127848914825,
      "worst_drawdown": -0.30534461143853486
    }
  },
  "dip": {
    "5": {
      "n": 3,
      "median_return": -0.040926356764586,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.030975240020212125,
      "median_mae": -0.05322952971529438,
      "worst_drawdown": -0.08210729570442532
    },
    "20": {
      "n": 3,
      "median_return": -0.0948499222981638,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.030975240020212125,
      "median_mae": -0.1467155128852956,
      "worst_drawdown": -0.1783794688531205
    },
    "60": {
      "n": 3,
      "median_return": -0.1425573409375518,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 1.0,
      "no_hit_rate": 0.0,
      "median_days_to_target": null,
      "median_mfe": 0.05077022888094285,
      "median_mae": -0.2180394138453765,
      "worst_drawdown": -0.30534461143853486
    }
  }
}
```

Sensitivity to distance cutoff (0.75× / 1× / 1.25×; never selected by outcomes):
```json
{
  "0.75": {
    "5": {
      "n": 3,
      "median_return": 0.015783404165536474,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.028980920517225783,
      "median_mae": -0.01101479129116234,
      "worst_drawdown": -0.022041728313052955
    },
    "20": {
      "n": 3,
      "median_return": 0.008715254543810504,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.03207041022395041,
      "median_mae": -0.042604816589806194,
      "worst_drawdown": -0.06015332608958113
    },
    "60": {
      "n": 3,
      "median_return": -0.07612663425828081,
      "target_first_rate": 0.3333333333333333,
      "wilson_95": [
        0.0614903152761605,
        0.7923450448735121
      ],
      "stop_first_rate": 0.6666666666666666,
      "no_hit_rate": 0.0,
      "median_days_to_target": 27.0,
      "median_mfe": 0.04958254212255486,
      "median_mae": -0.14248618617711883,
      "worst_drawdown": -0.30534461143853486
    }
  },
  "1.0": {
    "5": {
      "n": 3,
      "median_return": 0.015783404165536474,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.028980920517225783,
      "median_mae": -0.01101479129116234,
      "worst_drawdown": -0.022041728313052955
    },
    "20": {
      "n": 3,
      "median_return": 0.008715254543810504,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.03207041022395041,
      "median_mae": -0.042604816589806194,
      "worst_drawdown": -0.06015332608958113
    },
    "60": {
      "n": 3,
      "median_return": -0.07612663425828081,
      "target_first_rate": 0.3333333333333333,
      "wilson_95": [
        0.0614903152761605,
        0.7923450448735121
      ],
      "stop_first_rate": 0.6666666666666666,
      "no_hit_rate": 0.0,
      "median_days_to_target": 27.0,
      "median_mfe": 0.04958254212255486,
      "median_mae": -0.14248618617711883,
      "worst_drawdown": -0.30534461143853486
    }
  },
  "1.25": {
    "5": {
      "n": 3,
      "median_return": 0.015783404165536474,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.028980920517225783,
      "median_mae": -0.01101479129116234,
      "worst_drawdown": -0.022041728313052955
    },
    "20": {
      "n": 3,
      "median_return": 0.008715254543810504,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.03207041022395041,
      "median_mae": -0.042604816589806194,
      "worst_drawdown": -0.06015332608958113
    },
    "60": {
      "n": 3,
      "median_return": -0.07612663425828081,
      "target_first_rate": 0.3333333333333333,
      "wilson_95": [
        0.0614903152761605,
        0.7923450448735121
      ],
      "stop_first_rate": 0.6666666666666666,
      "no_hit_rate": 0.0,
      "median_days_to_target": 27.0,
      "median_mfe": 0.04958254212255486,
      "median_mae": -0.14248618617711883,
      "worst_drawdown": -0.30534461143853486
    }
  }
}
```

## Limits

- Research only; no production BUY/SELL integration or probability of profit.
- Adjusted OHLC outcomes approximate reinvested distributions; historical vendor data can be revised.
- US federal holiday calendar is an approximation, not an exchange calendar; unknown gaps are excluded.
- Broad-market trend is matched only when benchmark data is supplied; sector regimes are NOT controlled.
- Target/stop touches use daily adjusted ranges, not executable fills; same-bar ties count as stops.
- Illustrative round-trip cost; gaps, liquidity, spreads, event/dilution and going-concern risks are not modeled.
- Wilson intervals describe this sample; episode separation does not prove statistical independence.
- Settings are predeclared research assumptions, not optimized thresholds. No cross-stock pooling.
