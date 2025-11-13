from typing import Optional, List, Dict, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget, QStackedWidget, QSizePolicy, QScrollArea

from autotrainer.core.logging import get_verbose_logger

from autotrainer.pyside import CardWidget
from autotrainer.pyside.StackedWidget import StackedWidget

from autotrainer.training import TrainingPlan


logger = get_verbose_logger(__name__)


class TrainingPlanContent(StackedWidget):

    def __init__(self):
        super().__init__()
        self._plan_card_by_plan_id: Dict[str, QWidget] = {}
        self._plans_by_plan_id: Dict[str, TrainingPlan] = {}
        self._phases_by_plan_id: Dict[str, List[QWidget]] = {}
        card = self._empty_card = self._card = CardWidget(title="Protocol")
        self.addWidget(card)

    def set_training_plan(self, plan: Optional[TrainingPlan]):
        logger.verbose("Setting training plan to %s", plan)
        if plan is None:
            self.setCurrentWidget(self._empty_card)
            return

        prev = self._plan_card_by_plan_id.get(plan.plan_id)
        if prev is not None:
            logger.debug("Using cache for plan to %s", plan)
            self.setCurrentWidget(prev)
            return

        logger.debug("Adding new plan %s with %s phases", plan.plan_id, len(plan.phases))

        card = CardWidget(title="Protocol")
        card.header.setRightContent(None if plan is None else QLabel(plan.name))
        card.setContentsMargins(0, 0, 0, 0)
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        scroll_area = QScrollArea()
        scroll_area.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll_area.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.MinimumExpanding)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setWidgetResizable(True)

        card.setContentWidget(scroll_area)

        grid_widget = QWidget()
        grid_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)  # trying remove/shorten the top margin but doesn't work?
        grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        scroll_area.setWidget(grid_widget)

        cur_col = cur_row = 0
        right_max_cols = (
            3 if len(plan.phases) > 6
            else 2 if len(plan.phases) > 3
            else 1
        )
        phase_widgets = self._phases_by_plan_id[plan.plan_id] = []
        for phase_nr, phase in enumerate(plan.phases, start=1):
            widget = QWidget()
            widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
            widget.setContentsMargins(0, 0, 0, 0)
            phase_widget_name = f"plan-{plan.plan_id}-{phase.phase_id}"
            widget.setObjectName(phase_widget_name)
            is_current = plan.current_phase == phase
            phase_widgets.append(widget)
            layout = QVBoxLayout(widget)
            layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            grid.addWidget(widget, cur_row, cur_col)
            label_head = QLabel(f"{phase_nr}. {phase.name}")
            layout.addWidget(label_head)
            label = QLabel(phase.description)
            label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.MinimumExpanding)
            label.setWordWrap(True)
            layout.addWidget(label)
            if is_current:
                label_head.setStyleSheet("color: green; font-weight: bold;")
                widget.setStyleSheet(f"""
                    #{phase_widget_name} {{
                    border: 1px solid gray; /* Sets the contour/border */
                    border-radius: 10px; /* Optional: rounds the corners */
                    background-color: lightgray; /* Optional: sets background color */
                    /* padding: 2px; */ /* Optional: adds space inside the border */
                    }}
                    """)
            cur_col += 1
            if cur_col >= right_max_cols:
                cur_row += 1
                cur_col = 0

        self.addWidget(card)
        self._plan_card_by_plan_id[plan.plan_id] = card
        self.setCurrentWidget(card)
