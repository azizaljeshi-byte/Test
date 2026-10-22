# Chart Pattern Lab: AMZN historical fixture

As of 2018-02-07 — **INSUFFICIENT EVIDENCE**


Distances measure shape similarity; hit-first rates are observed frequencies, not success probabilities.

Source: {"url": "https://raw.githubusercontent.com/plotly/datasets/0c447c47b757ad74edecab31f0d72f849d2e67c2/all_stocks_5yr.csv", "sha256": "6aea253cd19de60b568143991aaf1fa482456565c389205658d236e595e716cf", "rows": 1259, "start": "2013-02-08", "end": "2018-02-07", "adjustment": "AMZN had no splits or dividends during 2013\u20132018. Historical prices preserved, not restated for 2022 split.", "excluded": "Other tickers excluded; no fabricated timestamps; no SPY supplied."}

## 20-bar formation

No calibrated tactical verdict: broad-market regime, execution risk and repeatable out-of-sample edge remain unverified.

| Horizon | Independent episodes | Median net return | Target first | Stop first | No hit | 95% Wilson interval |
|---|---|---|---|---|---|---|
| 5 | 4 | -0.03552655104882063 | 0.0 | 0.0 | 1.0 | [0.0, 0.48990002040399916] |
| 20 | 4 | -0.07927812603031209 | 0.0 | 0.5 | 0.5 | [0.0, 0.48990002040399916] |
| 60 | 4 | -0.06696763286214857 | 0.0 | 0.75 | 0.25 | [0.0, 0.48990002040399916] |

Frozen training end: 2016-08-08. Disjoint holdout evaluations: 0.
Holdout return prediction MAE (shape/regime/dip): {'shape': None, 'regime': None, 'dip': None}

| Formation start | Match end | Distance | Path / candles / volume | Volatility ratio |
|---|---|---|---|---|
| 2013-06-24 | 2013-07-22 | 0.429 | 0.200 / 1.084 / 0.251 | 0.91 |
| 2015-10-13 | 2015-11-09 | 0.499 | 0.258 / 1.219 / 0.264 | 1.22 |
| 2014-10-29 | 2014-11-25 | 0.585 | 0.395 / 1.223 / 0.279 | 1.14 |
| 2014-02-19 | 2014-03-18 | 0.735 | 0.637 / 1.261 / 0.252 | 1.18 |

Matched-regime and buy-the-dip baselines (same horizons and costs):
```json
{
  "regime": {
    "5": {
      "n": 5,
      "median_return": -0.02903606201161668,
      "target_first_rate": 0.0,
      "wilson_95": [
        -2.7755575615628914e-17,
        0.43449149475208104
      ],
      "stop_first_rate": 0.2,
      "no_hit_rate": 0.8,
      "median_days_to_target": null,
      "median_mfe": 0.012032995753021858,
      "median_mae": -0.0406307021575919,
      "worst_drawdown": -0.07461712089839023
    },
    "20": {
      "n": 5,
      "median_return": -0.002027857869151604,
      "target_first_rate": 0.0,
      "wilson_95": [
        -2.7755575615628914e-17,
        0.43449149475208104
      ],
      "stop_first_rate": 0.4,
      "no_hit_rate": 0.6,
      "median_days_to_target": null,
      "median_mfe": 0.01890156421935285,
      "median_mae": -0.07389741914407055,
      "worst_drawdown": -0.17699395411463414
    },
    "60": {
      "n": 5,
      "median_return": 0.08437700098007195,
      "target_first_rate": 0.2,
      "wilson_95": [
        0.03622316096978745,
        0.6244717358814613
      ],
      "stop_first_rate": 0.6,
      "no_hit_rate": 0.2,
      "median_days_to_target": 55.0,
      "median_mfe": 0.1013067624959163,
      "median_mae": -0.085007554983491,
      "worst_drawdown": -0.23879927132560652
    }
  },
  "dip": {
    "5": {
      "n": 4,
      "median_return": -0.0007360096061694854,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.25,
      "no_hit_rate": 0.75,
      "median_days_to_target": null,
      "median_mfe": 0.06010459777619048,
      "median_mae": -0.0290341528142245,
      "worst_drawdown": -0.14108831046376025
    },
    "20": {
      "n": 4,
      "median_return": 0.005902211775707489,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.5,
      "no_hit_rate": 0.5,
      "median_days_to_target": null,
      "median_mfe": 0.06676145691557989,
      "median_mae": -0.05951148719553051,
      "worst_drawdown": -0.14108831046376025
    },
    "60": {
      "n": 4,
      "median_return": 0.14401989700856543,
      "target_first_rate": 0.25,
      "wilson_95": [
        0.045586062644636216,
        0.6993639475573634
      ],
      "stop_first_rate": 0.5,
      "no_hit_rate": 0.25,
      "median_days_to_target": 30.0,
      "median_mfe": 0.16337839040935276,
      "median_mae": -0.07143266644225904,
      "worst_drawdown": -0.2460981117093869
    }
  }
}
```

