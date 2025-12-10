import streamlit as st
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import pytz
from pymongo import MongoClient
from datetime import datetime
from database import obtener_datos, obtener_registro_comida
from funciones_dashboard import (
    mostrar_metricas,
    mostrar_reporte,
    mostrar_registro_comida,
    mostrar_graficos,
    mostrar_imagenes,
    mostrar_registro_manual,
    mostrar_historial_manual,
    mostrar_registro_manual_vs_sensor,
    mostrar_filtro_global,
    mostrar_modelo
)

# --- CREDENCIALES PARA BASE DE DATOS ---
MONGO_URI = st.secrets["MONGO_URI"]

# --- UTILIDADES ---
def obtener_hora_chile(dt_utc=None):
    chile_tz = pytz.timezone("America/Santiago")
    if dt_utc is None:
        return datetime.now(chile_tz)
    return dt_utc.replace(tzinfo=pytz.utc).astimezone(chile_tz)

@st.cache_data(ttl=600)
def cargar_datos_cacheados(dominio='dominio_terreno', limit=5000):
    return obtener_datos(dominio, limit)

# --- CONFIGURACIÓN GENERAL ---
st.set_page_config(page_title="Dashboard Biorreactor", layout="wide")
st_autorefresh(interval=900000, key="dashboardrefresh")

# --- REGISTRO DE HORA DE ÚLTIMA ACTUALIZACIÓN ---
if "ultima_actualizacion" not in st.session_state:
    st.session_state.ultima_actualizacion = obtener_hora_chile()

# --- TÍTULO Y HORA DE ÚLTIMA ACTUALIZACIÓN ---
st.title("🌱 Dashboard de Monitoreo - Biorreactor Inteligente")
st.caption(f"🕒 Última actualización: {st.session_state.ultima_actualizacion.strftime('%Y-%m-%d %H:%M:%S')}")

# --- MENÚ LATERAL ---
st.sidebar.markdown("### 📁 **Navegación**")
seccion = st.sidebar.radio("Selecciona una sección:", [
    "📊 Métricas", 
    "📋 Reporte", 
    #"🍽️ Alimentación", 
    "📈 Gráficos", 
    #"✍️ Registro Manual",
    #"📄 Historial Manual",
    #"🆚 Comparación de Registros",
    #"🖼️ Imágenes",
    "🤖 Modelo"
])

# --- CONEXIÓN A LA BASE DE DATOS --- 
client = MongoClient(MONGO_URI)
db = client["biorreactor_app"]

