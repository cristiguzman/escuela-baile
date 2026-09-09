from datetime import datetime
from html import escape
import json
import os
import traceback

import gspread
import requests
from flask import Flask, jsonify, render_template, request
from google.oauth2.service_account import Credentials


app = Flask(__name__)

# Google Sheets
SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = os.getenv(
    "SPREADSHEET_ID",
    "114L--j0CQW9yikCx7fn04xDPX89il5nWS7tr7z4Scko",
)

ENCABEZADOS = [
    "ID",
    "Nombre",
    "Email",
    "Teléfono",
    "Clases",
    "Tutor",
    "Tel. Tutor",
    "Email Tutor",
    "Acepta Términos",
    "Autoriza Imagen",
    "Firma",
    "Fecha Registro",
]


def conectar_sheets():
    """Conecta con Google Sheets y devuelve la hoja Inscripciones."""
    try:
        credentials_json = os.getenv("GOOGLE_CREDENTIALS")

        if credentials_json:
            credentials_dict = json.loads(credentials_json)
            credentials = Credentials.from_service_account_info(
                credentials_dict,
                scopes=SCOPE,
            )
        else:
            credentials = Credentials.from_service_account_file(
                "credentials.json",
                scopes=SCOPE,
            )

        client = gspread.authorize(credentials)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)

        try:
            worksheet = spreadsheet.worksheet("Inscripciones")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title="Inscripciones",
                rows=1000,
                cols=len(ENCABEZADOS),
            )

        # Crear encabezados si la hoja está vacía.
        if not worksheet.get_all_values():
            worksheet.append_row(
                ENCABEZADOS,
                value_input_option="USER_ENTERED",
            )

        return worksheet

    except Exception as error:
        print(
            f"[SHEETS] Error conectando con Google Sheets: {error}",
            flush=True,
        )
        traceback.print_exc()
        return None


def enviar_confirmacion(email, nombre, clases, datos):
    """Envía el correo mediante la API HTTPS de Brevo."""
    api_key = os.getenv("BREVO_API_KEY")
    remitente_email = os.getenv("MAIL_SENDER_EMAIL")
    remitente_nombre = os.getenv(
        "MAIL_SENDER_NAME",
        "Bailando Soñarás",
    )

    if not api_key:
        print("[EMAIL] Falta la variable BREVO_API_KEY", flush=True)
        return False

    if not remitente_email:
        print("[EMAIL] Falta la variable MAIL_SENDER_EMAIL", flush=True)
        return False

    nombre_seguro = escape(str(nombre))
    email_seguro = escape(str(email))

    telefono = (
        datos.get("telefono")
        or datos.get("tutor_telefono")
        or "No indicado"
    )
    telefono_seguro = escape(str(telefono))

    if clases:
        clases_html = "".join(
            f"• {escape(str(clase))}<br>"
            for clase in clases
        )
    else:
        clases_html = "No se seleccionaron clases"

    fecha_registro = datetime.now().strftime("%d/%m/%Y %H:%M")

    cuerpo_html = f"""
    <!DOCTYPE html>
    <html lang="es">
        <body style="
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
            font-family: Arial, sans-serif;
        ">
            <div style="
                max-width: 600px;
                margin: 0 auto;
                padding: 30px;
                background-color: white;
                border-radius: 10px;
            ">
                <h2 style="color: #667eea;">
                    ✓ ¡Inscripción confirmada!
                </h2>

                <p>Hola <strong>{nombre_seguro}</strong>,</p>

                <p>
                    Gracias por inscribirte en Bailando Soñarás.
                    Hemos recibido correctamente tu solicitud.
                </p>

                <h3 style="color: #667eea;">
                    Datos de la inscripción
                </h3>

                <div style="
                    padding: 15px;
                    background-color: #f9f9f9;
                    border-left: 4px solid #667eea;
                    border-radius: 5px;
                ">
                    <p>
                        <strong>Nombre:</strong>
                        {nombre_seguro}
                    </p>

                    <p>
                        <strong>Email de contacto:</strong>
                        {email_seguro}
                    </p>

                    <p>
                        <strong>Teléfono:</strong>
                        {telefono_seguro}
                    </p>

                    <p>
                        <strong>Clases seleccionadas:</strong><br>
                        {clases_html}
                    </p>

                    <p>
                        <strong>Fecha de registro:</strong>
                        {fecha_registro}
                    </p>
                </div>

                <p style="margin-top: 30px;">
                    En breve nos pondremos en contacto contigo para
                    facilitarte más información.
                </p>

                <p style="
                    margin-top: 30px;
                    color: #777;
                    font-size: 12px;
                ">
                    Este es un correo automático.
                </p>

                <hr style="
                    border: none;
                    border-top: 1px solid #ddd;
                ">

                <p style="
                    text-align: center;
                    color: #667eea;
                    font-weight: bold;
                ">
                    Bailando Soñarás
                </p>
            </div>
        </body>
    </html>
    """

    payload = {
        "sender": {
            "name": remitente_nombre,
            "email": remitente_email,
        },
        "to": [
            {
                "email": email,
                "name": nombre,
            }
        ],
        "subject": (
            "Confirmación de inscripción - Bailando Soñarás"
        ),
        "htmlContent": cuerpo_html,
    }

    try:
        print(
            f"[EMAIL] Enviando confirmación a {email}",
            flush=True,
        )

        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "api-key": api_key,
            },
            json=payload,
            timeout=15,
        )

        if not response.ok:
            print(
                f"[EMAIL] Brevo respondió {response.status_code}: "
                f"{response.text}",
                flush=True,
            )
            return False

        print(
            f"[EMAIL] Correo enviado correctamente: {response.text}",
            flush=True,
        )
        return True

    except requests.Timeout:
        print(
            "[EMAIL] Brevo tardó demasiado en responder",
            flush=True,
        )
        return False

    except requests.RequestException as error:
        print(
            f"[EMAIL] Error de conexión con Brevo: {error}",
            flush=True,
        )
        traceback.print_exc()
        return False


