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
    """
    Colorea la celda según el %:
    - Verde si val >= 97
    - Amarillo si val >= 85
    - Rojo si val < 85
    """
    try:
        if val >= 97:
            color = "green"
        elif val >= 85:
            color = "orange"
        else:
            color = "red"
        return f"color: {color}; font-weight: bold;"
    except:
        return ""

def style_difference(val):
    """
    - Rojo si ≥1.1
    - Amarillo si ≥0.65 y <1.1
    """
    if pd.isna(val):
        return ""
    if val >= 1.1:
        return "background-color: red; color: white;"
    elif val >= 0.65:
        return "background-color: yellow; color: black;"
    return ""

def normalize_name(s):
    """Quita tildes, pasa a mayúsculas y colapsa espacios."""
    s = str(s).strip().upper()
    # Descompone Unicode y quita marcas diacríticas
    s = "".join(c for c in unicodedata.normalize("NFKD", s) 
                if unicodedata.category(c) != "Mn")
    return " ".join(s.split())

def fuzzy_map(name, choices, cutoff=0.8):
    """
    Devuelve la coincidencia más cercana en 'choices' (lista de strings)
    si supera 'cutoff'; si no, None.
    """
    matches = get_close_matches(name, choices, n=1, cutoff=cutoff)
    return matches[0] if matches else None

def map_promoter_names_to_codes(df_to_map: pd.DataFrame, promoter_name_column: str, df_control: pd.DataFrame) -> pd.DataFrame:
    """
    Maps promoter names in a DataFrame to promoter codes ("N") using various strategies.

    Args:
        df_to_map: The DataFrame that needs promoter names mapped to codes.
        promoter_name_column: The name of the column in df_to_map containing promoter names.
        df_control: Control DataFrame with "N", "Nombre", "Nombre_upper", and "Nombre_norm".

    Returns:
        The df_to_map with an added "N" column containing mapped promoter codes.
    """
    if df_control.empty or not all(col in df_control.columns for col in ["N", "Nombre", "Nombre_upper", "Nombre_norm"]):
        st.warning("df_control está vacío o le faltan columnas esenciales ('N', 'Nombre', 'Nombre_upper', 'Nombre_norm'). No se puede mapear nombres.")
        df_to_map["N"] = pd.NA
        return df_to_map

    if promoter_name_column not in df_to_map.columns:
        st.warning(f"La columna '{promoter_name_column}' no existe en el DataFrame a mapear. No se puede mapear nombres.")
        df_to_map["N"] = pd.NA
        return df_to_map

    # Initialize "N" column
    df_to_map["N"] = pd.NA

    # --- a. Initial Cleaning (applied on a temporary column for mapping) ---
    temp_promoter_name_col = "_temp_promoter_name_upper"
    df_to_map[temp_promoter_name_col] = df_to_map[promoter_name_column].astype(str).str.strip().str.upper()

    # --- b. Direct Mapping (using Nombre_upper) ---
    map_upper_to_N = dict(zip(df_control["Nombre_upper"], df_control["N"]))
    df_to_map["N"] = df_to_map[temp_promoter_name_col].map(map_upper_to_N)

    # --- c. Normalized Name Mapping (for remaining unmapped names) ---
    unmapped_indices = df_to_map["N"].isna()
    if unmapped_indices.any():
        # Normalize names in df_to_map for those still unmapped
        temp_normalized_name_col = "_temp_normalized_name"
        df_to_map.loc[unmapped_indices, temp_normalized_name_col] = df_to_map.loc[unmapped_indices, temp_promoter_name_col].apply(normalize_name)
        
        # Map using df_control's pre-normalized "Nombre_norm"
        map_norm_to_N = dict(zip(df_control["Nombre_norm"], df_control["N"]))
        df_to_map.loc[unmapped_indices, "N"] = df_to_map.loc[unmapped_indices, temp_normalized_name_col].map(map_norm_to_N)

    # --- d. Fuzzy Mapping (for remaining unmapped names) ---
    unmapped_indices = df_to_map["N"].isna() # Re-check unmapped indices
    if unmapped_indices.any():
        # Ensure normalized names exist for all current unmapped rows if not created in step c for all
        if temp_normalized_name_col not in df_to_map.columns: # Should have been created
             df_to_map[temp_normalized_name_col] = df_to_map[temp_promoter_name_col].apply(normalize_name)
        elif df_to_map.loc[unmapped_indices, temp_normalized_name_col].isnull().any(): # If some were not populated
            df_to_map.loc[unmapped_indices & df_to_map[temp_normalized_name_col].isnull(), temp_normalized_name_col] = \
                df_to_map.loc[unmapped_indices & df_to_map[temp_normalized_name_col].isnull(), temp_promoter_name_col].apply(normalize_name)


        choices_fuzzy = df_control["Nombre_norm"].unique().tolist()
        
        # Apply fuzzy_map to the temporary normalized column for unmapped rows
        df_to_map.loc[unmapped_indices, "_temp_fuzzy_match"] = df_to_map.loc[unmapped_indices, temp_normalized_name_col].apply(
            lambda name_to_match: fuzzy_map(name_to_match, choices_fuzzy, cutoff=0.8) # Standard cutoff
        )
        
        # Map fuzzy matches back to N using the Nombre_norm -> N map
        map_norm_to_N_for_fuzzy = dict(zip(df_control["Nombre_norm"], df_control["N"])) # Re-ensure map
        df_to_map.loc[unmapped_indices, "N"] = df_to_map.loc[unmapped_indices, "_temp_fuzzy_match"].map(map_norm_to_N_for_fuzzy)


    # Clean up temporary columns
    temp_cols_to_drop = [temp_promoter_name_col, "_temp_normalized_name", "_temp_fuzzy_match"]
    for col in temp_cols_to_drop:
        if col in df_to_map.columns:
            df_to_map.drop(columns=[col], inplace=True)
            
    unmapped_count = df_to_map["N"].isna().sum()
    if unmapped_count > 0:
        st.warning(f"{unmapped_count} nombres de promotor(es) en la columna '{promoter_name_column}' no pudieron ser mapeados a un código 'N'.")

    return df_to_map

# --------------------------------------------------------------------
#                       CARGA DE DATOS (CACHED)
# --------------------------------------------------------------------
@st.cache_data
def load_data_control(vas_file):
    if not vas_file:
        df_control_empty = pd.DataFrame(columns=["N", "Nombre", "Antigüedad (meses)", "Nombre_upper", "Nombre_norm"])
        promotores_dict_empty = {}
        # Based on current logic, df_metas_summary is built from df_metas with ["Promotor", "Semana", "Meta"]
        df_metas_summary_empty = pd.DataFrame(columns=["Promotor", "Semana", "Meta"])
        return df_control_empty, promotores_dict_empty, df_metas_summary_empty

    df_control = pd.read_excel(vas_file, sheet_name="Control")
    required_cols_control = ["N", "Nombre", "Antigüedad (meses)"]
    check_required_columns(df_control, required_cols_control, "df_control (sheet Control)")

    df_control["N"] = df_control["N"].astype(str).str.strip().str.upper()
    df_control["Nombre"] = df_control["Nombre"].str.strip()
    df_control["Antigüedad (meses)"] = df_control["Antigüedad (meses)"].apply(
        lambda x: round(x, 2) if pd.notna(x) else x
    )
    # <-- CAMBIO: creamos "Nombre_upper" en df_control para facilitar mapeos
    df_control["Nombre_upper"] = df_control["Nombre"].str.strip().str.upper()
    df_control["Nombre_norm"] = df_control["Nombre"].apply(normalize_name) # Ensure Nombre_norm is created

    promotores_dict = dict(zip(df_control["N"], df_control["Nombre"]))

    xls = pd.ExcelFile(vas_file)
    lista_metas = []
    for sheet in xls.sheet_names:
        if sheet.lower() != "control":
            df_sheet = pd.read_excel(vas_file, sheet_name=sheet, header=1)
            if df_sheet.shape[1] < 3:
                st.warning(f"La hoja '{sheet}' no tiene el formato esperado (mínimo 3 columnas). Se omitirá.")
                continue
            data = df_sheet.iloc[:, [1, 2]].copy()
            data.columns = ["Fecha", "Meta"]
            data["Promotor"] = sheet.strip().upper()
            lista_metas.append(data)

    if lista_metas:
        df_metas = pd.concat(lista_metas, ignore_index=True)
    else:
        df_metas = pd.DataFrame(columns=["Fecha", "Meta", "Promotor"])

    df_metas["Fecha"] = pd.to_datetime(df_metas["Fecha"], errors="coerce")
    df_metas["Semana"] = df_metas["Fecha"].dt.to_period("W-FRI")
    df_metas_summary = df_metas.groupby(["Promotor", "Semana"])["Meta"].first().reset_index()

    return df_control, promotores_dict, df_metas_summary

@st.cache_data
def load_data_cobranza(cob_file):
    if not cob_file:
        return pd.DataFrame(columns=[
            "Nombre Promotor", "Fecha Transacción", "Depósito", "Estado", 
            "Municipio", "Contrato", "Semana", "Día_num", "N"
        ])

    df_cobranza = pd.read_excel(
        cob_file,
        sheet_name="Recuperaciones",
        skiprows=4,
        usecols=["Nombre Promotor", "Fecha transacción", "Depósito", "Estado", "Municipio", "Contrato"]
    )
    required_cols_cob = ["Nombre Promotor", "Fecha transacción", "Depósito", "Estado", "Municipio", "Contrato"  ]
    check_required_columns(df_cobranza, required_cols_cob, "df_cobranza (sheet Recuperaciones)")

    df_cobranza["Fecha transacción"] = pd.to_datetime(df_cobranza["Fecha transacción"], errors="coerce")
    df_cobranza["Depósito"] = df_cobranza["Depósito"].apply(convert_number)
    df_cobranza.dropna(subset=["Nombre Promotor", "Depósito"], inplace=True)

    df_cobranza.rename(columns={"Fecha transacción": "Fecha Transacción"}, inplace=True)
    df_cobranza["Semana"] = df_cobranza["Fecha Transacción"].dt.to_period("W-FRI")
    df_cobranza["Nombre Promotor"] = df_cobranza["Nombre Promotor"].str.strip().str.upper()
    df_cobranza["Día_num"] = ((df_cobranza["Fecha Transacción"].dt.dayofweek - 5) % 7) + 1
    return df_cobranza

