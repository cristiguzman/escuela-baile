from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo
import json
import os
import traceback

import gspread
import requests
from flask import Flask, jsonify, render_template, request
from google.oauth2.service_account import Credentials


app = Flask(__name__)

# Configuración de Google Sheets
SCOPE = ["https://www.googleapis.com/auth/spreadsheets"]

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

if not SPREADSHEET_ID:
    raise RuntimeError(
        "Falta la variable de entorno SPREADSHEET_ID"
    )

ENCABEZADOS = [
    "ID",
    "Nombre",
    "DNI/NIE",
    "Email",
    "Teléfono",
    "Clases",
    "Tutor",
    "DNI/NIE Tutor",
    "Tel. Tutor",
    "Email Tutor",
    "Acepta Información",
    "Autoriza Comunicaciones",
    "Autoriza Imagen",
    "Autoriza Web",
    "Firma",
    "Fecha Registro",
]


ZONA_HORARIA = ZoneInfo("Europe/Madrid")


def fecha_actual():
    """Devuelve la fecha y hora actuales de España."""
    return datetime.now(ZONA_HORARIA).strftime(
        "%d/%m/%Y %H:%M"
    )


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

        # Añadir encabezados si la hoja está vacía.
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


def normalizar(valor):
    """Normaliza un texto para poder compararlo."""
    return str(valor or "").strip().casefold()


def buscar_fila_existente(filas, datos):
    """
    Busca una inscripción existente.

    Mayor:
        Se identifica por el email del alumno.

    Menor:
        Se identifica por el nombre del alumno y el email del tutor.

    Devuelve el número real de fila de Google Sheets o None.
    """
    edad = normalizar(datos.get("edad"))
    nombre = normalizar(datos.get("nombre"))
    email = normalizar(datos.get("email"))
    tutor_email = normalizar(datos.get("tutor_email"))

    # Se omite la primera fila porque contiene los encabezados.
    for numero_fila, fila in enumerate(filas[1:], start=2):
        fila_completa = fila + [""] * (
            len(ENCABEZADOS) - len(fila)
        )

        nombre_guardado = normalizar(fila_completa[1])
        email_guardado = normalizar(fila_completa[2])
        tutor_email_guardado = normalizar(
            fila_completa[7]
        )

        if edad == "mayor":
            if email and email == email_guardado:
                return numero_fila

        elif edad == "menor":
            if (
                nombre
                and nombre == nombre_guardado
                and tutor_email
                and tutor_email == tutor_email_guardado
            ):
                return numero_fila

    return None


def obtener_siguiente_id(filas):
    """Obtiene el siguiente ID disponible."""
    ids_existentes = []

    for fila in filas[1:]:
        try:
            ids_existentes.append(int(fila[0]))
        except (ValueError, TypeError, IndexError):
            continue

    return max(ids_existentes, default=0) + 1