Sensitivity to distance cutoff (0.75× / 1× / 1.25×; never selected by outcomes):
```json
{
  "0.75": {
    "5": {
      "n": 4,
      "median_return": -0.03552655104882063,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.02489674702621536,
      "median_mae": -0.056186552983402915,
      "worst_drawdown": -0.07107215460569727
    },
    "20": {
      "n": 4,
      "median_return": -0.07927812603031209,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.5,
      "no_hit_rate": 0.5,
      "median_days_to_target": null,
      "median_mfe": 0.025988681721826223,
      "median_mae": -0.09564510725252784,
      "worst_drawdown": -0.17699395411463414
    },
    "60": {
      "n": 4,
      "median_return": -0.06696763286214857,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.75,
      "no_hit_rate": 0.25,
      "median_days_to_target": null,
      "median_mfe": 0.06326464421579381,
      "median_mae": -0.1935283474349329,
      "worst_drawdown": -0.2764384627577562
    }
  },
  "1.0": {
    "5": {
      "n": 4,
      "median_return": -0.03552655104882063,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.02489674702621536,
      "median_mae": -0.056186552983402915,
      "worst_drawdown": -0.07107215460569727
    },
    "20": {
      "n": 4,
      "median_return": -0.07927812603031209,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.5,
      "no_hit_rate": 0.5,
      "median_days_to_target": null,
      "median_mfe": 0.025988681721826223,
      "median_mae": -0.09564510725252784,
      "worst_drawdown": -0.17699395411463414
    },
    "60": {
      "n": 4,
      "median_return": -0.06696763286214857,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.75,
      "no_hit_rate": 0.25,
      "median_days_to_target": null,
      "median_mfe": 0.06326464421579381,
      "median_mae": -0.1935283474349329,
      "worst_drawdown": -0.2764384627577562
    }
  },
  "1.25": {
    "5": {
      "n": 4,
      "median_return": -0.03552655104882063,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.02489674702621536,
      "median_mae": -0.056186552983402915,
      "worst_drawdown": -0.07107215460569727
    },
    "20": {
      "n": 4,
      "median_return": -0.07927812603031209,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.5,
      "no_hit_rate": 0.5,
      "median_days_to_target": null,
      "median_mfe": 0.025988681721826223,
      "median_mae": -0.09564510725252784,
      "worst_drawdown": -0.17699395411463414
    },
    "60": {
      "n": 4,
      "median_return": -0.06696763286214857,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.75,
      "no_hit_rate": 0.25,
      "median_days_to_target": null,
      "median_mfe": 0.06326464421579381,
      "median_mae": -0.1935283474349329,
      "worst_drawdown": -0.2764384627577562
    }
  }
}
```
## 40-bar formation

No calibrated tactical verdict: broad-market regime, execution risk and repeatable out-of-sample edge remain unverified.

| Horizon | Independent episodes | Median net return | Target first | Stop first | No hit | 95% Wilson interval |
|---|---|---|---|---|---|---|
| 5 | 4 | 0.014319794821841758 | 0.0 | 0.0 | 1.0 | [0.0, 0.48990002040399916] |
| 20 | 4 | -0.041105366139715716 | 0.0 | 0.25 | 0.75 | [0.0, 0.48990002040399916] |
| 60 | 4 | 0.01797017235188747 | 0.25 | 0.75 | 0.0 | [0.045586062644636216, 0.6993639475573634] |

Frozen training end: 2016-08-08. Disjoint holdout evaluations: 0.
Holdout return prediction MAE (shape/regime/dip): {'shape': None, 'regime': None, 'dip': None}

| Formation start | Match end | Distance | Path / candles / volume | Volatility ratio |
|---|---|---|---|---|
| 2013-06-03 | 2013-07-29 | 0.397 | 0.290 / 0.719 / 0.289 | 0.92 |
| 2015-09-25 | 2015-11-19 | 0.400 | 0.223 / 0.894 / 0.286 | 1.24 |
| 2014-12-24 | 2015-02-23 | 0.527 | 0.372 / 0.968 / 0.412 | 1.25 |
| 2014-05-08 | 2014-07-03 | 0.569 | 0.453 / 0.981 / 0.348 | 1.15 |

