"""MQTT link (mosquitto on the Pi): status out on pet/status, commands in on pet/cmd/<name>.
Optional: without paho-mqtt or a broker the pet runs the same, just without the bus."""
import json
import logging

log = logging.getLogger("bus")


class Bus:
    def __init__(self, cfg, handler):
        self.client = None
        self.handler = handler            # handler(name, payload_dict)
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            log.info("paho-mqtt not installed: no MQTT")
            return
        try:
            c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pet")
        except AttributeError:            # paho 1.x
            c = mqtt.Client(client_id="pet")
        c.on_connect = lambda cl, *a: cl.subscribe("pet/cmd/#")
        c.on_message = self._message
        try:
            m = cfg.get("mqtt", {})
            c.connect_async(m.get("host", "localhost"), int(m.get("port", 1883)))
            c.loop_start()
            self.client = c
        except Exception as e:
            log.warning("MQTT unavailable: %s", e)

    def _message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload or b"{}")
        except ValueError:
            payload = {}
        self.handler(msg.topic.split("/", 2)[-1], payload)

    def publish(self, topic, data):
        if self.client:
            self.client.publish(topic, json.dumps(data), qos=0)
