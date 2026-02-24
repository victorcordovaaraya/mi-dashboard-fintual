import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd 
import time  
import requests 
from supabase import create_client, Client

# 1. MODO PANTALLA COMPLETA
st.set_page_config(page_title="Mi Portafolio", layout="wide", initial_sidebar_state="collapsed")

# ==========================================
# CONEXIÓN A BASE DE DATOS SUPABASE 🗄️
# ==========================================
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# Funciones de Transacciones
def obtener_transacciones():
    try: return supabase.table("transacciones").select("*").execute().data
    except: return []

def registrar_transaccion(ticker, tipo, cantidad, precio):
    supabase.table("transacciones").insert({
        "ticker": ticker, "tipo": tipo, "cantidad": cantidad, "precio_usd": precio
    }).execute()
    # Si compras o vendes, nos aseguramos que esté en tu watchlist
    agregar_watchlist(ticker)

# ¡NUEVO! Funciones de Watchlist (Adiós al Link)
def obtener_watchlist():
    try: return [r['ticker'] for r in supabase.table("watchlist").select("ticker").execute().data]
    except: return []

def agregar_watchlist(ticker):
    try: supabase.table("watchlist").upsert({"ticker": ticker}).execute()
    except: pass

def eliminar_watchlist(ticker):
    try: supabase.table("watchlist").delete().eq("ticker", ticker).execute()
    except: pass

# ==========================================
# LA MEMORIA PERSISTENTE (SIN URL)
# ==========================================
if "mis_tickers" not in st.session_state:
    st.session_state.mis_tickers = obtener_watchlist()
    if not st.session_state.mis_tickers:
        st.session_state.mis_tickers = ["VAW"] # Por defecto si está vacía
        agregar_watchlist("VAW")

if "nombres_tickers" not in st.session_state:
    st.session_state.nombres_tickers = {}

# Borramos cualquier rastro de st.query_params (Matamos el link)

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
    except: pass
    return resultados

for t in st.session_state.mis_tickers:
    if t not in st.session_state.nombres_tickers:
        r = buscar_multiples_tickers(t)
        st.session_state.nombres_tickers[t] = r[0]["name"] if r else t

def accion_agregar(ticker_real, nombre_real):
    if ticker_real not in st.session_state.mis_tickers:
        st.session_state.mis_tickers.append(ticker_real)
        st.session_state.nombres_tickers[ticker_real] = nombre_real
        agregar_watchlist(ticker_real)
    st.session_state.buscador = ""

# ==========================================
# 🧠 CÁLCULO DE LIBRO MAYOR (MÉTODO FIFO Y PRECIO DE VENTA)
# ==========================================
tx_data = obtener_transacciones()
df_tx = pd.DataFrame(tx_data)
mis_posiciones = {}
ganancia_realizada_total = 0.0

if not df_tx.empty:
    for ticker in df_tx['ticker'].unique():
        df_t = df_tx[df_tx['ticker'] == ticker].copy()
        df_t = df_t.sort_values('fecha') 
        
        lote_compras = [] 
        ganancia_cobrada_fifo = 0.0
        ultimo_precio_venta = 0.0 # ¡Para el Radar de Oportunidades!
        
        for _, row in df_t.iterrows():
            cant = float(row['cantidad'])
            precio = float(row['precio_usd'])
            
            if row['tipo'] == 'COMPRA':
                lote_compras.append({'qty': cant, 'price': precio})
            elif row['tipo'] == 'VENTA':
                ultimo_precio_venta = precio
                cant_a_vender = cant
                while cant_a_vender > 0 and lote_compras:
                    compra_mas_antigua = lote_compras[0]
                    if compra_mas_antigua['qty'] <= cant_a_vender:
                        ganancia_cobrada_fifo += compra_mas_antigua['qty'] * (precio - compra_mas_antigua['price'])
                        cant_a_vender -= compra_mas_antigua['qty']
                        lote_compras.pop(0)
                    else:
                        ganancia_cobrada_fifo += cant_a_vender * (precio - compra_mas_antigua['price'])
                        compra_mas_antigua['qty'] -= cant_a_vender
                        cant_a_vender = 0

        cuotas_restantes = sum(lote['qty'] for lote in lote_compras)
        costo_total_restante = sum(lote['qty'] * lote['price'] for lote in lote_compras)
        precio_medio_final = costo_total_restante / cuotas_restantes if cuotas_restantes > 0 else 0.0
        
        mis_posiciones[ticker] = {
            'cuotas': cuotas_restantes,
            'precio_medio': precio_medio_final,
            'ganancia_realizada': ganancia_cobrada_fifo,
            'ultimo_precio_venta': ultimo_precio_venta
        }
        ganancia_realizada_total += ganancia_cobrada_fifo

