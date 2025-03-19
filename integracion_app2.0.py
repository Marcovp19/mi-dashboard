import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from datetime import datetime, timedelta, date

# --------------------------------------------------------------------
#                       FUNCIONES AUXILIARES
# --------------------------------------------------------------------

def format_money(x):
    """
    Convierte un número a formato monetario con dos decimales,
    ej: 12345.678 -> '$12,345.68'.
    """
    try:
        return f"${x:,.2f}"
    except Exception:
        return x

def convert_number(x):
    """
    Convierte cadenas con comas o puntos mezclados a float estándar.
    Ejemplo:
      '1,234.56' -> 1234.56
      '1.234,56' -> 1234.56
    """
    s = str(x).strip()
    if "," in s and "." in s:
        # Caso "1.234,56"
        s = s.replace(".", "").replace(",", ".")
    else:
        # Caso "1,234.56" o "1234,56"
        s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
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

# -- Función de estilo para el Ranking (≥96% Verde, ≥80% Amarillo, <80% Rojo) --
def style_cumplimiento(val):
    if val >= 96:
        color = "green"
    elif val >= 80:
        color = "orange"
    else:
        color = "red"
    return f"color: {color}; font-weight: bold;"

# -- Función de estilo para la Diferencia de patrón de pago --
def style_difference(val):
    """
    - Rojo si ≥1.1
    - Amarillo si ≥0.65 y <1.1
    """
    try:
        if val >= 1.1:
            return "background-color: red; color: white;"
        elif val >= 0.65:
            return "background-color: yellow; color: black;"
    except:
        pass
    return ""  # Sin estilo si <0.65 o NaN

# --------------------------------------------------------------------
#                 SECCIÓN PARA CARGA DE DATOS (CACHED)
# --------------------------------------------------------------------

@st.cache_data
def load_data_control(vas_file):
    """
    Carga y procesa el archivo de Metas y Control (vas_file).
    - Hoja "Control"
    - Hojas individuales (Promotor) con columnas Fecha, Meta
    """
    df_control = pd.read_excel(vas_file, sheet_name="Control")
    required_cols_control = ["N", "Nombre", "Antigüedad (meses)"]
    check_required_columns(df_control, required_cols_control, df_name="df_control (sheet Control)")
    
    df_control["N"] = df_control["N"].astype(str).str.strip().str.upper()
    df_control["Nombre"] = df_control["Nombre"].str.strip()
    df_control["Antigüedad (meses)"] = df_control["Antigüedad (meses)"].apply(
        lambda x: round(x, 2) if pd.notna(x) else x
    )
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
    """
    Carga y procesa el archivo de cobranza (cob_file).
    - Hoja "Recuperaciones"
    - Columnas: [Nombre Promotor, Fecha transacción, Depósito, Estado, Municipio]
    - skiprows=2
    """
    df_cobranza = pd.read_excel(
        cob_file,
        sheet_name="Recuperaciones",
        skiprows=2,
        usecols=["Nombre Promotor", "Fecha transacción", "Depósito", "Estado", "Municipio"]
    )
    required_cols_cob = ["Nombre Promotor", "Fecha transacción", "Depósito", "Estado", "Municipio"]
    check_required_columns(df_cobranza, required_cols_cob, df_name="df_cobranza (sheet Recuperaciones)")
    
    df_cobranza["Fecha transacción"] = pd.to_datetime(df_cobranza["Fecha transacción"], errors="coerce")
    df_cobranza["Depósito"] = df_cobranza["Depósito"].apply(convert_number)
    df_cobranza.dropna(subset=["Nombre Promotor", "Depósito"], inplace=True)
    
    df_cobranza.rename(columns={"Fecha transacción": "Fecha Transacción"}, inplace=True)
    df_cobranza["Semana"] = df_cobranza["Fecha Transacción"].dt.to_period("W-FRI")
    df_cobranza["Nombre Promotor"] = df_cobranza["Nombre Promotor"].str.strip().str.upper()
    
    # Cálculo de Día_num con base en "Sábado=1, Domingo=2, Lunes=3, ..." 
    df_cobranza["Día_num"] = ((df_cobranza["Fecha Transacción"].dt.dayofweek - 5) % 7) + 1
    
    return df_cobranza

@st.cache_data
def load_data_colocaciones(col_file):
    """
    Carga y procesa el archivo de colocaciones (col_file).
    - Hoja "Colocación"
    - skiprows=4
    - Columnas: [Nombre promotor, Fecha desembolso, Monto desembolsado]
    - Se agrupa para obtener:
        Creditos_Colocados = count(Monto desembolsado)
        Venta = sum(Monto desembolsado)
    """
    if not col_file:
        return pd.DataFrame()
    
    df_col = pd.read_excel(
        col_file,
        sheet_name="Colocación",
        skiprows=4,
        usecols=["Nombre promotor", "Fecha desembolso", "Monto desembolsado"]
    )
    
    required_cols_col = ["Nombre promotor", "Fecha desembolso", "Monto desembolsado"]
    check_required_columns(df_col, required_cols_col, df_name="df_col (sheet Colocación)")
    
    df_col["Fecha desembolso"] = pd.to_datetime(df_col["Fecha desembolso"], errors="coerce")
    df_col.dropna(subset=["Nombre promotor", "Fecha desembolso"], inplace=True)
    df_col["Nombre promotor"] = df_col["Nombre promotor"].str.strip().str.upper()
    df_col["Semana"] = df_col["Fecha desembolso"].dt.to_period("W-FRI")
    
    df_col_agg = df_col.groupby(["Nombre promotor", "Semana"], as_index=False).agg(
        Creditos_Colocados=("Monto desembolsado", "count"),
        Venta=("Monto desembolsado", "sum")
    )
    return df_col_agg

