import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd 
import time  
import requests 

# 1. MODO PANTALLA COMPLETA
st.set_page_config(page_title="Mi Portafolio", layout="wide")

st.title("Mi Dashboard Financiero 📈")
st.write("Análisis de Portafolio Dinámico")

# ==========================================
# MOTOR DE BÚSQUEDA INTELIGENTE
# ==========================================
def buscar_multiples_tickers(texto):
    url = f"https://query2.finance.yahoo.com/v1/finance/search?q={texto}"
    headers = {'User-Agent': 'Mozilla/5.0'}
    resultados = []
    try:
        res = requests.get(url, headers=headers).json()
        if 'quotes' in res:
            for q in res['quotes']:
                if 'symbol' in q:
                    simbolo = q['symbol']
                    nombre = q.get('shortname', simbolo)
                    tipo = q.get('quoteType', 'N/A')
                    bolsa = q.get('exchDisp', 'N/A')
                    etiqueta = f"{simbolo} - {nombre} ({tipo} | {bolsa})"
                    resultados.append({"symbol": simbolo, "name": nombre, "label": etiqueta})
    except:
        pass
    return resultados

# ==========================================
# LA MEMORIA PERSISTENTE 
# ==========================================
if "nombres_tickers" not in st.session_state:
    st.session_state.nombres_tickers = {}

if "mis_tickers" not in st.session_state:
    if "q_tickers" in st.query_params:
        st.session_state.mis_tickers = st.query_params["q_tickers"].split(",")
    else:
        st.session_state.mis_tickers = ["VAW"]
        st.session_state.nombres_tickers["VAW"] = "Vanguard Materials ETF"

if "buscador" not in st.session_state:
    st.session_state.buscador = ""

for t in st.session_state.mis_tickers:
    if t not in st.session_state.nombres_tickers:
        r = buscar_multiples_tickers(t)
        st.session_state.nombres_tickers[t] = r[0]["name"] if r else t

def sincronizar_url():
    st.query_params["q_tickers"] = ",".join(st.session_state.mis_tickers)

sincronizar_url()

# ==========================================
# FUNCIONES CALLBACK (LA SOLUCIÓN AL ERROR)
# ==========================================
def accion_agregar(ticker_real, nombre_real):
    if ticker_real not in st.session_state.mis_tickers:
        st.session_state.mis_tickers.append(ticker_real)
        st.session_state.nombres_tickers[ticker_real] = nombre_real
        sincronizar_url() 
    # Vaciamos el buscador ANTES de que recargue la página
    st.session_state.buscador = ""

def accion_limpiar():
    # Vaciamos el buscador
    st.session_state.buscador = ""

# ==========================================
# BARRA DE BÚSQUEDA Y SELECTOR DE TIEMPO
# ==========================================
col_busqueda, col_tiempo = st.columns([2, 1])

with col_busqueda:
    texto_busqueda = st.text_input("🔍 Escribe qué buscas (Ej: Apple, oro, SQM) y presiona Enter:", key="buscador")
    
    if texto_busqueda:
        resultados = buscar_multiples_tickers(texto_busqueda)
        
        if resultados:
            mapa_opciones = {r["label"]: r for r in resultados}
            opcion_elegida = st.selectbox("👇 Se encontraron estas opciones. Selecciona la correcta:", list(mapa_opciones.keys()))
            
            datos_seleccionados = mapa_opciones[opcion_elegida]
            
            # MAGIA AQUÍ: Usamos on_click para llamar a la función de limpieza
            st.button("➕ Añadir al Dashboard", on_click=accion_agregar, args=(datos_seleccionados["symbol"], datos_seleccionados["name"]))
            
        else:
            st.warning("No encontramos nada con ese nombre. Intenta con otra palabra.")
            st.button("Limpiar búsqueda", on_click=accion_limpiar)

with col_tiempo:
    opciones_tiempo = {
        "1 Día": {"fetch": "60d", "interval": "5m", "dias_vista": 1},
        "1 Semana": {"fetch": "60d", "interval": "15m", "dias_vista": 7},
        "1 Mes": {"fetch": "2y", "interval": "1d", "dias_vista": 30},
        "3 Meses": {"fetch": "2y", "interval": "1d", "dias_vista": 90},
        "6 Meses": {"fetch": "2y", "interval": "1d", "dias_vista": 180},
        "YTD (Desde enero)": {"fetch": "2y", "interval": "1d", "dias_vista": "YTD"},
        "1 Año": {"fetch": "5y", "interval": "1d", "dias_vista": 365}
    }
    seleccion = st.selectbox("⏳ Período global:", list(opciones_tiempo.keys()))
    config = opciones_tiempo[seleccion]

if len(st.session_state.mis_tickers) > 1:
    if st.button("🗑️ Limpiar todo y dejar solo el primero"):
        st.session_state.mis_tickers = [st.session_state.mis_tickers[0]]
        sincronizar_url() 
        st.rerun()

