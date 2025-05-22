import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from datetime import datetime, timedelta, date
import unicodedata
from difflib import get_close_matches
import re


# --------------------------------------------------------------------
#                      CONFIGURACIÓN BÁSICA
# --------------------------------------------------------------------
st.set_page_config(
    page_title="Dashboard de Promotores",
    page_icon="✅",
    layout="wide"
)

# --------------------------------------------------------------------
#                  FUNCIONES AUXILIARES Y DE FORMATO
# --------------------------------------------------------------------
def format_money(x):
    """Convierte un número a formato monetario con dos decimales."""
    try:
        return f"${x:,.2f}"
    except Exception:
        return x

def convert_number(x):
    """
    Convierte cadenas con comas o puntos mezclados a float estándar.
    Ej: '1,234.56' -> 1234.56
        '1.234,56' -> 1234.56
    """
    s = str(x).strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except:
        return np.nan

def check_required_columns(df, required_cols, df_name="DataFrame"):
    """
    Verifica que el DataFrame contenga todas las columnas requeridas.
    Lanza una excepción si faltan columnas.
    """
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        raise ValueError(
            f"El {df_name} no contiene las columnas requeridas: {missing}"
        )

def style_cumplimiento(val):
    """Colorea la celda según el %."""
    try:
        if val >= 97: color = "green"
        elif val >= 85: color = "orange"
        else: color = "red"
        return f"color: {color}; font-weight: bold;"
    except: return ""

def style_difference(val):
    """Colorea la celda según la diferencia."""
    if pd.isna(val): return ""
    if val >= 1.1: return "background-color: red; color: white;"
    elif val >= 0.65: return "background-color: yellow; color: black;"
    return ""

def normalize_name(s):
    """Quita tildes, pasa a mayúsculas y colapsa espacios."""
    s = str(s).strip().upper()
    s = "".join(c for c in unicodedata.normalize("NFKD", s) 
                if unicodedata.category(c) != "Mn")
    return " ".join(s.split())

def fuzzy_map(name, choices, cutoff=0.8):
    """Devuelve la coincidencia más cercana."""
    matches = get_close_matches(name, choices, n=1, cutoff=cutoff)
    return matches[0] if matches else None

# --------------------------------------------------------------------
#                       CARGA DE DATOS (CACHED)
# --------------------------------------------------------------------
@st.cache_data
def load_data_control(vas_file):
    """Carga y procesa el archivo de control y metas (VasTu.xlsx)."""
    df_control = pd.read_excel(vas_file, sheet_name="Control")
    required_cols_control = ["N", "Nombre", "Antigüedad (meses)"]
    check_required_columns(df_control, required_cols_control, "df_control (hoja 'Control' de VasTu.xlsx)")

    df_control["N"] = df_control["N"].astype(str).str.strip().str.upper()
    df_control["Nombre"] = df_control["Nombre"].str.strip()
    df_control["Antigüedad (meses)"] = df_control["Antigüedad (meses)"].apply(lambda x: round(x, 2) if pd.notna(x) else x)
    df_control["Nombre_upper"] = df_control["Nombre"].str.strip().str.upper()

    xls = pd.ExcelFile(vas_file)
    lista_metas = []
    for sheet in xls.sheet_names:
        if sheet.lower() != "control":
            try:
                df_sheet = pd.read_excel(vas_file, sheet_name=sheet, header=1)
                if df_sheet.shape[1] < 3:
                    st.warning(f"La hoja '{sheet}' en VasTu.xlsx no tiene el formato esperado (mínimo 3 columnas de datos más allá de la cabecera). Se omitirá.")
                    continue
                data = df_sheet.iloc[:, [1, 2]].copy() 
                data.columns = ["Fecha", "Meta"]
                data["Promotor"] = sheet.strip().upper() 
                lista_metas.append(data)
            except Exception as e:
                st.warning(f"Error al leer la hoja de metas '{sheet}' en VasTu.xlsx: {e}. Se omitirá.")
    
    if not lista_metas:
        st.warning("No se encontraron hojas de metas válidas en VasTu.xlsx.")
        df_metas = pd.DataFrame(columns=["Fecha", "Meta", "Promotor"])
    else:
        df_metas = pd.concat(lista_metas, ignore_index=True)

    df_metas["Fecha"] = pd.to_datetime(df_metas["Fecha"], errors="coerce")
    df_metas.dropna(subset=["Fecha"], inplace=True)
    df_metas["Semana"] = df_metas["Fecha"].dt.to_period("W-FRI")
    df_metas_summary = df_metas.groupby(["Promotor", "Semana"])["Meta"].first().reset_index()
    return df_control, dict(zip(df_control["N"], df_control["Nombre"])), df_metas_summary

@st.cache_data
def load_data_cobranza(cob_file):
    """Carga y procesa el archivo de cobranza (Cobranza.xlsx)."""
    df_cobranza = pd.read_excel(cob_file, sheet_name="Recuperaciones", skiprows=4,
                                usecols=["Nombre Promotor", "Fecha transacción", "Depósito", "Estado", "Municipio", "Contrato"])
    required_cols_cob = ["Nombre Promotor", "Fecha transacción", "Depósito", "Estado", "Municipio", "Contrato"]
    check_required_columns(df_cobranza, required_cols_cob, "df_cobranza (hoja 'Recuperaciones' de Cobranza.xlsx)")

    df_cobranza["Fecha transacción"] = pd.to_datetime(df_cobranza["Fecha transacción"], errors="coerce")
    df_cobranza["Depósito"] = df_cobranza["Depósito"].apply(convert_number)
    df_cobranza.dropna(subset=["Nombre Promotor", "Fecha transacción", "Depósito"], inplace=True)
    df_cobranza.rename(columns={"Fecha transacción": "Fecha Transacción"}, inplace=True)
    df_cobranza["Semana"] = df_cobranza["Fecha Transacción"].dt.to_period("W-FRI")
    df_cobranza["Nombre Promotor"] = df_cobranza["Nombre Promotor"].astype(str).str.strip().str.upper()
    df_cobranza["Día_num"] = ((df_cobranza["Fecha Transacción"].dt.dayofweek - 5) % 7) + 1
    return df_cobranza

