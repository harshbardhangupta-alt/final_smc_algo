"""Deterministic trading engine.

This package contains the *deterministic* logic of the system: candle handling,
indicators, Smart-Money-Concepts (SMC) market-structure analysis, trade-level
calculation (entry / stop-loss / targets), position sizing and the quality
scoring engine.

Nothing in here calls an LLM or invents prices. Every value is derived from the
supplied market data, which keeps the core fully unit-testable and keeps price
calculations out of the hands of the language model, as required by the system
architecture rules.
"""
