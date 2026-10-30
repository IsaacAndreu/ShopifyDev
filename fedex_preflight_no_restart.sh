#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   bash fedex_preflight_no_restart.sh [archive] [target_module_dir]
#
# Read-only preflight. It extracts the archive into /tmp, validates it and
# compares the relevant files with the installed module. It never copies files,
# upgrades Odoo or restarts a service.

ARCHIVE="${1:-$HOME/delivery_fedex_rest2_13.0.1.1.0.tar.gz}"
TARGET="${2:-/opt/tuctuc-erp/nath/custom_addons/delivery_fedex_rest2}"
PYTHON="${ODOO_PYTHON:-/opt/tuctuc-erp/env/bin/python}"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -r "$ARCHIVE" ]] || die "No puc llegir l'arxiu: $ARCHIVE"
[[ -x "$PYTHON" ]] || die "No puc executar Python: $PYTHON"
[[ -d "$TARGET" ]] || die "No existeix el mòdul instal·lat: $TARGET"

TMP_DIR="$(mktemp -d /tmp/fedex_preflight.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

case "$ARCHIVE" in
  *.tar.gz|*.tgz)
    tar -xzf "$ARCHIVE" -C "$TMP_DIR"
    ;;
  *.zip)
    command -v unzip >/dev/null 2>&1 || die "Falta unzip per llegir un .zip"
    unzip -q "$ARCHIVE" -d "$TMP_DIR"
    ;;
  *)
    die "Format no suportat: usa .tar.gz, .tgz o .zip"
    ;;
esac

MANIFEST="$(find "$TMP_DIR" -type f -path '*/delivery_fedex_rest2/__manifest__.py' -print -quit)"
[[ -n "$MANIFEST" ]] || die "L'arxiu no conté delivery_fedex_rest2/__manifest__.py"
MODULE_ROOT="$(dirname "$MANIFEST")"

echo "=== PRECHECK FedEx (sense canvis ni reinici) ==="
echo "Arxiu: $ARCHIVE"
echo "Mòdul empaquetat: $MODULE_ROOT"
echo "Mòdul instal·lat: $TARGET"

mapfile -t PY_FILES < <(find "$MODULE_ROOT" -type f -name '*.py' -print)
(( ${#PY_FILES[@]} > 0 )) || die "No s'han trobat fitxers Python"
"$PYTHON" -m py_compile "${PY_FILES[@]}"
echo "OK: Python (${#PY_FILES[@]} fitxers)"

mapfile -t XML_FILES < <(find "$MODULE_ROOT" -type f -name '*.xml' -print)
if (( ${#XML_FILES[@]} )); then
  "$PYTHON" -c 'import sys, xml.etree.ElementTree as ET; [ET.parse(p) for p in sys.argv[1:]]; print("OK: XML (%s fitxers)" % len(sys.argv[1:]))' "${XML_FILES[@]}"
else
  echo "AVÍS: no hi ha XML"
fi

grep -q "fedex_rest_shipment_state" "$MODULE_ROOT/models/delivery_carrier.py" || die "Falta el guard d'estat FedEx"
grep -q "FOR UPDATE" "$MODULE_ROOT/models/delivery_carrier.py" || die "Falta el bloqueig de picking"
grep -q "carrier_tracking_ref" "$MODULE_ROOT/models/delivery_carrier.py" || die "Falta la comprovació del tracking"
echo "OK: guard d'idempotència detectat"

echo "--- Versions ---"
grep -E "'version'|^version" "$MODULE_ROOT/__manifest__.py" || true
grep -E "'version'|^version" "$TARGET/__manifest__.py" || true

echo "--- Hashos dels fitxers que canviarien ---"
for rel in __manifest__.py models/delivery_carrier.py views/stock_picking_views.xml; do
  if [[ -f "$MODULE_ROOT/$rel" ]]; then
    printf 'paquet    %-38s ' "$rel"
    sha256sum "$MODULE_ROOT/$rel" | awk '{print $1}'
  fi
  if [[ -f "$TARGET/$rel" ]]; then
    printf 'instal·lat %-35s ' "$rel"
    sha256sum "$TARGET/$rel" | awk '{print $1}'
  fi
done

echo "PRECHECK OK: no s'ha escrit res, no s'ha actualitzat Odoo i no s'ha reiniciat cap servei."
