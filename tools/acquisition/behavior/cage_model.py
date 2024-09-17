from statemachine import StateMachine, State


class CageModel(StateMachine):
    idle = State(initial=True)
    detecting = State()
    analyzing = State()
    missing = State()

    entered_tunnel = (
            idle.to(missing) |
            detecting.to(idle) |
            analyzing.to.itself() |
            missing.to(idle)
    )

    exited_tunnel = (
            missing.to(detecting, unless="is_analyzing") |
            analyzing.to.itself(cond="is_analyzing")
    )

    detection_started = (
            idle.to(detecting) |
            missing.to(detecting)
    )

    detection_complete = (
            detecting.to(idle)
    )

    analysis_started = (
            idle.to(analyzing) |
            detecting.to(analyzing) |
            missing.to(analyzing)
    )

    analysis_complete = (
            analyzing.to(idle, cond="mouse_present") |
            analyzing.to(missing, unless="mouse_present")
    )

    def after_entered_tunnel(self):
        self.set_mouse_present(False)

    def after_detection_complete(self):
        self.set_mouse_present(True)

    def __init__(self):
        super(CageModel, self).__init__(allow_event_without_transition=True)

        self._mouse_present = True
        self._is_analyzing = False

        self.properties = Events(("property_changed",))

    def mouse_present(self):
        return self._mouse_present

    def set_mouse_present(self, value: bool):
        if self._mouse_present == value:
            return

        self._mouse_present = value

        self.properties.property_changed("mouse_present", value, not value)

    def is_analyzing(self):
        return self._is_analyzing