def enviar_confirmacion(
    email,
    nombre,
    clases,
    datos,
    actualizada=False,
):
    """
    Envía el correo de confirmación mediante la API HTTPS de Brevo.
    """
    api_key = os.getenv("BREVO_API_KEY")
    remitente_email = os.getenv("MAIL_SENDER_EMAIL")
    remitente_nombre = os.getenv(
        "MAIL_SENDER_NAME",
        "Bailando Soñarás",
    )

    if not api_key:
        print(
            "[EMAIL] Falta la variable BREVO_API_KEY",
            flush=True,
        )
        return False

    if not remitente_email:
        print(
            "[EMAIL] Falta la variable MAIL_SENDER_EMAIL",
            flush=True,
        )
        return False

    es_menor = normalizar(datos.get("edad")) == "menor"

    # Datos sin escapar para Brevo.
    tutor_nombre_original = str(
        datos.get("tutor_nombre") or ""
    ).strip()

    if es_menor and tutor_nombre_original:
        nombre_destinatario = tutor_nombre_original
    else:
        nombre_destinatario = nombre

    # Datos escapados para introducirlos de forma segura en el HTML.
    nombre_seguro = escape(str(nombre))

    email_alumno_seguro = escape(
        str(datos.get("email") or "No indicado")
    )

    telefono_alumno_seguro = escape(
        str(datos.get("telefono") or "No indicado")
    )

    tutor_nombre_seguro = escape(
        str(datos.get("tutor_nombre") or "No indicado")
    )

    tutor_email_seguro = escape(
        str(datos.get("tutor_email") or "No indicado")
    )

    tutor_telefono_seguro = escape(
        str(datos.get("tutor_telefono") or "No indicado")
    )

    if clases:
        clases_html = "".join(
            f"• {escape(str(clase))}<br>"
            for clase in clases
        )
    else:
        clases_html = "No se seleccionaron clases"

    fecha_registro = fecha_actual()

    if actualizada:
        titulo = "✓ ¡Inscripción actualizada!"
        texto_principal = (
            "Hemos actualizado correctamente los datos "
            "de la inscripción."
        )
        asunto = (
            "Actualización de inscripción - Bailando Soñarás"
        )
    else:
        titulo = "✓ ¡Inscripción confirmada!"
        texto_principal = (
            "Gracias por inscribirte en Bailando Soñarás. "
            "Hemos recibido correctamente la solicitud."
        )
        asunto = (
            "Confirmación de inscripción - Bailando Soñarás"
        )

    if es_menor:
        saludo = (
            f"Hola <strong>{tutor_nombre_seguro}</strong>,"
        )

        texto_alumno = (
            f"Hemos recibido la inscripción de "
            f"<strong>{nombre_seguro}</strong>."
        )

        contacto_alumno_html = ""

        datos_tutor_html = f"""
            <h3 style="
                color: #667eea;
                margin-top: 25px;
                margin-bottom: 12px;
            ">
                Datos del tutor o responsable
            </h3>

            <div style="
                padding: 15px;
                background-color: #f9f9f9;
                border-left: 4px solid #667eea;
                border-radius: 5px;
            ">
                <p>
                    <strong>Nombre del tutor:</strong>
                    {tutor_nombre_seguro}
                </p>

                <p>
                    <strong>Email del tutor:</strong>
                    {tutor_email_seguro}
                </p>

                <p>
                    <strong>Teléfono del tutor:</strong>
                    {tutor_telefono_seguro}
                </p>
            </div>
        """
    else:
        saludo = (
            f"Hola <strong>{nombre_seguro}</strong>,"
        )

        texto_alumno = ""

        contacto_alumno_html = f"""
            <p>
                <strong>Email:</strong>
                {email_alumno_seguro}
            </p>

            <p>
                <strong>Teléfono:</strong>
                {telefono_alumno_seguro}
            </p>
        """

        datos_tutor_html = ""

    cuerpo_html = f"""
    <!DOCTYPE html>
    <html lang="es">
        <head>
            <meta charset="UTF-8">
        </head>

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
                    {titulo}
                </h2>

                <p>{saludo}</p>

                <p>{texto_principal}</p>

                {
                    f"<p>{texto_alumno}</p>"
                    if texto_alumno
                    else ""
                }

                <h3 style="
                    color: #667eea;
                    margin-top: 25px;
                    margin-bottom: 12px;
                ">
                    Datos del alumno
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

                    {contacto_alumno_html}

                    <p>
                        <strong>Clases seleccionadas:</strong><br>
                        {clases_html}
                    </p>

                    <p>
                        <strong>Fecha:</strong>
                        {fecha_registro}
                    </p>
                </div>

                {datos_tutor_html}

                <p style="margin-top: 30px;">
                    En breve nos pondremos en contacto para
                    facilitar más información.
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
                "name": nombre_destinatario,
            }
        ],
        "subject": asunto,
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
                f"[EMAIL] Brevo respondió "
                f"{response.status_code}: {response.text}",
                flush=True,
            )
            return False

        print(
            f"[EMAIL] Correo aceptado por Brevo: "
            f"{response.text}",
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
    """Muestra el formulario de inscripción."""
    return render_template("formulario.html")


@app.route("/registro-correcto")
def registro_correcto():
    """Muestra la página de confirmación."""
    return render_template("registro_correcto.html")


@app.route("/guardar", methods=["POST"])
def guardar():
    """Guarda o actualiza una inscripción."""
    try:
        datos = request.get_json(silent=True) or {}

        edad = normalizar(datos.get("edad"))
        nombre = str(datos.get("nombre", "")).strip()
        email = str(datos.get("email", "")).strip()
        telefono = str(
            datos.get("telefono", "")
        ).strip()

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

        # Validaciones
        if edad not in ("mayor", "menor"):
            return jsonify({
                "success": False,
                "error": (
                    "Selecciona si el alumno es mayor o menor."
                ),
            }), 400

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
                "error": (
                    "Debes aceptar los términos y condiciones."
                ),
            }), 400

        if not datos.get("firma"):
            return jsonify({
                "success": False,
                "error": "La firma digital es obligatoria.",
            }), 400

        if edad == "mayor":
            if not email:
                return jsonify({
                    "success": False,
                    "error": (
                        "El email del alumno es obligatorio."
                    ),
                }), 400

            if not telefono:
                return jsonify({
                    "success": False,
                    "error": (
                        "El teléfono del alumno es obligatorio."
                    ),
                }), 400

            email_destino = email

        else:
            if not tutor_nombre:
                return jsonify({
                    "success": False,
                    "error": (
                        "El nombre del tutor es obligatorio."
                    ),
                }), 400

            if not tutor_email:
                return jsonify({
                    "success": False,
                    "error": (
                        "El email del tutor es obligatorio."
                    ),
                }), 400

            if not tutor_telefono:
                return jsonify({
                    "success": False,
                    "error": (
                        "El teléfono del tutor es obligatorio."
                    ),
                }), 400

            email_destino = tutor_email

        worksheet = conectar_sheets()

        if worksheet is None:
            return jsonify({
                "success": False,
                "error": (
                    "No se pudo conectar con Google Sheets."
                ),
            }), 500

        filas = worksheet.get_all_values()

        numero_fila_existente = buscar_fila_existente(
            filas,
            datos,
        )

        registro_actualizado = (
            numero_fila_existente is not None
        )

        if registro_actualizado:
            fila_anterior = filas[
                numero_fila_existente - 1
            ]

            try:
                id_registro = int(fila_anterior[0])
            except (
                ValueError,
                TypeError,
                IndexError,
            ):
                id_registro = numero_fila_existente - 1
        else:
            id_registro = obtener_siguiente_id(filas)

        fecha_registro = fecha_actual()

        fila_nueva = [
            id_registro,
            nombre,
            datos.get("dni", ""),
            email,
            telefono,
            ", ".join(
                str(clase)
                for clase in clases
            ),
            tutor_nombre,
            datos.get("dni_tutor", ""),
            tutor_telefono,
            tutor_email,
            (
                "Sí"
                if datos.get("acepta_terminos")
                else "No"
            ),
            (
                "Sí"
                if datos.get("autoriza_comunicaciones")
                else "No"
            ),
            (
                "Sí"
                if datos.get("autoriza_imagen")
                else "No"
            ),
            (
                "Sí"
                if datos.get("autoriza_web")
                else "No"
            ),
            datos.get("firma", ""),
            fecha_registro,
        ]


        if registro_actualizado:
            worksheet.update(
                [fila_nueva],
                f"A{numero_fila_existente}:P{numero_fila_existente}",
                value_input_option="USER_ENTERED",
            )


            print(
                f"[GUARDAR] Inscripción actualizada. "
                f"ID: {id_registro}. "
                f"Fila: {numero_fila_existente}",
                flush=True,
            )
        else:
            worksheet.append_row(
                fila_nueva,
                value_input_option="USER_ENTERED",
            )

            print(
                f"[GUARDAR] Nueva inscripción. "
                f"ID: {id_registro}",
                flush=True,
            )

        correo_enviado = enviar_confirmacion(
            email=email_destino,
            nombre=nombre,
            clases=clases,
            datos=datos,
            actualizada=registro_actualizado,
        )

        if registro_actualizado:
            if correo_enviado:
                mensaje = (
                    "¡Inscripción actualizada correctamente! "
                    "El correo de confirmación ha sido aceptado "
                    "para su envío."
                )
            else:
                mensaje = (
                    "La inscripción se ha actualizado, pero no "
                    "se pudo enviar el correo de confirmación."
                )
        else:
            if correo_enviado:
                mensaje = (
                    "¡Inscripción registrada correctamente! "
                    "El correo de confirmación ha sido aceptado "
                    "para su envío."
                )
            else:
                mensaje = (
                    "La inscripción se ha registrado, pero no "
                    "se pudo enviar el correo de confirmación."
                )

        return jsonify({
            "success": True,
            "mensaje": mensaje,
            "correo_enviado": correo_enviado,
            "registro_actualizado": registro_actualizado,
            "id_registro": id_registro,
        })

    except Exception as error:
        print(
            f"[GUARDAR] Error: {error}",
            flush=True,
        )
        traceback.print_exc()

        return jsonify({
            "success": False,
            "error": (
                "Ocurrió un error procesando la inscripción."
            ),
        }), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )