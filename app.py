import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd 
import time  
import requests 
from supabase import create_client, Client

# 1. MODO PANTALLA COMPLETA
st.set_page_config(page_title="Mi Portafolio", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# CONEXIÓN A BASE DE DATOS SUPABASE 🗄️
# ==========================================
@st.cache_resource
def init_connection():
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

def obtener_transacciones():
    try:
        respuesta = supabase.table("transacciones").select("*").execute()
        return respuesta.data
    except:
        return []

def registrar_transaccion(ticker, tipo, cantidad, precio):
    supabase.table("transacciones").insert({
        "ticker": ticker,
        "tipo": tipo,
        "cantidad": cantidad,
        "precio_usd": precio
    }).execute()

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

def accion_agregar(ticker_real, nombre_real):
    if ticker_real not in st.session_state.mis_tickers:
        st.session_state.mis_tickers.append(ticker_real)
        st.session_state.nombres_tickers[ticker_real] = nombre_real
        sincronizar_url() 
    st.session_state.buscador = ""

def accion_limpiar():
    st.session_state.buscador = ""

# ==========================================
# 🧠 CÁLCULO DE LIBRO MAYOR (LEDGER)
# ==========================================
tx_data = obtener_transacciones()
df_tx = pd.DataFrame(tx_data)
mis_posiciones = {}
ganancia_realizada_total = 0.0

if not df_tx.empty:
    for ticker in df_tx['ticker'].unique():
        df_t = df_tx[df_tx['ticker'] == ticker].copy()
        df_t = df_t.sort_values('fecha') 
        
        cuotas = 0.0
        costo_total = 0.0
        ganancia_cobrada = 0.0
        
        for _, row in df_t.iterrows():
            cant = float(row['cantidad'])
            precio = float(row['precio_usd'])
            
            if row['tipo'] == 'COMPRA':
                cuotas += cant
                costo_total += cant * precio
            elif row['tipo'] == 'VENTA':
                precio_promedio_actual = costo_total / cuotas if cuotas > 0 else 0
                cuotas -= cant
                # Evitar cuotas negativas por errores de tipeo
                if cuotas < 0: cuotas = 0 
                costo_total -= cant * precio_promedio_actual
                ganancia_cobrada += (precio - precio_promedio_actual) * cant
                
        precio_medio_final = costo_total / cuotas if cuotas > 0 else 0.0
        
        mis_posiciones[ticker] = {
            'cuotas': cuotas,
            'precio_medio': precio_medio_final,
            'ganancia_realizada': ganancia_cobrada
        }
        ganancia_realizada_total += ganancia_cobrada

# ==========================================
# MENÚ LATERAL: TERMINAL DE OPERACIONES 💼
# ==========================================
with st.sidebar:
    st.title("💼 Terminal de Operaciones")
    st.markdown("Registra tus compras y ventas. La base de datos calculará tu precio promedio y ganancias al instante.")
    
    with st.form("form_transaccion"):
        st.subheader("Nueva Transacción")
        t_ticker = st.selectbox("Acción / ETF:", st.session_state.mis_tickers)
        t_tipo = st.radio("Tipo de Movimiento:", ["COMPRA", "VENTA"], horizontal=True)
        t_cant = st.number_input("Cantidad de cuotas:", min_value=0.001, step=0.1, format="%.3f")
        t_precio = st.number_input("Precio por cuota ($ USD):", min_value=0.01, step=1.0)
        
        submit_btn = st.form_submit_button("💾 Guardar en Base de Datos")
        
        if submit_btn:
            registrar_transaccion(t_ticker, t_tipo, t_cant, t_precio)
            st.success(f"✅ {t_tipo} registrada con éxito.")
            time.sleep(1.5)
            st.rerun()

# ==========================================
# 🧠 FASE 2: EL ANALISTA FUNDAMENTAL 
# ==========================================
@st.cache_data(ttl=3600) 
def obtener_fundamentales(ticker):
    try:
        info = yf.Ticker(ticker).info
        pe = info.get('trailingPE', info.get('forwardPE', None))
        margen = info.get('profitMargins', None)
        deuda_equity = info.get('debtToEquity', None)
        
        if margen is None:
            return "⚪ **Fundamental:** Es un ETF/Fondo (No aplica)."
        
        margen_pct = margen * 100
        
        if margen_pct < 0:
            return f"🔴 **RIESGO (Fundamental):** Empresa perdiendo plata (Margen: {margen_pct:.1f}%)."
        elif pe is not None and pe > 40:
            return f"🟡 **REGULAR (Fundamental):** Gana plata pero la acción está cara (P/E: {pe:.1f})."
        elif deuda_equity is not None and deuda_equity > 150:
            return f"🟡 **REGULAR (Fundamental):** Alta deuda (D/E: {deuda_equity:.0f}), aunque genere ganancias."
        else:
            texto_pe = f"P/E: {pe:.1f}" if pe else "P/E: N/A"
            return f"🟢 **SÓLIDA (Fundamental):** Negocio sano ({texto_pe}, Margen: {margen_pct:.1f}%)."
    except:
        return "⚪ **Fundamental:** Datos no disponibles en la bolsa."

# ==========================================
# INTERFAZ PRINCIPAL
# ==========================================
st.title("Finanzas 📈")

col_busqueda, col_tiempo = st.columns([2, 1])

with col_busqueda:
    texto_busqueda = st.text_input("🔍 Escribe qué buscas (Ej: Apple, oro, SQM) y presiona Enter:", key="buscador")
    if texto_busqueda:
        resultados = buscar_multiples_tickers(texto_busqueda)
        if resultados:
            mapa_opciones = {r["label"]: r for r in resultados}
            opcion_elegida = st.selectbox("👇 Se encontraron estas opciones. Selecciona la correcta:", list(mapa_opciones.keys()))
            datos_seleccionados = mapa_opciones[opcion_elegida]
            st.button("➕ Añadir al Dashboard", on_click=accion_agregar, args=(datos_seleccionados["symbol"], datos_seleccionados["name"]))
        else:
            st.warning("No encontramos nada con ese nombre. Intenta con otra palabra.")
            st.button("Limpiar búsqueda", on_click=accion_limpiar)

with col_tiempo:
    opciones_tiempo = {
        "1 Mes": {"fetch": "2y", "interval": "1d", "dias_vista": 30},
        "3 Meses": {"fetch": "2y", "interval": "1d", "dias_vista": 90},
        "6 Meses": {"fetch": "2y", "interval": "1d", "dias_vista": 180},
        "YTD (Desde enero)": {"fetch": "2y", "interval": "1d", "dias_vista": "YTD"},
        "1 Año": {"fetch": "5y", "interval": "1d", "dias_vista": 365},
        "1 Semana": {"fetch": "60d", "interval": "15m", "dias_vista": 7},
        "1 Día": {"fetch": "60d", "interval": "5m", "dias_vista": 1}
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
# MOTOR CENTRAL DE DESCARGA Y CÁLCULO
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
if config["interval"] in ["5m", "15m"]:
    cortes_eje_x.append(dict(bounds=[16, 9.5], pattern="hour"))

for ticker in st.session_state.mis_tickers:
    activo = yf.Ticker(ticker)
    hist_full = activo.history(period=config["fetch"], interval=config["interval"])

    if not hist_full.empty:
        hist_full = calcular_indicadores(hist_full)
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

        datos_portafolio[ticker] = {
            "full": hist_full,
            "vista": hist_vista,
            "inicio": fecha_inicio,
            "fin": fecha_fin
        }

# ==========================================
# RESUMEN DE PATRIMONIO HISTÓRICO TOTAL 🏦
# ==========================================
total_invertido = 0.0
total_actual = 0.0

for ticker in st.session_state.mis_tickers:
    datos_posicion = mis_posiciones.get(ticker, {'cuotas': 0.0, 'precio_medio': 0.0})
    cuotas = datos_posicion['cuotas']
    precio_medio = datos_posicion['precio_medio']
    
    if cuotas > 0 and precio_medio > 0 and ticker in datos_portafolio:
        precio_hoy = datos_portafolio[ticker]["vista"]['Close'].iloc[-1]
        total_invertido += (cuotas * precio_medio)
        total_actual += (cuotas * precio_hoy)

ganancia_flotante_usd = total_actual - total_invertido
desempeño_historico_total = ganancia_flotante_usd + ganancia_realizada_total

if total_invertido > 0 or ganancia_realizada_total != 0:
    st.subheader("🏦 Mi Patrimonio Histórico (USD)")
    col1, col2, col3, col4 = st.columns(4)
    
    col1.metric("💰 Inversión Activa", f"${total_invertido:,.2f}")
    col2.metric("💵 Valor Actual", f"${total_actual:,.2f}", f"{ganancia_flotante_usd:,.2f} Flotante")
    
    if ganancia_realizada_total >= 0:
        col3.metric("💼 Ganancia Ya Cobrada", f"+${ganancia_realizada_total:,.2f}", "Caja")
    else:
        col3.metric("💼 Pérdida Ya Cobrada", f"${ganancia_realizada_total:,.2f}", "Caja")
        
    if desempeño_historico_total >= 0:
        col4.metric("🏆 Desempeño Histórico Total", f"+${desempeño_historico_total:,.2f}")
    else:
        col4.metric("📉 Desempeño Histórico Total", f"${desempeño_historico_total:,.2f}")
        
    st.divider()

# ==========================================
# SECCIÓN 2: EL GRÁFICO GLOBAL COMBINADO
# ==========================================
st.subheader("🌐 Rendimiento Global Comparativo (%)")

if datos_portafolio:
    fig_global = go.Figure()
    
    primer_ticker = list(datos_portafolio.keys())[0]
    rango_inicio = datos_portafolio[primer_ticker]["inicio"]
    rango_fin = datos_portafolio[primer_ticker]["fin"]

    global_y_min = float('inf')
    global_y_max = float('-inf')

    for ticker, datos in datos_portafolio.items():
        nombre_empresa = st.session_state.nombres_tickers.get(ticker, ticker)
        hist_full = datos["full"]
        hist_vista = datos["vista"]
        
        precio_base = hist_vista['Close'].iloc[0]
        rendimiento_pct = ((hist_full['Close'] - precio_base) / precio_base) * 100
        
        rendimiento_vista_pct = ((hist_vista['Close'] - precio_base) / precio_base) * 100
        global_y_min = min(global_y_min, rendimiento_vista_pct.min())
        global_y_max = max(global_y_max, rendimiento_vista_pct.max())
        
        fig_global.add_trace(go.Scatter(
            x=hist_full.index, 
            y=rendimiento_pct, 
            mode='lines+markers', 
            name=f"{nombre_empresa} ({ticker})",
            line=dict(width=2.5), 
            marker=dict(size=4)   
        ))

    global_y_min = min(global_y_min, 0)
    global_y_max = max(global_y_max, 0)
    margen_global = (global_y_max - global_y_min) * 0.1
    if margen_global == 0: margen_global = 1
    
    limite_inferior_global = global_y_min - margen_global
    limite_superior_global = global_y_max + margen_global

    fig_global.add_hline(y=0, line_dash="dash", line_color="rgba(255, 255, 255, 0.5)", line_width=1.5)

    fig_global.update_layout(
        template="plotly_dark", 
        xaxis=dict(range=[rango_inicio, rango_fin], showgrid=False, rangebreaks=cortes_eje_x), 
        yaxis=dict(
            range=[limite_inferior_global, limite_superior_global], 
            side="right", 
            gridcolor="rgba(255,255,255,0.1)", 
            title="Rendimiento %", 
            ticksuffix="%"
        ), 
        dragmode="pan", 
        margin=dict(l=0, r=0, t=10, b=0), 
        height=450, 
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5) 
    )
    
    st.plotly_chart(fig_global, use_container_width=True)

st.divider()

# ==========================================
# SECCIÓN 3: LOS GRÁFICOS INDIVIDUALES 
# ==========================================
st.subheader("📊 Análisis Individual y Mis Ganancias")
columnas_grid = st.columns(3)

for i, ticker in enumerate(st.session_state.mis_tickers):
    
    col_actual = columnas_grid[i % 3]
    nombre_empresa = st.session_state.nombres_tickers.get(ticker, ticker)
    
    datos_posicion = mis_posiciones.get(ticker, {'cuotas': 0.0, 'precio_medio': 0.0, 'ganancia_realizada': 0.0})
    mis_cuotas = datos_posicion['cuotas']
    mi_precio = datos_posicion['precio_medio']
    mi_ganancia_cobrada = datos_posicion['ganancia_realizada']
    
    with col_actual:
        col_tit, col_izq, col_der, col_del = st.columns([5, 1, 1, 1])
        with col_tit:
            st.markdown(f"**{nombre_empresa} ({ticker})**")
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
        
        if ticker in datos_portafolio:
            datos = datos_portafolio[ticker]
            hist_full = datos["full"]
            hist_vista = datos["vista"]
            fecha_inicio = datos["inicio"]
            fecha_fin = datos["fin"]

            precio_actual = hist_vista['Close'].iloc[-1]
            precio_inicial_grafico = hist_vista['Close'].iloc[0] 
            
            # --- FASE 1: INDICADORES TÉCNICOS ---
            rsi_actual = hist_vista['RSI'].iloc[-1]
            caida_desde_max = hist_vista['Caida_Desde_Max'].iloc[-1]
            
            if pd.isna(rsi_actual):
                mensaje_tecnico = "⚪ Técnico: Esperando datos..."
            elif rsi_actual > 70:
                mensaje_tecnico = f"🔴 **Técnico (VENDER/ESPERAR):** Sobrecomprada (RSI: {rsi_actual:.0f})."
            elif rsi_actual < 30:
                mensaje_tecnico = f"🟢 **Técnico (COMPRAR):** Sobrevendida (RSI: {rsi_actual:.0f})."
            elif caida_desde_max < -10:
                mensaje_tecnico = f"🚨 **Técnico (ALERTA):** Cayó {caida_desde_max:.1f}% desde su techo."
            else:
                mensaje_tecnico = f"🟡 **Técnico (MANTENER):** Tendencia normal (RSI: {rsi_actual:.0f})."

            # --- FASE 2: INDICADORES FUNDAMENTALES ---
            mensaje_fundamental = obtener_fundamentales(ticker)

            st.caption(f"{mensaje_tecnico}")
            st.caption(f"{mensaje_fundamental}")

            # --- LÓGICA DE GANANCIA REAL ---
            if mis_cuotas > 0 and mi_precio > 0:
                mi_plata_invertida = mis_cuotas * mi_precio
                mi_plata_actual = mis_cuotas * precio_actual
                ganancia_flotante_usd = mi_plata_actual - mi_plata_invertida
                ganancia_flotante_pct = (ganancia_flotante_usd / mi_plata_invertida) * 100
                
                total_ganancia_este_ticker = ganancia_flotante_usd + mi_ganancia_cobrada
                
                if mi_ganancia_cobrada != 0:
                    st.metric(
                        label=f"Posición ({mis_cuotas:.2f}c) + Ya Cobrado", 
                        value=f"${mi_plata_actual:,.2f}",
                        delta=f"{total_ganancia_este_ticker:,.2f} USD (Total Histórico)" 
                    )
                else:
                    st.metric(
                        label=f"Mi Posición ({mis_cuotas:.2f} cuotas)", 
                        value=f"${mi_plata_actual:,.2f}",
                        delta=f"{ganancia_flotante_usd:,.2f} USD ({ganancia_flotante_pct:.2f}%)" 
                    )
                
                if ganancia_flotante_usd >= 0:
                    color_linea = '#34c759'
                    color_relleno = 'rgba(52, 199, 89, 0.1)'
                else:
                    color_linea = '#ff3b30'
                    color_relleno = 'rgba(255, 59, 48, 0.1)'
            else:
                variacion_usd = precio_actual - precio_inicial_grafico
                variacion_pct = (variacion_usd / precio_inicial_grafico) * 100
                
                if mi_ganancia_cobrada != 0:
                    st.metric(
                        label="Posición Cerrada. Ganancia ya cobrada:", 
                        value=f"${mi_ganancia_cobrada:,.2f}",
                        delta="En Caja" 
                    )
                else:
                    st.metric(
                        label="Precio de la Acción (Modo Sapeo)", 
                        value=f"${precio_actual:.2f}",
                        delta=f"{variacion_usd:.2f} ({variacion_pct:.2f}%)" 
                    )
                    
                if variacion_usd >= 0:
                    color_linea = '#34c759'
                    color_relleno = 'rgba(52, 199, 89, 0.1)'
                else:
                    color_linea = '#ff3b30'
                    color_relleno = 'rgba(255, 59, 48, 0.1)'

            # --- DIBUJAR GRÁFICO ---
            fig = go.Figure()
            
            fig.add_trace(go.Scatter(
                x=hist_full.index, 
                y=hist_full['Close'], 
                mode='lines+markers', 
                name='Precio',
                line=dict(color=color_linea, width=2.5), 
                marker=dict(size=4), 
                fill='tozeroy', 
                fillcolor=color_relleno 
            ))

            fig.add_hline(
                y=precio_inicial_grafico, 
                line_dash="dot", 
                line_color="rgba(255, 255, 255, 0.4)", 
                line_width=1.5,
            )

            if mi_precio > 0 and mis_cuotas > 0:
                fig.add_hline(
                    y=mi_precio, 
                    line_dash="dash", 
                    line_color="#ffd60a", 
                    line_width=2,
                    annotation_text="Mi Compra",
                    annotation_position="bottom right",
                    annotation_font_color="#ffd60a"
                )

            y_min = hist_vista['Close'].min()
            y_max = hist_vista['Close'].max()
            
            if mi_precio > 0 and mis_cuotas > 0:
                y_min = min(y_min, mi_precio)
                y_max = max(y_max, mi_precio)

            margen = (y_max - y_min) * 0.1 
            if margen == 0: margen = 1 
            
            limite_inferior = min(y_min, precio_inicial_grafico) - margen
            limite_superior = max(y_max, precio_inicial_grafico) + margen

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
                height=250, 
                hovermode="x unified",
                showlegend=False
            )

            st.plotly_chart(fig, use_container_width=True)
        else:
            st.error(f"⚠️ Hubo un error procesando {ticker}.")

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
