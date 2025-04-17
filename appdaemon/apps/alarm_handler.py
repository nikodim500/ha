# AppDaemon app to replicate Home Assistant alarm logic
import appdaemon.plugins.hass.hassapi as hass

class AlarmHandler(hass.Hass):
    def initialize(self):
        self.listen_state(self.motion_triggered, "binary_sensor.pir_sensor_porch", new="on")
        self.listen_event(self.toggle_off_reset, "state_changed", entity_id="input_boolean.alarm_toggle")
        self.listen_event(self.auto_reset, "timer.finished", entity_id="timer.alarm_reset")

    def motion_triggered(self, entity, attribute, old, new, kwargs):
        if self.get_state("input_boolean.alarm_toggle") == "on":
            name = self.friendly_name(entity)
            area = self.area_name(entity)
            self.fire_event("alarm_triggered", name=name, area=area)

            if self.get_state("input_boolean.alarm_level") == "off":
                self.turn_on("input_boolean.alarm_level")

            delay = int(float(self.get_state("input_number.alarm_reset_delay")))
            self.call_service("timer/start", entity_id="timer.alarm_reset", duration=delay)

    def toggle_off_reset(self, event_name, data, kwargs):
        if data.get("new_state") == "off":
            self.turn_off("input_boolean.alarm_level")
            self.call_service("timer/cancel", entity_id="timer.alarm_reset")

    def auto_reset(self, event_name, data, kwargs):
        if self.get_state("input_boolean.alarm_level") == "on":
            self.turn_off("input_boolean.alarm_level")
