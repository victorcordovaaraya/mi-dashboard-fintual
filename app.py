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
# CONEXIÓN A BASE DE DATOS Y API DÓLAR 🗄️💵
# ==========================================
@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()

@st.cache_data(ttl=600) # Se actualiza cada 10 min
def obtener_dolar_actual():
    try: return float(yf.Ticker("CLP=X").history(period="1d")['Close'].iloc[-1])
    except: return 950.0 # Dólar de emergencia si falla la bolsa

dolar_hoy = obtener_dolar_actual()

# --- Funciones BD ---
def obtener_transacciones():
    try: return supabase.table("transacciones").select("*").execute().data
    except: return []

def registrar_transaccion(ticker, tipo, cantidad, precio, fx_dolar):
    supabase.table("transacciones").insert({
        "ticker": ticker, "tipo": tipo, "cantidad": cantidad, "precio_usd": precio, "precio_dolar_clp": fx_dolar
    }).execute()
    agregar_watchlist(ticker)

def obtener_watchlist():
    try: return [r['ticker'] for r in supabase.table("watchlist").select("ticker").execute().data]
    except: return []

def agregar_watchlist(ticker):
    try: supabase.table("watchlist").upsert({"ticker": ticker}).execute()
    except: pass

def eliminar_watchlist(ticker):
    try: supabase.table("watchlist").delete().eq("ticker", ticker).execute()
    except: pass

def obtener_configuracion():
    try:
        res = supabase.table("configuracion").select("*").eq("id", 1).execute()
        if res.data: return res.data[0]
    except: pass
    return {"tasa_sii": 0.0, "tramo_nombre": "Exento (< $850k)"}

def guardar_configuracion(tasa, nombre):
    try: supabase.table("configuracion").upsert({"id": 1, "tasa_sii": tasa, "tramo_nombre": nombre}).execute()
    except: pass

# ==========================================
# LA MEMORIA PERSISTENTE 
# ==========================================
if "mis_tickers" not in st.session_state:
    st.session_state.mis_tickers = obtener_watchlist()
    if not st.session_state.mis_tickers:
        st.session_state.mis_tickers = ["VAW"] 
        agregar_watchlist("VAW")

if "nombres_tickers" not in st.session_state: st.session_state.nombres_tickers = {}

if "config_cargada" not in st.session_state:
    config_db = obtener_configuracion()
    st.session_state.tasa_impuesto = config_db["tasa_sii"]
    st.session_state.tramo_nombre = config_db["tramo_nombre"]
    st.session_state.config_cargada = True

# ==========================================
# MOTOR DE BÚSQUEDA 
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
                    resultados.append({"symbol": simbolo, "name": q.get('shortname', simbolo), "label": f"{simbolo} - {q.get('shortname', simbolo)}"})
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

# ==========================================
# 🧠 CÁLCULO DE LIBRO MAYOR (BIMONETARIO: USD y CLP)
# ==========================================
tx_data = obtener_transacciones()
df_tx = pd.DataFrame(tx_data)
mis_posiciones = {}
ganancia_realizada_total_usd = 0.0
ganancia_realizada_total_clp = 0.0

