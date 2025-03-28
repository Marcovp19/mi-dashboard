import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from datetime import datetime, timedelta, date

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

# --------------------------------------------------------------------
#                       CARGA DE DATOS (CACHED)
# --------------------------------------------------------------------
@st.cache_data
def load_data_control(vas_file):
    df_control = pd.read_excel(vas_file, sheet_name="Control")
    required_cols_control = ["N", "Nombre", "Antigüedad (meses)"]
    check_required_columns(df_control, required_cols_control, "df_control (sheet Control)")

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
    df_cobranza = pd.read_excel(
        cob_file,
        sheet_name="Recuperaciones",
        skiprows=2,
        usecols=["Nombre Promotor", "Fecha transacción", "Depósito", "Estado", "Municipio"]
    )
    required_cols_cob = ["Nombre Promotor", "Fecha transacción", "Depósito", "Estado", "Municipio"]
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
    if not col_file:
        return pd.DataFrame()

    df_col = pd.read_excel(
        col_file,
        sheet_name="Colocación",
        skiprows=4,
        usecols=["Nombre promotor", "Fecha desembolso", "Monto desembolsado"]
    )
    required_cols_col = ["Nombre promotor", "Fecha desembolso", "Monto desembolsado"]
    check_required_columns(df_col, required_cols_col, "df_col (sheet Colocación)")

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
    if not por_capturar_file:
        return pd.DataFrame()

    df_desc = pd.read_excel(
        por_capturar_file,
        skiprows=3,
        usecols=["Promotor", "Fecha Ministración", "Descuento Renovación"]
    )
    required_cols_desc = ["Promotor", "Fecha Ministración", "Descuento Renovación"]
    check_required_columns(df_desc, required_cols_desc, "df_desc (Por_capturar)")

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

        # Excluimos a promotores sin datos (antigüedad NaN y metas=0, cobranza=0)
        # Si quieres mostrar promotores sin antigüedad pero con datos, ajusta la condición
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
            df_col_agg = load_data_colocaciones(col_file)
            df_col_merge = merge_colocaciones(df_col_agg, df_control)
            df_desc_agg = load_data_descuentos(por_capturar_file)
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
            "Por Localidad",
            "Colocación de Créditos"
        ])

        # -----------------------------------------------------------
        ##################################
        # 0. Pestaña: Datos Globales
        ###################################
        with tabs[0]:
            st.header("Datos Globales de la Empresa")
            if df_metas_summary.empty or df_cobranza.empty:
                st.write("No hay datos suficientes para mostrar gráficas globales.")
            else:
                # Obtenemos todas las semanas que aparecen en Metas y en Cobranza
                weeks_meta = pd.Index(df_metas_summary["Semana"].unique())
                weeks_cob = pd.Index(df_cobranza["Semana"].unique())
                all_weeks = weeks_meta.union(weeks_cob)

                if len(all_weeks) == 0:
                    st.write("No se encontraron semanas disponibles.")
                else:
                    # Generamos etiquetas legibles para las semanas
                    sorted_weeks = sorted(all_weeks, key=lambda p: p.start_time)

                    def format_week_label(w):
                        return (w.start_time + pd.Timedelta(days=2)).strftime("%-d %b %Y")

                    week_mapping = {format_week_label(w): w for w in sorted_weeks}
                    week_labels = list(week_mapping.keys())

                    st.markdown("#### Selecciona dos semanas para comparar")
                    selected_week_1_label = st.selectbox("Semana 1", week_labels, index=0)

                    # En caso de que solo haya una semana, repetimos la misma
                    if len(week_labels) > 1:
                        selected_week_2_label = st.selectbox("Semana 2", week_labels, index=1)
                    else:
                        selected_week_2_label = selected_week_1_label

                    week_1 = week_mapping[selected_week_1_label]
                    week_2 = week_mapping[selected_week_2_label]

                    # -------------------------------------------------------
                    # 1) Cálculo de totales de Metas y Cobranzas en ambas semanas
                    # -------------------------------------------------------
                    total_meta_1 = df_metas_summary[df_metas_summary["Semana"] == week_1]["Meta"].sum()
                    total_cob_1 = df_cobranza[df_cobranza["Semana"] == week_1]["Depósito"].sum()

                    total_meta_2 = df_metas_summary[df_metas_summary["Semana"] == week_2]["Meta"].sum()
                    total_cob_2 = df_cobranza[df_cobranza["Semana"] == week_2]["Depósito"].sum()

                    cumplimiento_1 = round((total_cob_1 / total_meta_1 * 100), 2) if total_meta_1 > 0 else 0
                    cumplimiento_2 = round((total_cob_2 / total_meta_2 * 100), 2) if total_meta_2 > 0 else 0

                    # Métricas principales (Metas vs Cobranza vs %)
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Meta Semana 1", format_money(total_meta_1))
                    col2.metric("Cobranza Semana 1", format_money(total_cob_1))
                    col3.metric("% Cumplimiento S1", f"{cumplimiento_1}%")

                    col4, col5, col6 = st.columns(3)
                    col4.metric("Meta Semana 2", format_money(total_meta_2))
                    col5.metric("Cobranza Semana 2", format_money(total_cob_2))
                    col6.metric("% Cumplimiento S2", f"{cumplimiento_2}%")

                    # -------------------------------------------------------
                    # 2) Gráfica comparativa de Metas vs Cobranza
                    # -------------------------------------------------------
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

                    # -------------------------------------------------------
                    # 3) Gráfica de depósitos diarios (línea con puntos)
                    # -------------------------------------------------------
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

                    # -------------------------------------------------------
                    # 4) NUEVA Gráfica: Créditos colocados vs renovados
                    #    (comparando las 2 semanas seleccionadas)
                    # -------------------------------------------------------

                    # Variables por defecto en caso de que df_col_agg o df_desc_agg estén vacíos
                    week_1_credits_placed = 0
                    week_2_credits_placed = 0
                    week_1_credits_renewed = 0
                    week_2_credits_renewed = 0

                    if not df_col_agg.empty:
                        # Suma de créditos colocados en cada semana
                        week_1_credits_placed = df_col_agg[df_col_agg["Semana"] == week_1]["Creditos_Colocados"].sum()
                        week_2_credits_placed = df_col_agg[df_col_agg["Semana"] == week_2]["Creditos_Colocados"].sum()

                    if not por_capturar_file or df_desc_agg.empty:
                        # Si no hay archivo de descuentos o si df_desc_agg está vacío,
                        # asumimos 0 créditos renovados
                        pass
                    else:
                        # El dataframe df_desc_agg tiene la sumatoria de "Descuento_Renovacion" por (Promotor, Semana),
                        # pero NO el recuento de créditos renovados. Para obtener un aproximado,
                        # contamos cuántos promotores tuvieron descuento en esa semana (una fila = al menos un crédito renovado).
                        # Si necesitas el recuento exacto de créditos renovados, habría que cambiar la forma de agrupar en load_data_descuentos.
                        df_week_1 = df_desc_agg[df_desc_agg["Semana"] == week_1]
                        df_week_2 = df_desc_agg[df_desc_agg["Semana"] == week_2]
                        week_1_credits_renewed = len(df_week_1)  # nº promotor-semana con descuento > 0
                        week_2_credits_renewed = len(df_week_2)

                    # Construimos un DataFrame para la gráfica
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

                    # -------------------------------------------------------
                    # 5) Totales de Venta, Flujo, Descuentos y Flujo Final
                    #    (para cada semana)
                    # -------------------------------------------------------
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
                # EXCLUIR donde Total Metas=0 y Total Cobranza=0
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
        # 2. Pestaña: Ranking a la Fecha (Acumulado)
        # -----------------------------------------------------------
        with tabs[2]:
            st.header("Ranking de Promotores a la Fecha")
            st.markdown("Selecciona una semana para ver, acumulativamente hasta esa fecha, la suma de metas y cobranzas de cada promotor.")

            weeks_meta = pd.Index(df_metas_summary["Semana"].unique())
            weeks_cob = pd.Index(df_cobranza["Semana"].unique())
            all_weeks = weeks_meta.union(weeks_cob)

            if len(all_weeks)==0:
                st.write("No hay semanas en los datos.")
            else:
                sorted_weeks = sorted(all_weeks, key=lambda p: p.start_time)
                week_mapping = {
                    (w.start_time + pd.Timedelta(days=2)).strftime("%-d %b %Y"): w
                    for w in sorted_weeks
                }
                selected_week_label = st.selectbox(
                    "Selecciona una semana", 
                    list(week_mapping.keys()),
                    key="ranking_selectbox"
                )
                selected_week = week_mapping[selected_week_label]

                df_metas_acum = df_metas_summary[df_metas_summary["Semana"]<=selected_week]
                df_cob_acum = df_cobranza[df_cobranza["Semana"]<=selected_week]

                metas_group = df_metas_acum.groupby("Promotor")["Meta"].sum().reset_index()
                metas_group.rename(columns={"Meta":"Meta_Total"}, inplace=True)

                cob_group = df_cob_acum.groupby("Nombre Promotor")["Depósito"].sum().reset_index()
                cob_group.rename(columns={"Depósito":"Cobranza_Total"}, inplace=True)

                code_to_name = dict(zip(df_control["N"], df_control["Nombre"]))
                name_to_code = {v.upper(): k for k, v in code_to_name.items()}
                cob_group["Promotor"] = cob_group["Nombre Promotor"].map(name_to_code)

                ranking_df = pd.merge(metas_group, cob_group, on="Promotor", how="outer").fillna(0)
                ranking_df["N"] = ranking_df["Promotor"]
                ranking_df["Nombre"] = ranking_df["N"].map(code_to_name)

                ranking_df["Cumplimiento (%)"] = ranking_df.apply(
                    lambda row: round((row["Cobranza_Total"]/row["Meta_Total"]*100),2) if row["Meta_Total"]>0 else 0,
                    axis=1
                )
                ranking_df = ranking_df.sort_values(by="Cumplimiento (%)", ascending=False)

                # EXCLUIR donde Meta_Total=0 y Cobranza_Total=0
                ranking_df = ranking_df[~((ranking_df["Meta_Total"]==0) & (ranking_df["Cobranza_Total"]==0))]

                ranking_df["Meta_Total"] = ranking_df["Meta_Total"].apply(format_money)
                ranking_df["Cobranza_Total"] = ranking_df["Cobranza_Total"].apply(format_money)

                final_df = ranking_df[["N","Nombre","Meta_Total","Cobranza_Total","Cumplimiento (%)"]].copy()
                final_df.rename(columns={
                    "N":"numero",
                    "Nombre":"nombre promotor",
                    "Meta_Total":"meta total",
                    "Cobranza_Total":"cobranza total",
                    "Cumplimiento (%)":"cumplimiento %"
                }, inplace=True)

                styled_df = final_df.style.applymap(style_cumplimiento, subset=["cumplimiento %"])
                st.dataframe(styled_df, use_container_width=True)

        # -----------------------------------------------------------
        #############################################
        # Pestaña: Análisis de Cambio de Patrón de Pago
        #############################################
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
        # 4. Pestaña: Incumplimiento Semanal
        # (Con la lista adicional de "al corriente" en semanas anteriores)
        # -----------------------------------------------------------
        with tabs[4]:
            st.header("Incumplimiento por Semana")

            all_weeks = pd.Index(df_metas_summary["Semana"]).union(pd.Index(df_cobranza["Semana"]))
            sorted_weeks = sorted(all_weeks, key=lambda p: p.start_time)
            if len(sorted_weeks) == 0:
                st.write("No hay semanas disponibles.")
            else:
                week_mapping = {
                    (w.start_time + pd.Timedelta(days=2)).strftime("%-d %b %Y"): w
                    for w in sorted_weeks
                }
                selected_week_label = st.selectbox(
                    "Selecciona una semana",
                    list(week_mapping.keys()),
                    key="incumplimiento_selectbox"
                )
                selected_week = week_mapping[selected_week_label]

                # 1) Datos de la semana seleccionada
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

                incumplidos.rename(columns={"Meta": "MetaSemana", "Depósito": "CobranzaSemana"}, inplace=True)
                # Excluir aquellos con 0 en ambas si se desea
                incumplidos = incumplidos[~((incumplidos["MetaSemana"] == 0) & (incumplidos["CobranzaSemana"] == 0))]

                # Estadísticas globales
                num_incumplidores = incumplidos["Promotor"].nunique()
                total_meta_week = df_meta_sel["Meta"].sum()
                total_cob_week = df_cob_sel["Depósito"].sum() if not df_cob_sel.empty else 0
                porcentaje_cumpl = round((total_cob_week / total_meta_week * 100), 2) if total_meta_week > 0 else 0

                st.markdown(f"- **Número de promotores que incumplieron:** {num_incumplidores}")
                st.markdown(f"- **Total Metas (Semana):** {format_money(total_meta_week)}")
                st.markdown(f"- **Total Cobranza (Semana):** {format_money(total_cob_week)}")
                st.markdown(f"- **Cumplimiento (Semana):** {porcentaje_cumpl}%")

                st.markdown("### Incumplidos")
                st.dataframe(
                    incumplidos[["Fecha", "Promotor", "Nombre Promotor", "MetaSemana", "CobranzaSemana", "Cumplimiento (%)"]],
                    use_container_width=True
                )

                # 3) Quiénes de esos incumplidos van al corriente en semanas anteriores?
                prom_incumplidos_codes = incumplidos["Promotor"].unique().tolist()
                if len(prom_incumplidos_codes) == 0:
                    st.write("Ningún promotor incumplió en la semana seleccionada.")
                else:
                    # a) Filtramos metas anteriores
                    df_metas_anteriores = df_metas_summary[
                        (df_metas_summary["Semana"] < selected_week) &
                        (df_metas_summary["Promotor"].isin(prom_incumplidos_codes))
                    ].copy()

                    # b) Filtramos cobranza anterior
                    df_cob_anteriores = df_cobranza[
                        (df_cobranza["Semana"] < selected_week) &
                        (df_cobranza["Nombre Promotor"].isin(incumplidos["Nombre Promotor"].unique()))
                    ].copy()

                    # c) Sumamos metas y cobranza previas
                    meta_anteriores_agg = df_metas_anteriores.groupby("Promotor")["Meta"].sum().reset_index()
                    meta_anteriores_agg.rename(columns={"Meta": "MetaAcumuladaPrev"}, inplace=True)

                    cob_anteriores_agg = df_cob_anteriores.groupby("Nombre Promotor")["Depósito"].sum().reset_index()
                    cob_anteriores_agg.rename(columns={"Depósito": "CobranzaAcumuladaPrev"}, inplace=True)

                    code_to_name = dict(zip(df_control["N"], df_control["Nombre"]))
                    name_to_code = {v.upper(): k for k, v in code_to_name.items()}

                    cob_anteriores_agg["Promotor"] = cob_anteriores_agg["Nombre Promotor"].map(name_to_code)

                    df_corriente = pd.merge(meta_anteriores_agg, cob_anteriores_agg, on="Promotor", how="outer").fillna(0)
                    df_corriente["DiferenciaPrev"] = df_corriente["CobranzaAcumuladaPrev"] - df_corriente["MetaAcumuladaPrev"]

                    # Filtramos los que estén "al corriente" (DiferenciaPrev >= 0)
                    df_al_corriente = df_corriente[df_corriente["DiferenciaPrev"] >= 0].copy()
                    # De estos, solo nos interesan los que incumplieron en la semana actual
                    df_al_corriente_in_week = df_al_corriente[df_al_corriente["Promotor"].isin(prom_incumplidos_codes)]

                    if df_al_corriente_in_week.empty:
                        st.info("Ninguno de los incumplidos estaba adelantado en semanas anteriores.")
                    else:
                        df_al_corriente_in_week["Nombre"] = df_al_corriente_in_week["Promotor"].map(code_to_name)

                        df_al_corriente_in_week["MetaAcumuladaPrev"] = df_al_corriente_in_week["MetaAcumuladaPrev"].apply(format_money)
                        df_al_corriente_in_week["CobranzaAcumuladaPrev"] = df_al_corriente_in_week["CobranzaAcumuladaPrev"].apply(format_money)
                        df_al_corriente_in_week["DiferenciaPrev"] = df_al_corriente_in_week["DiferenciaPrev"].apply(format_money)

                        st.markdown("### Incumplidos que van al corriente (semanas anteriores)")
                        st.dataframe(
                            df_al_corriente_in_week[[
                                "Promotor", "Nombre", "MetaAcumuladaPrev", "CobranzaAcumuladaPrev", "DiferenciaPrev"
                            ]],
                            use_container_width=True
                        )

        # -----------------------------------------------------------
        # 5. Pestaña: Detalles del Promotor
        # -----------------------------------------------------------
        with tabs[5]:
            st.header("Detalles del Promotor")
            if df_promoters_summary.empty:
                st.write("No hay promotores para mostrar.")
            else:
                search_term = st.text_input("Buscar promotor (por nombre parcial)")
                if search_term:
                    filtered_promoters = df_control[df_control["Nombre"].str.contains(search_term, case=False, na=False)]
                else:
                    filtered_promoters = df_control

                if filtered_promoters.empty:
                    st.error("No se encontraron promotores con ese criterio.")
                else:
                    selected_promoter_name = st.selectbox("Selecciona el promotor", filtered_promoters["Nombre"].tolist())
                    df_match = df_control[df_control["Nombre"]==selected_promoter_name]
                    if df_match.empty:
                        st.error("Promotor no encontrado.")
                    else:
                        promotor_sel = df_match["N"].iloc[0]
                        nombre_promotor = df_match["Nombre"].iloc[0]
                        antiguedad_val = df_match["Antigüedad (meses)"].iloc[0]

                        df_cob_prom = df_cobranza[df_cobranza["Nombre Promotor"]==nombre_promotor.upper()].copy()
                        estados = df_cob_prom["Estado"].dropna().unique()
                        municipios = df_cob_prom["Municipio"].dropna().unique()
                        estado_str = ", ".join(estados) if len(estados)>0 else "No registrado"
                        municipio_str = ", ".join(municipios) if len(municipios)>0 else "No registrado"

                        df_meta_prom = df_metas_summary[df_metas_summary["Promotor"]==promotor_sel]
                        total_meta = df_meta_prom["Meta"].sum() if not df_meta_prom.empty else 0
                        total_cob = df_cob_prom["Depósito"].sum() if not df_cob_prom.empty else 0
                        diferencia = total_cob - total_meta

                        if total_meta==0 and total_cob==0:
                            st.warning("Este promotor no tiene datos de metas ni cobranzas.")
                        else:
                            st.markdown(f"**Número Promotor:** {promotor_sel}")
                            st.markdown(f"**Nombre Promotor:** {nombre_promotor}")
                            st.markdown(f"**Antigüedad (meses):** {antiguedad_val}")
                            st.markdown(f"**Estado(s):** {estado_str}")
                            st.markdown(f"**Municipio(s):** {municipio_str}")
                            st.markdown(f"**Meta Total:** {format_money(total_meta)}")
                            st.markdown(f"**Cobranza Total:** {format_money(total_cob)}")
                            st.markdown(f"**Diferencia Total:** {format_money(diferencia)}")

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
                                full_weeks = pd.period_range(start=start_week.start_time, end=end_week.end_time, freq="W-FRI")
                                df_weeks = pd.DataFrame({"Semana": full_weeks})

                                df_merge = pd.merge(df_weeks, df_meta_prom[["Semana","Meta"]], on="Semana", how="left")
                                df_merge = pd.merge(df_merge, df_cob_summary, on="Semana", how="left")
                                df_merge.rename(columns={"Meta":"Cobranza Meta","Depósito":"Cobranza Realizada"}, inplace=True)
                                df_merge[["Cobranza Meta","Cobranza Realizada"]] = df_merge[["Cobranza Meta","Cobranza Realizada"]].fillna(0)
                                df_merge["Cumplimiento (%)"] = df_merge.apply(
                                    lambda row: round((row["Cobranza Realizada"]/row["Cobranza Meta"]*100),2) if row["Cobranza Meta"]>0 else 0,
                                    axis=1
                                )
                                df_merge["Cobranza Meta"] = df_merge["Cobranza Meta"].apply(format_money)
                                df_merge["Cobranza Realizada"] = df_merge["Cobranza Realizada"].apply(format_money)

                                st.write("#### Resumen Semanal del Promotor")
                                # Ordenar cronológicamente
                                df_merge = df_merge.sort_values(
                                    by="Semana",
                                    key=lambda col: col.apply(lambda p: p.start_time if isinstance(p, pd.Period) else p)
                                )
                                st.dataframe(
                                    df_merge[["Semana","Cobranza Meta","Cobranza Realizada","Cumplimiento (%)"]],
                                    use_container_width=True
                                )

                                # Detalle diario
                                if len(df_merge)>0:
                                    st.markdown("##### Detalle Diario")
                                    n_weeks = list(range(1, len(df_merge)+1))
                                    df_merge["Nº Semana"] = n_weeks
                                    week_num_sel = st.number_input(
                                        "Ingresa Nº de Semana para ver detalle diario",
                                        min_value=1,
                                        max_value=len(df_merge),
                                        step=1,
                                        value=1
                                    )
                                    if week_num_sel<=len(df_merge):
                                        sel_week = df_merge.loc[df_merge["Nº Semana"]==week_num_sel,"Semana"].iloc[0]
                                        df_detail = df_cob_prom[df_cob_prom["Semana"]==sel_week].copy()
                                        if not df_detail.empty:
                                            df_detail["Día"] = df_detail["Fecha Transacción"].dt.day_name()
                                            daily = df_detail.groupby("Día")["Depósito"].sum().reset_index()
                                            daily["Depósito"] = daily["Depósito"].apply(format_money)
                                            st.write(f"#### Detalle Diario - Semana {sel_week}")
                                            st.dataframe(daily, use_container_width=True)
                                        else:
                                            st.write("No hay registros de cobranza para la semana seleccionada.")

        # -----------------------------------------------------------
        # 6. Pestaña: Por Localidad
        # -----------------------------------------------------------
        with tabs[6]:
            st.header("Promotores por Localidad")

            all_estados = df_cobranza["Estado"].dropna().unique()
            if len(all_estados)==0:
                st.write("No hay datos de Estado/Municipio.")
            else:
                estado_sel = st.selectbox("Estado", sorted(all_estados))
                muni_fil = df_cobranza[df_cobranza["Estado"]==estado_sel]["Municipio"].dropna().unique()
                municipio_list = ["Todos"] + sorted(muni_fil.tolist())
                municipio_sel = st.selectbox("Municipio", municipio_list)

                if municipio_sel=="Todos":
                    df_local = df_cobranza[df_cobranza["Estado"]==estado_sel].copy()
                else:
                    df_local = df_cobranza[
                        (df_cobranza["Estado"]==estado_sel) &
                        (df_cobranza["Municipio"]==municipio_sel)
                    ].copy()

                if df_local.empty:
                    st.write("No hay registros de cobranza en la localidad seleccionada.")
                else:
                    df_local_group = df_local.groupby("Nombre Promotor")["Depósito"].sum().reset_index()
                    df_local_group.rename(columns={"Depósito":"Total Cobranza"}, inplace=True)

                    df_control["Nombre_upper"] = df_control["Nombre"].str.upper()
                    df_local_merge = pd.merge(
                        df_local_group,
                        df_control,
                        left_on="Nombre Promotor",
                        right_on="Nombre_upper",
                        how="left"
                    )
                    df_metas_agg = df_metas_summary.groupby("Promotor")["Meta"].sum().reset_index()
                    df_metas_agg.rename(columns={"Meta":"Total Metas","Promotor":"N"}, inplace=True)

                    df_local_merge = pd.merge(df_local_merge, df_metas_agg, on="N", how="left").fillna({"Total Metas":0})
                    df_local_merge["Diferencia"] = df_local_merge["Total Cobranza"] - df_local_merge["Total Metas"]
                    df_local_merge["Cumplimiento (%)"] = df_local_merge.apply(
                        lambda row: round((row["Total Cobranza"]/row["Total Metas"]*100),2) if row["Total Metas"]>0 else 0,
                        axis=1
                    )
                    df_local_merge["N_prom_numeric"] = pd.to_numeric(
                        df_local_merge["N"].str.extract(r"(\d+)")[0],
                        errors="coerce"
                    ).fillna(9999).astype(int)
                    df_local_merge.sort_values(by="N_prom_numeric", inplace=True)
                    df_local_merge.drop(columns=["N_prom_numeric","Nombre_upper"], inplace=True, errors="ignore")

                    # EXCLUIR donde Total Metas=0 y Total Cobranza=0
                    df_local_merge = df_local_merge[~(
                        (df_local_merge["Total Metas"]==0) &
                        (df_local_merge["Total Cobranza"]==0)
                    )]

                    df_local_merge["Total Metas"] = df_local_merge["Total Metas"].apply(format_money)
                    df_local_merge["Total Cobranza"] = df_local_merge["Total Cobranza"].apply(format_money)
                    df_local_merge["Diferencia"] = df_local_merge["Diferencia"].apply(format_money)
                    df_local_merge["Antigüedad (meses)"] = df_local_merge["Antigüedad (meses)"].round(2)

                    if municipio_sel=="Todos":
                        st.markdown(f"### Lista de promotores en {estado_sel}")
                    else:
                        st.markdown(f"### Lista de promotores en {municipio_sel}, {estado_sel}")

                    st.dataframe(
                        df_local_merge[["N","Nombre","Antigüedad (meses)","Total Metas","Total Cobranza","Diferencia","Cumplimiento (%)"]],
                        use_container_width=True
                    )

                    def parse_money(x):
                        if isinstance(x, str):
                            return float(x.replace("$","").replace(",",""))
                        return 0
                    total_metas_local = df_local_merge["Total Metas"].apply(parse_money).sum()
                    total_cob_local = df_local_merge["Total Cobranza"].apply(parse_money).sum()
                    diferencia_local = total_cob_local - total_metas_local
                    cumplimiento_local = round((total_cob_local/total_metas_local*100),2) if total_metas_local>0 else 0

                    st.markdown("### Datos Globales de la Localidad")
                    st.markdown(f"- **Total Metas (conjunto):** {format_money(total_metas_local)}")
                    st.markdown(f"- **Total Cobranza (conjunto):** {format_money(total_cob_local)}")
                    st.markdown(f"- **Diferencia (conjunto):** {format_money(diferencia_local)}")
                    st.markdown(f"- **Cumplimiento (%) (conjunto):** {cumplimiento_local}%")

        # -----------------------------------------------------------
        # 7. Pestaña: Colocación de Créditos
        # (Mostrar todas las semanas, incluso sin colocaciones)
        # -----------------------------------------------------------
        with tabs[7]:
            st.header("Colocación de Créditos (Venta, Flujo y Descuentos)")
            if df_col_merge.empty:
                st.write("No se encontraron datos de colocaciones.")
            else:
                st.markdown("Selecciona un promotor para ver sus colocaciones por semana.")
                search_term = st.text_input("Buscar promotor por nombre", "")
                if search_term:
                    filtered_proms = df_control[df_control["Nombre"].str.contains(search_term, case=False, na=False)]
                else:
                    filtered_proms = df_control.copy()

                if filtered_proms.empty:
                    st.error("No se encontraron promotores con ese criterio.")
                else:
                    selected_prom = st.selectbox("Promotor", filtered_proms["Nombre"].tolist())
                    df_match = df_control[df_control["Nombre"]==selected_prom]
                    if df_match.empty:
                        st.error("Promotor no encontrado en df_control.")
                    else:
                        prom_sel = df_match["N"].iloc[0]
                        df_sel = df_col_merge[df_col_merge["N"]==prom_sel].copy()
                        if df_sel.empty:
                            st.write("No hay registros de colocación para este promotor.")
                        else:
                            df_sel.rename(columns={"Nombre promotor":"Promotor_upper"}, inplace=True)
                            if not df_desc_agg.empty:
                                df_merged = pd.merge(
                                    df_sel,
                                    df_desc_agg,
                                    left_on=["Promotor_upper","Semana"],
                                    right_on=["Promotor","Semana"],
                                    how="left"
                                )
                                df_merged["Descuento_Renovacion"] = df_merged["Descuento_Renovacion"].fillna(0)
                            else:
                                df_merged = df_sel.copy()
                                df_merged["Descuento_Renovacion"] = 0

                            df_agr = df_merged.groupby("Semana", as_index=False).agg({
                                "Creditos_Colocados":"sum",
                                "Venta":"sum",
                                "Descuento_Renovacion":"sum"
                            })
                            df_agr["Flujo"] = df_agr["Venta"]*0.9
                            df_agr["Flujo F."] = df_agr["Flujo"]-df_agr["Descuento_Renovacion"]

                            # Crear un rango completo de semanas, min->max
                            min_week = df_agr["Semana"].min()
                            max_week = df_agr["Semana"].max()

                            # Generar PeriodIndex
                            full_weeks = pd.period_range(
                                start=min_week.start_time,
                                end=max_week.end_time,
                                freq="W-FRI"
                            )
                            df_weeks = pd.DataFrame({"Semana": full_weeks})

                            # Merge con df_agr para mostrar semanas sin colocación
                            df_full = pd.merge(df_weeks, df_agr, on="Semana", how="left").fillna(0)

                            # Ordenar cronológicamente
                            df_full = df_full.sort_values(
                                by="Semana",
                                key=lambda col: col.apply(lambda p: p.start_time)
                            )

                            df_full.rename(columns={"Descuento_Renovacion":"Descuento x Renovación"}, inplace=True)
                            df_full["Venta"] = df_full["Venta"].apply(format_money)
                            df_full["Flujo"] = df_full["Flujo"].apply(format_money)
                            df_full["Descuento x Renovación"] = df_full["Descuento x Renovación"].apply(format_money)
                            df_full["Flujo F."] = df_full["Flujo F."].apply(format_money)

                            st.markdown(f"#### Colocaciones de {selected_prom}")
                            st.dataframe(
                                df_full[[
                                    "Semana","Creditos_Colocados","Venta","Flujo","Descuento x Renovación","Flujo F."
                                ]],
                                use_container_width=True
                            )
    else:
        st.info("Sube al menos el archivo de Metas/Control y el archivo de Cobranza para iniciar.")

if __name__ == "__main__":
    main()
