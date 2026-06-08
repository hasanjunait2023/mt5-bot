#!/bin/bash
# Disable the heaviest NON-TRADING services to free CPU under host steal.
# Reversible: set enabled:true (or delete the line) + restart orchestrator.
set -e
cd /home/trader/mt5-bot
cp configs/services.yaml "configs/services.yaml.bak.$(date +%s)"

# heavy / non-live-trading services to pause
CUT="factory_runner factory_paper factory_executor source_hunter growth_pipeline improvement_loop maic_bot tv_intraday tv_scalper tv_connection_watchdog"

for id in $CUT; do
  # idempotent: only insert if this id block doesn't already carry enabled:false
  if ! awk -v id="  - id: $id" '
        $0==id{f=1;next}
        f&&/^  - id:/{f=0}
        f&&/enabled: false/{print "y";exit}' configs/services.yaml | grep -q y; then
    sed -i "/^  - id: ${id}\$/a\\    enabled: false" configs/services.yaml
    echo "disabled: $id"
  else
    echo "already disabled: $id"
  fi
done

echo "=== services now disabled ==="
grep -nE "^  - id:|enabled: false" configs/services.yaml | grep -B1 "enabled: false"
echo "=== syntax sanity (python yaml load) ==="
.venv/bin/python -c "import yaml;d=yaml.safe_load(open('configs/services.yaml'));print('yaml OK, services:',len(d.get('services',[])))"
