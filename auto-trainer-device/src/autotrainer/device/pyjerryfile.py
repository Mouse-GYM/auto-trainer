class JerryCAN:
    def __init__(self):
        pass

class JerryCANCmdType:

    LOAD_CELL_READ = 0
    STATUS = 1
    PRESSURE_READ = 2
    STEPPER_STATUS = 3
    TEMP_HUM_READ = 4
    GPIO_READ = 5
    SERVO_STATUS = 6
    CFG_RESPONSE = 7

    def __init__(self):
        pass

class JerryStepperStatus:
    motor_id: int
    position: float
    status: int
    homing_status: int
    limit_switch: int

class JerryServoStatus:
    motor_id: int
    position: float
    status: int

class JerryCANMsg:
    dst_id: int
    type: int

    stepper_status: JerryStepperStatus
    servo_status: JerryServoStatus

    @classmethod
    def stepper_message(cls, motor_id: int, position: float, status: int = 0, homing_status: int = 0, limit_switch: int = 0):
        msg = JerryCANMsg()
        msg.dst_id = 1
        msg.type = JerryCANCmdType.STEPPER_STATUS
        msg.stepper_status = JerryStepperStatus()
        msg.stepper_status.motor_id = motor_id
        msg.stepper_status.position = position
        msg.stepper_status.status = status
        msg.stepper_status.homing_status = homing_status
        msg.stepper_status.limit_switch = limit_switch

        return msg

    @classmethod
    def servo_message(cls, dst_id: int,  motor_id: int, position: float, status: int = 0):
        msg = JerryCANMsg()
        msg.dst_id = dst_id
        msg.type = JerryCANCmdType.SERVO_STATUS
        msg.servo_status = JerryServoStatus()
        msg.servo_status.motor_id = motor_id
        msg.servo_status.position = position
        msg.servo_status.status = status

        return msg

    def __init__(self):
        pass

class JerryCANCfgMsg:
    def __init__(self):
        pass