from flask import Flask, render_template, request, jsonify
from flask_mail import Mail, Message
from google.oauth2.service_account import Credentials
import gspread
from datetime import datetime
import os
import json
import threading

app = Flask(__name__)

# Configurar email
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', True)
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')

mail = Mail(app)

SCOPE = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = '114L--j0CQW9yikCx7fn04xDPX89il5nWS7tr7z4Scko'

def conectar_sheets():
    try:
        creds_json = os.getenv('GOOGLE_CREDENTIALS')
        
        if creds_json:
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
        else:
            creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPE)
        
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        
        try:
            ws = spreadsheet.worksheet("Inscripciones")
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title="Inscripciones", rows=1000, cols=12)
        
        return ws
    except Exception as e:
        print(f"Error conectando a Google Sheets: {e}")
        return None

def crear_hoja_si_no_existe():
    try:
        ws = conectar_sheets()
        if ws and ws.cell(1, 1).value is None:
            encabezados = [
                'ID', 'Nombre', 'Email', 'Teléfono', 'Clases', 'Tutor', 'Tel. Tutor', 
                'Email Tutor', 'Acepta Términos', 'Autoriza Imagen', 'Firma', 'Fecha Registro'
            ]
            ws.insert_row(encabezados, 1)
    except Exception as e:
        print(f"Error creando hoja: {e}")

def enviar_email_async(app, email, nombre, clases, datos):
    with app.app_context():
        try:
            print(f"[EMAIL] Iniciando envío a: {email}")
            
            asunto = "Confirmación de Inscripción - Escuela de Baile"
            
            cuerpo = f"""
            <html>
            <body style="font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px;">
                <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1);">
                    <h2 style="color: #667eea;">✓ ¡Inscripción Confirmada!</h2>
                    
                    <p>Hola <strong>{nombre}</strong>,</p>
                    
                    <p>Gracias por inscribirse en nuestra escuela de baile. Hemos recibido tu solicitud correctamente.</p>
                    
                    <h3 style="color: #667eea; margin-top: 30px;">Datos de tu Inscripción:</h3>
                    <div style="background-color: #f9f9f9; padding: 15px; border-radius: 5px; border-left: 4px solid #667eea;">
                        <p><strong>Nombre:</strong> {nombre}</p>
                        <p><strong>Email:</strong> {email}</p>
                        <p><strong>Teléfono:</strong> {datos.get('telefono', 'N/A')}</p>
                        <p><strong>Clases Seleccionadas:</strong><br>
                        {''.join([f'• {clase}<br>' for clase in clases])}
                        </p>
                        <p><strong>Fecha de Registro:</strong> {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
                    </div>
                    
                    <h3 style="color: #667eea; margin-top: 30px;">¿Qué es lo siguiente?</h3>
                    <p>En breve nos pondremos en contacto contigo para confirmar tu pago y proporcionar más detalles sobre el inicio de las clases.</p>
                    
                    <p style="margin-top: 30px; color: #888; font-size: 12px;">
                        Este es un email automático. Por favor, no respondas a este correo.
                    </p>
                    
                    <hr style="margin-top: 30px; border: none; border-top: 1px solid #ddd;">
                    <p style="text-align: center; color: #667eea; font-weight: bold;">Escuela de Baile</p>
                </div>
            </body>
            </html>
            """
            
            msg = Message(subject=asunto, recipients=[email], html=cuerpo)
            print(f"[EMAIL] Mensaje creado, enviando...")
            mail.send(msg)
            print(f"[EMAIL] ✓ Email enviado a {email}")
        except Exception as e:
            print(f"[EMAIL] ✗ Error enviando email: {e}")
            import traceback
            traceback.print_exc()

@app.route('/')
def formulario():
    return render_template('formulario.html')

@app.route('/guardar', methods=['POST'])
def guardar():
    try:
        datos = request.json
        ws = conectar_sheets()
        
        if ws is None:
            return jsonify({'success': False, 'error': 'No se pudo conectar a Google Sheets'})
        
        all_rows = ws.get_all_values()
        id_registro = len(all_rows)
        
        fila = [
            id_registro,
            datos['nombre'],
            datos.get('email', ''),
            datos.get('telefono', ''),
            ', '.join(datos.get('clases', [])),
            datos.get('tutor_nombre', ''),
            datos.get('tutor_telefono', ''),
            datos.get('tutor_email', ''),
            'Sí' if datos.get('acepta_terminos') else 'No',
            'Sí' if datos.get('autoriza_imagen') else 'No',
            datos.get('firma', ''),
            datetime.now().strftime('%d/%m/%Y %H:%M')
        ]
        
        ws.append_row(fila)
        print(f"[GUARDAR] Registro guardado con ID: {id_registro}")
        
        email_destino = datos.get('email') or datos.get('tutor_email')
        
        if email_destino:
            print(f"[GUARDAR] Iniciando thread de email...")
            thread = threading.Thread(target=enviar_email_async, args=(app, email_destino, datos['nombre'], datos.get('clases', []), datos))
            thread.start()
        
        return jsonify({'success': True, 'mensaje': '¡Inscripción registrada correctamente!'})
    except Exception as e:
        print(f"Error guardando: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    crear_hoja_si_no_existe()
    app.run(debug=False)