if not df_tx.empty:
    if 'precio_dolar_clp' not in df_tx.columns: df_tx['precio_dolar_clp'] = dolar_hoy
    
    for ticker in df_tx['ticker'].unique():
        df_t = df_tx[df_tx['ticker'] == ticker].copy().sort_values('fecha') 
        
        lote_compras = [] 
        gan_usd_ticker = 0.0
        gan_clp_ticker = 0.0
        ultimo_precio_venta = 0.0 
        
        for _, row in df_t.iterrows():
            cant = float(row['cantidad'])
            precio = float(row['precio_usd'])
            fx_tx = float(row['precio_dolar_clp']) if pd.notnull(row['precio_dolar_clp']) else dolar_hoy
            
            if row['tipo'] == 'COMPRA':
                lote_compras.append({'qty': cant, 'price': precio, 'fx': fx_tx})
            elif row['tipo'] == 'VENTA':
                ultimo_precio_venta = precio
                cant_a_vender = cant
                while cant_a_vender > 0 and lote_compras:
                    compra_antigua = lote_compras[0]
                    qty_vendida = min(compra_antigua['qty'], cant_a_vender)
                    
                    # Ganancia en USD (Precio venta - Precio compra) * cuotas
                    gan_usd_ticker += qty_vendida * (precio - compra_antigua['price'])
                    # Ganancia real en CLP (Plata que entra en CLP - Plata que salió en CLP al comprar)
                    gan_clp_ticker += (qty_vendida * precio * fx_tx) - (qty_vendida * compra_antigua['price'] * compra_antigua['fx'])
                    
                    if compra_antigua['qty'] <= cant_a_vender:
                        cant_a_vender -= qty_vendida
                        lote_compras.pop(0)
                    else:
                        compra_antigua['qty'] -= qty_vendida
                        cant_a_vender = 0

        cuotas_restantes = sum(l['qty'] for l in lote_compras)
        costo_total_usd = sum(l['qty'] * l['price'] for l in lote_compras)
        costo_total_clp = sum(l['qty'] * l['price'] * l['fx'] for l in lote_compras)
        
        mis_posiciones[ticker] = {
            'cuotas': cuotas_restantes,
            'precio_medio_usd': costo_total_usd / cuotas_restantes if cuotas_restantes > 0 else 0.0,
            'costo_total_clp': costo_total_clp,
            'ultimo_precio_venta': ultimo_precio_venta
        }
        ganancia_realizada_total_usd += gan_usd_ticker
        ganancia_realizada_total_clp += gan_clp_ticker

# ==========================================
# MENÚ LATERAL: TERMINAL Y CONFIGURACIÓN
# ==========================================
with st.sidebar:
    st.title("💼 Mi Terminal")
    st.metric("Dólar Mercado Hoy", f"${dolar_hoy:,.1f} CLP")
    
    with st.expander("📝 Ingreso Manual", expanded=False):
        with st.form("form_transaccion"):
            t_ticker = st.selectbox("Acción:", st.session_state.mis_tickers)
            t_tipo = st.radio("Tipo:", ["COMPRA", "VENTA"], horizontal=True)
            t_cant = st.number_input("Cuotas:", min_value=0.001, step=0.1, format="%.3f")
            t_precio = st.number_input("Precio ($ USD):", min_value=0.01, step=1.0)
            t_fx = st.number_input("Tipo de Cambio cobrado (CLP):", value=float(dolar_hoy), step=1.0)
            
            if st.form_submit_button("💾 Guardar"):
                registrar_transaccion(t_ticker, t_tipo, t_cant, t_precio, t_fx)
                st.success("Registrado.")
                time.sleep(1)
                st.rerun()
        
    with st.expander("⚙️ Configuración SII (Impuestos)"):
        tramos_sii = {
            "Exento (< $850k)": 0.0, "Tramo 1 ($850k a $1.9M)": 4.0, "Tramo 2 ($1.9M a $3.2M)": 8.0,
            "Tramo 3 ($3.2M a $4.5M)": 13.5, "Tramo 4 ($4.5M a $5.7M)": 23.0, "Tramo 5 ($5.7M a $7.6M)": 30.4, "Tramo 6 (> $7.6M)": 35.0
        }
        lista_tramos = list(tramos_sii.keys())
        indice_actual = lista_tramos.index(st.session_state.tramo_nombre) if st.session_state.tramo_nombre in lista_tramos else 0
        seleccion_tramo = st.selectbox("Sueldo Mensual:", lista_tramos, index=indice_actual)
        
        if seleccion_tramo != st.session_state.tramo_nombre:
            st.session_state.tramo_nombre = seleccion_tramo
            st.session_state.tasa_impuesto = tramos_sii[seleccion_tramo]
            guardar_configuracion(st.session_state.tasa_impuesto, st.session_state.tramo_nombre)
            st.rerun()
        st.caption(f"Tasa a retener SII: **{st.session_state.tasa_impuesto}%**")

