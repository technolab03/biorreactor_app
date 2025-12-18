import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import plotly.graph_objects as go
import requests
from pymongo import MongoClient
from datetime import datetime
import pytz
from PIL import Image
import base64
from io import BytesIO
import numpy as np

# --- CREDENCIALES PARA BASE DE DATOS ---
MONGO_URI = st.secrets["MONGO_URI"]

# --- UMBRALES DE VARIABLES AMBIENTALES ---
UMBRAL = {
    "temperatura": (18, 27),
    "ph": (6.0, 9.5),
    "oxigeno": (3, 25),
    "luz": (0, 5000)
}

# --- UTILIDADES ---
def parsear_decimal(valor_str, nombre_campo):
    if not valor_str:
        return None
    try:
        valor_str = valor_str.replace(",", ".")
        return float(valor_str)
    except ValueError:
        st.error(f"❌ El valor ingresado en '{nombre_campo}' no es válido.")
        st.stop()

def evaluar_alertas_dispositivo(row):
    alertas = []
    for variable, (min_val, max_val) in UMBRAL.items():
        valor = row[variable]
        if valor < min_val or valor > max_val:
            alertas.append(
                f"⚠️ {variable.upper()} ({valor:.2f}) fuera del rango permitido [{min_val} – {max_val}]"
            )
    return alertas

# --- FILTRO GLOBAL DE DISPOSITIVOS ---
def mostrar_filtro_global(df, dominio_actual):
    # Obtener la lista única de dispositivos ordenada
    dispositivos = sorted(df["id_dispositivo"].dropna().unique())

    # Define claves únicas para session_state
    clave_ids = f"ids_filtrados_{dominio_actual}"
    clave_checkbox = f"checkbox_todos_{dominio_actual}"

    # Inicializar session_state si no existe
    if clave_ids not in st.session_state:
        st.session_state[clave_ids] = dispositivos.copy()
    if clave_checkbox not in st.session_state:
        st.session_state[clave_checkbox] = True  # Por defecto todo seleccionado

    with st.sidebar.expander("🔎 Filtro global de dispositivos", expanded=True):
        checkbox_val = st.checkbox(
            "Seleccionar todos",
            value=st.session_state[clave_checkbox],
            key=f"checkbox_todos_widget_{dominio_actual}"
        )

        # Detectar cambios en el checkbox y actualiza el session_state
        if checkbox_val != st.session_state[clave_checkbox]:
            st.session_state[clave_checkbox] = checkbox_val
            if checkbox_val:
                st.session_state[clave_ids] = dispositivos.copy()
            else:
                st.session_state[clave_ids] = []
            st.rerun()

        # Asegurar que los valores por defecto existen en las opciones actuales
        valores_validos = [d for d in st.session_state[clave_ids] if d in dispositivos]

        seleccion = st.multiselect(
            "Selecciona dispositivos:",
            dispositivos,
            default=valores_validos,
            key=f"multiselect_global_{dominio_actual}"
        )

        # Detectar cambios en la selección manual
        if set(seleccion) != set(st.session_state[clave_ids]):
            st.session_state[clave_ids] = seleccion
            if set(seleccion) == set(dispositivos):
                st.session_state[clave_checkbox] = True # Si seleccionó todos, checkbox activo
            elif len(seleccion) == 0:
                st.session_state[clave_checkbox] = False # Si no seleccionó ninguno, checkbox desactivado
            else:
                st.session_state[clave_checkbox] = False # Si seleccionó algunos, checkbox desactivado
            st.rerun()

    # Retornar la lista actual de dispositivos seleccionados
    return st.session_state[clave_ids]

# --- MÉTRICAS ---
def mostrar_metricas(df):
    st.markdown("### 📊 Últimos Valores por Dispositivo")

    if "id_dispositivo" not in df.columns:
        st.warning("⚠️ No se encontraron IDs de dispositivos en los datos.")
        return

    # Cargar los dispositivos filtrados, usando el filtro global para saber qué dispositivos mostrar
    dominio_actual = st.session_state.get("dominio_seleccionado", "dominio_terreno")
    clave_estado_ids = f"ids_filtrados_{dominio_actual}"

    # Obtener lista original ordenada alfabéticamente
    dispositivos_ordenados = sorted(df["id_dispositivo"].dropna().unique())

    # Obtener ids filtrados o por defecto toda la lista ordenada
    ids_filtrados = st.session_state.get(clave_estado_ids, dispositivos_ordenados)

    # Ordenar ids_filtrados manteniendo el orden alfabético original
    ids_filtrados_ordenados = [d for d in dispositivos_ordenados if d in ids_filtrados]

    # Filtrar el dataframe solo con los dispositivos seleccionados y configurar la zona horaria
    df_filtrado = df[df["id_dispositivo"].isin(ids_filtrados_ordenados)]
    chile_tz = pytz.timezone("America/Santiago")

    # Iterar por cada dispositivo seleccionado
    for disp in ids_filtrados_ordenados:
        # Ordenar por tiempo descendente y toma la fila más reciente
        df_disp = df_filtrado[df_filtrado["id_dispositivo"] == disp].sort_values(by="tiempo", ascending=False)
        if df_disp.empty:
            continue
        ultima_fecha = df_disp["tiempo"].iloc[0]
        if ultima_fecha.tzinfo is None:
            ultima_fecha = chile_tz.localize(ultima_fecha)
        else:
            ultima_fecha = ultima_fecha.astimezone(chile_tz)

        # Convertir la fecha a formato legible
        tiempo_str = ultima_fecha.strftime('%Y-%m-%d %H:%M:%S')

        # Mostrar título de dispositivo y última medición
        st.markdown(f"**🔎 Dispositivo:** `{disp}`  \n🕒 Última medición: `{tiempo_str}`")

        # Mostrar últimas métricas de cada variable en columnas 
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("🌡️ Temperatura", f"{df_disp['temperatura'].iloc[0]:.2f} °C")
        col2.metric("🌊 pH", f"{df_disp['ph'].iloc[0]:.2f}")
        col3.metric("🫁 Oxígeno", f"{df_disp['oxigeno'].iloc[0]:.2f} mg/L")
        col4.metric("⚡ Luz", f"{df_disp['luz'].iloc[0]:.2f} lux")

        # Última fila
        row = df_disp.iloc[0]

        # --- ALERTAS VISUALES ---
        alertas = evaluar_alertas_dispositivo(row)

        if alertas:
            with st.container():
                st.error("🚨 **ALERTAS DETECTADAS:**")
                for a in alertas:
                    st.write(a)

        # Agregar línea divisora entre dispositivos
        st.markdown("---")

