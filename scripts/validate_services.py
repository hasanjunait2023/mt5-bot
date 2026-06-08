import yaml
d = yaml.safe_load(open("/home/trader/mt5-bot/configs/services.yaml"))
s = d["services"]
dis = [x["id"] for x in s if x.get("enabled", True) is False]
en = [x["id"] for x in s if x.get("enabled", True) is not False]
print("YAML_OK  total", len(s))
print("DISABLED", dis)
print("ENABLED ", len(en), en)
