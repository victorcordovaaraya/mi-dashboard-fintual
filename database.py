import streamlit as st
from supabase import create_client, Client

@st.cache_resource
def init_connection():
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

supabase = init_connection()

def obtener_transacciones():
    try: return supabase.table("transacciones").select("*").execute().data
    except: return []

def registrar_transaccion(ticker, tipo, cantidad, precio, fx_dolar):
    supabase.table("transacciones").insert({"ticker": ticker, "tipo": tipo, "cantidad": cantidad, "precio_usd": precio, "precio_dolar_clp": fx_dolar}).execute()
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
