from flask import Flask, render_template, request, jsonify
from google.oauth2.service_account import Credentials
import gspread
from datetime import datetime
import os
import json

app = Flask(__name__)

# Configura Google Sheets
SCOPE = ['https://www.googleapis.com/auth/spreadsheets']
SPREADSHEET_ID = '114L--j0CQW9yikCx7fn04xDPX89il5nWS7tr7z4Scko'  # Reemplaza con tu ID

def conectar_sheets():
    try:
        # Leer credenciales de la variable de entorno
        creds_json = os.getenv('GOOGLE_CREDENTIALS')
        
        if creds_json:
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)
        else:
            creds = Credentials.from_service_account_file('credentials.json', scopes=SCOPE)
        
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)
        
        # Buscar la hoja "Inscripciones", si no existe crearla
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
            encabezados = ['ID', 'Nombre', 'Email', 'Teléfono', 'Clases', 
                          'Tutor', 'Tel. Tutor', 'Email Tutor', 
                          'Acepta Términos', 'Autoriza Imagen', 'Firma', 'Fecha Registro']
            ws.append_row(encabezados)
    except Exception as e:
        print(f"Error creando hoja: {e}")

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
        
        # Obtener siguiente ID
        id_registro = ws.row_count + 1
        
        # La firma viene como base64
        firma_base64 = datos.get('firma', '')
        
        # Las clases vienen como lista, convertir a string separado por comas
        clases = ', '.join(datos.get('clases', []))
        
        fila = [
            id_registro,
            datos['nombre'],
            datos['email'],
            datos['telefono'],
            clases,
            datos.get('tutor_nombre', ''),
            datos.get('tutor_telefono', ''),
            datos.get('tutor_email', ''),
            'Sí' if datos.get('acepta_terminos') else 'No',
            'Sí' if datos.get('autoriza_imagen') else 'No',
            firma_base64,
            datetime.now().strftime('%d/%m/%Y %H:%M')
        ]
        
        ws.append_row(fila)
        
        return jsonify({'success': True, 'mensaje': '¡Inscripción registrada correctamente!'})
    except Exception as e:
        print(f"Error guardando: {e}")
        return jsonify({'success': False, 'error': str(e)})

if __name__ == '__main__':
    crear_hoja_si_no_existe()
    app.run(debug=False)