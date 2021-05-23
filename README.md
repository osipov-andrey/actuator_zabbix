# Zabbix actuator

Actuator for communication Zabbix and [Control Bot](https://github.com/osipov-andrey/control_bot).


## Run
 In _zactuator/zabbix_client/feedback_templates_ directory:
 
 > cp host_info.json.template host_info.json
 > 
 > cp hot_keys.json.template hot_keys.json
 
 Describe in these two files the required hot buttons 
 (for graph objects, graphs of items and items values) and for hosts. See sample.
 
Next:

 > pip install -r requirements.txt
 >
 > cp zactuator/config.yaml.template zactuator/config.yaml 
 >
 >  _# fill config_
 > 
 > python -m zactuator