@st.cache_data
def load_data_colocaciones(col_file):
    """Carga y procesa el archivo de colocaciones (Colocaciones.xlsx)."""
    cols_to_read = ["Nombre promotor", "Fecha desembolso", "Monto desembolsado", "Nombre del cliente", "Contrato", "Cuota total", "Fecha primer pago"]
    empty_agg = pd.DataFrame(columns=["Nombre promotor", "Semana", "Creditos_Colocados", "Venta"])
    empty_detail = pd.DataFrame(columns=cols_to_read)

    if not col_file: return empty_agg, empty_detail

    try:
        df_col_raw = pd.read_excel(col_file, sheet_name="Colocación", skiprows=4, header=0)
    except Exception as e:
        st.error(f"Error CRÍTICO al leer Colocaciones.xlsx (hoja 'Colocación'): {e}")
        return empty_agg, empty_detail

    missing = [col for col in cols_to_read if col not in df_col_raw.columns]
    if missing:
        st.error(f"Faltan columnas en Colocaciones.xlsx: {', '.join(missing)}")
        st.warning(f"Columnas encontradas: {', '.join(df_col_raw.columns.tolist())}")
        return empty_agg, empty_detail

    df_detail = df_col_raw[cols_to_read].copy()
    df_detail["Nombre promotor"] = df_detail["Nombre promotor"].astype(str).str.strip().str.upper()
    df_detail["Fecha primer pago"] = pd.to_datetime(df_detail["Fecha primer pago"], errors='coerce')
    df_detail["Cuota total"] = df_detail["Cuota total"].apply(convert_number).fillna(0)
    df_detail["Fecha desembolso"] = pd.to_datetime(df_detail["Fecha desembolso"], errors='coerce')
    df_detail["Monto desembolsado"] = df_detail["Monto desembolsado"].apply(convert_number).fillna(0)
    df_detail.dropna(subset=["Nombre promotor", "Fecha desembolso", "Nombre del cliente"], inplace=True)

    required_agg = ["Nombre promotor", "Fecha desembolso", "Monto desembolsado"]
    df_agg_src = df_col_raw[required_agg].copy()
    df_agg_src["Fecha desembolso"] = pd.to_datetime(df_agg_src["Fecha desembolso"], errors='coerce')
    df_agg_src["Monto desembolsado"] = df_agg_src["Monto desembolsado"].apply(convert_number)
    df_agg_src.dropna(subset=required_agg, inplace=True)

    if not df_agg_src.empty:
        df_agg_src["Nombre promotor"] = df_agg_src["Nombre promotor"].astype(str).str.strip().str.upper()
        if pd.api.types.is_datetime64_any_dtype(df_agg_src["Fecha desembolso"]):
            df_agg_src["Semana"] = df_agg_src["Fecha desembolso"].dt.to_period("W-FRI")
            df_agg = df_agg_src.groupby(["Nombre promotor", "Semana"], as_index=False).agg(
                Creditos_Colocados=("Monto desembolsado", "count"), Venta=("Monto desembolsado", "sum"))
        else:
            st.warning("No se pudo generar 'Semana' para agregación de colocaciones (problemas con 'Fecha desembolso').")
            df_agg = empty_agg.copy()
    else:
        df_agg = empty_agg.copy()
    return df_agg, df_detail

@st.cache_data
def load_data_descuentos(por_capturar_file, df_control):
    """Carga y procesa el archivo de descuentos ('Por Capturar.xlsx')."""
    empty_df_desc = pd.DataFrame(columns=["N", "Semana", "Descuento_Renovacion"])
    if not por_capturar_file: return empty_df_desc

    try:
        df_desc = pd.read_excel(por_capturar_file, skiprows=3, usecols=["Promotor", "Fecha Ministración", "Descuento Renovación"])
    except Exception as e:
        st.error(f"Error al leer 'Por Capturar.xlsx': {e}")
        return empty_df_desc

    required_cols = ["Promotor", "Fecha Ministración", "Descuento Renovación"]
    missing = [col for col in required_cols if col not in df_desc.columns]
    if missing:
        st.error(f"Faltan columnas en 'Por Capturar.xlsx': {', '.join(missing)}. Encontradas: {df_desc.columns.tolist()}")
        return empty_df_desc

    df_desc["Promotor"] = df_desc["Promotor"].astype(str).str.strip().str.upper()
    df_desc["Descuento_Num_Temp"] = df_desc["Descuento Renovación"].apply(convert_number)
    df_desc["Fecha Ministración"] = pd.to_datetime(df_desc["Fecha Ministración"], errors='coerce')
    df_desc.dropna(subset=["Promotor", "Descuento_Num_Temp", "Fecha Ministración"], inplace=True)
    df_desc = df_desc[df_desc["Descuento_Num_Temp"] > 0].copy()

    if df_desc.empty: return empty_df_desc
    if df_control.empty or "N" not in df_control.columns or "Nombre_upper" not in df_control.columns :
        st.warning("No se pueden mapear promotores para descuentos: df_control (archivo VasTu) está vacío o faltan columnas 'N'/'Nombre_upper'.")
        return empty_df_desc

    name_to_code_upper = dict(zip(df_control["Nombre_upper"], df_control["N"]))
    df_desc["CodigoPromotor"] = df_desc["Promotor"].map(name_to_code_upper)
    
    unmapped = df_desc["CodigoPromotor"].isna()
    if unmapped.any() and "Nombre" in df_control.columns:
        norm_map = dict(zip(df_control["Nombre"].apply(normalize_name), df_control["N"]))
        choices = list(norm_map.keys())
        df_desc.loc[unmapped, "Promotor_Normalized"] = df_desc.loc[unmapped, "Promotor"].apply(normalize_name)
        df_desc.loc[unmapped, "CodigoPromotor"] = df_desc.loc[unmapped, "Promotor_Normalized"].map(norm_map)
        
        still_unmapped = df_desc["CodigoPromotor"].isna() & unmapped
        if still_unmapped.any():
            df_desc.loc[still_unmapped, "FuzzyMatch"] = df_desc.loc[still_unmapped, "Promotor_Normalized"].apply(lambda nm: fuzzy_map(nm, choices))
            df_desc.loc[still_unmapped, "CodigoPromotor"] = df_desc.loc[still_unmapped, "FuzzyMatch"].map(norm_map)
        df_desc.drop(columns=["Promotor_Normalized", "FuzzyMatch"], errors='ignore', inplace=True)
    
    df_final = df_desc.dropna(subset=["CodigoPromotor"]).copy()
    if df_final.empty: return empty_df_desc
    
    df_final["Semana"] = df_final["Fecha Ministración"].dt.to_period("W-FRI")
    return df_final.groupby(["CodigoPromotor", "Semana"], as_index=False)["Descuento_Num_Temp"].sum().rename(
        columns={"CodigoPromotor": "N", "Descuento_Num_Temp": "Descuento_Renovacion"})