# ==========================================
# MENÚ LATERAL: TERMINAL Y CONFIGURACIÓN
# ==========================================
with st.sidebar:
    st.title("💼 Mi Terminal")
    with st.expander("📝 Ingreso Manual", expanded=False):
        with st.form("form_transaccion"):
            t_ticker = st.selectbox("Acción:", st.session_state.mis_tickers)
            t_tipo = st.radio("Tipo:", ["COMPRA", "VENTA"], horizontal=True)
            t_cant = st.number_input("Cuotas:", min_value=0.001, step=0.1, format="%.3f")
            t_precio = st.number_input("Precio ($ USD):", min_value=0.01, step=1.0)
            if st.form_submit_button("💾 Guardar"):
                registrar_transaccion(t_ticker, t_tipo, t_cant, t_precio)
                st.success("Registrado.")
                time.sleep(1)
                st.rerun()

    if "tasa_impuesto" not in st.session_state:
        st.session_state.tasa_impuesto = 0.0
        
    with st.expander("⚙️ Configuración SII (Impuestos)"):
        tramos_sii = {
            "Exento (< $850k)": 0.0, "Tramo 1 ($850k a $1.9M)": 4.0, "Tramo 2 ($1.9M a $3.2M)": 8.0,
            "Tramo 3 ($3.2M a $4.5M)": 13.5, "Tramo 4 ($4.5M a $5.7M)": 23.0, "Tramo 5 ($5.7M a $7.6M)": 30.4, "Tramo 6 (> $7.6M)": 35.0
        }
        seleccion_tramo = st.selectbox("Sueldo Mensual:", list(tramos_sii.keys()))
        st.session_state.tasa_impuesto = tramos_sii[seleccion_tramo]
        st.caption(f"Tasa a retener: **{st.session_state.tasa_impuesto}%**")

# ==========================================
# 🧠 FASE 2: EL ANALISTA FUNDAMENTAL 
# ==========================================
@st.cache_data(ttl=3600) 
def obtener_fundamentales(ticker):
    try:
        info = yf.Ticker(ticker).info
        pe = info.get('trailingPE', info.get('forwardPE', None))
        margen = info.get('profitMargins', None)
        if margen is None: return "⚪ ETF/Fondo (No aplica fundamental)."
        margen_pct = margen * 100
        if margen_pct < 0: return f"🔴 **RIESGO:** Empresa perdiendo plata (Margen: {margen_pct:.1f}%)."
        elif pe is not None and pe > 40: return f"🟡 **REGULAR:** Gana plata pero está cara (P/E: {pe:.1f})."
        else: return f"🟢 **SÓLIDA:** Negocio sano (P/E: {pe:.1f}, Margen: {margen_pct:.1f}%)."
    except: return "⚪ Datos fundamentales no disponibles."

# ==========================================
# INTERFAZ PRINCIPAL Y BÚSQUEDA
# ==========================================
col_busqueda, col_tiempo = st.columns([2, 1])
with col_busqueda:
    texto_busqueda = st.text_input("🔍 Escribe qué buscas (Ej: Apple, oro, SQM) y presiona Enter:", key="buscador")
    if texto_busqueda:
        resultados = buscar_multiples_tickers(texto_busqueda)
        if resultados:
            mapa_opciones = {r["label"]: r for r in resultados}
            opcion_elegida = st.selectbox("👇 Selecciona la correcta:", list(mapa_opciones.keys()))
            datos_seleccionados = mapa_opciones[opcion_elegida]
            st.button("➕ Añadir al Dashboard", on_click=accion_agregar, args=(datos_seleccionados["symbol"], datos_seleccionados["name"]))

with col_tiempo:
    opciones_tiempo = {
        "1 Mes": {"fetch": "2y", "interval": "1d", "dias_vista": 30},
        "3 Meses": {"fetch": "2y", "interval": "1d", "dias_vista": 90},
        "6 Meses": {"fetch": "2y", "interval": "1d", "dias_vista": 180},
        "YTD (Desde enero)": {"fetch": "2y", "interval": "1d", "dias_vista": "YTD"},
        "1 Año": {"fetch": "5y", "interval": "1d", "dias_vista": 365}
    }
    seleccion = st.selectbox("⏳ Período global:", list(opciones_tiempo.keys()))
    config = opciones_tiempo[seleccion]

st.divider()