Matched-regime and buy-the-dip baselines (same horizons and costs):
```json
{
  "regime": {
    "5": {
      "n": 5,
      "median_return": -0.02903606201161668,
      "target_first_rate": 0.0,
      "wilson_95": [
        -2.7755575615628914e-17,
        0.43449149475208104
      ],
      "stop_first_rate": 0.2,
      "no_hit_rate": 0.8,
      "median_days_to_target": null,
      "median_mfe": 0.012032995753021858,
      "median_mae": -0.0406307021575919,
      "worst_drawdown": -0.07461712089839023
    },
    "20": {
      "n": 5,
      "median_return": -0.002027857869151604,
      "target_first_rate": 0.0,
      "wilson_95": [
        -2.7755575615628914e-17,
        0.43449149475208104
      ],
      "stop_first_rate": 0.4,
      "no_hit_rate": 0.6,
      "median_days_to_target": null,
      "median_mfe": 0.01890156421935285,
      "median_mae": -0.07389741914407055,
      "worst_drawdown": -0.17699395411463414
    },
    "60": {
      "n": 5,
      "median_return": 0.08437700098007195,
      "target_first_rate": 0.2,
      "wilson_95": [
        0.03622316096978745,
        0.6244717358814613
      ],
      "stop_first_rate": 0.6,
      "no_hit_rate": 0.2,
      "median_days_to_target": 55.0,
      "median_mfe": 0.1013067624959163,
      "median_mae": -0.085007554983491,
      "worst_drawdown": -0.23879927132560652
    }
  },
  "dip": {
    "5": {
      "n": 4,
      "median_return": -0.0007360096061694854,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.25,
      "no_hit_rate": 0.75,
      "median_days_to_target": null,
      "median_mfe": 0.06010459777619048,
      "median_mae": -0.0290341528142245,
      "worst_drawdown": -0.14108831046376025
    },
    "20": {
      "n": 4,
      "median_return": 0.005902211775707489,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.5,
      "no_hit_rate": 0.5,
      "median_days_to_target": null,
      "median_mfe": 0.06676145691557989,
      "median_mae": -0.05951148719553051,
      "worst_drawdown": -0.14108831046376025
    },
    "60": {
      "n": 4,
      "median_return": 0.14401989700856543,
      "target_first_rate": 0.25,
      "wilson_95": [
        0.045586062644636216,
        0.6993639475573634
      ],
      "stop_first_rate": 0.5,
      "no_hit_rate": 0.25,
      "median_days_to_target": 30.0,
      "median_mfe": 0.16337839040935276,
      "median_mae": -0.07143266644225904,
      "worst_drawdown": -0.2460981117093869
    }
  }
}
```

Sensitivity to distance cutoff (0.75× / 1× / 1.25×; never selected by outcomes):
```json
{
  "0.75": {
    "5": {
      "n": 4,
      "median_return": 0.014319794821841758,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.026226523935676482,
      "median_mae": -0.017975847788122945,
      "worst_drawdown": -0.040540220212627265
    },
    "20": {
      "n": 4,
      "median_return": -0.041105366139715716,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.25,
      "no_hit_rate": 0.75,
      "median_days_to_target": null,
      "median_mfe": 0.029946908902793057,
      "median_mae": -0.056607850316360564,
      "worst_drawdown": -0.14904112626094657
    },
    "60": {
      "n": 4,
      "median_return": 0.01797017235188747,
      "target_first_rate": 0.25,
      "wilson_95": [
        0.045586062644636216,
        0.6993639475573634
      ],
      "stop_first_rate": 0.75,
      "no_hit_rate": 0.0,
      "median_days_to_target": 43.0,
      "median_mfe": 0.0911847123609919,
      "median_mae": -0.09247536219020108,
      "worst_drawdown": -0.30534461143853486
    }
  },
  "1.0": {
    "5": {
      "n": 4,
      "median_return": 0.014319794821841758,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.026226523935676482,
      "median_mae": -0.017975847788122945,
      "worst_drawdown": -0.040540220212627265
    },
    "20": {
      "n": 4,
      "median_return": -0.041105366139715716,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.25,
      "no_hit_rate": 0.75,
      "median_days_to_target": null,
      "median_mfe": 0.029946908902793057,
      "median_mae": -0.056607850316360564,
      "worst_drawdown": -0.14904112626094657
    },
    "60": {
      "n": 4,
      "median_return": 0.01797017235188747,
      "target_first_rate": 0.25,
      "wilson_95": [
        0.045586062644636216,
        0.6993639475573634
      ],
      "stop_first_rate": 0.75,
      "no_hit_rate": 0.0,
      "median_days_to_target": 43.0,
      "median_mfe": 0.0911847123609919,
      "median_mae": -0.09247536219020108,
      "worst_drawdown": -0.30534461143853486
    }
  },
  "1.25": {
    "5": {
      "n": 4,
      "median_return": 0.014319794821841758,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.026226523935676482,
      "median_mae": -0.017975847788122945,
      "worst_drawdown": -0.040540220212627265
    },
    "20": {
      "n": 4,
      "median_return": -0.041105366139715716,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.25,
      "no_hit_rate": 0.75,
      "median_days_to_target": null,
      "median_mfe": 0.029946908902793057,
      "median_mae": -0.056607850316360564,
      "worst_drawdown": -0.14904112626094657
    },
    "60": {
      "n": 4,
      "median_return": 0.01797017235188747,
      "target_first_rate": 0.25,
      "wilson_95": [
        0.045586062644636216,
        0.6993639475573634
      ],
      "stop_first_rate": 0.75,
      "no_hit_rate": 0.0,
      "median_days_to_target": 43.0,
      "median_mfe": 0.0911847123609919,
      "median_mae": -0.09247536219020108,
      "worst_drawdown": -0.30534461143853486
    }
  }
}
```
## 60-bar formation

