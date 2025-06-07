# AppDaemon app to fully handle Home Assistant alarm logic in Python
import appdaemon.plugins.hass.hassapi as hass

class AlarmHandler(hass.Hass):

    def initialize(self):
        self.log(">>> AlarmHandler initialize started <<<", level="WARNING")
        self.listen_state(self.motion_triggered, "binary_sensor.pir_sensor_porch", new="on")
        self.listen_event(self.send_alert, "alarm_triggered")
        self.listen_state(self.toggle_off_reset, "input_boolean.alarm_toggle", new="off")
        self.listen_event(self.auto_reset, "timer.finished", entity_id="timer.alarm_reset")

    def motion_triggered(self, entity, attribute, old, new, kwargs):
        if self.get_state("input_boolean.alarm_toggle") != "on":
            return

        name = self.friendly_name(entity) or entity
        area = self.area_name(entity) or "Unknown"

        self.log(f"Motion detected from {entity}, name: {name}, area: {area}")
        self.fire_event("alarm_triggered", name=name, area=area)

        if self.get_state("input_boolean.alarm_level") == "off":
            self.turn_on("input_boolean.alarm_level")

        delay = int(float(self.get_state("input_number.alarm_reset_delay")))
        self.call_service("timer/start", entity_id="timer.alarm_reset", duration=delay)

    def send_alert(self, event_name, data, kwargs):
        name = data.get("name", "unknown")
        area = data.get("area", "unknown")

        message = f"!ON! Motion detected in area {area} ({name})"
        self.call_service("telegram_bot/send_message", title="*ALARM* (SALE)", message=message)

    def auto_reset(self, event_name, data, kwargs):
        if self.get_state("input_boolean.alarm_level") == "on":
            self.log("Auto-resetting alarm")
            self.turn_off("input_boolean.alarm_level")
            message = f"!off! Alarm has been reset after time-out"
            self.call_service("telegram_bot/send_message", title="*ALARM* (SALE)", message=message)

    def toggle_off_reset(self, entity, attribute, old, new, kwargs):
        self.log("Alarm mode toggled off, resetting...")
        self.turn_off("input_boolean.alarm_level")
        self.call_service("timer/cancel", entity_id="timer.alarm_reset")
