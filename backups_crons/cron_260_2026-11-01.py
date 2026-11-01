local_tz = timezone(env.user.tz)
current_hour = datetime.datetime.now().astimezone(local_tz)
current_hour = current_hour.strftime('%H:%M')
limit_hour = "18:00"

company_ids = [1, 23]

ubicaciones_sorter = env['stock.location'].with_context(allowed_company_ids=company_ids).search([
    ('company_id', 'in', company_ids),
    ('barcode', '=', 'SORTER'),
], order='id asc')

email_destino = 'isaac.andreu@nath.es'
email_remitente = 'no_reply@tuctuc.com'

if ubicaciones_sorter:
  message = []
  # posar 'unavailable_for_reservation' a False
  new_status = False
  
  for index, ubicacion in enumerate(ubicaciones_sorter):
    old_status = ubicacion.unavailable_for_reservation
    
    message_line = "Ubicación <b>{}</b> => Estado anterior: {}, Estado nuevo: {}".format(
        ubicacion.complete_name, 
        str(old_status), 
        str(new_status)
    )
    message.append(message_line)
    
    ubicacion.write({'unavailable_for_reservation': new_status})
    
  asunto = "Cambio 'unavailable_for_reservation' ubicaciones SORTER 04:15h"
  message_html = "<br/>".join(message)
  
  env['mail.mail'].create({
      'subject': asunto,
      'body_html': message_html,
      'email_to': email_destino,
      'email_from': email_remitente,
  }).send()