@st.cache_data
def load_data_colocaciones(col_file):
    """
    Carga y procesa los datos de colocaciones desde un archivo Excel.

    Args:
        col_file: Objeto de archivo cargado para el archivo de colocaciones.

    Returns:
        tuple: Dos DataFrames:
            - df_col_agg: DataFrame agregado con ["Nombre promotor", "Semana", "Creditos_Colocados", "Venta"].
            - df_col_detail_return: DataFrame detallado con las columnas de `cols_to_read_from_excel`.
            Ambos son DataFrames vacíos con la estructura definida si hay errores o no hay archivo.
    """
    cols_to_read_from_excel = [
        "Nombre promotor", "Fecha desembolso", "Monto desembolsado",
        "Nombre del cliente", "Contrato", "Cuota total", "Fecha primer pago"
    ]
    
    # Definir estructuras de DataFrames vacíos para retorno consistente
    empty_agg = pd.DataFrame(columns=["Nombre promotor", "Semana", "Creditos_Colocados", "Venta"])
    # Asegurar que el orden de columnas en empty_detail sea el mismo que cols_to_read_from_excel
    empty_detail = pd.DataFrame(columns=cols_to_read_from_excel)

    if not col_file:
        return empty_agg, empty_detail

    try:
        df_col_raw = pd.read_excel(
            col_file,
            sheet_name="Colocación",
            skiprows=4,
            header=0
        )
    except FileNotFoundError:
        st.error("Error: Archivo de Colocaciones no encontrado. Por favor, verifica la ruta o el archivo.")
        return empty_agg, empty_detail
    except ValueError as e: # Específicamente para hoja no encontrada
        if "Colocación" in str(e):
            st.error("Error CRÍTICO: La hoja 'Colocación' no se encontró en el archivo de Colocaciones.")
            st.info("Por favor, asegúrate de que tu archivo Excel contenga una hoja llamada exactamente 'Colocación'.")
        else:
            st.error(f"Error al leer el archivo de Colocaciones: {e}")
        return empty_agg, empty_detail
    except Exception as e:
        st.error(f"Error CRÍTICO al leer el archivo de Colocaciones (hoja 'Colocación'): {e}")
        return empty_agg, empty_detail

    # Verificar columnas requeridas
    missing_cols = [col for col in cols_to_read_from_excel if col not in df_col_raw.columns]
    if missing_cols:
        st.error(f"Faltan las siguientes columnas requeridas en la hoja 'Colocación': {', '.join(missing_cols)}")
        st.warning(f"Columnas encontradas en tu archivo Excel: {', '.join(df_col_raw.columns.tolist())}")
        st.info("Por favor, asegúrate de que los nombres de las columnas en tu archivo Excel (fila 5) coincidan exactamente con los esperados.")
        return empty_agg, empty_detail # Devolver empty_detail en lugar de df_col_raw

    # Crear df_col_detail_return con las columnas especificadas y en el orden correcto
    df_col_detail_return = df_col_raw[cols_to_read_from_excel].copy()

    # Limpieza y transformación de datos para df_col_detail_return
    if "Nombre promotor" in df_col_detail_return.columns:
        df_col_detail_return["Nombre promotor"] = df_col_detail_return["Nombre promotor"].astype(str).str.strip().str.upper()
    
    if "Fecha desembolso" in df_col_detail_return.columns:
        df_col_detail_return["Fecha desembolso"] = pd.to_datetime(df_col_detail_return["Fecha desembolso"], errors='coerce')
    
    if "Fecha primer pago" in df_col_detail_return.columns:
        df_col_detail_return["Fecha primer pago"] = pd.to_datetime(df_col_detail_return["Fecha primer pago"], errors='coerce')
    
    if "Monto desembolsado" in df_col_detail_return.columns:
        df_col_detail_return["Monto desembolsado"] = df_col_detail_return["Monto desembolsado"].astype(str).str.replace(',', '', regex=False)
        df_col_detail_return["Monto desembolsado"] = pd.to_numeric(df_col_detail_return["Monto desembolsado"], errors='coerce').fillna(0)

    if "Cuota total" in df_col_detail_return.columns:
        df_col_detail_return["Cuota total"] = df_col_detail_return["Cuota total"].astype(str).str.replace(',', '', regex=False)
        df_col_detail_return["Cuota total"] = pd.to_numeric(df_col_detail_return["Cuota total"], errors='coerce').fillna(0)

    # Preparación para la agregación de df_col_agg
    required_for_agg = ["Nombre promotor", "Fecha desembolso", "Monto desembolsado"]
    
    # Verificar si las columnas necesarias para la agregación están presentes y no son todas NaN
    # Usamos df_col_detail_return como base ya que está limpio
    if all(col in df_col_detail_return.columns for col in required_for_agg) and \
       not df_col_detail_return[required_for_agg].isnull().all().all(): # Verifica que no todas las celdas en las cols de agg sean NaN

        # Realizar una copia para la agregación para no afectar df_col_detail_return innecesariamente
        df_for_agg = df_col_detail_return[required_for_agg].copy()

        # Eliminar filas donde CUALQUIERA de las columnas clave para la agregación sea NaN
        # Esto es importante para asegurar que "count" y "sum" funcionen correctamente.
        df_for_agg.dropna(subset=required_for_agg, inplace=True)

        if not df_for_agg.empty:
            # "Nombre promotor" ya está limpio en df_col_detail_return
            # "Fecha desembolso" ya está como datetime
            # "Monto desembolsado" ya está como numérico y con NaNs en 0 (aunque dropna los quita)

            df_for_agg["Semana"] = df_for_agg["Fecha desembolso"].dt.to_period("W-FRI")
            
            df_col_agg = df_for_agg.groupby(["Nombre promotor", "Semana"], as_index=False).agg(
                Creditos_Colocados=("Monto desembolsado", "count"),
                Venta=("Monto desembolsado", "sum")
            )
        else:
            # Si df_for_agg queda vacío después de dropna, retornar empty_agg
            df_col_agg = empty_agg.copy()
    else:
        # Si faltan columnas clave o todas son NaN, no se puede agregar.
        # No es necesario un st.error aquí si ya se notificó la falta de columnas principales.
        # Si las columnas están pero son todos NaN, es un problema de datos, no de estructura.
        df_col_agg = empty_agg.copy()
        if not all(col in df_col_detail_return.columns for col in required_for_agg):
             st.warning(f"Advertencia: Faltan columnas esenciales para la agregación en Colocaciones: {[col for col in required_for_agg if col not in df_col_detail_return.columns]}. El resumen agregado de colocaciones puede estar incompleto o vacío.")


    return df_col_agg, df_col_detail_return

# <-- CAMBIO IMPORTANTE: Ajustamos la función para que reciba df_control y mapee el nombre al código
@st.cache_data
def load_data_descuentos(por_capturar_file, df_control):
    if not por_capturar_file:
        # Si no se carga el archivo, devolvemos un DataFrame vacío con la estructura esperada.
        return pd.DataFrame(columns=["N", "Semana", "Descuento_Renovacion"])

    try:
        df_desc_original = pd.read_excel(
            por_capturar_file,
            skiprows=3, # Asume que los encabezados están en la fila 4
            usecols=["Promotor", "Fecha Ministración", "Descuento Renovación"]
        )
    except Exception as e:
        st.error(f"Error al leer el archivo 'Por Capturar' de descuentos: {e}")
        return pd.DataFrame(columns=["N", "Semana", "Descuento_Renovacion"])

    required_cols_desc = ["Promotor", "Fecha Ministración", "Descuento Renovación"]
    missing_excel_cols = [col for col in required_cols_desc if col not in df_desc_original.columns]
    if missing_excel_cols:
        st.error(f"Faltan columnas en el Excel 'Por Capturar': {', '.join(missing_excel_cols)}. Columnas encontradas: {df_desc_original.columns.tolist()}")
        return pd.DataFrame(columns=["N", "Semana", "Descuento_Renovacion"])

    df_desc = df_desc_original.copy()

    df_desc["Promotor"] = df_desc["Promotor"].astype(str).str.strip().str.upper()
    df_desc["Descuento_Num_Temp"] = df_desc["Descuento Renovación"].apply(convert_number)
    
    df_desc.dropna(subset=["Promotor", "Descuento_Num_Temp"], inplace=True)
    
    # Aplicación del filtro para considerar solo descuentos estrictamente POSITIVOS
    df_desc = df_desc[df_desc["Descuento_Num_Temp"] > 0].copy()

    if df_desc.empty:
        # Si no quedan filas después del filtro > 0 (o si estaba vacío antes)
        return pd.DataFrame(columns=["N", "Semana", "Descuento_Renovacion"])

    # Mapeo de "Promotor" a "N" (CodigoPromotor) utilizando la nueva función centralizada
    df_desc = map_promoter_names_to_codes(df_desc, "Promotor", df_control)
    # La columna "N" ya está en df_desc, no se necesita "CodigoPromotor"

    # Continuar con el resto de la lógica solo si hay filas con "N"
    if df_desc["N"].notna().any():
        df_desc_con_N = df_desc.dropna(subset=["N"]).copy() # Usar "N"
        
        df_desc_con_N["Fecha Ministración"] = pd.to_datetime(df_desc_con_N["Fecha Ministración"], errors="coerce")
        df_desc_con_N.dropna(subset=["Fecha Ministración"], inplace=True) 
        
        if not df_desc_con_N.empty:
            df_desc_con_N["Semana"] = df_desc_con_N["Fecha Ministración"].dt.to_period("W-FRI")
            
            # Agrupar por "N" directamente
            df_desc_agg = df_desc_con_N.groupby(["N", "Semana"], as_index=False)["Descuento_Num_Temp"].sum()
            
            df_desc_agg.rename(columns={
                # "N" ya es el nombre correcto
                "Descuento_Num_Temp": "Descuento_Renovacion"
            }, inplace=True)
        else:
            df_desc_agg = pd.DataFrame(columns=["N", "Semana", "Descuento_Renovacion"])
    else: 
        df_desc_agg = pd.DataFrame(columns=["N", "Semana", "Descuento_Renovacion"])

    return df_desc_agg



@st.cache_data
def load_data_pagos(pagos_file):
    """
    Carga el Excel de Pagos Esperados (fila 4 contiene PROMOTOR y SALDO).
    Devuelve un DataFrame con columnas ['PROMOTOR','SALDO'].
    """
    if not pagos_file:
        # Return structure that would be expected before mapping to "N"
        return pd.DataFrame(columns=["PROMOTOR", "SALDO", "PS", "SV", "VENCI"]) 

    df_pagos = pd.read_excel(
        pagos_file,
        skiprows=3,                  # saltamos las primeras 3 filas
        usecols=["PROMOTOR","SALDO","PS*","MULTAS","VENCI*"] # columnas obligatorias
    )
    required_cols_pagos = ["PROMOTOR","SALDO"]
    check_required_columns(df_pagos, required_cols_pagos, "df_pagos (Pagos Esperados)")

    df_pagos["PROMOTOR"] = df_pagos["PROMOTOR"].str.strip().str.upper()
    df_pagos["SALDO"]    = df_pagos["SALDO"].apply(convert_number)
    # --- NUEVO: estandarizamos y transformamos la columna PS* ---------------
    if "PS*" in df_pagos.columns:
        df_pagos.rename(columns={"PS*": "PS"}, inplace=True)     # quitamos el asterisco
        df_pagos["PS"] = pd.to_numeric(df_pagos["PS"], errors="coerce").fillna(0)
    else:
        df_pagos["PS"] = 0          # por si el archivo venía sin esa columna
        # --- NUEVO: columna Saldo Vencido (SV) ----------------------------------
    if "MULTAS" in df_pagos.columns:
        df_pagos.rename(columns={"MULTAS": "SV"}, inplace=True)
        df_pagos["SV"] = df_pagos["SV"].apply(convert_number).fillna(0)
    else:
        df_pagos["SV"] = 0
    # ---- VENCI* → VENCI (fecha de vencimiento) -----------------------------
    if "VENCI*" in df_pagos.columns:
        df_pagos.rename(columns={"VENCI*": "VENCI"}, inplace=True)
        df_pagos["VENCI"] = pd.to_datetime(df_pagos["VENCI"], errors="coerce")
    else:
        df_pagos["VENCI"] = pd.NaT




    df_pagos.dropna(subset=["PROMOTOR","SALDO"], inplace=True)

    return df_pagos


@st.cache_data
def merge_colocaciones(df_col_agg, df_control):
    if df_col_agg.empty:
        return pd.DataFrame()
    # df_control["Nombre_upper"] ya existe y se usa para unificar
    df_col_merge = pd.merge(
        df_col_agg,
        df_control,
        left_on="Nombre promotor",
        right_on="Nombre_upper",
        how="left"
    )
    return df_col_merge

