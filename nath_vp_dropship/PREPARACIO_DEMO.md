# Prova a la demo amb el privalia_demo_kit

1. Instal·la el mòdul **NATH - Dropshipping Veepee (batches automáticos)**.
2. **Dades del kit**:
   - Crea les variants del fitxer 01, amb codi de barres i estoc.
   - Crea els transportistes `Demo - <país> - <clau>` del fitxer 05.
   - Crea les tarifes `Demo - ES`, `Demo - FR_BENELUX` i `Demo - IT`.

   Si la demo és una còpia de producció, pots fer servir directament els batches reals de VentePriveeSync i els transportistes `Veepee - …`.
3. **Configuració**:
   - «Simular API» activat.
   - Omple les dades de les comandes (taula del README).
4. **Importar Excel**:
   - *Mapeo de transportistas* → `05_MAPPING_CARRIER.xlsx`;
   - *Precios* → `06_price_list_by_country.xlsx`, amb campanya `DEMO01`;
   - *Batch* → `03_batch_150orders_9900001_07-10-2026.xlsx`.
5. **Al batch:**
   - Comprova que hi ha 150 comandes i 607 unitats, sense errors.
   - Clica **Crear pedidos** i mira el temps al xat.
   - Revisa unes quantes comandes DP: preu, tarifa, transportista, fecha de entrega, remarks, modo i plazo de pago.
6. Executa el cron 450 en simulació: ha de veure les 150 com a «por confirmar».
7. Repeteix-ho amb `04_batch_10000units_…` (2.172 comandes) per mesurar el temps. Si cal, tornant a clicar «Crear pedidos», que continua on ho ha deixat.
8. **Errors:** canvia un EAN o esborra un mapeig, torna a importar un batch i comprova que:
   - la comanda queda en *Error*;
   - arriba el correu;
   - «Volver a validar» la recupera.
