import numpy as np
import pandas as pd
import onnxruntime as ort
from datetime import datetime, timedelta
from pathlib import Path
import joblib
from pymongo import MongoClient
import time
import threading
import os
import requests

# Configuración
SEQ_LEN = 48
BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "modelos"

# MongoDB
MONGO_URI = os.environ.get("MONGO_URI")
DB_NAME = "biorreactor_app"
COLECCION_DATOS = "dominio_terreno"
COLECCION_CLASIFICACIONES = "clasificaciones"
COLECCION_ESTADO = "estado_clasificacion"  # Guarda última fase

# Telegram
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

# Modelo GRU
GRU_MODEL_PATH = MODELS_DIR / "gru_48.onnx"
SESSION_GRU = ort.InferenceSession(str(GRU_MODEL_PATH))

# Escalador y label encoder
SCALER = joblib.load(MODELS_DIR / "robust_scaler.pkl")
LABEL_ENCODER = joblib.load(MODELS_DIR / "label_encoder.pkl")

# ====================================================
# ALERTAS TELEGRAM
# ====================================================
def enviar_alerta(mensaje):
    if not BOT_TOKEN or not CHAT_ID:
        print("⚠️ No se enviaron alertas (faltan BOT_TOKEN o CHAT_ID)")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": mensaje, "parse_mode": "Markdown"},
            timeout=5
        )
        print(f"📨 Alerta enviada: {mensaje}")
    except Exception as e:
        print(f"❌ Error enviando alerta Telegram: {e}")

# ====================================================
# FUNCIONES AUXILIARES
# ====================================================
def preparar_secuencia(df):
    """Prepara la secuencia para GRU (48 filas × features)"""
    if len(df) < SEQ_LEN:
        return None, f"No hay suficientes datos (se necesitan {SEQ_LEN})"

    df = df.sort_values("tiempo")
    df["hora"] = df["tiempo"].dt.hour + df["tiempo"].dt.minute / 60
    df["hora_sin"] = np.sin(2 * np.pi * df["hora"] / 24)
    df["hora_cos"] = np.cos(2 * np.pi * df["hora"] / 24)

    features = ["ph", "oxigeno", "hora_sin", "hora_cos"]
    seq = df.tail(SEQ_LEN)[features]

    if seq.isna().any().any():
        return None, "Secuencia con valores nulos"

    return SCALER.transform(seq.to_numpy())[np.newaxis, :, :].astype(np.float32), None

def clasificar_fase(df):
    """Ejecuta modelo GRU y devuelve fase y probabilidades"""
    input_seq, error = preparar_secuencia(df)
    if error:
        return None, None, error

    input_name = SESSION_GRU.get_inputs()[0].name
    output = SESSION_GRU.run(None, {input_name: input_seq})[0].flatten()
    clase = int(np.argmax(output))

    try:
        fase = LABEL_ENCODER.inverse_transform([clase])[0]
    except:
        fase = str(clase)

    return fase, output.tolist(), None

# ====================================================
# SERVICIO PRINCIPAL
# ====================================================
def servicio_clasificaciones():
    """Ejecuta clasificaciones GRU por dispositivo y actualiza MongoDB"""
    try:
        print(f"\n[{datetime.utcnow()}] 🔄 Ejecutando clasificaciones...")

        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        col_datos = db[COLECCION_DATOS]
        col_clasificacion = db[COLECCION_CLASIFICACIONES]
        col_estado = db[COLECCION_ESTADO]

        dispositivos = col_datos.distinct("id_dispositivo")
        if not dispositivos:
            print("⚠️ No hay dispositivos en la base de datos.")
            return

        for disp in dispositivos:
            cursor = col_datos.find(
                {"id_dispositivo": disp, "tiempo": {"$gte": datetime.utcnow() - timedelta(hours=48)}}
            ).sort("tiempo", 1)
            df = pd.DataFrame(list(cursor))
            if df.empty:
                print(f"⚠️ Sin datos recientes para {disp}")
                continue

            df["tiempo"] = pd.to_datetime(df["tiempo"])
            fase, proba, error = clasificar_fase(df)
            if error:
                print(f"❌ Error clasificación GRU ({disp}): {error}")
                continue

            # Leer fase anterior
            doc_estado = col_estado.find_one({"id_dispositivo": disp})
            fase_anterior = doc_estado["fase_actual"] if doc_estado else None

            # Guardar clasificación histórica
            col_clasificacion.insert_one({
                "id_dispositivo": disp,
                "fase": fase,
                "proba": proba,
                "timestamp": datetime.utcnow()
            })

            # Enviar alerta si hay cambio de fase
            if fase_anterior and fase_anterior != fase:
                mensaje = (
                    f"🔔 *Cambio de fase detectado*\n"
                    f"Dispositivo: `{disp}`\n"
                    f"Antes: `{fase_anterior}`\n"
                    f"Ahora: *{fase}*\n"
                    f"🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
                )
                enviar_alerta(mensaje)

            # Actualizar estado
            col_estado.update_one(
                {"id_dispositivo": disp},
                {"$set": {"fase_actual": fase, "fecha": datetime.utcnow()}},
                upsert=True
            )

            print(f"🧪 {disp} → Fase: {fase} (antes: {fase_anterior})")

        print(f"[{datetime.utcnow()}] ✔️ Clasificaciones finalizadas.")

    except Exception as e:
        print(f"❌ Error en servicio_clasificaciones: {e}")

# ====================================================
# EJECUCIÓN AUTOMÁTICA CADA HORA
# ====================================================
def iniciar_hilo(interval_minutes=60):
    def tarea():
        print(f"🧵 Hilo iniciado, clasificaciones cada {interval_minutes} min...")
        time.sleep(2)
        while True:
            servicio_clasificaciones()
            time.sleep(interval_minutes * 60)

    hilo = threading.Thread(target=tarea, daemon=True)
    hilo.start()
    print("✔️ Hilo de clasificaciones ejecutándose en segundo plano.")
    return hilo

# Para arrancar el hilo automáticamente
if __name__ == "__main__":
    iniciar_hilo(interval_minutes=60)