@st.cache_data
def build_promoters_summary(df_control, df_metas_summary, df_cobranza):
    promoters_summary_list = []
    for _, row in df_control.iterrows():
        code = row["N"]
        name = row["Nombre"]
        antig = row["Antigüedad (meses)"]

        df_meta_prom = df_metas_summary[df_metas_summary["Promotor"] == code]
        total_meta = df_meta_prom["Meta"].sum() if not df_meta_prom.empty else 0

        if not df_cobranza.empty:
            total_cob = df_cobranza[df_cobranza["Nombre Promotor"] == name.upper()]["Depósito"].sum()
        else:
            total_cob = 0
        difference = total_cob - total_meta

        if pd.isna(antig) and total_meta == 0 and total_cob == 0:
            continue

        promoters_summary_list.append({
            "N": code,
            "Nombre": name,
            "Antigüedad (meses)": antig,
            "Total Metas": total_meta,
            "Total Cobranza": total_cob,
            "Diferencia": difference
        })

    df_promoters_summary = pd.DataFrame(promoters_summary_list)
    df_promoters_summary = df_promoters_summary.sort_values(
        by="N",
        key=lambda x: x.str.extract(r"(\d+)")[0].astype(int)
    )
    return df_promoters_summary

def main():
    st.sidebar.title("Parámetros y Archivos")
    vas_file = st.sidebar.file_uploader("1) Archivo de metas y control (VasTu.xlsx)", type=["xlsx"])
    cob_file = st.sidebar.file_uploader("2) Archivo de cobranza (Cobranza.xlsx)", type=["xlsx"])
    col_file = st.sidebar.file_uploader("3) Archivo de colocaciones (Colocaciones.xlsx)", type=["xlsx"])
    por_capturar_file = st.sidebar.file_uploader("4) Archivo de Descuento Renovación", type=["xlsx"])
    pagos_file = st.sidebar.file_uploader("5) Archivo de Pagos Esperados", type=["xlsx"])

    st.title("Dashboard de Promotores")

    with st.expander("Información general del Dashboard", expanded=False):
        st.markdown("""
        **Bienvenido** a este Dashboard. Aquí podrás:
        - Subir tus archivos Excel en la barra lateral.
        - Consultar datos globales y comparaciones semanales.
        - Ver resúmenes y rankings de promotores.
        - Analizar detalles de pago, por localidad, y colocaciones de créditos.
        
        Usa las **pestañas** para navegar entre las secciones.
        """)

    if vas_file and cob_file:
        try:
            df_control, promotores_dict, df_metas_summary = load_data_control(vas_file)
            df_cobranza = load_data_cobranza(cob_file)
            
            # Mapeo de nombres para df_cobranza
            if df_cobranza is not None and not df_cobranza.empty and "Nombre Promotor" in df_cobranza.columns:
                df_cobranza = map_promoter_names_to_codes(df_cobranza.copy(), "Nombre Promotor", df_control)
            elif df_cobranza is not None and "N" not in df_cobranza.columns: # Ensure N column if mapping did not run
                df_cobranza["N"] = pd.NA
            # La función map_promoter_names_to_codes ya limpia sus propias columnas temporales y maneja advertencias.

            # --- Carga de datos de colocaciones (agregado y detallado) ---
            df_col_agg, df_col_detail_return = load_data_colocaciones(col_file) # df_col_detail_return is the correct name

            # Mapeo de nombres para df_col_detail_return (que se convertirá en df_colocaciones_info_completa)
            if df_col_detail_return is not None and not df_col_detail_return.empty:
                if "Nombre promotor" in df_col_detail_return.columns:
                    df_colocaciones_info_completa = map_promoter_names_to_codes(
                        df_col_detail_return.copy(), # Use .copy()
                        "Nombre promotor",
                        df_control
                    )
                else:
                    st.warning("La columna 'Nombre promotor' no se encontró en los datos de colocaciones detallados. No se pudo realizar el mapeo a códigos 'N' para df_colocaciones_info_completa.")
                    df_colocaciones_info_completa = df_col_detail_return.copy() # Use copy
                    if "N" not in df_colocaciones_info_completa.columns:
                        df_colocaciones_info_completa["N"] = pd.NA
            else:
                # Si df_col_detail_return está vacío o es None, crear un df_colocaciones_info_completa vacío
                # con las columnas esperadas incluyendo 'N'
                expected_cols = df_col_detail_return.columns.tolist() if df_col_detail_return is not None else \
                                ["Nombre promotor", "Fecha desembolso", "Monto desembolsado", "Nombre del cliente", "Contrato", "Cuota total", "Fecha primer pago"] # Fallback si None
                if "N" not in expected_cols:
                    expected_cols.append("N")
                df_colocaciones_info_completa = pd.DataFrame(columns=expected_cols)

            df_col_merge = merge_colocaciones(df_col_agg, df_control) # df_col_agg no se mapea, merge_colocaciones handles it.

            # df_control ya tiene Nombre_upper y Nombre_norm gracias a load_data_control
            df_desc_agg = load_data_descuentos(por_capturar_file, df_control) 
             
            df_pagos_raw = load_data_pagos(pagos_file)
            # Mapeo de nombres para df_pagos_raw
            if df_pagos_raw is not None and not df_pagos_raw.empty and "PROMOTOR" in df_pagos_raw.columns:
                df_pagos_raw = map_promoter_names_to_codes(df_pagos_raw.copy(), "PROMOTOR", df_control) # Use .copy()
            elif df_pagos_raw is not None and "N" not in df_pagos_raw.columns: # If map_promoter_names_to_codes was not run
                 df_pagos_raw["N"] = pd.NA
            
            # Agrupamos df_pagos por el "N" ya mapeado
            if df_pagos_raw is not None and not df_pagos_raw.empty and "N" in df_pagos_raw.columns:
                df_pagos = (
                    df_pagos_raw
                    .dropna(subset=["N"]) 
                    .groupby("N", as_index=False)["SALDO"]
                    .sum()
                )
            else: # df_pagos_raw es None, vacío, o no tiene "N"
                df_pagos = pd.DataFrame(columns=["N", "SALDO"])

            df_promoters_summary = build_promoters_summary(df_control, df_metas_summary, df_cobranza)
        except Exception as e:
            st.error(f"Error al cargar y procesar los datos: {e}")
            return

        tabs = st.tabs([
            "Datos Globales",
            "Resumen de Promotores",
            "Ranking a la Fecha",
            "Análisis de Cambio de Patrón",
            "Incumplimiento Semanal",
            "Detalles del Promotor",
            "Créditos a Detalle",
            "Totales y Última"
        ])

        # -----------------------------------------------------------
        # 0. Pestaña: Datos Globales
        # -----------------------------------------------------------
        # ... Código original de la pestaña "Datos Globales" ...
        # (Sin cambios, lo omitimos por brevedad)
        # 0. Pestaña: Datos Globales (MODIFICADA)
        ######################################################################
        with tabs[0]:
            st.header("Datos Globales de la Empresa")
            
            # A) Verificar si hay datos mínimos
            if df_metas_summary.empty or df_cobranza.empty:
                st.write("No hay datos suficientes para mostrar información global.")
            else:
                # --------------------------------------------------------------------
                # 1) Totales Históricos de Metas y Cobranza (y eficiencia)
                # --------------------------------------------------------------------
                # 1) Totales Históricos de Metas, Cobranza, Eficiencia y Cartera
                total_meta_hist    = df_metas_summary["Meta"].sum()
                total_cob_hist     = df_cobranza["Depósito"].sum()
                eficiencia_hist    = round((total_cob_hist / total_meta_hist) * 100, 2) if total_meta_hist>0 else 0
                total_cartera_hist = df_pagos_raw["SALDO"].sum()    # <-- calculamos la cartera total

                colH_m1, colH_m2, colH_m3, colH_m4 = st.columns(4)
                colH_m1.metric("Total Metas (Histórico)",      format_money(total_meta_hist))
                colH_m2.metric("Total Cobranza (Histórico)",   format_money(total_cob_hist))
                colH_m3.metric("Eficiencia (Histórico)",       f"{eficiencia_hist}%")
                colH_m4.metric("Valor Total de Cartera",       format_money(total_cartera_hist))  # <--- nuevo


                # --------------------------------------------------------------------
                # 2) Totales Históricos de Venta, Flujo, Desc. Renov. y Flujo Final
                # --------------------------------------------------------------------
                hist_venta = 0
                hist_desc = 0
                if not df_col_agg.empty:
                    hist_venta = df_col_agg["Venta"].sum()
                if not df_desc_agg.empty:
                    hist_desc = df_desc_agg["Descuento_Renovacion"].sum()

                hist_flujo = hist_venta * 0.9
                hist_flujo_final = hist_flujo - hist_desc

                st.markdown("#### Totales Históricos de Venta y Flujo")
                colH1, colH2, colH3, colH4 = st.columns(4)
                colH1.metric("Venta (Hist)", format_money(hist_venta))
                colH2.metric("Flujo (Hist)", format_money(hist_flujo))
                colH3.metric("Desc. Renov. (Hist)", format_money(hist_desc))
                colH4.metric("Flujo Final (Hist)", format_money(hist_flujo_final))

                # --------------------------------------------------------------------
                # 3) Gráfica de 3 Barras: 
                #    - Total Créditos Colocados (Hist)
                #    - Créditos Nuevos
                #    - Créditos Renovados
                # --------------------------------------------------------------------
                total_colocados_hist = 0
                if not df_col_agg.empty:
                    total_colocados_hist = df_col_agg["Creditos_Colocados"].sum()

                # Usamos df_desc_agg para estimar cuántos créditos se renovaron (contando filas)
                # ya que antes, para cada semana, usábamos len(...) como aproximación de créditos renovados.
                total_renovados_hist = 0
                if not df_desc_agg.empty:
                    total_renovados_hist = len(df_desc_agg)  # Conteo de filas => # de créditos renovados aprox.

                total_nuevos_hist = total_colocados_hist - total_renovados_hist
                if total_nuevos_hist < 0:
                    # Por si acaso, en caso de inconsistencia de datos
                    total_nuevos_hist = 0

                df_credits_hist = pd.DataFrame({
                    "Tipo": ["Total Colocados", "Nuevos", "Renovados"],
                    "Cantidad": [total_colocados_hist, total_nuevos_hist, total_renovados_hist]
                })

                st.markdown("#### Total de Créditos Colocados (Hist), Nuevos y Renovados")
                chart_credits_hist = alt.Chart(df_credits_hist).mark_bar().encode(
                    x=alt.X("Tipo:N", sort=["Total Colocados", "Nuevos", "Renovados"]),
                    y=alt.Y("Cantidad:Q"),
                    tooltip=["Tipo:N", "Cantidad:Q"]
                ).properties(width=450, height=400)
                st.altair_chart(chart_credits_hist, use_container_width=True)

                # --------------------------------------------------------------------
                # 4) COMPARACIÓN ENTRE DOS SEMANAS (sección anterior, intacta)
                # --------------------------------------------------------------------
                st.markdown("### Comparación entre dos Semanas")
                weeks_meta = pd.Index(df_metas_summary["Semana"].unique())
                weeks_cob = pd.Index(df_cobranza["Semana"].unique())
                all_weeks = weeks_meta.union(weeks_cob)

                if len(all_weeks) == 0:
                    st.write("No se encontraron semanas disponibles.")
                else:
                    # Generar etiquetas
                    sorted_weeks = sorted(all_weeks, key=lambda p: p.start_time)

                    def format_week_label(w):
                        return (w.start_time + pd.Timedelta(days=2)).strftime("%-d %b %Y")

                    week_mapping = {format_week_label(w): w for w in sorted_weeks}
                    week_labels = list(week_mapping.keys())

                    st.markdown("#### Selecciona dos semanas para comparar")
                    selected_week_1_label = st.selectbox("Semana 1", week_labels, index=0)

                    # Si solo hay una semana, repetimos
                    if len(week_labels) > 1:
                        selected_week_2_label = st.selectbox("Semana 2", week_labels, index=1)
                    else:
                        selected_week_2_label = selected_week_1_label

                    week_1 = week_mapping[selected_week_1_label]
                    week_2 = week_mapping[selected_week_2_label]

                    # Totales metas/cobranza S1 y S2
                    total_meta_1 = df_metas_summary[df_metas_summary["Semana"] == week_1]["Meta"].sum()
                    total_cob_1 = df_cobranza[df_cobranza["Semana"] == week_1]["Depósito"].sum()

                    total_meta_2 = df_metas_summary[df_metas_summary["Semana"] == week_2]["Meta"].sum()
                    total_cob_2 = df_cobranza[df_cobranza["Semana"] == week_2]["Depósito"].sum()

                    cumplimiento_1 = round((total_cob_1 / total_meta_1 * 100), 2) if total_meta_1 > 0 else 0
                    cumplimiento_2 = round((total_cob_2 / total_meta_2 * 100), 2) if total_meta_2 > 0 else 0

                    # Métricas (Metas vs Cobranza vs %)
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Meta Semana 1", format_money(total_meta_1))
                    col2.metric("Cobranza Semana 1", format_money(total_cob_1))
                    col3.metric("% Cumplimiento S1", f"{cumplimiento_1}%")

                    col4, col5, col6 = st.columns(3)
                    col4.metric("Meta Semana 2", format_money(total_meta_2))
                    col5.metric("Cobranza Semana 2", format_money(total_cob_2))
                    col6.metric("% Cumplimiento S2", f"{cumplimiento_2}%")

                    # Gráfica comparativa Metas vs Cobranza S1 y S2
                    global_data = pd.DataFrame({
                        "Semana": [selected_week_1_label, selected_week_2_label],
                        "Total Metas": [total_meta_1, total_meta_2],
                        "Total Cobranza": [total_cob_1, total_cob_2]
                    })
                    data_melt = global_data.melt(
                        id_vars=["Semana"],
                        value_vars=["Total Metas", "Total Cobranza"],
                        var_name="Tipo",
                        value_name="Monto"
                    )
                    chart_totals = alt.Chart(data_melt).mark_bar().encode(
                        x=alt.X("Semana:N"),
                        xOffset="Tipo:N",
                        y=alt.Y("Monto:Q", axis=alt.Axis(format="$,.2f")),
                        color="Tipo:N",
                        tooltip=["Semana:N", "Tipo:N", "Monto:Q"]
                    ).properties(width=400, height=400)
                    st.altair_chart(chart_totals, use_container_width=True)

                    # Gráfica depósitos diarios
                    df_cob_2w = df_cobranza[df_cobranza["Semana"].isin([week_1, week_2])]
                    if not df_cob_2w.empty:
                        def map_label(semana):
                            if semana == week_1:
                                return selected_week_1_label
                            elif semana == week_2:
                                return selected_week_2_label
                            return "Otros"

                        df_cob_2w["SemanaLabel"] = df_cob_2w["Semana"].apply(map_label)
                        df_cob_2w["Día"] = df_cob_2w["Fecha Transacción"].dt.day_name().str[:3]
                        df_cob_2w_agg = df_cob_2w.groupby(["SemanaLabel", "Día"], as_index=False)["Depósito"].sum()
                        df_cob_2w_agg.rename(columns={"Depósito": "TotalDia"}, inplace=True)
                        day_order = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"]

                        st.markdown("#### Depósitos diarios en las Semanas Seleccionadas")
                        chart_scatter = alt.Chart(df_cob_2w_agg).mark_line(point=True).encode(
                            x=alt.X("Día:N", sort=day_order),
                            y=alt.Y("TotalDia:Q", axis=alt.Axis(format="$,.2f")),
                            color="SemanaLabel:N",
                            tooltip=["SemanaLabel:N", "Día:N", "TotalDia:Q"]
                        ).properties(width=700, height=400)
                        st.altair_chart(chart_scatter, use_container_width=True)

                    # Créditos colocados vs renovados en S1 y S2
                    week_1_credits_placed = 0
                    week_2_credits_placed = 0
                    week_1_credits_renewed = 0
                    week_2_credits_renewed = 0

                    if not df_col_agg.empty:
                        week_1_credits_placed = df_col_agg[df_col_agg["Semana"] == week_1]["Creditos_Colocados"].sum()
                        week_2_credits_placed = df_col_agg[df_col_agg["Semana"] == week_2]["Creditos_Colocados"].sum()

                    if not por_capturar_file or df_desc_agg.empty:
                        pass  # Asumimos 0 créditos renovados
                    else:
                        df_week_1 = df_desc_agg[df_desc_agg["Semana"] == week_1]
                        df_week_2 = df_desc_agg[df_desc_agg["Semana"] == week_2]
                        week_1_credits_renewed = len(df_week_1)
                        week_2_credits_renewed = len(df_week_2)

                    data_credits = pd.DataFrame({
                        "Semana": [selected_week_1_label, selected_week_2_label],
                        "Créditos Colocados": [week_1_credits_placed, week_2_credits_placed],
                        "Créditos Renovados": [week_1_credits_renewed, week_2_credits_renewed]
                    })
                    data_credits_melt = data_credits.melt(
                        id_vars="Semana",
                        var_name="Tipo",
                        value_name="Cantidad"
                    )
                    st.markdown("#### Créditos Colocados y Créditos Renovados (Ambas Semanas)")
                    chart_credits = alt.Chart(data_credits_melt).mark_bar().encode(
                        x=alt.X("Semana:N"),
                        xOffset="Tipo:N",
                        y=alt.Y("Cantidad:Q"),
                        color="Tipo:N",
                        tooltip=["Semana:N", "Tipo:N", "Cantidad:Q"]
                    ).properties(width=400, height=400)
                    st.altair_chart(chart_credits, use_container_width=True)

                    # Totales de Venta y Flujo (por Semana)
                    week_1_venta = 0
                    week_2_venta = 0
                    week_1_desc = 0
                    week_2_desc = 0

                    if not df_col_agg.empty:
                        week_1_venta = df_col_agg.loc[df_col_agg["Semana"] == week_1, "Venta"].sum()
                        week_2_venta = df_col_agg.loc[df_col_agg["Semana"] == week_2, "Venta"].sum()

                    if not df_desc_agg.empty:
                        week_1_desc = df_desc_agg.loc[df_desc_agg["Semana"] == week_1, "Descuento_Renovacion"].sum()
                        week_2_desc = df_desc_agg.loc[df_desc_agg["Semana"] == week_2, "Descuento_Renovacion"].sum()

                    week_1_flujo = week_1_venta * 0.9
                    week_2_flujo = week_2_venta * 0.9
                    week_1_flujo_final = week_1_flujo - week_1_desc
                    week_2_flujo_final = week_2_flujo - week_2_desc

                    st.markdown("#### Totales de Venta y Flujo (por Semana)")
                    colA1, colA2, colA3, colA4 = st.columns(4)
                    colA1.metric("Venta (S1)", format_money(week_1_venta))
                    colA2.metric("Flujo (S1)", format_money(week_1_flujo))
                    colA3.metric("Desc. Renov. (S1)", format_money(week_1_desc))
                    colA4.metric("Flujo Final (S1)", format_money(week_1_flujo_final))

                    colB1, colB2, colB3, colB4 = st.columns(4)
                    colB1.metric("Venta (S2)", format_money(week_2_venta))
                    colB2.metric("Flujo (S2)", format_money(week_2_flujo))
                    colB3.metric("Desc. Renov. (S2)", format_money(week_2_desc))
                    colB4.metric("Flujo Final (S2)", format_money(week_2_flujo_final))



        # -----------------------------------------------------------
        # 1. Pestaña: Resumen de Promotores
        # -----------------------------------------------------------
        with tabs[1]:
            st.header("Resumen de Promotores")
            if df_promoters_summary.empty:
                st.write("No hay promotores para mostrar.")
            else:
                df_display = df_promoters_summary.copy()
                df_display = df_display[~((df_display["Total Metas"]==0) & (df_display["Total Cobranza"]==0))]

                df_display["Total Metas"] = df_display["Total Metas"].apply(format_money)
                df_display["Total Cobranza"] = df_display["Total Cobranza"].apply(format_money)
                df_display["Diferencia"] = df_display["Diferencia"].apply(format_money)
                df_display["Antigüedad (meses)"] = df_display["Antigüedad (meses)"].round(2)

                st.dataframe(
                    df_display[["N","Nombre","Antigüedad (meses)","Total Metas","Total Cobranza","Diferencia"]],
                    use_container_width=True
                )

        # -----------------------------------------------------------
        # 2. Pestaña: Ranking a la Fecha
        # -----------------------------------------------------------
        # ... Código original de la pestaña "Ranking a la Fecha" ...
        # 2. Pestaña: Ranking a la Fecha (Acumulado)
        # -----------------------------------------------------------
        # ------------------- PESTAÑA 2 : RANKING A LA FECHA ----------------------
        # ------------------- PESTAÑA 2 : RANKING A LA FECHA ----------------------
        # ------------------- PESTAÑA 2 : RANKING A LA FECHA ----------------------
        # ---------------- PESTAÑA 2 : RANKING A LA FECHA ------------------------
        with tabs[2]:
            st.header("Ranking a la Fecha (sábado → viernes)")

            # ------------------------------------------------------------------
            # 1) ARMAMOS EL DATASET BASE A PARTIR DE LAS FUENTES ORIGINALES
            #    - df_metas_summary   →  Meta semanal por promotor
            #    - df_cobranza        →  Cobranza diaria
            # ------------------------------------------------------------------
            # a) Metas semanales ya vienen agregadas (Promotor, Semana, Meta)
            metas = df_metas_summary[["Promotor", "Semana", "Meta"]].copy()

            # b) Cobranza semanal: sumamos depósitos por promotor / semana
            cobranza = (
                df_cobranza
                .groupby(["N", "Semana"], as_index=False)["Depósito"]
                .sum()
                .rename(columns={"N": "Promotor", "Depósito": "Cobranza"})
            )

            # c) Merge → una fila por Promotor-Semana
            df_base = (
                pd.merge(metas, cobranza, on=["Promotor", "Semana"], how="outer")
                .fillna(0)        # si faltó meta o cobro esa semana
            )

            # ------------------------------------------------------------------
            # 2) SELECTOR DE SEMANA  (Period[W-FRI] → sábado-viernes)
            # ------------------------------------------------------------------
            semanas_disp = sorted(df_base["Semana"].unique(), key=lambda p: p.start_time)
            selected_week = st.selectbox(
                "Semana a cierre:",
                semanas_disp,
                format_func=lambda p: f"{p.start_time.strftime('%d %b')} → {p.end_time.strftime('%d %b')}"
            )

            # ------------------------------------------------------------------
            # 3) ACUMULADOS HASTA LA SEMANA SELECCIONADA
            # ------------------------------------------------------------------
            df_cum = (
                df_base[df_base["Semana"] <= selected_week]
                .groupby("Promotor", as_index=False)
                .agg({"Meta": "sum", "Cobranza": "sum"})
            )

            # % de cumplimiento  |  evita división 0
            df_cum["Cumplimiento %"] = (
                df_cum.apply(
                    lambda r: r["Cobranza"] / r["Meta"] * 100 if r["Meta"] else 0,
                    axis=1
                )
            )

            # ------------------------------------------------------------------
            # 4) FILTRO OPCIONAL POR PROMOTORES (CÓDIGOS P1, P2, …)
            # ------------------------------------------------------------------
            proms_select = st.multiselect(
                "Mostrar solo promotores (códigos):",
                sorted(df_cum["Promotor"].unique(), key=lambda s: int(s.lstrip("P")))
            )
            if proms_select:
                df_cum = df_cum[df_cum["Promotor"].isin(proms_select)]

            # ------------------------------------------------------------------
            # 5) AÑADIMOS NOMBRE PARA VISUALIZAR  (NO se usa para cálculos)
            # ------------------------------------------------------------------
            code_to_name = dict(zip(df_control["N"], df_control["Nombre"]))
            df_cum["Nombre"] = df_cum["Promotor"].map(code_to_name)

            # ------------------------------------------------------------------
            # 6) ORDENAMOS POR % CUMPLIMIENTO  Y  POR CÓDIGO NATURAL
            # ------------------------------------------------------------------
            df_cum.sort_values(
                ["Cumplimiento %", "Promotor"],
                ascending=[False, True],
                key=lambda col: (
                    col if col.name != "Promotor" else col.str.lstrip("P").astype(int)
                ),
                inplace=True
            )

            # ------------------------------------------------------------------
            # 7) FORMATO MONETARIO Y % CON 1 DECIMAL
            # ------------------------------------------------------------------
            df_cum["Meta"]      = df_cum["Meta"].apply(format_money)
            df_cum["Cobranza"]  = df_cum["Cobranza"].apply(format_money)
            df_cum["Cumplimiento %"] = df_cum["Cumplimiento %"].apply(lambda x: f"{x:,.1f}%")

            # ------------------------------------------------------------------
            # 8) MOSTRAMOS TABLA
            # ------------------------------------------------------------------
            st.dataframe(
                df_cum[["Promotor", "Nombre", "Meta", "Cobranza", "Cumplimiento %"]],
                use_container_width=True,
                height=min(700, 35 + 25 * len(df_cum))
            )






        # -----------------------------------------------------------
        # 3. Pestaña: Análisis de Cambio de Patrón
        # -----------------------------------------------------------
        # ... Código original de "Análisis de Cambio de Patrón" ...
        # Pestaña: Análisis de Cambio de Patrón de Pago (con exclusión <7% y colores en score)
        #############################################
        with tabs[3]:
            st.header("Análisis de Cambio de Patrón de Pago - Ajustes Especiales")
            st.markdown("""
            - Se excluyen del ranking (lista principal) los promotores con <7% de cumplimiento 
              en las últimas 4 semanas, y se muestran en un listado aparte ("promotores en default").
            - El Score de Riesgo se colorea según tres rangos:
                - <11 => verde
                - <35 => naranja
                - >=35 => rojo
            """)

            # --------------------------------------------------------------
            # 1) Cálculo de variación en el día promedio de pago
            # --------------------------------------------------------------
            code_to_name = dict(zip(df_control["N"], df_control["Nombre"]))
            all_prom_changes = []

            for code, name in code_to_name.items():
                df_prom = df_cobranza[df_cobranza["Nombre Promotor"] == name.upper()].copy()
                if df_prom.empty:
                    continue

                df_prom["weighted_product"] = df_prom["Día_num"] * df_prom["Depósito"]
                agg_df = df_prom.groupby("Semana").agg(
                    sum_weighted_product=("weighted_product", "sum"),
                    sum_deposito=("Depósito", "sum")
                ).reset_index()
                agg_df["Weighted_Day"] = agg_df["sum_weighted_product"] / agg_df["sum_deposito"]

                df_weekly = agg_df[["Semana", "Weighted_Day"]].sort_values("Semana")
                n = len(df_weekly)
                if n < 2:
                    continue

                # Si hay 6 o más semanas, tomamos las últimas 6 y comparamos las mitades
                if n >= 6:
                    last_data = df_weekly.tail(6)
                    first_avg = last_data.head(3)["Weighted_Day"].mean()
                    last_avg = last_data.tail(3)["Weighted_Day"].mean()
                else:
                    half = n // 2
                    first_avg = df_weekly.head(half)["Weighted_Day"].mean()
                    last_avg = df_weekly.tail(half)["Weighted_Day"].mean()

                diff = (last_avg - first_avg) if pd.notna(first_avg) and pd.notna(last_avg) else np.nan

                all_prom_changes.append({
                    "N": code,
                    "Nombre": name,
                    "Inicio Promedio": round(first_avg, 2) if pd.notna(first_avg) else np.nan,
                    "Final Promedio": round(last_avg, 2) if pd.notna(last_avg) else np.nan,
                    "Diferencia": round(diff, 2) if pd.notna(diff) else np.nan
                })

            df_change = pd.DataFrame(all_prom_changes)

            if df_change.empty:
                st.write("No hay datos suficientes para mostrar cambios de patrón de pago.")
                st.stop()

            # (Opcional) Mostramos la tabla de cambio de día de pago, con estilo en la columna 'Diferencia'
            styled_change = df_change.style.applymap(style_difference, subset=["Diferencia"])
            st.markdown("### Variación en el Día Promedio de Pago")
            st.dataframe(styled_change, use_container_width=True)

            # --------------------------------------------------------------
            # 2) Calcular % de cumplimiento en últimas 4 semanas cerradas
            # --------------------------------------------------------------
            from datetime import datetime
            today = datetime.today()

            df_cobranza_closed = df_cobranza[df_cobranza["Semana"].apply(lambda w: w.end_time < today)]
            df_metas_closed = df_metas_summary[df_metas_summary["Semana"].apply(lambda w: w.end_time < today)]

            def get_recent_weeks_compliance(promotor_code, df_metas, df_cob, top_weeks=4):
                if promotor_code not in code_to_name:
                    return 0.0
                name_upper = code_to_name[promotor_code].upper()

                df_meta_p = df_metas[df_metas["Promotor"] == promotor_code]
                df_cob_p = df_cob[df_cob["Nombre Promotor"] == name_upper]

                metas_sem = df_meta_p.groupby("Semana")["Meta"].sum()
                cob_sem = df_cob_p.groupby("Semana")["Depósito"].sum()

                df_weeks = pd.DataFrame({"Meta": metas_sem, "Cobranza": cob_sem}).fillna(0)
                df_weeks = df_weeks.sort_index(ascending=False).head(top_weeks)

                df_weeks["Cumplimiento"] = df_weeks.apply(
                    lambda row: (row["Cobranza"]/row["Meta"]) * 100 if row["Meta"] > 0 else 0,
                    axis=1
                ) if not df_weeks.empty else pd.Series()
                return round(df_weeks["Cumplimiento"].mean(), 2) if not df_weeks.empty else 0

            # Construimos df_risk uniendo la info
            risk_rows = []
            for _, row in df_change.iterrows():
                code = row["N"]
                avg_4w = get_recent_weeks_compliance(code, df_metas_closed, df_cobranza_closed, 4)
                risk_rows.append({
                    "N": code,
                    "Nombre": row["Nombre"],
                    "Inicio Promedio (día pago)": row["Inicio Promedio"],
                    "Final Promedio (día pago)": row["Final Promedio"],
                    "Diferencia": row["Diferencia"],
                    "Cumpl. 4 Semanas (%)": avg_4w
                })

            df_risk = pd.DataFrame(risk_rows)

            # --------------------------------------------------------------
            # 3) Score de Riesgo (puedes ajustar la fórmula)
            # --------------------------------------------------------------
            def compliance_component_mod(cumpl):
                if cumpl >= 95:
                    return 0
                elif cumpl >= 80:
                    return (95 - cumpl) / (95 - 80)
                else:
                    return 1

            def delay_component_mod(diff):
                if diff <= 0:
                    return 0
                delay_pos = min(diff, 3)
                return delay_pos / 3.0

            weight_cumpl = 0.7
            weight_delay = 0.3

            df_risk["comp_component"] = df_risk["Cumpl. 4 Semanas (%)"].apply(compliance_component_mod)
            df_risk["delay_component"] = df_risk["Diferencia"].apply(delay_component_mod)
            df_risk["score_0to1"] = (weight_cumpl * df_risk["comp_component"] +
                                     weight_delay * df_risk["delay_component"])
            df_risk["score_riesgo"] = (df_risk["score_0to1"] * 100).round(2)

            # --------------------------------------------------------------
            # 4) Separar default (<7% de cumplimiento) de la lista principal
            # --------------------------------------------------------------
            df_default = df_risk[df_risk["Cumpl. 4 Semanas (%)"] < 7].copy()
            df_principal = df_risk[df_risk["Cumpl. 4 Semanas (%)"] >= 7].copy()

            # --------------------------------------------------------------
            # 5) Colorear el score_riesgo: (<11 verde, <35 naranja, >=35 rojo)
            # --------------------------------------------------------------
            def style_risk_score(val):
                if val < 11:
                    return "background-color: green; color: white;"
                elif val < 35:
                    return "background-color: orange; color: black;"
                else:
                    return "background-color: red; color: white;"

            # --------------------------------------------------------------
            # 6) Mostrar Ranking Principal
            # --------------------------------------------------------------
            st.markdown("### Ranking Principal (con 7% o más de Cumplimiento en 4 Semanas)")

            df_principal.sort_values("score_riesgo", ascending=False, inplace=True)

            # Seleccionamos columnas en el DataFrame, luego aplicamos estilo
            df_principal_subset = df_principal[
                ["N", "Nombre",
                 "Inicio Promedio (día pago)",
                 "Final Promedio (día pago)",
                 "Diferencia",
                 "Cumpl. 4 Semanas (%)",
                 "score_riesgo"]
            ].copy()

            df_principal_styled = df_principal_subset.style.applymap(
                style_risk_score,
                subset=["score_riesgo"]
            )

            st.dataframe(df_principal_styled, use_container_width=True)

            # --------------------------------------------------------------
            # 7) Listado de promotores en default (<7%)
            # --------------------------------------------------------------
            if not df_default.empty:
                st.markdown("### Promotores en Default (Cumplimiento <7%)")
                st.write("Estos promotores se excluyen del ranking principal.")

                df_default.sort_values("score_riesgo", ascending=False, inplace=True)

                df_default_subset = df_default[
                    ["N", "Nombre",
                     "Inicio Promedio (día pago)",
                     "Final Promedio (día pago)",
                     "Diferencia",
                     "Cumpl. 4 Semanas (%)",
                     "score_riesgo"]
                ].copy()

                df_default_styled = df_default_subset.style.applymap(
                    style_risk_score,
                    subset=["score_riesgo"]
                )

                st.dataframe(df_default_styled, use_container_width=True)


        # -----------------------------------------------------------
        # ------------------- PESTAÑA 4 : INCUMPLIMIENTO SEMANAL -------------------
        # ------------------- PESTAÑA 4 : INCUMPLIMIENTO SEMANAL -------------------
        # ------------------- PESTAÑA 4 : INCUMPLIMIENTO SEMANAL -------------------
        with tabs[4]:
            st.header("Incumplimiento Semanal")

            # 1) Selector de semana
            semanas_disp = sorted(df_metas_summary["Semana"].unique(),
                                  key=lambda p: p.start_time)
            selected_week = st.selectbox(
                "Selecciona la semana a evaluar:",
                semanas_disp,
                format_func=lambda p: f"{p.start_time.strftime('%d %b')} → {p.end_time.strftime('%d %b')}"
            )

            # ---------- DATASETS --------------------------------------------------
            # a) Metas y cobranza de la semana
            df_meta_w = df_metas_summary[df_metas_summary["Semana"] == selected_week][
                ["Promotor", "Meta"]
            ]
            df_cob_w = (
                df_cobranza[df_cobranza["Semana"] == selected_week]
                .groupby("N", as_index=False)["Depósito"]
                .sum()
                .rename(columns={"N": "Promotor", "Depósito": "Cobranza"})
            )

            # b) Metas y cobranza ACUMULADAS hasta la semana seleccionada
            df_meta_cum = (
                df_metas_summary[df_metas_summary["Semana"] <= selected_week]
                .groupby("Promotor", as_index=False)["Meta"]
                .sum()
                .rename(columns={"Meta": "MetaAcum"})
            )
            df_cob_cum = (
                df_cobranza[df_cobranza["Semana"] <= selected_week]
                .groupby("N", as_index=False)["Depósito"]
                .sum()
                .rename(columns={"N": "Promotor", "Depósito": "CobranzaAcum"})
            )

            # c) Fusionamos todo
            df_semana = (
                pd.merge(df_meta_w, df_cob_w, on="Promotor", how="outer")
                .merge(df_meta_cum, on="Promotor", how="outer")
                .merge(df_cob_cum, on="Promotor", how="outer")
                .fillna(0)
            )

            # d) Diferencias
            df_semana["DifSemana"] = df_semana["Cobranza"]     - df_semana["Meta"]
            df_semana["DifAcum"]   = df_semana["CobranzaAcum"] - df_semana["MetaAcum"]

            # e) Nombre legible
            code_to_name = dict(zip(df_control["N"], df_control["Nombre"]))
            df_semana["Nombre"] = df_semana["Promotor"].map(code_to_name)

            # ---------- FILTROS SEGÚN REGLAS -------------------------------------
            # Incumplidos: meta semanal > 0  Y  cob_acum < meta_acum
            df_incumplidos = df_semana[
                (df_semana["Meta"] > 0) &                       # meta semanal positiva
                (df_semana["Cobranza"]   < df_semana["Meta"]) & # NO cumplió la meta de la semana
                (df_semana["CobranzaAcum"] < df_semana["MetaAcum"])  # sigue atrasado acumulado
            ].copy()


            # Meta 0 con depósito: meta = 0  Y  cob_semana > 0
            df_meta0_dep = df_semana[
                (df_semana["Meta"] == 0) &
                (df_semana["Cobranza"] > 0)
            ].copy()

            # Orden P1, P2…
            sort_key = lambda s: s.str.lstrip("P").astype(int)
            df_incumplidos.sort_values("Promotor", key=sort_key, inplace=True)
            df_meta0_dep.sort_values("Promotor", key=sort_key, inplace=True)

            # ---------- MÉTRICAS RESUMEN (ANTES DE LA TABLA) ----------------------
            # --- NUEVAS MÉTRICAS -----------------------------------------------------
            total_meta  = df_meta_w["Meta"].sum()
            total_cob   = df_cob_w["Cobranza"].sum()
            porcentaje  = (total_cob / total_meta * 100) if total_meta else 0
            
            col1, col2, col3, col4 = st.columns(4)

            col1.metric("Cobranza realizada vs Meta", f"{porcentaje:.1f}%")
            col2.metric("Total meta semana",          format_money(total_meta))
            col3.metric("Total cobranza semana",      format_money(total_cob))
            col4.metric("Incumplidos netos",          len(df_incumplidos))


            st.subheader(
                f"Semana: {selected_week.start_time.strftime('%d %b %Y')} → "
                f"{selected_week.end_time.strftime('%d %b %Y')}"
            )

            # ---------- FORMATEO --------------------------------------------------
            money_cols = ["Meta", "Cobranza", "MetaAcum", "CobranzaAcum",
                          "DifSemana", "DifAcum"]
            for col in money_cols:
                df_incumplidos[col] = df_incumplidos[col].apply(format_money)
                df_meta0_dep[col]   = df_meta0_dep[col].apply(format_money)

            # ---------- TABLA 1: INCUMPLIDOS --------------------------------------
            st.markdown("### Promotores que **NO** alcanzan la meta (considerando adelantos)")
            if df_incumplidos.empty:
                st.success("🎉 Ningún promotor incumple su meta esta semana.")
            else:
                st.dataframe(
                    df_incumplidos[[
                        "Promotor", "Nombre",
                        "Meta", "Cobranza", "DifSemana",
                        "MetaAcum", "CobranzaAcum", "DifAcum"
                    ]],
                    use_container_width=True,
                    height=min(400, 35 + 25 * len(df_incumplidos))
                )

            # ---------- TABLA 2: META 0 CON DEPÓSITO ------------------------------
            st.markdown("### Promotores con **meta 0** pero que depositaron")
            if df_meta0_dep.empty:
                st.info("No hay depósitos registrados en promotores con meta 0.")
            else:
                st.dataframe(
                    df_meta0_dep[[
                        "Promotor", "Nombre",
                        "Meta", "Cobranza", "DifSemana",
                        "MetaAcum", "CobranzaAcum", "DifAcum"
                    ]],
                    use_container_width=True,
                    height=min(400, 35 + 25 * len(df_meta0_dep))
                )



        # -----------------------------------------------------------
        # 5. Pestaña: Detalles del Promotor
        # -----------------------------------------------------------
        with tabs[5]:
            st.header("Detalles del Promotor")
            if df_promoters_summary.empty:
                st.write("No hay promotores para mostrar.")
            else:
                # -------------------------------------------------------------
                # 1) SELECCIÓN DE PROMOTOR
                # -------------------------------------------------------------
                search_term = st.text_input("Buscar promotor (por nombre parcial)")
                if search_term:
                    filtered_promoters = df_control[df_control["Nombre"].str.contains(search_term, case=False, na=False)]
                else:
                    filtered_promoters = df_control

                if filtered_promoters.empty:
                    st.error("No se encontraron promotores con ese criterio.")
                else:
                    selected_promoter_name = st.selectbox(
                        "Selecciona el promotor",
                        filtered_promoters["Nombre"].tolist()
                    )
                    df_match = df_control[df_control["Nombre"] == selected_promoter_name]

                    if df_match.empty:
                        st.error("Promotor no encontrado en df_control.")
                    else:
                        promotor_sel = df_match["N"].iloc[0]  # <-- Código (P1, P2...)
                        nombre_promotor = df_match["Nombre"].iloc[0]
                        antiguedad_val = df_match["Antigüedad (meses)"].iloc[0] if "Antigüedad (meses)" in df_match else None

                        # Muestra Estado/Municipio (si existen datos)
                        df_cob_prom = df_cobranza[df_cobranza["N"] == promotor_sel].copy()

                        estados     = df_cob_prom["Estado"].dropna().unique()
                        municipios  = df_cob_prom["Municipio"].dropna().unique()

                        estado_str    = ", ".join(estados)    if len(estados)    > 0 else "No registrado"
                        municipio_str = ", ".join(municipios) if len(municipios) > 0 else "No registrado"

                        st.markdown(f"**Número Promotor (Código):** {promotor_sel}")
                        st.markdown(f"**Nombre Promotor:** {nombre_promotor}")
                        st.markdown(f"**Antigüedad (meses):** {antiguedad_val}")
                        st.markdown(f"**Estado(s):** {estado_str}")
                        st.markdown(f"**Municipio(s):** {municipio_str}")
                        from datetime import datetime     # ya está importado antes; si no, añade una sola vez


                        # --- Metas históricas del promotor (necesarias para el resumen semanal) ---
                        df_meta_prom = df_metas_summary[df_metas_summary["Promotor"] == promotor_sel]


                        # -------------------------------------------------------------
                        # META VS. COBRANZA TOTALES
                        # -------------------------------------------------------------
                        # -------------------------------------------------------------
                        # KPI HISTÓRICOS  (tarjetas grandes lado a lado)
                        # -------------------------------------------------------------
                        # ---------- KPI RESUMEN DEL PROMOTOR  (tarjetas grandes) -----------------
                        # 1) Recalcula totales históricos (en caso de que aún no existan)
                        meta_hist = df_metas_summary.loc[
                            df_metas_summary["Promotor"] == promotor_sel, "Meta"
                        ].sum()

                        cob_hist = df_cobranza.loc[
                            df_cobranza["N"] == promotor_sel, "Depósito"
                        ].sum()

                        dif_hist = cob_hist - meta_hist
                        # --- Cálculo de KPIs del estado actual -----------------------------------
                        hoy = datetime.now().date()
                        df_pagos_prom_raw = df_pagos_raw[df_pagos_raw["N"] == promotor_sel].copy()

                        clientes_activos      = (df_pagos_prom_raw["VENCI"].dt.date >= hoy).sum()
                        clientes_vencidos     = ((df_pagos_prom_raw["VENCI"].dt.date < hoy) & (df_pagos_prom_raw["SV"] > 0)).sum()
                        saldo_vencido_total   = df_pagos_prom_raw["SV"].sum()
                        clientes_atrasados    = ((df_pagos_prom_raw["VENCI"].dt.date >= hoy) & (df_pagos_prom_raw["SV"] > df_pagos_prom_raw["PS"])).sum()
                        cartera_ind           = df_pagos_prom_raw["SALDO"].sum()

                        # 2) Primera fila: situación actual
                        row1c1, row1c2, row1c3, row1c4 = st.columns(4)
                        row1c1.metric("Nº de Clientes Activos",  f"{clientes_activos:,}")
                        row1c2.metric("Clientes Vencidos",       f"{clientes_vencidos:,}")
                        row1c3.metric("Saldo Vencido Total",     format_money(saldo_vencido_total))
                        row1c4.metric("Clientes Atrasados",      f"{clientes_atrasados:,}")

                        # 3) Segunda fila: cartera y totales históricos
                        row2c1, row2c2, row2c3, row2c4 = st.columns(4)
                        row2c1.metric("Valor Cartera Individual",  format_money(cartera_ind))
                        row2c2.metric("Meta Total (Histórico)",    format_money(meta_hist))
                        row2c3.metric("Cobranza Total (Histórico)",format_money(cob_hist))
                        row2c4.metric("Diferencia Histórica",      format_money(dif_hist))




                        # -------------------------------------------------------------
                        # 4) RESUMEN SEMANAL DE METAS VS. COBRANZA
                        # -------------------------------------------------------------
                        df_cob_summary = df_cob_prom.groupby("Semana")["Depósito"].sum().reset_index()
                        if not df_meta_prom.empty or not df_cob_summary.empty:
                            if not df_cob_summary.empty and not df_meta_prom.empty:
                                start_week = min(df_cob_summary["Semana"].min(), df_meta_prom["Semana"].min())
                                end_week = max(df_cob_summary["Semana"].max(), df_meta_prom["Semana"].max())
                            elif not df_cob_summary.empty:
                                start_week = df_cob_summary["Semana"].min()
                                end_week = df_cob_summary["Semana"].max()
                            else:
                                start_week = df_meta_prom["Semana"].min()
                                end_week = df_meta_prom["Semana"].max()

                            full_weeks = pd.period_range(
                                start=start_week.start_time,
                                end=end_week.end_time,
                                freq="W-FRI"
                            )
                            df_weeks = pd.DataFrame({"Semana": full_weeks})

                            df_merge = pd.merge(
                                df_weeks,
                                df_meta_prom[["Semana", "Meta"]],
                                on="Semana", how="left"
                            )
                            df_merge = pd.merge(
                                df_merge,
                                df_cob_summary[["Semana", "Depósito"]],
                                on="Semana", how="left"
                            )
                            df_merge.rename(columns={"Meta": "Cobranza Meta", "Depósito": "Cobranza Realizada"}, inplace=True)
                            df_merge[["Cobranza Meta", "Cobranza Realizada"]] = df_merge[["Cobranza Meta", "Cobranza Realizada"]].fillna(0)

                            df_merge["Cumplimiento (%)"] = df_merge.apply(
                                lambda row: round(row["Cobranza Realizada"] / row["Cobranza Meta"] * 100, 2)
                                if row["Cobranza Meta"] > 0 else 0,
                                axis=1
                            )

                            df_merge.sort_values(
                                by="Semana",
                                key=lambda col: col.apply(lambda p: p.start_time),
                                inplace=True
                            )

                            st.write("#### Resumen Semanal del Promotor (Meta vs. Cobranza)")
                            st.dataframe(
                                df_merge[["Semana", "Cobranza Meta", "Cobranza Realizada", "Cumplimiento (%)"]],
                                use_container_width=True
                            )

                            # Detalle diario (opcional)
                            if not df_cob_summary.empty:
                                st.markdown("##### Detalle Diario")
                                df_merge["Nº Semana"] = range(1, len(df_merge) + 1)
                                week_num_sel = st.number_input(
                                    "Ingresa Nº de Semana para ver detalle diario",
                                    min_value=1,
                                    max_value=len(df_merge),
                                    step=1,
                                    value=1
                                )
                                if week_num_sel <= len(df_merge):
                                    sel_week = df_merge.loc[df_merge["Nº Semana"] == week_num_sel, "Semana"].iloc[0]
                                    df_detail = df_cob_prom[df_cob_prom["Semana"] == sel_week].copy()
                                    if not df_detail.empty:
                                        df_detail["Día"] = df_detail["Fecha Transacción"].dt.day_name()
                                        daily = df_detail.groupby("Día")["Depósito"].sum().reset_index()
                                        daily["Depósito"] = daily["Depósito"].apply(format_money)
                                        st.write(f"#### Detalle Diario - Semana {sel_week}")
                                        st.dataframe(daily, use_container_width=True)
                                    else:
                                        st.write("No hay registros de cobranza para la semana seleccionada.")
                        else:
                            st.warning("Este promotor no tiene datos de metas ni cobranzas.")

                        # -----------------------------------------------------------------
                        # 5) INFORMACIÓN DE COLOCACIÓN DE CRÉDITOS (fusionada)
                        # -----------------------------------------------------------------
                        st.markdown("### Colocación de Créditos (Venta, Flujo y Descuentos)")
                        if df_col_merge.empty:
                            st.info("No se encontraron datos de colocaciones en general.")
                        else:
                            # Filtrar df_col_merge por promotor (código)
                            df_sel = df_col_merge[df_col_merge["N"] == promotor_sel].copy()
                            if df_sel.empty:
                                st.write("No hay registros de colocación para este promotor.")
                            else:
                                # <-- CAMBIO: merge por ["N","Semana"] en lugar de nombres
                                df_merged = pd.merge(
                                    df_sel,
                                    df_desc_agg,  # ya contiene ["N","Semana","Descuento_Renovacion"]
                                    left_on=["N","Semana"],
                                    right_on=["N","Semana"],
                                    how="left"
                                )
                                df_merged["Descuento_Renovacion"] = df_merged["Descuento_Renovacion"].fillna(0)

                                total_credits_placed = df_merged["Creditos_Colocados"].sum()

                                # Contar filas con descuento > 0 en df_desc_agg (mismo N)
                                df_desc_renov = df_desc_agg[
                                    (df_desc_agg["N"] == promotor_sel) &
                                    (df_desc_agg["Descuento_Renovacion"] > 0)
                                ]
                                total_credits_renewed = len(df_desc_renov)
                                total_credits_new = total_credits_placed - total_credits_renewed
                                if total_credits_new < 0:
                                    total_credits_new = 0

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

                                df_agr = df_merged.groupby("Semana", as_index=False).agg({
                                    "Creditos_Colocados": "sum",
                                    "Venta": "sum",
                                    "Descuento_Renovacion": "sum"
                                })
                                df_agr["Flujo"] = df_agr["Venta"] * 0.9
                                df_agr["Flujo Final"] = df_agr["Flujo"] - df_agr["Descuento_Renovacion"]

                                min_week = df_agr["Semana"].min()
                                max_week = df_agr["Semana"].max()
                                if pd.notna(min_week) and pd.notna(max_week):
                                    full_weeks = pd.period_range(
                                        start=min_week.start_time,
                                        end=max_week.end_time,
                                        freq="W-FRI"
                                    )
                                    df_weeks = pd.DataFrame({"Semana": full_weeks})
                                    df_full = pd.merge(df_weeks, df_agr, on="Semana", how="left").fillna(0)
                                    df_full = df_full.sort_values(
                                        by="Semana",
                                        key=lambda col: col.apply(lambda p: p.start_time)
                                    )
                                else:
                                    df_full = df_agr.copy()

                                df_full["Venta"] = df_full["Venta"].apply(format_money)
                                df_full["Flujo"] = df_full["Flujo"].apply(format_money)
                                df_full["Descuento_Renovacion"] = df_full["Descuento_Renovacion"].apply(format_money)
                                df_full["Flujo Final"] = df_full["Flujo Final"].apply(format_money)

                                # ---------- KPIs de Colocación de Créditos ------------------------------
                    
                                # (1) Totales
                                # ---------- KPIs de Colocación de Créditos ------------------------------
                                num_creditos = int(total_credits_placed)          # ya lo calculaste
                                tot_ventas   = total_venta
                                tot_flujo    = total_flujo
                                tot_desc     = total_desc


                                # (2) Promedios por crédito
                                prom_venta = tot_ventas / num_creditos if num_creditos else 0
                                prom_flujo = tot_flujo  / num_creditos if num_creditos else 0
                                prom_desc  = tot_desc  / num_creditos if num_creditos else 0

                                


                                st.markdown("#### Detalle Semanal de Colocación de Créditos")
                                st.dataframe(
                                    df_full[[
                                        "Semana",
                                        "Creditos_Colocados",
                                        "Venta",
                                        "Flujo",
                                        "Descuento_Renovacion",
                                        "Flujo Final"
                                    ]],
                                    use_container_width=True
                                )

        # -----------------------------------------------------------
        # ---------------- PESTAÑA 5 : CRÉDITOS A DETALLE ------------------------
        # -------------------- PESTAÑA 5 : CRÉDITOS A DETALLE ---------------------
        # -----------------------------------------------------------
        # 5) PESTAÑA: CRÉDITOS A DETALLE
        # -----------------------------------------------------------
        # PESTAÑA 6 : CRÉDITOS A DETALLE (Corregida)
        # -----------------------------------------------------------
        with tabs[6]:
            st.header("Créditos a Detalle")

            # Asumimos que df_control y df_cobranza están cargados y procesados como antes.
            # Y que df_colocaciones_info_completa está disponible y preparada.
            # df_colocaciones_info_completa debe tener:
            # - Columna 'N' con el código del promotor.
            # - Columnas originales del Excel: "Nombre del cliente", "Contrato", "Cuota total", "Fecha primer pago".
            # - Tipos de datos ya corregidos (fechas como datetime, números como float/int).

            if 'df_colocaciones_info_completa' not in locals() and 'df_colocaciones_info_completa' not in globals():
                st.error("Error crítico: El DataFrame 'df_colocaciones_info_completa' no está disponible. Esta pestaña no puede funcionar.")
                st.stop()
            
            if df_control.empty:
                st.warning("No hay datos de control de promotores cargados.")
                st.stop()

            # 1) Selección de promotor (código P1, P2…)
            codigos = sorted(df_control["N"].unique(), key=lambda x: int(x.lstrip("P")))
            promotor_sel = st.selectbox("Selecciona promotor (código):", codigos, key="creditos_detalle_promotor_sel")
            
            if not promotor_sel:
                st.info("Por favor, selecciona un promotor.")
                st.stop()

            nombre_promotor_info = df_control.loc[df_control["N"] == promotor_sel, "Nombre"]
            if nombre_promotor_info.empty:
                st.error(f"No se encontró el nombre para el promotor con código {promotor_sel}.")
                nombre_promotor_display = "Desconocido"
            else:
                nombre_promotor_display = nombre_promotor_info.iat[0]
            
            st.markdown(f"**Promotor:** {promotor_sel} — {nombre_promotor_display}")

            # 2) Filtramos datos de Colocación (usando df_colocaciones_info_completa) y Cobranza
            if df_colocaciones_info_completa.empty or "N" not in df_colocaciones_info_completa.columns:
                st.warning("No hay datos de colocaciones detallados o falta la columna 'N' para filtrar.")
                df_col_prom_original = pd.DataFrame()
            else:
                df_col_prom_original = df_colocaciones_info_completa[df_colocaciones_info_completa["N"] == promotor_sel].copy()

            if df_cobranza.empty or "N" not in df_cobranza.columns:
                st.warning("No hay datos de cobranza o falta la columna 'N' para filtrar.")
                df_cob_prom = pd.DataFrame()
            else:
                df_cob_prom = df_cobranza[df_cobranza["N"] == promotor_sel].copy()


            # Normalizar y renombrar columnas de Cobranza (como en tu código original)
            if not df_cob_prom.empty:
                df_cob_prom.columns = (
                    df_cob_prom.columns
                    .str.strip()
                    .str.lower()
                    .str.normalize("NFKD").str.encode("ascii", "ignore").str.decode("utf-8")
                )
                # Renombres selectivos para evitar errores si una columna no existe
                cob_rename_map = {
                    "contrato": "Contrato", # Asegúrate que 'contrato' es el nombre normalizado
                    "deposito": "Deposito", # Asegúrate que 'deposito' es el nombre normalizado
                    "fecha transaccion": "FechaTrans" # Asegúrate que 'fecha transaccion' es el nombre normalizado
                }
                actual_cob_renames = {k: v for k, v in cob_rename_map.items() if k in df_cob_prom.columns}
                df_cob_prom.rename(columns=actual_cob_renames, inplace=True)

                if "FechaTrans" in df_cob_prom.columns:
                    df_cob_prom["FechaTrans"] = pd.to_datetime(df_cob_prom["FechaTrans"], errors="coerce")
                if "Deposito" in df_cob_prom.columns:
                    df_cob_prom["Deposito"] = pd.to_numeric(df_cob_prom["Deposito"], errors="coerce").fillna(0) # Asumimos que convert_number ya se aplicó en la carga
                else: # Si Deposito no existe tras renombrar, añadirlo como 0 para evitar errores
                    df_cob_prom["Deposito"] = 0
                # Asegurar que 'Contrato' sea string para el join
                if "Contrato" in df_cob_prom.columns:
                    df_cob_prom["Contrato"] = df_cob_prom["Contrato"].astype(str)


            # Trabajar con df_col_prom_original para el detalle de colocaciones
            df_col_prom = df_col_prom_original.copy() # df_col_prom será el DataFrame de trabajo

            if df_col_prom.empty:
                st.info(f"No se encontraron créditos colocados para el promotor {promotor_sel}.")
            else:
                # Asegurar que 'Contrato' sea string para el join
                if "Contrato" in df_col_prom.columns:
                    df_col_prom["Contrato"] = df_col_prom["Contrato"].astype(str)
                
                # Nombres de columna esperados directamente desde tu archivo Excel (fila 5)
                # Estos son los nombres que deben existir en df_col_prom ANTES de renombrar
                excel_col_names = {
                    "cliente": "Nombre del cliente",
                    "contrato_id": "Contrato",
                    "cuota": "Cuota total",
                    "fecha_pago1": "Fecha primer pago"
                }

                # Renombrar a los nombres internos que usa el resto de la lógica de esta pestaña
                rename_map_colocaciones = {
                    excel_col_names["cliente"]: "Cliente",
                    excel_col_names["contrato_id"]: "Contrato",
                    excel_col_names["cuota"]: "PS", # Payment Size (Cuota)
                    excel_col_names["fecha_pago1"]: "FechaPrimerPago"
                }
                
                # Aplicar renombres solo si las columnas existen
                actual_col_renames = {k: v for k, v in rename_map_colocaciones.items() if k in df_col_prom.columns}
                df_col_prom.rename(columns=actual_col_renames, inplace=True)

                # Validar columnas críticas DESPUÉS de intentar renombrar
                if "FechaPrimerPago" not in df_col_prom.columns:
                    st.error(
                        f"Columna crítica '{rename_map_colocaciones[excel_col_names['fecha_pago1']]}' (debería originarse de '{excel_col_names['fecha_pago1']}') "
                        "no se encontró en los datos de colocaciones del promotor."
                    )
                    st.markdown(f"**Columnas disponibles en datos de colocación para este promotor:** `{', '.join(df_col_prom.columns.tolist())}`")
                    st.markdown(f"**Asegúrate de que la columna '{excel_col_names['fecha_pago1']}' exista en tu archivo Excel 'Colocación' (fila 5) y se esté cargando.**")
                    st.stop()
                
                if "PS" not in df_col_prom.columns:
                    st.error(
                        f"Columna crítica '{rename_map_colocaciones[excel_col_names['cuota']]}' (debería originarse de '{excel_col_names['cuota']}') "
                        "no se encontró."
                    )
                    st.markdown(f"**Columnas disponibles en datos de colocación para este promotor:** `{', '.join(df_col_prom.columns.tolist())}`")
                    df_col_prom["PS"] = 0 # Para evitar que se detenga, pero indica un problema de datos
                
                if "Contrato" not in df_col_prom.columns: # Esencial para el cruce con cobranza
                     st.error(
                        f"Columna crítica '{rename_map_colocaciones[excel_col_names['contrato_id']]}' (debería originarse de '{excel_col_names['contrato_id']}') "
                        "no se encontró."
                    )
                     st.markdown(f"**Columnas disponibles en datos de colocación para este promotor:** `{', '.join(df_col_prom.columns.tolist())}`")
                     # No se puede continuar sin Contrato para el cruce, pero la tabla se puede mostrar parcialmente
                
                # Convertir tipos de datos (si no se hizo ya al cargar df_colocaciones_info_completa)
                df_col_prom["FechaPrimerPago"] = pd.to_datetime(df_col_prom["FechaPrimerPago"], errors="coerce")
                df_col_prom["PS"] = pd.to_numeric(df_col_prom["PS"], errors="coerce").fillna(0)

                # La siguiente línea original es:
                # hoy = datetime.now().date()

                # 3) Métricas por crédito
                hoy = datetime.now().date()
                filas = []

                if df_col_prom.empty:
                    st.info("No hay créditos registrados para este promotor después del procesamiento.")
                else:
                    for _, cred in df_col_prom.iterrows():
                        # Validar que las columnas necesarias para el cálculo existan en la fila 'cred'
                        contrato = cred.get("Contrato", None)
                        ps = cred.get("PS", 0)
                        fecha_fp_obj = cred.get("FechaPrimerPago", None)

                        if contrato is None or pd.isna(fecha_fp_obj):
                            # Saltar este crédito si falta información esencial
                            # Podrías añadir un st.warning aquí si quieres notificar sobre créditos omitidos
                            continue
                        
                        fecha_fp = fecha_fp_obj.date()

                        # Semanas transcurridas y pagos debidos
                        weeks_elapsed = max(0, (hoy - fecha_fp).days // 7)
                        pag_debidos = min(14, weeks_elapsed + 1) # Asumiendo máximo 14 pagos

                        # Sumar todos los depósitos para este contrato
                        total_dep = 0
                        if not df_cob_prom.empty and "Contrato" in df_cob_prom.columns and "Deposito" in df_cob_prom.columns:
                            pagos = df_cob_prom[df_cob_prom["Contrato"] == contrato]
                            total_dep = pagos["Deposito"].sum()
                        
                        completos = 0
                        resto = 0
                        if ps > 0:
                            completos = min(int(total_dep // ps), 14)
                            resto = total_dep % ps
                        
                        incompletos = 1 if 0 < resto < ps else 0
                        vencido_monto = max(0, pag_debidos * ps - total_dep)
                        adelantados = max(0, completos - pag_debidos)

                        # Estatus
                        fecha_venc_credito = (fecha_fp + pd.Timedelta(weeks=13)) # Vencimiento del crédito (14 semanas)
                        
                        estatus = "Indeterminado"
                        color = "grey"

                        if completos >= 14 : # Crédito Liquidado
                            estatus, color = "Liquidado", "blue"
                        elif completos >= pag_debidos:
                            estatus, color = "Al corriente", "green"
                        elif hoy < fecha_venc_credito : # Aún no vence el crédito completo
                            estatus, color = "Atrasado", "orange"
                        else: # Ya pasó la fecha de vencimiento del crédito y no está liquidado
                            estatus, color = "Vencido", "red"


                        filas.append({
                            "Cliente": cred.get("Cliente", "N/A"), # Usa .get() para seguridad
                            "Contrato": contrato,
                            "Pagos debidos": pag_debidos,
                            "Pagos completos": completos,
                            "Pagos incompletos": incompletos,
                            "Saldo vencido": vencido_monto,
                            "Pagos adelantados": adelantados,
                            "Estatus": estatus,
                            "Color": color,
                        })
                
                df_det = pd.DataFrame(filas)
            if df_det.empty:
                st.info("No hay créditos para mostrar para este promotor (posiblemente por falta de datos o errores en el procesamiento).")
            else:
                # 4) Formato y estilo
                df_det["Saldo vencido"] = df_det["Saldo vencido"].apply(format_money)

                def pintar(row):
                    # Esta función ASUME que la columna "Color" existe en la 'row' que recibe
                    # de df_det_styled
                    color_val = row.get("Color", "grey") # Usamos .get() por seguridad, por si acaso
                    return [f"color: {color_val}; font-weight: bold;" if col == "Estatus" else "" for col in row.index]

                # Aplicamos el estilo al DataFrame COMPLETO (que SÍ tiene la columna "Color")
                df_det_styled = df_det.style.apply(pintar, axis=1)

                # Columnas que queremos MOSTRAR al usuario final (excluyendo "Color")
                columnas_a_mostrar = [col for col in df_det.columns if col != "Color"]

                st.dataframe(
                    df_det_styled, # Pasamos el DataFrame ya estilizado
                    use_container_width=True,
                    height=min(600, 35 + 30 * len(df_det)), # Ajustar altura
                    # Para ocultar la columna "Color" visualmente si aún estuviera después del styler:
                    column_config={ 
                        "Color": None # Esto oculta la columna "Color" si el styler no la eliminó
                    },
                    # O, si quieres ser más explícito sobre qué columnas mostrar del df_det original:
                    # data=df_det[columnas_a_mostrar].style.apply(pintar, axis=1) 
                    # Pero es más simple aplicar el estilo y luego ocultar/configurar.
                    # La forma más limpia es que el styler no dependa de una columna que se va a quitar *justo antes*.

                    # Vamos a probar solo ocultándola, ya que el styler puede necesitarla.
                    # Si st.dataframe(df_det_styled...) muestra la columna "Color", entonces usamos
                    # data=df_det[columnas_a_mostrar] y aplicamos el style a eso.
                    # Pero primero, probemos si el styler la maneja bien y luego st.dataframe
                    # puede simplemente mostrar el resultado.
                    # El .drop() ANTES del .style.apply() es el problema directo.
                )




        # ------------- NUEVA PESTAÑA: Totales y Última -------------
        # ------------- PESTAÑA: Totales y Última (actualizada) -------------
        # ------------- PESTAÑA: Totales y Última (versión a prueba de nombres) -------------
        with tabs[7]:
            st.header("Totales y Última")

            # Mapeo de meses a texto en español
            meses = {
                1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
                5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
                9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
            }

            # ------------------------------------------------------------------
            # 1) Detectamos las dos últimas semanas presentes en TODOS los datos
            # ------------------------------------------------------------------
            semanas = sorted(
                df_metas_summary["Semana"].unique(),
                key=lambda p: p.start_time
            )
            penult_week = semanas[-2] if len(semanas) >= 2 else None
            last_week   = semanas[-1] if len(semanas) >= 1 else None

            # Encabezados bonitos: “Lunes 5 mayo”, etc.
            def header_from_period(p):
                if p is None:
                    return ""
                lunes = p.start_time + pd.Timedelta(days=2)   # lunes de esa semana
                return f"Lunes {lunes.day} {meses[lunes.month]}"

            penult_header = header_from_period(penult_week) or "Penúltima Meta"
            last_header   = header_from_period(last_week)   or "Última Meta"

            # ------------------------------------------------------------------
            # 2) Recorremos cada promotor por código (P1, P2, …)
            # ------------------------------------------------------------------
            code_to_name = dict(zip(df_control["N"], df_control["Nombre"]))
            codes_sorted = sorted(df_control["N"], key=lambda x: int(x.lstrip("P")))

            rows = []
            for code in codes_sorted:
                nombre = code_to_name.get(code, "")

                # ----- Metas -----
                df_meta_prom = df_metas_summary[df_metas_summary["Promotor"] == code]
                if df_meta_prom.empty:
                    continue  # no metas -> nada que mostrar

                suma_metas = df_meta_prom["Meta"].sum()
                if suma_metas == 0:
                    continue  # filtra promotores sin metas

                penult_val = (
                    df_meta_prom.loc[df_meta_prom["Semana"] == penult_week, "Meta"].sum()
                    if penult_week else 0
                )
                last_val = (
                    df_meta_prom.loc[df_meta_prom["Semana"] == last_week, "Meta"].sum()
                    if last_week else 0
                )

                # ----- Cobranza acumulada hasta el viernes de la última semana -----
                if last_week:
                    last_end = last_week.end_time      # viernes 23:59
                    df_cob_prom = df_cobranza[df_cobranza["N"] == code]
                    suma_cob = df_cob_prom.loc[
                        df_cob_prom["Fecha Transacción"] <= last_end,
                        "Depósito"
                    ].sum()
                else:
                    suma_cob = 0

                rows.append({
                    "N": code,
                    "Nombre": nombre,
                    penult_header: penult_val,
                    last_header:  last_val,
                    "Suma Metas": suma_metas,
                    "Cobranza Hasta Último Viernes": suma_cob
                })

            # ------------------------------------------------------------------
            # 3) Construimos y mostramos el DataFrame
            # ------------------------------------------------------------------
            if rows:
                df_totales = pd.DataFrame(rows)

                # Formateo monetario
                for col in [penult_header, last_header, "Suma Metas", "Cobranza Hasta Último Viernes"]:
                    df_totales[col] = df_totales[col].apply(format_money)

                st.dataframe(df_totales, use_container_width=True)
            else:
                st.info("No hay datos para mostrar en esta sección.")

if __name__ == "__main__":
    main()
