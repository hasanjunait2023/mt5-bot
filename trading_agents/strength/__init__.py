"""Currency-strength engine — faithful -7..+7 net-pair-win model.

Computes 8-major currency strength internally from live MT5 bars, mirroring the
external "FX Co-Relation Strength" scanner the user follows (see
Correlation_System_Explained_BN.md): each currency's score = net count of pairs
it won/lost across its 7 major matchups, range -7..+7. Tiered + turned into
strength-difference BUY/SELL pair suggestions, computed per session.

Public surface lives in :mod:`trading_agents.strength.strength`.
"""
