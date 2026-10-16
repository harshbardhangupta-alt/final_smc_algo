"""Smart Money Concepts (SMC) analysis primitives.

Each module here is a pure, deterministic analyser over completed candles:

* ``structure``  - swing points, BOS, CHOCH, trend classification
* ``zones``      - supply & demand zones with freshness / mitigation state
* ``fvg``        - displacement detection and Fair Value Gaps
* ``liquidity``  - equal highs/lows, buy/sell-side pools, sweeps
* ``levels``     - support / resistance from structure

Confirmed signals use only confirmed structural levels and never look ahead.
"""
