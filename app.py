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

# ---------------------------------------------------------
# CONFIGURACIÓN DE GOOGLE SHEETS
# ---------------------------------------------------------

SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
]

SPREADSHEET_ID = os.getenv(
    "SPREADSHEET_ID",
    "114L--j0CQW9yikCx7fn04xDPX89il5nWS7tr7z4Scko",
)

# Las columnas de cada clase se añadirán automáticamente
# después de estas columnas.
ENCABEZADOS_BASE = [
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


# ---------------------------------------------------------
# FUNCIONES GENERALES
# ---------------------------------------------------------

def normalizar(valor):
    """Normaliza texto para realizar comparaciones."""
    return str(valor or "").strip().casefold()


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
                cols=len(ENCABEZADOS_BASE),
            )

        encabezados_actuales = worksheet.row_values(1)

        if not encabezados_actuales:
            worksheet.append_row(
                ENCABEZADOS_BASE,
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


def obtener_mapa_encabezados(encabezados):
    """
    Devuelve un diccionario con el nombre normalizado
    del encabezado y su posición.
    """
    return {
        normalizar(encabezado): posicion
        for posicion, encabezado in enumerate(encabezados)
    }


def obtener_valor_fila(fila, mapa_encabezados, encabezado):
    """Obtiene el valor de una fila utilizando el nombre de la columna."""
    posicion = mapa_encabezados.get(normalizar(encabezado))

    if posicion is None or posicion >= len(fila):
        return ""

    return fila[posicion]


# ---------------------------------------------------------
# COLUMNAS DINÁMICAS PARA LAS CLASES
# ---------------------------------------------------------

def asegurar_columnas_clases(worksheet, clases):
    """
    Crea automáticamente una columna por cada clase nueva.

    Las columnas se añaden al final de Google Sheets.
    Las filas anteriores se inicializan con No.
    """
    encabezados = worksheet.row_values(1)

    if not encabezados:
        encabezados = ENCABEZADOS_BASE.copy()

        worksheet.append_row(
            encabezados,
            value_input_option="USER_ENTERED",
        )

    encabezados_normalizados = {
        normalizar(encabezado)
        for encabezado in encabezados
    }

    clases_nuevas = []

    for clase in clases:
        nombre_clase = str(clase or "").strip()

        if not nombre_clase:
            continue

        if normalizar(nombre_clase) not in encabezados_normalizados:
            clases_nuevas.append(nombre_clase)
            encabezados.append(nombre_clase)
            encabezados_normalizados.add(normalizar(nombre_clase))

    if not clases_nuevas:
        return encabezados

    columnas_anteriores = len(encabezados) - len(clases_nuevas)
    columnas_necesarias = len(encabezados)

    if worksheet.col_count < columnas_necesarias:
        worksheet.add_cols(
            columnas_necesarias - worksheet.col_count
        )

    ultima_celda_encabezado = gspread.utils.rowcol_to_a1(
        1,
        columnas_necesarias,
    )

    worksheet.update(
        range_name=f"A1:{ultima_celda_encabezado}",
        values=[encabezados],
        value_input_option="USER_ENTERED",
    )

    # Inicializar con "No" las nuevas columnas para registros anteriores.
    numero_filas = len(worksheet.get_all_values())

    if numero_filas > 1:
        primera_columna_nueva = columnas_anteriores + 1
        ultima_columna_nueva = columnas_necesarias

        celda_inicial = gspread.utils.rowcol_to_a1(
            2,
            primera_columna_nueva,
        )

        celda_final = gspread.utils.rowcol_to_a1(
            numero_filas,
            ultima_columna_nueva,
        )

        valores_no = [
            ["No"] * len(clases_nuevas)
            for _ in range(numero_filas - 1)
        ]

        worksheet.update(
            range_name=f"{celda_inicial}:{celda_final}",
            values=valores_no,
            value_input_option="USER_ENTERED",
        )

    print(
        "[SHEETS] Nuevas columnas de clases creadas: "
        f"{', '.join(clases_nuevas)}",
        flush=True,
    )

    return encabezados


def construir_fila(
    encabezados,
    id_registro,
    nombre,
    email,
    telefono,
    clases,
    tutor_nombre,
    tutor_telefono,
    tutor_email,
    datos,
):
    """
    Construye una fila respetando el orden actual de las columnas.

    En la columna correspondiente a cada clase guarda Sí o No.
    """
    fecha_actual = datetime.now().strftime("%d/%m/%Y %H:%M")

    clases_normalizadas = {
        normalizar(clase)
        for clase in clases
        if str(clase or "").strip()
    }

    valores_base = {
        "id": id_registro,
        "nombre": nombre,
        "email": email,
        "teléfono": telefono,
        "telefono": telefono,
        "clases": ", ".join(
            str(clase).strip()
            for clase in clases
            if str(clase or "").strip()
        ),
        "tutor": tutor_nombre,
        "tel. tutor": tutor_telefono,
        "email tutor": tutor_email,
        "acepta términos": (
            "Sí" if datos.get("acepta_terminos") else "No"
        ),
        "acepta terminos": (
            "Sí" if datos.get("acepta_terminos") else "No"
        ),
        "autoriza imagen": (
            "Sí" if datos.get("autoriza_imagen") else "No"
        ),
        "firma": datos.get("firma", ""),
        "fecha registro": fecha_actual,
    }

    encabezados_base_normalizados = {
        normalizar(encabezado)
        for encabezado in ENCABEZADOS_BASE
    }

    fila = []

    for encabezado in encabezados:
        encabezado_normalizado = normalizar(encabezado)

        if encabezado_normalizado in valores_base:
            fila.append(
                valores_base[encabezado_normalizado]
            )

        elif encabezado_normalizado in encabezados_base_normalizados:
            fila.append("")

        elif encabezado_normalizado in clases_normalizadas:
            fila.append("Sí")

        else:
            # Es una clase que no ha sido seleccionada.
            fila.append("No")

    return fila


# ---------------------------------------------------------
# ACTUALIZACIÓN DE INSCRIPCIONES
# ---------------------------------------------------------

def buscar_fila_existente(filas, encabezados, datos):
    """
    Busca una inscripción existente.

    Mayor:
        Se identifica por el email del alumno.

    Menor:
        Se identifica por el nombre del alumno y email del tutor.

    Devuelve el número real de fila en Google Sheets.
    """
    if len(filas) <= 1:
        return None

    mapa_encabezados = obtener_mapa_encabezados(encabezados)

    edad = normalizar(datos.get("edad"))
    nombre = normalizar(datos.get("nombre"))
    email = normalizar(datos.get("email"))
    tutor_email = normalizar(datos.get("tutor_email"))

    es_menor = edad in {
        "menor",
        "menor de edad",
    }

    for numero_fila, fila in enumerate(filas[1:], start=2):
        nombre_guardado = normalizar(
            obtener_valor_fila(
                fila,
                mapa_encabezados,
                "Nombre",
            )
        )

        email_guardado = normalizar(
            obtener_valor_fila(
                fila,
                mapa_encabezados,
                "Email",
            )
        )

        tutor_email_guardado = normalizar(
            obtener_valor_fila(
                fila,
                mapa_encabezados,
                "Email Tutor",
            )
        )

        if es_menor:
            if (
                nombre
                and tutor_email
                and nombre == nombre_guardado
                and tutor_email == tutor_email_guardado
            ):
                return numero_fila

        else:
            if email and email == email_guardado:
                return numero_fila

            # Compatibilidad si no se recibió correctamente la edad.
            if (
                not email
                and nombre
                and tutor_email
                and nombre == nombre_guardado
                and tutor_email == tutor_email_guardado
            ):
                return numero_fila

    return None


def obtener_siguiente_id(filas, encabezados):
    """Obtiene el siguiente ID numérico disponible."""
    if not filas:
        return 1

    mapa_encabezados = obtener_mapa_encabezados(encabezados)
    ids_existentes = []

    for fila in filas[1:]:
        valor_id = obtener_valor_fila(
            fila,
            mapa_encabezados,
            "ID",
        )

        try:
            ids_existentes.append(int(valor_id))
        except (ValueError, TypeError):
            continue

    return max(ids_existentes, default=0) + 1


def obtener_id_existente(
    filas,
    encabezados,
    numero_fila,
):
    """Obtiene el ID de una inscripción existente."""
    mapa_encabezados = obtener_mapa_encabezados(encabezados)

    try:
        fila = filas[numero_fila - 1]

        valor_id = obtener_valor_fila(
            fila,
            mapa_encabezados,
            "ID",
        )

        return int(valor_id)

    except (ValueError, TypeError, IndexError):
        return numero_fila - 1


# ---------------------------------------------------------
# ENVÍO DE CORREO MEDIANTE BREVO
# ---------------------------------------------------------

def enviar_confirmacion(
    email,
    nombre,
    clases,
    datos,
    actualizada=False,
):
    """Envía el correo mediante la API HTTPS de Brevo."""
    api_key = os.getenv("BREVO_API_KEY")
    remitente_email = os.getenv("MAIL_SENDER_EMAIL")
    remitente_nombre = os.getenv(
        "MAIL_SENDER_NAME",
        "Bailando Soñarás",
    )

    if not api_key:
        print(
            "[EMAIL] Falta BREVO_API_KEY",
            flush=True,
        )
        return False

    if not remitente_email:
        print(
            "[EMAIL] Falta MAIL_SENDER_EMAIL",
            flush=True,
        )
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

    fecha_actual = datetime.now().strftime("%d/%m/%Y %H:%M")

    if actualizada:
        titulo = "✓ ¡Inscripción actualizada!"
        asunto = "Actualización de inscripción - Bailando Soñarás"
        texto_principal = (
            "Hemos actualizado correctamente los datos "
            "de tu inscripción."
        )
    else:
        titulo = "✓ ¡Inscripción confirmada!"
        asunto = "Confirmación de inscripción - Bailando Soñarás"
        texto_principal = (
            "Gracias por inscribirte en Bailando Soñarás. "
            "Hemos recibido correctamente tu solicitud."
        )

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
                    {titulo}
                </h2>

                <p>
                    Hola <strong>{nombre_seguro}</strong>,
                </p>

                <p>{texto_principal}</p>

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
                        <strong>Email:</strong>
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
                        <strong>Fecha:</strong>
                        {fecha_actual}
                    </p>
                </div>

                <p style="margin-top: 30px;">
                    En breve nos pondremos en contacto contigo
                    para facilitarte más información.
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
            f"[EMAIL] Error conectando con Brevo: {error}",
            flush=True,
        )
        traceback.print_exc()
        return False