@app.route("/")
def formulario():
    return render_template("formulario.html")


@app.route("/guardar", methods=["POST"])
def guardar():
    try:
        datos = request.get_json(silent=True) or {}

        nombre = str(datos.get("nombre", "")).strip()
        email = str(datos.get("email", "")).strip()
        telefono = str(datos.get("telefono", "")).strip()
        tutor_nombre = str(
            datos.get("tutor_nombre", "")
        ).strip()
        tutor_email = str(
            datos.get("tutor_email", "")
        ).strip()
        tutor_telefono = str(
            datos.get("tutor_telefono", "")
        ).strip()

        clases = datos.get("clases", [])
        if not isinstance(clases, list):
            clases = []

        if not nombre:
            return jsonify({
                "success": False,
                "error": "El nombre es obligatorio.",
            }), 400

        if not clases:
            return jsonify({
                "success": False,
                "error": "Selecciona al menos una clase.",
            }), 400

        if not datos.get("acepta_terminos"):
            return jsonify({
                "success": False,
                "error": "Debes aceptar los términos y condiciones.",
            }), 400

        email_destino = email or tutor_email

        if not email_destino:
            return jsonify({
                "success": False,
                "error": "Es necesario indicar un correo electrónico.",
            }), 400

        worksheet = conectar_sheets()

        if worksheet is None:
            return jsonify({
                "success": False,
                "error": "No se pudo conectar con Google Sheets.",
            }), 500

        filas = worksheet.get_all_values()

        # La primera fila contiene los encabezados.
        id_registro = len(filas)

        fila = [
            id_registro,
            nombre,
            email,
            telefono,
            ", ".join(str(clase) for clase in clases),
            tutor_nombre,
            tutor_telefono,
            tutor_email,
            "Sí" if datos.get("acepta_terminos") else "No",
            "Sí" if datos.get("autoriza_imagen") else "No",
            datos.get("firma", ""),
            datetime.now().strftime("%d/%m/%Y %H:%M"),
        ]

        worksheet.append_row(
            fila,
            value_input_option="USER_ENTERED",
        )

        print(
            f"[GUARDAR] Registro guardado con ID: {id_registro}",
            flush=True,
        )

        correo_enviado = enviar_confirmacion(
            email=email_destino,
            nombre=nombre,
            clases=clases,
            datos=datos,
        )

        if correo_enviado:
            mensaje = (
                "¡Inscripción registrada correctamente! "
                "Se ha enviado el correo de confirmación."
            )
        else:
            mensaje = (
                "La inscripción se ha registrado, pero no se pudo "
                "enviar el correo de confirmación."
            )

        return jsonify({
            "success": True,
            "mensaje": mensaje,
            "correo_enviado": correo_enviado,
        })

    except Exception as error:
        print(
            f"[GUARDAR] Error: {error}",
            flush=True,
        )
        traceback.print_exc()

        return jsonify({
            "success": False,
            "error": "Ocurrió un error procesando la inscripción.",
        }), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )