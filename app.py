import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd 
import time  
import requests 
from database import obtener_transacciones, registrar_transaccion, obtener_watchlist, agregar_watchlist, eliminar_watchlist, obtener_configuracion, guardar_configuracion

# ==========================================
# BLOQUE 1: CONFIGURACIÓN INICIAL
# ==========================================
st.set_page_config(page_title="Mi Portafolio", layout="wide", initial_sidebar_state="collapsed")

@st.cache_data(ttl=600)
def obtener_dolar_actual():
    try: return float(yf.Ticker("CLP=X").history(period="1d")['Close'].iloc[-1])
    except: return 950.0 

dolar_hoy = obtener_dolar_actual()

# ==========================================
# BLOQUE 2: MEMORIA PERSISTENTE (SESSION STATE)
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
# BLOQUE 3: MOTOR DE BÚSQUEDA
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
# BLOQUE 4: CÁLCULO DE LIBRO MAYOR (FIFO BIMONETARIO)
# ==========================================
tx_data = obtener_transacciones()
df_tx = pd.DataFrame(tx_data)
mis_posiciones = {}
ganancia_realizada_total_clp = 0.0

if not df_tx.empty:
    if 'precio_dolar_clp' not in df_tx.columns: df_tx['precio_dolar_clp'] = dolar_hoy
    for ticker in df_tx['ticker'].unique():
        df_t = df_tx[df_tx['ticker'] == ticker].copy().sort_values('fecha') 
        lote_compras = [] 
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
        ganancia_realizada_total_clp += gan_clp_ticker

# ==========================================
# BLOQUE 5: MENÚ LATERAL (TERMINAL Y SII)
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
        tramos_sii = {"Exento (< $850k)": 0.0, "Tramo 1 ($850k a $1.9M)": 4.0, "Tramo 2 ($1.9M a $3.2M)": 8.0, "Tramo 3 ($3.2M a $4.5M)": 13.5, "Tramo 4 ($4.5M a $5.7M)": 23.0, "Tramo 5 ($5.7M a $7.6M)": 30.4, "Tramo 6 (> $7.6M)": 35.0}
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
# BLOQUE 6: ANÁLISIS FUNDAMENTAL
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
        elif pe is not None and pe > 40: return f"🟡 **REGULAR:** Gana plata pero cara (P/E: {pe:.1f})."
        else: return f"🟢 **SÓLIDA:** Negocio sano (P/E: {pe:.1f}, Margen: {margen_pct:.1f}%)."
    except: return "⚪ Datos no disponibles."

# ==========================================
# BLOQUE 7: INTERFAZ PRINCIPAL Y BÚSQUEDA
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
    opciones_tiempo = {"1 Día": {"fetch": "5d", "interval": "5m", "dias_vista": 1}, "1 Semana": {"fetch": "1mo", "interval": "15m", "dias_vista": 7}, "1 Mes": {"fetch": "2y", "interval": "1d", "dias_vista": 30}, "3 Meses": {"fetch": "2y", "interval": "1d", "dias_vista": 90}, "6 Meses": {"fetch": "2y", "interval": "1d", "dias_vista": 180}, "YTD (Desde enero)": {"fetch": "2y", "interval": "1d", "dias_vista": "YTD"}, "1 Año": {"fetch": "5y", "interval": "1d", "dias_vista": 365}}
    seleccion = st.selectbox("⏳ Período global:", list(opciones_tiempo.keys()))
    config = opciones_tiempo[seleccion]

st.divider()

# ==========================================
# BLOQUE 8: DESCARGA DE DATOS Y TÉCNICO (RSI)
# ==========================================
def calcular_indicadores(df):
    delta = df['Close'].diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=13, adjust=False).mean()
    ema_down = down.ewm(com=13, adjust=False).mean()
    rs = ema_up / ema_down
    df['RSI'] = 100 - (100 / (1 + rs))
    return df

datos_portafolio = {}
activos_activos = [t for t, p in mis_posiciones.items() if p['cuotas'] > 0]
activos_radar = [t for t in st.session_state.mis_tickers if t not in activos_activos]

for ticker in st.session_state.mis_tickers:
    activo = yf.Ticker(ticker)
    hist_full = activo.history(period=config["fetch"], interval=config["interval"])
    if not hist_full.empty:
        if hist_full.index.tz is not None:
            hist_full.index = hist_full.index.tz_localize(None)
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

cortes_eje_x = [dict(bounds=["sat", "mon"])]
if config["interval"] in ["5m", "15m"]: 
    cortes_eje_x.append(dict(bounds=[16, 9.5], pattern="hour"))

if datos_portafolio:
    todas_fechas = pd.DatetimeIndex([])
    for t in datos_portafolio:
        todas_fechas = todas_fechas.union(datos_portafolio[t]["full"].index.normalize())
    todas_fechas = todas_fechas.unique()
    if len(todas_fechas) > 1:
        rango_completo = pd.date_range(start=todas_fechas.min(), end=todas_fechas.max(), freq='D')
        dias_faltantes = rango_completo.difference(todas_fechas)
        if not dias_faltantes.empty:
            cortes_eje_x.append(dict(values=dias_faltantes.strftime('%Y-%m-%d').tolist()))
# ==========================================
# BLOQUE 9: RESUMEN PATRIMONIO EN PESOS (CLP)
# ==========================================
total_invertido_clp = sum(mis_posiciones.get(t, {}).get('costo_total_clp', 0.0) for t in activos_activos)
total_actual_usd = sum(mis_posiciones.get(t, {}).get('cuotas', 0) * datos_portafolio[t]["vista"]['Close'].iloc[-1] for t in activos_activos if t in datos_portafolio)
total_actual_clp = total_actual_usd * dolar_hoy 
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
# BLOQUE 10: GRÁFICO GLOBAL MIS INVERSIONES
# ==========================================
if activos_activos and any(t in datos_portafolio for t in activos_activos):
    st.subheader("🌐 Rendimiento de Mis Acciones Compradas (%)")
    fig_global_activos = go.Figure()
    global_y_min, global_y_max = float('inf'), float('-inf')
    
    for ticker in activos_activos:
        if ticker in datos_portafolio:
            hist_full = datos_portafolio[ticker]["full"]
            hist_vista = datos_portafolio[ticker]["vista"]
            precio_base = hist_vista['Close'].iloc[0]
            rendimiento_pct = ((hist_full['Close'] - precio_base) / precio_base) * 100
            rendimiento_vista = ((hist_vista['Close'] - precio_base) / precio_base) * 100
            
            global_y_min = min(global_y_min, rendimiento_vista.min())
            global_y_max = max(global_y_max, rendimiento_vista.max())
            
            fig_global_activos.add_trace(go.Scatter(x=hist_full.index, y=rendimiento_pct, mode='lines', name=ticker, line=dict(width=2)))
            
    if global_y_min == float('inf'):
        global_y_min, global_y_max = -10, 10
    elif global_y_min == global_y_max:
        global_y_min, global_y_max = global_y_min - 1, global_y_max + 1

    primer_t = activos_activos[0] if activos_activos[0] in datos_portafolio else list(datos_portafolio.keys())[0]
    rango_inicio, rango_fin = datos_portafolio[primer_t]["inicio"], datos_portafolio[primer_t]["fin"]
    
    fig_global_activos.add_hline(y=0, line_dash="dash", line_color="rgba(255,255,255,0.5)")
    fig_global_activos.update_layout(template="plotly_dark", height=350, margin=dict(l=0,r=0,t=10,b=0), hovermode="x unified", dragmode="pan", xaxis=dict(range=[rango_inicio, rango_fin], rangebreaks=cortes_eje_x, showgrid=False), yaxis=dict(range=[global_y_min, global_y_max], title="Rendimiento %", side="right", ticksuffix="%"))
    st.plotly_chart(fig_global_activos, use_container_width=True)
    st.divider()
# ==========================================
# BLOQUE 11: DETALLE INDIVIDUAL DE PORTAFOLIO
# ==========================================
if activos_activos:
    st.subheader("📈 Detalle de mi Portafolio")
    columnas_grid = st.columns(3)
    for i, ticker in enumerate(activos_activos):
        if ticker not in datos_portafolio: continue
        col_actual = columnas_grid[i % 3]
        nombre_empresa = st.session_state.nombres_tickers.get(ticker, ticker)
        datos_pos = mis_posiciones[ticker]
        hist_vista = datos_portafolio[ticker]["vista"]
        precio_actual_usd = hist_vista['Close'].iloc[-1]
        with col_actual:
            with st.container(border=True):
                col_t, col_del = st.columns([5, 1])
                col_t.markdown(f"**{nombre_empresa} ({ticker})**")
                if col_del.button("❌", key=f"del_{ticker}"):
                    eliminar_watchlist(ticker)
                    st.session_state.mis_tickers.remove(ticker)
                    st.rerun()
                rsi_actual = hist_vista['RSI'].iloc[-1]
                if rsi_actual > 70: msj_tec = f"🔴 **Sobrecomprada** (RSI: {rsi_actual:.0f})"
                elif rsi_actual < 30: msj_tec = f"🟢 **Sobrevendida** (RSI: {rsi_actual:.0f})"
                else: msj_tec = f"🟡 **Normal** (RSI: {rsi_actual:.0f})"
                st.caption(f"{msj_tec} | {obtener_fundamentales(ticker)}")
                inversion_inicial_clp = datos_pos['costo_total_clp']
                valor_hoy_clp = (datos_pos['cuotas'] * precio_actual_usd) * dolar_hoy
                ganancia_clp = valor_hoy_clp - inversion_inicial_clp
                ganancia_pct_clp = (ganancia_clp / inversion_inicial_clp) * 100 if inversion_inicial_clp > 0 else 0
                st.metric(f"Posición ({datos_pos['cuotas']:.2f}c) a ${precio_actual_usd:.2f} USD", f"${valor_hoy_clp:,.0f} CLP", f"{ganancia_clp:,.0f} CLP ({ganancia_pct_clp:.1f}%)")
                if st.button("💰 Vender Todo AHORA", key=f"sell_{ticker}", use_container_width=True):
                    registrar_transaccion(ticker, "VENTA", datos_pos['cuotas'], precio_actual_usd, dolar_hoy)
                    st.success("¡Vendido!")
                    time.sleep(1)
                    st.rerun()
                fig = go.Figure(go.Scatter(x=hist_vista.index, y=hist_vista['Close'], line=dict(color='#34c759' if ganancia_clp >= 0 else '#ff3b30')))
                fig.add_hline(y=datos_pos['precio_medio_usd'], line_dash="dash", line_color="#ffd60a", annotation_text="Compra (USD)")
                fig.update_layout(template="plotly_dark", height=150, margin=dict(l=0,r=0,t=0,b=0), dragmode="pan", xaxis=dict(visible=False, rangebreaks=cortes_eje_x), yaxis=dict(visible=False))
                st.plotly_chart(fig, use_container_width=True)

st.divider()

# ==========================================
# BLOQUE 12: RADAR DE OPORTUNIDADES
# ==========================================
if activos_radar:
    st.subheader("🎯 Radar de Seguimiento y Oportunidades")
    col_tabla, col_grafico = st.columns([2, 3])
    datos_tabla = []
    fig_radar = go.Figure()
    
    primer_t_radar = activos_radar[0] if activos_radar[0] in datos_portafolio else list(datos_portafolio.keys())[0]
    rango_ini_radar, rango_fin_radar = datos_portafolio[primer_t_radar]["inicio"], datos_portafolio[primer_t_radar]["fin"]
    radar_y_min, radar_y_max = float('inf'), float('-inf')
    
    for ticker in activos_radar:
        if ticker not in datos_portafolio: continue
        ultimo_precio = mis_posiciones.get(ticker, {}).get('ultimo_precio_venta', 0.0)
        hist_full = datos_portafolio[ticker]["full"]
        hist_vista = datos_portafolio[ticker]["vista"]
        precio_actual = hist_vista['Close'].iloc[-1]
        rsi_actual = hist_vista['RSI'].iloc[-1]
        if ultimo_precio > 0:
            dif_pct = ((precio_actual - ultimo_precio) / ultimo_precio) * 100
            if dif_pct < 0 and rsi_actual > 40: est, pri = "🔥 REMONTANDO", 1
            elif dif_pct < 0 and rsi_actual <= 40: est, pri = "📉 Cayendo", 3
            else: est, pri = "📈 Cara", 2
            precio_base = ultimo_precio
        else:
            precio_base = hist_vista['Close'].iloc[0]
            dif_pct = ((precio_actual - precio_base) / precio_base) * 100
            est, pri = "⚪ Seguimiento", 2 if rsi_actual > 40 else 3
        datos_tabla.append({"Ticker": ticker, "Venta USD": f"${ultimo_precio:.2f}" if ultimo_precio > 0 else "N/A", "Hoy USD": f"${precio_actual:.2f}", "Estado": est, "_p": pri})
        
        rendimiento_radar_full = ((hist_full['Close'] - precio_base) / precio_base) * 100
        rendimiento_radar_vista = ((hist_vista['Close'] - precio_base) / precio_base) * 100
        
        radar_y_min = min(radar_y_min, rendimiento_radar_vista.min())
        radar_y_max = max(radar_y_max, rendimiento_radar_vista.max())
        
        fig_radar.add_trace(go.Scatter(x=hist_full.index, y=rendimiento_radar_full, mode='lines', name=ticker))
        
    if radar_y_min == float('inf'):
        radar_y_min, radar_y_max = -10, 10
    elif radar_y_min == radar_y_max:
        radar_y_min, radar_y_max = radar_y_min - 1, radar_y_max + 1

    if datos_tabla:
        df_radar = pd.DataFrame(datos_tabla).sort_values(by="_p").drop(columns=["_p"])
        with col_tabla: st.dataframe(df_radar, hide_index=True, use_container_width=True)
    with col_grafico:
        fig_radar.add_hline(y=0, line_dash="dash", line_color="#ffffff", annotation_text="Punto Referencia")
        fig_radar.update_layout(template="plotly_dark", height=300, margin=dict(l=0,r=0,t=10,b=0), dragmode="pan", yaxis=dict(range=[radar_y_min, radar_y_max], side="right", ticksuffix="%"), xaxis=dict(range=[rango_ini_radar, rango_fin_radar], rangebreaks=cortes_eje_x), hovermode="x unified")
        st.plotly_chart(fig_radar, use_container_width=True)

