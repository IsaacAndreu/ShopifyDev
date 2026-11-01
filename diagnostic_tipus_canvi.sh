#!/usr/bin/env bash
# Diagnòstic (només lectura) de per què Odoo no descarrega els tipus de canvi del BCE.
# No canvia res: només fa peticions HTTP i llegeix el log.
# Ús al servidor:  bash diagnostic_tipus_canvi.sh
PYTHON="${ODOO_PYTHON:-/opt/tuctuc-erp/env/bin/python}"
ODOO_CONF="${ODOO_CONF:-/opt/tuctuc-erp/tuctuc-erp.conf}"
URL_HTTP="http://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
URL_HTTPS="https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

echo "== 1. DNS"
getent hosts www.ecb.europa.eu || echo "!! No resol www.ecb.europa.eu"

echo; echo "== 2. curl (sistema)"
curl -sS -o /dev/null -w "http  -> %{http_code} %{redirect_url}\n" --max-time 20 "$URL_HTTP"
curl -sS -o /dev/null -w "https -> %{http_code}\n" --max-time 20 "$URL_HTTPS"

echo; echo "== 3. Python d'Odoo, igual que currency_rate_live (requests a http, segueix la redirecció)"
"$PYTHON" - "$URL_HTTP" <<'EOF'
import sys, requests
try:
    import certifi; print('certifi', certifi.__version__, certifi.where())
except Exception as e:
    print('certifi: no', e)
print('requests', requests.__version__)
try:
    r = requests.get(sys.argv[1], timeout=30)
    print('OK', r.status_code, r.url)
    print(r.text[:300])
except Exception as e:
    print('ERROR', type(e).__name__, e)
EOF

echo; echo "== 4. Proxy configurat?"
env | grep -i -E '^(https?|no)_proxy=' || echo "cap variable de proxy"
systemctl show tuctuc-erp.service -p Environment 2>/dev/null

echo; echo "== 5. Log d'Odoo (últims missatges del cron de divises)"
LOG=$(awk -F'=' '/^ *logfile/ {gsub(/ /,"",$2); print $2}' "$ODOO_CONF" 2>/dev/null)
if [[ -n "$LOG" && -r "$LOG" ]]; then
    grep -i -E "exchange rate|ecb|currency_rate|Unable to connect" "$LOG" | tail -n 15
else
    sudo journalctl -u tuctuc-erp.service --since "-3 days" --no-pager | grep -i -E "exchange rate|ecb|currency_rate|Unable to connect" | tail -n 15
fi
