f = r"e:\linux\trae_project\antibody_map01\backend\app\services\map_service.py"
c = open(f, encoding="utf-8").read()
print("lines:", len(c.splitlines()))
print("has seroprevalence filter:", 'data_type == "seroprevalence"' in c)
print("has valid_dps:", "valid_dps" in c)