# --- REPORTE DE SENSORES ---
def mostrar_reporte(df):
    st.subheader("📋 Reporte de Sensores")

    # Verificar si existe la columna "id_dispositivo"
    if "id_dispositivo" in df.columns:
        dispositivos = sorted(df["id_dispositivo"].dropna().unique())

        # Obtener dominio actual desde session_state
        dominio_actual = st.session_state.get("dominio_seleccionado", "dominio_terreno")
        clave_estado_ids = f"ids_filtrados_{dominio_actual}"

        # Recuperar la lista de dispositivos seleccionados por el usuario desde session_state
        ids_filtrados = st.session_state.get(clave_estado_ids, dispositivos)

        # Filtrar el dataframe solo con esos dispositivos seleccionados
        df_filtrado = df[df["id_dispositivo"].isin(ids_filtrados)]
    # Si no hay columna "id_dispositivo", se muestra todo el dataframe sin filtro
    else:
        df_filtrado = df

    # Botón de descarga para todos los datos filtrados (sin paginar)
    if not df_filtrado.empty:
        csv_data = df_filtrado.to_csv(index=False).encode('utf-8')
        # Mostrar los dispositivos filtrados en el nombre del archivo
        ids_str = "_".join(st.session_state.get(clave_estado_ids, []))
        nombre_archivo = f"datos_{ids_str}.csv"
        st.download_button(
            label="📥 Descargar datos filtrados de los dispositivos",
            data=csv_data,
            file_name=nombre_archivo,
            mime="text/csv"
        )

    # Paginación de registros, para evitar mostrar tabla con muchos datos
    filas_por_pagina = 250
    total_filas = len(df_filtrado)
    paginas_totales = max((total_filas - 1) // filas_por_pagina + 1, 1)

    # Inicializar y controlar la página actual
    if "pagina_actual" not in st.session_state:
        st.session_state.pagina_actual = 0

    # Mostrar los botones de navegación y la página actual
    col1, col2, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("⬅️ Anterior") and st.session_state.pagina_actual > 0:
            st.session_state.pagina_actual -= 1
    with col3:
        if st.button("Siguiente ➡️") and st.session_state.pagina_actual < paginas_totales - 1:
            st.session_state.pagina_actual += 1
    with col2:
        st.markdown(f"<div style='text-align: center; font-weight: bold;'>Página {st.session_state.pagina_actual + 1} de {paginas_totales}</div>", unsafe_allow_html=True)

    # Mostrar la tabla de datos
    inicio = st.session_state.pagina_actual * filas_por_pagina
    fin = inicio + filas_por_pagina
    # Invertir el dataframe para que los registros más reciente aparezcan arriba
    df_pagina = df_filtrado[::-1].iloc[inicio:fin]
    # Crear dataframe para tabla interactiva
    st.dataframe(df_pagina, use_container_width=True)
    # Agregar nota para rango mostrado en la tabla
    st.caption(f"Mostrando registros {inicio + 1} a {min(fin, total_filas)} de {total_filas}")

# --- REGISTRO DE ALIMENTACIÓN ---
def mostrar_registro_comida(registros, dominio_seleccionado, ids_filtrados=None):
    st.subheader("🍽️ Registro de Alimentación")

    # Verificar que lista de dispositivos seleccionados esté definida
    if ids_filtrados is None:
        ids_filtrados = []

    # Mostrar historial de alimentación expandible
    if registros:
        with st.expander("📄 Historial de alimentación por dispositivo"):
            # Si hay registros, convertir en dataframe
            df_comida = pd.DataFrame(registros)

            # Filtrar por dispositivos seleccionados
            df_comida = df_comida[df_comida["id_dispositivo"].isin(ids_filtrados)]

            # Ordenar los registros por fecha descendente
            df_comida["tiempo"] = pd.to_datetime(df_comida["tiempo"])
            df_ordenado = df_comida.sort_values("tiempo", ascending=False)
            df_ordenado["tiempo"] = df_ordenado["tiempo"].dt.strftime("%Y-%m-%d %H:%M:%S")

            # Mostrar solamente las columnas de tiempo e id_dispositivo
            st.dataframe(df_ordenado[["tiempo", "id_dispositivo"]], use_container_width=True)
    else:
        st.info("ℹ️ No hay registros de alimentación aún.")
        return

    try:
        # Conexión a base de datos para obtener dispositivos dentro del dominio seleccionado
        client = MongoClient(MONGO_URI)
        db = client["biorreactor_app"]
        collection = db[dominio_seleccionado]
        dispositivos_db = collection.distinct("id_dispositivo")

        # Filtrar solo los que están en ids_filtrados
        dispositivos_ordenados = sorted([d for d in dispositivos_db if d and d in ids_filtrados])
    except Exception as e:
        st.error(f"❌ Error al obtener dispositivos del dominio '{dominio_seleccionado}': {e}")
        return

    if not dispositivos_ordenados:
        st.info("ℹ️ No hay dispositivos disponibles para registrar alimentación en este dominio.")
        return

    st.markdown("### 📋 Estado actual de alimentación por dispositivo")
    ahora_chile = datetime.now(pytz.timezone("America/Santiago"))

    # Para cada dispositivo, obtener el último registro de alimentación
    for dispositivo in dispositivos_ordenados:
        registros_dispositivo = [r for r in registros if r["id_dispositivo"] == dispositivo]
        if registros_dispositivo:
            #Calcular cuántos días han pasado desde ese último evento
            ultimo = max(registros_dispositivo, key=lambda x: x["tiempo"])
            ultima_fecha = pd.to_datetime(ultimo["tiempo"])
            dias_sin_alimentar = (ahora_chile.date() - ultima_fecha.date()).days
            ultima_str = ultima_fecha.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ultima_str = "Sin registros"
            dias_sin_alimentar = None

        with st.container():
            col1, col2, col3, col4 = st.columns([2, 2, 1.5, 1])
            col1.markdown(f"**🆔 Nombre de dispositivo:**<br>{dispositivo}", unsafe_allow_html=True)
            col2.markdown(f"**📅 Última alimentación:**<br>{ultima_str}", unsafe_allow_html=True)

            # Indicador de cuántos días han pasado sin alimentar
            if dias_sin_alimentar is None:
                mensaje = "⚪ Sin registros"
                color = "gray"
            elif dias_sin_alimentar == 0:
                mensaje = "🟢 Hoy se alimentó"
                color = "green"
            elif dias_sin_alimentar <= 2:
                mensaje = f"🟡 {dias_sin_alimentar} día(s) sin alimentar"
                color = "orange"
            else:
                mensaje = f"🔴 {dias_sin_alimentar} días sin alimentar"
                color = "red"

            col3.markdown(f"**⏱️ Días sin alimentar:**<br><span style='color:{color}'>{mensaje}</span>", unsafe_allow_html=True)

            # Botón para registrar alimentación por cada dispositivo
            with col4:
                if st.button("🍽️ Alimentar", key=f"alimentar_{dispositivo}"):
                    # Enviar un POST a la API para registrar el evento de alimentación
                    response = requests.post(
                        "https://biorreactor-app.onrender.com/api/registro_comida",
                        json={"evento": "comida", "id_dispositivo": dispositivo}
                    )
                    # Si responde con éxito (201), muestra un mensaje y refresca la página
                    if response.status_code == 201:
                        st.success(f"✅ Alimentación registrada para {dispositivo}.")
                        st.rerun()
                    else:
                        st.error(f"❌ Error al registrar para {dispositivo}")

# --- GRAFICOS ---
def mostrar_graficos(df):
    st.subheader("📈 Visualización de Sensores por Dispositivo")

    # Obtener la lista única de dispositivos ordenada
    dispositivos = sorted(df["id_dispositivo"].dropna().unique())
    if not dispositivos:
        st.info("ℹ️ No hay dispositivos disponibles para el dominio y rango de fecha seleccionados.")
        return

    # Inicializar session_state si no existe y guardar la selección del usuario en la sesión
    if "dispositivo_seleccionado" not in st.session_state or st.session_state.dispositivo_seleccionado not in dispositivos:
        st.session_state.dispositivo_seleccionado = dispositivos[0]

    # Mostrar un selector para elegir el dispositivo
    id_seleccionado = st.selectbox(
        "Selecciona un dispositivo:",
        dispositivos,
        index=dispositivos.index(st.session_state.dispositivo_seleccionado),
        key="selectbox_graficos"
    )

    # Detectar cambios en la selección y actualizar sesión
    if id_seleccionado != st.session_state.dispositivo_seleccionado:
        st.session_state.dispositivo_seleccionado = id_seleccionado
        st.rerun()

    # Filtrar los datos por dispositivo seleccionado
    df_id = df[df["id_dispositivo"] == st.session_state.dispositivo_seleccionado]

    # Botón para descargar datos de dispositivo filtrado
    st.download_button(
        label="📥 Descargar datos filtrados del dispositivo",
        data=df_id.to_csv(index=False).encode('utf-8'),
        file_name=f"datos_{id_seleccionado}.csv",
        mime='text/csv'
    )

    # Diccionario de las variables para graficar
    variables = {
        "temperatura": ("🌡️ Temperatura", "°C", "red"),
        "ph": ("🌊 pH", "pH", "purple"),
        "oxigeno": ("🫁 Oxígeno", "mg/L", "green"),
        "luz": ("⚡ Luz", "lux", "orange"),
    }

    # Crear pestañas: una por variable + comparación múltiple + comparación de variables
    tab_labels = list([nombre for (nombre, _, _) in variables.values()])
    tab_labels.append("📊 Comparación múltiple")
    tab_labels.append("🧩 Comparar variables")
    tabs = st.tabs(tab_labels)

    # Graficar individualmente la variable específica del dispositivo seleccionado dentro de cada pestaña
    for i, (var, (nombre, unidad, color)) in enumerate(variables.items()):
        with tabs[i]:
            if var in df_id.columns:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_id["tiempo"], y=df_id[var],
                    mode="lines+markers",
                    name=nombre,
                    line=dict(color=color, width=2),
                    marker=dict(size=6, opacity=0.7)
                ))
                fig.update_layout(title=f"{nombre} - {id_seleccionado}", xaxis_title="Tiempo", yaxis_title=unidad, height=400)
                fig.update_xaxes(tickformat="%d-%m %H:%M", tickangle=45)
                fig.update_yaxes(showgrid=True)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning(f"⚠️ No hay datos para '{var}' en {id_seleccionado}.")

    # Seleccionar varios dispositivos y una variable a comparar
    with tabs[-2]:
        st.markdown("### 🔍 Comparación múltiple de dispositivos")
        seleccionados = st.multiselect("Selecciona dispositivos:", dispositivos, default=dispositivos[:2])
        var_multi = st.selectbox("Variable a visualizar:", list(variables.keys()), format_func=lambda x: variables[x][0])

        if seleccionados and var_multi:
            fig = go.Figure()
            for disp in seleccionados:
                df_disp = df[df["id_dispositivo"] == disp]
                fig.add_trace(go.Scatter(
                    x=df_disp["tiempo"], y=df_disp[var_multi],
                    mode="lines+markers", name=disp
                ))
            fig.update_layout(
                title=f"Comparación de {variables[var_multi][0]} entre múltiples dispositivos",
                xaxis_title="Tiempo", yaxis_title=variables[var_multi][1], height=450)
            fig.update_xaxes(tickformat="%d-%m %H:%M", tickangle=45)
            fig.update_yaxes(showgrid=True)
            st.plotly_chart(fig, use_container_width=True)

    # Comparar múltiples variables de un mismo dispositivo (Z-Score estándar)
    with tabs[-1]:
        st.markdown("### 🧩 Comparar múltiples variables en un mismo dispositivo")

        vars_seleccionadas = st.multiselect(
            "Variables a graficar:",
            list(variables.keys()),
            default=["ph", "oxigeno"],
            format_func=lambda x: variables[x][0]
        )

        # Método Z-score
        st.markdown("**Método de normalización:** Z-score (estándar)")
        ventana = st.slider("📏 Suavizado (media móvil, puntos)", 1, 21, 1, 2)

        if not vars_seleccionadas:
            st.warning("Selecciona al menos una variable para graficar.")
        else:
            df_plot = df_id[["tiempo"]].copy()
            raw_series = {}

            # Extraer y suavizar series
            for var in vars_seleccionadas:
                if var in df_id.columns:
                    serie = df_id[var].astype(float).dropna()
                    if ventana > 1:
                        serie = serie.rolling(ventana, center=True, min_periods=1).mean()
                    raw_series[var] = serie

            if not raw_series:
                st.warning("No hay datos válidos para las variables seleccionadas.")
            else:
                # Crear DataFrame con todas las variables alineadas en tiempo
                df_all = pd.DataFrame({"tiempo": df_id["tiempo"]}).set_index("tiempo")
                for k, s in raw_series.items():
                    df_all[k] = s.values

                # Normalización Z-score
                normed = pd.DataFrame(index=df_all.index)
                for k in vars_seleccionadas:
                    s = df_all[k]
                    mu, sd = np.nanmean(s.values), np.nanstd(s.values)
                    sd = sd if sd not in (0, None) and sd != 0 else 1.0
                    z = (s - mu) / sd
                    # Escalar a rango 0–1 para visualización comparativa
                    normed[k] = (z - (-3)) / (3 - (-3))  # mapea [-3, 3] → [0, 1]

                # Graficar 
                fig = go.Figure()
                for var in vars_seleccionadas:
                    if var in normed.columns:
                        nombre, unidad, color = variables[var]
                        serie_plot = normed[var]
                        if serie_plot is None or serie_plot.dropna().empty:
                            st.warning(f"⚠ '{nombre}' no tiene datos suficientes tras normalización.")
                            continue
                        fig.add_trace(go.Scatter(
                            x=serie_plot.index, y=serie_plot,
                            mode="lines+markers",
                            name=f"{nombre} (Z-score norm.)",
                            line=dict(width=2, color=color) if color else dict(width=2),
                            hovertemplate="%{x|%d-%m %H:%M}<br>%{y:.3f}<extra></extra>"
                        ))

                fig.update_layout(
                    title=f"Comparación de variables normalizadas (Z-score) en {id_seleccionado}",
                    xaxis_title="Tiempo",
                    yaxis_title="Escala normalizada (0–1)",
                    height=450,
                    legend_title="Variable"
                )
                fig.update_xaxes(tickformat="%d-%m %H:%M", tickangle=45)
                fig.update_yaxes(range=[0, 1], showgrid=True, zeroline=True)
                st.plotly_chart(fig, use_container_width=True)