# --- SECCIÓN: FILTROS DE DOMINIO Y FECHAS ---
if seccion in ["📊 Métricas", "📋 Reporte", "🍽️ Alimentación", "📈 Gráficos", "✍️ Registro Manual", "📄 Historial Manual", "🆚 Comparación de Registros", "🖼️ Imágenes", "🤖 Modelo"]:
    with st.expander("🌐📅 Filtros de dominio y fechas", expanded=False):
        with st.form("form_filtros"):
            col1, col2 = st.columns(2)

            with col1:
                # Extraer desde la base de datos las colecciones disponibles que comienzan con "dominio_"
                dominios_disponibles = sorted([col for col in db.list_collection_names() if col.startswith("dominio_")])
                
                # Elegir por defecto "dominio_terreno", si existe
                indice_por_defecto = dominios_disponibles.index("dominio_terreno") if "dominio_terreno" in dominios_disponibles else 0
                
                # Recuperar dominio guardado en session_state o mostrar por defecto
                dominio_inicial = st.session_state.get("dominio_seleccionado", dominios_disponibles[indice_por_defecto])

                # Mostrar selectbox con las opciones para que el usuario elija
                dominio_seleccionado = st.selectbox(
                    "🌐 Selecciona un dominio:",
                    dominios_disponibles,
                    index=dominios_disponibles.index(dominio_inicial)
                )

            with col2:
                # Cargar los datos desde el dominio seleccionado
                data = cargar_datos_cacheados(dominio_seleccionado)
                if not data:
                    st.warning("⚠️ No hay datos disponibles.")
                    st.stop()

                # Convertir a dataframe y convierte la columna "tiempo" a tipo fecha
                df = pd.DataFrame(data)
                df = df[df['tiempo'].notna()]
                df['tiempo'] = pd.to_datetime(df['tiempo'])
                df = df.sort_values(by='tiempo')

                # Determinar los límites mínimo y máximo para el calendario 
                fecha_min = df['tiempo'].min().date()
                fecha_max = df['tiempo'].max().date()
            
                # Obtener valores guardados o usar por defecto
                fecha_inicio_default = st.session_state.get("fecha_inicio", fecha_min)
                fecha_fin_default = st.session_state.get("fecha_fin", fecha_max)

                # Mostrar un selector donde el usuario elige el rango de fechas
                fecha_inicio, fecha_fin = st.date_input(
                    "📅 Selecciona un rango de fechas:",
                    value=(fecha_min, fecha_max),
                    min_value=fecha_min,
                    max_value=fecha_max
                )

            # Botón de formulario para confirmar filtros
            form_enviado = st.form_submit_button("Aplicar filtros")

            # Detectar cambios en los filtros, si se cambió el dominio o las fechas respecto a las que había en session_state
            cambios = (
                dominio_seleccionado != st.session_state.get("dominio_seleccionado") or
                fecha_inicio != st.session_state.get("fecha_inicio") or
                fecha_fin != st.session_state.get("fecha_fin")
            )

            # Se guardan los nuevos valores en session_state
            if form_enviado and cambios:
                st.session_state["dominio_seleccionado"] = dominio_seleccionado
                st.session_state["fecha_inicio"] = fecha_inicio
                st.session_state["fecha_fin"] = fecha_fin
                st.rerun()  # Recarga solo si hubo cambios

    # Si el usuario no ha enviado el formulario, tomar valores de session_state o usar por defecto
    dominio_seleccionado = st.session_state.get("dominio_seleccionado", dominios_disponibles[indice_por_defecto])
    fecha_inicio = st.session_state.get("fecha_inicio", fecha_min)
    fecha_fin = st.session_state.get("fecha_fin", fecha_max)

    # Filtrar el dataframe por fechas, se filtra por el rango de fechas elegido, si no hay datos en ese rango, se muestra una advertencia
    df = df[(df['tiempo'].dt.date >= fecha_inicio) & (df['tiempo'].dt.date <= fecha_fin)]
    if df.empty:
        st.warning("⚠️ No hay datos dentro del rango de fechas seleccionado.")
        st.stop()

    # Se muestra el filtro global para permitir al usuario seleccionar dispositivos
    ids_filtrados = mostrar_filtro_global(df, dominio_seleccionado)

    # Luego filtrar el df para usar los dispositivos seleccionados
    df = df[df["id_dispositivo"].isin(ids_filtrados)]

    # Si no hay datos luego del filtro, se muestra advertencia y se detiene la ejecución
    if df.empty:
        st.warning("⚠️ No hay datos para los dispositivos seleccionados.")
        st.stop()

# --- BOTONES DE ACCIÓN ---
# Botón para limpiar caché y actualizar datos
if st.sidebar.button("🔄 Actualizar datos"):
    st.cache_data.clear()
    st.session_state.ultima_actualizacion = obtener_hora_chile()
    st.rerun()

# Botón para resetear los filtros
dominio_actual = st.session_state.get("dominio_seleccionado", "dominio_terreno")  # Asegúrate de definirlo antes

if st.sidebar.button("🧹 Resetear filtros"):
    claves_a_borrar = [
        "dispositivo_seleccionado",
        "selectbox_graficos",
        "ids_filtrados",
        "multiselect_tabla",
        "pagina_actual",
        f"ids_filtrados_{dominio_actual}",
        f"checkbox_todos_{dominio_actual}",
        f"checkbox_todos_widget_{dominio_actual}",
        f"multiselect_global_{dominio_actual}"
    ]
    for key in claves_a_borrar:
        st.session_state.pop(key, None)
    st.rerun()

# --- RENDERIZADO DE SECCIONES ---
if seccion == "📊 Métricas":
    mostrar_metricas(df)

elif seccion == "📋 Reporte":
    mostrar_reporte(df)

elif seccion == "🍽️ Alimentación":
    dominio_seleccionado = st.session_state.get("dominio_seleccionado", "dominio_terreno")
    registros = obtener_registro_comida(limit=5000)
    ids_filtrados = st.session_state.get(f"ids_filtrados_{dominio_seleccionado}", [])
    mostrar_registro_comida(registros, dominio_seleccionado, ids_filtrados=ids_filtrados)

elif seccion == "📈 Gráficos":
    mostrar_graficos(df)

elif seccion == "🖼️ Imágenes":
    mostrar_imagenes(db)

elif seccion == "✍️ Registro Manual":
    mostrar_registro_manual()

elif seccion == "📄 Historial Manual":
    mostrar_historial_manual()

elif seccion == "🆚 Comparación de Registros":
    mostrar_registro_manual_vs_sensor()

elif seccion == "🤖 Modelo":
    mostrar_modelo()

# --- BOTÓN GRAFANA ---
#st.sidebar.markdown("---")
#st.sidebar.link_button("🔗 Ir al Dashboard de Grafana", "https://jeanmolina.grafana.net/public-dashboards/dd177b1f03f94db6ac6242f5586c796d")
