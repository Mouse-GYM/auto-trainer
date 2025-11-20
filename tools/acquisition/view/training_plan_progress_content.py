from typing import Optional, List, Dict, Any, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget, QStackedWidget, QSizePolicy, QScrollArea, \
    QHBoxLayout, QFormLayout

from autotrainer.core.logging import get_verbose_logger

from autotrainer.pyside import CardWidget
from autotrainer.training import TrainingPlan


logger = get_verbose_logger(__name__)


def make_unit_label(txt, *, background_color="lightblue"):
    label = QLabel(txt)
    label.setStyleSheet(f"background-color: {background_color}")
    return label


class TrainingPlanProgressContent(CardWidget):

    phase_desc_truncate_length = 92

    def __init__(self):
        super().__init__(title="Protocol Progress")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._plan_card_by_plan_id: Dict[str, Tuple[CardWidget, QScrollArea]] = {}
        self._plans_by_plan_id: Dict[str, TrainingPlan] = {}
        self._phases_by_plan_id: Dict[str, List[QWidget]] = {}

        main_content = QWidget()
        # main_content.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setContentWidget(main_content)

        main_layout = QHBoxLayout(main_content)
        main_layout.setSpacing(6)

        r = c = 0
        left = QGridLayout()
        left.addWidget(QLabel("Started"), r, c)
        label = self._started_label = QLabel("")
        left.addWidget(label, r, c + 1)
        r += 1
        left.addWidget(QLabel("Time in Training"), r, c)
        label = self._time_in_training_label = QLabel("")
        hbox = QHBoxLayout()
        hbox.addWidget(label)
        hbox.addWidget(make_unit_label("hr"))
        left.addLayout(hbox, r, c + 1)
        r += 1
        left.addWidget(QLabel("Sessions"), r, c)
        label = self._sessions_label = QLabel("")
        left.addWidget(label, r, c + 1)

        r = c = 0
        right = QGridLayout()
        right.addWidget(QLabel("Pellets Presented"), r, c)
        label = self._pellets_presented_label = QLabel("")
        right.addWidget(label, r, c + 1)
        r += 1
        right.addWidget(QLabel("Pellets Consumed"), r, c)
        label = self._pellets_consumed_label = QLabel("")
        right.addWidget(label, r, c + 1)
        r += 1
        right.addWidget(QLabel("Reaches"), r, c)
        label = self._pellets_reaches_label = QLabel("")
        right.addWidget(label, r, c + 1)

        border_with_padding_style = f"""QLabel {{
            border: 1px solid gray;
            padding: 4px;
        }}"""

        main_content.setStyleSheet(border_with_padding_style)

        for side in (left, right):
            assert isinstance(side, QGridLayout)
            side.setContentsMargins(0, 0, 0, 0)
            side.setVerticalSpacing(0)
            side.setHorizontalSpacing(0)
            side.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            for row in range(side.rowCount()):
                item = side.itemAtPosition(row, 0)
                label = item.widget()
                label.setContentsMargins(0, 0, 0, 0)
                label.setStyleSheet(f"{label.styleSheet()}; background-color: lightgray;")
                font = label.font()
                font.setBold(True)
                label.setFont(font)  # do not forget !
            side_widget = QWidget()
            side_widget.setLayout(side)
            main_layout.addWidget(side_widget)

    def set_training_plan_progress(self, plan: Optional[TrainingPlan]):
        logger.verbose("Setting training plan to %s", plan)
        if plan is None:
            for label in (
                self._started_label,
                self._time_in_training_label,
                self._sessions_label,
                self._pellets_presented_label,
                self._pellets_consumed_label,
                self._pellets_reaches_label,
            ):
                label.setText("")
            return
        value = plan.training_start_timestamp
        self._started_label.setText(
            "NA" if value is None
            else f"{value.strftime('%Y/%m/%d %I:%M %p')}"
        )
        self._time_in_training_label.setText(f"{plan.total_time:.1f}")
        for label, value in (
            (self._sessions_label, plan.total_session_count),
            (self._pellets_presented_label, plan.total_pellets_presented),
            (self._pellets_consumed_label, plan.total_pellets_consumed),
            (self._pellets_reaches_label, plan.total_successful_reaches),
        ):
            label.setText(f"{value}")