@st.cache_data
def load_data_pagos(pagos_file):
    """Carga y procesa el archivo de pagos esperados ('Pagos Esperados.xlsx')."""
    empty_df_pagos = pd.DataFrame(columns=["PROMOTOR","SALDO", "PS", "SV", "VENCI", "N"])
    if not pagos_file: return empty_df_pagos

    try:
        df_pagos = pd.read_excel(pagos_file, skiprows=3, usecols=["PROMOTOR","SALDO","PS*","MULTAS","VENCI*"])
    except Exception as e:
        st.error(f"Error al leer 'Pagos Esperados.xlsx': {e}")
        return empty_df_pagos
        
    check_required_columns(df_pagos, ["PROMOTOR","SALDO"], "df_pagos (Pagos Esperados.xlsx)")

    df_pagos["PROMOTOR"] = df_pagos["PROMOTOR"].astype(str).str.strip().str.upper()
    df_pagos["SALDO"] = df_pagos["SALDO"].apply(convert_number)
    df_pagos.rename(columns={"PS*": "PS", "MULTAS": "SV", "VENCI*": "VENCI"}, inplace=True)
    
    for col, default_val, dtype in [("PS", 0, float), ("SV", 0, float), ("VENCI", pd.NaT, 'datetime64[ns]')]:
        if col not in df_pagos.columns: df_pagos[col] = default_val
        else:
            if dtype == float: df_pagos[col] = df_pagos[col].apply(convert_number if col == "SV" else pd.to_numeric, errors='coerce').fillna(default_val)
            else: df_pagos[col] = pd.to_datetime(df_pagos[col], errors='coerce')
            
    df_pagos.dropna(subset=["PROMOTOR","SALDO"], inplace=True)
    df_pagos["N"] = pd.NA 
    return df_pagos

@st.cache_data
def merge_colocaciones(df_col_agg, df_control):
    """Une datos agregados de colocaciones con datos de control."""
    if df_col_agg.empty or df_control.empty: return pd.DataFrame()
    if "Nombre_upper" not in df_control.columns or "N" not in df_control.columns:
        st.warning("Columnas 'Nombre_upper' o 'N' no encontradas en df_control al unir colocaciones.")
        return pd.DataFrame(columns=df_col_agg.columns.tolist() + ["N", "Nombre", "Antigüedad (meses)", "Nombre_upper"])
    return pd.merge(df_col_agg, df_control[["N", "Nombre", "Antigüedad (meses)", "Nombre_upper"]], 
                    left_on="Nombre promotor", right_on="Nombre_upper", how="left")

@st.cache_data
def build_promoters_summary(df_control, df_metas_summary, df_cobranza):
    """Construye el resumen de promotores."""
    cols = ["N", "Nombre", "Antigüedad (meses)", "Total Metas", "Total Cobranza", "Diferencia"]
    if df_control.empty or "N" not in df_control.columns or "Nombre" not in df_control.columns:
        return pd.DataFrame(columns=cols)
    
    summary_list = []
    for _, row in df_control.iterrows():
        code, name, antig = row["N"], row["Nombre"], row.get("Antigüedad (meses)", np.nan)
        meta = df_metas_summary[df_metas_summary["Promotor"] == code]["Meta"].sum() if not df_metas_summary.empty else 0
        cob = df_cobranza[df_cobranza["N"] == code]["Depósito"].sum() if not df_cobranza.empty and "N" in df_cobranza else 0
        if pd.isna(antig) and meta == 0 and cob == 0: continue
        summary_list.append({"N": code, "Nombre": name, "Antigüedad (meses)": antig, 
                             "Total Metas": meta, "Total Cobranza": cob, "Diferencia": cob - meta})
    
    if not summary_list: return pd.DataFrame(columns=cols)
    df_summary = pd.DataFrame(summary_list)
    return df_summary.sort_values(by="N", key=lambda x: x.astype(str).str.extract(r"(\d+)")[0].astype(int))


# --------------------------------------------------------------------
#  FUNCIONES PARA LÓGICA DE PESTAÑAS (Refactoring)
# --------------------------------------------------------------------

def _get_recent_weeks_compliance_for_risk(promotor_code, df_metas, df_cob, code_to_name_map, top_weeks=4):
    """Helper para calcular cumplimiento reciente para el score de riesgo."""
    if not code_to_name_map or promotor_code not in code_to_name_map: return 0.0
    name_upper = code_to_name_map[promotor_code].upper()
    
    df_meta_p = df_metas[df_metas["Promotor"] == promotor_code]
    # df_cobranza is mapped to 'N' in main, so use 'N' for filtering if available
    if "N" in df_cob.columns:
        df_cob_p = df_cob[df_cob["N"] == promotor_code]
    elif "Nombre Promotor" in df_cob.columns: # Fallback if 'N' not in this specific df_cob view
        df_cob_p = df_cob[df_cob["Nombre Promotor"] == name_upper]
    else: return 0.0


    metas_sem = df_meta_p.groupby("Semana")["Meta"].sum()
    cob_sem = df_cob_p.groupby("Semana")["Depósito"].sum()
    df_weeks = pd.DataFrame({"Meta": metas_sem, "Cobranza": cob_sem}).fillna(0).sort_index(ascending=False).head(top_weeks)
    if df_weeks.empty: return 0.0
    df_weeks["Cumplimiento"] = df_weeks.apply(lambda r: (r["Cobranza"]/r["Meta"]*100) if r["Meta"] > 0 else 0, axis=1)
    return round(df_weeks["Cumplimiento"].mean(), 2)

