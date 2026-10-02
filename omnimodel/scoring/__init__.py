"""Weighted-rule scoring subpackage.

Phase 1 scoring lives here as a Python reference implementation. The
production scoring path in Laravel can call this module via a small
HTTP endpoint or CLI, or duplicate the rules — the logic is intentionally
simple enough to translate 1:1.
"""