# --- IMÁGENES ---
def mostrar_imagenes(db):
    st.subheader("🖼️ Visualización de Imágenes Capturadas")

    # Acceder a la colección "imagenes_camara"
    collection = db["imagenes_camara"]

    # Filtros de entrada del usuario 
    col1, col2 = st.columns(2)
    with col1:
        # Filtrar para mostrar imágenes capturadas ese día
        fecha_filtrada = st.date_input("📅 Filtrar por fecha (opcional):", value=None)
    with col2:
        # Filtrar cuántas imágenes quiere ver (hasta un máximo de 50)
        cantidad = st.number_input("🔢 ¿Cuántas imágenes mostrar?", min_value=1, max_value=50, value=5, step=1)

    # Consulta a MongoDB
    # Al seleccionar una fecha, se filtra imágenes dentro de ese rango horario (desde el inicio al fin del día), 
    # convirtiendo las zonas horarias desde Santiago a UTC, ya que MongoDB guarda en UTC
    query = {}
    if fecha_filtrada:
        inicio_dia = datetime.combine(fecha_filtrada, datetime.min.time()).replace(tzinfo=pytz.timezone("America/Santiago"))
        fin_dia = datetime.combine(fecha_filtrada, datetime.max.time()).replace(tzinfo=pytz.timezone("America/Santiago"))
        query["tiempo"] = {
            "$gte": inicio_dia.astimezone(pytz.utc),
            "$lte": fin_dia.astimezone(pytz.utc)
        }

    # Buscar con el filtro anterior, y se ordenan por tiempo descendente 
    # y se limita el número de resultados según el valor ingresado del usuario
    documentos = list(collection.find(query).sort("tiempo", -1).limit(cantidad))

    if not documentos:
        st.info("⚠️ No hay imágenes para mostrar con los filtros seleccionados.")
        return

    # Mostrar imágenes en columnas dinámicas
    cols = st.columns(len(documentos))
    for idx, doc in enumerate(documentos):
        if 'imagen' in doc and 'tiempo' in doc:
            # Decodificar la cadena Base64 y se convierte a formato PIL.Image para mostrarla
            imagen_bytes = base64.b64decode(doc['imagen'])
            imagen = Image.open(BytesIO(imagen_bytes))
            # Convertir la hora UTC a horario de Chile
            chile_tz = pytz.timezone("America/Santiago")
            tiempo_chile = doc["tiempo"].replace(tzinfo=pytz.utc).astimezone(chile_tz)
            tiempo_str = tiempo_chile.strftime('%Y-%m-%d %H:%M:%S')
            # Mostrar la imagen junto con su fecha y hora en que fue tomada
            cols[idx].image(imagen, caption=f"Capturada el {tiempo_str}", use_container_width=True)

