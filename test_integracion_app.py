import unittest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from pandas.testing import assert_frame_equal, assert_series_equal
from io import BytesIO

# Assuming integracion_app3.8.py is in the same directory or accessible in PYTHONPATH
import integracion_app3_8 as app  # Use an alias to avoid name conflicts

class TestIntegracionApp(unittest.TestCase):

    def assertDataFramesEqual(self, df1, df2, msg=None, check_dtype=True):
        """Helper to compare DataFrames, ignoring index by default."""
        df1_reset = df1.reset_index(drop=True)
        df2_reset = df2.reset_index(drop=True)
        try:
            assert_frame_equal(df1_reset, df2_reset, check_dtype=check_dtype)
        except AssertionError as e:
            raise self.failureException(msg) from e

    # 1. Test convert_number
    def test_convert_number(self):
        self.assertEqual(app.convert_number("1234.56"), 1234.56)
        self.assertEqual(app.convert_number("1,234.56"), 1234.56)
        self.assertEqual(app.convert_number("1.234,56"), 1234.56) # European format
        self.assertEqual(app.convert_number("1,234"), 1234.0)
        self.assertEqual(app.convert_number(123), 123.0)
        self.assertTrue(np.isnan(app.convert_number("abc")))
        self.assertTrue(np.isnan(app.convert_number(np.nan)))
        self.assertEqual(app.convert_number("  123.45  "), 123.45)

    # 2. Test normalize_name
    def test_normalize_name(self):
        self.assertEqual(app.normalize_name("José Pérez"), "JOSE PEREZ")
        self.assertEqual(app.normalize_name("  María  López  "), "MARIA LOPEZ")
        self.assertEqual(app.normalize_name("João Silva"), "JOAO SILVA")
        self.assertEqual(app.normalize_name("Strauß"), "STRAUSS") # ß to SS (common normalization)

    # 3. Test fuzzy_map
    def test_fuzzy_map(self):
        choices = ["José Pérez", "Maria Lopez", "Juan Garcia"]
        self.assertEqual(app.fuzzy_map("Jose Perez", choices, cutoff=0.8), "José Pérez")
        self.assertEqual(app.fuzzy_map("Jose Perez", choices, cutoff=0.95), None) # Higher cutoff fails
        self.assertEqual(app.fuzzy_map("Pedro", choices, cutoff=0.7), None)
        self.assertEqual(app.fuzzy_map("Maria L.", choices, cutoff=0.7), "Maria Lopez")
        self.assertEqual(app.fuzzy_map("Maria L.", [], cutoff=0.7), None) # Empty choices

    # 4. Test load_data_control
    @patch('pandas.read_excel')
    @patch('pandas.ExcelFile')
    def test_load_data_control(self, mock_excel_file, mock_read_excel):
        # Mocking pd.read_excel for the 'Control' sheet
        control_data = {
            "N": ["P1", "P2"],
            "Nombre": ["Promotor Uno", " Promotor Dos "],
            "Antigüedad (meses)": [12.345, 24]
        }
        df_control_mock = pd.DataFrame(control_data)
        
        # Mocking pd.ExcelFile and its sheets for metas
        mock_xls_instance = MagicMock()
        mock_xls_instance.sheet_names = ["Control", "P1", "P2", "P3_bad_format"]
        
        meta_p1_data = {"Unnamed: 0": [0,1], "Fecha": ["2023-01-02", "2023-01-09"], "Meta": [1000, 1100]}
        df_meta_p1_mock = pd.DataFrame(meta_p1_data)
        
        meta_p2_data = {"Unnamed: 0": [0], "Fecha": ["2023-01-03"], "Meta": [2000]}
        df_meta_p2_mock = pd.DataFrame(meta_p2_data)

        meta_p3_bad_data = {"Fecha": ["2023-01-03"], "Meta": [2000]} # Missing one column
        df_meta_p3_bad_mock = pd.DataFrame(meta_p3_bad_data)

        # Configure side_effect for pd.read_excel
        # The first call is for 'Control', then for each sheet in sheet_names
        def read_excel_side_effect(file, sheet_name=None, header=None, **kwargs):
            if sheet_name == "Control":
                return df_control_mock.copy()
            elif sheet_name == "P1":
                return df_meta_p1_mock.copy()
            elif sheet_name == "P2":
                return df_meta_p2_mock.copy()
            elif sheet_name == "P3_bad_format":
                 return df_meta_p3_bad_mock.copy()
            return pd.DataFrame()

        mock_read_excel.side_effect = read_excel_side_effect
        mock_excel_file.return_value = mock_xls_instance

        df_control, promotores_dict, df_metas_summary = app.load_data_control("dummy_vas_file.xlsx")

        # Test "Nombre_upper"
        self.assertTrue("Nombre_upper" in df_control.columns)
        self.assertEqual(df_control["Nombre_upper"].iloc[0], "PROMOTOR UNO")
        self.assertEqual(df_control["Nombre_upper"].iloc[1], "PROMOTOR DOS")
        self.assertEqual(df_control["Antigüedad (meses)"].iloc[0], 12.35) # Rounded

        # Test promotores_dict
        self.assertEqual(promotores_dict, {"P1": "Promotor Uno", "P2": "Promotor Dos"})

        # Test df_metas_summary
        self.assertEqual(len(df_metas_summary), 3) # 2 for P1, 1 for P2
        self.assertTrue("Semana" in df_metas_summary.columns)
        # Example check for one row
        p1_meta_week1 = df_metas_summary[(df_metas_summary["Promotor"] == "P1") & (df_metas_summary["Meta"] == 1000)]
        self.assertEqual(len(p1_meta_week1), 1)
        self.assertEqual(p1_meta_week1["Semana"].iloc[0], pd.Period("2023-01-02", freq="W-FRI"))
        
        # P3_bad_format sheet should be skipped (check st.warning was called - harder to test directly without capturing stdout/stderr or mocking st)


    # 5. Test load_data_cobranza
    @patch('pandas.read_excel')
    def test_load_data_cobranza(self, mock_read_excel):
        cobranza_data = {
            "Nombre Promotor": ["Ana", "Luis", "Ana"],
            "Fecha transacción": ["2023-01-02 10:00:00", "2023-01-08 12:00:00", "2023-01-15 15:00:00"], # Sat, Sun, Sun
            "Depósito": ["1,000.50", "500", "invalid"],
            "Estado": ["X", "Y", "Z"], "Municipio": ["A", "B", "C"], "Contrato": [1,2,3]
        }
        df_cobranza_mock = pd.DataFrame(cobranza_data)
        mock_read_excel.return_value = df_cobranza_mock

        df_result = app.load_data_cobranza("dummy_cob_file.xlsx")
        
        self.assertEqual(len(df_result), 2) # 1 row dropped due to 'invalid' Depósito -> NaN
        self.assertTrue("Fecha Transacción" in df_result.columns) # Renamed
        self.assertEqual(df_result["Depósito"].iloc[0], 1000.50)
        self.assertEqual(df_result["Depósito"].iloc[1], 500.00)
        
        # Test Semana (2023-01-02 is Sat, week ends Fri 2022-12-30 or Fri 2023-01-06)
        # Monday of that week is 2022-12-27. Friday is 2022-12-30.
        # Saturday 2023-01-02 is day 5. For W-FRI, it belongs to week ending 2023-01-06
        self.assertEqual(df_result["Semana"].iloc[0], pd.Period("2023-01-02", freq="W-FRI")) # Week of Sat 2023-01-02 ends Fri 2023-01-06
        self.assertEqual(df_result["Semana"].iloc[1], pd.Period("2023-01-08", freq="W-FRI")) # Week of Sun 2023-01-08 ends Fri 2023-01-13

        # Test Día_num (Sat=1, Sun=2, ..., Fri=7)
        # 2023-01-02 is a Monday in pandas dayofweek (0), but context seems to be Sat-Fri week
        # Formula: ((dayofweek - 5) % 7) + 1
        # Mon (0) -> ((0-5)%7)+1 = (-5%7)+1 = 2+1 = 3 (if Sat is 1)
        # Sat (5) -> ((5-5)%7)+1 = 0+1 = 1
        # Sun (6) -> ((6-5)%7)+1 = 1+1 = 2
        # Assuming dayofweek: Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
        # 2023-01-02 is Mon -> df_result["Fecha Transacción"].dt.dayofweek is 0. ((0 - 5) % 7) + 1 = (-5 % 7) + 1 = 2 + 1 = 3.
        # 2023-01-08 is Sun -> df_result["Fecha Transacción"].dt.dayofweek is 6. ((6 - 5) % 7) + 1 = (1 % 7) + 1 = 1 + 1 = 2.
        self.assertEqual(df_result["Día_num"].iloc[0], 3) # Monday
        self.assertEqual(df_result["Día_num"].iloc[1], 2) # Sunday

    # 6. Test load_data_colocaciones
    @patch('pandas.read_excel')
    def test_load_data_colocaciones(self, mock_read_excel):
        coloc_data = {
            "Nombre promotor": ["P1", "P2", "P1"],
            "Fecha desembolso": ["2023-01-02", "2023-01-10", "2023-01-02"],
            "Monto desembolsado": ["1,500.00", "2,000", "100"],
            "Nombre del cliente": ["Cliente A", "Cliente B", "Cliente C"],
            "Contrato": ["C1", "C2", "C3"],
            "Cuota total": ["150.50", "200", "10.0"],
            "Fecha primer pago": ["2023-01-16", "2023-01-24", "2023-01-16"]
        }
        df_coloc_mock = pd.DataFrame(coloc_data)
        mock_read_excel.return_value = df_coloc_mock

        df_agg, df_detail = app.load_data_colocaciones("dummy_col_file.xlsx")

        # Test df_detail
        self.assertEqual(len(df_detail), 3)
        self.assertEqual(df_detail["Monto desembolsado"].iloc[0], 1500.0)
        self.assertEqual(df_detail["Cuota total"].iloc[1], 200.0)
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(df_detail["Fecha desembolso"]))

        # Test df_agg
        self.assertEqual(len(df_agg), 2) # P1 has two entries for same week, P2 one
        p1_agg = df_agg[df_agg["Nombre promotor"] == "P1"].iloc[0]
        self.assertEqual(p1_agg["Creditos_Colocados"], 2)
        self.assertEqual(p1_agg["Venta"], 1600.0) # 1500 + 100
        self.assertEqual(p1_agg["Semana"], pd.Period("2023-01-02", freq="W-FRI"))

        # Test missing columns
        df_missing_cols_mock = df_coloc_mock.drop(columns=["Monto desembolsado"])
        mock_read_excel.return_value = df_missing_cols_mock
        df_agg_miss, df_detail_miss = app.load_data_colocaciones("dummy_col_file.xlsx")
        self.assertTrue(df_agg_miss.empty) # Aggregation should fail or be empty
        self.assertTrue(df_detail_miss.empty) # Detail should also be empty due to missing required col

    # 7. Test load_data_descuentos
    @patch('pandas.read_excel')
    def test_load_data_descuentos(self, mock_read_excel):
        desc_data = {
            "Promotor": ["Promotor Uno", "Promotor Dos", "Promotor Tres", "Promotor Uno"],
            "Fecha Ministración": ["2023-01-05", "2023-01-12", "2023-01-05", "2023-01-05"],
            "Descuento Renovación": ["10.0", "0", "20.50", "-5.0"] # 0 and negative should be filtered
        }
        df_desc_mock = pd.DataFrame(desc_data)
        mock_read_excel.return_value = df_desc_mock

        control_data = {
            "N": ["P1", "P2", "P4"],
            "Nombre": ["Promotor Uno", "Promotor Dos", "Promotor Cuatro"],
            "Nombre_upper": ["PROMOTOR UNO", "PROMOTOR DOS", "PROMOTOR CUATRO"],
            "Antigüedad (meses)": [1,2,3]
        }
        df_control_mock = pd.DataFrame(control_data)

        df_result = app.load_data_descuentos("dummy_desc_file.xlsx", df_control_mock)
        
        self.assertEqual(len(df_result), 1) # Only "Promotor Uno" and "Promotor Tres" have positive discounts. "Promotor Tres" not in control.
                                            # "Promotor Uno" has one entry.
        self.assertEqual(df_result["N"].iloc[0], "P1")
        self.assertEqual(df_result["Descuento_Renovacion"].iloc[0], 10.0)
        self.assertEqual(df_result["Semana"].iloc[0], pd.Period("2023-01-05", freq="W-FRI"))
        
        # Test with fuzzy match needed
        desc_data_fuzzy = {
            "Promotor": ["Promotor Unno", "PROMOTOR DOS"], # "Promotor Unno" needs fuzzy
            "Fecha Ministración": ["2023-01-05", "2023-01-12"],
            "Descuento Renovación": ["15.0", "25.0"]
        }
        df_desc_fuzzy_mock = pd.DataFrame(desc_data_fuzzy)
        mock_read_excel.return_value = df_desc_fuzzy_mock
        df_result_fuzzy = app.load_data_descuentos("dummy_desc_file.xlsx", df_control_mock)
        self.assertEqual(len(df_result_fuzzy), 2)
        self.assertTrue("P1" in df_result_fuzzy["N"].values)
        self.assertTrue("P2" in df_result_fuzzy["N"].values)


    # 8. Test load_data_pagos
    @patch('pandas.read_excel')
    def test_load_data_pagos(self, mock_read_excel):
        pagos_data = {
            "PROMOTOR": ["P1", "P2", "P3"],
            "SALDO": ["1,000.00", "2000", "invalid_saldo"],
            "PS*": ["100", "200", "50"],
            "MULTAS": ["10.50", "0", "5.0"], # SV
            "VENCI*": ["2023-01-31", "2023-02-15", "2023-03-01"]
        }
        df_pagos_mock = pd.DataFrame(pagos_data)
        mock_read_excel.return_value = df_pagos_mock

        df_result = app.load_data_pagos("dummy_pagos_file.xlsx")
        
        self.assertEqual(len(df_result), 2) # Row with "invalid_saldo" should be dropped
        self.assertTrue("PS" in df_result.columns and "PS*" not in df_result.columns)
        self.assertTrue("SV" in df_result.columns and "MULTAS" not in df_result.columns)
        self.assertTrue("VENCI" in df_result.columns and "VENCI*" not in df_result.columns)
        
        self.assertEqual(df_result["SALDO"].iloc[0], 1000.0)
        self.assertEqual(df_result["PS"].iloc[1], 200.0)
        self.assertEqual(df_result["SV"].iloc[0], 10.50)
        self.assertEqual(df_result["VENCI"].iloc[0], pd.Timestamp("2023-01-31"))
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(df_result["VENCI"]))
        self.assertTrue("N" in df_result.columns) # N column should be initialized

if __name__ == '__main__':
    # Mock streamlit functions globally for testing if they are called directly
    # This is a simple mock; for more complex interactions, a more sophisticated setup might be needed.
    app.st = MagicMock()
    unittest.main(argv=['first-arg-is-ignored'], exit=False)
