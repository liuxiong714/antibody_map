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

    # ── 回归测试：简称模糊匹配不得误伤城市名 ──
    def test_city_name_not_confused_with_abbreviation(self):
        """"南京"含"京"不得返回"北京"——简称模糊匹配 bug 回归"""
        assert normalize_province("南京") == "南京"
        assert normalize_province("广州") == "广州"
        assert normalize_province("哈尔滨") == "哈尔滨"
        assert normalize_province("西宁") == "西宁"
        assert normalize_province("南宁") == "南宁"
        assert normalize_province("银川") == "银川"
        assert normalize_province("贵阳") == "贵阳"
        assert normalize_province("乌鲁木齐") == "乌鲁木齐"
        assert normalize_province("成都") == "成都"
        assert normalize_province("兰州") == "兰州"
        assert normalize_province("沈阳") == "沈阳"
        assert normalize_province("长春") == "长春"
        assert normalize_province("福州") == "福州"
        assert normalize_province("南昌") == "南昌"
        assert normalize_province("长沙") == "长沙"
        assert normalize_province("武汉") == "武汉"
        assert normalize_province("西安") == "西安"
        assert normalize_province("石家庄") == "石家庄"
        assert normalize_province("合肥") == "合肥"
        assert normalize_province("太原") == "太原"
        assert normalize_province("呼和浩特") == "呼和浩特"
        assert normalize_province("海口") == "海口"
        assert normalize_province("昆明") == "昆明"
        assert normalize_province("拉萨") == "拉萨"
        assert normalize_province("济南") == "济南"
        assert normalize_province("青岛") == "青岛"
        assert normalize_province("大连") == "大连"
        assert normalize_province("厦门") == "厦门"
        assert normalize_province("宁波") == "宁波"
        assert normalize_province("苏州") == "苏州"
        assert normalize_province("无锡") == "无锡"
        assert normalize_province("佛山") == "佛山"
        assert normalize_province("东莞") == "东莞"

    def test_city_with_shi_suffix(self):
        """以"市"结尾的输入也不参与简称模糊匹配"""
        assert normalize_province("南京市") == "南京市"
        assert normalize_province("广州市") == "广州市"
        assert normalize_province("哈尔滨市") == "哈尔滨市"
        assert normalize_province("西宁市") == "西宁市"

    def test_abbreviation_still_works(self):
        """单字简称仍然正常工作"""
        assert normalize_province("京") == "北京"
        assert normalize_province("沪") == "上海"
        assert normalize_province("粤") == "广东"
        assert normalize_province("黑") == "黑龙江"
        assert normalize_province("宁") == "宁夏"
        assert normalize_province("川") == "四川"
        assert normalize_province("贵") == "贵州"
        assert normalize_province("新") == "新疆"