# --- REGISTRO MANUAL ---
def mostrar_registro_manual():
    st.subheader("✍️ Registro Manual de Variables")

    # Recuperar el dominio y la lista de dispositivos seleccionados por el usuario
    dominio_actual = st.session_state.get("dominio_seleccionado", "dominio_terreno")
    ids = st.session_state.get(f"ids_filtrados_{dominio_actual}", [])

    if not ids:
        st.warning("⚠️ No hay dispositivos seleccionados para registrar manualmente.")
        return

    # Al enviar un formulario exitoso en la sesión anterior, se muestra una notificación
    if st.session_state.get("registro_manual_exitoso"):
        st.success("✅ Registro manual enviado correctamente.")
        st.session_state.pop("registro_manual_exitoso")

    # Mostrar un formulario por cada dispositivo seleccionado
    for dispositivo in ids:
        st.markdown(f"📟 Dispositivo: `{dispositivo}`")
        with st.form(f"form_manual_{dispositivo}"):
            # Mostrar 6 columnas con campos de entrada dentro de cada formulario
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                temperatura = st.text_input("🌡️ Temperatura (°C)", key=f"temp_{dispositivo}", help="Rango: 0.00 - 30.00 (°C)", placeholder="Ingrese el valor de temperatura")
            with col2:
                ph = st.text_input("🌊 pH", key=f"ph_{dispositivo}", help="Rango: 0.00 - 14.00 (pH)", placeholder="Ingrese el valor de ph")
            with col3:
                oxigeno = st.text_input("🫁 Oxígeno (mg/L)", key=f"oxigeno_{dispositivo}", help="Rango: 0.00 - 100.00 (mg/L)", placeholder="Ingrese el valor de oxigeno")
            with col4:
                luz = st.text_input("⚡ Luz (lux)", key=f"luz_{dispositivo}", help="Rango: 0.00 - 3000.00 (lux)", placeholder="Ingrese el valor de luz")
            with col5:
                enviado = st.form_submit_button("📩 Enviar registro")
        
        # Manejar el botón de envío
        if enviado:
            campos = {
                "temperatura": temperatura,
                "ph": ph,
                "oxigeno": oxigeno,
                "luz": luz
            }

            # Validar que al menos un campo esté lleno, o da error
            if all(v.strip() == "" for v in campos.values()):
                st.error("❌ Debes ingresar al menos un valor.")
                return

            # Construir diccionario data, agregando la fecha actual en Santiago y nuevo campo "manual" por defecto en True
            data = {
                "dominio": dominio_actual,
                "id_dispositivo": dispositivo,
                "manual": True,
                "tiempo": datetime.now(pytz.timezone("America/Santiago")).isoformat()
            }

            # Valores ingresados, convertirlos correctamente con función parsear_decimal()
            for campo, valor in campos.items():
                if valor.strip():
                    data[campo] = parsear_decimal(valor, campo.capitalize())

            # Hacer petición POST a la API
            response = requests.post("https://biorreactor-app.onrender.com/api/registro_manual", json=data)

            # Si el servidor responde con éxito (201)
            if response.status_code == 201:
                # Mostrar mensaje de éxito
                st.success(f"✅ Registro enviado correctamente para `{dispositivo}`.")
                st.session_state["registro_manual_exitoso"] = True
                # Guardar dispositivo registrado en la sesión
                st.session_state["ultimo_dispositivo_registrado"] = dispositivo
                # Limpiar campos del formulario
                for campo in ["temp", "ph", "oxigeno", "luz"]:
                    st.session_state.pop(f"{campo}_{dispositivo}", None)
                # Refrescar la página
                st.rerun()
            else:
                st.error(f"❌ Error al registrar manualmente: {response.text}")

    # Mostrar historial de registros manuales
    st.markdown("---")
    st.markdown("### 📄 Últimos registros manuales")

    # Después de la línea separadora, mostrar el historial sólo del último dispositivo registrado manualmente
    ultimo = st.session_state.get("ultimo_dispositivo_registrado")
    if not ultimo:
        st.info("ℹ️ Aún no has registrado datos manuales en esta sesión.")
        return

    try:
        # Conexión a la base de datos
        client = MongoClient(MONGO_URI)
        db = client["biorreactor_app"]
        collection = db[dominio_actual]

        # Buscar registros manuales para ese último dispositivo, ordenados por fecha descendente
        registros_manuales = list(collection.find({
            "id_dispositivo": ultimo,
            "manual": True
        }).sort("tiempo", -1).limit(50))

        # Crear dataframe y formatear la columna "tiempo"
        if registros_manuales:
            df_hist = pd.DataFrame(registros_manuales)
            df_hist["tiempo"] = pd.to_datetime(df_hist["tiempo"]).dt.strftime("%Y-%m-%d %H:%M:%S")

            columnas_mostrar = ["tiempo", "temperatura", "ph", "oxigeno", "luz"]
            columnas_mostrar = [col for col in columnas_mostrar if col in df_hist.columns]

            st.markdown(f"📋 Historial del dispositivo: `{ultimo}`")
            
            # Mostrar las columnas relevantes en una tabla
            st.dataframe(df_hist[columnas_mostrar], use_container_width=True)
        else:
            st.info(f"ℹ️ No hay registros manuales previos para `{ultimo}`.")
    except Exception as e:
        st.error(f"❌ Error al cargar el historial manual: {e}")