No calibrated tactical verdict: broad-market regime, execution risk and repeatable out-of-sample edge remain unverified.

| Horizon | Independent episodes | Median net return | Target first | Stop first | No hit | 95% Wilson interval |
|---|---|---|---|---|---|---|
| 5 | 4 | 1.0362268736130442e-05 | 0.0 | 0.0 | 1.0 | [0.0, 0.48990002040399916] |
| 20 | 4 | -0.03731190765203801 | 0.0 | 0.25 | 0.75 | [0.0, 0.48990002040399916] |
| 60 | 4 | 0.02453432570364711 | 0.25 | 0.75 | 0.0 | [0.045586062644636216, 0.6993639475573634] |

Frozen training end: 2016-08-08. Disjoint holdout evaluations: 0.
Holdout return prediction MAE (shape/regime/dip): {'shape': None, 'regime': None, 'dip': None}

| Formation start | Match end | Distance | Path / candles / volume | Volatility ratio |
|---|---|---|---|---|
| 2013-05-03 | 2013-07-29 | 0.356 | 0.209 / 0.747 / 0.292 | 0.92 |
| 2015-08-26 | 2015-11-18 | 0.383 | 0.178 / 0.933 / 0.290 | 1.24 |
| 2014-12-10 | 2015-03-09 | 0.520 | 0.362 / 0.928 / 0.477 | 1.24 |
| 2014-04-10 | 2014-07-07 | 0.807 | 0.841 / 0.991 / 0.366 | 1.13 |

