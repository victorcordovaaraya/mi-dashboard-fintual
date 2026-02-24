# Contexto de Mi Dashboard Fintual / Portafolio

**Stack Tecnológico:** Streamlit (Python), YFinance, Plotly, Supabase (PostgreSQL).

**Funcionalidades actuales:**
1. **Bimonetario:** Calcula el patrimonio en USD y CLP. Descarga el dólar en tiempo real de Yahoo Finance (`CLP=X`).
2. **Base de Datos:** Usa Supabase para guardar `transacciones`, `watchlist` y `configuracion` (tramo SII).
3. **Libro Mayor (FIFO):** Calcula ganancias reales cruzando el precio de compra, el dólar de compra, el precio de venta y el dólar de venta.
4. **Impuestos (SII):** Calcula la provisión de impuestos según el sueldo del usuario.
5. **Radar de Oportunidades:** Compara el último precio de venta con el precio actual para buscar rebajas (Value/Momentum) usando el indicador RSI.

**Regla de trabajo con la IA:** Al modificar código, NO generar el archivo completo. Entregar solo "Snippets" (parches) indicando exactamente en qué archivo y bajo qué línea se deben insertar para no romper el código existente ni superar los límites de caracteres.
