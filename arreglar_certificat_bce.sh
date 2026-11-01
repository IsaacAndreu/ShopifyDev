#!/usr/bin/env bash
# Afegeix l'arrel "Sectigo Public Server Authentication Root E46" al certifi del Python d'Odoo.
# Des de l'1/08/2026 el certificat de www.ecb.europa.eu penja d'aquesta arrel (2021) i el
# certifi 2020.06.20 del servidor no la té: Odoo no pot baixar els tipus de canvi.
# Només AFEGEIX una arrel (no en treu cap): la resta d'integracions no canvien.
# Fa còpia del fitxer abans i pregunta abans d'escriure.
set -euo pipefail
PYTHON="${ODOO_PYTHON:-/opt/tuctuc-erp/env/bin/python}"
FP_OK="C9:0F:26:F0:FB:1B:40:18:B2:22:27:51:9B:5C:A2:B5:3E:2C:A5:B3:BE:5C:F1:8E:FE:1B:EF:47:38:0C:53:83"
URL="http://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"

PEM=$(mktemp)
trap 'rm -f "$PEM"' EXIT
cat > "$PEM" <<'EOF'
-----BEGIN CERTIFICATE-----
MIICOjCCAcGgAwIBAgIQQvLM2htpN0RfFf51KBC49DAKBggqhkjOPQQDAzBfMQsw
CQYDVQQGEwJHQjEYMBYGA1UEChMPU2VjdGlnbyBMaW1pdGVkMTYwNAYDVQQDEy1T
ZWN0aWdvIFB1YmxpYyBTZXJ2ZXIgQXV0aGVudGljYXRpb24gUm9vdCBFNDYwHhcN
MjEwMzIyMDAwMDAwWhcNNDYwMzIxMjM1OTU5WjBfMQswCQYDVQQGEwJHQjEYMBYG
A1UEChMPU2VjdGlnbyBMaW1pdGVkMTYwNAYDVQQDEy1TZWN0aWdvIFB1YmxpYyBT
ZXJ2ZXIgQXV0aGVudGljYXRpb24gUm9vdCBFNDYwdjAQBgcqhkjOPQIBBgUrgQQA
IgNiAAR2+pmpbiDt+dd34wc7qNs9Xzjoq1WmVk/WSOrsfy2qw7LFeeyZYX8QeccC
WvkEN/U0NSt3zn8gj1KjAIns1aeibVvjS5KToID1AZTc8GgHHs3u/iVStSBDHBv+
6xnOQ6OjQjBAMB0GA1UdDgQWBBTRItpMWfFLXyY4qp3W7usNw/upYTAOBgNVHQ8B
Af8EBAMCAYYwDwYDVR0TAQH/BAUwAwEB/zAKBggqhkjOPQQDAwNnADBkAjAn7qRa
qCG76UeXlImldCBteU/IvZNeWBj7LRoAasm4PdCkT0RHlAFWovgzJQxC36oCMB3q
4S6ILuH5px0CMk7yn2xVdOOurvulGu7t0vzCAxHrRVxgED1cf5kDW21USAGKcw==
-----END CERTIFICATE-----
EOF

FP=$(openssl x509 -in "$PEM" -noout -fingerprint -sha256 | cut -d= -f2)
openssl x509 -in "$PEM" -noout -subject -dates
[[ "$FP" == "$FP_OK" ]] || { echo "!! La petjada no coincideix ($FP). No toco res."; exit 1; }
echo "Petjada SHA-256 correcta."

BUNDLE=$("$PYTHON" -c 'import certifi; print(certifi.where())')
echo "Fitxer de certificats d'Odoo: $BUNDLE"
if grep -q "MIICOjCCAcGgAwIBAgIQQvLM2htpN0RfFf51KBC49DAKBggqhkjOPQQDAzBfMQsw" "$BUNDLE"; then
    echo "L'arrel ja hi és: no cal afegir-la."
else
    read -r -p "Afegir l'arrel Sectigo E46 a aquest fitxer (amb còpia abans)? [s/N] " OK || true
    [[ "${OK,,}" == "s" ]] || { echo "No he fet res."; exit 0; }
    BK="$BUNDLE.bak.$(date +%Y%m%d%H%M%S)"
    sudo cp -p "$BUNDLE" "$BK"
    { echo; echo "# Sectigo Public Server Authentication Root E46 (afegit $(date +%F) per al BCE)"; cat "$PEM"; } | sudo tee -a "$BUNDLE" >/dev/null
    echo "Afegida. Còpia anterior: $BK"
fi

echo; echo "== Prova amb el Python d'Odoo"
"$PYTHON" - "$URL" <<'EOF'
import sys, requests
try:
    r = requests.get(sys.argv[1], timeout=30)
    print('OK', r.status_code, r.url)
    print('Tipus del dia' if 'Cube time=' in r.text else 'Resposta inesperada', r.text[r.text.find('Cube time='):][:30])
except Exception as e:
    print('ERROR', type(e).__name__, e)
EOF
echo
echo "Per desfer-ho: sudo cp -p <còpia .bak> \"$BUNDLE\""