st.divider()

# ==========================================
# RENDERIZAR TODOS LOS GRÁFICOS DINÁMICAMENTE
# ==========================================
columnas_grid = st.columns(2)

for i, ticker in enumerate(st.session_state.mis_tickers):
    
    col_actual = columnas_grid[i % 2]
    nombre_empresa = st.session_state.nombres_tickers.get(ticker, ticker)
    
    with col_actual:
        col_tit, col_izq, col_der, col_del = st.columns([5, 1, 1, 1])
        with col_tit:
            st.subheader(f"📊 {nombre_empresa} ({ticker})")
        with col_izq:
            if i > 0: 
                if st.button("◀", key=f"izq_{ticker}"):
                    st.session_state.mis_tickers[i], st.session_state.mis_tickers[i-1] = st.session_state.mis_tickers[i-1], st.session_state.mis_tickers[i]
                    sincronizar_url() 
                    st.rerun()
        with col_der:
            if i < len(st.session_state.mis_tickers) - 1: 
                if st.button("▶", key=f"der_{ticker}"):
                    st.session_state.mis_tickers[i], st.session_state.mis_tickers[i+1] = st.session_state.mis_tickers[i+1], st.session_state.mis_tickers[i]
                    sincronizar_url() 
                    st.rerun()
        with col_del:
            if st.button("❌", key=f"del_{ticker}"):
                st.session_state.mis_tickers.pop(i)
                sincronizar_url() 
                st.rerun()
        
        activo = yf.Ticker(ticker)
        hist_full = activo.history(period=config["fetch"], interval=config["interval"])

        if not hist_full.empty:
            fecha_fin = hist_full.index[-1]
            
            if config["dias_vista"] == "YTD":
                try:
                    fecha_inicio = hist_full[hist_full.index.year == fecha_fin.year].index[0]
                except:
                    fecha_inicio = hist_full.index[0]
            else:
                fecha_inicio = fecha_fin - pd.Timedelta(days=config["dias_vista"])

            hist_vista = hist_full[hist_full.index >= fecha_inicio]
            if hist_vista.empty: 
                hist_vista = hist_full 

            precio_actual = hist_vista['Close'].iloc[-1]
            precio_inicial = hist_vista['Close'].iloc[0] 
            
            variacion_usd = precio_actual - precio_inicial
            variacion_pct = (variacion_usd / precio_inicial) * 100

            if variacion_usd >= 0:
                color_linea = '#34c759'
                color_relleno = 'rgba(52, 199, 89, 0.1)'
            else:
                color_linea = '#ff3b30'
                color_relleno = 'rgba(255, 59, 48, 0.1)'

            st.metric(
                label=f"Precio Actual", 
                value=f"${precio_actual:.2f}",
                delta=f"{variacion_usd:.2f} ({variacion_pct:.2f}%)" 
            )

            fig = go.Figure()
            
            fig.add_trace(go.Scatter(
                x=hist_full.index, 
                y=hist_full['Close'], 
                mode='lines', 
                name='Precio',
                line=dict(color=color_linea, width=2.5), 
                fill='tozeroy', 
                fillcolor=color_relleno 
            ))

            fig.add_hline(
                y=precio_inicial, 
                line_dash="dot", 
                line_color="rgba(255, 255, 255, 0.4)", 
                line_width=1.5,
            )

            y_min = hist_vista['Close'].min()
            y_max = hist_vista['Close'].max()
            margen = (y_max - y_min) * 0.1 
            if margen == 0: margen = 1 
            
            limite_inferior = min(y_min, precio_inicial) - margen
            limite_superior = max(y_max, precio_inicial) + margen

            cortes_eje_x = [dict(bounds=["sat", "mon"])]
            if config["interval"] in ["5m", "15m"]:
                cortes_eje_x.append(dict(bounds=[16, 9.5], pattern="hour"))

            fig.update_layout(
                template="plotly_dark", 
                xaxis=dict(
                    range=[fecha_inicio, fecha_fin], 
                    showgrid=False,
                    rangebreaks=cortes_eje_x
                ), 
                yaxis=dict(
                    range=[limite_inferior, limite_superior], 
                    fixedrange=False, 
                    side="right", 
                    gridcolor="rgba(255,255,255,0.1)" 
                ), 
                dragmode="pan", 
                margin=dict(l=0, r=0, t=10, b=0), 
                height=300, 
                hovermode="x unified",
                showlegend=False
            )

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error(f"⚠️ No se encontraron datos para {ticker}. Revisa si está bien escrito.")

# ==========================================
# SWITCH DE AUTO-ACTUALIZACIÓN
# ==========================================
st.divider() 

col_auto1, col_auto2 = st.columns([1, 3])
with col_auto1:
    auto_refresh = st.toggle("🔄 Auto-Actualizar")
with col_auto2:
    if auto_refresh:
        st.caption("Actualizando automáticamente cada 1 minuto...")
        time.sleep(60) 
        st.rerun()
