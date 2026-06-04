"""Strategy Factory — YouTube → research → codegen → backtest → demo soak → real-money.

A resumable, stage-based pipeline that turns a trading-strategy video into a
vetted, paper-soaked strategy ready for a human go-live decision. One JSON job
file per strategy under logs/factory/. See state.py for the schema and runner.py
for the stage dispatcher.
"""