# ==========================================
# DESCARGA DE DATOS DE YFINANCE
# ==========================================
def calcular_indicadores(df):
    delta = df['Close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=13, adjust=False).mean()
    ema_down = down.ewm(com=13, adjust=False).mean()
    rs = ema_up / ema_down
    df['RSI'] = 100 - (100 / (1 + rs))
    df['Max_Periodo'] = df['Close'].cummax()
    df['Caida_Desde_Max'] = ((df['Close'] - df['Max_Periodo']) / df['Max_Periodo']) * 100
    return df

datos_portafolio = {}
cortes_eje_x = [dict(bounds=["sat", "mon"])]

# Filtramos las acciones en 2 grupos: ACTIVAS (cuotas>0) y RADAR (cuotas=0)
activos_activos = []
activos_radar = []

for ticker in st.session_state.mis_tickers:
    pos = mis_posiciones.get(ticker, {'cuotas': 0.0})
    if pos['cuotas'] > 0:
        activos_activos.append(ticker)
    else:
        activos_radar.append(ticker)

    activo = yf.Ticker(ticker)
    hist_full = activo.history(period=config["fetch"], interval=config["interval"])
    if not hist_full.empty:
        hist_full = calcular_indicadores(hist_full)
        fecha_fin = hist_full.index[-1]
        if config["dias_vista"] == "YTD":
            try: fecha_inicio = hist_full[hist_full.index.year == fecha_fin.year].index[0]
            except: fecha_inicio = hist_full.index[0]
        else:
            fecha_inicio = fecha_fin - pd.Timedelta(days=config["dias_vista"])
        hist_vista = hist_full[hist_full.index >= fecha_inicio]
        if hist_vista.empty: hist_vista = hist_full 
        datos_portafolio[ticker] = {"full": hist_full, "vista": hist_vista, "inicio": fecha_inicio, "fin": fecha_fin}

# ==========================================
# RESUMEN PATRIMONIO E IMPUESTOS
# ==========================================
total_invertido = sum(mis_posiciones.get(t, {}).get('cuotas', 0) * mis_posiciones.get(t, {}).get('precio_medio', 0) for t in activos_activos)
total_actual = sum(mis_posiciones.get(t, {}).get('cuotas', 0) * datos_portafolio[t]["vista"]['Close'].iloc[-1] for t in activos_activos if t in datos_portafolio)

ganancia_flotante_usd = total_actual - total_invertido
desempeño_historico_total = ganancia_flotante_usd + ganancia_realizada_total
provision_sii_usd = ganancia_realizada_total * (st.session_state.tasa_impuesto / 100) if ganancia_realizada_total > 0 else 0.0

st.subheader("🏦 Mi Patrimonio Histórico y Tributario (USD)")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("💰 Inversión Activa", f"${total_invertido:,.2f}")
col2.metric("💵 Valor Actual", f"${total_actual:,.2f}", f"{ganancia_flotante_usd:,.2f} Flotante")
col3.metric("💼 Ganancia Bruta Cobrada", f"${ganancia_realizada_total:,.2f}")
col4.metric("🏛️ Provisión SII (Reserva)", f"-${provision_sii_usd:,.2f}")
col5.metric("🏆 Desempeño Total Neto", f"${desempeño_historico_total - provision_sii_usd:,.2f}")
st.divider()

# ==========================================
# GRÁFICO GLOBAL (SÓLO ACTIVAS)
# ==========================================
if activos_activos and any(t in datos_portafolio for t in activos_activos):
    st.subheader("🌐 Rendimiento de mis Acciones Activas (%)")
    fig_global = go.Figure()
    
    global_y_min, global_y_max = float('inf'), float('-inf')
    for ticker in activos_activos:
        if ticker in datos_portafolio:
            hist_full = datos_portafolio[ticker]["full"]
            hist_vista = datos_portafolio[ticker]["vista"]
            precio_base = hist_vista['Close'].iloc[0]
            rendimiento_pct = ((hist_full['Close'] - precio_base) / precio_base) * 100
            global_y_min = min(global_y_min, rendimiento_pct.min())
            global_y_max = max(global_y_max, rendimiento_pct.max())
            fig_global.add_trace(go.Scatter(x=hist_full.index, y=rendimiento_pct, mode='lines', name=ticker))

    fig_global.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.5)")
    fig_global.update_layout(template="plotly_dark", height=350, margin=dict(l=0,r=0,t=10,b=0), hovermode="x unified")
    st.plotly_chart(fig_global, use_container_width=True)
    st.divider()