# --- HISTORIAL MANUAL ---
def mostrar_historial_manual():
    st.subheader("📈 Visualización por variable")

    # Obtener dominio seleccionado
    dominio_actual = st.session_state.get("dominio_seleccionado", "dominio_terreno")

    try:
        # Conexión a la base de datos con el dominio actual
        client = MongoClient(MONGO_URI)
        db = client["biorreactor_app"]
        collection = db[dominio_actual]

        # Cargar registros manuales, que tengan campo "manual": True (o sea, que no fueron ingresados automáticamente)
        registros_manuales = list(collection.find({"manual": True}).sort("tiempo", -1).limit(500))

        if not registros_manuales:
            st.info("ℹ️ No hay registros manuales disponibles.")
            return

        # Convertir los registros a un dataframe, convertir el tiempo a fecha y ordenar por fecha descendente
        df_manual = pd.DataFrame(registros_manuales)
        df_manual["tiempo"] = pd.to_datetime(df_manual["tiempo"])
        df_manual = df_manual.sort_values("tiempo", ascending=False)

        # Filtro por dispositivo, para elegir uno o varios dispositivos
        dispositivos = df_manual["id_dispositivo"].unique().tolist()
        seleccionados = st.multiselect("📟 Filtrar por dispositivo", ["Todos"] + dispositivos, default="Todos")

        if "Todos" not in seleccionados:
            df_manual = df_manual[df_manual["id_dispositivo"].isin(seleccionados)]

        # Filtro por fecha, permite seleccionar un rango de fechas, para filtrar los registros dentro de ese rango
        fechas = df_manual["tiempo"]
        fecha_min, fecha_max = fechas.min().date(), fechas.max().date()
        rango = st.date_input("📆 Rango de fechas", [fecha_min, fecha_max])
        if len(rango) == 2:
            f1 = pd.to_datetime(rango[0])
            f2 = pd.to_datetime(rango[1]) + pd.Timedelta(days=1)
            df_manual = df_manual[(df_manual["tiempo"] >= f1) & (df_manual["tiempo"] < f2)]

        # Gráfico de evolución por variable seleccionada
        variables = ["temperatura", "ph", "oxigeno", "luz"]
        variables_disponibles = [v for v in variables if v in df_manual.columns]

        # Mostrar solamente las variables disponibles
        if variables_disponibles:
            var = st.selectbox("Selecciona variable a graficar", variables_disponibles)
            df_chart = df_manual[["tiempo", "id_dispositivo", var]].dropna()
            df_chart = df_chart.sort_values("tiempo")

            if not df_chart.empty:
                fig = go.Figure()

                # Agrupar por dispositivo, donde cada dispositivo tiene su propia línea en el gráfico
                for dispositivo_id, df_disp in df_chart.groupby("id_dispositivo"):
                    fig.add_trace(go.Scatter(
                        x=df_disp["tiempo"],
                        y=df_disp[var],
                        mode="lines+markers", 
                        name=str(dispositivo_id)
                    ))

                fig.update_layout(
                    title=f"Evolución de {var.capitalize()} por dispositivo",
                    xaxis=dict(
                        title="Fecha",
                        tickformat="%d-%b",
                        tickangle=0,
                        tickfont=dict(size=12),
                        tickmode="auto",
                        showticklabels=True,
                        ticks="outside"
                    ),
                    yaxis_title=var.capitalize(),
                    hovermode="x unified",
                    legend_title="Dispositivo",
                    template="plotly_white",
                    height=400
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("ℹ️ No hay datos disponibles para graficar.")
        else:
            st.info("ℹ️ No hay variables numéricas disponibles para graficar.")

        # Tabla colapsable, permite ver tabla completa de los registros debajo del gráfico
        with st.expander("📄 Ver tabla de registros manuales"):
            df_manual["tiempo"] = df_manual["tiempo"].dt.strftime("%Y-%m-%d %H:%M:%S")
            columnas = ["tiempo", "id_dispositivo", "temperatura", "ph", "oxigeno", "luz"]
            columnas = [col for col in columnas if col in df_manual.columns]
            st.dataframe(df_manual[columnas], use_container_width=True)

        # Botón para descarga en CSV
        # Convierte el dataframe en CSV y permite al usuario descargar todos los registros manuales filtrados
        csv_manual = df_manual[columnas].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Descargar CSV de registros manuales",
            data=csv_manual,
            file_name=f"registros_manuales_{dominio_actual}.csv",
            mime="text/csv"
        )

    except Exception as e:
        st.error(f"❌ Error al cargar registros manuales: {e}")

