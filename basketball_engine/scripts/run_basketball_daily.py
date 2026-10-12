"""Actual production entrypoint. No cached-dashboard relabeling or hardcoded zeros."""
from repair_v22.cli import main
if __name__=='__main__': raise SystemExit(main())