# ==========================================
# INTERFAZ PRINCIPAL Y DESCARGA DATOS
# ==========================================
st.title("Finanzas 📈🇨🇱")
col_busqueda, col_tiempo = st.columns([2, 1])
with col_busqueda:
    texto_busqueda = st.text_input("🔍 Escribe qué buscas (Ej: Apple, SQM) y presiona Enter:")
    if texto_busqueda:
        resultados = buscar_multiples_tickers(texto_busqueda)
        if resultados:
            opcion_elegida = st.selectbox("👇 Selecciona la correcta:", list({r["label"]: r for r in resultados}.keys()))
            st.button("➕ Añadir al Dashboard", on_click=accion_agregar, args=({r["label"]: r for r in resultados}[opcion_elegida]["symbol"], {r["label"]: r for r in resultados}[opcion_elegida]["name"]))

with col_tiempo:
    opciones_tiempo = {"1 Mes": "1mo", "3 Meses": "3mo", "6 Meses": "6mo", "1 Año": "1y"}
    config_fetch = opciones_tiempo[st.selectbox("⏳ Período:", list(opciones_tiempo.keys()))]

st.divider()

# Descarga de datos
def calcular_rsi(df):
    delta = df['Close'].diff()
    rs = delta.clip(lower=0).ewm(com=13, adjust=False).mean() / (-1 * delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

datos_portafolio = {}
activos_activos = [t for t, p in mis_posiciones.items() if p['cuotas'] > 0]
activos_radar = [t for t in st.session_state.mis_tickers if t not in activos_activos]

for ticker in st.session_state.mis_tickers:
    hist_full = yf.Ticker(ticker).history(period=config_fetch, interval="1d")
    if not hist_full.empty:
        datos_portafolio[ticker] = calcular_rsi(hist_full)

# ==========================================
# RESUMEN PATRIMONIO EN PESOS CHILENOS (CLP) 🏦🇨🇱
# ==========================================
total_invertido_clp = sum(mis_posiciones.get(t, {}).get('costo_total_clp', 0.0) for t in activos_activos)
total_actual_usd = sum(mis_posiciones.get(t, {}).get('cuotas', 0) * datos_portafolio[t]['Close'].iloc[-1] for t in activos_activos if t in datos_portafolio)
total_actual_clp = total_actual_usd * dolar_hoy # Valorizado al dólar de HOY

ganancia_flotante_clp = total_actual_clp - total_invertido_clp
desempeño_historico_total_clp = ganancia_flotante_clp + ganancia_realizada_total_clp
provision_sii_clp = ganancia_realizada_total_clp * (st.session_state.tasa_impuesto / 100) if ganancia_realizada_total_clp > 0 else 0.0

st.subheader("🏦 Mi Patrimonio Real en Chile (CLP)")
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("💰 Inversión Activa", f"${total_invertido_clp:,.0f} CLP")
col2.metric("💵 Valor Actual", f"${total_actual_clp:,.0f} CLP", f"{ganancia_flotante_clp:,.0f} CLP Flotante")
col3.metric("💼 Ganancia Bruta Cobrada", f"${ganancia_realizada_total_clp:,.0f} CLP")
col4.metric("🏛️ Provisión SII", f"-${provision_sii_clp:,.0f} CLP")
col5.metric("🏆 Desempeño Neto Total", f"${desempeño_historico_total_clp - provision_sii_clp:,.0f} CLP")
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
        hist_vista = datos_portafolio[ticker]
        precio_actual_usd = hist_vista['Close'].iloc[-1]
        
        with col_actual:
            with st.container(border=True):
                col_t, col_del = st.columns([5, 1])
                col_t.markdown(f"**{nombre_empresa} ({ticker})**")
                if col_del.button("❌", key=f"del_{ticker}"):
                    eliminar_watchlist(ticker)
                    st.session_state.mis_tickers.remove(ticker)
                    st.rerun()

                # Cálculo de ganancia individual en CLP
                inversion_inicial_clp = datos_pos['costo_total_clp']
                valor_hoy_clp = (datos_pos['cuotas'] * precio_actual_usd) * dolar_hoy
                ganancia_clp = valor_hoy_clp - inversion_inicial_clp
                ganancia_pct_clp = (ganancia_clp / inversion_inicial_clp) * 100 if inversion_inicial_clp > 0 else 0
                
                st.metric(f"Posición ({datos_pos['cuotas']:.2f}c) a ${precio_actual_usd:.2f} USD", 
                          f"${valor_hoy_clp:,.0f} CLP", 
                          f"{ganancia_clp:,.0f} CLP ({ganancia_pct_clp:.1f}%)")
                
                if st.button("💰 Vender Todo AHORA", key=f"sell_{ticker}", use_container_width=True):
                    # Al vender todo rápido, asume el dólar del mercado hoy
                    registrar_transaccion(ticker, "VENTA", datos_pos['cuotas'], precio_actual_usd, dolar_hoy)
                    st.success("¡Vendido!")
                    time.sleep(1)
                    st.rerun()

                fig = go.Figure(go.Scatter(x=hist_vista.index, y=hist_vista['Close'], line=dict(color='#34c759' if ganancia_clp >= 0 else '#ff3b30')))
                fig.add_hline(y=datos_pos['precio_medio_usd'], line_dash="dash", line_color="#ffd60a", annotation_text="Compra (USD)")
                fig.update_layout(template="plotly_dark", height=150, margin=dict(l=0,r=0,t=0,b=0), xaxis=dict(visible=False), yaxis=dict(visible=False))
                st.plotly_chart(fig, use_container_width=True)

st.divider()

# ==========================================
# 🎯 SECCIÓN: RADAR DE OPORTUNIDADES
# ==========================================
if activos_radar:
    st.subheader("🎯 Radar de Seguimiento y Oportunidades")
    col_tabla, col_grafico = st.columns([2, 3])
    datos_tabla = []
    fig_radar = go.Figure()
    
    for ticker in activos_radar:
        if ticker not in datos_portafolio: continue
        ultimo_precio = mis_posiciones.get(ticker, {}).get('ultimo_precio_venta', 0.0)
        hist_full = datos_portafolio[ticker]
        precio_actual = hist_full['Close'].iloc[-1]
        rsi_actual = hist_full['RSI'].iloc[-1]
        
        if ultimo_precio > 0:
            dif_pct = ((precio_actual - ultimo_precio) / ultimo_precio) * 100
            if dif_pct < 0 and rsi_actual > 40: est, pri = "🔥 REMONTANDO", 1
            elif dif_pct < 0 and rsi_actual <= 40: est, pri = "📉 Cayendo", 3
            else: est, pri = "📈 Cara", 2
            precio_base = ultimo_precio
        else:
            precio_base = hist_full['Close'].iloc[0]
            dif_pct = ((precio_actual - precio_base) / precio_base) * 100
            est, pri = "⚪ Seguimiento", 2 if rsi_actual > 40 else 3

        datos_tabla.append({"Ticker": ticker, "Venta USD": f"${ultimo_precio:.2f}", "Hoy USD": f"${precio_actual:.2f}", "Estado": est, "_p": pri})
        fig_radar.add_trace(go.Scatter(x=hist_full.index, y=((hist_full['Close'] - precio_base)/precio_base)*100, mode='lines', name=ticker))

    if datos_tabla:
        df_radar = pd.DataFrame(datos_tabla).sort_values(by="_p").drop(columns=["_p"])
        with col_tabla: st.dataframe(df_radar, hide_index=True, use_container_width=True)

    with col_grafico:
        fig_radar.add_hline(y=0, line_dash="dash", line_color="#ffffff")
        fig_radar.update_layout(template="plotly_dark", height=300, margin=dict(l=0,r=0,t=10,b=0), yaxis=dict(side="right", ticksuffix="%"))
        st.plotly_chart(fig_radar, use_container_width=True)