@st.cache_data
def load_data_descuentos(por_capturar_file):
    """
    Carga el archivo 'Por_capturar.xlsx' con columnas:
    [Promotor, Fecha Ministración, Descuento Renovación] en la fila 4 => skiprows=3.
    Solo toma valores de Descuento Renovación > 0.
    """
    if not por_capturar_file:
        return pd.DataFrame()
    
    df_desc = pd.read_excel(
        por_capturar_file,
        skiprows=3,
        usecols=["Promotor", "Fecha Ministración", "Descuento Renovación"]
    )
    
    required_cols_desc = ["Promotor", "Fecha Ministración", "Descuento Renovación"]
    check_required_columns(df_desc, required_cols_desc, df_name="df_desc (Por_capturar)")
    
    df_desc["Fecha Ministración"] = pd.to_datetime(df_desc["Fecha Ministración"], errors="coerce")
    df_desc["Promotor"] = df_desc["Promotor"].str.strip().str.upper()
    df_desc["Descuento Renovación"] = df_desc["Descuento Renovación"].apply(convert_number)
    df_desc.dropna(subset=["Promotor", "Descuento Renovación"], inplace=True)
    
    df_desc = df_desc[df_desc["Descuento Renovación"] > 0]
    df_desc["Semana"] = df_desc["Fecha Ministración"].dt.to_period("W-FRI")
    
    df_desc_agg = df_desc.groupby(["Promotor", "Semana"], as_index=False)["Descuento Renovación"].sum()
    df_desc_agg.rename(columns={"Descuento Renovación": "Descuento_Renovacion"}, inplace=True)
    
    return df_desc_agg

@st.cache_data
def merge_colocaciones(df_col_agg, df_control):
    """
    Enlaza la info de colocaciones con df_control para obtener 'N' y 'Nombre'.
    """
    if df_col_agg.empty:
        return pd.DataFrame()
    
    df_control["Nombre_upper"] = df_control["Nombre"].str.upper()
    
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
    """
    Construye un DataFrame con el resumen de promotores:
    [N, Nombre, Antigüedad (meses), Total Metas, Total Cobranza]
    Se excluyen promotores sin antigüedad o sin datos.
    """
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
        
        # Se excluye solo si no hay antigüedad y tampoco datos;
        # si quieres mostrar todos, podrías quitar este if:
        if pd.isna(antig) or (total_meta == 0 and total_cob == 0):
            # Quitar la línea anterior si deseas mostrarlos absolutamente todos.
            continue
        
        promoters_summary_list.append({
            "N": code,
            "Nombre": name,
            "Antigüedad (meses)": antig,
            "Total Metas": total_meta,
            "Total Cobranza": total_cob
        })
    
    df_promoters_summary = pd.DataFrame(promoters_summary_list)
    # Ordenar basado en el número dentro de la columna N
    df_promoters_summary = df_promoters_summary.sort_values(
        by="N",
        key=lambda x: x.str.extract(r"(\d+)")[0].astype(int)
    )
    return df_promoters_summary

def build_ranking(df_control, df_metas, df_cob):
    """
    Construye un DataFrame para el ranking de promotores EXCLUYENDO la última meta de cada promotor.
    Columnas: [N, Nombre, Metas_sin_ultima, Cobranza_total, Cumplimiento (%)]
    """
    df_metas_no_ultima = df_metas.copy()
    df_metas_no_ultima["max_semana_prom"] = df_metas_no_ultima.groupby("Promotor")["Semana"].transform("max")
    df_metas_no_ultima = df_metas_no_ultima[df_metas_no_ultima["Semana"] != df_metas_no_ultima["max_semana_prom"]]
    df_metas_no_ultima.drop(columns=["max_semana_prom"], inplace=True)
    
    df_metas_group = df_metas_no_ultima.groupby("Promotor")["Meta"].sum().reset_index(name="Metas_sin_ultima")
    
    code_to_name = dict(zip(df_control["N"], df_control["Nombre"]))
    name_to_code = {v.upper(): k for k, v in code_to_name.items()}
    
    df_cob_group = df_cob.groupby("Nombre Promotor")["Depósito"].sum().reset_index(name="Cobranza_total")
    df_cob_group["Promotor"] = df_cob_group["Nombre Promotor"].map(name_to_code)
    
    df_ranking = pd.merge(df_metas_group, df_cob_group, on="Promotor", how="outer").fillna(0)
    df_ranking["N"] = df_ranking["Promotor"]
    df_ranking["Nombre"] = df_ranking["N"].map(code_to_name)
    
    df_ranking["Cumplimiento (%)"] = np.where(
        df_ranking["Metas_sin_ultima"] == 0,
        0,
        df_ranking["Cobranza_total"] / df_ranking["Metas_sin_ultima"] * 100
    )
    df_ranking["Cumplimiento (%)"] = df_ranking["Cumplimiento (%)"].round(2)
    
    # Orden descendente por % de cumplimiento
    df_ranking.sort_values(by="Cumplimiento (%)", ascending=False, inplace=True)
    
    return df_ranking[["N", "Nombre", "Metas_sin_ultima", "Cobranza_total", "Cumplimiento (%)"]]

# --------------------------------------------------------------------
#                           APP PRINCIPAL
# --------------------------------------------------------------------

