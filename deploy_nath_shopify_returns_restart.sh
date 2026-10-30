#!/usr/bin/env bash
set -euo pipefail

# Copia el mòdul nath_shopify_returns amb backup i, si ho autoritzes,
# reinicia el servei. No executa l'actualització Odoo (-u): aquesta la faràs
# manualment des de la interfície o amb la teva pròpia comanda.
# No executa mai systemctl stop/start per separat: només usa systemctl restart.
#
# Ús:
#   sudo bash deploy_nath_shopify_returns_restart.sh \
#     ARCHIVE TARGET_MODULE_DIR ODOO_SERVICE DB_NAME
#
# Exemples:
#   sudo bash deploy_nath_shopify_returns_restart.sh \
#     /home/it_nath_group/nath_shopify_returns_13.0.1.6.8.tar.gz \
#     /opt/tuctuc-erp/nath/custom_addons/nath_shopify_returns \
#     tuctuc-erp.service TUCTUC_PRODUCTION

ARCHIVE="${1:-}"
TARGET="${2:-/opt/tuctuc-erp/nath/custom_addons/nath_shopify_returns}"
SERVICE="${3:-}"
DB_NAME="${4:-TUCTUC_PRODUCTION}"
PYTHON="${ODOO_PYTHON:-/opt/tuctuc-erp/env/bin/python}"

MODULE_NAME="nath_shopify_returns"
EXPECTED_VERSION="13.0.1.6.8"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ -n "$ARCHIVE" ]] || die "Falta ARCHIVE"
[[ -n "$SERVICE" ]] || die "Falta ODOO_SERVICE"
[[ -r "$ARCHIVE" ]] || die "No puc llegir l'arxiu: $ARCHIVE"
[[ -x "$PYTHON" ]] || die "No puc executar Python: $PYTHON"
[[ -d "$TARGET" ]] || die "No existeix el mòdul instal·lat: $TARGET"
case "$TARGET" in
  */custom_addons/nath_shopify_returns|*/custom_addons/*/nath_shopify_returns) ;;
  *) die "TARGET no sembla el mòdul esperat: $TARGET" ;;
esac

TMP_DIR="$(mktemp -d /tmp/shopify_returns_deploy.XXXXXX)"
cleanup() { rm -rf "$TMP_DIR"; }
trap cleanup EXIT

case "$ARCHIVE" in
  *.tar.gz|*.tgz) tar -xzf "$ARCHIVE" -C "$TMP_DIR" ;;
  *.zip)
    command -v unzip >/dev/null 2>&1 || die "Falta unzip per llegir un .zip"
    unzip -q "$ARCHIVE" -d "$TMP_DIR"
    ;;
  *) die "Format no suportat: usa .tar.gz, .tgz o .zip" ;;
esac

MANIFEST="$(find "$TMP_DIR" -type f -path "*/${MODULE_NAME}/__manifest__.py" -print -quit)"
[[ -n "$MANIFEST" ]] || die "L'arxiu no conté ${MODULE_NAME}/__manifest__.py"
MODULE_ROOT="$(dirname "$MANIFEST")"

mapfile -t PY_FILES < <(find "$MODULE_ROOT" -type f -name '*.py' -print)
(( ${#PY_FILES[@]} )) || die "El paquet no conté fitxers Python"
"$PYTHON" -m py_compile "${PY_FILES[@]}"

mapfile -t XML_FILES < <(find "$MODULE_ROOT" -type f -name '*.xml' -print)
if (( ${#XML_FILES[@]} )); then
  "$PYTHON" -c 'import sys, xml.etree.ElementTree as ET; [ET.parse(p) for p in sys.argv[1:]]' "${XML_FILES[@]}"
fi

"$PYTHON" - "$MANIFEST" "$EXPECTED_VERSION" <<'PY'
import ast
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1])
expected_version = sys.argv[2]
tree = ast.parse(manifest_path.read_text(encoding="utf-8"), filename=str(manifest_path))
values = {}
for node in tree.body:
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in {"__manifest__", "__openerp__"}:
                values = ast.literal_eval(node.value)
# Els manifests habituals d'Odoo 13 són un diccionari directe (sense
# "__manifest__ ="). També acceptem la forma assignada per compatibilitat.
if not values and len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr):
    values = ast.literal_eval(tree.body[0].value)
if not isinstance(values, dict):
    raise SystemExit("El manifest no és un diccionari vàlid")
if values.get("version") != expected_version:
    raise SystemExit(
        f"Versió inesperada: {values.get('version')!r}; s'esperava {expected_version!r}"
    )
PY

grep -q "shopify_return" "$MODULE_ROOT/__manifest__.py" || die "Manifest inesperat per al mòdul Shopify"

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="${TARGET}.backup.${STAMP}"
TARGET_OWNER="$(stat -c '%u:%g' "$TARGET")"

echo "=== COPIA nath_shopify_returns (sense actualitzar Odoo) ==="
echo "Mòdul: $MODULE_NAME"
echo "Versió: $EXPECTED_VERSION"
echo "Backup: $BACKUP"
echo "Target: $TARGET"
echo "Servei: $SERVICE"
echo "Base de dades: $DB_NAME"

sudo cp -a "$TARGET" "$BACKUP"
sudo cp -a "$MODULE_ROOT/." "$TARGET/"
sudo chown -R "$TARGET_OWNER" "$TARGET"

echo "Còpia completada. Encara no s'ha actualitzat el mòdul a la base de dades."
echo "La base de dades indicada és: $DB_NAME"
echo
read -r -p "Vols reiniciar $SERVICE ara? [s/N] " RESTART_CONFIRM || true
case "${RESTART_CONFIRM,,}" in
  s|si|sí|y|yes)
    echo "Reiniciant servei (systemctl restart; no stop/start separat)..."
    sudo systemctl restart "$SERVICE"
    echo "RESTART OK."
    ;;
  *)
    echo "No s'ha reiniciat el servei. Pots reiniciar-lo més tard amb:"
    echo "sudo systemctl restart $SERVICE"
    ;;
esac

echo "PROCÉS OK. Backup conservat a: $BACKUP"
