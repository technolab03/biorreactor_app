from flask import Blueprint, request, jsonify, current_app
from datetime import datetime

main = Blueprint('main', __name__)

@main.route('/')
def index():
    return jsonify({"message": "API del biorreactor funcionando"})

@main.route('/api/sensores', methods=['POST'])
def recibir_datos():
    # Toma los datos en formato JSON que envía el cliente como el sensor IoT
    data = request.get_json()
    # Validar que venga el campo "dominio", si no se reciben datos o falta el campo "dominio", responde con error 400 (Bad Request)
    if not data or 'dominio' not in data:
        return jsonify({'error': 'Falta campo dominio'}), 400

    # Añadir un campo de tiempo con la hora en UTC y añade un identificador del dispositivo, si no existe se pone "Desconocido"
    data['tiempo'] = datetime.utcnow()
    data['id_dispositivo'] = data.get('id_dispositivo', 'desconocido')

    # Extraer el campo "dominio" del JSON y usar como nombre de colección en la base de datos
    dominio = data.pop('dominio')
    collection = current_app.mongo.db[dominio]

    # Inserta el documento completo, sin el campo "dominio" que se usó como nombre de la colección
    collection.insert_one(data)

    return jsonify({'message': f'Datos guardados en dominio {dominio}'}), 201

@main.route('/api/datos', methods=['GET'])
def obtener_datos():
    # Leer los parámetros que pasen en la URL como "dominio" e "id_dispositivo"
    dominio = request.args.get('dominio')
    id_dispositivo = request.args.get('id_dispositivo')

    # Validar si existe el parámetro "dominio"
    if not dominio:
        return jsonify({'error': 'Falta parámetro dominio'}), 400

    # Leer y validar el parámetro "limit", establece un límite máximo de registros (por defecto 200), evitando valores negativos o cero
    limit = request.args.get('limit', default=200, type=int)
    if limit <= 0:
        return jsonify({'error': 'El parámetro limit debe ser mayor que 0'}), 400

    # Verificar que el dominio exista en la base de datos, si no existe, devuelve el error 404 (Not Found)
    colecciones = current_app.mongo.db.list_collection_names()
    if dominio not in colecciones:
        return jsonify({'error': f'No existe la colección {dominio}'}), 404

    # Se apunta a la colección correspondiente
    collection = current_app.mongo.db[dominio]

    # Se arma el diccionario filtro solo si el usuario quiere consultar por un "id_dispositivo" específico
    filtro = {}
    if id_dispositivo:
        filtro['id_dispositivo'] = id_dispositivo

    # Realizar la consulta con el filtro y ordenar por tiempo descendente y limita el números según lo pedido
    cursor = collection.find(filtro).sort("tiempo", -1).limit(limit)
    datos = []

    # Iterar cada documento y extraer los campos deseados, convirtiendo el campo "tiempo" a una cadena en formato ISO (por compatibilidad con JSON) 
    for doc in cursor:
        tiempo = doc.get("tiempo")
        if isinstance(tiempo, datetime):
            tiempo_str = tiempo.isoformat() + "Z"
        else:
            tiempo_str = str(tiempo)

        datos.append({
            'tiempo': tiempo_str,
            'id_dispositivo': doc.get('id_dispositivo'),
            'temperatura': doc.get('temperatura'),
            'ph': doc.get('ph'),
            'oxigeno': doc.get('oxigeno'),
            'turbidez': doc.get('turbidez'),
            'conductividad': doc.get('conductividad')
        })

    # Invertir la lista para que los datos aparezcan en orden cronológico ascendente (más antiguos primero) y los devuelve como JSON
    return jsonify(list(reversed(datos)))

@main.route('/api/registro_comida', methods=['POST'])
def registrar_comida():
    # Recibir los datos JSON, esperar al cliente como Dashboard que envié un JSON con información del evento
    data = request.get_json()
    
    # Verificar que se haya recibido la información y que el campo "evento" exista y su valor sea "comida"
    if not data or data.get("evento") != "comida":
        return jsonify({'error': 'JSON inválido o evento incorrecto'}), 400

    # Agregar automáticamente la hora en que se registró el evento (UTC), y asegurar que haya un "id_dispositivo", si no se pone "Desconocido"
    data['tiempo'] = datetime.utcnow()
    data['id_dispositivo'] = data.get("id_dispositivo", "desconocido")

    # Conectar a la colección "registro_comida" y se guarda el documento
    collection = current_app.mongo.db.registro_comida
    collection.insert_one(data)

    # Devolver un mensaje de éxito (201 Created) 
    return jsonify({'message': 'Registro de comida guardado correctamente'}), 201

@main.route('/api/registro_comida', methods=['GET'])
def obtener_registros_comida():
    # Conectar a la colección "registro_comida" de la base de datos
    collection = current_app.mongo.db.registro_comida

    # Consultar hasta 200 registros, ordenados desde el más reciente al más antiguo
    cursor = collection.find().sort("tiempo", -1).limit(200)
    registros = []

    # Iterar los documentos, creando una lista registros para guardar cada documento en un diccionario
    for doc in cursor:
        tiempo = doc.get("tiempo")
        # Convertir el campo "tiempo" a formato ISO para asegurar compatibilidad con API
        if isinstance(tiempo, datetime):
            tiempo_str = tiempo.isoformat() + "Z"
        else:
            tiempo_str = str(tiempo)

        registros.append({
            'tiempo': tiempo_str,
            'evento': doc.get('evento'),
            # Asegurar que exista un campo "id_dispositivo", y si no se marca "Desconocido"
            'id_dispositivo': doc.get('id_dispositivo', 'desconocido')
        })
    
    # Invertir la lista para que los datos se entreguen del más antiguo al más reciente y se devuelven en formato JSON
    return jsonify(list(reversed(registros)))

@main.route('/api/registro_manual', methods=['POST'])
def registrar_manual():
    # Recibir los datos JSON
    data = request.get_json()

    # Si no se recibe los datos, y si no tiene al menos el campo "dominio" o "id_dispositivo", devuelve un error 400
    if not data or 'dominio' not in data or 'id_dispositivo' not in data:
        return jsonify({'error': 'Faltan campos obligatorios'}), 400

    # Extraer y eliminar del diccionario original para usarlos por separado
    dominio = data.pop('dominio')
    id_disp = data.pop('id_dispositivo')

    # Crear el documento, y se comienza con ID del dispositivo para un mejor orden en la base de datos
    doc = {
        "id_dispositivo": id_disp,
    }

    # Agregar los campos en el orden deseado si están presentes y tienen un valor válido (no vacío ni nulo)
    for campo in ["turbidez", "ph", "temperatura", "oxigeno", "conductividad"]:
        if campo in data and data[campo] not in ("", None):
            doc[campo] = data[campo]

    # Agregar el tiempo con fecha y hora del registro, en UTC, y campo adicional "manual" que marca ese dato como manual,
    # para diferenciarlo de los datos automáticos de sensores
    doc["tiempo"] = datetime.utcnow()
    doc["manual"] = True  # Campo adicional al final

    # Guardar el documento en la colección correspondiente al dominio indicado
    collection = current_app.mongo.db[dominio]
    collection.insert_one(doc)

    # Devolver mensaje indicando que el registro fue guardado correctamente, junto al código HTTP (201 Created)
    return jsonify({'message': f'Registro manual guardado en dominio {dominio}'}), 201