Matched-regime and buy-the-dip baselines (same horizons and costs):
```json
{
  "regime": {
    "5": {
      "n": 5,
      "median_return": -0.02903606201161668,
      "target_first_rate": 0.0,
      "wilson_95": [
        -2.7755575615628914e-17,
        0.43449149475208104
      ],
      "stop_first_rate": 0.2,
      "no_hit_rate": 0.8,
      "median_days_to_target": null,
      "median_mfe": 0.012032995753021858,
      "median_mae": -0.0406307021575919,
      "worst_drawdown": -0.07461712089839023
    },
    "20": {
      "n": 5,
      "median_return": -0.002027857869151604,
      "target_first_rate": 0.0,
      "wilson_95": [
        -2.7755575615628914e-17,
        0.43449149475208104
      ],
      "stop_first_rate": 0.4,
      "no_hit_rate": 0.6,
      "median_days_to_target": null,
      "median_mfe": 0.01890156421935285,
      "median_mae": -0.07389741914407055,
      "worst_drawdown": -0.17699395411463414
    },
    "60": {
      "n": 5,
      "median_return": 0.08437700098007195,
      "target_first_rate": 0.2,
      "wilson_95": [
        0.03622316096978745,
        0.6244717358814613
      ],
      "stop_first_rate": 0.6,
      "no_hit_rate": 0.2,
      "median_days_to_target": 55.0,
      "median_mfe": 0.1013067624959163,
      "median_mae": -0.085007554983491,
      "worst_drawdown": -0.23879927132560652
    }
  },
  "dip": {
    "5": {
      "n": 4,
      "median_return": -0.0007360096061694854,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.25,
      "no_hit_rate": 0.75,
      "median_days_to_target": null,
      "median_mfe": 0.06010459777619048,
      "median_mae": -0.0290341528142245,
      "worst_drawdown": -0.14108831046376025
    },
    "20": {
      "n": 4,
      "median_return": 0.005902211775707489,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.5,
      "no_hit_rate": 0.5,
      "median_days_to_target": null,
      "median_mfe": 0.06676145691557989,
      "median_mae": -0.05951148719553051,
      "worst_drawdown": -0.14108831046376025
    },
    "60": {
      "n": 4,
      "median_return": 0.14401989700856543,
      "target_first_rate": 0.25,
      "wilson_95": [
        0.045586062644636216,
        0.6993639475573634
      ],
      "stop_first_rate": 0.5,
      "no_hit_rate": 0.25,
      "median_days_to_target": 30.0,
      "median_mfe": 0.16337839040935276,
      "median_mae": -0.07143266644225904,
      "worst_drawdown": -0.2460981117093869
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
      "median_return": -0.015762679628064213,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.012032995753021858,
      "median_mae": -0.025481868670369168,
      "worst_drawdown": -0.032200972104818204
    },
    "20": {
      "n": 3,
      "median_return": -0.012962595097210426,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.5615060804490177
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.012032995753021858,
      "median_mae": -0.042604816589806194,
      "worst_drawdown": -0.07033649134269859
    },
    "60": {
      "n": 3,
      "median_return": 0.08437700098007195,
      "target_first_rate": 0.3333333333333333,
      "wilson_95": [
        0.0614903152761605,
        0.7923450448735121
      ],
      "stop_first_rate": 0.6666666666666666,
      "no_hit_rate": 0.0,
      "median_days_to_target": 33.0,
      "median_mfe": 0.1013067624959163,
      "median_mae": -0.08745508003920299,
      "worst_drawdown": -0.30534461143853486
    }
  },
  "1.0": {
    "5": {
      "n": 4,
      "median_return": 1.0362268736130442e-05,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.02050695813512382,
      "median_mae": -0.028986707792496513,
      "worst_drawdown": -0.032200972104818204
    },
    "20": {
      "n": 4,
      "median_return": -0.03731190765203801,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.25,
      "no_hit_rate": 0.75,
      "median_days_to_target": null,
      "median_mfe": 0.022051702988486133,
      "median_mae": -0.05825111786693837,
      "worst_drawdown": -0.14904112626094657
    },
    "60": {
      "n": 4,
      "median_return": 0.02453432570364711,
      "target_first_rate": 0.25,
      "wilson_95": [
        0.045586062644636216,
        0.6993639475573634
      ],
      "stop_first_rate": 0.75,
      "no_hit_rate": 0.0,
      "median_days_to_target": 33.0,
      "median_mfe": 0.09757288357144789,
      "median_mae": -0.08714232041234621,
      "worst_drawdown": -0.30534461143853486
    }
  },
  "1.25": {
    "5": {
      "n": 4,
      "median_return": 1.0362268736130442e-05,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.0,
      "no_hit_rate": 1.0,
      "median_days_to_target": null,
      "median_mfe": 0.02050695813512382,
      "median_mae": -0.028986707792496513,
      "worst_drawdown": -0.032200972104818204
    },
    "20": {
      "n": 4,
      "median_return": -0.03731190765203801,
      "target_first_rate": 0.0,
      "wilson_95": [
        0.0,
        0.48990002040399916
      ],
      "stop_first_rate": 0.25,
      "no_hit_rate": 0.75,
      "median_days_to_target": null,
      "median_mfe": 0.022051702988486133,
      "median_mae": -0.05825111786693837,
      "worst_drawdown": -0.14904112626094657
    },
    "60": {
      "n": 4,
      "median_return": 0.02453432570364711,
      "target_first_rate": 0.25,
      "wilson_95": [
        0.045586062644636216,
        0.6993639475573634
      ],
      "stop_first_rate": 0.75,
      "no_hit_rate": 0.0,
      "median_days_to_target": 33.0,
      "median_mfe": 0.09757288357144789,
      "median_mae": -0.08714232041234621,
      "worst_drawdown": -0.30534461143853486
    }
  }
}
```

## Limits

- Research only; no production BUY/SELL integration or probability of profit.
- Adjusted OHLC outcomes approximate reinvested distributions; historical vendor data can be revised.
- US federal holidays plus Good Friday are an approximation, not an exchange calendar; unknown gaps are excluded.
- Broad-market trend is matched only when benchmark data is supplied; sector regimes are NOT controlled.
- Target/stop touches use daily adjusted ranges, not executable fills; same-bar ties count as stops.
- Illustrative round-trip cost; gaps, liquidity, spreads, event/dilution and going-concern risks are not modeled.
- Wilson intervals describe this sample; episode separation does not prove statistical independence.
- Settings are predeclared research assumptions, not optimized thresholds. No cross-stock pooling.