# ==========================================
# SECCIÓN: MIS INVERSIONES ACTIVAS
# ==========================================
if activos_activos:
    st.subheader("📈 Mis Inversiones Activas")
    columnas_grid = st.columns(3)
    
    for i, ticker in enumerate(activos_activos):
        if ticker not in datos_portafolio: continue
        col_actual = columnas_grid[i % 3]
        nombre_empresa = st.session_state.nombres_tickers.get(ticker, ticker)
        datos_pos = mis_posiciones[ticker]
        hist_vista = datos_portafolio[ticker]["vista"]
        precio_actual = hist_vista['Close'].iloc[-1]
        
        with col_actual:
            col_t, col_del = st.columns([5, 1])
            col_t.markdown(f"**{nombre_empresa} ({ticker})**")
            if col_del.button("❌", key=f"del_{ticker}"):
                eliminar_watchlist(ticker)
                st.session_state.mis_tickers.remove(ticker)
                st.rerun()
                
            # Lógica Técnica y Fundamental
            rsi_actual = hist_vista['RSI'].iloc[-1]
            if rsi_actual > 70: msj_tec = f"🔴 **Técnico:** Sobrecomprada (RSI: {rsi_actual:.0f})"
            elif rsi_actual < 30: msj_tec = f"🟢 **Técnico:** Sobrevendida (RSI: {rsi_actual:.0f})"
            else: msj_tec = f"🟡 **Técnico:** Normal (RSI: {rsi_actual:.0f})"
            st.caption(f"{msj_tec}\n\n{obtener_fundamentales(ticker)}")

            ganancia_usd = (precio_actual - datos_pos['precio_medio']) * datos_pos['cuotas']
            ganancia_pct = (ganancia_usd / (datos_pos['precio_medio'] * datos_pos['cuotas'])) * 100 if datos_pos['precio_medio'] > 0 else 0
            st.metric(f"Posición ({datos_pos['cuotas']:.2f}c)", f"${precio_actual * datos_pos['cuotas']:,.2f}", f"{ganancia_usd:,.2f} USD ({ganancia_pct:.2f}%)")
            
            # ¡BOTÓN VENDER TODO!
            if st.button("💰 Vender Todo AHORA", key=f"sell_{ticker}", use_container_width=True):
                registrar_transaccion(ticker, "VENTA", datos_pos['cuotas'], precio_actual)
                st.success(f"¡Vendiste todo {ticker} a ${precio_actual:.2f}!")
                time.sleep(1.5)
                st.rerun()

            fig = go.Figure(go.Scatter(x=hist_vista.index, y=hist_vista['Close'], line=dict(color='#34c759' if ganancia_usd >= 0 else '#ff3b30')))
            fig.add_hline(y=datos_pos['precio_medio'], line_dash="dash", line_color="#ffd60a", annotation_text="Mi Compra")
            fig.update_layout(template="plotly_dark", height=200, margin=dict(l=0,r=0,t=0,b=0), xaxis=dict(visible=False))
            st.plotly_chart(fig, use_container_width=True)

st.divider()

# ==========================================
# SECCIÓN: RADAR DE OPORTUNIDADES (Cementerio Inteligente) 🧟‍♂️📈
# ==========================================
if activos_radar:
    st.subheader("🎯 Radar de Oportunidades (Acciones que vendiste o sigues)")
    st.caption("La app compara el precio actual con el último precio al que vendiste para decirte si conviene recomprar.")
    
    columnas_radar = st.columns(3)
    
    for i, ticker in enumerate(activos_radar):
        if ticker not in datos_portafolio: continue
        col_actual = columnas_radar[i % 3]
        nombre_empresa = st.session_state.nombres_tickers.get(ticker, ticker)
        datos_pos = mis_posiciones.get(ticker, {'ultimo_precio_venta': 0.0})
        ultimo_precio = datos_pos.get('ultimo_precio_venta', 0.0)
        
        hist_vista = datos_portafolio[ticker]["vista"]
        precio_actual = hist_vista['Close'].iloc[-1]
        
        with col_actual:
            with st.container(border=True):
                col_t, col_del = st.columns([5, 1])
                col_t.markdown(f"**{ticker}**")
                if col_del.button("❌", key=f"del_rad_{ticker}"):
                    eliminar_watchlist(ticker)
                    st.session_state.mis_tickers.remove(ticker)
                    st.rerun()
                
                # Cálculo de descuento frente a tu venta
                if ultimo_precio > 0:
                    dif_usd = precio_actual - ultimo_precio
                    dif_pct = (dif_usd / ultimo_precio) * 100
                    if dif_usd < 0:
                        st.success(f"🔥 ¡Está {abs(dif_pct):.1f}% MÁS BARATA que cuando la vendiste (${ultimo_precio:.1f})!")
                    else:
                        st.warning(f"Está {dif_pct:.1f}% más cara que cuando la vendiste (${ultimo_precio:.1f}).")
                else:
                    st.info("Solo en seguimiento (Nunca comprada).")

                # Analítica
                rsi_actual = hist_vista['RSI'].iloc[-1]
                if rsi_actual < 30: st.markdown("🟢 **RSI: Sobrevendida. ¡Buena opción de recompra!**")
                elif rsi_actual > 70: st.markdown("🔴 **RSI: Muy cara todavía. Sigue esperando.**")
                else: st.markdown("🟡 **RSI: Terreno neutral.**")
                
                st.metric("Precio Mercado", f"${precio_actual:.2f}")
