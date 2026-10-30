cat > ~/patch_label_email.py <<'EOF'
# Fa que l'email de l'etiqueta (send_label_email) també surti amb nacex_return_method = 'label'.
import shutil, time, py_compile
F = '/opt/tuctuc-erp/nath/custom_addons/nath_shopify_returns/models/shopify_return_log.py'
src = open(F, encoding='utf-8').read()

old_nacex = """            self.label_attachment_id = att
        else:
            cod_exp, albaran = carrier.nacex_put_return_expedicion(self)
"""
new_nacex = """            self.label_attachment_id = att
            self._send_label_email(att)
        else:
            cod_exp, albaran = carrier.nacex_put_return_expedicion(self)
"""
old_label = """            self.label_attachment_id = att
            config = self.config_id
            if config.send_label_email and config.mail_template_id and self.email:
                config.mail_template_id.send_mail(
                    self.id, force_send=True,
                    email_values={'attachment_ids': [(4, att.id)]})
        except Exception as e:
"""
new_label = """            self.label_attachment_id = att
            self._send_label_email(att)
        except Exception as e:
"""
old_def = """    def _step_label(self):
"""
new_def = """    def _send_label_email(self, att):
        \"\"\"Envia l'etiqueta al client amb la plantilla de la config (send_label_email). No bloqueja si falla.\"\"\"
        config = self.config_id
        if not (config.send_label_email and config.mail_template_id and self.email):
            return
        try:
            config.mail_template_id.send_mail(
                self.id, force_send=True,
                email_values={'attachment_ids': [(4, att.id)]})
        except Exception as e:
            _logger.warning('Email etiqueta %s: %s', self.remarks, e)
            self.message_post(body=_('No se ha podido enviar la etiqueta por email: %s') % e)

    def _step_label(self):
"""
for old in (old_nacex, old_label, old_def):
    assert src.count(old) == 1, 'No trobo el bloc (o surt més d\'un cop):\n' + old
assert '_send_label_email' not in src, 'Ja està aplicat'

backup = F + '.bak_' + time.strftime('%Y%m%d_%H%M%S')
shutil.copy2(F, backup)
src = src.replace(old_nacex, new_nacex).replace(old_label, new_label).replace(old_def, new_def)
open(F, 'w', encoding='utf-8').write(src)
py_compile.compile(F, doraise=True)
print('OK. Còpia a', backup)
EOF
/opt/tuctuc-erp/env/bin/python ~/patch_label_email.py
