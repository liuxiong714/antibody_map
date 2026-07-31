import pytest
from app.core.term_normalizer import (
    normalize_disease,
    normalize_method,
    normalize_antibody_type,
    normalize_province,
    DISEASE_MAP,
    METHOD_MAP,
    ANTIBODY_TYPE_MAP,
    PROVINCE_MAP,
)


class TestDiseaseNormalization:
    def test_exact_match(self):
        assert normalize_disease("麻疹") == "measles"
        assert normalize_disease("乙肝") == "hepatitis_b"
        assert normalize_disease("新冠") == "covid19"

    def test_aliases(self):
        assert normalize_disease("麻诊") == "measles"
        assert normalize_disease("Measles") == "measles"
        assert normalize_disease("乙型肝炎") == "hepatitis_b"
        assert normalize_disease("COVID-19") == "covid19"
        assert normalize_disease("SARS-CoV-2") == "covid19"

    def test_fuzzy_match(self):
        assert normalize_disease("流行性腮腺炎") == "mumps"
        assert normalize_disease("流行性感冒") == "influenza"

    def test_none_input(self):
        assert normalize_disease(None) is None

    def test_empty_input(self):
        assert normalize_disease("") is None

    def test_unknown_disease(self):
        assert normalize_disease("未知疾病") == "未知疾病"


class TestMethodNormalization:
    def test_exact_match(self):
        assert normalize_method("ELISA") == "ELISA"
        assert normalize_method("CLIA") == "CLIA"

    def test_aliases(self):
        assert normalize_method("酶联免疫吸附试验") == "ELISA"
        assert normalize_method("化学发光") == "CLIA"
        assert normalize_method("中和试验") == "NT"
        assert normalize_method("血凝抑制试验") == "HAI"

    def test_fuzzy_match(self):
        assert normalize_method("酶联免疫") == "ELISA"
        assert normalize_method("化学发光法") == "CLIA"

    def test_none_input(self):
        assert normalize_method(None) is None

    def test_unknown_method(self):
        assert normalize_method("未知方法") == "未知方法"


class TestAntibodyTypeNormalization:
    def test_exact_match(self):
        assert normalize_antibody_type("IgG") == "IgG"
        assert normalize_antibody_type("IgM") == "IgM"

    def test_aliases(self):
        assert normalize_antibody_type("IGG") == "IgG"
        assert normalize_antibody_type("Immunoglobulin G") == "IgG"
        assert normalize_antibody_type("中和抗体") == "Neutralizing Ab"
        assert normalize_antibody_type("总抗体") == "Total Ab"

    def test_none_input(self):
        assert normalize_antibody_type(None) is None


class TestProvinceNormalization:
    def test_exact_match(self):
        assert normalize_province("北京") == "北京"
        assert normalize_province("广东省") == "广东"

    def test_aliases(self):
        assert normalize_province("北京市") == "北京"
        assert normalize_province("Guangdong") == "广东"
        assert normalize_province("粤") == "广东"
        assert normalize_province("鲁") == "山东"

    def test_full_names(self):
        assert normalize_province("内蒙古自治区") == "内蒙古"
        assert normalize_province("广西壮族自治区") == "广西"
        assert normalize_province("香港特别行政区") == "香港"

    def test_none_input(self):
        assert normalize_province(None) is None

    def test_unknown_province(self):
        assert normalize_province("未知省份") == "未知省份"