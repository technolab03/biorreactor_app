from pymongo import MongoClient
import os
import pytz

# Conversión centralizada a horario chileno
def convertir_a_chile(fecha_utc):
    if fecha_utc is None:
        return None
    chile_tz = pytz.timezone("America/Santiago")
    if fecha_utc.tzinfo is None:
        fecha_utc = fecha_utc.replace(tzinfo=pytz.utc)
    return fecha_utc.astimezone(chile_tz)

def obtener_datos(dominio='dominio_ucn', limit=5000):
    # Usar variable de entorno "MONGO_URI" para conectarse a MongoDB, si no se encuentra la variable, lanza un error
    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri:
        raise RuntimeError("❌ No se encontró la variable de entorno MONGO_URI")
    
    # Conectarse a la base de datos, y seleccionar la colección al dominio pasado por parámetro o por defecto "dominio_ucn"
    client = MongoClient(mongo_uri)
    db = client["biorreactor_app"]
    collection = db[dominio]
    
    # Consultar los documentos desde MongoDB ordenados por campo "tiempo" de más reciente a más antiguo (por defecto 5000)
    cursor = collection.find().sort("tiempo", -1).limit(limit)
    datos = []

    # Iterar los documentos obtenidos, convirtiendo la hora UTC a hora de Chile usando la función convertir_a_chile()
    # Extraer y guardar los valores en un diccionario
    for doc in cursor:
        tiempo_chile = convertir_a_chile(doc.get("tiempo"))
        datos.append({
            'tiempo': tiempo_chile.strftime('%Y-%m-%d %H:%M:%S'),
            'id_dispositivo': doc.get('id_dispositivo'),
            'temperatura': doc.get('temperatura'),
            'ph': doc.get('ph'),
            'oxigeno': doc.get('oxigeno'),
            'turbidez': doc.get('turbidez'),
            'conductividad': doc.get('conductividad')
        })

    # Cierra la conexión a la base de datos, e invierte el orden de los datos para que queden del más antiguo al más reciente y los retorna
    client.close()
    return list(reversed(datos))

def obtener_registro_comida(limit=5000):
    # Usar variable de entorno "MONGO_URI" para conectarse a MongoDB, si no se encuentra la variable, lanza un error
    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri:
        raise RuntimeError("❌ No se encontró la variable de entorno MONGO_URI")
    
    # Conectarse a la base de datos, y seleccionar la colección llamada "registro_comida", que guarda los eventos de alimentación
    client = MongoClient(mongo_uri)
    db = client["biorreactor_app"]
    collection = db["registro_comida"]

    # Consultar todos los documentos de esa colección, ordenados por "tiempo" de más nuevo más antiguo (Con límite de 5000 por defecto)
    cursor = collection.find().sort("tiempo", -1).limit(limit)
    registros = []

    # Iterar los documentos, convirtiendo la hora a la zona horaria de Chile
    for doc in cursor:
        tiempo = convertir_a_chile(doc.get("tiempo"))
        # Extraer el "id_dispositivo". Si no existe, pone "Desconocido"
        id_dispositivo = doc.get("id_dispositivo", "Desconocido")
        # Agrega los datos formateados a una lista "registros"
        registros.append({
            'tiempo': tiempo.strftime('%Y-%m-%d %H:%M:%S') if tiempo else "Sin tiempo",
            'id_dispositivo': id_dispositivo
        })

    # Cierra la conexión a la base de datos, e invierte el orden del más antiguo al más reciente y los retorna
    client.close()
    return list(reversed(registros))