def main():
    st.set_page_config(page_title="Dashboard de Promotores", layout="wide")
    st.title("Dashboard de Promotores y Cobranza (Versión Completa)")

    # 1) ARCHIVOS PRINCIPALES: Metas/Control + Cobranza
    st.sidebar.header("Carga de Archivos")
    vas_file = st.sidebar.file_uploader("Archivo de metas y control (VasTu.xlsx)", type=["xlsx"])
    cob_file = st.sidebar.file_uploader("Archivo de cobranza (Cobranza_al_14_mar.xlsx)", type=["xlsx"])
    # 2) Colocaciones
    col_file = st.sidebar.file_uploader("Archivo de colocaciones (Colocaciones_al_14_mar.xlsx)", type=["xlsx"])
    # 3) Por_capturar (descuento renovación)
    por_capturar_file = st.sidebar.file_uploader("Archivo Por_capturar.xlsx (Descuento Renovación)", type=["xlsx"])

    if vas_file and cob_file:
        try:
            # --- Cargamos la info principal ---
            df_control, promotores_dict, df_metas_summary = load_data_control(vas_file)
            df_cobranza = load_data_cobranza(cob_file)
            
            # --- Cargamos Colocaciones ---
            df_col_agg = load_data_colocaciones(col_file)
            df_col_merge = merge_colocaciones(df_col_agg, df_control)
            
            # --- Cargamos Descuentos Renovación ---
            df_desc_agg = load_data_descuentos(por_capturar_file)  # puede ser vacío

            # --- Resumen de promotores ---
            df_promoters_summary = build_promoters_summary(df_control, df_metas_summary, df_cobranza)

        except Exception as e:
            st.error(f"Error al cargar y procesar los datos: {e}")
            return

        # Creamos las Pestañas (8):
        tabs = st.tabs([
            "Datos Globales",
            "Resumen de Promotores",
            "Ranking de Promotores",
            "Análisis de Cambio de Patrón de Pago",
            "Incumplimiento por Semana",
            "Detalles del Promotor",
            "Por Localidad",
            "Colocación de Créditos"
        ])

        # --------------------------------------------------------------------------------
        # --- 0. Pestaña: Datos Globales ---
        with tabs[0]:
            st.header("Datos Globales de la Empresa")
            st.markdown("Comparación de dos semanas y dispersión de depósitos.")
            
            # Obtenemos todas las semanas
            weeks_meta = pd.Index(df_metas_summary["Semana"].unique())
            weeks_cob = pd.Index(df_cobranza["Semana"].unique())
            all_weeks = weeks_meta.union(weeks_cob)

            if len(all_weeks) == 0:
                st.write("No se encontraron semanas disponibles. Revisa tus datos.")
            else:
                sorted_weeks = sorted(all_weeks, key=lambda p: p.start_time)

                def format_week_label(w):
                    return (w.start_time + pd.Timedelta(days=2)).strftime("%-d %b").lower() + f" ({w})"

                week_mapping = {format_week_label(w): w for w in sorted_weeks}
                week_labels = list(week_mapping.keys())

                st.write("Selecciona 2 semanas para comparar:")
                selected_week_1_label = st.selectbox("Semana 1", week_labels, index=0)
                if len(week_labels) > 1:
                    selected_week_2_label = st.selectbox("Semana 2", week_labels, index=1)
                else:
                    selected_week_2_label = selected_week_1_label
                
                week_1 = week_mapping[selected_week_1_label]
                week_2 = week_mapping[selected_week_2_label]

                total_meta_1 = df_metas_summary[df_metas_summary["Semana"] == week_1]["Meta"].sum()
                total_cobranza_1 = df_cobranza[df_cobranza["Semana"] == week_1]["Depósito"].sum()
                total_meta_2 = df_metas_summary[df_metas_summary["Semana"] == week_2]["Meta"].sum()
                total_cobranza_2 = df_cobranza[df_cobranza["Semana"] == week_2]["Depósito"].sum()

                cumplimiento_1 = (total_cobranza_1 / total_meta_1 * 100) if total_meta_1 > 0 else 0
                cumplimiento_2 = (total_cobranza_2 / total_meta_2 * 100) if total_meta_2 > 0 else 0

                global_data = pd.DataFrame({
                    "Semana": [selected_week_1_label, selected_week_2_label],
                    "Total Metas": [total_meta_1, total_meta_2],
                    "Total Cobranza": [total_cobranza_1, total_cobranza_2],
                    "Cumplimiento (%)": [cumplimiento_1, cumplimiento_2]
                })

                global_data["Cumplimiento (%)"] = global_data["Cumplimiento (%)"].round(2)

                global_data_display = global_data.copy()
                global_data_display["Total Metas"] = global_data_display["Total Metas"].apply(format_money)
                global_data_display["Total Cobranza"] = global_data_display["Total Cobranza"].apply(format_money)

                st.markdown("### Comparación de semanas seleccionadas")
                st.dataframe(global_data_display, use_container_width=True)

                # Gráfico de comparación (Metas vs Cobranza)
                data_melt = global_data.melt(
                    id_vars=["Semana"],
                    value_vars=["Total Metas", "Total Cobranza"],
                    var_name="Tipo",
                    value_name="Monto"
                )
                chart_totals = alt.Chart(data_melt).mark_bar().encode(
                    x=alt.X("Semana:N", title="Semana", axis=alt.Axis(labelAngle=0)),
                    xOffset="Tipo:N",
                    y=alt.Y("Monto:Q", title="Monto", axis=alt.Axis(format="$,.2f")),
                    color="Tipo:N",
                    tooltip=["Semana:N", "Tipo:N", "Monto:Q"]
                ).properties(
                    width=400,
                    height=400,
                    title="Comparación de Totales"
                )
                st.altair_chart(chart_totals, use_container_width=True)

                st.markdown("### Dispersión de Depósitos a lo largo de cada semana")
                df_cob_2w = df_cobranza[df_cobranza["Semana"].isin([week_1, week_2])].copy()
                if not df_cob_2w.empty:
                    def map_label(semana):
                        if semana == week_1:
                            return selected_week_1_label
                        elif semana == week_2:
                            return selected_week_2_label
                        else:
                            return "Otros"

                    df_cob_2w["SemanaLabel"] = df_cob_2w["Semana"].apply(map_label)
                    df_cob_2w["DayName"] = df_cob_2w["Fecha Transacción"].dt.day_name().str[:3]
                    
                    df_cob_2w_agg = df_cob_2w.groupby(["SemanaLabel", "DayName"], as_index=False)["Depósito"].sum()
                    df_cob_2w_agg.rename(columns={"Depósito": "TotalDia"}, inplace=True)
                    
                    # Orden sábado->viernes
                    day_order = ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"]

                    chart_scatter = alt.Chart(df_cob_2w_agg).mark_line(point=True).encode(
                        x=alt.X("DayName:N", sort=day_order, title="Día de la semana"),
                        y=alt.Y("TotalDia:Q", title="Depósito Total del Día", axis=alt.Axis(format="$,.2f")),
                        color=alt.Color("SemanaLabel:N", title="Semana"),
                        tooltip=["SemanaLabel:N", "DayName:N", "TotalDia:Q"]
                    ).properties(
                        width=600,
                        height=400,
                        title="Depósitos diarios por Semana (suma por día)"
                    )
                    st.altair_chart(chart_scatter, use_container_width=True)
                else:
                    st.write("No hay registros de depósitos para las semanas seleccionadas.")

                # =======================
                # 1) NUEVA GRÁFICA BARRAS DE CRÉDITOS COLOCADOS (SEMANA 1 VS SEMANA 2)
                # =======================
                st.markdown("### Comparación de Créditos Colocados en las semanas seleccionadas")
                if df_col_agg is not None and not df_col_agg.empty:
                    df_col_2w = df_col_agg[df_col_agg["Semana"].isin([week_1, week_2])].copy()
                    if not df_col_2w.empty:
                        col_2w_sum = df_col_2w.groupby("Semana")["Creditos_Colocados"].sum().reset_index()

                        # Convertimos la columna 'Semana' a etiquetas similares
                        def label_semana(s):
                            if s == week_1:
                                return selected_week_1_label
                            elif s == week_2:
                                return selected_week_2_label
                            return "Otra"

                        col_2w_sum["SemanaLabel"] = col_2w_sum["Semana"].apply(label_semana)

                        chart_creditos = alt.Chart(col_2w_sum).mark_bar().encode(
                            x=alt.X("SemanaLabel:N", title="Semana"),
                            y=alt.Y("Creditos_Colocados:Q", title="Créditos Colocados"),
                            tooltip=["SemanaLabel:N", "Creditos_Colocados:Q"]
                        ).properties(
                            width=400,
                            height=400
                        )
                        st.altair_chart(chart_creditos, use_container_width=True)
                    else:
                        st.write("No se encontraron créditos colocados para las semanas seleccionadas.")
                else:
                    st.write("No se cuenta con datos de colocaciones para graficar.")

        # --------------------------------------------------------------------------------
        # --- 1. Pestaña: Resumen de Promotores ---
        with tabs[1]:
            st.header("Resumen de Promotores")
            st.markdown("Tabla con promotores, antigüedad, metas, cobranza y diferencia.")

            df_display = df_promoters_summary.copy()
            df_display["Diferencia"] = df_display["Total Cobranza"] - df_display["Total Metas"]
            
            df_display["Total Metas"] = df_display["Total Metas"].apply(format_money)
            df_display["Total Cobranza"] = df_display["Total Cobranza"].apply(format_money)
            df_display["Diferencia"] = df_display["Diferencia"].apply(format_money)
            df_display["Antigüedad (meses)"] = df_display["Antigüedad (meses)"].round(2)

            st.dataframe(
                df_display[["N", "Nombre", "Antigüedad (meses)", "Total Metas", "Total Cobranza", "Diferencia"]],
                use_container_width=True
            )

        # --------------------------------------------------------------------------------
        #############################################
        # Pestaña: RANKING DE PROMOTORES
        #############################################
        with tabs[2]:
            st.header("Ranking de Promotores (excluyendo la última meta)")
            st.markdown("Se calcula el porcentaje de cumplimiento global sin tomar la última meta.")
            
            # ----------------------------------------------------------
            # 1) Seleccionar el 'lunes de corte' para ignorar semanas inconclusas
            # ----------------------------------------------------------
            from datetime import date, datetime
            
            ranking_cutoff = st.date_input("Lunes de corte", value=date.today())
            ranking_cutoff_dt = datetime.combine(ranking_cutoff, datetime.min.time())

            # ----------------------------------------------------------
            # 2) Filtramos las metas y la cobranza para incluir solo semanas con end_time < cutoff
            # ----------------------------------------------------------
            df_metas_ranking = df_metas_summary[
                df_metas_summary["Semana"].apply(lambda p: p.end_time < ranking_cutoff_dt)
            ].copy()

            df_cob_ranking = df_cobranza[
                df_cobranza["Semana"].apply(lambda p: p.end_time < ranking_cutoff_dt)
            ].copy()

            # ----------------------------------------------------------
            # 3) Función que construye el ranking sin incluir la última meta
            # ----------------------------------------------------------
            def build_ranking(df_control, df_metas, df_cob):
                """
                Excluye la última meta de cada promotor dentro del DataFrame df_metas,
                luego calcula la suma de esas metas y la compara con la cobranza (df_cob).
                """
                # Ordenamos por Promotor y Semana
                df_metas_sorted = df_metas.sort_values(["Promotor", "Semana"])
                
                # Para cada promotor, removemos la fila correspondiente a su 'última' semana
                # dentro de este conjunto de datos (ya filtrado por 'lunes de corte').
                # Si un promotor solo tiene 1 meta en el rango, también se excluye (es la "última").
                df_metas_no_ultima = (
                    df_metas_sorted.groupby("Promotor", group_keys=True)
                    .apply(lambda group: group.iloc[:-1] if len(group) > 1 else group.iloc[0:0])
                    .reset_index(drop=True)
                )

                # Sumamos las metas "sin la última"
                df_metas_group = df_metas_no_ultima.groupby("Promotor")["Meta"].sum().reset_index(name="Metas_sin_ultima")

                # Sumamos la cobranza por promotor
                code_to_name = dict(zip(df_control["N"], df_control["Nombre"]))
                name_to_code = {v.upper(): k for k, v in code_to_name.items()}

                df_cob_group = df_cob.groupby("Nombre Promotor")["Depósito"].sum().reset_index(name="Cobranza_total")
                df_cob_group["Promotor"] = df_cob_group["Nombre Promotor"].map(name_to_code)

                # Unimos metas y cobranza
                df_ranking = pd.merge(df_metas_group, df_cob_group, on="Promotor", how="outer").fillna(0)

                # Añadimos columnas auxiliares
                df_ranking["N"] = df_ranking["Promotor"]
                df_ranking["Nombre"] = df_ranking["N"].map(code_to_name)

                df_ranking["Cumplimiento (%)"] = np.where(
                    df_ranking["Metas_sin_ultima"] == 0,
                    0,
                    df_ranking["Cobranza_total"] / df_ranking["Metas_sin_ultima"] * 100
                )
                df_ranking["Cumplimiento (%)"] = df_ranking["Cumplimiento (%)"].round(2)

                # Ordenamos descendente por % de cumplimiento
                df_ranking.sort_values(by="Cumplimiento (%)", ascending=False, inplace=True)

                return df_ranking[["N", "Nombre", "Metas_sin_ultima", "Cobranza_total", "Cumplimiento (%)"]]

            # ----------------------------------------------------------
            # 4) Construimos el ranking y formateamos
            # ----------------------------------------------------------
            df_ranking = build_ranking(df_control, df_metas_ranking, df_cob_ranking)

            # Formateo para visualizar Metas_sin_ultima y Cobranza_total como dinero
            df_ranking["Metas_sin_ultima"] = df_ranking["Metas_sin_ultima"].apply(format_money)
            df_ranking["Cobranza_total"] = df_ranking["Cobranza_total"].apply(format_money)

            # Estilo condicional según % de cumplimiento
            def highlight_style(df):
                return df.style.applymap(style_cumplimiento, subset=["Cumplimiento (%)"])

            st.dataframe(
                highlight_style(df_ranking),
                use_container_width=True
            )

        # --------------------------------------------------------------------------------
        # --- 3. Pestaña: Análisis de Cambio de Patrón de Pago ---
        with tabs[3]:
            st.header("Análisis de Cambio de Patrón de Pago")
            st.markdown("""
                Se muestra la comparación del día promedio de pago (últimas semanas vs. primeras).
                - Rojo si diferencia ≥ 1.1
                - Amarillo si diferencia ≥ 0.65 y < 1.1
                - Sin color si diferencia < 0.65
            """)

            # ===============================
            # 3) MOSTRAR TODOS LOS PROMOTORES
            # ===============================
            all_prom_changes = []
            # Recorremos TODOS los promotores (incluso los que no estén en el df_promoters_summary)
            # para mostrar si tienen al menos 1 registro de cobranza.
            for _, row in df_control.iterrows():
                promoter_code = row["N"]
                promoter_name = row["Nombre"]

                df_prom = df_cobranza[df_cobranza["Nombre Promotor"] == promoter_name.upper()].copy()
                if df_prom.empty:
                    # Sin registros de cobranza => mostramos diferencia = 0 o NaN
                    all_prom_changes.append({
                        "N": promoter_code,
                        "Nombre": promoter_name,
                        "Inicio Promedio": np.nan,
                        "Final Promedio": np.nan,
                        "Diferencia": np.nan
                    })
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
                    # Si solo hay 1 semana o menos, no hay cambio
                    first_avg = df_weekly["Weighted_Day"].mean() if n > 0 else np.nan
                    last_avg = first_avg
                else:
                    # Tomar las últimas 7 semanas, si hay suficientes
                    if n >= 7:
                        last_data = df_weekly.tail(7)
                        first_avg = last_data.head(3)["Weighted_Day"].mean()
                        last_avg = last_data.tail(3)["Weighted_Day"].mean()
                    else:
                        half = n // 2
                        first_avg = df_weekly.head(half)["Weighted_Day"].mean()
                        last_avg = df_weekly.tail(half)["Weighted_Day"].mean()

                diff = last_avg - first_avg if (pd.notna(first_avg) and pd.notna(last_avg)) else np.nan

                all_prom_changes.append({
                    "N": promoter_code,
                    "Nombre": promoter_name,
                    "Inicio Promedio": round(first_avg, 2) if pd.notna(first_avg) else np.nan,
                    "Final Promedio": round(last_avg, 2) if pd.notna(last_avg) else np.nan,
                    "Diferencia": round(diff, 2) if pd.notna(diff) else np.nan
                })

            df_change = pd.DataFrame(all_prom_changes)

            def highlight_diff(df):
                return df.style.applymap(style_difference, subset=["Diferencia"])

            if not df_change.empty:
                st.dataframe(highlight_diff(df_change), use_container_width=True)
            else:
                st.write("No hay datos de cobranza para mostrar cambios de patrón de pago.")

        # --------------------------------------------------------------------------------
        # --- 4. Pestaña: Incumplimiento por Semana ---
        with tabs[4]:
            st.header("Incumplimiento por Semana")
            st.markdown("Selecciona una semana para ver quiénes no alcanzaron su meta.")

            weeks_meta = pd.Index(df_metas_summary["Semana"])
            weeks_cob = pd.Index(df_cobranza["Semana"])
            all_weeks = weeks_meta.union(weeks_cob)
            sorted_weeks = sorted(all_weeks, key=lambda p: p.start_time)

            if len(sorted_weeks) == 0:
                st.write("No hay semanas disponibles en los datos.")
            else:
                week_mapping = {
                    (w.start_time + pd.Timedelta(days=2)).strftime("%-d %b").lower(): w
                    for w in sorted_weeks
                }
                selected_week_str = st.selectbox("Selecciona una semana", list(week_mapping.keys()))
                selected_week = week_mapping[selected_week_str]

                df_meta_sel = df_metas_summary[df_metas_summary["Semana"] == selected_week].copy()
                df_meta_sel["Nombre Promotor"] = df_meta_sel["Promotor"].map(promotores_dict).str.upper()

                df_cob_sel = df_cobranza[df_cobranza["Semana"] == selected_week].copy()
                df_cob_sel_grp = df_cob_sel.groupby("Nombre Promotor", as_index=False)["Depósito"].sum()

                incumplimiento = pd.merge(df_meta_sel, df_cob_sel_grp, on="Nombre Promotor", how="left")
                incumplimiento["Depósito"].fillna(0, inplace=True)
                incumplimiento["Cumplimiento (%)"] = incumplimiento.apply(
                    lambda row: round((row["Depósito"] / row["Meta"] * 100), 2) if row["Meta"] > 0 else 0,
                    axis=1
                )
                incumplidos = incumplimiento[incumplimiento["Depósito"] < incumplimiento["Meta"]].copy()
                incumplidos["Fecha"] = (selected_week.start_time + pd.Timedelta(days=2)).strftime("%-d %b %Y")
                incumplidos["N promotor"] = incumplidos["Promotor"]
                incumplidos["nombre"] = incumplidos["Nombre Promotor"]
                incumplidos = incumplidos.rename(columns={"Meta": "meta", "Depósito": "cobranza"})
                incumplidos["meta"] = incumplidos["meta"].apply(format_money)
                incumplidos["cobranza"] = incumplidos["cobranza"].apply(format_money)

                st.markdown("#### Totales de la semana seleccionada")
                num_incumplidores = incumplidos["N promotor"].nunique()
                total_meta_week = df_meta_sel["Meta"].sum()
                total_cob_week = df_cob_sel["Depósito"].sum() if not df_cob_sel.empty else 0
                porcentaje_cumpl = round((total_cob_week / total_meta_week * 100), 2) if total_meta_week > 0 else 0

                day_mapping = {
                    1: "Sábado", 2: "Domingo", 3: "Lunes", 4: "Martes",
                    5: "Miércoles", 6: "Jueves", 7: "Viernes"
                }
                avg_day_num = df_cob_sel["Día_num"].mean() if not df_cob_sel.empty else None
                if avg_day_num is not None and not np.isnan(avg_day_num):
                    avg_day = day_mapping.get(int(round(avg_day_num)), "N/A")
                else:
                    avg_day = "N/A"

                st.markdown(f"- **Número de promotores que incumplieron (semana):** {num_incumplidores}")
                st.markdown(f"- **Suma de todas las metas (semana):** {format_money(total_meta_week)}")
                st.markdown(f"- **Suma de todas las cobranzas (semana):** {format_money(total_cob_week)}")
                st.markdown(f"- **Porcentaje de cumplimiento (semana):** {porcentaje_cumpl}%")
                st.markdown(f"- **Día promedio de pago (semana):** {avg_day}")

                # Evaluación acumulada
                df_meta_cum = df_metas_summary[df_metas_summary["Semana"] <= selected_week].copy()
                df_meta_cum["Nombre Promotor"] = df_meta_cum["Promotor"].map(promotores_dict).str.upper()
                df_meta_group = df_meta_cum.groupby("Nombre Promotor")["Meta"].sum().reset_index()

                df_cob_cum = df_cobranza[df_cobranza["Semana"] <= selected_week].copy()
                df_cob_group = df_cob_cum.groupby("Nombre Promotor")["Depósito"].sum().reset_index()
                df_cob_avg_day = df_cob_cum.groupby("Nombre Promotor")["Día_num"].mean().reset_index().rename(columns={"Día_num": "avg_day_num"})

                df_cum = pd.merge(df_meta_group, df_cob_group, on="Nombre Promotor", how="outer").fillna(0)
                df_cum = pd.merge(df_cum, df_cob_avg_day, on="Nombre Promotor", how="left")
                df_cum["Diferencia"] = df_cum["Depósito"] - df_cum["Meta"]
                df_cum["Cumplimiento (%) acumulado"] = df_cum.apply(
                    lambda row: round((row["Depósito"] / row["Meta"] * 100), 2) if row["Meta"] > 0 else 0,
                    axis=1
                )
                df_cum["Día promedio de pago acumulado"] = df_cum["avg_day_num"].apply(
                    lambda x: day_mapping.get(int(round(x)), "N/A") if pd.notnull(x) else "N/A"
                )

                reverse_promotores = {v.upper(): k for k, v in promotores_dict.items()}
                df_cum["N promotor"] = df_cum["Nombre Promotor"].map(reverse_promotores)

                df_cum["N_prom_numeric"] = pd.to_numeric(
                    df_cum["N promotor"].astype(str).str.extract(r"(\d+)")[0],
                    errors="coerce"
                ).fillna(9999).astype(int)
                df_cum = df_cum.sort_values(by="N_prom_numeric").drop(columns=["N_prom_numeric"], errors="ignore")

                df_cum["Meta"] = df_cum["Meta"].apply(format_money)
                df_cum["Depósito"] = df_cum["Depósito"].apply(format_money)
                df_cum["Diferencia"] = df_cum["Diferencia"].apply(format_money)

                st.markdown("#### Evaluación acumulada individual hasta la semana seleccionada")
                st.dataframe(df_cum[[
                    "N promotor", "Nombre Promotor", "Meta", "Depósito",
                    "Diferencia", "Cumplimiento (%) acumulado", "Día promedio de pago acumulado"
                ]], use_container_width=True)

                st.markdown("### Incumplimiento para la semana seleccionada")
                st.dataframe(
                    incumplidos[["Fecha", "N promotor", "nombre", "meta", "cobranza", "Cumplimiento (%)"]],
                    use_container_width=True
                )

        # --------------------------------------------------------------------------------
        # --- 5. Pestaña: Detalles del Promotor ---
        with tabs[5]:
            st.header("Detalles del Promotor")
            if not df_promoters_summary.empty:
                # Entrada para buscar por parte del nombre
                search_term = st.text_input("Buscar promotor", key="busqueda_promotor_detalle")
                if search_term:
                    # Filtrar promotores cuyo nombre contenga el término
                    filtered_promoters = df_control[df_control["Nombre"].str.contains(search_term, case=False, na=False)]
                else:
                    filtered_promoters = df_control.copy()
                    
                promoter_names = filtered_promoters["Nombre"].tolist()
                if len(promoter_names) == 0:
                    st.error("No se encontraron promotores con ese criterio.")
                else:
                    # El usuario selecciona el promotor de la lista filtrada
                    selected_promoter = st.selectbox("Selecciona el promotor", promoter_names, key="select_promotor_detalle")
                    df_match = df_control[df_control["Nombre"] == selected_promoter]
                    if df_match.empty:
                        st.error("Promotor no encontrado. Revisa el nombre seleccionado.")
                    else:
                        promotor_sel = df_match["N"].iloc[0]
                        nombre_promotor = df_match["Nombre"].iloc[0]
                        antiguedad_val = df_match["Antigüedad (meses)"].iloc[0]
                        
                        # Filtrar la cobranza de este promotor
                        df_cob_prom = df_cobranza[df_cobranza["Nombre Promotor"] == nombre_promotor.upper()].copy()
                        
                        estados = df_cob_prom["Estado"].dropna().unique()
                        municipios = df_cob_prom["Municipio"].dropna().unique()
                        estado_str = ", ".join(estados) if len(estados) > 0 else "No registrado"
                        municipio_str = ", ".join(municipios) if len(municipios) > 0 else "No registrado"
                        
                        # Filtrar las metas del promotor según su código
                        df_meta_prom = df_metas_summary[df_metas_summary["Promotor"].str.strip().str.upper() == promotor_sel]
                        total_cobranza_meta = df_meta_prom["Meta"].sum()
                        total_cobranza_real = df_cob_prom["Depósito"].sum()
                        diferencia_cobranza = total_cobranza_real - total_cobranza_meta

                        # ===============================
                        # 4) REORDENAR Y RENOMBRAR LOS CAMPOS SOLICITADOS
                        # ===============================
                        st.markdown(
                            f"**Promotor:** {nombre_promotor}\n\n"
                            f"**Antigüedad (meses):** {antiguedad_val}\n\n"
                            f"**Estado:** {estado_str}\n\n"
                            f"**Municipio:** {municipio_str}\n\n"
                            f"**Meta Total:** {format_money(total_cobranza_meta)}\n\n"
                            f"**Cobranza Total:** {format_money(total_cobranza_real)}\n\n"
                            f"**Diferencia Total:** {format_money(diferencia_cobranza)}"
                        )
                        
                        # --- Sección de Resumen Semanal y Detalle Diario ---
                        df_cob_summary = df_cob_prom.groupby("Semana")["Depósito"].sum().reset_index()
                        
                        if not df_cob_summary.empty or not df_meta_prom.empty:
                            # Determinamos el rango de semanas
                            if not df_cob_summary.empty and not df_meta_prom.empty:
                                start_week = min(df_cob_summary["Semana"].min(), df_meta_prom["Semana"].min())
                                end_week = max(df_cob_summary["Semana"].max(), df_meta_prom["Semana"].max())
                            elif not df_cob_summary.empty:
                                start_week = df_cob_summary["Semana"].min()
                                end_week = df_cob_summary["Semana"].max()
                            else:
                                start_week = df_meta_prom["Semana"].min()
                                end_week = df_meta_prom["Semana"].max()
                            
                            # Creamos un DataFrame con todas las semanas del rango
                            full_weeks = pd.period_range(start=start_week, end=end_week, freq="W-FRI")
                            df_weeks = pd.DataFrame({"Semana": full_weeks})
                            df_weeks["Número de Semana"] = range(1, len(df_weeks) + 1)
                            
                            # Unimos la info de metas y cobranza
                            df_merge = df_weeks.merge(df_meta_prom[["Semana", "Meta"]], on="Semana", how="left")
                            df_merge = df_merge.merge(df_cob_summary, on="Semana", how="left").fillna(0)
                            df_merge.rename(columns={"Meta": "Cobranza Meta", "Depósito": "Cobranza Realizada"}, inplace=True)
                            df_merge["Cumplimiento (%)"] = df_merge.apply(
                                lambda row: round((row["Cobranza Realizada"] / row["Cobranza Meta"] * 100), 2)
                                if row["Cobranza Meta"] > 0 else 0,
                                axis=1
                            )
                            df_merge["Cobranza Meta"] = df_merge["Cobranza Meta"].apply(format_money)
                            df_merge["Cobranza Realizada"] = df_merge["Cobranza Realizada"].apply(format_money)

                            st.write("#### Resumen Semanal")
                            st.dataframe(
                                df_merge[["Número de Semana", "Semana", "Cobranza Meta", "Cobranza Realizada", "Cumplimiento (%)"]],
                                use_container_width=True
                            )
                            
                            # Permitir al usuario seleccionar semana para ver detalle diario
                            if len(df_weeks) > 0:
                                week_num = st.number_input("Ingresa el número de semana para ver detalles diarios",
                                                           min_value=1, max_value=len(df_weeks),
                                                           step=1, value=1, key="week_num_detalle")
                                sel_week = df_weeks.loc[df_weeks["Número de Semana"] == week_num, "Semana"]
                                if not sel_week.empty:
                                    sel_week = sel_week.iloc[0]
                                    df_detail = df_cob_prom[df_cob_prom["Semana"] == sel_week].copy()
                                    if not df_detail.empty:
                                        df_detail["Día"] = df_detail["Fecha Transacción"].dt.day_name()
                                        daily = df_detail.groupby("Día")["Depósito"].sum().reset_index()
                                        daily["Depósito"] = daily["Depósito"].apply(format_money)
                                        st.write(f"#### Detalle Diario para la semana {sel_week}")
                                        st.dataframe(daily, use_container_width=True)
                                    else:
                                        st.write("No hay datos de cobranza para la semana seleccionada.")
                        else:
                            st.write("No hay metas o cobranzas registrados para este promotor.")
            else:
                st.write("No hay promotores para mostrar. Revisa tu archivo 'VasTu.xlsx' y Metas/Control.")

        # --------------------------------------------------------------------------------
        # --- 6. Pestaña: Por Localidad ---
        with tabs[6]:
            st.header("Promotores Por Localidad")
            st.markdown("""
            Selecciona un **Estado** y un **Municipio** (o 'Todos') para filtrar la cobranza y ver
            el cumplimiento total.
            """)

            all_estados = df_cobranza["Estado"].dropna().unique()
            if len(all_estados) == 0:
                st.write("No se encontraron datos de Estado/Municipio en la cobranza.")
            else:
                selected_estado = st.selectbox("Seleccione un Estado", sorted(all_estados))
                all_municipios = df_cobranza.loc[df_cobranza["Estado"] == selected_estado, "Municipio"].dropna().unique()
                
                municipio_list = ["Todos"] + sorted(all_municipios)
                selected_municipio = st.selectbox("Seleccione un Municipio", municipio_list)
                
                if selected_municipio == "Todos":
                    df_local = df_cobranza[df_cobranza["Estado"] == selected_estado].copy()
                else:
                    df_local = df_cobranza[
                        (df_cobranza["Estado"] == selected_estado) &
                        (df_cobranza["Municipio"] == selected_municipio)
                    ].copy()
                
                if df_local.empty:
                    st.write("No hay registros de cobranza en la localidad seleccionada.")
                else:
                    df_local_group = df_local.groupby("Nombre Promotor", as_index=False)["Depósito"].sum()
                    df_local_group.rename(columns={"Depósito": "Total Cobranza"}, inplace=True)
                    
                    df_control["Nombre_upper"] = df_control["Nombre"].str.upper()
                    df_local_merge = pd.merge(
                        df_local_group,
                        df_control,
                        left_on="Nombre Promotor",
                        right_on="Nombre_upper",
                        how="left"
                    )
                    
                    df_metas_agg = df_metas_summary.groupby("Promotor")["Meta"].sum().reset_index()
                    df_metas_agg.rename(columns={"Meta": "Total Metas", "Promotor": "N"}, inplace=True)
                    
                    df_local_merge = pd.merge(df_local_merge, df_metas_agg, on="N", how="left").fillna({"Total Metas": 0})
                    df_local_merge["Diferencia"] = df_local_merge["Total Cobranza"] - df_local_merge["Total Metas"]
                    df_local_merge["Cumplimiento (%)"] = df_local_merge.apply(
                        lambda row: round((row["Total Cobranza"] / row["Total Metas"] * 100), 2)
                        if row["Total Metas"] > 0 else 0,
                        axis=1
                    )
                    
                    df_local_merge["N_prom_numeric"] = pd.to_numeric(
                        df_local_merge["N"].astype(str).str.extract(r"(\d+)")[0],
                        errors="coerce"
                    ).fillna(9999).astype(int)
                    df_local_merge.sort_values(by="N_prom_numeric", inplace=True)
                    df_local_merge.drop(columns=["N_prom_numeric", "Nombre_upper"], inplace=True, errors="ignore")
                    
                    df_local_merge_display = df_local_merge[[
                        "N", "Nombre", "Antigüedad (meses)", "Total Metas",
                        "Total Cobranza", "Diferencia", "Cumplimiento (%)"
                    ]].copy()
                    
                    df_local_merge_display["Total Metas"] = df_local_merge_display["Total Metas"].apply(format_money)
                    df_local_merge_display["Total Cobranza"] = df_local_merge_display["Total Cobranza"].apply(format_money)
                    df_local_merge_display["Diferencia"] = df_local_merge_display["Diferencia"].apply(format_money)
                    df_local_merge_display["Antigüedad (meses)"] = df_local_merge_display["Antigüedad (meses)"].round(2)
                    
                    if selected_municipio == "Todos":
                        st.markdown(f"### Lista de Promotores en el Estado: {selected_estado}")
                    else:
                        st.markdown(f"### Lista de Promotores en {selected_municipio}, {selected_estado}")
                    
                    st.dataframe(df_local_merge_display, use_container_width=True)
                    
                    total_metas_local = df_local_merge["Total Metas"].sum()
                    total_cob_local = df_local_merge["Total Cobranza"].sum()
                    cumplimiento_local = round((total_cob_local / total_metas_local * 100), 2) if total_metas_local > 0 else 0
                    diferencia_local = total_cob_local - total_metas_local
                    
                    st.markdown("### Datos Globales de la Localidad Seleccionada")
                    st.markdown(f"- **Total Metas (conjunto):** {format_money(total_metas_local)}")
                    st.markdown(f"- **Total Cobranza (conjunto):** {format_money(total_cob_local)}")
                    st.markdown(f"- **Diferencia (conjunto):** {format_money(diferencia_local)}")
                    st.markdown(f"- **Cumplimiento (%) (conjunto):** {cumplimiento_local}%")

        # --------------------------------------------------------------------------------
        # --- 7. Pestaña: Colocación de Créditos ---
        with tabs[7]:
            st.header("Colocación de Créditos (Venta, Flujo y Descuentos por Renovación)")
            
            if df_col_merge.empty:
                st.write("No se han encontrado datos de colocaciones. Por favor, sube el archivo correspondiente.")
            else:
                # Entrada para buscar promotor
                search_term = st.text_input("Buscar promotor", key="busqueda_promotor_colocacion")
                if search_term:
                    filtered_promoters = df_control[df_control["Nombre"].str.contains(search_term, case=False, na=False)]
                else:
                    filtered_promoters = df_control.copy()
                    
                promoter_names = filtered_promoters["Nombre"].tolist()
                if len(promoter_names) == 0:
                    st.error("No se encontraron promotores con ese criterio.")
                else:
                    selected_promoter = st.selectbox("Selecciona el promotor", promoter_names, key="select_promotor_colocacion")
                    df_match = df_control[df_control["Nombre"] == selected_promoter]
                    if df_match.empty:
                        st.error("Promotor no encontrado. Revisa el nombre seleccionado.")
                    else:
                        promotor_sel = df_match["N"].iloc[0]
                        nombre_prom = df_match["Nombre"].iloc[0]
                        antiguedad_prom = df_match["Antigüedad (meses)"].iloc[0]
                        st.markdown(f"**Promotor:** {nombre_prom}  \n"
                                    f"**Antigüedad (meses):** {antiguedad_prom}")
                        
                        df_sel = df_col_merge[df_col_merge["N"] == promotor_sel].copy()
                        
                        if df_sel.empty:
                            st.write("No se encontraron registros de colocación para este promotor.")
                        else:
                            # Renombramos la columna para el merge con descuentos
                            df_sel.rename(columns={"Nombre promotor": "Promotor_upper"}, inplace=True)
                            df_merged = pd.merge(
                                df_sel,
                                df_desc_agg,
                                left_on=["Promotor_upper", "Semana"],
                                right_on=["Promotor", "Semana"],
                                how="left"
                            )
                            df_merged["Descuento_Renovacion"] = df_merged["Descuento_Renovacion"].fillna(0)
                            df_agr = df_merged.groupby("Semana", as_index=False).agg({
                                "Creditos_Colocados": "sum",
                                "Venta": "sum",
                                "Descuento_Renovacion": "sum"
                            })
                            df_agr["Flujo"] = df_agr["Venta"] * 0.9
                            df_agr["Flujo F."] = df_agr["Flujo"] - df_agr["Descuento_Renovacion"]
                            df_agr = df_agr.sort_values(
                                by="Semana",
                                key=lambda col: col.apply(lambda p: p.start_time)
                            )
                            df_agr.rename(columns={"Descuento_Renovacion": "Descuento x Renovación"}, inplace=True)
                            
                            df_agr["Venta"] = df_agr["Venta"].apply(format_money)
                            df_agr["Flujo"] = df_agr["Flujo"].apply(format_money)
                            df_agr["Descuento x Renovación"] = df_agr["Descuento x Renovación"].apply(format_money)
                            df_agr["Flujo F."] = df_agr["Flujo F."].apply(format_money)
                            
                            st.markdown("### Resumen de Colocaciones")
                            st.dataframe(
                                df_agr[[
                                    "Semana",
                                    "Creditos_Colocados",
                                    "Venta",
                                    "Flujo",
                                    "Descuento x Renovación",
                                    "Flujo F."
                                ]],
                                use_container_width=True
                            )

# --------------------------------------------------------------------
#                             EJECUCIÓN
# --------------------------------------------------------------------
if __name__ == "__main__":
    main()