def calculate_payment_pattern_changes_tab(df_cobranza_tab, code_to_name_map):
    """Calcula la variación en el día promedio de pago."""
    changes = []
    if not code_to_name_map or df_cobranza_tab.empty or "N" not in df_cobranza_tab.columns: return pd.DataFrame(changes)
    for code, name in code_to_name_map.items():
        df_prom = df_cobranza_tab[df_cobranza_tab["N"] == code].copy()
        if df_prom.empty or "Día_num" not in df_prom.columns or "Depósito" not in df_prom.columns: continue
        df_prom["wp"] = df_prom["Día_num"] * df_prom["Depósito"]
        agg = df_prom.groupby("Semana").agg(swp=("wp", "sum"), sd=("Depósito", "sum")).reset_index()
        agg = agg[agg["sd"] > 0] # Avoid division by zero if total deposit for a week is 0
        agg["Weighted_Day"] = agg["swp"] / agg["sd"]
        weekly = agg[["Semana", "Weighted_Day"]].sort_values("Semana")
        n = len(weekly)
        if n < 2: continue
        first_avg, last_avg = (weekly.head(3 if n >= 6 else n//2)["Weighted_Day"].mean(), 
                               weekly.tail(3 if n >= 6 else n - n//2)["Weighted_Day"].mean())
        diff = (last_avg - first_avg) if pd.notna(first_avg) and pd.notna(last_avg) else np.nan
        changes.append({"N": code, "Nombre": name, "Inicio Promedio": round(first_avg,2) if pd.notna(first_avg) else np.nan, 
                        "Final Promedio": round(last_avg,2) if pd.notna(last_avg) else np.nan, 
                        "Diferencia": round(diff,2) if pd.notna(diff) else np.nan})
    return pd.DataFrame(changes)

def calculate_risk_score_data_tab(df_change, df_metas_summary, df_cobranza, code_to_name_map):
    """Calcula el score de riesgo."""
    if df_change.empty: return pd.DataFrame()
    today = datetime.today()
    # Ensure df_cobranza and df_metas_summary have 'Semana'
    df_cob_closed = df_cobranza[df_cobranza["Semana"].apply(lambda w: w.end_time < today)] if "Semana" in df_cobranza else pd.DataFrame()
    df_metas_closed = df_metas_summary[df_metas_summary["Semana"].apply(lambda w: w.end_time < today)] if "Semana" in df_metas_summary else pd.DataFrame()
    
    rows = []
    for _, r_change in df_change.iterrows():
        # Ensure 'N' is in r_change before using it
        if "N" not in r_change: continue
        avg_comp = _get_recent_weeks_compliance_for_risk(r_change["N"], df_metas_closed, df_cob_closed, code_to_name_map)
        row_data = r_change.to_dict()
        row_data["Cumpl. 4 Semanas (%)"] = avg_comp
        rows.append(row_data)

    df_risk = pd.DataFrame(rows)
    if df_risk.empty: return df_risk

    c_comp = lambda c: 0 if c >= 95 else ((95-c)/(95-80) if c >= 80 else 1)
    d_comp = lambda d: 0 if pd.isna(d) or d <= 0 else min(d,3)/3.0 # Handle NaN in Diferencia
    df_risk["score_0to1"] = (0.7 * df_risk["Cumpl. 4 Semanas (%)"].apply(c_comp) + 
                             0.3 * df_risk["Diferencia"].apply(d_comp))
    df_risk["score_riesgo"] = (df_risk["score_0to1"]*100).round(2)
    return df_risk

def display_risk_analysis_tables(df_risk_tab):
    """Muestra las tablas de ranking principal y en default."""
    if df_risk_tab.empty or "Cumpl. 4 Semanas (%)" not in df_risk_tab.columns or "score_riesgo" not in df_risk_tab.columns: 
        st.write("No hay datos de riesgo para mostrar o faltan columnas requeridas.")
        return
    df_default = df_risk_tab[df_risk_tab["Cumpl. 4 Semanas (%)"] < 7].copy()
    df_principal = df_risk_tab[df_risk_tab["Cumpl. 4 Semanas (%)"] >= 7].copy()
    cols_to_show = ["N", "Nombre", "Inicio Promedio (día pago)", "Final Promedio (día pago)", "Diferencia", "Cumpl. 4 Semanas (%)", "score_riesgo"]
    
    def style_score(val):
        if pd.isna(val): return ""
        if val < 11: return "background-color: green; color: white;"
        elif val < 35: return "background-color: orange; color: black;"
        else: return "background-color: red; color: white;"

    st.markdown("### Ranking Principal (con 7% o más de Cumplimiento en 4 Semanas)")
    if not df_principal.empty:
        df_principal.sort_values("score_riesgo", ascending=False, inplace=True)
        st.dataframe(df_principal[cols_to_show].style.applymap(style_score, subset=["score_riesgo"]), use_container_width=True)
    else: st.write("No hay promotores en el ranking principal.")

    if not df_default.empty:
        st.markdown("### Promotores en Default (Cumplimiento <7%)")
        df_default.sort_values("score_riesgo", ascending=False, inplace=True)
        st.dataframe(df_default[cols_to_show].style.applymap(style_score, subset=["score_riesgo"]), use_container_width=True)

def display_promoter_kpis_tab(promotor_sel_code, df_metas_summary_tab, df_cobranza_tab, df_pagos_raw_tab, df_control_tab, code_to_name_map):
    """Muestra KPIs históricos y actuales para el promotor seleccionado."""
    nombre_promotor = code_to_name_map.get(promotor_sel_code, "Desconocido")
    antiguedad_val = df_control_tab.loc[df_control_tab["N"] == promotor_sel_code, "Antigüedad (meses)"].iloc[0] if not df_control_tab.empty and "Antigüedad (meses)" in df_control_tab.columns else "N/A"
    
    df_cob_prom = df_cobranza_tab[df_cobranza_tab["N"] == promotor_sel_code].copy() if "N" in df_cobranza_tab else pd.DataFrame()
    estados = ", ".join(df_cob_prom["Estado"].dropna().unique()) if not df_cob_prom.empty and "Estado" in df_cob_prom else "No registrado"
    municipios = ", ".join(df_cob_prom["Municipio"].dropna().unique()) if not df_cob_prom.empty and "Municipio" in df_cob_prom else "No registrado"

    st.markdown(f"**Número Promotor (Código):** {promotor_sel_code}")
    st.markdown(f"**Nombre Promotor:** {nombre_promotor}")
    st.markdown(f"**Antigüedad (meses):** {antiguedad_val}")
    st.markdown(f"**Estado(s):** {estados}")
    st.markdown(f"**Municipio(s):** {municipios}")

    meta_hist = df_metas_summary_tab.loc[df_metas_summary_tab["Promotor"] == promotor_sel_code, "Meta"].sum() if not df_metas_summary_tab.empty else 0
    cob_hist = df_cob_prom["Depósito"].sum() if not df_cob_prom.empty else 0
    dif_hist = cob_hist - meta_hist
    
    hoy = datetime.now().date()
    df_pagos_prom_raw = df_pagos_raw_tab[df_pagos_raw_tab["N"] == promotor_sel_code].copy() if not df_pagos_raw_tab.empty and "N" in df_pagos_raw_tab else pd.DataFrame()

    clientes_activos = 0; clientes_vencidos = 0; saldo_vencido_total = 0; clientes_atrasados = 0; cartera_ind = 0
    if not df_pagos_prom_raw.empty and "VENCI" in df_pagos_prom_raw and "SV" in df_pagos_prom_raw and "PS" in df_pagos_prom_raw and "SALDO" in df_pagos_prom_raw:
        df_pagos_prom_raw["VENCI_date"] = pd.to_datetime(df_pagos_prom_raw["VENCI"], errors='coerce').dt.date
        clientes_activos = (df_pagos_prom_raw["VENCI_date"] >= hoy).sum()
        clientes_vencidos = ((df_pagos_prom_raw["VENCI_date"] < hoy) & (df_pagos_prom_raw["SV"] > 0)).sum()
        saldo_vencido_total = df_pagos_prom_raw["SV"].sum()
        clientes_atrasados = ((df_pagos_prom_raw["VENCI_date"] >= hoy) & (df_pagos_prom_raw["SV"] > df_pagos_prom_raw["PS"])).sum()
        cartera_ind = df_pagos_prom_raw["SALDO"].sum()

    row1c1, row1c2, row1c3, row1c4 = st.columns(4)
    row1c1.metric("Nº de Clientes Activos",  f"{clientes_activos:,}")
    row1c2.metric("Clientes Vencidos",       f"{clientes_vencidos:,}")
    row1c3.metric("Saldo Vencido Total",     format_money(saldo_vencido_total))
    row1c4.metric("Clientes Atrasados",      f"{clientes_atrasados:,}")

    row2c1, row2c2, row2c3, row2c4 = st.columns(4)
    row2c1.metric("Valor Cartera Individual",  format_money(cartera_ind))
    row2c2.metric("Meta Total (Histórico)",    format_money(meta_hist))
    row2c3.metric("Cobranza Total (Histórico)",format_money(cob_hist))
    row2c4.metric("Diferencia Histórica",      format_money(dif_hist))

def display_promoter_weekly_summary_tab(promotor_sel_code, df_metas_summary_tab, df_cobranza_tab):
    """Muestra el resumen semanal de metas vs. cobranza para el promotor."""
    df_meta_prom = df_metas_summary_tab[df_metas_summary_tab["Promotor"] == promotor_sel_code] if not df_metas_summary_tab.empty else pd.DataFrame()
    df_cob_summary = df_cobranza_tab[df_cobranza_tab["N"] == promotor_sel_code].groupby("Semana")["Depósito"].sum().reset_index() if not df_cobranza_tab.empty and "N" in df_cobranza_tab else pd.DataFrame(columns=["Semana", "Depósito"])
    
    if df_meta_prom.empty and df_cob_summary.empty:
        st.warning("Este promotor no tiene datos de metas ni cobranzas.")
        return

    start_week = min(df_meta_prom["Semana"].min() if not df_meta_prom.empty else pd.NaT, 
                     df_cob_summary["Semana"].min() if not df_cob_summary.empty else pd.NaT)
    end_week = max(df_meta_prom["Semana"].max() if not df_meta_prom.empty else pd.NaT, 
                   df_cob_summary["Semana"].max() if not df_cob_summary.empty else pd.NaT)

    if pd.isna(start_week) or pd.isna(end_week):
        st.warning("No hay suficientes datos de semana para el resumen.")
        return

    full_weeks = pd.period_range(start=start_week.start_time, end=end_week.end_time, freq="W-FRI")
    df_weeks = pd.DataFrame({"Semana": full_weeks})

    df_merge = pd.merge(df_weeks, df_meta_prom[["Semana", "Meta"]], on="Semana", how="left")
    df_merge = pd.merge(df_merge, df_cob_summary, on="Semana", how="left") # df_cob_summary already has "Depósito"
    df_merge.rename(columns={"Meta": "Cobranza Meta", "Depósito": "Cobranza Realizada"}, inplace=True)
    df_merge[["Cobranza Meta", "Cobranza Realizada"]] = df_merge[["Cobranza Meta", "Cobranza Realizada"]].fillna(0)
    df_merge["Cumplimiento (%)"] = df_merge.apply(lambda r: round(r["Cobranza Realizada"] / r["Cobranza Meta"] * 100, 2) if r["Cobranza Meta"] > 0 else 0, axis=1)
    df_merge.sort_values(by="Semana", key=lambda col: col.apply(lambda p: p.start_time), inplace=True)

    st.write("#### Resumen Semanal del Promotor (Meta vs. Cobranza)")
    st.dataframe(df_merge[["Semana", "Cobranza Meta", "Cobranza Realizada", "Cumplimiento (%)"]].style.format({"Cumplimiento (%)": "{:.2f}%"}), use_container_width=True)

def display_promoter_placement_summary_tab(promotor_sel_code, df_col_merge_tab, df_desc_agg_tab):
    """Muestra el resumen de colocación de créditos para el promotor."""
    st.markdown("### Colocación de Créditos (Venta, Flujo y Descuentos)")
    if df_col_merge_tab.empty or "N" not in df_col_merge_tab.columns:
        st.info("No se encontraron datos consolidados de colocaciones.")
        return
    
    df_sel = df_col_merge_tab[df_col_merge_tab["N"] == promotor_sel_code].copy()
    if df_sel.empty:
        st.write("No hay registros de colocación para este promotor.")
        return
    
    df_merged = pd.merge(df_sel, df_desc_agg_tab, on=["N","Semana"], how="left") if not df_desc_agg_tab.empty else df_sel.assign(Descuento_Renovacion=0)
    df_merged["Descuento_Renovacion"] = df_merged["Descuento_Renovacion"].fillna(0)

    total_credits_placed = df_merged["Creditos_Colocados"].sum()
    total_credits_renewed = len(df_desc_agg_tab[(df_desc_agg_tab["N"] == promotor_sel_code) & (df_desc_agg_tab["Descuento_Renovacion"] > 0)]) if not df_desc_agg_tab.empty else 0
    total_credits_new = max(0, total_credits_placed - total_credits_renewed)
    total_venta = df_merged["Venta"].sum()
    total_desc = df_merged["Descuento_Renovacion"].sum()
    total_flujo = total_venta * 0.9
    total_flujo_final = total_flujo - total_desc

    colC1, colC2, colC3 = st.columns(3)
    colC1.metric("Créditos Colocados (Hist. Promotor)", f"{int(total_credits_placed)}")
    colC2.metric("Créditos Nuevos", f"{int(total_credits_new)}")
    colC3.metric("Créditos Renovados", f"{int(total_credits_renewed)}")

    colC4, colC5, colC6, colC7 = st.columns(4)
    colC4.metric("Venta (Hist. Promotor)", format_money(total_venta))
    colC5.metric("Flujo (Hist. Promotor)", format_money(total_flujo))
    colC6.metric("Desc. Renov. (Hist. Prom.)", format_money(total_desc))
    colC7.metric("Flujo Final (Hist.)", format_money(total_flujo_final))

    df_agr = df_merged.groupby("Semana", as_index=False).agg(
        Creditos_Colocados=("Creditos_Colocados", "sum"), Venta=("Venta", "sum"), Descuento_Renovacion=("Descuento_Renovacion", "sum"))
    df_agr["Flujo"] = df_agr["Venta"] * 0.9
    df_agr["Flujo Final"] = df_agr["Flujo"] - df_agr["Descuento_Renovacion"]
    # ... (Formatting and display of df_agr as in original tab)
    st.dataframe(df_agr, use_container_width=True)


def prepare_credit_details_data_tab(df_col_prom_orig, df_cob_prom_detail):
    """Prepara los datos detallados de créditos para un promotor."""
    if df_col_prom_orig.empty: return pd.DataFrame()
    excel_map = {"Nombre del cliente": "Cliente", "Contrato": "Contrato", "Cuota total": "PS", "Fecha primer pago": "FechaPrimerPago"}
    df_col = df_col_prom_orig.rename(columns={k:v for k,v in excel_map.items() if k in df_col_prom_orig.columns})

    crit_cols = ["FechaPrimerPago", "PS", "Contrato", "Cliente"]
    if not all(c in df_col.columns for c in crit_cols):
        missing_display = [excel_map.get(c, c) for c in crit_cols if c not in df_col.columns] # Show user-friendly names
        st.error(f"Faltan columnas críticas ({', '.join(missing_display)}) en los datos de Colocaciones para generar el detalle de créditos. Verifique que su archivo Excel 'Colocaciones.xlsx' (hoja 'Colocación', fila 5) contenga estas columnas.")
        return pd.DataFrame()
        
    df_col["FechaPrimerPago"] = pd.to_datetime(df_col["FechaPrimerPago"], errors='coerce')
    df_col["PS"] = pd.to_numeric(df_col["PS"], errors='coerce').fillna(0)
    df_col.dropna(subset=["FechaPrimerPago", "Contrato", "Cliente"], inplace=True) 

    filas = []
    hoy = datetime.now().date()
    for _, cred in df_col.iterrows():
        contrato, ps_val, fecha_fp_obj = cred.get("Contrato"), cred.get("PS", 0), cred.get("FechaPrimerPago")
        if contrato is None or pd.isna(fecha_fp_obj): continue
        
        fecha_fp = fecha_fp_obj.date()
        weeks_elapsed = max(0, (hoy - fecha_fp).days // 7)
        pag_debidos = min(14, weeks_elapsed + 1) 

        total_dep = 0
        if not df_cob_prom_detail.empty and "Contrato" in df_cob_prom_detail.columns and "Deposito" in df_cob_prom_detail.columns:
            pagos = df_cob_prom_detail[df_cob_prom_detail["Contrato"] == contrato] # Ensure Contrato type matches
            total_dep = pagos["Deposito"].sum()
        
        completos, resto = (min(int(total_dep // ps_val), 14), total_dep % ps_val) if ps_val > 0 else (0,0)
        incompletos = 1 if 0 < resto < ps_val else 0
        vencido_monto = max(0, pag_debidos * ps_val - total_dep)
        adelantados = max(0, completos - pag_debidos)
        fecha_venc_credito = (fecha_fp + pd.Timedelta(weeks=13))
        
        estatus, color = "Indeterminado", "grey"
        if completos >= 14 : estatus, color = "Liquidado", "blue"
        elif completos >= pag_debidos: estatus, color = "Al corriente", "green"
        elif hoy < fecha_venc_credito : estatus, color = "Atrasado", "orange"
        else: estatus, color = "Vencido", "red"

        filas.append({
            "Cliente": cred.get("Cliente", "N/A"), "Contrato": contrato,
            "Pagos debidos": pag_debidos, "Pagos completos": completos,
            "Pagos incompletos": incompletos, "Saldo vencido": vencido_monto,
            "Pagos adelantados": adelantados, "Estatus": estatus, "Color": color,
        })
    return pd.DataFrame(filas)

def display_credit_details_table_tab(df_det):
    """Muestra la tabla de detalles de crédito."""
    if df_det.empty:
        st.info("No hay detalles de crédito para mostrar para el promotor seleccionado (o datos insuficientes).")
        return
    df_det["Saldo vencido"] = df_det["Saldo vencido"].apply(format_money)
    st.dataframe(df_det.style.apply(lambda r: [f"color: {r.get('Color','grey')}; font-weight: bold;" if c=="Estatus" else "" for c in r.index], axis=1), 
                 use_container_width=True, height=min(600, 35 + 30*len(df_det)), column_config={"Color":None})

# --------------------------------------------------------------------
#                        FUNCIÓN PRINCIPAL (main)
# --------------------------------------------------------------------
def main():
    st.sidebar.title("Parámetros y Archivos")
    vas_file = st.sidebar.file_uploader("1) Archivo de metas y control (VasTu.xlsx)", type=["xlsx"])
    cob_file = st.sidebar.file_uploader("2) Archivo de cobranza (Cobranza.xlsx)", type=["xlsx"])
    # ... (Resto de file_uploaders)
    col_file = st.sidebar.file_uploader("3) Archivo de colocaciones (Colocaciones.xlsx)", type=["xlsx"])
    por_capturar_file = st.sidebar.file_uploader("4) Archivo de Descuento Renovación", type=["xlsx"])
    pagos_file = st.sidebar.file_uploader("5) Archivo de Pagos Esperados", type=["xlsx"])


    st.title("Dashboard de Promotores")
    with st.expander("Información general del Dashboard", expanded=False):
        st.markdown("...") # Welcome message

    if vas_file and cob_file:
        try:
            df_control, _, df_metas_summary = load_data_control(vas_file)
            df_cobranza = load_data_cobranza(cob_file)
            
            code_to_name = dict(zip(df_control["N"], df_control["Nombre"])) if not df_control.empty and "N" in df_control.columns and "Nombre" in df_control.columns else {}
            norm_name_to_code = dict(zip(df_control["Nombre"].apply(normalize_name), df_control["N"])) if not df_control.empty and "N" in df_control.columns and "Nombre" in df_control.columns else {}

            if not code_to_name: st.error("Archivo de control (VasTu.xlsx) no cargado o inválido (falta 'N' o 'Nombre'). Funcionalidad limitada.")

            # Map 'N' to df_cobranza
            if not df_cobranza.empty and norm_name_to_code:
                df_cobranza["Nombre_norm"] = df_cobranza["Nombre Promotor"].apply(normalize_name)
                df_cobranza["N"] = df_cobranza["Nombre_norm"].map(norm_name_to_code)
                unmapped_cob_idx = df_cobranza["N"].isna()
                if unmapped_cob_idx.any():
                    choices_cob = list(norm_name_to_code.keys())
                    df_cobranza.loc[unmapped_cob_idx, "N"] = df_cobranza.loc[unmapped_cob_idx, "Nombre_norm"].apply(lambda nm: fuzzy_map(nm, choices_cob)).map(norm_name_to_code)
                    if df_cobranza["N"].isna().any(): # Still unmapped after fuzzy
                        unmapped_names = df_cobranza[df_cobranza["N"].isna()]["Nombre Promotor"].unique()
                        st.warning(f"En Cobranza.xlsx, {len(unmapped_names)} promotor(es) no mapeados: {', '.join(unmapped_names)}.")
            elif not df_cobranza.empty: st.warning("No se mapearon nombres en Cobranza.xlsx (problemas con archivo control).")
            
            df_col_agg, df_col_details_raw = load_data_colocaciones(col_file)
            df_col_info_completa = pd.DataFrame() 
            if not df_col_details_raw.empty and "Nombre promotor" in df_col_details_raw.columns and not df_control.empty:
                df_col_info_completa = df_col_details_raw.copy()
                if "Nombre_upper" in df_control.columns and "N" in df_control.columns:
                    map_upper_to_N = dict(zip(df_control["Nombre_upper"], df_control["N"]))
                    df_col_info_completa["N"] = df_col_info_completa["Nombre promotor"].map(map_upper_to_N)
                
                unmapped_col_idx = df_col_info_completa["N"].isna()
                if unmapped_col_idx.any() and norm_name_to_code:
                    choices_col = list(norm_name_to_code.keys())
                    df_col_info_completa.loc[unmapped_col_idx, "N"] = df_col_info_completa.loc[unmapped_col_idx, "Nombre promotor"].apply(normalize_name).map(norm_name_to_code)
                    still_unmapped_col_idx = df_col_info_completa["N"].isna() & unmapped_col_idx
                    if still_unmapped_col_idx.any():
                         df_col_info_completa.loc[still_unmapped_col_idx, "N"] = df_col_info_completa.loc[still_unmapped_col_idx, "Nombre promotor"].apply(normalize_name).apply(lambda nm: fuzzy_map(nm, choices_col)).map(norm_name_to_code)
                
                if "N" in df_col_info_completa and df_col_info_completa["N"].isna().any():
                    unmapped_col_names = df_col_info_completa[df_col_info_completa["N"].isna()]["Nombre promotor"].unique()
                    st.warning(f"En Colocaciones.xlsx, {len(unmapped_col_names)} promotor(es) no mapeados: {', '.join(unmapped_col_names)}.")


            df_col_merge = merge_colocaciones(df_col_agg, df_control)
            df_desc_agg = load_data_descuentos(por_capturar_file, df_control)
            df_pagos_raw = load_data_pagos(pagos_file)

            if not df_pagos_raw.empty and "PROMOTOR" in df_pagos_raw.columns and norm_name_to_code:
                df_pagos_raw["PROMOTOR_norm"] = df_pagos_raw["PROMOTOR"].apply(normalize_name)
                df_pagos_raw["N"] = df_pagos_raw["PROMOTOR_norm"].map(norm_name_to_code)
                unmapped_pagos_idx = df_pagos_raw["N"].isna()
                if unmapped_pagos_idx.any():
                    choices_pagos = list(norm_name_to_code.keys())
                    df_pagos_raw.loc[unmapped_pagos_idx, "N"] = df_pagos_raw.loc[unmapped_pagos_idx, "PROMOTOR_norm"].apply(lambda nm: fuzzy_map(nm, choices_pagos)).map(norm_name_to_code)
                    if df_pagos_raw["N"].isna().any():
                        unmapped_pagos_names = df_pagos_raw[df_pagos_raw["N"].isna()]["PROMOTOR"].unique()
                        st.warning(f"En Pagos Esperados.xlsx, {len(unmapped_pagos_names)} promotor(es) no mapeados: {', '.join(unmapped_pagos_names)}.")
            elif not df_pagos_raw.empty: st.warning("No se mapearon nombres en Pagos Esperados.xlsx (problemas con archivo control).")
            
            df_pagos = df_pagos_raw.dropna(subset=["N"]).groupby("N")["SALDO"].sum().reset_index() if "N" in df_pagos_raw else pd.DataFrame(columns=["N","SALDO"])
            df_promoters_summary = build_promoters_summary(df_control, df_metas_summary, df_cobranza)

        except ValueError as ve: st.error(f"Error de configuración/datos: {ve}"); return
        except Exception as e: st.error(f"Error inesperado al cargar datos: {e}"); return

        tabs = st.tabs(["Globales", "Resumen", "Ranking", "Patrón Pago", "Incumplimiento", "Detalle Promotor", "Detalle Créditos", "Totales"])

        with tabs[0]: # Datos Globales
            # ... (Content as previously, ensuring it uses globally loaded dataframes)
            st.write("Contenido Pestaña Datos Globales")


        with tabs[3]: # Análisis de Cambio de Patrón
            st.header("Análisis de Cambio de Patrón de Pago")
            if not df_cobranza.empty and "N" in df_cobranza.columns and code_to_name and not df_metas_summary.empty:
                df_change = calculate_payment_pattern_changes_tab(df_cobranza, code_to_name)
                if not df_change.empty:
                    st.markdown("### Variación en el Día Promedio de Pago")
                    st.dataframe(df_change.style.applymap(style_difference, subset=["Diferencia"]), use_container_width=True)
                    df_risk = calculate_risk_score_data_tab(df_change, df_metas_summary, df_cobranza, code_to_name)
                    display_risk_analysis_tables(df_risk)
                else: st.write("No hay datos para el análisis de cambio de patrón.")
            else: st.write("Datos insuficientes para este análisis.")
        
        with tabs[5]: # Detalles del Promotor
            st.header("Detalles del Promotor")
            if df_control.empty or not code_to_name: st.write("Datos de control no disponibles.")
            else:
                prom_list_details = sorted(list(code_to_name.keys()), key=lambda x: int(str(x).lstrip("P")))
                selected_prom_code_details = st.selectbox("Selecciona Promotor (Código):", prom_list_details, 
                                                          format_func=lambda x: f"{x} - {code_to_name.get(x, '')}", 
                                                          key="detail_prom_sel_refactored")
                if selected_prom_code_details:
                    display_promoter_kpis_tab(selected_prom_code_details, df_metas_summary, df_cobranza, df_pagos_raw, df_control, code_to_name)
                    display_promoter_weekly_summary_tab(selected_prom_code_details, df_metas_summary, df_cobranza)
                    display_promoter_placement_summary_tab(selected_prom_code_details, df_col_merge, df_desc_agg)


        with tabs[6]: # Créditos a Detalle
            st.header("Créditos a Detalle")
            if df_col_info_completa.empty or "N" not in df_col_info_completa.columns:
                st.warning("Datos de colocaciones detallados con códigos 'N' no disponibles.")
            elif not code_to_name: st.warning("Mapeo de promotores no disponible.")
            else:
                prom_codes_with_credits = sorted(df_col_info_completa["N"].dropna().unique(), key=lambda x: int(str(x).lstrip("P")))
                if not prom_codes_with_credits: st.info("No hay promotores con créditos detallados mapeados.")
                else:
                    sel_prom_credit_detail = st.selectbox("Promotor (Créditos):", prom_codes_with_credits, format_func=lambda x: f"{x} - {code_to_name.get(x, 'Desconocido')}", key="credit_detail_sel_refactored")
                    if sel_prom_credit_detail:
                        nombre_promotor_display_col_det = code_to_name.get(sel_prom_credit_detail, "Desconocido")
                        st.markdown(f"**Promotor:** {sel_prom_credit_detail} — {nombre_promotor_display_col_det}")
                        df_cols_prom = df_col_info_completa[df_col_info_completa["N"] == sel_prom_credit_detail]
                        df_cob_prom_cr = df_cobranza[df_cobranza["N"] == sel_prom_credit_detail] if "N" in df_cobranza else pd.DataFrame()
                        df_det_data = prepare_credit_details_data_tab(df_cols_prom, df_cob_prom_cr)
                        display_credit_details_table_tab(df_det_data)
    else:
        st.info("Por favor, sube los archivos de VasTu y Cobranza para comenzar.")

if __name__ == "__main__":
    main()
