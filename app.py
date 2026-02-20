import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
import pandas as pd 
import time  # <--- AQUÍ VA, JUNTO A LAS OTRAS HERRAMIENTAS

# Título de la app
st.title("Mi Dashboard Financiero 📈")
st.write("Seguimiento interactivo del ETF: Vanguard Materials (VAW)")

vaw = yf.Ticker("VAW")

# 1. Lógica de tiempo
opciones_tiempo = {
    "1 Día": {"fetch": "60d", "interval": "5m", "dias_vista": 1},
    "1 Semana": {"fetch": "60d", "interval": "15m", "dias_vista": 7},
    "1 Mes": {"fetch": "2y", "interval": "1d", "dias_vista": 30},
    "3 Meses": {"fetch": "2y", "interval": "1d", "dias_vista": 90},
    "6 Meses": {"fetch": "2y", "interval": "1d", "dias_vista": 180},
    "YTD (Desde enero)": {"fetch": "2y", "interval": "1d", "dias_vista": "YTD"},
    "1 Año": {"fetch": "5y", "interval": "1d", "dias_vista": 365}
}

seleccion = st.selectbox("⏳ Selecciona el período a visualizar:", list(opciones_tiempo.keys()))
config = opciones_tiempo[seleccion]

# Descargamos la historia
hist_full = vaw.history(period=config["fetch"], interval=config["interval"])

if not hist_full.empty:
    fecha_fin = hist_full.index[-1]
    
    # Calcular ventana inicial
    if config["dias_vista"] == "YTD":
        fecha_inicio = hist_full[hist_full.index.year == fecha_fin.year].index[0]
    else:
        fecha_inicio = fecha_fin - pd.Timedelta(days=config["dias_vista"])

    hist_vista = hist_full[hist_full.index >= fecha_inicio]
    if hist_vista.empty: 
        hist_vista = hist_full 

    precio_actual = hist_vista['Close'].iloc[-1]
    precio_inicial = hist_vista['Close'].iloc[0] 
    
    variacion_usd = precio_actual - precio_inicial
    variacion_pct = (variacion_usd / precio_inicial) * 100

    # LÓGICA ESTILO APPLE/YAHOO
    if variacion_usd >= 0:
        color_linea = '#34c759'
        color_relleno = 'rgba(52, 199, 89, 0.1)'
    else:
        color_linea = '#ff3b30'
        color_relleno = 'rgba(255, 59, 48, 0.1)'

    # Métricas
    st.metric(
        label=f"Precio Actual de VAW", 
        value=f"${precio_actual:.2f}",
        delta=f"{variacion_usd:.2f} USD ({variacion_pct:.2f}%) en {seleccion}" 
    )

    # GRÁFICO CON SCROLL INFINITO
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
        height=450,
        hovermode="x unified",
        showlegend=False
    )

    st.plotly_chart(fig, use_container_width=True)

else:
    st.warning("Yahoo Finance no devolvió datos para este periodo en este momento.")

# ==========================================
# SWITCH DE AUTO-ACTUALIZACIÓN
# ==========================================
st.divider() 

col1, col2 = st.columns([1, 3])
with col1:
    auto_refresh = st.toggle("🔄 Auto-Actualizar")
with col2:
    if auto_refresh:
        st.caption("Actualizando automáticamente cada 1 minuto...")
        time.sleep(60) 
        st.rerun()