# ---------------------------------------------------------
# RUTAS
# ---------------------------------------------------------

@app.route("/")
def formulario():
    return render_template("formulario.html")


@app.route("/guardar", methods=["POST"])
def guardar():
    try:
        datos = request.get_json(silent=True) or {}

        edad = normalizar(datos.get("edad"))
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

        clases = [
            str(clase).strip()
            for clase in clases
            if str(clase or "").strip()
        ]

        # -------------------------------------------------
        # VALIDACIONES
        # -------------------------------------------------

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

        es_menor = edad in {
            "menor",
            "menor de edad",
        }

        if es_menor and not tutor_email:
            return jsonify({
                "success": False,
                "error": "El email del tutor es obligatorio.",
            }), 400

        if not es_menor and not email:
            return jsonify({
                "success": False,
                "error": "El email del alumno es obligatorio.",
            }), 400

        email_destino = tutor_email if es_menor else email

        if not email_destino:
            email_destino = email or tutor_email

        # -------------------------------------------------
        # CONEXIÓN CON GOOGLE SHEETS
        # -------------------------------------------------

        worksheet = conectar_sheets()

        if worksheet is None:
            return jsonify({
                "success": False,
                "error": (
                    "No se pudo conectar con Google Sheets."
                ),
            }), 500

        # Crear las columnas nuevas de clases.
        encabezados = asegurar_columnas_clases(
            worksheet,
            clases,
        )

        filas = worksheet.get_all_values()

        # -------------------------------------------------
        # BUSCAR SI YA EXISTE
        # -------------------------------------------------

        numero_fila_existente = buscar_fila_existente(
            filas,
            encabezados,
            datos,
        )

        registro_actualizado = (
            numero_fila_existente is not None
        )

        if registro_actualizado:
            id_registro = obtener_id_existente(
                filas,
                encabezados,
                numero_fila_existente,
            )
        else:
            id_registro = obtener_siguiente_id(
                filas,
                encabezados,
            )

        # -------------------------------------------------
        # CONSTRUIR LA FILA
        # -------------------------------------------------

        fila_nueva = construir_fila(
            encabezados=encabezados,
            id_registro=id_registro,
            nombre=nombre,
            email=email,
            telefono=telefono,
            clases=clases,
            tutor_nombre=tutor_nombre,
            tutor_telefono=tutor_telefono,
            tutor_email=tutor_email,
            datos=datos,
        )

        # -------------------------------------------------
        # ACTUALIZAR O INSERTAR
        # -------------------------------------------------

        if registro_actualizado:
            ultima_celda = gspread.utils.rowcol_to_a1(
                numero_fila_existente,
                len(encabezados),
            )

            worksheet.update(
                range_name=(
                    f"A{numero_fila_existente}:"
                    f"{ultima_celda}"
                ),
                values=[fila_nueva],
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

        # -------------------------------------------------
        # ENVIAR CORREO
        # -------------------------------------------------

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


# ---------------------------------------------------------
# EJECUCIÓN LOCAL
# ---------------------------------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
    )