# --- COMPARACIÓN DE REGISTROS ---
def mostrar_registro_manual_vs_sensor():
    st.subheader("📋 Comparación por Día: Registro Manual vs Sensor")

    # Obtener dominio actual e IDs de dispositivos filtrados desde session_state
    dominio_actual = st.session_state.get("dominio_seleccionado", "dominio_terreno")
    ids = st.session_state.get(f"ids_filtrados_{dominio_actual}", [])

    if not ids:
        st.warning("⚠️ No hay dispositivos seleccionados para comparar.")
        st.stop()

    # Selección del dispositivo
    dispositivo = st.selectbox("📟 Selecciona un dispositivo:", ids)

    try:
        # Conexión a la base de datos con el dominio actual
        client = MongoClient(MONGO_URI)
        db = client["biorreactor_app"]
        collection = db[dominio_actual]

        # Buscar todos los registros del dispositivo seleccionado
        registros = list(collection.find({"id_dispositivo": dispositivo}))
        if not registros:
            st.info("ℹ️ No hay registros para este dispositivo.")
            return
        
        # Convertir los datos a un dataframe, transformando la columna "tiempo" y extrayendo la fecha
        df = pd.DataFrame(registros)
        df["tiempo"] = pd.to_datetime(df["tiempo"])
        df["fecha"] = df["tiempo"].dt.date

        # Variables a comparar
        vars_medibles = ["temperatura", "ph", "oxigeno", "luz"]

        # Separar registros manuales y automáticos
        df_manual = df[df["manual"] == True].copy()
        df_auto = df[(df["manual"] != True)].copy()

        if df_manual.empty or df_auto.empty:
            st.info("ℹ️ Se necesitan registros manuales y automáticos para comparar.")
            return
        
        # Agrupar automáticos por día, calculando la mediana o promedio
        df_auto_grouped = df_auto.groupby("fecha")[vars_medibles].mean().round(2).reset_index() #.median() - Mediana

        # Agrupar manuales por día, tomando el primer registro del día 
        df_manual_grouped = df_manual.groupby("fecha")[vars_medibles].first().round(2).reset_index()

        # Combinar ambas tablas por la columna "fecha"
        df_comp = pd.merge(df_manual_grouped, df_auto_grouped, on="fecha", suffixes=("_manual","_sensor"))

        # Calcular diferencia por variable medible, se calcula la diferencia diaria entre el registro manual y el automático
        for var in vars_medibles:
            col_manual = f"{var}_manual"
            col_sensor = f"{var}_sensor"
            if col_manual in df_comp.columns and col_sensor in df_comp.columns:
                df_comp[f"{var}_diff"] = (df_comp[col_manual] - df_comp[col_sensor]).round(2)

        # Mostrar tabla comparativa
        columnas_mostrar = ["fecha"]
        for var in vars_medibles:
            columnas_mostrar += [f"{var}_manual", f"{var}_sensor", f"{var}_diff"]
        
        # Renombrar columnas para legibilidad
        nombres_columnas = {"fecha": "Fecha"}
        for var in vars_medibles:
            nombres_columnas[f"{var}_manual"] = f"{var.capitalize()} (Manual)"
            nombres_columnas[f"{var}_sensor"] = f"{var.capitalize()} (Sensor)"
            nombres_columnas[f"{var}_diff"] = f"Diferencia {var.capitalize()}"

        df_mostrar = df_comp[columnas_mostrar].rename(columns=nombres_columnas)
        st.dataframe(df_mostrar, use_container_width=True)

        # Gráfico por variable, selector para seleccionar una variable a graficar
        st.markdown("### 📈 Selector de variable para gráficos")
        var_sel = st.selectbox("Selecciona una variable", vars_medibles)
        if f"{var_sel}_manual" in df_comp.columns:
            
            # Línea Manual vs Sensor
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=df_comp["fecha"],
                y=df_comp[f"{var_sel}_manual"],
                mode="lines+markers",
                name="Manual"
            ))
            fig.add_trace(go.Scatter(
                x=df_comp["fecha"],
                y=df_comp[f"{var_sel}_sensor"],
                mode="lines+markers",
                name="Sensor"
            ))

            fig.update_layout(
                title=f"📊 {var_sel.capitalize()}: Manual vs Sensor",
                xaxis=dict(
                    title="Fecha",
                    tickformat="%d-%b",
                    tickangle=0,
                    tickfont=dict(size=12)
                ),
                yaxis_title=var_sel.capitalize(),
                hovermode="x unified",
                template="plotly_white",
                height=400
            )
            st.plotly_chart(fig, use_container_width=True)

            # Diferencia diaria
            fig_diff = go.Figure()
            fig_diff.add_trace(go.Bar(
                x=df_comp["fecha"],
                y=df_comp[f"{var_sel}_diff"],
                name="Diferencia (Manual - Sensor)",
                marker_color="indianred"
            ))

            fig_diff.update_layout(
                title=f"📉 Diferencia diaria de {var_sel.capitalize()}",
                xaxis=dict(
                    title="Fecha",
                    tickformat="%d-%b",
                    tickangle=0,
                    tickfont=dict(size=12)
                ),
                yaxis_title="Diferencia",
                template="plotly_white",
                height=350
            )
            st.plotly_chart(fig_diff, use_container_width=True)

    except Exception as e:
        st.error(f"❌ Error al obtener los registros: {e}")

# --- MODELO ---
def mostrar_modelo():
    st.subheader("🤖 Clasificación de fase del cultivo (Modelo GRU)")

    # Consulta a colección clasificaciones
    client = MongoClient(MONGO_URI)
    db = client["biorreactor_app"]
    df_clasificaciones = pd.DataFrame(list(db["clasificaciones"].find()))

    df = df_clasificaciones.copy()

    # Asegurarse de que existan las columnas
    for col in ["fase", "proba", "timestamp"]:
        if col not in df.columns:
            df[col] = df.apply(lambda row: row.get(col, None), axis=1)

    # Selección de dispositivo
    dispositivos = sorted(df["id_dispositivo"].dropna().unique())
    if not dispositivos:
        st.warning("No hay dispositivos disponibles.")
        return

    dispositivo = st.selectbox("📟 Selecciona un dispositivo:", dispositivos)
    df_disp = df[df["id_dispositivo"] == dispositivo].copy()

    # Convertir timestamp a datetime
    df_disp["timestamp"] = df_disp["timestamp"].apply(
        lambda x: pd.to_datetime(x.get("$date")) if isinstance(x, dict) else pd.to_datetime(x, errors="coerce")
    )
    df_disp = df_disp.dropna(subset=["timestamp"])  # eliminar filas sin timestamp

    # Convertir a hora chilena y renombrar columna
    df_disp["tiempo"] = df_disp["timestamp"].dt.tz_localize("UTC").dt.tz_convert("America/Santiago")
    df_disp = df_disp.sort_values("tiempo")

    # Mostrar últimas clasificaciones
    st.markdown("### 📊 Últimas clasificaciones guardadas")
    st.dataframe(df_disp[["tiempo", "fase", "proba"]].tail(10))

    # Mostrar última clasificación
    if not df_disp.empty:
        ultima = df_disp.iloc[-1]
        fase = ultima.get("fase", "Desconocida")
        proba = ultima.get("proba", None)

        if proba and isinstance(proba, (list, tuple)) and len(proba) >= 3:
            # Reordenar probabilidades: 0=Crecimiento, 2=Estacionaria, 1=Declive
            proba_ordenada = [proba[0], proba[2], proba[1]]
        else:
            proba_ordenada = [0.0, 0.0, 0.0]

        clases = ["Crecimiento", "Estacionaria", "Declive"]

        st.markdown("### 🧬 Última fase estimada")
        col1, col2 = st.columns([1, 2])
        with col1:
            st.metric("Fase actual", fase.capitalize())
        with col2:
            st.write("📊 Probabilidades por fase:")
            for c, p in zip(clases, proba_ordenada):
                st.write(f"- **{c}**: {p:.5f}")

        # Gráfico
        fig = go.Figure(data=[go.Bar(x=clases, y=proba_ordenada)])
        fig.update_layout(
            title=f"Distribución de probabilidades — Última clasificación",
            xaxis_title="Fase",
            yaxis_title="Probabilidad",
            height=400
        )
        st.plotly_chart(fig, use_container_width=True)

    # Refrescar automáticamente cada 60 segundos
    st_autorefresh(interval=60000, key="refresh_modelo")


